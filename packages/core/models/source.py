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
    tables: list[list[list[str]]] = Field(default_factory=list)


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
    pages: list[ParsedPage] = Field(default_factory=list)
    metadata: SourceMetadataExtracted = Field(default_factory=SourceMetadataExtracted)
    full_text: str = ""
    needs_ocr_pages: list[int] = Field(default_factory=list)
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
