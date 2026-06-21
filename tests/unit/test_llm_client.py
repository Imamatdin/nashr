"""Behaviour tests for :class:`LLMClient` and :class:`LLMResponse`.

The Anthropic SDK is the only thing we mock at this layer (per the
testing rules: external LLM APIs may be stubbed). We verify the
behaviours that the rest of the system relies on:

* Cost is computed from the token counts using the right per-model rate,
  including the prompt-caching read / write buckets.
* The system prompt is sent plain by default and as a cache-controlled
  block when caching is opted in.
* Retry kicks in for transient errors (``RateLimitError`` /
  ``APIError``) and the first successful response is returned.
* ``AuthenticationError`` is *not* swallowed — a misconfigured key must
  surface immediately, not after two backoff sleeps.

We do not exercise real network calls; that's an integration concern.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
import pytest
from anthropic import APIError, AuthenticationError, RateLimitError
from anthropic.types import CacheCreation, Message, TextBlock, Usage
from pydantic import ValidationError

from packages.core.llm import (
    DEFAULT_HAIKU_MODEL,
    HAIKU_INPUT_COST_PER_MTOK,
    HAIKU_OUTPUT_COST_PER_MTOK,
    OPUS_INPUT_COST_PER_MTOK,
    OPUS_OUTPUT_COST_PER_MTOK,
    SONNET_INPUT_COST_PER_MTOK,
    SONNET_OUTPUT_COST_PER_MTOK,
    LLMClient,
    LLMResponse,
)


def _make_message(
    text: str,
    input_tokens: int = 100,
    output_tokens: int = 50,
    cache_read: int = 0,
    cache_write_5m: int = 0,
    cache_write_1h: int = 0,
) -> Message:
    creation = (
        CacheCreation(
            ephemeral_5m_input_tokens=cache_write_5m,
            ephemeral_1h_input_tokens=cache_write_1h,
        )
        if (cache_write_5m or cache_write_1h)
        else None
    )
    return Message(
        id="msg_test",
        type="message",
        role="assistant",
        model=DEFAULT_HAIKU_MODEL,
        content=[TextBlock(type="text", text=text, citations=None)],
        stop_reason="end_turn",
        stop_sequence=None,
        usage=Usage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_input_tokens=cache_read,
            cache_creation_input_tokens=cache_write_5m + cache_write_1h,
            cache_creation=creation,
        ),
    )


class _FakeMessages:
    def __init__(self, behaviour: Callable[[], Awaitable[Message]]) -> None:
        self._behaviour = behaviour
        self.calls = 0
        self.last_kwargs: dict[str, Any] = {}

    async def create(self, **kwargs: Any) -> Message:
        self.calls += 1
        self.last_kwargs = kwargs
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


def test_cost_for_routes_opus_to_opus_rates_not_haiku() -> None:
    # Regression guard: substring routing used to send every non-sonnet model through to
    # Haiku, silently under-costing Opus. Opus must price at Opus rates and exceed the Haiku
    # fallback for identical token counts.
    cost = LLMResponse.cost_for("claude-opus-4-8", input_tokens=1_000_000, output_tokens=1_000_000)
    expected = OPUS_INPUT_COST_PER_MTOK + OPUS_OUTPUT_COST_PER_MTOK
    assert cost == pytest.approx(expected)
    haiku = LLMResponse.cost_for(DEFAULT_HAIKU_MODEL, 1_000_000, 1_000_000)
    assert cost > haiku


def test_cost_for_prices_each_cache_bucket() -> None:
    cost = LLMResponse.cost_for(
        "claude-sonnet-4-6",
        input_tokens=1_000_000,
        output_tokens=1_000_000,
        cache_read_input_tokens=1_000_000,
        cache_write_5m_input_tokens=1_000_000,
        cache_write_1h_input_tokens=1_000_000,
    )
    expected = (
        SONNET_INPUT_COST_PER_MTOK  # uncached input
        + SONNET_INPUT_COST_PER_MTOK * 0.10  # cache read
        + SONNET_INPUT_COST_PER_MTOK * 1.25  # 5-minute cache write
        + SONNET_INPUT_COST_PER_MTOK * 2.00  # 1-hour cache write
        + SONNET_OUTPUT_COST_PER_MTOK  # output
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
async def test_complete_without_cache_sends_plain_string_system() -> None:
    async def behaviour() -> Message:
        return _make_message("ok")

    fake = _FakeAsyncAnthropic(behaviour)
    client = LLMClient(client=fake)  # type: ignore[arg-type]

    await client.complete(system="rules", user="task")  # cache defaults to False

    assert fake.messages.last_kwargs["system"] == "rules"


@pytest.mark.asyncio
async def test_complete_with_cache_sends_cache_control_system_block() -> None:
    async def behaviour() -> Message:
        return _make_message("ok")

    fake = _FakeAsyncAnthropic(behaviour)
    client = LLMClient(client=fake)  # type: ignore[arg-type]

    await client.complete(system="rules", user="task", cache="1h")

    system_arg = fake.messages.last_kwargs["system"]
    assert isinstance(system_arg, list)
    assert len(system_arg) == 1
    block = system_arg[0]
    assert block["type"] == "text"
    assert block["text"] == "rules"
    assert block["cache_control"] == {"type": "ephemeral", "ttl": "1h"}


@pytest.mark.asyncio
async def test_complete_surfaces_cache_tokens_and_prices_them() -> None:
    async def behaviour() -> Message:
        return _make_message(
            "cached",
            input_tokens=10,
            output_tokens=20,
            cache_read=900,
            cache_write_5m=100,
        )

    fake = _FakeAsyncAnthropic(behaviour)
    client = LLMClient(client=fake)  # type: ignore[arg-type]

    response = await client.complete(
        system="rules", user="task", model="claude-sonnet-4-6", cache="5m"
    )

    assert response.cache_read_input_tokens == 900
    assert response.cache_creation_input_tokens == 100
    assert response.total_prompt_tokens == 10 + 900 + 100

    base_in = SONNET_INPUT_COST_PER_MTOK / 1_000_000.0
    expected = (
        10 * base_in
        + 900 * base_in * 0.10
        + 100 * base_in * 1.25
        + 20 * (SONNET_OUTPUT_COST_PER_MTOK / 1_000_000.0)
    )
    assert response.estimated_cost_usd == pytest.approx(expected)
    # total_prompt_tokens is a derived property, not a serialised field — round-trip is lossless.
    assert LLMResponse(**response.model_dump()) == response


@pytest.mark.asyncio
async def test_llm_call_complete_logs_cache_fields(caplog: pytest.LogCaptureFixture) -> None:
    async def behaviour() -> Message:
        return _make_message("x", input_tokens=5, output_tokens=5, cache_read=50, cache_write_5m=10)

    fake = _FakeAsyncAnthropic(behaviour)
    client = LLMClient(client=fake)  # type: ignore[arg-type]

    caplog.set_level(logging.INFO, logger="packages.core.llm")
    await client.complete(system="rules", user="task", cache="5m")

    records = [r for r in caplog.records if r.message == "llm_call_complete"]
    assert len(records) == 1
    record = records[0]
    assert record.cache_read_input_tokens == 50
    assert record.cache_creation_input_tokens == 10
    assert record.total_prompt_tokens == 5 + 50 + 10


@pytest.mark.asyncio
async def test_complete_per_call_timeout_overrides_client_default() -> None:
    # The per-call timeout is the seam the editorial executor uses to give its
    # 16k-token generation a longer ceiling than the small planner/classifier
    # calls. A short per-call timeout must fire even when the client default is
    # long — proving the override reaches the asyncio.wait_for, not just the
    # constructor default.
    async def slow() -> Message:
        await asyncio.sleep(3)
        return _make_message("never reached")

    fake = _FakeAsyncAnthropic(slow)
    client = LLMClient(client=fake, timeout_seconds=180, max_retries=0)  # type: ignore[arg-type]

    with pytest.raises(TimeoutError):
        await client.complete(system="sys", user="usr", timeout=1)


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
