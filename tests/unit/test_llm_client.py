"""Behaviour tests for :class:`LLMClient` and :class:`LLMResponse`.

The Anthropic SDK is the only thing we mock at this layer (per the
testing rules: external LLM APIs may be stubbed). We verify the
behaviours that the rest of the system relies on:

* Cost is computed from the token counts using the right per-model rate.
* Retry kicks in for transient errors (``RateLimitError`` /
  ``APIError``) and the first successful response is returned.
* ``AuthenticationError`` is *not* swallowed — a misconfigured key must
  surface immediately, not after two backoff sleeps.

We do not exercise real network calls; that's an integration concern.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import httpx
import pytest
from anthropic import APIError, AuthenticationError, RateLimitError
from anthropic.types import Message, TextBlock, Usage
from pydantic import ValidationError

from packages.core.llm import (
    DEFAULT_HAIKU_MODEL,
    HAIKU_INPUT_COST_PER_MTOK,
    HAIKU_OUTPUT_COST_PER_MTOK,
    SONNET_INPUT_COST_PER_MTOK,
    SONNET_OUTPUT_COST_PER_MTOK,
    LLMClient,
    LLMResponse,
)


def _make_message(text: str, input_tokens: int = 100, output_tokens: int = 50) -> Message:
    return Message(
        id="msg_test",
        type="message",
        role="assistant",
        model=DEFAULT_HAIKU_MODEL,
        content=[TextBlock(type="text", text=text, citations=None)],
        stop_reason="end_turn",
        stop_sequence=None,
        usage=Usage(input_tokens=input_tokens, output_tokens=output_tokens),
    )


class _FakeMessages:
    def __init__(self, behaviour: Callable[[], Awaitable[Message]]) -> None:
        self._behaviour = behaviour
        self.calls = 0

    async def create(self, **_kwargs: Any) -> Message:
        self.calls += 1
        return await self._behaviour()


class _FakeAsyncAnthropic:
    def __init__(self, behaviour: Callable[[], Awaitable[Message]]) -> None:
        self.messages = _FakeMessages(behaviour)


def _make_api_error() -> APIError:
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return APIError(message="boom", request=request, body=None)


def _make_rate_limit_error() -> RateLimitError:
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx.Response(status_code=429, request=request)
    return RateLimitError(message="slow down", response=response, body=None)


def _make_auth_error() -> AuthenticationError:
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx.Response(status_code=401, request=request)
    return AuthenticationError(message="bad key", response=response, body=None)


def test_llm_response_cost_calculation_haiku() -> None:
    cost = LLMResponse.cost_for(
        DEFAULT_HAIKU_MODEL, input_tokens=1_000_000, output_tokens=2_000_000
    )
    expected = HAIKU_INPUT_COST_PER_MTOK + 2 * HAIKU_OUTPUT_COST_PER_MTOK
    assert cost == pytest.approx(expected)


def test_llm_response_cost_calculation_sonnet() -> None:
    cost = LLMResponse.cost_for("claude-sonnet-4-6", input_tokens=500_000, output_tokens=100_000)
    expected = (
        500_000 / 1_000_000 * SONNET_INPUT_COST_PER_MTOK
        + 100_000 / 1_000_000 * SONNET_OUTPUT_COST_PER_MTOK
    )
    assert cost == pytest.approx(expected)


def test_llm_response_model_validation_accepts_zero_latency() -> None:
    response = LLMResponse(
        content="ok",
        model=DEFAULT_HAIKU_MODEL,
        input_tokens=10,
        output_tokens=5,
        latency_ms=0,
        estimated_cost_usd=0.0,
    )
    assert response.latency_ms == 0


def test_llm_response_rejects_negative_tokens() -> None:
    with pytest.raises(ValidationError):
        LLMResponse(
            content="ok",
            model=DEFAULT_HAIKU_MODEL,
            input_tokens=-1,
            output_tokens=5,
            latency_ms=10,
            estimated_cost_usd=0.0,
        )


@pytest.mark.asyncio
async def test_llm_client_returns_text_and_cost() -> None:
    async def behaviour() -> Message:
        return _make_message("hello world", input_tokens=200, output_tokens=400)

    fake = _FakeAsyncAnthropic(behaviour)
    client = LLMClient(client=fake)  # type: ignore[arg-type]

    response = await client.complete(system="sys", user="usr")

    assert response.content == "hello world"
    assert response.input_tokens == 200
    assert response.output_tokens == 400
    expected_cost = (
        200 / 1_000_000 * HAIKU_INPUT_COST_PER_MTOK + 400 / 1_000_000 * HAIKU_OUTPUT_COST_PER_MTOK
    )
    assert response.estimated_cost_usd == pytest.approx(expected_cost)
    assert fake.messages.calls == 1


@pytest.mark.asyncio
async def test_llm_client_retries_on_rate_limit_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = {"count": 0}

    async def behaviour() -> Message:
        state["count"] += 1
        if state["count"] == 1:
            raise _make_rate_limit_error()
        return _make_message("recovered", input_tokens=10, output_tokens=10)

    async def no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr("packages.core.llm.asyncio.sleep", no_sleep)

    fake = _FakeAsyncAnthropic(behaviour)
    client = LLMClient(client=fake)  # type: ignore[arg-type]

    response = await client.complete(system="sys", user="usr")

    assert response.content == "recovered"
    assert fake.messages.calls == 2


@pytest.mark.asyncio
async def test_llm_client_gives_up_after_max_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def behaviour() -> Message:
        raise _make_api_error()

    async def no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr("packages.core.llm.asyncio.sleep", no_sleep)

    fake = _FakeAsyncAnthropic(behaviour)
    client = LLMClient(client=fake, max_retries=2)  # type: ignore[arg-type]

    with pytest.raises(APIError):
        await client.complete(system="sys", user="usr")

    assert fake.messages.calls == 3  # initial call + 2 retries


@pytest.mark.asyncio
async def test_llm_client_does_not_swallow_authentication_error() -> None:
    async def behaviour() -> Message:
        raise _make_auth_error()

    fake = _FakeAsyncAnthropic(behaviour)
    client = LLMClient(client=fake)  # type: ignore[arg-type]

    with pytest.raises(AuthenticationError):
        await client.complete(system="sys", user="usr")

    assert fake.messages.calls == 1
