"""Source-file models: uploaded artifacts, parsed chunks, and extracted claims."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from packages.core.constants import MAX_FILE_SIZE_BYTES
from packages.core.enums import ClaimStrength, FileType, SourceQuality


class SourceMetadata(BaseModel):
    """Parsed/derived metadata about a single uploaded source file."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str | None = Field(default=None, max_length=500)
    authors: list[str] = Field(default_factory=list)
    year: int | None = Field(default=None, ge=1500, le=2100)
    doi: str | None = Field(default=None, max_length=200)
    page_count: int | None = Field(default=None, ge=0)
    ocr_confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class SourceCreate(BaseModel):
    """Payload sent when registering a freshly uploaded source."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    project_id: UUID
    filename: str = Field(min_length=1, max_length=255)
    file_type: FileType
    file_size_bytes: int = Field(gt=0, le=MAX_FILE_SIZE_BYTES)
    storage_key: str = Field(min_length=1, max_length=512)


class Source(BaseModel):
    """Persisted source record."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: UUID = Field(default_factory=uuid4)
    project_id: UUID
    filename: str = Field(min_length=1, max_length=255)
    file_type: FileType
    file_size_bytes: int = Field(gt=0, le=MAX_FILE_SIZE_BYTES)
    storage_key: str = Field(min_length=1, max_length=512)
    quality: SourceQuality = SourceQuality.MEDIUM
    metadata: SourceMetadata = Field(default_factory=SourceMetadata)
    parsed_text: str | None = None
    ocr_used: bool = False
    created_at: datetime


class SourceChunk(BaseModel):
    """One contiguous chunk of parsed text from a source."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: UUID = Field(default_factory=uuid4)
    source_id: UUID
    project_id: UUID
    chunk_index: int = Field(ge=0)
    text: str = Field(min_length=1, max_length=10_000)
    page: int | None = Field(default=None, ge=1)
    is_ocr: bool = False
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    created_at: datetime


class SourceClaim(BaseModel):
    """A specific evidentiary claim extracted from a source chunk."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: UUID = Field(default_factory=uuid4)
    source_chunk_id: UUID
    project_id: UUID
    claim_text: str = Field(min_length=1, max_length=2000)
    quote: str = Field(min_length=1, max_length=2000)
    strength: ClaimStrength
    created_at: datetime


class SourceChunkCreate(BaseModel):
    """Pre-persistence representation of a chunk emitted by :class:`SourceChunker`.

    ``source_id`` and ``project_id`` are filled in by the caller after the
    parent :class:`Source` row is written; the chunker itself emits them as
    empty strings so it can stay decoupled from persistence concerns. Text
    intentionally is *not* whitespace-stripped here — chunk overlap math
    relies on byte-exact slices of the parent page.
    """

    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(default="", max_length=64)
    project_id: str = Field(default="", max_length=64)
    chunk_index: int = Field(ge=0)
    text: str = Field(min_length=1, max_length=10_000)
    page: int | None = Field(default=None, ge=1)
    is_ocr: bool = False
    confidence: float | None = Field(default=None, ge=0.0, le=100.0)


class SourceClaimCreate(BaseModel):
    """Pre-persistence representation of a single claim emitted by the extractor."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    source_chunk_id: str = Field(default="", max_length=64)
    project_id: str = Field(default="", max_length=64)
    claim_text: str = Field(min_length=10, max_length=500)
    quote: str | None = Field(default=None, max_length=300)
    strength: ClaimStrength


class ParsedPage(BaseModel):
    """A single page (or logical section) extracted from a source file.

    For PDFs each page is one entry; for DOCX each ``Heading 1`` section is
    one entry; for PPTX each slide is one entry; for plain text a fixed-size
    chunk; for images a single entry with ``needs_ocr=True`` and empty text.
    """

    model_config = ConfigDict(extra="forbid")

    page_number: int = Field(ge=1)
    text: str = ""
    char_count: int = Field(ge=0)
    needs_ocr: bool = False
    headings: list[str] = Field(default_factory=list)
    tables: list[list[list[str]]] = Field(default_factory=list[list[list[str]]])
    ocr_confidence: float | None = Field(default=None, ge=0.0, le=100.0)
    is_ocr: bool = False


class OCRResult(BaseModel):
    """Result of OCR processing on a single page or image.

    ``average_confidence`` is the mean Tesseract per-word confidence on the
    accepted (non-empty, non-``-1``) words, on a 0–100 scale. ``success`` is
    True even when the page is blank — only crashes/timeouts flip it to False.
    """

    model_config = ConfigDict(extra="forbid")

    text: str = Field(default="", max_length=200_000)
    word_count: int = Field(default=0, ge=0)
    average_confidence: float = Field(default=0.0, ge=0.0, le=100.0)
    low_confidence_words: int = Field(default=0, ge=0)
    language_detected: str | None = Field(default=None, max_length=8)
    processing_time_ms: int = Field(default=0, ge=0)
    success: bool = True
    error: str | None = Field(default=None, max_length=500)


class SourceMetadataExtracted(BaseModel):
    """Metadata pulled directly out of a file by its parser (not user-supplied)."""

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, max_length=500)
    authors: list[str] = Field(default_factory=list)
    year: int | None = Field(default=None, ge=1500, le=2100)
    doi: str | None = Field(default=None, max_length=200)
    page_count: int = Field(default=0, ge=0)
    word_count: int = Field(default=0, ge=0)
    language_detected: str | None = Field(default=None, max_length=8)
    has_images: bool = False
    creation_date: str | None = Field(default=None, max_length=64)


class ParsedSource(BaseModel):
    """The complete parse result for one uploaded file."""

    model_config = ConfigDict(extra="forbid")

    filename: str = Field(min_length=1, max_length=255)
    file_type: str = Field(min_length=1, max_length=32)
    file_size_bytes: int = Field(ge=0)
    pages: list[ParsedPage] = Field(default_factory=list[ParsedPage])
    metadata: SourceMetadataExtracted = Field(default_factory=SourceMetadataExtracted)
    full_text: str = ""
    needs_ocr_pages: list[int] = Field(default_factory=list[int])
    parse_errors: list[str] = Field(default_factory=list)


class FileValidationResult(BaseModel):
    """Outcome of running an upload through the Magika-backed validator.

    ``valid`` is the only field callers should branch on. ``warning`` is
    informational (e.g. extension does not match content type) and does NOT
    cause rejection; ``rejection_reason`` is set if and only if ``valid`` is
    False.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    valid: bool
    detected_type: str = Field(min_length=1, max_length=64)
    mime_type: str = Field(min_length=1, max_length=128)
    confidence: float = Field(ge=0.0, le=1.0)
    file_size_bytes: int = Field(ge=0)
    extension_mismatch: bool = False
    rejection_reason: str | None = Field(default=None, max_length=500)
    warning: str | None = Field(default=None, max_length=500)


class SourcePipelineResult(BaseModel):
    """End-to-end output of :class:`SourcePipeline.process` for one upload.

    ``parsed`` is ``None`` only when validation rejected the file; in that case
    ``chunks`` and ``claims`` are empty and ``errors`` contains the rejection
    reason. Non-fatal warnings (empty extracted text, partial OCR, claim
    extractor JSON failures) are appended to ``errors`` without short-
    circuiting the pipeline.
    """

    model_config = ConfigDict(extra="forbid")

    validation: FileValidationResult
    parsed: ParsedSource | None = None
    chunks: list[SourceChunkCreate] = Field(
        default_factory=list[SourceChunkCreate], max_length=10_000
    )
    claims: list[SourceClaimCreate] = Field(
        default_factory=list[SourceClaimCreate], max_length=50_000
    )
    errors: list[str] = Field(default_factory=list[str], max_length=100)
