"""Bibliography models: format-ready citation metadata and rendered entries.

:class:`CitationMetadata` is the union of everything any of the five
supported styles needs to render a single reference. It is built by
:func:`packages.workers.article.bibliography.source_to_citation_metadata`
from a :class:`SourceMetadataExtracted` (parser output) merged with an
optional :class:`DOIMetadata` (CrossRef enrichment), so the formatter
never sees a half-populated source.

:class:`FormattedBibliography` is the formatter's output: a list of
:class:`FormattedEntry` rows alongside the style and language used.
The DOCX exporter consumes these directly without re-running any
formatting.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from packages.core.enums import CitationFormat, SourceType


class CitationMetadata(BaseModel):
    """Format-ready metadata describing one citable source.

    Combines every field used by GOST, APA, IEEE, Chicago, and Vancouver
    in one schema. Style-specific renderers pull the subset they need
    and ignore the rest. ``authors`` use the canonical ``"Last, First"``
    form so each style's helper can split on the comma without ambiguity;
    organisations and single-name authors omit the comma.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=500)
    authors: list[str] = Field(default_factory=list[str], max_length=50)
    year: int | None = Field(default=None, ge=1500, le=2100)

    journal: str | None = Field(default=None, max_length=500)
    volume: str | None = Field(default=None, max_length=50)
    issue: str | None = Field(default=None, max_length=50)
    pages: str | None = Field(default=None, max_length=50)

    publisher: str | None = Field(default=None, max_length=300)
    city: str | None = Field(default=None, max_length=200)
    edition: str | None = Field(default=None, max_length=100)
    total_pages: int | None = Field(default=None, ge=1, le=100_000)

    doi: str | None = Field(default=None, max_length=200)
    url: str | None = Field(default=None, max_length=1000)
    access_date: str | None = Field(default=None, max_length=20)

    source_type: SourceType

    source_id: str | None = Field(default=None, max_length=64)
    citation_number: int | None = Field(default=None, ge=1, le=10_000)


class FormattedEntry(BaseModel):
    """One rendered bibliography line ready for the DOCX exporter.

    ``number`` is set for numbered styles (GOST, IEEE, Vancouver) and
    left ``None`` for alphabetical styles (APA, Chicago bibliography).
    ``formatted_text`` is the full reference exactly as it should
    appear; the exporter is responsible only for hanging-indent layout.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    number: int | None = Field(default=None, ge=1, le=10_000)
    formatted_text: str = Field(min_length=1, max_length=2000)
    source_id: str | None = Field(default=None, max_length=64)
    doi: str | None = Field(default=None, max_length=200)


class FormattedBibliography(BaseModel):
    """Aggregate output of :class:`BibliographyFormatter.format_bibliography`."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    entries: list[FormattedEntry] = Field(default_factory=list[FormattedEntry], max_length=500)
    style: CitationFormat
    language: str = Field(default="en", max_length=8)
    total_entries: int = Field(default=0, ge=0, le=500)
