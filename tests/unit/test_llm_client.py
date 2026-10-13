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
import json
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
    LLMClient,
    LLMResponse,
    build_default_anthropic_client,
    resolve_llm_transport,
)
from packages.core.model_registry import UnknownModelError

# Published list prices (USD per MTok), platform.claude.com pricing, 2026-10-13.
HAIKU_IN, HAIKU_OUT = 0.10, 0.50
SONNET_IN, SONNET_OUT = 2.0, 10.0
SONNET = "claude-sonnet-5-5"


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


def test_default_claude_model_is_haiku_5_5() -> None:
    assert DEFAULT_HAIKU_MODEL == "claude-haiku-5-5"


def test_llm_response_cost_calculation_haiku() -> None:
    # Under the 100k-token prompt threshold: the base $0.10 / $0.50 tier.
    cost = LLMResponse.cost_for(DEFAULT_HAIKU_MODEL, input_tokens=100_000, output_tokens=200_000)
    assert cost == pytest.approx(0.1 * HAIKU_IN + 0.2 * HAIKU_OUT)


def test_haiku_prompt_over_100k_tokens_bills_the_long_context_tier() -> None:
    # Haiku 5.5: prompts over 100k tokens bill $0.50 / $2.50, cache reads $0.05.
    cost = LLMResponse.cost_for(
        DEFAULT_HAIKU_MODEL,
        input_tokens=100_000,
        output_tokens=1_000_000,
        cache_read_input_tokens=1_000_000,
    )
    assert cost == pytest.approx(0.1 * 0.50 + 2.50 + 0.05)


def test_llm_response_cost_calculation_sonnet() -> None:
    cost = LLMResponse.cost_for(SONNET, input_tokens=500_000, output_tokens=100_000)
    assert cost == pytest.approx(0.5 * SONNET_IN + 0.1 * SONNET_OUT)


@pytest.mark.parametrize(
    "model",
    [
        "claude-opus-4-8",
        "claude-haiku-4-5-20251001",
        "claude-sonnet-4-6",
        "claude-sonnet-4-6-20250514",
    ],
)
def test_cost_for_refuses_unregistered_claude_models(model: str) -> None:
    # The old substring routing priced any unknown string as Haiku; an unregistered id
    # now raises (LLMClient refuses it before sending, so no finished call hits this).
    with pytest.raises(UnknownModelError):
        LLMResponse.cost_for(model, input_tokens=1, output_tokens=1)


def test_cost_for_prices_each_cache_bucket_at_its_published_rate() -> None:
    # Sonnet 5.5: cache read $0.10, 5-minute write $2.50, 1-hour write $4.00.
    cost = LLMResponse.cost_for(
        SONNET,
        input_tokens=1_000_000,
        output_tokens=1_000_000,
        cache_read_input_tokens=1_000_000,
        cache_write_5m_input_tokens=1_000_000,
        cache_write_1h_input_tokens=1_000_000,
    )
    assert cost == pytest.approx(SONNET_IN + 0.10 + 2.50 + 4.00 + SONNET_OUT)


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
    expected_cost = 200 / 1_000_000 * HAIKU_IN + 400 / 1_000_000 * HAIKU_OUT
    assert response.estimated_cost_usd == pytest.approx(expected_cost)
    assert fake.messages.calls == 1


@pytest.mark.asyncio
async def test_complete_sends_no_temperature_and_pins_thinking_per_model() -> None:
    # Claude 4.7+ answers a non-default temperature with a 400, and the 5.5 models
    # think by default (thinking tokens spend max_tokens), so each request carries
    # the registry's thinking mode and never a sampling parameter.
    async def behaviour() -> Message:
        return _make_message("ok")

    fake = _FakeAsyncAnthropic(behaviour)
    client = LLMClient(client=fake)  # type: ignore[arg-type]

    await client.complete(system="sys", user="usr")
    haiku_kwargs = fake.messages.last_kwargs
    await client.complete(system="sys", user="usr", model=SONNET)
    sonnet_kwargs = fake.messages.last_kwargs

    for kwargs in (haiku_kwargs, sonnet_kwargs):
        assert not {"temperature", "top_p", "top_k"} & set(kwargs)
        assert "thinking" not in kwargs  # sent as a body field, see below
    assert haiku_kwargs["extra_body"] == {"thinking": {"type": "disabled"}}
    assert sonnet_kwargs["extra_body"] == {"thinking": {"type": "between_tools"}}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "model",
    [
        "claude-haiku-4-5-20251001",
        "claude-sonnet-4-6-20250514",
        "claude-opus-4-8",
        "gemini-3.8-flash",
    ],
)
async def test_complete_refuses_unregistered_or_non_claude_model_before_sending(
    model: str,
) -> None:
    async def behaviour() -> Message:
        return _make_message("never")

    fake = _FakeAsyncAnthropic(behaviour)
    client = LLMClient(client=fake)  # type: ignore[arg-type]

    with pytest.raises(UnknownModelError):
        await client.complete(system="sys", user="usr", model=model)
    assert fake.messages.calls == 0


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

    response = await client.complete(system="rules", user="task", model=SONNET, cache="5m")

    assert response.cache_read_input_tokens == 900
    assert response.cache_creation_input_tokens == 100
    assert response.total_prompt_tokens == 10 + 900 + 100

    expected = (10 * SONNET_IN + 900 * 0.10 + 100 * 2.50 + 20 * SONNET_OUT) / 1_000_000.0
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

    records = [r for r in caplog.records if r.getMessage().startswith("llm_call_complete ")]
    assert len(records) == 1
    payload = json.loads(records[0].getMessage().removeprefix("llm_call_complete "))
    assert payload["cache_read_input_tokens"] == 50
    assert payload["cache_creation_input_tokens"] == 10
    assert payload["total_prompt_tokens"] == 5 + 50 + 10


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


def test_resolve_llm_transport_defaults_to_vertex(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LLM_TRANSPORT", raising=False)
    assert resolve_llm_transport() == "vertex"


def test_resolve_llm_transport_rejects_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_TRANSPORT", "openai")
    with pytest.raises(ValueError, match="LLM_TRANSPORT"):
        resolve_llm_transport()


def test_build_default_client_uses_vertex(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_TRANSPORT", "vertex")
    monkeypatch.setenv("VERTEX_PROJECT", "nashr-prod")
    monkeypatch.setenv("VERTEX_LOCATION", "global")
    created: list[dict[str, str]] = []

    class _FakeVertex:
        def __init__(self, *, project_id: str, region: str) -> None:
            created.append({"project_id": project_id, "region": region})

    monkeypatch.setattr("packages.core.llm.AsyncAnthropicVertex", _FakeVertex)
    build_default_anthropic_client()
    assert created == [{"project_id": "nashr-prod", "region": "global"}]


def test_build_default_client_requires_vertex_project(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_TRANSPORT", "vertex")
    monkeypatch.delenv("VERTEX_PROJECT", raising=False)
    monkeypatch.delenv("ANTHROPIC_VERTEX_PROJECT_ID", raising=False)
    with pytest.raises(RuntimeError, match="VERTEX_PROJECT"):
        build_default_anthropic_client()


def test_build_default_client_uses_anthropic_api(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_TRANSPORT", "anthropic")
    created: list[object] = []

    class _FakeAnthropic:
        def __init__(self) -> None:
            created.append(self)

    monkeypatch.setattr("packages.core.llm.AsyncAnthropic", _FakeAnthropic)
    build_default_anthropic_client()
    assert len(created) == 1


def test_llm_client_freezes_transport_at_construction(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_TRANSPORT", "vertex")
    monkeypatch.setenv("VERTEX_PROJECT", "nashr-prod")
    monkeypatch.setenv("VERTEX_LOCATION", "global")

    class _FakeVertex:
        def __init__(self, *, project_id: str, region: str) -> None:
            self.project_id = project_id
            self.region = region

    monkeypatch.setattr("packages.core.llm.AsyncAnthropicVertex", _FakeVertex)
    client = LLMClient()
    assert client.transport == "vertex"
    monkeypatch.setenv("LLM_TRANSPORT", "anthropic")
    assert client.transport == "vertex"


@pytest.mark.asyncio
async def test_bare_construction_is_safe_without_vertex_env_but_first_call_fails_fast(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Regression (Codex HIGH / drafter-suite breakage): SectionDrafter() and other
    # construct-but-may-never-call paths must not crash on a box without Vertex env.
    # The SDK client builds lazily; the first real call still fails with the
    # explicit VERTEX_PROJECT message.
    monkeypatch.delenv("LLM_TRANSPORT", raising=False)
    monkeypatch.delenv("VERTEX_PROJECT", raising=False)
    monkeypatch.delenv("ANTHROPIC_VERTEX_PROJECT_ID", raising=False)
    client = LLMClient()  # must not raise
    assert client.transport == "vertex"
    with pytest.raises(RuntimeError, match="VERTEX_PROJECT"):
        await client.complete(system="sys", user="usr")


@pytest.mark.asyncio
async def test_complete_sends_the_same_id_on_vertex_transport() -> None:
    # Claude 4.6+ ids are identical on the Claude API and Vertex; the old
    # "@date" translation existed only for Haiku 4.5.
    async def behaviour() -> Message:
        return _make_message("ok")

    fake = _FakeAsyncAnthropic(behaviour)
    client = LLMClient(client=fake, transport="vertex")  # type: ignore[arg-type]
    response = await client.complete(system="sys", user="usr")
    assert fake.messages.last_kwargs["model"] == "claude-haiku-5-5"
    assert response.model == "claude-haiku-5-5"


@pytest.mark.asyncio
@pytest.mark.parametrize("region", ["global", "us", "eu"])
async def test_complete_accepts_vertex_locations_that_serve_claude_5(region: str) -> None:
    async def behaviour() -> Message:
        return _make_message("ok")

    fake = _FakeAsyncAnthropic(behaviour)
    fake.region = region  # type: ignore[attr-defined]
    client = LLMClient(client=fake, transport="vertex")  # type: ignore[arg-type]
    await client.complete(system="sys", user="usr", model=SONNET)
    assert fake.messages.calls == 1


@pytest.mark.asyncio
async def test_complete_refuses_a_single_vertex_region_before_sending() -> None:
    # Single-region Vertex endpoints serve only Sonnet 4.6 and earlier.
    async def behaviour() -> Message:
        return _make_message("never")

    fake = _FakeAsyncAnthropic(behaviour)
    fake.region = "us-east5"  # type: ignore[attr-defined]
    client = LLMClient(client=fake, transport="vertex")  # type: ignore[arg-type]
    with pytest.raises(UnknownModelError, match="us-east5"):
        await client.complete(system="sys", user="usr")
    assert fake.messages.calls == 0


@pytest.mark.asyncio
async def test_complete_leaves_model_untouched_on_injected_transport() -> None:
    async def behaviour() -> Message:
        return _make_message("ok")

    fake = _FakeAsyncAnthropic(behaviour)
    client = LLMClient(client=fake)  # type: ignore[arg-type]
    assert client.transport == "injected"
    await client.complete(system="sys", user="usr")
    assert fake.messages.last_kwargs["model"] == DEFAULT_HAIKU_MODEL


@pytest.mark.asyncio
async def test_complete_propagates_unexpected_exception_without_retry() -> None:
    # A non-Anthropic failure (e.g. google-auth DefaultCredentialsError under the
    # vertex transport) must surface immediately — not be retried as transient.
    calls = 0

    async def behaviour() -> Message:
        nonlocal calls
        calls += 1
        raise RuntimeError("ADC misconfigured")

    fake = _FakeAsyncAnthropic(behaviour)
    client = LLMClient(client=fake, transport="vertex")  # type: ignore[arg-type]
    with pytest.raises(RuntimeError, match="ADC misconfigured"):
        await client.complete(system="sys", user="usr")
    assert calls == 1
