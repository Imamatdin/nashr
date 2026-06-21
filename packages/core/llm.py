"""Shared async Anthropic client wrapper used by every LLM-touching worker.

Centralised so the timeout, retry, cost-accounting, and structured-logging
contract from ``.claude/rules/llm-integration.md`` is enforced exactly once
instead of scattered across the article, presentation, and source workers.

* **Timeouts** — every call is wrapped in :func:`asyncio.wait_for` so a
  hanging API connection cannot stall a worker indefinitely.
* **Retries** — transient ``APIError`` / ``RateLimitError`` failures are
  retried with exponential backoff; ``AuthenticationError`` is intentionally
  *not* caught because it indicates a misconfigured key, not a transient
  fault, and silently retrying would only delay the operator's diagnosis.
* **Cost** — token usage is multiplied by the per-million-token price for
  Haiku 4.5 / Sonnet 4.6 to record an estimated cost on every response. The
  numbers come from the SPEC's cost-control table and are intentionally a
  small, immutable surface so cost changes are a one-line edit.
* **Prompt caching** — callers may opt in (``cache=...``) to mark the system
  prompt as a cache breakpoint; the cache-read / cache-write token buckets the
  API returns are then surfaced on the response and priced at their own
  multipliers.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import ClassVar, Final, Literal, NamedTuple

from anthropic import APIError, AsyncAnthropic, AuthenticationError, RateLimitError
from anthropic.types import (
    CacheControlEphemeralParam,
    MessageParam,
    TextBlock,
    TextBlockParam,
)
from pydantic import BaseModel, ConfigDict, Field

from packages.core.constants import DEFAULT_LLM_MAX_RETRIES, DEFAULT_LLM_TIMEOUT_SECONDS

logger = logging.getLogger(__name__)


HAIKU_INPUT_COST_PER_MTOK: float = 1.0
HAIKU_OUTPUT_COST_PER_MTOK: float = 5.0
SONNET_INPUT_COST_PER_MTOK: float = 3.0
SONNET_OUTPUT_COST_PER_MTOK: float = 15.0

# Opus is NOT used at runtime — .claude/rules/llm-integration.md forbids it ("Never use Opus
# for runtime user jobs"). These rates exist ONLY so cost_for cannot silently mis-cost an Opus
# model string as Haiku (the prior substring-routing defect). They are the historical Opus 4.x
# list prices and are UNCONFIRMED for Opus 4.8 — the prompt-caching docs' worked example implies
# a lower input rate. CONFIRM against the official pricing page before any Opus call is added to a
# runtime path.
OPUS_INPUT_COST_PER_MTOK: float = 15.0  # UNCONFIRMED — see note above
OPUS_OUTPUT_COST_PER_MTOK: float = 75.0  # UNCONFIRMED — see note above

DEFAULT_HAIKU_MODEL: str = "claude-haiku-4-5-20251001"

# Cache pricing multipliers vs. the base input price, per the Anthropic prompt-caching docs
# (verified 2026-06-21): a 5-minute cache write costs 1.25x, a 1-hour cache write 2.0x, and a
# cache read 0.1x the base input token price.
_CACHE_READ_MULTIPLIER: Final[float] = 0.10
_CACHE_WRITE_5M_MULTIPLIER: Final[float] = 1.25
_CACHE_WRITE_1H_MULTIPLIER: Final[float] = 2.00

CacheTTL = Literal["5m", "1h"]


class _Rates(NamedTuple):
    """Per-million-token USD prices (input, output) for one model family."""

    input: float
    output: float


_MODEL_RATES: Final[dict[str, _Rates]] = {
    "haiku": _Rates(HAIKU_INPUT_COST_PER_MTOK, HAIKU_OUTPUT_COST_PER_MTOK),
    "sonnet": _Rates(SONNET_INPUT_COST_PER_MTOK, SONNET_OUTPUT_COST_PER_MTOK),
    "opus": _Rates(OPUS_INPUT_COST_PER_MTOK, OPUS_OUTPUT_COST_PER_MTOK),
}


def _rates_for(model: str) -> _Rates:
    """Map a model string to its rate family.

    Checks opus and sonnet BEFORE the Haiku fallback, so an Opus or Sonnet model is never
    mis-costed at the cheaper Haiku rate (the prior substring-routing defect). An unknown
    string falls back to Haiku rather than raising — cost accounting must never fail a job.
    """

    lower = model.lower()
    for family in ("opus", "sonnet", "haiku"):
        if family in lower:
            return _MODEL_RATES[family]
    return _MODEL_RATES["haiku"]


def cached_system_block(text: str, ttl: CacheTTL = "5m") -> TextBlockParam:
    """Wrap a system prompt as a single cache-controlled text block.

    The ``cache_control`` marker places a cache breakpoint at the END of this block, making
    the whole system prompt the cached prefix. Used internally by :meth:`LLMClient.complete`
    when a caller opts in; exposed so tests can assert the exact block shape without
    hand-rolling the SDK JSON.
    """

    return TextBlockParam(
        type="text",
        text=text,
        cache_control=CacheControlEphemeralParam(type="ephemeral", ttl=ttl),
    )


class LLMResponse(BaseModel):
    """Structured response from a single :meth:`LLMClient.complete` call.

    ``estimated_cost_usd`` is computed from the model name and token counts;
    callers should accumulate this on the parent generation job to enforce
    per-job budget caps from :data:`packages.core.constants.JOB_COST_LIMITS`.
    """

    model_config = ConfigDict(extra="forbid")

    content: str = Field(max_length=200_000)
    model: str = Field(min_length=1, max_length=128)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    cache_read_input_tokens: int = Field(default=0, ge=0)
    cache_creation_input_tokens: int = Field(default=0, ge=0)
    latency_ms: int = Field(ge=0)
    estimated_cost_usd: float = Field(ge=0.0)

    HAIKU_INPUT_COST: ClassVar[float] = HAIKU_INPUT_COST_PER_MTOK
    HAIKU_OUTPUT_COST: ClassVar[float] = HAIKU_OUTPUT_COST_PER_MTOK
    SONNET_INPUT_COST: ClassVar[float] = SONNET_INPUT_COST_PER_MTOK
    SONNET_OUTPUT_COST: ClassVar[float] = SONNET_OUTPUT_COST_PER_MTOK
    OPUS_INPUT_COST: ClassVar[float] = OPUS_INPUT_COST_PER_MTOK
    OPUS_OUTPUT_COST: ClassVar[float] = OPUS_OUTPUT_COST_PER_MTOK

    @property
    def total_prompt_tokens(self) -> int:
        """Total prompt tokens billed across all buckets.

        The SDK's ``input_tokens`` counts only the tokens AFTER the last cache breakpoint;
        cache reads and writes are reported separately. This is a plain property (not a
        ``computed_field``) so the model's dict round-trip stays lossless under
        ``extra="forbid"`` — a computed field would serialise and then fail to reconstruct.
        """

        return self.input_tokens + self.cache_read_input_tokens + self.cache_creation_input_tokens

    @classmethod
    def cost_for(
        cls,
        model: str,
        input_tokens: int,
        output_tokens: int,
        *,
        cache_read_input_tokens: int = 0,
        cache_write_5m_input_tokens: int = 0,
        cache_write_1h_input_tokens: int = 0,
    ) -> float:
        """Return the USD cost of one call given its model and token usage.

        The model routes to its rate family (Opus / Sonnet / Haiku) and each input bucket is
        priced at its own multiplier: uncached input at base, cache reads at 0.1x, 5-minute
        cache writes at 1.25x, and 1-hour cache writes at 2.0x. The cache buckets default to
        zero so non-caching call sites and the pure-pricing tests are unaffected. Falls back
        to Haiku pricing for unknown model strings rather than raising, because cost
        accounting must never fail a user-visible job.
        """

        rates = _rates_for(model)
        base_input = rates.input / 1_000_000.0
        return (
            input_tokens * base_input
            + cache_read_input_tokens * base_input * _CACHE_READ_MULTIPLIER
            + cache_write_5m_input_tokens * base_input * _CACHE_WRITE_5M_MULTIPLIER
            + cache_write_1h_input_tokens * base_input * _CACHE_WRITE_1H_MULTIPLIER
            + output_tokens * (rates.output / 1_000_000.0)
        )


class LLMClient:
    """Async Anthropic wrapper enforcing the project's LLM-integration rules.

    The client is intentionally small: it owns one ``AsyncAnthropic``
    instance, exposes a single :meth:`complete` method, and lets workers
    layer their own JSON parsing, validation, and prompt-construction logic
    on top.
    """

    def __init__(
        self,
        client: AsyncAnthropic | None = None,
        timeout_seconds: int = DEFAULT_LLM_TIMEOUT_SECONDS,
        max_retries: int = DEFAULT_LLM_MAX_RETRIES,
    ) -> None:
        self._client = client if client is not None else AsyncAnthropic()
        self._timeout_seconds = timeout_seconds
        self._max_retries = max_retries

    async def complete(
        self,
        system: str,
        user: str,
        model: str = DEFAULT_HAIKU_MODEL,
        max_tokens: int = 2000,
        temperature: float = 0.0,
        timeout: int | None = None,
        cache: bool | CacheTTL = False,
    ) -> LLMResponse:
        """Run one completion with retry, timeout, and cost logging.

        ``timeout`` overrides the client's default per-attempt timeout for THIS
        call only (``None`` keeps the client default). A large generation — the
        editorial executor runs at 16k ``max_tokens`` and can legitimately take
        minutes — passes a longer value so a slow-but-valid completion is not
        cancelled, while small calls (planner, classifier, claim extraction)
        keep the tighter default so a genuine hang still surfaces quickly.

        ``cache`` opts the system prompt into Anthropic prompt caching: ``False``
        (default) sends it as a plain string; ``True`` / ``"5m"`` / ``"1h"`` sends
        it as one cache-controlled block with that TTL. Only worth enabling where
        the same large system prefix repeats within a job (e.g. section drafting),
        since a single-shot call pays the cache-write premium for no later read.
        """

        effective_timeout = timeout if timeout is not None else self._timeout_seconds
        system_param: str | list[TextBlockParam]
        if cache is False:
            system_param = system
        else:
            ttl: CacheTTL = "5m" if cache is True else cache
            system_param = [cached_system_block(system, ttl=ttl)]
        attempt = 0
        last_error: Exception | None = None
        while attempt <= self._max_retries:
            start = time.perf_counter()
            try:
                messages: list[MessageParam] = [{"role": "user", "content": user}]
                message = await asyncio.wait_for(
                    self._client.messages.create(
                        model=model,
                        max_tokens=max_tokens,
                        temperature=temperature,
                        system=system_param,
                        messages=messages,
                    ),
                    timeout=effective_timeout,
                )
            except AuthenticationError:
                raise
            except (RateLimitError, APIError, TimeoutError) as exc:
                last_error = exc
                attempt += 1
                if attempt > self._max_retries:
                    break
                backoff = 2 ** (attempt - 1)
                logger.warning(
                    "LLM call failed; retrying",
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
            content = _extract_text(message)
            usage = message.usage
            input_tokens = int(usage.input_tokens)
            output_tokens = int(usage.output_tokens)
            cache_read = int(usage.cache_read_input_tokens or 0)
            cache_creation = int(usage.cache_creation_input_tokens or 0)
            creation = usage.cache_creation
            if creation is not None:
                write_5m = int(creation.ephemeral_5m_input_tokens or 0)
                write_1h = int(creation.ephemeral_1h_input_tokens or 0)
            else:
                # Older payloads omit the per-TTL split; attribute the whole write to the
                # TTL we asked for (1h only when explicitly requested).
                write_1h = cache_creation if cache == "1h" else 0
                write_5m = cache_creation - write_1h
            cost = LLMResponse.cost_for(
                model,
                input_tokens,
                output_tokens,
                cache_read_input_tokens=cache_read,
                cache_write_5m_input_tokens=write_5m,
                cache_write_1h_input_tokens=write_1h,
            )

            logger.info(
                "llm_call_complete",
                extra={
                    "model": model,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "cache_read_input_tokens": cache_read,
                    "cache_creation_input_tokens": cache_creation,
                    "total_prompt_tokens": input_tokens + cache_read + cache_creation,
                    "latency_ms": latency_ms,
                    "estimated_cost_usd": round(cost, 6),
                },
            )

            return LLMResponse(
                content=content,
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cache_read_input_tokens=cache_read,
                cache_creation_input_tokens=cache_creation,
                latency_ms=latency_ms,
                estimated_cost_usd=cost,
            )

        assert last_error is not None
        raise last_error


def _extract_text(message: object) -> str:
    """Concatenate every ``TextBlock`` in an Anthropic ``Message`` response.

    Non-text blocks (tool-use, etc.) are ignored — workers that need them
    should call the SDK directly rather than through :class:`LLMClient`.
    """

    content_attr = getattr(message, "content", None)
    if not isinstance(content_attr, list):
        return ""
    parts: list[str] = []
    for block in content_attr:  # type: ignore[reportUnknownVariableType]
        if isinstance(block, TextBlock):
            parts.append(block.text)
    return "".join(parts)
