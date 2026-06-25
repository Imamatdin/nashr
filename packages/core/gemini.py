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
from packages.core.gemini_tools import ToolTurnResult
from packages.core.llm import LLMResponse

logger = logging.getLogger(__name__)


GEMINI_FLASH_MODEL: Final[str] = "gemini-2.5-flash"

# Current-generation Flash — the GeminiClient DEFAULT model (see ``DEFAULT_MODEL``
# below and the default ``model=`` on ``complete()``). After the 3.x model swap it
# backs every Flash-tier pass: thesis classifier (planner-validator), design
# direction, claim extraction, vision (via gemini_image), and editorial's
# interactive-content pass — all migrated off 2.5 Flash.
GEMINI_FLASH_3_5_MODEL: Final[str] = "gemini-3.5-flash"

# Current-generation Pro — the strong-reasoning tier. Opt-in (not the
# GeminiClient default): pass explicitly as ``model=``. Used by the planner
# (source-grounded authorship plan) and the content critic (adversarial
# source-grounding audit). Its cost entry is in GEMINI_COSTS below.
GEMINI_PRO_3_1_MODEL: Final[str] = "gemini-3.1-pro-preview"

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


class GeminiToolCallError(RuntimeError):
    """A tool-calling turn produced no usable model content.

    Distinct from a transport failure (:class:`google.genai.errors.APIError`):
    this is a content-level outcome that is not retryable at the transport layer
    and must be surfaced rather than mistaken for a finished answer. Raised for
    an empty / blocked candidate (no content to append) and for a DEGRADED
    terminal turn — one whose ``finish_reason`` is anything other than a clean
    completion (truncated ``MAX_TOKENS``, ``MALFORMED_FUNCTION_CALL``,
    ``UNEXPECTED_TOOL_CALL``, or a safety / recitation block) with no function
    call to run. The caller may catch it and recover (e.g. retry ``MAX_TOKENS``
    with a larger budget).
    """


# Finish reasons that mark a COMPLETE, usable terminal turn. Everything else the
# SDK's FinishReason enum can report (MAX_TOKENS, MALFORMED_FUNCTION_CALL,
# UNEXPECTED_TOOL_CALL, SAFETY/RECITATION/BLOCKLIST/PROHIBITED_CONTENT/SPII,
# LANGUAGE/OTHER, the IMAGE_* reasons) is a DEGRADED turn. This is an allowlist,
# not a denylist, so a future/unknown finish reason fails safe (raises) rather
# than silently passing as a finished answer.
_CLEAN_FINISH_REASONS: Final[frozenset[genai_types.FinishReason]] = frozenset(
    {
        genai_types.FinishReason.STOP,
        genai_types.FinishReason.FINISH_REASON_UNSPECIFIED,
    }
)


@runtime_checkable
class _GenerateContentResponseLike(Protocol):
    """Subset of ``GenerateContentResponse`` we depend on; lets tests inject stubs.

    These are read-only properties on the SDK's real response model, so we
    declare them as ``@property`` here to keep Protocol matching covariant. Test
    fakes can satisfy the protocol with plain attributes of the same types.

    The superset spans both call paths: :meth:`GeminiClient.complete` reads
    ``text`` + ``usage_metadata``; :meth:`GeminiClient.generate_with_tools`
    reads ``candidates`` (for the model's full Content, signatures intact) +
    ``function_calls`` + ``usage_metadata``. The real SDK response satisfies all
    four; the existing ``complete`` test fakes are injected through an
    ``Awaitable[Any]`` boundary, so broadening the protocol does not disturb them.
    """

    @property
    def text(self) -> str | None: ...

    @property
    def usage_metadata(self) -> object | None: ...

    @property
    def candidates(self) -> list[genai_types.Candidate] | None: ...

    @property
    def function_calls(self) -> list[genai_types.FunctionCall] | None: ...


GenerateContentFn = Callable[..., Awaitable[_GenerateContentResponseLike]]


def gemini_cost_for(model: str, input_tokens: int, output_tokens: int) -> float:
    """Return USD cost of one Gemini call from its model name and token usage.

    Falls back to current-generation Flash pricing for unknown model
    strings — cost accounting must never fail a user-visible job, but a
    misrouted call would still be surfaced via the per-call info log line.
    """

    rates = GEMINI_COSTS.get(model)
    if rates is None:
        rates = GEMINI_COSTS[GEMINI_FLASH_3_5_MODEL]
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
    """Bind a ``google.genai.Client`` into the injected-fn shape.

    ``contents`` is the SDK's own ``ContentListUnion`` so the one injected fn
    serves both call paths: :meth:`GeminiClient.complete` passes a ``str`` (a
    valid member of the union) and :meth:`GeminiClient.generate_with_tools`
    passes a ``list[Content]`` history.
    """

    async def fn(
        *,
        model: str,
        contents: genai_types.ContentListUnion,
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

    DEFAULT_MODEL: ClassVar[str] = GEMINI_FLASH_3_5_MODEL

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
        model: str = GEMINI_FLASH_3_5_MODEL,
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
        response, latency_ms = await self._generate_with_retry(
            model=model,
            contents=user,
            config=config,
            timeout=self._timeout_seconds,
        )

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

    async def _generate_with_retry(
        self,
        *,
        model: str,
        contents: str | list[genai_types.Content],
        config: genai_types.GenerateContentConfig,
        timeout: int,
    ) -> tuple[_GenerateContentResponseLike, int]:
        """Run one ``generate_content`` call under the shared retry/timeout policy.

        The single source of truth for the project's Gemini call policy, used by
        both :meth:`complete` and :meth:`generate_with_tools`: a per-attempt
        :func:`asyncio.wait_for` timeout, up to ``max_retries`` retries on a
        transient :class:`~google.genai.errors.APIError` (any HTTP code NOT in
        :data:`_AUTH_HTTP_CODES`) or :class:`TimeoutError` with 1s/2s exponential
        backoff, immediate propagation of auth errors (401 / 403), and one
        ``gemini_call_failed_retrying`` warning per retry. Returns the raw
        response and the successful attempt's latency; the caller owns success
        logging, cost accounting, and response parsing.

        A 400 (e.g. a dropped ``thought_signature``) is non-transient but, being
        neither an auth code nor a timeout, is retried to exhaustion like any
        other API error — identical to ``complete``'s historical behaviour, kept
        unchanged here. A future caller that must skip-retry 400 should
        parameterise the non-retryable code set rather than diverge this loop.
        """

        attempt = 0
        last_error: Exception | None = None
        while attempt <= self._max_retries:
            start = time.perf_counter()
            try:
                response = await asyncio.wait_for(
                    self._generate_content_fn(
                        model=model,
                        contents=contents,
                        config=config,
                    ),
                    timeout=timeout,
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
            return response, latency_ms

        assert last_error is not None
        raise last_error

    async def generate_with_tools(
        self,
        contents: list[genai_types.Content],
        tools: list[genai_types.Tool],
        *,
        system: str | None = None,
        model: str = GEMINI_PRO_3_1_MODEL,
        max_tokens: int = 8192,
        temperature: float = 0.0,
        tool_mode: genai_types.FunctionCallingConfigMode = (
            genai_types.FunctionCallingConfigMode.AUTO
        ),
        allowed_function_names: list[str] | None = None,
        timeout: int | None = None,
    ) -> ToolTurnResult:
        """Run ONE manual tool-calling turn against Gemini and parse the result.

        This is a SINGLE-TURN primitive: one ``generate_content`` call in, one
        :class:`~packages.core.gemini_tools.ToolTurnResult` out. The multi-turn
        loop — and the human-approval pause that manual function-calling exists
        to allow — lives in the caller, not here. Function-calling is manual:
        ``tools`` are declarations only and ``automatic_function_calling`` is
        explicitly disabled, so the SDK never executes a tool itself; it returns
        the requested call(s) for the caller to run.

        THE APPEND RULE (the caller's responsibility, stated here because getting
        it wrong silently breaks Gemini 3): when the result
        :attr:`~packages.core.gemini_tools.ToolTurnResult.wants_tool`, append
        ``result.model_content`` to ``contents`` **verbatim** — it carries the
        ``thought_signature`` Gemini 3 requires back on the next request, and
        hand-reconstructing the turn drops it (→ HTTP 400). Then append
        :func:`~packages.core.gemini_tools.build_function_responses_content` with
        one entry per call and invoke this method again.

        THE CONTROL PATH. A returned :class:`ToolTurnResult` is always a USABLE
        turn — either a tool request or a clean completion::

            try:
                result = await client.generate_with_tools(history, tools)
            except GeminiToolCallError:
                ...  # degraded turn (truncated / malformed / blocked) — handle/retry
            else:
                if result.wants_tool:
                    ...  # run the tool(s), append, loop
                else:
                    deliver(result.text)  # a clean STOP completion — the answer

        A DEGRADED terminal turn (a ``finish_reason`` outside
        :data:`_CLEAN_FINISH_REASONS` — ``MAX_TOKENS``, ``MALFORMED_FUNCTION_CALL``,
        ``UNEXPECTED_TOOL_CALL``, a safety/recitation block — with no function
        call) raises :class:`GeminiToolCallError` instead of returning a result
        whose ``wants_tool`` is falsely ``False``. ``MAX_TOKENS`` raising means a
        caller that wants to can catch it and retry with a larger ``max_tokens``.

        ``tool_mode`` defaults to ``AUTO`` (the model decides whether to call a
        tool or answer) — the right default for the brain; the gate may force
        ``ANY``. ``max_tokens`` defaults high enough for Gemini 3 Pro to think:
        the ``thought_signature`` is a by-product of thinking, so
        ``thinking_config`` is deliberately left unset to preserve it. ``timeout``
        overrides the client default for a single call, for turns with large
        thinking budgets. Per-call cost and token usage are recorded on the
        result; the caller sums them across a conversation's turns.
        """

        effective_timeout = timeout if timeout is not None else self._timeout_seconds
        function_calling_config = genai_types.FunctionCallingConfig(
            mode=tool_mode,
            allowed_function_names=allowed_function_names,
        )
        config = genai_types.GenerateContentConfig(
            system_instruction=system,
            max_output_tokens=max_tokens,
            temperature=temperature,
            safety_settings=_SAFETY_SETTINGS,
            tools=tools,
            tool_config=genai_types.ToolConfig(function_calling_config=function_calling_config),
            automatic_function_calling=genai_types.AutomaticFunctionCallingConfig(disable=True),
        )

        response, latency_ms = await self._generate_with_retry(
            model=model,
            contents=contents,
            config=config,
            timeout=effective_timeout,
        )

        model_content, finish_reason = _extract_tool_turn_content(response)
        function_calls = list(response.function_calls or [])
        if (
            not function_calls
            and finish_reason is not None
            and finish_reason not in _CLEAN_FINISH_REASONS
        ):
            # A terminal turn with no tool call and a degraded finish reason is not
            # a usable answer. Raise rather than return wants_tool=False, so the
            # caller's "if not wants_tool: deliver text" path can never ship a
            # truncated / malformed / blocked turn as a finished answer.
            raise GeminiToolCallError(
                f"Gemini ended a terminal turn on a degraded finish_reason="
                f"{finish_reason.value} (truncated, malformed, or blocked) with no "
                "function call — not a usable answer; the caller may catch and retry "
                "(e.g. a larger max_tokens on MAX_TOKENS)."
            )
        text = _join_text_parts(model_content)
        input_tokens, output_tokens = _extract_usage(response)
        cost = gemini_cost_for(model, input_tokens, output_tokens)

        logger.info(
            "gemini_call_complete",
            extra={
                "model": model,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "latency_ms": latency_ms,
                "estimated_cost_usd": round(cost, 6),
                "function_calls": len(function_calls),
                "finish_reason": finish_reason.value if finish_reason is not None else None,
            },
        )

        return ToolTurnResult(
            model_content=model_content,
            function_calls=function_calls,
            text=text,
            finish_reason=finish_reason,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated_cost_usd=cost,
            latency_ms=latency_ms,
        )


def _extract_usage(response: _GenerateContentResponseLike) -> tuple[int, int]:
    """Pull ``(input_tokens, output_tokens)`` from a response, defensively.

    The SDK returns ``usage_metadata=None`` when no token accounting is
    available; missing or non-int counts surface as zero rather than crashing,
    so cost accounting stays sound. Shared by :meth:`GeminiClient.complete` (via
    :func:`_extract_content_and_usage`) and :meth:`GeminiClient.generate_with_tools`.
    """

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
    return input_tokens, output_tokens


def _extract_content_and_usage(
    response: _GenerateContentResponseLike,
) -> tuple[str, int, int]:
    """Pull text and token usage from a ``GenerateContentResponse``-like object.

    Defensive against responses with no text content (surfaces as an empty
    string) and delegates token accounting to :func:`_extract_usage`. Used only
    by :meth:`GeminiClient.complete`; the tool path reads parts directly to
    avoid the SDK's ``.text`` warning on function-call responses.
    """

    text_attr = getattr(response, "text", None)
    text = text_attr if isinstance(text_attr, str) else ""
    input_tokens, output_tokens = _extract_usage(response)
    return text, input_tokens, output_tokens


def _extract_tool_turn_content(
    response: _GenerateContentResponseLike,
) -> tuple[genai_types.Content, genai_types.FinishReason | None]:
    """Return the model's full Content and finish reason from a tool-calling turn.

    The Content is read from ``candidates[0]`` verbatim — every part, including
    each ``thought_signature`` — so the caller can append it without losing the
    signature Gemini 3 requires on the next request.

    Raises :class:`GeminiToolCallError` when there is no usable content to append
    — an empty ``candidates`` list, or a candidate whose ``content`` is ``None``
    or partless (a safety block, recitation halt, or prompt-feedback rejection).
    That is a NON-transient outcome, so it is surfaced rather than retried or
    silently treated as an empty completion. ``finish_reason`` is returned (not
    swallowed) so a degraded-but-non-empty turn — ``MALFORMED_FUNCTION_CALL``,
    ``MAX_TOKENS`` — reaches the caller intact.
    """

    candidates = response.candidates
    if not candidates:
        raise GeminiToolCallError(
            "Gemini returned no candidates (likely a safety or prompt block); "
            "there is no model turn to append."
        )
    candidate = candidates[0]
    content = candidate.content
    if content is None or not content.parts:
        reason = candidate.finish_reason
        reason_label = reason.value if reason is not None else "unknown"
        raise GeminiToolCallError(
            "Gemini candidate has no content parts "
            f"(finish_reason={reason_label}); there is no model turn to append."
        )
    return content, candidate.finish_reason


def _join_text_parts(content: genai_types.Content) -> str | None:
    """Concatenate the text of a Content's text parts, or ``None`` if there is none.

    Reads ``part.text`` directly rather than ``response.text`` because the SDK's
    ``.text`` property emits a warning whenever function-call parts are present
    (the normal case on a tool turn). Returns ``None`` for a pure function-call
    turn so the caller can distinguish "the model talked" from "the model only
    called a tool".
    """

    texts = [part.text for part in (content.parts or []) if part.text]
    if not texts:
        return None
    return "".join(texts)
