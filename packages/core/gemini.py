"""Async Google Gemini client wrapper used by the Inspector layer.

Mirrors :class:`packages.core.llm.LLMClient`'s contract — same
:class:`LLMResponse` model, same retry / timeout / cost-logging policy —
so workers can route between Anthropic and Google providers via
:class:`packages.core.model_router.ModelRouter` without changing call
sites.

Built on the ``google-genai`` SDK (the successor to the deprecated
``google-generativeai`` package). The SDK exposes a single async entry
point at ``client.aio.models.generate_content``; we wrap that call in
an injectable ``generate_content_fn`` so tests can supply a stub
without monkeypatching module-level state or constructing a live
:class:`google.genai.Client`.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import Awaitable, Callable
from typing import ClassVar, Final, Protocol, runtime_checkable

import google.genai as genai
from google.genai import errors as genai_errors
from google.genai import types as genai_types

from packages.core.constants import (
    DEFAULT_LLM_MAX_RETRIES,
    DEFAULT_LLM_TIMEOUT_SECONDS,
)
from packages.core.llm import LLMResponse

logger = logging.getLogger(__name__)


GEMINI_FLASH_MODEL: Final[str] = "gemini-2.5-flash"

# Current-generation Flash. Opt-in: not the GeminiClient default — pass
# explicitly as the ``model=`` arg on ``complete()``. Routed through the
# ThesisClassifier so the planner-validator pass benefits from the
# stronger multilingual judgment without changing editorial's existing
# interactive-pass calls (which stay on 2.5 Flash).
GEMINI_FLASH_3_5_MODEL: Final[str] = "gemini-3.5-flash"

# Per million tokens (input, output)
GEMINI_COSTS: Final[dict[str, tuple[float, float]]] = {
    "gemini-2.5-flash": (0.50, 3.00),
    # https://cloud.google.com/vertex-ai/generative-ai/pricing
    "gemini-3.5-flash": (1.50, 9.00),
    "gemini-3.1-flash-lite-preview": (0.25, 1.00),
    "gemini-3.1-pro-preview": (2.50, 15.00),
}

GEMINI_FLASH_INPUT_COST_PER_MTOK: Final[float] = GEMINI_COSTS["gemini-2.5-flash"][0]
GEMINI_FLASH_OUTPUT_COST_PER_MTOK: Final[float] = GEMINI_COSTS["gemini-2.5-flash"][1]
GEMINI_FLASH_LITE_INPUT_COST_PER_MTOK: Final[float] = GEMINI_COSTS["gemini-3.1-flash-lite-preview"][
    0
]
GEMINI_FLASH_LITE_OUTPUT_COST_PER_MTOK: Final[float] = GEMINI_COSTS[
    "gemini-3.1-flash-lite-preview"
][1]
GEMINI_PRO_INPUT_COST_PER_MTOK: Final[float] = GEMINI_COSTS["gemini-3.1-pro-preview"][0]
GEMINI_PRO_OUTPUT_COST_PER_MTOK: Final[float] = GEMINI_COSTS["gemini-3.1-pro-preview"][1]


_SAFETY_SETTINGS: Final[list[genai_types.SafetySetting]] = [
    genai_types.SafetySetting(
        category=genai_types.HarmCategory.HARM_CATEGORY_HARASSMENT,
        threshold=genai_types.HarmBlockThreshold.BLOCK_NONE,
    ),
    genai_types.SafetySetting(
        category=genai_types.HarmCategory.HARM_CATEGORY_HATE_SPEECH,
        threshold=genai_types.HarmBlockThreshold.BLOCK_NONE,
    ),
    genai_types.SafetySetting(
        category=genai_types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
        threshold=genai_types.HarmBlockThreshold.BLOCK_NONE,
    ),
    genai_types.SafetySetting(
        category=genai_types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
        threshold=genai_types.HarmBlockThreshold.BLOCK_NONE,
    ),
]


# HTTP status codes the SDK surfaces via APIError.code. Auth errors must
# not retry — a bad key is a configuration fault, not a transient one.
_AUTH_HTTP_CODES: Final[frozenset[int]] = frozenset({401, 403})


@runtime_checkable
class _GenerateContentResponseLike(Protocol):
    """Subset of ``GenerateContentResponse`` we depend on; lets tests inject stubs.

    Both attributes are read-only properties on the SDK's real
    response model, so we declare them as ``@property`` here to keep
    Protocol matching covariant. Test fakes can satisfy the protocol
    with plain attributes of the same types.
    """

    @property
    def text(self) -> str | None: ...

    @property
    def usage_metadata(self) -> object | None: ...


GenerateContentFn = Callable[..., Awaitable[_GenerateContentResponseLike]]


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


def build_default_genai_client() -> genai.Client:
    """Construct a ``google-genai`` client, preferring Vertex AI over AI Studio.

    Auth resolution, in order of preference:

    * **Vertex AI** — used whenever ``VERTEX_PROJECT`` is set. Credentials
      resolve through the SDK's standard chain: an explicit
      ``GOOGLE_APPLICATION_CREDENTIALS`` service-account JSON if present,
      otherwise Application Default Credentials from
      ``gcloud auth application-default login``. ``VERTEX_LOCATION``
      overrides the regional endpoint (default ``global`` — the only
      location that publishes the current Gemini 3.x family; regional
      endpoints like ``us-central1`` return 404 NOT_FOUND for them).
      Vertex bills against the GCP project and bypasses the AI Studio
      prepayment-credit pool entirely, which is the path you want for
      any non-trivial workload.
    * **AI Studio** — falls back to a personal API key under either
      ``GOOGLE_API_KEY`` (the SDK's documented name) or ``GEMINI_API_KEY``
      (the alias the AI Studio UI exposes and that several Google
      examples ship with). This is the casual / single-developer path;
      it does NOT survive depleted prepaid credits.

    Shared by :class:`GeminiClient` and the image/vision client so both
    providers route through the same credentials with one definition.
    """

    vertex_project = os.environ.get("VERTEX_PROJECT")
    if vertex_project:
        location = os.environ.get("VERTEX_LOCATION", "global")
        logger.info(
            "genai client using Vertex AI (project=%s, location=%s)",
            vertex_project,
            location,
        )
        return genai.Client(vertexai=True, project=vertex_project, location=location)
    api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "No Gemini credentials found. Set VERTEX_PROJECT (with "
            "`gcloud auth application-default login` or "
            "GOOGLE_APPLICATION_CREDENTIALS) for Vertex AI, or set "
            "GOOGLE_API_KEY / GEMINI_API_KEY for AI Studio."
        )
    logger.info("genai client using AI Studio API key")
    return genai.Client(api_key=api_key)


def _default_generate_content_fn(client: genai.Client) -> GenerateContentFn:
    """Bind a ``google.genai.Client`` into the injected-fn shape."""

    async def fn(
        *,
        model: str,
        contents: str,
        config: genai_types.GenerateContentConfig,
    ) -> _GenerateContentResponseLike:
        return await client.aio.models.generate_content(
            model=model,
            contents=contents,
            config=config,
        )

    return fn


class GeminiClient:
    """Async Gemini wrapper enforcing the project's LLM-integration rules.

    Behaviour parity with :class:`packages.core.llm.LLMClient`:

    * a per-call asyncio timeout (``DEFAULT_LLM_TIMEOUT_SECONDS`` — 180s today);
    * up to two retries on transient API errors (any
      :class:`google.genai.errors.APIError` whose HTTP code is not an
      auth code) or ``asyncio.TimeoutError`` (1s/2s exponential backoff);
    * authentication errors (HTTP 401 / 403) propagate immediately
      without retry — a misconfigured key is a configuration fault, not
      a transient one;
    * one info log per call with model, token counts, latency, and
      estimated cost.

    The constructor reads ``GOOGLE_API_KEY`` from the environment and
    constructs a :class:`google.genai.Client`. Tests inject a
    ``generate_content_fn`` to bypass both the env-var requirement and
    the live SDK initialization.
    """

    DEFAULT_MODEL: ClassVar[str] = GEMINI_FLASH_MODEL

    def __init__(
        self,
        generate_content_fn: GenerateContentFn | None = None,
        timeout_seconds: int = DEFAULT_LLM_TIMEOUT_SECONDS,
        max_retries: int = DEFAULT_LLM_MAX_RETRIES,
    ) -> None:
        if generate_content_fn is None:
            self._generate_content_fn: GenerateContentFn = _default_generate_content_fn(
                build_default_genai_client()
            )
        else:
            self._generate_content_fn = generate_content_fn
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

        config = genai_types.GenerateContentConfig(
            system_instruction=system,
            max_output_tokens=max_tokens,
            temperature=temperature,
            safety_settings=_SAFETY_SETTINGS,
        )

        attempt = 0
        last_error: Exception | None = None
        while attempt <= self._max_retries:
            start = time.perf_counter()
            try:
                response = await asyncio.wait_for(
                    self._generate_content_fn(
                        model=model,
                        contents=user,
                        config=config,
                    ),
                    timeout=self._timeout_seconds,
                )
            except TimeoutError as exc:
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
            except genai_errors.APIError as exc:
                if exc.code in _AUTH_HTTP_CODES:
                    raise
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
                        "error_code": exc.code,
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


def _extract_content_and_usage(
    response: _GenerateContentResponseLike,
) -> tuple[str, int, int]:
    """Pull text and token usage from a ``GenerateContentResponse``-like object.

    Defensive against missing ``usage_metadata`` (the SDK returns
    ``None`` when no token accounting is available) and against
    responses with no text content — both surface as empty/zero values
    rather than crashes so cost accounting stays sound.
    """

    text_attr = getattr(response, "text", None)
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
