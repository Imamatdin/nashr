"""Splits a :class:`ParsedSource` into overlapping chunks for downstream LLM use.

The chunker is the bridge between the parsing/OCR layer and everything that
needs bounded-context input — claim extraction now, embeddings and evidence
matrix lookups later. It is intentionally pure synchronous Python:

* No LLM calls. Chunking is deterministic so identical inputs always produce
  identical chunks (load-bearing for embedding caches and golden tests).
* Page-first splitting. Each :class:`ParsedPage` is chunked independently so
  the resulting :class:`SourceChunkCreate` can carry the originating page
  number — citations need that level of provenance.
* Sentence-aware boundaries. We try ``.``/``!``/``?`` first, fall back to
  whitespace, and only hard-cut when neither exists (e.g. a 5 KB URL with no
  punctuation). The fallback order avoids splitting a sentence mid-word.
* Overlap. Each subsequent chunk starts ``CHUNK_OVERLAP`` characters before
  the previous one ended, so a fact straddling a boundary still appears
  whole in at least one chunk.
* Trailing-text merging. If the residue after a split is shorter than
  ``MIN_CHUNK_SIZE`` it is appended to the previous chunk instead of
  emitting a tiny stub that costs an LLM call but conveys little.
"""

from __future__ import annotations

import re
from typing import Final

from packages.core.models.source import (
    ParsedSource,
    SourceChunkCreate,
)

_SENTENCE_END_RE: Final[re.Pattern[str]] = re.compile(r"[.!?](?=\s|$)")


class SourceChunker:
    """Splits parsed source text into overlapping chunks for processing."""

    CHUNK_SIZE: int = 2000
    CHUNK_OVERLAP: int = 200
    MIN_CHUNK_SIZE: int = 100

    def chunk_parsed_source(self, parsed: ParsedSource) -> list[SourceChunkCreate]:
        """Split a :class:`ParsedSource` into chunks, preserving page boundaries.

        Empty pages (``char_count == 0``) are skipped so the chunk stream
        contains only chunks with extractable content. ``chunk_index`` is a
        single global counter across all pages so consumers can rely on it
        being dense (0, 1, 2, ...).
        """

        chunks: list[SourceChunkCreate] = []
        next_index = 0
        for page in parsed.pages:
            if page.char_count == 0:
                continue
            for raw_chunk in self._split_text(page.text):
                chunks.append(
                    SourceChunkCreate(
                        chunk_index=next_index,
                        text=raw_chunk,
                        page=page.page_number,
                        is_ocr=page.is_ocr,
                        confidence=page.ocr_confidence,
                    )
                )
                next_index += 1
        return chunks

    def _split_text(self, text: str) -> list[str]:
        """Return one or more chunk strings for a single page's text.

        For pages at or below :attr:`CHUNK_SIZE` the page is emitted as a
        single chunk (no splitting cost, no overlap). Larger pages are
        split using :meth:`_find_split_point` and an overlap window. The
        tail-merge guard runs in two places: when the natural split would
        leave a sub-:attr:`MIN_CHUNK_SIZE` tail, the tail is absorbed into
        the chunk that would have preceded it; and on the final iteration
        if the residue is below the minimum it is appended to the prior
        chunk. Both prevent us from ever emitting a chunk smaller than
        :attr:`MIN_CHUNK_SIZE`.
        """

        if not text:
            return []
        if len(text) <= self.CHUNK_SIZE:
            return [text]

        chunks: list[str] = []
        start = 0
        n = len(text)
        while start < n:
            end_target = start + self.CHUNK_SIZE
            if end_target >= n:
                remainder = text[start:n]
                if chunks and len(remainder) < self.MIN_CHUNK_SIZE:
                    chunks[-1] = chunks[-1] + remainder
                else:
                    chunks.append(remainder)
                break

            split_point = self._find_split_point(text, start, end_target)
            if n - split_point < self.MIN_CHUNK_SIZE:
                chunks.append(text[start:n])
                break
            chunks.append(text[start:split_point])
            next_start = split_point - self.CHUNK_OVERLAP
            if next_start <= start:
                next_start = split_point
            start = next_start
        return chunks

    def _find_split_point(self, text: str, start: int, end_target: int) -> int:
        """Find the best position to end a chunk at or before ``end_target``.

        Search order: nearest sentence terminator within the last 20 % of
        the window → nearest whitespace within the window → hard cut at
        ``end_target``. ``end_target`` is exclusive (slice end).
        """

        window_text = text[start:end_target]
        soft_zone_start = max(0, int(len(window_text) * 0.8))
        soft_zone = window_text[soft_zone_start:]

        last_sentence_match: re.Match[str] | None = None
        for match in _SENTENCE_END_RE.finditer(soft_zone):
            last_sentence_match = match
        if last_sentence_match is not None:
            return start + soft_zone_start + last_sentence_match.end()

        last_space = window_text.rfind(" ")
        if last_space >= 0 and last_space > 0:
            return start + last_space + 1

        return end_target


__all__ = ["SourceChunker"]
