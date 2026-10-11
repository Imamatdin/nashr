"""Free source extraction, separate from paid interpretation/claim extraction."""

from __future__ import annotations

import asyncio
import hashlib

from pydantic import BaseModel, ConfigDict, Field

from packages.core.models.source import SourceChunkCreate
from packages.workers.source.chunker import SourceChunker
from packages.workers.source.parse_service import SourceParseService
from packages.workers.source.validation import FileValidationService

MAX_PASSAGES = 2000
MAX_EXTRACTED_CHARACTERS = 2_000_000
# Formats whose parser page numbers are real locations (PDF page, slide, image).
# DOCX/text/spreadsheet "pages" are parser sections; citing them as pages would invent a location.
PAGINATED_TYPES = frozenset({"pdf", "pptx", "png", "jpeg", "webp", "gif"})
_validator: FileValidationService | None = None


class ExtractedPassages(BaseModel):
    """Bounded extraction result; IDs are assigned atomically by persistence."""

    model_config = ConfigDict(extra="forbid")

    content_hash: str = Field(min_length=64, max_length=64)
    chunks: list[SourceChunkCreate] = Field(min_length=1, max_length=MAX_PASSAGES)
    warnings: list[str] = Field(default_factory=list, max_length=100)


async def extract_passages(data: bytes, filename: str) -> ExtractedPassages:
    """Validate actual bytes and preserve source locations without any LLM call."""

    global _validator
    if _validator is None:
        # Construction does synchronous model loading; keep it off the event loop.
        _validator = await asyncio.to_thread(FileValidationService)
    validation = await _validator.validate(data, filename)
    if not validation.valid:
        raise ValueError("invalid_source")
    async with asyncio.timeout(180):
        parsed = await SourceParseService().parse(data, filename, validation.detected_type)
    if sum(len(page.text) for page in parsed.pages) > MAX_EXTRACTED_CHARACTERS:
        raise ValueError("source_text_limit")
    chunks = await asyncio.to_thread(SourceChunker().chunk_parsed_source, parsed)
    if not chunks:
        raise ValueError("source_has_no_text")
    if len(chunks) > MAX_PASSAGES:
        raise ValueError("source_passage_limit")
    if validation.detected_type not in PAGINATED_TYPES:
        chunks = [chunk.model_copy(update={"page": None}) for chunk in chunks]
    warnings = [warning[:500] for warning in parsed.parse_errors[:99]]
    if validation.warning:
        warnings.append(validation.warning[:500])
    return ExtractedPassages(
        content_hash=hashlib.sha256(data).hexdigest(), chunks=chunks, warnings=warnings
    )
