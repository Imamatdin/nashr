"""Plain-text / CSV / Markdown parser.

Decodes UTF-8 with a latin-1 fallback (we never raise on encoding), then splits
into ~2000-character logical pages so the rest of the pipeline can treat text
files uniformly with paged formats.
"""

from __future__ import annotations

import asyncio
import re
from typing import Final

from packages.core.models.source import (
    ParsedPage,
    ParsedSource,
    SourceMetadataExtracted,
)
from packages.workers.source.parsers.lang_detect import detect_language

PAGE_SIZE_CHARS: Final[int] = 2000


class TextParser:
    """Parses plain-text payloads into a :class:`ParsedSource`."""

    async def parse(self, file_bytes: bytes, filename: str) -> ParsedSource:
        return await asyncio.to_thread(self._parse_sync, file_bytes, filename)

    def _parse_sync(self, file_bytes: bytes, filename: str) -> ParsedSource:
        errors: list[str] = []
        decoded, decode_error = _decode(file_bytes)
        if decode_error is not None:
            errors.append(decode_error)

        pages = _paginate(decoded)
        full_text = decoded
        word_count = len(full_text.split()) if full_text else 0
        file_type = _file_type_from_filename(filename)

        metadata = SourceMetadataExtracted(
            page_count=len(pages),
            word_count=word_count,
            language_detected=detect_language(full_text),
        )

        return ParsedSource(
            filename=filename,
            file_type=file_type,
            file_size_bytes=len(file_bytes),
            pages=pages,
            metadata=metadata,
            full_text=full_text,
            needs_ocr_pages=[],
            parse_errors=errors,
        )


def _decode(file_bytes: bytes) -> tuple[str, str | None]:
    try:
        return file_bytes.decode("utf-8"), None
    except UnicodeDecodeError:
        return file_bytes.decode("latin-1", errors="replace"), (
            "Decoded with latin-1 fallback; some characters may be replaced."
        )


def _paginate(text: str) -> list[ParsedPage]:
    if not text:
        return [ParsedPage(page_number=1, text="", char_count=0, needs_ocr=False)]

    pages: list[ParsedPage] = []
    for index, start in enumerate(range(0, len(text), PAGE_SIZE_CHARS)):
        chunk = text[start : start + PAGE_SIZE_CHARS]
        pages.append(
            ParsedPage(
                page_number=index + 1,
                text=chunk,
                char_count=len(re.sub(r"\s+", "", chunk)),
                needs_ocr=False,
            )
        )
    return pages


def _file_type_from_filename(filename: str) -> str:
    lower = filename.lower()
    if lower.endswith(".csv"):
        return "csv"
    if lower.endswith((".md", ".markdown")):
        return "markdown"
    return "txt"
