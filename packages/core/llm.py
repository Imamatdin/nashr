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
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import ClassVar

from anthropic import APIError, AsyncAnthropic, AuthenticationError, RateLimitError
from anthropic.types import MessageParam, TextBlock
from pydantic import BaseModel, ConfigDict, Field

from packages.core.constants import DEFAULT_LLM_MAX_RETRIES, DEFAULT_LLM_TIMEOUT_SECONDS

logger = logging.getLogger(__name__)


HAIKU_INPUT_COST_PER_MTOK: float = 1.0
HAIKU_OUTPUT_COST_PER_MTOK: float = 5.0
SONNET_INPUT_COST_PER_MTOK: float = 3.0
SONNET_OUTPUT_COST_PER_MTOK: float = 15.0

DEFAULT_HAIKU_MODEL: str = "claude-haiku-4-5-20251001"


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
    latency_ms: int = Field(ge=0)
    estimated_cost_usd: float = Field(ge=0.0)

    HAIKU_INPUT_COST: ClassVar[float] = HAIKU_INPUT_COST_PER_MTOK
    HAIKU_OUTPUT_COST: ClassVar[float] = HAIKU_OUTPUT_COST_PER_MTOK
    SONNET_INPUT_COST: ClassVar[float] = SONNET_INPUT_COST_PER_MTOK
    SONNET_OUTPUT_COST: ClassVar[float] = SONNET_OUTPUT_COST_PER_MTOK

    @classmethod
    def cost_for(cls, model: str, input_tokens: int, output_tokens: int) -> float:
        """Return the USD cost of one call given its model and token usage.

        Falls back to Haiku pricing for unknown model strings rather than
        raising, because cost accounting must never fail a user-visible job.
        """

        lower = model.lower()
        if "sonnet" in lower:
            input_rate = cls.SONNET_INPUT_COST
            output_rate = cls.SONNET_OUTPUT_COST
        else:
            input_rate = cls.HAIKU_INPUT_COST
            output_rate = cls.HAIKU_OUTPUT_COST
        return (input_tokens / 1_000_000.0) * input_rate + (
            output_tokens / 1_000_000.0
        ) * output_rate


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
    ) -> LLMResponse:
        """Run one completion with retry, timeout, and cost logging.

        ``timeout`` overrides the client's default per-attempt timeout for THIS
        call only (``None`` keeps the client default). A large generation — the
        editorial executor runs at 16k ``max_tokens`` and can legitimately take
        minutes — passes a longer value so a slow-but-valid completion is not
        cancelled, while small calls (planner, classifier, claim extraction)
        keep the tighter default so a genuine hang still surfaces quickly.
        """

        effective_timeout = timeout if timeout is not None else self._timeout_seconds
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
                        system=system,
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
            input_tokens = int(message.usage.input_tokens)
            output_tokens = int(message.usage.output_tokens)
            cost = LLMResponse.cost_for(model, input_tokens, output_tokens)

            logger.info(
                "llm_call_complete",
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
