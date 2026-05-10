"""Domain-detection and per-section suggestion models.

The suggestion engine analyses an article outline plus its supporting source
material and proposes additional, real, externally-verified data the user
did not upload. Suggestions are produced per article section, ranked, and
gated behind explicit user approval before they enter the evidence matrix.

These models are wire-format types shared between the detector, the
provider registry, individual data providers, and the suggestion
orchestrator. They carry no DB id/timestamp columns; persisted suggestion
rows will live in a separate model when persistence lands.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from packages.core.models.evidence import EvidenceMatrix, EvidenceMatrixEntry
from packages.core.models.source import SourceChunkCreate, SourceClaimCreate


class AcademicDomain(StrEnum):
    """Academic subject domains used to route suggestion providers.

    ``GENERAL`` is the catch-all when no specific domain fires; every
    domain — including ``GENERAL`` — has at least one provider mapped to
    it, so the registry never returns an empty list.
    """

    MEDICAL = "medical"
    ECONOMICS = "economics"
    LEGAL = "legal"
    ENGINEERING = "engineering"
    ENVIRONMENTAL = "environmental"
    EDUCATION = "education"
    AGRICULTURE = "agriculture"
    COMPUTER_SCIENCE = "computer_science"
    SOCIAL_SCIENCES = "social_sciences"
    GENERAL = "general"


class SuggestionSource(StrEnum):
    """The data provider that emitted a single :class:`Suggestion`."""

    PUBMED = "pubmed"
    WORLD_BANK = "world_bank"
    LEX_UZ = "lex_uz"
    DATA_GOV_UZ = "data_gov_uz"
    SEMANTIC_SCHOLAR = "semantic_scholar"
    ARXIV = "arxiv"
    OPENALEX = "openalex"


class DomainScore(BaseModel):
    """A single domain's score in a :class:`DomainDetectionResult`."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    domain: AcademicDomain
    confidence: float = Field(ge=0.0, le=1.0)
    matched_keywords: list[str] = Field(default_factory=list[str], max_length=200)


class DomainDetectionResult(BaseModel):
    """Output of :class:`DomainDetector` over one article's content.

    ``primary_domain`` is the highest-scoring domain after normalisation
    and is what the registry uses by default. ``all_domains`` retains
    every domain whose post-normalisation confidence exceeds 0.1, so
    callers can fan out to multi-domain searches when an article straddles
    e.g. medical and economics topics.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    primary_domain: AcademicDomain
    all_domains: list[DomainScore] = Field(default_factory=list[DomainScore], max_length=20)
    detection_method: str = Field(default="keyword_analysis", max_length=64)


class Suggestion(BaseModel):
    """A single externally-sourced suggestion attached to one section.

    A suggestion is provider-agnostic: it carries enough citation-ready
    metadata for any provider's hit to be promoted into an evidence-matrix
    entry without further calls. Provider-specific fields (legal status,
    indicator values) are optional and only set by the providers that
    populate them.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=500)
    description: str = Field(default="", max_length=1000)
    source_provider: SuggestionSource
    relevance_score: float = Field(ge=0.0, le=1.0)

    authors: list[str] = Field(default_factory=list[str], max_length=20)
    year: int | None = Field(default=None, ge=1500, le=2100)
    doi: str | None = Field(default=None, max_length=200)
    url: str | None = Field(default=None, max_length=1000)

    citation_count: int | None = Field(default=None, ge=0)

    law_number: str | None = Field(default=None, max_length=100)
    law_status: str | None = Field(default=None, max_length=50)
    enacted_date: str | None = Field(default=None, max_length=20)

    indicator_name: str | None = Field(default=None, max_length=300)
    indicator_value: str | None = Field(default=None, max_length=100)
    indicator_year: int | None = Field(default=None, ge=1500, le=2100)
    indicator_country: str | None = Field(default=None, max_length=100)

    target_section_id: str | None = Field(default=None, max_length=64)

    suggestion_id: str = Field(default_factory=lambda: str(uuid4()), max_length=64)


class SectionSuggestions(BaseModel):
    """All suggestions surfaced for one article section."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    section_id: str = Field(min_length=1, max_length=64)
    section_title: str = Field(min_length=1, max_length=200)
    suggestions: list[Suggestion] = Field(default_factory=list[Suggestion], max_length=50)
    search_queries_used: list[str] = Field(default_factory=list[str], max_length=20)
    providers_searched: list[str] = Field(default_factory=list[str], max_length=20)


class SectionNeedType(StrEnum):
    """Why a section warrants additional suggestions."""

    THIN_EVIDENCE = "thin_evidence"
    NO_STATISTICAL_BACKING = "no_statistical_backing"
    NO_LEGAL_GROUNDING = "no_legal_grounding"
    WEAK_CLAIMS_ONLY = "weak_claims_only"
    NO_NEED = "no_need"


class SectionNeed(BaseModel):
    """Assessment of whether a section needs suggestions and why."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    section_id: str = Field(min_length=1, max_length=64)
    needs_suggestions: bool
    need_types: list[SectionNeedType] = Field(default_factory=list[SectionNeedType], max_length=10)
    ready_claim_count: int = Field(default=0, ge=0)
    total_claim_count: int = Field(default=0, ge=0)
    reason: str = Field(default="", max_length=300)


class SuggestionReport(BaseModel):
    """Complete suggestion report for an article."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    domains_detected: DomainDetectionResult
    sections_analyzed: int = Field(default=0, ge=0)
    sections_with_suggestions: int = Field(default=0, ge=0)
    sections_skipped: int = Field(default=0, ge=0)
    section_suggestions: list[SectionSuggestions] = Field(
        default_factory=list[SectionSuggestions], max_length=40
    )
    total_suggestions: int = Field(default=0, ge=0)
    providers_queried: list[str] = Field(default_factory=list[str], max_length=20)
    search_time_ms: int = Field(default=0, ge=0)
    errors: list[str] = Field(default_factory=list[str], max_length=100)


class ApprovedSuggestion(BaseModel):
    """A suggestion the user approved for inclusion in the evidence matrix."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    suggestion: Suggestion
    target_section_id: str = Field(min_length=1, max_length=64)
    approved_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class IntegrationResult(BaseModel):
    """Result of integrating one approved suggestion into the evidence matrix."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    success: bool
    suggestion_id: str = Field(min_length=1, max_length=64)
    claim_created: SourceClaimCreate | None = None
    chunk_created: SourceChunkCreate | None = None
    matrix_entry_created: EvidenceMatrixEntry | None = None
    error: str | None = Field(default=None, max_length=500)


class BatchIntegrationResult(BaseModel):
    """Result of integrating multiple approved suggestions."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    total: int = Field(ge=0)
    succeeded: int = Field(ge=0)
    failed: int = Field(ge=0)
    results: list[IntegrationResult] = Field(
        default_factory=list[IntegrationResult], max_length=200
    )
    updated_matrix: EvidenceMatrix
