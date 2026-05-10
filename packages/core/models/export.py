"""DOCX export models: input metadata and the rendered file result.

The DOCX exporter takes an :class:`ArticleDraftResult` plus this
:class:`ArticleExportMetadata` (university, supervisor, author, etc.)
and returns an :class:`ExportResult` containing the file bytes plus
counters that the bot/API layer logs and shows back to the user.

Both models are pure data containers — they carry no behaviour.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from packages.core.enums import ArticleStructure, CitationFormat


class ArticleExportMetadata(BaseModel):
    """Submission metadata that lives outside the article draft.

    The user supplies this through the bot/API at export time. Title,
    author, and city are required; everything else is optional and the
    title page adapts to whatever is present (no university line, no
    supervisor block) without breaking the layout.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=500)
    author_name: str = Field(min_length=1, max_length=200)
    author_group: str | None = Field(default=None, max_length=100)
    supervisor_name: str | None = Field(default=None, max_length=200)
    supervisor_title: str | None = Field(default=None, max_length=200)
    university_name: str | None = Field(default=None, max_length=300)
    faculty_name: str | None = Field(default=None, max_length=300)
    department_name: str | None = Field(default=None, max_length=300)
    city: str = Field(default="Toshkent", min_length=1, max_length=100)
    year: int | None = Field(default=None, ge=1900, le=2200)
    article_type: ArticleStructure
    citation_format: CitationFormat
    keywords: list[str] = Field(default_factory=list[str], max_length=15)
    abstract_text: str | None = Field(default=None, max_length=2000)


class ExportResult(BaseModel):
    """Output of :meth:`DOCXExporter.export`.

    ``file_bytes`` is the raw DOCX payload (a ZIP container of XML
    parts). It survives :meth:`pydantic.BaseModel.model_dump_json` via
    Pydantic's native bytes encoding and round-trips losslessly through
    :meth:`model_validate`. Counters are derived during build so callers
    don't need to re-open the file to surface them in admin/UI views.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    file_bytes: bytes
    filename: str = Field(min_length=1, max_length=300)
    file_size_bytes: int = Field(ge=0)
    page_count_estimate: int = Field(ge=0)
    word_count: int = Field(ge=0)
    section_count: int = Field(ge=0)
    citation_count: int = Field(ge=0)
    bibliography_count: int = Field(ge=0)
    warnings: list[str] = Field(default_factory=list[str], max_length=50)


class PDFExportResult(BaseModel):
    """Output of :meth:`PDFExporter.export` — the DOCX→PDF conversion.

    On the success path ``file_bytes`` holds the rendered PDF and
    ``error`` is ``None``. On failure (LibreOffice missing, conversion
    timeout, corrupt input) ``success`` is ``False``, ``file_bytes`` is
    empty, ``file_size_bytes`` is 0, and ``error`` carries a human-
    readable explanation. Callers always get a value back; they never
    need a try/except around the exporter.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    file_bytes: bytes
    filename: str = Field(min_length=1, max_length=300)
    file_size_bytes: int = Field(ge=0)
    source_docx_size: int = Field(ge=0)
    conversion_time_ms: int = Field(ge=0)
    success: bool = True
    error: str | None = Field(default=None, max_length=2000)


class ArticleExportBundle(BaseModel):
    """Both DOCX and PDF outputs of a single article export job.

    The DOCX is the canonical, edit-friendly artefact; the PDF is the
    layout-locked version produced by piping the DOCX through
    LibreOffice. Both are returned together so the caller (bot, API,
    admin) can hand the user whichever they ask for without re-running
    the exporter.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    docx: ExportResult
    pdf: PDFExportResult
