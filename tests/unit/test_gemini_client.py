"""Behaviour tests for :class:`GeminiClient` and Gemini cost helpers.

The Google ``google-genai`` SDK is the only thing we mock at this layer
(per the testing rules: external LLM APIs may be stubbed). We assert
the contract that the rest of the system relies on:

* Cost is computed from the token counts using the right per-model rate.
* Retry kicks in for transient errors (HTTP 429 / 503) and the first
  successful response is returned.
* Auth errors (HTTP 401 / 403) propagate immediately — a misconfigured
  key is a configuration fault, not transient.
* When ``GOOGLE_API_KEY`` is unset and no generate-content fn is
  injected, initialization fails with a clear error instead of failing
  later on a confusing API call.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from google.genai import errors as genai_errors
from google.genai import types as genai_types
from pydantic import ValidationError

from packages.core.gemini import (
    GEMINI_COSTS,
    GEMINI_FLASH_3_5_MODEL,
    GEMINI_FLASH_INPUT_COST_PER_MTOK,
    GEMINI_FLASH_LITE_INPUT_COST_PER_MTOK,
    GEMINI_FLASH_LITE_OUTPUT_COST_PER_MTOK,
    GEMINI_FLASH_MODEL,
    GEMINI_FLASH_OUTPUT_COST_PER_MTOK,
    GEMINI_PRO_3_1_MODEL,
    GEMINI_PRO_INPUT_COST_PER_MTOK,
    GEMINI_PRO_OUTPUT_COST_PER_MTOK,
    GeminiClient,
    GeminiToolCallError,
    _extract_usage,
    gemini_cost_for,
)
from packages.core.llm import LLMResponse


class _FakeUsage:
    def __init__(self, prompt: int, candidates: int) -> None:
        self.prompt_token_count = prompt
        self.candidates_token_count = candidates


class _FakeUsageCached:
    """Usage metadata that carries ``cached_content_token_count`` (int or None).

    ``_FakeUsage`` omits the attribute entirely (the absent path); this stub sets
    it explicitly so tests exercise the present-int and present-None branches of
    :func:`_extract_usage`.
    """

    def __init__(self, prompt: int, candidates: int, cached: int | None) -> None:
        self.prompt_token_count = prompt
        self.candidates_token_count = candidates
        self.cached_content_token_count = cached


class _UsageResponse:
    """Minimal response satisfying ``_GenerateContentResponseLike`` for usage tests.

    ``_extract_usage`` reads only ``usage_metadata``; the other protocol members
    are ``None`` so the stub still structurally matches the protocol (whose
    docstring permits plain attributes) and pyright accepts it as the argument.
    """

    def __init__(self, usage: object | None) -> None:
        self.text: str | None = None
        self.usage_metadata: object | None = usage
        self.candidates: list[genai_types.Candidate] | None = None
        self.function_calls: list[genai_types.FunctionCall] | None = None


class _FakeResponse:
    def __init__(
        self,
        text: str,
        prompt_tokens: int,
        candidate_tokens: int,
        cached_tokens: int | None = None,
    ) -> None:
        self.text: str | None = text
        self.usage_metadata: object | None = (
            _FakeUsage(prompt_tokens, candidate_tokens)
            if cached_tokens is None
            else _FakeUsageCached(prompt_tokens, candidate_tokens, cached_tokens)
        )


def _make_fn(
    behaviour: Callable[[], Awaitable[_FakeResponse]],
) -> tuple[Callable[..., Awaitable[Any]], list[dict[str, Any]]]:
    """Build a `generate_content_fn` that scripts a sequence of behaviours.

    Returns the fn and a captured list of call kwargs so tests can
    assert how many times the SDK boundary was invoked.
    """

    calls: list[dict[str, Any]] = []

    async def fn(*, model: str, contents: str, config: object) -> _FakeResponse:
        calls.append({"model": model, "contents": contents, "config": config})
        return await behaviour()

    return fn, calls


def _rate_limited() -> genai_errors.ClientError:
    return genai_errors.ClientError(
        429, {"error": {"status": "RESOURCE_EXHAUSTED", "message": "rate limit"}}
    )


def _service_unavailable() -> genai_errors.ServerError:
    return genai_errors.ServerError(
        503, {"error": {"status": "UNAVAILABLE", "message": "overloaded"}}
    )


def _permission_denied() -> genai_errors.ClientError:
    return genai_errors.ClientError(
        403, {"error": {"status": "PERMISSION_DENIED", "message": "no access"}}
    )


def test_gemini_response_cost_calculation_flash() -> None:
    cost = gemini_cost_for(GEMINI_FLASH_MODEL, input_tokens=1_000_000, output_tokens=2_000_000)
    expected = GEMINI_FLASH_INPUT_COST_PER_MTOK + 2 * GEMINI_FLASH_OUTPUT_COST_PER_MTOK
    assert cost == pytest.approx(expected)


def test_gemini_response_cost_calculation_flash_lite() -> None:
    cost = gemini_cost_for(
        "gemini-3.1-flash-lite-preview", input_tokens=500_000, output_tokens=100_000
    )
    expected = (
        500_000 / 1_000_000 * GEMINI_FLASH_LITE_INPUT_COST_PER_MTOK
        + 100_000 / 1_000_000 * GEMINI_FLASH_LITE_OUTPUT_COST_PER_MTOK
    )
    assert cost == pytest.approx(expected)


def test_gemini_response_cost_calculation_pro() -> None:
    cost = gemini_cost_for("gemini-3.1-pro-preview", input_tokens=200_000, output_tokens=50_000)
    expected = (
        200_000 / 1_000_000 * GEMINI_PRO_INPUT_COST_PER_MTOK
        + 50_000 / 1_000_000 * GEMINI_PRO_OUTPUT_COST_PER_MTOK
    )
    assert cost == pytest.approx(expected)


def test_gemini_response_cost_unknown_model_falls_back_to_flash() -> None:
    cost = gemini_cost_for("gemini-unknown", input_tokens=1_000_000, output_tokens=0)
    assert cost == pytest.approx(GEMINI_COSTS[GEMINI_FLASH_3_5_MODEL][0])


# --- _extract_usage: token accounting incl. cached_content_token_count --------


def test_extract_usage_reads_cached_content_token_count() -> None:
    usage = _FakeUsageCached(prompt=120, candidates=40, cached=90)
    result = _extract_usage(_UsageResponse(usage))
    assert result.input_tokens == 120
    assert result.output_tokens == 40
    assert result.cached_input_tokens == 90


def test_extract_usage_cached_absent_defaults_to_zero() -> None:
    # A usage object that never sets cached_content_token_count (getattr default 0).
    result = _extract_usage(_UsageResponse(_FakeUsage(prompt=50, candidates=10)))
    assert result == (50, 10, 0)


def test_extract_usage_cached_none_defaults_to_zero() -> None:
    # Attribute present but None (SDK Optional field unset) → 0, not a crash.
    usage = _FakeUsageCached(prompt=50, candidates=10, cached=None)
    result = _extract_usage(_UsageResponse(usage))
    assert result.cached_input_tokens == 0
    assert result.input_tokens == 50
    assert result.output_tokens == 10


def test_extract_usage_clamps_negative_cached_to_zero() -> None:
    usage = _FakeUsageCached(prompt=10, candidates=5, cached=-3)
    result = _extract_usage(_UsageResponse(usage))
    assert result.cached_input_tokens == 0


def test_extract_usage_no_usage_metadata_is_all_zero() -> None:
    result = _extract_usage(_UsageResponse(None))
    assert result == (0, 0, 0)


def test_gemini_client_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """With BOTH AI-Studio env vars AND VERTEX_PROJECT unset the client refuses
    to initialise."""

    monkeypatch.delenv("VERTEX_PROJECT", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="No Gemini credentials found"):
        GeminiClient()


def test_gemini_client_accepts_gemini_api_key_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The AI Studio UI exposes the key as GEMINI_API_KEY; the client
    accepts it as a fallback when GOOGLE_API_KEY is unset.

    We construct with an injected ``generate_content_fn`` so the actual
    google-genai ``Client`` initialisation is not exercised — the test
    pins that build_default_genai_client is NOT called when an fn is
    injected, and that the no-fn path stops complaining once either
    key is present. We verify the no-fn path by deleting GOOGLE_API_KEY,
    setting GEMINI_API_KEY, and expecting the default construction to
    proceed to the genai SDK (which may itself raise on a fake key — we
    don't care, only that the early no-key RuntimeError does not fire).
    """

    monkeypatch.delenv("VERTEX_PROJECT", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "fake-but-present")
    try:
        GeminiClient()
    except RuntimeError as exc:
        # Acceptable: anything from the SDK auth flow. Not acceptable:
        # our own "no credentials" message.
        assert "No Gemini credentials found" not in str(exc)


def test_gemini_client_routes_to_vertex_when_project_set_without_app_creds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """VERTEX_PROJECT alone is enough — the SDK resolves credentials via ADC.

    Phase 1.5 follow-up: previously the code required BOTH
    ``VERTEX_PROJECT`` and ``GOOGLE_APPLICATION_CREDENTIALS`` to take the
    Vertex path, which forced a service-account-JSON workflow even for
    devs running ``gcloud auth application-default login``. The relaxed
    check uses Vertex whenever the project var is set; auth flows
    through the SDK's standard resolution chain (service-account JSON
    if specified, otherwise ADC).

    We don't exercise the real SDK auth here — we pin that the
    "no credentials" RuntimeError does NOT fire when VERTEX_PROJECT
    alone is set, even with the AI Studio keys cleared.
    """

    monkeypatch.setenv("VERTEX_PROJECT", "any-project-id")
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    try:
        GeminiClient()
    except RuntimeError as exc:
        # The SDK may raise on missing ADC; that's fine. Our own
        # early-exit message must NOT fire.
        assert "No Gemini credentials found" not in str(exc)


def test_gemini_response_model_rejects_negative_tokens() -> None:
    with pytest.raises(ValidationError):
        LLMResponse(
            content="ok",
            model=GEMINI_FLASH_MODEL,
            input_tokens=-1,
            output_tokens=5,
            latency_ms=10,
            estimated_cost_usd=0.0,
        )


@pytest.mark.asyncio
async def test_gemini_client_returns_text_and_cost() -> None:
    async def behaviour() -> _FakeResponse:
        return _FakeResponse("hello world", prompt_tokens=200, candidate_tokens=400)

    fn, calls = _make_fn(behaviour)
    client = GeminiClient(generate_content_fn=fn)

    response = await client.complete(system="sys", user="usr")

    assert response.content == "hello world"
    assert response.input_tokens == 200
    assert response.output_tokens == 400
    flash_input, flash_output = GEMINI_COSTS[GEMINI_FLASH_3_5_MODEL]
    expected_cost = 200 / 1_000_000 * flash_input + 400 / 1_000_000 * flash_output
    assert response.estimated_cost_usd == pytest.approx(expected_cost)
    assert len(calls) == 1
    assert calls[0]["model"] == GEMINI_FLASH_3_5_MODEL  # the GeminiClient default is now 3.5 Flash
    assert calls[0]["contents"] == "usr"


@pytest.mark.asyncio
async def test_gemini_client_retries_on_transient_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = {"count": 0}

    async def behaviour() -> _FakeResponse:
        state["count"] += 1
        if state["count"] <= 2:
            raise _rate_limited()
        return _FakeResponse("recovered", prompt_tokens=10, candidate_tokens=10)

    async def no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr("packages.core.gemini.asyncio.sleep", no_sleep)

    fn, calls = _make_fn(behaviour)
    client = GeminiClient(generate_content_fn=fn)

    response = await client.complete(system="sys", user="usr")

    assert response.content == "recovered"
    assert state["count"] == 3
    assert len(calls) == 3


@pytest.mark.asyncio
async def test_gemini_client_retries_on_service_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = {"count": 0}

    async def behaviour() -> _FakeResponse:
        state["count"] += 1
        if state["count"] == 1:
            raise _service_unavailable()
        return _FakeResponse("ok", prompt_tokens=5, candidate_tokens=5)

    async def no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr("packages.core.gemini.asyncio.sleep", no_sleep)

    fn, _ = _make_fn(behaviour)
    client = GeminiClient(generate_content_fn=fn)

    response = await client.complete(system="sys", user="usr")
    assert response.content == "ok"
    assert state["count"] == 2


@pytest.mark.asyncio
async def test_gemini_client_gives_up_after_max_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def behaviour() -> _FakeResponse:
        raise _service_unavailable()

    async def no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr("packages.core.gemini.asyncio.sleep", no_sleep)

    fn, calls = _make_fn(behaviour)
    client = GeminiClient(generate_content_fn=fn, max_retries=2)

    with pytest.raises(genai_errors.ServerError):
        await client.complete(system="sys", user="usr")

    # initial call + 2 retries = 3 attempts → 3 boundary invocations
    assert len(calls) == 3


def _quota_metric_429() -> genai_errors.ClientError:
    return genai_errors.ClientError(
        429,
        {
            "error": {
                "status": "RESOURCE_EXHAUSTED",
                "message": (
                    "Quota exceeded for quota metric 'Generate Content API requests "
                    "per minute' and limit 'GenerateContent request limit per minute'"
                ),
            }
        },
    )


@pytest.mark.asyncio
async def test_gemini_client_quota_metric_429_fails_fast() -> None:
    # Class A: a 429 that NAMES a quota metric is terminal — no retry at all.
    async def behaviour() -> _FakeResponse:
        raise _quota_metric_429()

    fn, calls = _make_fn(behaviour)
    client = GeminiClient(generate_content_fn=fn)

    with pytest.raises(genai_errors.ClientError) as excinfo:
        await client.complete(system="sys", user="usr")

    assert excinfo.value.code == 429
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_gemini_client_capacity_429_retries_until_budget_exhausted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Class B: a nameless RESOURCE_EXHAUSTED 429 retries on the throttle policy.
    # Pre-jitter series 10+20+40+80+120+120 = 390s fits the 480s budget; the 7th
    # backoff (120s) would exceed it → 6 retries, 7 boundary invocations.
    async def behaviour() -> _FakeResponse:
        raise _rate_limited()

    async def no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr("packages.core.gemini.asyncio.sleep", no_sleep)

    fn, calls = _make_fn(behaviour)
    client = GeminiClient(generate_content_fn=fn, max_retries=2)

    with pytest.raises(genai_errors.ClientError):
        await client.complete(system="sys", user="usr")

    assert len(calls) == 7


@pytest.mark.asyncio
async def test_gemini_client_capacity_429_does_not_consume_max_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The throttle counter is separate: even max_retries=0 recovers from a
    # capacity 429, because class B runs on its own budget.
    state = {"count": 0}

    async def behaviour() -> _FakeResponse:
        state["count"] += 1
        if state["count"] == 1:
            raise _rate_limited()
        return _FakeResponse("ok", prompt_tokens=5, candidate_tokens=5)

    async def no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr("packages.core.gemini.asyncio.sleep", no_sleep)

    fn, calls = _make_fn(behaviour)
    client = GeminiClient(generate_content_fn=fn, max_retries=0)

    response = await client.complete(system="sys", user="usr")
    assert response.content == "ok"
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_gemini_client_capacity_429_logs_attempt_delay_and_class_in_message(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    state = {"count": 0}
    slept: list[float] = []

    async def behaviour() -> _FakeResponse:
        state["count"] += 1
        if state["count"] == 1:
            raise _rate_limited()
        return _FakeResponse("ok", prompt_tokens=5, candidate_tokens=5)

    async def record_sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr("packages.core.gemini.asyncio.sleep", record_sleep)

    fn, _ = _make_fn(behaviour)
    client = GeminiClient(generate_content_fn=fn)

    with caplog.at_level(logging.WARNING, logger="packages.core.gemini"):
        await client.complete(system="sys", user="usr")

    records = [
        r for r in caplog.records if r.getMessage().startswith("gemini_call_throttled_retrying ")
    ]
    assert len(records) == 1
    payload = json.loads(records[0].getMessage().removeprefix("gemini_call_throttled_retrying "))
    assert payload["attempt"] == 1
    assert payload["error_class"] == "429_capacity_throttle"
    assert payload["backoff_seconds"] == 10.0
    # Full jitter: the actual delay is uniform in [0, backoff] and is what we slept.
    assert 0.0 <= payload["delay_seconds"] <= 10.0
    assert len(slept) == 1
    assert 0.0 <= slept[0] <= 10.0


@pytest.mark.asyncio
async def test_gemini_client_does_not_retry_auth_error() -> None:
    async def behaviour() -> _FakeResponse:
        raise _permission_denied()

    fn, calls = _make_fn(behaviour)
    client = GeminiClient(generate_content_fn=fn)

    with pytest.raises(genai_errors.ClientError) as excinfo:
        await client.complete(system="sys", user="usr")

    assert excinfo.value.code == 403
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_gemini_client_handles_missing_usage_metadata() -> None:
    class _ResponseWithoutUsage:
        def __init__(self) -> None:
            self.text: str | None = "no metadata"
            self.usage_metadata: object | None = None

    async def behaviour() -> Any:
        return _ResponseWithoutUsage()

    fn, _ = _make_fn(behaviour)
    client = GeminiClient(generate_content_fn=fn)

    response = await client.complete(system="sys", user="usr")
    assert response.content == "no metadata"
    assert response.input_tokens == 0
    assert response.output_tokens == 0
    assert response.estimated_cost_usd == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_complete_logs_cached_input_tokens(caplog: pytest.LogCaptureFixture) -> None:
    async def behaviour() -> _FakeResponse:
        return _FakeResponse("hi", prompt_tokens=300, candidate_tokens=20, cached_tokens=210)

    fn, _ = _make_fn(behaviour)
    client = GeminiClient(generate_content_fn=fn)

    with caplog.at_level(logging.INFO, logger="packages.core.gemini"):
        await client.complete(system="sys", user="usr")

    records = [r for r in caplog.records if r.getMessage() == "gemini_call_complete"]
    assert len(records) == 1
    assert records[0].__dict__["cached_input_tokens"] == 210
    assert records[0].__dict__["input_tokens"] == 300


# --- generate_with_tools (manual tool-calling primitive) ----------------------
#
# Fakes mirror the SDK response shape the tool path reads: candidates[0].content
# (the model's verbatim turn, with thought_signature on parts), the
# .function_calls convenience list, finish_reason, and usage_metadata. They are
# injected through a _make_tool_fn boundary typed for the tool-shaped response.


class _FakeFunctionCall:
    def __init__(self, name: str, args: dict[str, Any]) -> None:
        self.name = name
        self.args = args


class _FakeToolPart:
    def __init__(
        self,
        *,
        text: str | None = None,
        function_call: _FakeFunctionCall | None = None,
        thought_signature: bytes | None = None,
    ) -> None:
        self.text = text
        self.function_call = function_call
        self.thought_signature = thought_signature


class _FakeToolContent:
    def __init__(self, parts: list[_FakeToolPart], role: str = "model") -> None:
        self.parts = parts
        self.role = role


class _FakeCandidate:
    def __init__(
        self,
        content: _FakeToolContent | None,
        finish_reason: genai_types.FinishReason | None = None,
    ) -> None:
        self.content = content
        self.finish_reason = finish_reason


class _FakeToolResponse:
    def __init__(
        self,
        *,
        candidates: list[_FakeCandidate],
        function_calls: list[_FakeFunctionCall] | None = None,
        prompt_tokens: int = 0,
        candidate_tokens: int = 0,
        cached_tokens: int | None = None,
        text: str | None = None,
    ) -> None:
        self.candidates = candidates
        self.function_calls = function_calls
        self.usage_metadata: object | None = (
            _FakeUsage(prompt_tokens, candidate_tokens)
            if cached_tokens is None
            else _FakeUsageCached(prompt_tokens, candidate_tokens, cached_tokens)
        )
        self.text = text


def _make_tool_fn(
    behaviour: Callable[[], Awaitable[_FakeToolResponse]],
) -> tuple[Callable[..., Awaitable[_FakeToolResponse]], list[dict[str, Any]]]:
    """A ``generate_content_fn`` for the tool path.

    Typed for what ``generate_with_tools`` actually exchanges — ``list[Content]``
    contents in, a tool-shaped response out — unlike the complete() ``_make_fn``
    (``str`` contents, ``_FakeResponse``).
    """

    calls: list[dict[str, Any]] = []

    async def fn(
        *,
        model: str,
        contents: str | list[genai_types.Content],
        config: object,
    ) -> _FakeToolResponse:
        calls.append({"model": model, "contents": contents, "config": config})
        return await behaviour()

    return fn, calls


def _tool() -> genai_types.Tool:
    return genai_types.Tool(
        function_declarations=[
            genai_types.FunctionDeclaration(name="get_value", description="Return a value.")
        ]
    )


def _user_turn() -> list[genai_types.Content]:
    return [genai_types.Content(role="user", parts=[genai_types.Part(text="hi")])]


_STOP = genai_types.FinishReason.STOP


@pytest.mark.asyncio
async def test_generate_with_tools_returns_function_call() -> None:
    call = _FakeFunctionCall("get_value", {"key": "answer"})
    content = _FakeToolContent([_FakeToolPart(function_call=call, thought_signature=b"\x01\x02")])
    response = _FakeToolResponse(
        candidates=[_FakeCandidate(content, finish_reason=_STOP)],
        function_calls=[call],
        prompt_tokens=100,
        candidate_tokens=50,
    )

    async def behaviour() -> _FakeToolResponse:
        return response

    fn, calls = _make_tool_fn(behaviour)
    client = GeminiClient(generate_content_fn=fn)

    result = await client.generate_with_tools(contents=_user_turn(), tools=[_tool()])

    assert result.wants_tool is True
    assert len(result.function_calls) == 1
    assert result.function_calls[0].name == "get_value"
    assert result.model_content is content
    assert result.text is None
    assert result.input_tokens == 100
    assert result.output_tokens == 50
    expected_cost = 100 / 1_000_000 * GEMINI_PRO_INPUT_COST_PER_MTOK + (
        50 / 1_000_000 * GEMINI_PRO_OUTPUT_COST_PER_MTOK
    )
    assert result.estimated_cost_usd == pytest.approx(expected_cost)
    assert len(calls) == 1
    assert calls[0]["model"] == GEMINI_PRO_3_1_MODEL  # tool method defaults to Pro


@pytest.mark.asyncio
async def test_generate_with_tools_returns_text_on_clean_stop() -> None:
    # A normal STOP completion with no tool call: wants_tool=False, text is the answer.
    content = _FakeToolContent([_FakeToolPart(text="here is the answer")])
    response = _FakeToolResponse(
        candidates=[_FakeCandidate(content, finish_reason=_STOP)],
        function_calls=None,
        prompt_tokens=10,
        candidate_tokens=5,
    )

    async def behaviour() -> _FakeToolResponse:
        return response

    fn, _ = _make_tool_fn(behaviour)
    client = GeminiClient(generate_content_fn=fn)

    result = await client.generate_with_tools(contents=_user_turn(), tools=[_tool()])

    assert result.wants_tool is False
    assert result.function_calls == []
    assert result.text == "here is the answer"
    assert result.finish_reason is _STOP


@pytest.mark.asyncio
async def test_generate_with_tools_raises_on_empty_candidates() -> None:
    response = _FakeToolResponse(candidates=[], function_calls=None)

    async def behaviour() -> _FakeToolResponse:
        return response

    fn, calls = _make_tool_fn(behaviour)
    client = GeminiClient(generate_content_fn=fn)

    with pytest.raises(GeminiToolCallError):
        await client.generate_with_tools(contents=_user_turn(), tools=[_tool()])

    # An empty/blocked response is content-level, not transient — never retried.
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_generate_with_tools_raises_on_blocked_content() -> None:
    # No content at all (candidate.content is None) — blocked before any parts.
    candidate = _FakeCandidate(None, finish_reason=genai_types.FinishReason.SAFETY)
    response = _FakeToolResponse(candidates=[candidate], function_calls=None)

    async def behaviour() -> _FakeToolResponse:
        return response

    fn, calls = _make_tool_fn(behaviour)
    client = GeminiClient(generate_content_fn=fn)

    with pytest.raises(GeminiToolCallError, match="SAFETY"):
        await client.generate_with_tools(contents=_user_turn(), tools=[_tool()])
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_generate_with_tools_raises_on_malformed_function_call() -> None:
    # Degraded TERMINAL turn (content present, no usable call): the PRIMARY control
    # signal must not lie as wants_tool=False — it must raise. This locks the fix
    # for the silent-failure Codex caught (a malformed turn shipped as an answer).
    content = _FakeToolContent([_FakeToolPart(text="partial")])
    candidate = _FakeCandidate(
        content, finish_reason=genai_types.FinishReason.MALFORMED_FUNCTION_CALL
    )
    response = _FakeToolResponse(
        candidates=[candidate], function_calls=None, prompt_tokens=1, candidate_tokens=1
    )

    async def behaviour() -> _FakeToolResponse:
        return response

    fn, calls = _make_tool_fn(behaviour)
    client = GeminiClient(generate_content_fn=fn)

    with pytest.raises(GeminiToolCallError, match="MALFORMED_FUNCTION_CALL"):
        await client.generate_with_tools(contents=_user_turn(), tools=[_tool()])
    # Degraded content is not transient — surfaced on the first attempt, not retried.
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_generate_with_tools_raises_on_max_tokens() -> None:
    # Truncation is degraded: the caller may catch this and retry with more tokens.
    content = _FakeToolContent([_FakeToolPart(text="truncated half-thought")])
    candidate = _FakeCandidate(content, finish_reason=genai_types.FinishReason.MAX_TOKENS)
    response = _FakeToolResponse(candidates=[candidate], function_calls=None)

    async def behaviour() -> _FakeToolResponse:
        return response

    fn, _ = _make_tool_fn(behaviour)
    client = GeminiClient(generate_content_fn=fn)

    with pytest.raises(GeminiToolCallError, match="MAX_TOKENS"):
        await client.generate_with_tools(contents=_user_turn(), tools=[_tool()])


@pytest.mark.asyncio
async def test_generate_with_tools_raises_on_safety_block_with_content() -> None:
    # A safety block that still emitted parts must also raise (not only the
    # None-content path) — the finish_reason, not content emptiness, is the signal.
    content = _FakeToolContent([_FakeToolPart(text="...")])
    candidate = _FakeCandidate(content, finish_reason=genai_types.FinishReason.SAFETY)
    response = _FakeToolResponse(candidates=[candidate], function_calls=None)

    async def behaviour() -> _FakeToolResponse:
        return response

    fn, _ = _make_tool_fn(behaviour)
    client = GeminiClient(generate_content_fn=fn)

    with pytest.raises(GeminiToolCallError, match="SAFETY"):
        await client.generate_with_tools(contents=_user_turn(), tools=[_tool()])


@pytest.mark.asyncio
async def test_generate_with_tools_does_not_raise_degraded_when_function_calls_present() -> None:
    # The degraded raise is gated on having NO function call: a turn that DID
    # request a tool stays wants_tool=True even on a non-clean finish reason, so
    # the caller still runs the tool (this proves the fix did not over-raise).
    call = _FakeFunctionCall("get_value", {"key": "answer"})
    content = _FakeToolContent([_FakeToolPart(function_call=call, thought_signature=b"\x01")])
    response = _FakeToolResponse(
        candidates=[_FakeCandidate(content, finish_reason=genai_types.FinishReason.MAX_TOKENS)],
        function_calls=[call],
        prompt_tokens=5,
        candidate_tokens=5,
    )

    async def behaviour() -> _FakeToolResponse:
        return response

    fn, _ = _make_tool_fn(behaviour)
    client = GeminiClient(generate_content_fn=fn)

    result = await client.generate_with_tools(contents=_user_turn(), tools=[_tool()])

    assert result.wants_tool is True
    assert result.function_calls[0].name == "get_value"
    assert result.finish_reason is genai_types.FinishReason.MAX_TOKENS


@pytest.mark.asyncio
async def test_generate_with_tools_retries_on_transient_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = {"count": 0}
    call = _FakeFunctionCall("get_value", {})
    content = _FakeToolContent([_FakeToolPart(function_call=call, thought_signature=b"\x01")])
    ok = _FakeToolResponse(
        candidates=[_FakeCandidate(content, finish_reason=_STOP)],
        function_calls=[call],
        prompt_tokens=5,
        candidate_tokens=5,
    )

    async def behaviour() -> _FakeToolResponse:
        state["count"] += 1
        if state["count"] == 1:
            raise _rate_limited()
        return ok

    async def no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr("packages.core.gemini.asyncio.sleep", no_sleep)

    fn, calls = _make_tool_fn(behaviour)
    client = GeminiClient(generate_content_fn=fn)

    result = await client.generate_with_tools(contents=_user_turn(), tools=[_tool()])

    assert result.wants_tool is True
    assert state["count"] == 2
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_generate_with_tools_does_not_retry_auth_error() -> None:
    async def behaviour() -> _FakeToolResponse:
        raise _permission_denied()

    fn, calls = _make_tool_fn(behaviour)
    client = GeminiClient(generate_content_fn=fn)

    with pytest.raises(genai_errors.ClientError) as excinfo:
        await client.generate_with_tools(contents=_user_turn(), tools=[_tool()])

    assert excinfo.value.code == 403
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_generate_with_tools_logs_cached_input_tokens(
    caplog: pytest.LogCaptureFixture,
) -> None:
    call = _FakeFunctionCall("get_value", {"key": "answer"})
    content = _FakeToolContent([_FakeToolPart(function_call=call, thought_signature=b"\x01")])
    response = _FakeToolResponse(
        candidates=[_FakeCandidate(content, finish_reason=_STOP)],
        function_calls=[call],
        prompt_tokens=500,
        candidate_tokens=30,
        cached_tokens=420,
    )

    async def behaviour() -> _FakeToolResponse:
        return response

    fn, _ = _make_tool_fn(behaviour)
    client = GeminiClient(generate_content_fn=fn)

    with caplog.at_level(logging.INFO, logger="packages.core.gemini"):
        await client.generate_with_tools(contents=_user_turn(), tools=[_tool()])

    records = [r for r in caplog.records if r.getMessage() == "gemini_call_complete"]
    assert len(records) == 1
    assert records[0].__dict__["cached_input_tokens"] == 420
    assert records[0].__dict__["input_tokens"] == 500


@pytest.mark.asyncio
async def test_generate_with_tools_cached_content_omits_system_tools_and_tool_config() -> None:
    # cached_content is mutually exclusive with per-request system_instruction/
    # tools/tool_config — the cache already carries them. Sending both 400s.
    call = _FakeFunctionCall("get_value", {"key": "answer"})
    content = _FakeToolContent([_FakeToolPart(function_call=call, thought_signature=b"\x01")])
    response = _FakeToolResponse(
        candidates=[_FakeCandidate(content, finish_reason=_STOP)],
        function_calls=[call],
        prompt_tokens=100,
        candidate_tokens=50,
    )

    async def behaviour() -> _FakeToolResponse:
        return response

    fn, calls = _make_tool_fn(behaviour)
    client = GeminiClient(generate_content_fn=fn)

    result = await client.generate_with_tools(
        contents=_user_turn(),
        tools=[_tool()],
        system="brain rules",
        cached_content="cachedContents/abc",
    )

    assert result.wants_tool is True
    config = calls[0]["config"]
    assert config.cached_content == "cachedContents/abc"
    assert config.system_instruction is None
    assert config.tools is None
    assert config.tool_config is None
    assert config.automatic_function_calling is not None
    assert config.automatic_function_calling.disable is True


@pytest.mark.asyncio
async def test_generate_with_tools_bypasses_cache_for_nondefault_tool_config(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # A forced tool mode / allowlist cannot ride a cached call (tool_config is
    # excluded); the caller's constraint wins over the token saving.
    call = _FakeFunctionCall("get_value", {"key": "answer"})
    content = _FakeToolContent([_FakeToolPart(function_call=call, thought_signature=b"\x01")])
    response = _FakeToolResponse(
        candidates=[_FakeCandidate(content, finish_reason=_STOP)],
        function_calls=[call],
        prompt_tokens=100,
        candidate_tokens=50,
    )

    async def behaviour() -> _FakeToolResponse:
        return response

    fn, calls = _make_tool_fn(behaviour)
    client = GeminiClient(generate_content_fn=fn)

    with caplog.at_level(logging.WARNING, logger="packages.core.gemini"):
        await client.generate_with_tools(
            contents=_user_turn(),
            tools=[_tool()],
            system="brain rules",
            tool_mode=genai_types.FunctionCallingConfigMode.ANY,
            allowed_function_names=["get_value"],
            cached_content="cachedContents/abc",
        )

    config = calls[0]["config"]
    assert config.cached_content is None
    assert config.system_instruction == "brain rules"
    assert config.tools is not None
    assert config.tool_config is not None
    assert any(
        r.getMessage() == "gemini_cache_bypassed_nondefault_tool_config" for r in caplog.records
    )
