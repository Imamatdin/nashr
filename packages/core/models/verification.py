"""Citation verification models.

The verifier inspects a drafted article against its source material and
produces a :class:`CitationVerificationReport` describing every citation
in the article. Critical issues (``NOT_SUPPORTED`` / ``CONTRADICTED``)
should block export; warnings (``OVERCLAIMED``) merely flag the article
for revision.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from packages.core.enums import CitationVerdict


class CitationVerification(BaseModel):
    """Verifier's verdict on a single citation in a drafted article.

    ``article_sentence`` is the sentence in the draft that contained the
    citation marker; ``source_excerpt`` is the leading slice of the
    source chunk's text. ``confidence`` reflects the LLM's certainty in
    the verdict, not the strength of the underlying claim.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    section_id: str = Field(min_length=1, max_length=64)
    paragraph_index: int = Field(ge=0)
    citation_index: int = Field(ge=0)
    claim_id: str = Field(min_length=1, max_length=64)
    source_chunk_id: str = Field(min_length=1, max_length=64)
    claim_text: str = Field(default="", max_length=500)
    source_excerpt: str = Field(default="", max_length=1000)
    article_sentence: str = Field(default="", max_length=1000)
    verdict: CitationVerdict
    confidence: float = Field(ge=0.0, le=1.0)
    explanation: str = Field(default="", max_length=500)
    suggested_fix: str | None = Field(default=None, max_length=500)


class CitationVerificationReport(BaseModel):
    """Aggregate verification result across every citation in an article.

    ``overall_integrity_score`` is ``(supported + partially_supported) /
    total_citations`` and is ``1.0`` for an article with no citations
    (vacuously sound). ``critical_issues`` and ``warnings`` are slices of
    ``verifications`` filtered by verdict; they are stored eagerly so a
    consumer can render them without re-iterating.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    total_citations: int = Field(ge=0)
    supported: int = Field(ge=0)
    partially_supported: int = Field(ge=0)
    overclaimed: int = Field(ge=0)
    not_supported: int = Field(ge=0)
    contradicted: int = Field(ge=0)
    source_not_found: int = Field(ge=0)
    overall_integrity_score: float = Field(ge=0.0, le=1.0)
    verifications: list[CitationVerification] = Field(
        default_factory=list[CitationVerification], max_length=2_000
    )
    critical_issues: list[CitationVerification] = Field(
        default_factory=list[CitationVerification], max_length=2_000
    )
    warnings: list[CitationVerification] = Field(
        default_factory=list[CitationVerification], max_length=2_000
    )
    model_used: str = Field(default="", max_length=128)
    total_tokens: int = Field(default=0, ge=0)
    estimated_cost_usd: float = Field(default=0.0, ge=0.0)
    verification_time_ms: int = Field(default=0, ge=0)
