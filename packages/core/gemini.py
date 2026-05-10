"""Async Google Gemini client wrapper used by the Inspector layer.

Mirrors :class:`packages.core.llm.LLMClient`'s contract — same
:class:`LLMResponse` model, same retry / timeout / cost-logging policy —
so workers can route between Anthropic and Google providers via
:class:`packages.core.model_router.ModelRouter` without changing call
sites.

The Google ``google-generativeai`` SDK exposes a per-call
``GenerativeModel`` factory rather than a long-lived client; we wrap
that in an injectable ``model_factory`` so tests can stub the model
without monkeypatching module-level state.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import Callable
from typing import ClassVar, Final, Protocol, runtime_checkable

import google.generativeai as genai
from google.api_core.exceptions import (
    DeadlineExceeded,
    GoogleAPICallError,
    PermissionDenied,
    ResourceExhausted,
    ServiceUnavailable,
    Unauthenticated,
)
from google.generativeai.types import HarmBlockThreshold, HarmCategory

from packages.core.constants import (
    DEFAULT_LLM_MAX_RETRIES,
    DEFAULT_LLM_TIMEOUT_SECONDS,
)
from packages.core.llm import LLMResponse

logger = logging.getLogger(__name__)


GEMINI_FLASH_MODEL: Final[str] = "gemini-3-flash"

# Per million tokens (input, output)
GEMINI_COSTS: Final[dict[str, tuple[float, float]]] = {
    "gemini-3-flash": (0.50, 3.00),
    "gemini-3.1-flash-lite-preview": (0.25, 1.00),
    "gemini-3.1-pro-preview": (2.50, 15.00),
}

GEMINI_FLASH_INPUT_COST_PER_MTOK: Final[float] = GEMINI_COSTS["gemini-3-flash"][0]
GEMINI_FLASH_OUTPUT_COST_PER_MTOK: Final[float] = GEMINI_COSTS["gemini-3-flash"][1]
GEMINI_FLASH_LITE_INPUT_COST_PER_MTOK: Final[float] = GEMINI_COSTS["gemini-3.1-flash-lite-preview"][
    0
]
GEMINI_FLASH_LITE_OUTPUT_COST_PER_MTOK: Final[float] = GEMINI_COSTS[
    "gemini-3.1-flash-lite-preview"
][1]
GEMINI_PRO_INPUT_COST_PER_MTOK: Final[float] = GEMINI_COSTS["gemini-3.1-pro-preview"][0]
GEMINI_PRO_OUTPUT_COST_PER_MTOK: Final[float] = GEMINI_COSTS["gemini-3.1-pro-preview"][1]


_SAFETY_SETTINGS: Final[dict[HarmCategory, HarmBlockThreshold]] = {
    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
}


@runtime_checkable
class _GenerativeModelLike(Protocol):
    """Subset of ``GenerativeModel`` we depend on; lets tests inject stubs."""

    async def generate_content_async(
        self,
        contents: str,
        generation_config: object | None = ...,
        safety_settings: object | None = ...,
    ) -> object: ...


ModelFactory = Callable[[str, str], _GenerativeModelLike]


def gemini_cost_for(model: str, input_tokens: int, output_tokens: int) -> float:
    """Return USD cost of one Gemini call from its model name and token usage.

    Falls back to Flash pricing for unknown model strings — cost
    accounting must never fail a user-visible job, but a misrouted call
    would still be surfaced via the per-call info log line.
    """

    rates = GEMINI_COSTS.get(model)
    if rates is None:
        rates = GEMINI_COSTS[GEMINI_FLASH_MODEL]
    input_rate, output_rate = rates
    return (input_tokens / 1_000_000.0) * input_rate + (output_tokens / 1_000_000.0) * output_rate


def _default_model_factory(model_name: str, system_instruction: str) -> _GenerativeModelLike:
    """Construct a real ``GenerativeModel`` with our shared safety settings."""

    return genai.GenerativeModel(  # type: ignore[reportUnknownMemberType]
        model_name=model_name,
        system_instruction=system_instruction,
        safety_settings=_SAFETY_SETTINGS,
    )


class GeminiClient:
    """Async Gemini wrapper enforcing the project's LLM-integration rules.

    Behaviour parity with :class:`packages.core.llm.LLMClient`:

    * 30s asyncio timeout per call;
    * up to two retries on :class:`ResourceExhausted`,
      :class:`ServiceUnavailable`, :class:`DeadlineExceeded`, or
      ``asyncio.TimeoutError`` (1s/2s exponential backoff);
    * authentication errors (:class:`PermissionDenied`,
      :class:`Unauthenticated`) propagate immediately without retry — a
      misconfigured key is a configuration fault, not a transient one;
    * one info log per call with model, token counts, latency, and
      estimated cost.

    The constructor reads ``GOOGLE_API_KEY`` from the environment and
    calls :func:`genai.configure`. Tests inject a ``model_factory`` to
    bypass both the env-var requirement and the global SDK state.
    """

    DEFAULT_MODEL: ClassVar[str] = GEMINI_FLASH_MODEL

    def __init__(
        self,
        model_factory: ModelFactory | None = None,
        timeout_seconds: int = DEFAULT_LLM_TIMEOUT_SECONDS,
        max_retries: int = DEFAULT_LLM_MAX_RETRIES,
    ) -> None:
        if model_factory is None:
            api_key = os.environ.get("GOOGLE_API_KEY")
            if not api_key:
                raise RuntimeError(
                    "GOOGLE_API_KEY environment variable is not set; "
                    "GeminiClient cannot be initialized without it."
                )
            genai.configure(api_key=api_key)  # type: ignore[reportUnknownMemberType]
            self._model_factory: ModelFactory = _default_model_factory
        else:
            self._model_factory = model_factory
        self._timeout_seconds = timeout_seconds
        self._max_retries = max_retries

    async def complete(
        self,
        system: str,
        user: str,
        model: str = GEMINI_FLASH_MODEL,
        max_tokens: int = 2000,
        temperature: float = 0.0,
    ) -> LLMResponse:
        """Run one completion with retry, timeout, and cost logging."""

        attempt = 0
        last_error: Exception | None = None
        while attempt <= self._max_retries:
            start = time.perf_counter()
            try:
                model_obj = self._model_factory(model, system)
                generation_config = genai.GenerationConfig(  # type: ignore[reportUnknownMemberType]
                    max_output_tokens=max_tokens,
                    temperature=temperature,
                )
                response = await asyncio.wait_for(
                    model_obj.generate_content_async(
                        user,
                        generation_config=generation_config,
                        safety_settings=_SAFETY_SETTINGS,
                    ),
                    timeout=self._timeout_seconds,
                )
            except (PermissionDenied, Unauthenticated):
                raise
            except (TimeoutError, ResourceExhausted, ServiceUnavailable, DeadlineExceeded) as exc:
                last_error = exc
                attempt += 1
                if attempt > self._max_retries:
                    break
                backoff = 2 ** (attempt - 1)
                logger.warning(
                    "gemini_call_failed_retrying",
                    extra={
                        "model": model,
                        "attempt": attempt,
                        "backoff_seconds": backoff,
                        "error_type": type(exc).__name__,
                    },
                )
                await asyncio.sleep(backoff)
                continue
            except GoogleAPICallError as exc:
                last_error = exc
                attempt += 1
                if attempt > self._max_retries:
                    break
                backoff = 2 ** (attempt - 1)
                logger.warning(
                    "gemini_call_failed_retrying",
                    extra={
                        "model": model,
                        "attempt": attempt,
                        "backoff_seconds": backoff,
                        "error_type": type(exc).__name__,
                    },
                )
                await asyncio.sleep(backoff)
                continue

            latency_ms = int((time.perf_counter() - start) * 1000)
            content, input_tokens, output_tokens = _extract_content_and_usage(response)
            cost = gemini_cost_for(model, input_tokens, output_tokens)

            logger.info(
                "gemini_call_complete",
                extra={
                    "model": model,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "latency_ms": latency_ms,
                    "estimated_cost_usd": round(cost, 6),
                },
            )

            return LLMResponse(
                content=content,
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                latency_ms=latency_ms,
                estimated_cost_usd=cost,
            )

        assert last_error is not None
        raise last_error


def _extract_content_and_usage(response: object) -> tuple[str, int, int]:
    """Pull text and token usage from a ``GenerateContentResponse``-like object.

    Defensive against missing ``usage_metadata`` (older SDKs return
    ``None``) and against responses with no candidates — both surface as
    empty/zero values rather than crashes so cost accounting stays sound.
    """

    text_attr = getattr(response, "text", "")
    text = text_attr if isinstance(text_attr, str) else ""

    usage = getattr(response, "usage_metadata", None)
    input_tokens = 0
    output_tokens = 0
    if usage is not None:
        prompt = getattr(usage, "prompt_token_count", 0)
        candidate = getattr(usage, "candidates_token_count", 0)
        if isinstance(prompt, int):
            input_tokens = max(0, prompt)
        if isinstance(candidate, int):
            output_tokens = max(0, candidate)
    return text, input_tokens, output_tokens
