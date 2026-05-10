"""Extracts factual claims from chunked source text using the LLM.

This is the first LLM-touching module in the source pipeline; it uses
:class:`packages.core.llm.LLMClient` for the call itself and the prompt
constants from :mod:`packages.core.prompts` for the message bodies.

The extractor is deliberately tolerant of bad model output:

* JSON parse failures trigger one retry with an explicit "respond with only
  JSON" suffix. If the second attempt also fails we log the error and
  return ``[]`` for that chunk rather than crashing the pipeline — losing
  one chunk's claims is far better than failing the whole upload.
* Per-claim validation goes through :class:`SourceClaimCreate`. Items that
  violate the schema (out-of-range length, invalid strength enum) are
  filtered out individually so a single bad claim does not poison the rest.
* Concurrency is bounded with :data:`CLAIM_BATCH_SIZE`. Anthropic enforces
  per-key rate limits and the job-cost budget cap from the SPEC means we
  cannot afford to fan out unbounded — five concurrent calls is the
  observed sweet spot for Haiku throughput without tripping rate limits.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Final

from pydantic import ValidationError

from packages.core.enums import ClaimStrength
from packages.core.llm import LLMClient
from packages.core.models.source import (
    SourceChunkCreate,
    SourceClaimCreate,
    SourceMetadataExtracted,
)
from packages.core.prompts import (
    CLAIM_EXTRACTION_RETRY_SUFFIX,
    CLAIM_EXTRACTION_SYSTEM,
    CLAIM_EXTRACTION_USER,
)

logger = logging.getLogger(__name__)


CLAIM_BATCH_SIZE: Final[int] = 5
CLAIM_MIN_TEXT_LENGTH: Final[int] = 10
CLAIM_MAX_TEXT_LENGTH: Final[int] = 500
CLAIM_MAX_QUOTE_LENGTH: Final[int] = 500


class ClaimExtractor:
    """Extracts :class:`SourceClaimCreate` objects from a stream of chunks."""

    def __init__(self, llm: LLMClient | None = None) -> None:
        self._llm = llm if llm is not None else LLMClient()

    async def extract_claims(
        self,
        chunks: list[SourceChunkCreate],
        source_metadata: SourceMetadataExtracted,
    ) -> list[SourceClaimCreate]:
        """Run claim extraction over every chunk, batched for concurrency.

        Returns a flat list of every claim produced; chunk-to-claim mapping
        is preserved through ``source_chunk_id``, which the caller will
        rewrite once chunks are persisted and given UUIDs.
        """

        source_context = _format_source_context(source_metadata)
        results: list[SourceClaimCreate] = []
        for batch_start in range(0, len(chunks), CLAIM_BATCH_SIZE):
            batch = chunks[batch_start : batch_start + CLAIM_BATCH_SIZE]
            batch_results = await asyncio.gather(
                *(self.extract_claims_from_chunk(chunk, source_context) for chunk in batch)
            )
            for claim_list in batch_results:
                results.extend(claim_list)
        return results

    async def extract_claims_from_chunk(
        self,
        chunk: SourceChunkCreate,
        source_context: str,
    ) -> list[SourceClaimCreate]:
        """Extract claims from one chunk; returns ``[]`` on unrecoverable errors."""

        user_prompt = CLAIM_EXTRACTION_USER.format(
            source_context=source_context, chunk_text=chunk.text
        )

        raw_items = await self._call_with_json_retry(CLAIM_EXTRACTION_SYSTEM, user_prompt)
        if raw_items is None:
            return []
        return _items_to_claims(raw_items)

    async def _call_with_json_retry(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> list[dict[str, Any]] | None:
        """Call the LLM, retry once on bad JSON, return ``None`` on final failure."""

        first_response = await self._llm.complete(system=system_prompt, user=user_prompt)
        parsed = _try_parse_array(first_response.content)
        if parsed is not None:
            return parsed

        retry_prompt = user_prompt + CLAIM_EXTRACTION_RETRY_SUFFIX
        second_response = await self._llm.complete(system=system_prompt, user=retry_prompt)
        parsed = _try_parse_array(second_response.content)
        if parsed is not None:
            return parsed

        logger.error(
            "claim_extractor_json_parse_failed",
            extra={"first_excerpt": first_response.content[:200]},
        )
        return None


def _format_source_context(metadata: SourceMetadataExtracted) -> str:
    """Build the human-readable source citation string for the system prompt."""

    title = (metadata.title or "").strip()
    authors = [author.strip() for author in metadata.authors if author.strip()]
    year = metadata.year

    if not title and not authors and year is None:
        return "Unknown source"

    parts: list[str] = []
    if title:
        parts.append(title)
    if authors:
        parts.append(f"by {', '.join(authors)}")
    if year is not None:
        parts.append(f"({year})")
    return " ".join(parts)


def _try_parse_array(content: str) -> list[dict[str, Any]] | None:
    """Parse an LLM string as a top-level JSON array of objects.

    Returns ``None`` for any failure mode (not JSON, not an array, contains
    non-object items) so the caller can decide whether to retry or give up.
    Strips one layer of triple-backtick fenced markdown — Haiku occasionally
    wraps responses in fences despite the system prompt.
    """

    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[len("json") :]
        text = text.strip()
    try:
        loaded = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(loaded, list):
        return None
    items: list[dict[str, Any]] = []
    for item in loaded:  # type: ignore[reportUnknownVariableType]
        if isinstance(item, dict):
            items.append(item)  # type: ignore[reportUnknownArgumentType]
        else:
            return None
    return items


def _items_to_claims(items: list[dict[str, Any]]) -> list[SourceClaimCreate]:
    """Validate raw LLM dicts into :class:`SourceClaimCreate` objects.

    Each item is validated independently; bad items (length out of range,
    unknown strength enum, missing fields) are silently dropped so one bad
    suggestion does not invalidate the rest of the chunk's claims.
    """

    claims: list[SourceClaimCreate] = []
    for raw in items:
        claim_text_obj = raw.get("claim_text")
        quote_obj = raw.get("quote")
        strength_obj = raw.get("strength")

        if not isinstance(claim_text_obj, str):
            continue
        claim_text = claim_text_obj.strip()
        if len(claim_text) < CLAIM_MIN_TEXT_LENGTH or len(claim_text) > CLAIM_MAX_TEXT_LENGTH:
            continue

        if not isinstance(strength_obj, str):
            continue
        try:
            strength = ClaimStrength(strength_obj)
        except ValueError:
            continue

        quote: str | None
        if quote_obj is None:
            quote = None
        elif isinstance(quote_obj, str):
            quote = quote_obj.strip()[:CLAIM_MAX_QUOTE_LENGTH]
            if not quote:
                quote = None
        else:
            quote = None

        try:
            claims.append(
                SourceClaimCreate(
                    claim_text=claim_text,
                    quote=quote,
                    strength=strength,
                )
            )
        except ValidationError:
            continue
    return claims


__all__ = ["ClaimExtractor"]
