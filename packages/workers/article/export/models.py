"""Transport-neutral input and output types for the one article exporter.

Neither the web route nor the bot talk to the builder in their own vocabulary:
both resolve their data into an :class:`ArticleExportInput` first (the bot via
``adapter.py``). The builder and compliance checker then operate only on these
types and perform no I/O, no database access, and no model calls.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from packages.core.enums import ArticleStructure, CitationFormat, Language
from packages.core.models.bibliography import CitationMetadata, FormattedBibliography
from packages.core.models.document import ArticleDocumentContent
from packages.workers.article.export.profiles import ArticleProfileId, get_profile


class UnresolvedCitationError(ValueError):
    """A block cited a source id that the resolved ``sources`` map does not carry.

    Raised by the builder instead of printing a raw ``[<uuid>]`` marker: an
    article with a dangling citation is a defect the caller must settle, not a
    document we ship with a broken reference in it.
    """

    def __init__(self, source_id: str) -> None:
        self.source_id = source_id
        super().__init__(f"article citation references unknown source {source_id!r}")


class ArticleAuthorship(BaseModel):
    """Document-level authorship and institution metadata for the title page.

    Every field is optional except what a given title-page style needs; the
    builder suppresses lines whose metadata is absent rather than printing empty
    labels. Bounds mirror :class:`packages.core.models.export.ArticleExportMetadata`.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    author_name: str | None = Field(default=None, max_length=200)
    author_group: str | None = Field(default=None, max_length=100)
    supervisor_name: str | None = Field(default=None, max_length=200)
    supervisor_title: str | None = Field(default=None, max_length=200)
    university_name: str | None = Field(default=None, max_length=300)
    faculty_name: str | None = Field(default=None, max_length=300)
    department_name: str | None = Field(default=None, max_length=300)
    city: str | None = Field(default=None, max_length=100)
    year: int | None = Field(default=None, ge=1900, le=2200)


class ArticleExportInput(BaseModel):
    """Everything the one exporter needs to build a DOCX, resolved by the caller."""

    model_config = ConfigDict(extra="forbid")

    content: ArticleDocumentContent
    profile_id: ArticleProfileId
    language: Language
    citation_style: CitationFormat
    authorship: ArticleAuthorship = Field(default_factory=ArticleAuthorship)
    # Drives the student title page and front matter for the bot path; the web
    # path leaves it None and relies on the profile's title-page style.
    article_type: ArticleStructure | None = None
    abstract: str | None = Field(default=None, max_length=5_000)
    keywords: list[str] = Field(default_factory=list[str], max_length=30)
    # A Word TOC field after the title page (kurs ishi and similar long works).
    # The web path leaves this False; the field populates on open in Word.
    include_toc: bool = False
    # source_id (str form of the citation's UUID) -> resolved citation metadata.
    sources: dict[str, CitationMetadata] = Field(default_factory=dict[str, CitationMetadata])

    @model_validator(mode="after")
    def _profile_exists(self) -> ArticleExportInput:
        get_profile(self.profile_id)  # raises KeyError on an unknown id
        return self


class BuiltArticle(BaseModel):
    """The builder's result: the DOCX bytes plus what it rendered."""

    model_config = ConfigDict(extra="forbid")

    docx_bytes: bytes
    filename: str = Field(min_length=1, max_length=300)
    bibliography: FormattedBibliography
    # Cited source ids in first-appearance order (what the bibliography numbers).
    cited_source_ids: list[str] = Field(default_factory=list[str])
    word_count: int = Field(ge=0)
    block_count: int = Field(ge=0)
    citation_count: int = Field(ge=0)


ComplianceStatus = Literal["pass", "fail", "unknown"]


__all__ = [
    "ArticleAuthorship",
    "ArticleExportInput",
    "BuiltArticle",
    "ComplianceStatus",
    "UnresolvedCitationError",
]
