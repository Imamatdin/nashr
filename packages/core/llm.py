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
* **Models** — every model id is checked against
  :mod:`packages.core.model_registry` before a request is sent, translated to
  the transport's spelling there, and sent with the registry's pinned thinking
  mode. Claude 4.7+ rejects a non-default ``temperature``, so none is sent.
* **Cost** — token usage is priced from the model's registry row, including its
  own cache-read / cache-write rates and long-context tier.
* **Prompt caching** — callers may opt in (``cache=...``) to mark the system
  prompt as a cache breakpoint; the cache-read / cache-write token buckets the
  API returns are then surfaced on the response and priced at their own
  multipliers.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Literal, cast

from anthropic import APIError, AsyncAnthropic, AuthenticationError, RateLimitError
from anthropic.lib.vertex import AsyncAnthropicVertex
from anthropic.types import (
    CacheControlEphemeralParam,
    MessageParam,
    TextBlock,
    TextBlockParam,
)
from pydantic import BaseModel, ConfigDict, Field

from packages.core.constants import DEFAULT_LLM_MAX_RETRIES, DEFAULT_LLM_TIMEOUT_SECONDS
from packages.core.model_registry import (
    DEPLOYED_VERTEX_LOCATIONS,
    Provider,
    Role,
    Transport,
    UnknownModelError,
    model_for,
    spec,
    token_cost_usd,
    transport_id,
)

logger = logging.getLogger(__name__)


# The Claude model a caller gets when it names none (Haiku 5.5, via the registry).
DEFAULT_HAIKU_MODEL: str = model_for(Role.CLAUDE_DEFAULT)

LLMTransport = Literal["vertex", "anthropic"]
ResolvedLLMTransport = Literal["vertex", "anthropic", "injected"]

type AnthropicAsyncClient = AsyncAnthropic | AsyncAnthropicVertex

CacheTTL = Literal["5m", "1h"]


def _registry_transport(transport: ResolvedLLMTransport) -> Transport:
    return Transport.VERTEX_ANTHROPIC if transport == "vertex" else Transport.ANTHROPIC_API


def claude_request_id(model: str, transport: ResolvedLLMTransport, location: str | None) -> str:
    """The id to send for ``model``; unknown models and unserved Vertex locations raise.

    An injected client is addressed with the direct-API spelling (the tests' fakes).
    """

    entry = spec(model)
    if entry.provider is not Provider.ANTHROPIC:
        raise UnknownModelError(f"{model} is not a Claude model")
    return transport_id(entry.key, _registry_transport(transport), location)


def thinking_config(model: str) -> dict[str, str]:
    """The ``thinking`` block pinned for ``model`` (see ``ClaudeThinking``).

    Claude 5.5 models think by default and thinking tokens count against
    ``max_tokens``; pinning it keeps every call single-pass, as the budgets assume.
    """

    mode = spec(model).claude_thinking
    if mode is None:
        raise UnknownModelError(f"{model} records no thinking mode")
    return {"type": mode.value}


def request_body_extras(model: str) -> dict[str, dict[str, str]]:
    """Body fields SDK 0.84 has no types for: the pinned thinking mode and effort.

    Effort is pinned to the model's documented default (sending the default is
    documented as identical to omitting it), so a future default change cannot
    pair the thinking mode with an effort level that rejects it.
    """

    effort = spec(model).claude_effort
    if effort is None:
        raise UnknownModelError(f"{model} records no effort level")
    return {"thinking": thinking_config(model), "output_config": {"effort": effort.value}}


def resolve_llm_transport() -> LLMTransport:
    """Return the configured Claude transport (frozen for the lifetime of one :class:`LLMClient`)."""

    raw = os.environ.get("LLM_TRANSPORT", "vertex").strip().lower()
    if raw == "vertex":
        return "vertex"
    if raw == "anthropic":
        return "anthropic"
    raise ValueError(f"Invalid LLM_TRANSPORT={raw!r}; expected 'vertex' (default) or 'anthropic'.")


def build_default_anthropic_client(
    *, transport: LLMTransport | None = None
) -> AnthropicAsyncClient:
    """Construct the async Claude client for the configured transport.

    * **vertex** (default) — :class:`~anthropic.lib.vertex.AsyncAnthropicVertex`
      against ``VERTEX_PROJECT`` (or ``ANTHROPIC_VERTEX_PROJECT_ID``) and
      ``VERTEX_CLAUDE_REGION`` / ``VERTEX_LOCATION`` (default ``global``).
      Auth uses the same ADC / service-account chain as Gemini
      (``GOOGLE_APPLICATION_CREDENTIALS`` on the worker host).
    * **anthropic** — direct :class:`~anthropic.AsyncAnthropic` API using
      ``ANTHROPIC_API_KEY``. Fallback when Vertex quota or IAM blocks a job.
    """

    chosen = transport or resolve_llm_transport()
    if chosen == "anthropic":
        logger.info("llm client using Anthropic API (direct)")
        return AsyncAnthropic()
    project_id = os.environ.get("VERTEX_PROJECT") or os.environ.get("ANTHROPIC_VERTEX_PROJECT_ID")
    if not project_id:
        raise RuntimeError(
            "LLM_TRANSPORT=vertex requires VERTEX_PROJECT (or ANTHROPIC_VERTEX_PROJECT_ID) "
            "so Claude partner-model calls bill against GCP."
        )
    region = (
        os.environ.get("VERTEX_CLAUDE_REGION")
        or os.environ.get("VERTEX_LOCATION")
        or os.environ.get("CLOUD_ML_REGION")
        or "global"
    )
    if region not in DEPLOYED_VERTEX_LOCATIONS:
        # Refused before the SDK client exists: anthropic 0.84 would build the wrong
        # URL for the us/eu multi-regions, and their 1.1x price is not modeled.
        raise UnknownModelError(
            f"Vertex Claude region {region!r} is not deployed; use one of"
            f" {DEPLOYED_VERTEX_LOCATIONS} (see packages/core/model_registry.py)"
        )
    logger.info(
        "llm client using AnthropicVertex (project=%s, region=%s)",
        project_id,
        region,
    )
    return AsyncAnthropicVertex(project_id=project_id, region=region)


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
    # The thinking share of output_tokens (output_tokens is the billed total).
    thinking_tokens: int = Field(default=0, ge=0)
    # Provider stop reason; "max_tokens" (Claude) / "MAX_TOKENS" (Gemini) = truncated.
    stop_reason: str | None = Field(default=None, max_length=64)
    latency_ms: int = Field(ge=0)
    estimated_cost_usd: float = Field(ge=0.0)

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

        Every bucket is priced from the model's registry row: uncached input, cache
        reads, 5-minute and 1-hour cache writes, and output, at the long-context
        tier when the prompt crosses it. An unregistered model raises, but
        :meth:`LLMClient.complete` refuses one before any request is sent, so a
        finished call is always priceable.
        """

        return token_cost_usd(
            model,
            input_tokens,
            output_tokens,
            cache_read_tokens=cache_read_input_tokens,
            cache_write_5m_tokens=cache_write_5m_input_tokens,
            cache_write_1h_tokens=cache_write_1h_input_tokens,
        )


class LLMClient:
    """Async Claude wrapper enforcing the project's LLM-integration rules.

    The client owns one :class:`~anthropic.AsyncAnthropic` or
    :class:`~anthropic.lib.vertex.AsyncAnthropicVertex` instance (selected
    once at construction from ``LLM_TRANSPORT``), exposes a single
    :meth:`complete` method, and lets workers layer JSON parsing and prompt
    construction on top.
    """

    def __init__(
        self,
        client: AnthropicAsyncClient | None = None,
        timeout_seconds: int = DEFAULT_LLM_TIMEOUT_SECONDS,
        max_retries: int = DEFAULT_LLM_MAX_RETRIES,
        *,
        transport: ResolvedLLMTransport | None = None,
    ) -> None:
        if client is not None:
            self._client: AnthropicAsyncClient | None = client
            self._transport: ResolvedLLMTransport = transport or "injected"
        else:
            # Transport is resolved (env read once) and FROZEN here; the SDK client
            # itself is built lazily on first use so merely constructing an LLMClient
            # on a box without Vertex env (unit tests, article drafter defaults,
            # import-time construction) cannot crash. The first real Claude call
            # still fails fast with the explicit VERTEX_PROJECT message.
            self._transport = resolve_llm_transport()
            self._client = None
        self._timeout_seconds = timeout_seconds
        self._max_retries = max_retries

    @property
    def transport(self) -> ResolvedLLMTransport:
        """Transport frozen at construction — never flips mid-run."""

        return self._transport

    def _ensure_client(self) -> AnthropicAsyncClient:
        if self._client is None:
            if self._transport == "injected":
                raise RuntimeError("injected transport requires a client at construction")
            self._client = build_default_anthropic_client(transport=self._transport)
        return self._client

    async def complete(
        self,
        system: str,
        user: str,
        model: str = DEFAULT_HAIKU_MODEL,
        max_tokens: int = 2000,
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

        llm_client = self._ensure_client()
        # Translated once here so the API call, cost, logs and response all agree.
        location = getattr(llm_client, "region", None) if self._transport == "vertex" else None
        model = claude_request_id(model, self._transport, location)
        body_extras = request_body_extras(model)
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
                    llm_client.messages.create(
                        model=model,
                        max_tokens=max_tokens,
                        system=system_param,
                        messages=messages,
                        extra_body=body_extras,
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
            thinking_tokens = _thinking_tokens(usage)
            stop_reason = message.stop_reason
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

            # Payload in the message string, not extra: the docker log
            # formatter drops extra, hiding token/cost telemetry.
            logger.info(
                "llm_call_complete %s",
                json.dumps(
                    {
                        "model": model,
                        "input_tokens": input_tokens,
                        "output_tokens": output_tokens,
                        "cache_read_input_tokens": cache_read,
                        "cache_creation_input_tokens": cache_creation,
                        "total_prompt_tokens": input_tokens + cache_read + cache_creation,
                        "thinking_tokens": thinking_tokens,
                        "stop_reason": stop_reason,
                        "latency_ms": latency_ms,
                        "estimated_cost_usd": round(cost, 6),
                    }
                ),
            )

            return LLMResponse(
                content=content,
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cache_read_input_tokens=cache_read,
                cache_creation_input_tokens=cache_creation,
                thinking_tokens=thinking_tokens,
                stop_reason=stop_reason,
                latency_ms=latency_ms,
                estimated_cost_usd=cost,
            )

        assert last_error is not None
        raise last_error


def _thinking_tokens(usage: object) -> int:
    """``usage.output_tokens_details.thinking_tokens`` (a subset of output_tokens).

    SDK 0.84's ``Usage`` has no field for it; the model keeps unknown fields, so
    it is read from the extras, as a dict or an object.
    """

    extra: object = getattr(usage, "model_extra", None)
    details: object = (
        cast("dict[str, object]", extra).get("output_tokens_details")
        if isinstance(extra, dict)
        else None
    )
    raw: object = (
        cast("dict[str, object]", details).get("thinking_tokens")
        if isinstance(details, dict)
        else getattr(details, "thinking_tokens", None)
    )
    return raw if isinstance(raw, int) and raw >= 0 else 0


def _extract_text(message: object) -> str:
    """Concatenate every ``TextBlock`` in an Anthropic ``Message`` response.

    Non-text blocks (thinking, tool-use, etc.) are ignored — workers that need them
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
