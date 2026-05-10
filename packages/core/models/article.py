"""Article models: drafts, outlines, sections, and citation references."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from packages.core.enums import ArticleSectionStatus, ArticleStructure, CitationFormat


class CitationRef(BaseModel):
    """Reference from a paragraph back to a specific source claim."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    source_id: UUID
    page: int | None = Field(default=None, ge=1)
    claim_id: UUID


class Paragraph(BaseModel):
    """One paragraph of article text plus the citations that ground it."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    text: str = Field(min_length=1, max_length=5_000)
    citations: list[CitationRef] = Field(default_factory=list[CitationRef])


class OutlineSection(BaseModel):
    """One section in an article outline.

    ``purpose`` is the section's structural role, populated from the
    template's ``internal_purpose``. ``section_thesis`` is the LLM's
    specific argumentative statement for this section in this article;
    it is empty when the outline came from the template-only fallback.
    ``quality_flags`` collect non-blocking warnings detected during
    generation (e.g. citation count below ``min_citations``).
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: UUID = Field(default_factory=uuid4)
    title: str = Field(min_length=1, max_length=200)
    target_words: int = Field(gt=0, le=5_000)
    key_claims_to_use: list[str] = Field(default_factory=list[str], max_length=200)
    purpose: str = Field(min_length=1, max_length=500)
    section_thesis: str = Field(default="", max_length=1_000)
    quality_flags: list[str] = Field(default_factory=list[str], max_length=20)
    needs_user_input: bool = False
    min_citations: int = Field(default=0, ge=0, le=100)


class ArticleOutline(BaseModel):
    """Plan committed before any drafting starts.

    ``empirical_or_theoretical`` is set only when ``structure`` is
    :attr:`ArticleStructure.ILMIY_MAQOLA`; otherwise it stays ``None``.
    The string is one of ``"empirical"`` or ``"theoretical"`` and drives
    section selection (Methodology+Results vs Theoretical Framework+
    Analysis) at outline-generation time.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=300)
    structure: ArticleStructure
    sections: list[OutlineSection] = Field(min_length=1)
    thesis: str = Field(min_length=1, max_length=2000)
    total_target_words: int = Field(gt=0, le=20_000)
    empirical_or_theoretical: str | None = Field(default=None, max_length=16)
    quality_flags: list[str] = Field(default_factory=list[str], max_length=50)


class ArticleSection(BaseModel):
    """Drafted section of an article, with paragraph-level citations."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: UUID = Field(default_factory=uuid4)
    article_id: UUID
    section_index: int = Field(ge=0)
    title: str = Field(min_length=1, max_length=200)
    paragraphs: list[Paragraph] = Field(default_factory=list[Paragraph])
    word_count: int = Field(ge=0)
    status: ArticleSectionStatus = ArticleSectionStatus.DRAFT
    created_at: datetime


class ArticleCreate(BaseModel):
    """Payload sent when starting article generation."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    project_id: UUID
    structure_type: ArticleStructure
    thesis: str = Field(min_length=1, max_length=2000)
    citation_format: CitationFormat
    target_pages: int = Field(ge=1, le=30)


class Article(BaseModel):
    """Persisted article record."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: UUID = Field(default_factory=uuid4)
    project_id: UUID
    structure_type: ArticleStructure
    thesis: str = Field(min_length=1, max_length=2000)
    outline: ArticleOutline
    citation_format: CitationFormat
    target_pages: int = Field(ge=1, le=30)
    status: ArticleSectionStatus = ArticleSectionStatus.DRAFT
    created_at: datetime
    updated_at: datetime
