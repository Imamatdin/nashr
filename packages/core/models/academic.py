"""Academic-search transport models.

Used by :mod:`packages.academic` to normalise responses from Semantic Scholar,
arXiv, OpenAlex, and CrossRef into one shape, and to carry full citation
metadata resolved from a DOI back to the article worker for bibliography
formatting. These are wire/transport types — no DB id/timestamp columns.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from packages.core.enums import AcademicAPI


class AcademicPaper(BaseModel):
    """One paper found via an academic-search API.

    The same paper may be returned by multiple providers; deduplication is
    performed by :class:`packages.academic.search.AcademicSearchService` using
    ``doi`` as the join key. Papers without a DOI are never deduplicated
    because their identity cannot be established across APIs.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=500)
    authors: list[str] = Field(default_factory=list, max_length=20)
    year: int | None = Field(default=None, ge=1500, le=2100)
    abstract: str | None = Field(default=None, max_length=5000)
    doi: str | None = Field(default=None, max_length=200)
    citation_count: int | None = Field(default=None, ge=0)
    pdf_url: str | None = Field(default=None, max_length=1000)
    source_api: AcademicAPI
    external_id: str = Field(min_length=1, max_length=500)
    journal: str | None = Field(default=None, max_length=500)


class AcademicSearchResult(BaseModel):
    """Aggregate result of one federated search across all providers.

    ``errors`` is non-empty when at least one provider failed; the search as a
    whole still succeeds as long as any one provider returned data, which is
    why provider exceptions become entries here rather than propagating.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    query: str = Field(max_length=500)
    papers: list[AcademicPaper] = Field(default_factory=list[AcademicPaper], max_length=100)
    total_found: int = Field(default=0, ge=0)
    errors: list[str] = Field(default_factory=list, max_length=20)
    search_time_ms: int = Field(default=0, ge=0)


class DOIMetadata(BaseModel):
    """Full citation metadata for one DOI, resolved via CrossRef.

    Fed into the bibliography formatter (GOST / APA / IEEE) so users uploading
    a PDF whose metadata exposes a DOI get a perfectly-formatted reference
    without typing anything.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    doi: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=500)
    authors: list[str] = Field(default_factory=list, max_length=50)
    year: int | None = Field(default=None, ge=1500, le=2100)
    journal: str | None = Field(default=None, max_length=500)
    volume: str | None = Field(default=None, max_length=50)
    issue: str | None = Field(default=None, max_length=50)
    pages: str | None = Field(default=None, max_length=50)
    publisher: str | None = Field(default=None, max_length=300)
    doc_type: str | None = Field(default=None, max_length=100)
    url: str | None = Field(default=None, max_length=1000)
