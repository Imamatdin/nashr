"""Behaviour tests for :class:`ModelRouter`.

The router is a thin dispatch layer over :class:`LLMClient` and
:class:`GeminiClient`. We assert:

* Claude model names route to the Anthropic client.
* Gemini model names route to the Google client.
* Unknown providers raise :class:`ValueError` (rather than silently
  picking a provider).
* Provider clients are constructed lazily — one only on first use, the
  other not at all when its provider is unused.
"""

from __future__ import annotations

from typing import Any

import pytest

from packages.core.gemini import GeminiClient
from packages.core.llm import LLMClient, LLMResponse
from packages.core.model_router import ModelRouter


class _FakeAnthropicClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    async def complete(
        self,
        system: str,
        user: str,
        model: str = "claude-haiku-4-5-20251001",
        max_tokens: int = 2000,
        temperature: float = 0.0,
    ) -> LLMResponse:
        del max_tokens, temperature
        self.calls.append((system, user, model))
        return LLMResponse(
            content="anthropic-output",
            model=model,
            input_tokens=10,
            output_tokens=20,
            latency_ms=5,
            estimated_cost_usd=0.0001,
        )


class _FakeGeminiClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    async def complete(
        self,
        system: str,
        user: str,
        model: str = "gemini-3-flash",
        max_tokens: int = 2000,
        temperature: float = 0.0,
    ) -> LLMResponse:
        del max_tokens, temperature
        self.calls.append((system, user, model))
        return LLMResponse(
            content="gemini-output",
            model=model,
            input_tokens=10,
            output_tokens=20,
            latency_ms=5,
            estimated_cost_usd=0.0001,
        )


@pytest.mark.asyncio
async def test_router_routes_claude_to_anthropic() -> None:
    fake_anthropic = _FakeAnthropicClient()
    fake_gemini = _FakeGeminiClient()
    router = ModelRouter(
        anthropic=fake_anthropic,  # type: ignore[arg-type]
        gemini=fake_gemini,  # type: ignore[arg-type]
    )

    response = await router.complete(
        system="sys",
        user="usr",
        model="claude-sonnet-4-6-20250514",
    )

    assert response.content == "anthropic-output"
    assert len(fake_anthropic.calls) == 1
    assert fake_anthropic.calls[0][2] == "claude-sonnet-4-6-20250514"
    assert len(fake_gemini.calls) == 0


@pytest.mark.asyncio
async def test_router_routes_gemini_to_google() -> None:
    fake_anthropic = _FakeAnthropicClient()
    fake_gemini = _FakeGeminiClient()
    router = ModelRouter(
        anthropic=fake_anthropic,  # type: ignore[arg-type]
        gemini=fake_gemini,  # type: ignore[arg-type]
    )

    response = await router.complete(
        system="sys",
        user="usr",
        model="gemini-3-flash",
    )

    assert response.content == "gemini-output"
    assert len(fake_gemini.calls) == 1
    assert fake_gemini.calls[0][2] == "gemini-3-flash"
    assert len(fake_anthropic.calls) == 0


@pytest.mark.asyncio
async def test_router_rejects_unknown_provider() -> None:
    router = ModelRouter(
        anthropic=_FakeAnthropicClient(),  # type: ignore[arg-type]
        gemini=_FakeGeminiClient(),  # type: ignore[arg-type]
    )

    with pytest.raises(ValueError, match="Unknown model provider"):
        await router.complete(system="sys", user="usr", model="gpt-4o")


@pytest.mark.asyncio
async def test_router_lazy_initializes_clients(monkeypatch: pytest.MonkeyPatch) -> None:
    """Only the provider that is called gets constructed."""

    init_counts = {"anthropic": 0, "gemini": 0}

    def fake_anthropic_init(self: LLMClient, *args: Any, **kwargs: Any) -> None:
        del args, kwargs
        init_counts["anthropic"] += 1
        # Avoid touching the real AsyncAnthropic constructor.
        self._client = object()  # type: ignore[attr-defined]
        self._timeout_seconds = 30  # type: ignore[attr-defined]
        self._max_retries = 2  # type: ignore[attr-defined]

    def fake_gemini_init(self: GeminiClient, *args: Any, **kwargs: Any) -> None:
        del args, kwargs
        init_counts["gemini"] += 1
        self._model_factory = lambda *_a, **_k: None  # type: ignore[attr-defined]
        self._timeout_seconds = 30  # type: ignore[attr-defined]
        self._max_retries = 2  # type: ignore[attr-defined]

    async def fake_complete_anthropic(self: LLMClient, **_kwargs: Any) -> LLMResponse:
        del self
        return LLMResponse(
            content="ok",
            model="claude-sonnet-4-6-20250514",
            input_tokens=1,
            output_tokens=1,
            latency_ms=1,
            estimated_cost_usd=0.0,
        )

    monkeypatch.setattr(LLMClient, "__init__", fake_anthropic_init)
    monkeypatch.setattr(GeminiClient, "__init__", fake_gemini_init)
    monkeypatch.setattr(LLMClient, "complete", fake_complete_anthropic)

    router = ModelRouter()
    assert router._anthropic is None  # type: ignore[reportPrivateUsage]
    assert router._gemini is None  # type: ignore[reportPrivateUsage]

    await router.complete(system="sys", user="usr", model="claude-sonnet-4-6-20250514")

    assert init_counts["anthropic"] == 1
    assert init_counts["gemini"] == 0
    assert router._anthropic is not None  # type: ignore[reportPrivateUsage]
    assert router._gemini is None  # type: ignore[reportPrivateUsage]


@pytest.mark.asyncio
async def test_router_reuses_provider_client_across_calls() -> None:
    """A second Claude call must reuse the same Anthropic client."""

    fake_anthropic = _FakeAnthropicClient()
    router = ModelRouter(anthropic=fake_anthropic)  # type: ignore[arg-type]

    await router.complete(system="s", user="u1", model="claude-sonnet-4-6-20250514")
    await router.complete(system="s", user="u2", model="claude-sonnet-4-6-20250514")

    assert len(fake_anthropic.calls) == 2
    assert router._anthropic is fake_anthropic  # type: ignore[reportPrivateUsage]
