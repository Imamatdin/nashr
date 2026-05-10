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

from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from google.genai import errors as genai_errors
from pydantic import ValidationError

from packages.core.gemini import (
    GEMINI_FLASH_INPUT_COST_PER_MTOK,
    GEMINI_FLASH_LITE_INPUT_COST_PER_MTOK,
    GEMINI_FLASH_LITE_OUTPUT_COST_PER_MTOK,
    GEMINI_FLASH_MODEL,
    GEMINI_FLASH_OUTPUT_COST_PER_MTOK,
    GEMINI_PRO_INPUT_COST_PER_MTOK,
    GEMINI_PRO_OUTPUT_COST_PER_MTOK,
    GeminiClient,
    gemini_cost_for,
)
from packages.core.llm import LLMResponse


class _FakeUsage:
    def __init__(self, prompt: int, candidates: int) -> None:
        self.prompt_token_count = prompt
        self.candidates_token_count = candidates


class _FakeResponse:
    def __init__(self, text: str, prompt_tokens: int, candidate_tokens: int) -> None:
        self.text: str | None = text
        self.usage_metadata: object | None = _FakeUsage(prompt_tokens, candidate_tokens)


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
    assert cost == pytest.approx(GEMINI_FLASH_INPUT_COST_PER_MTOK)


def test_gemini_client_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="GOOGLE_API_KEY"):
        GeminiClient()


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
    expected_cost = (
        200 / 1_000_000 * GEMINI_FLASH_INPUT_COST_PER_MTOK
        + 400 / 1_000_000 * GEMINI_FLASH_OUTPUT_COST_PER_MTOK
    )
    assert response.estimated_cost_usd == pytest.approx(expected_cost)
    assert len(calls) == 1
    assert calls[0]["model"] == GEMINI_FLASH_MODEL
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
        raise _rate_limited()

    async def no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr("packages.core.gemini.asyncio.sleep", no_sleep)

    fn, calls = _make_fn(behaviour)
    client = GeminiClient(generate_content_fn=fn, max_retries=2)

    with pytest.raises(genai_errors.ClientError):
        await client.complete(system="sys", user="usr")

    # initial call + 2 retries = 3 attempts → 3 boundary invocations
    assert len(calls) == 3


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
