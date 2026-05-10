"""Models produced by the research-interview engine.

These are transient computation results — none are persisted as their own
table. ``ResearchAnswer`` (in :mod:`packages.core.models.evidence`) is the
canonical row that gets stored; everything here wraps either the input to
that row, the scoring intermediate, or the engine's overall reply to the
caller.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from packages.core.enums import CreditCapHit, WeaknessDimension
from packages.core.models.evidence import AnswerScore, EvidenceMatrix


class WeaknessProfile(BaseModel):
    """Weakness analysis of the current evidence matrix state.

    Each axis is scored on ``[0.0, 1.0]`` where ``0.0`` is fully weak and
    ``1.0`` is fully covered. ``weakest_dimension`` is the axis that drove
    the engine's question budget; ``summary`` is a one-sentence human
    description used in logs and audit trails.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    thesis_clarity: float = Field(ge=0.0, le=1.0)
    source_coverage: float = Field(ge=0.0, le=1.0)
    contradiction_awareness: float = Field(ge=0.0, le=1.0)
    originality: float = Field(ge=0.0, le=1.0)
    evidence_depth: float = Field(ge=0.0, le=1.0)
    weakest_dimension: WeaknessDimension
    summary: str = Field(min_length=1, max_length=500)


class ScoredAnswer(BaseModel):
    """A user's answer with LLM-generated rubric scores.

    ``referenced_chunk_ids`` are the chunk identifiers (as strings, since
    the engine speaks the same identifier dialect as ``SourceChunkCreate``
    where IDs are stringified pre-persistence) that the LLM judged the
    answer to actually draw on.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    question_id: UUID
    answer_text: str = Field(min_length=1, max_length=5_000)
    score: AnswerScore
    referenced_chunk_ids: list[str] = Field(default_factory=list[str], max_length=100)
    feedback: str = Field(min_length=1, max_length=1_000)


class CreditDecision(BaseModel):
    """Decision about whether a user earns free credits from an answer.

    ``capped`` is true when the answer would have earned credits on score
    alone but a cap (daily / weekly / per-project) blocked the award; in
    that case ``credits_earned`` is forced to zero and ``cap_hit`` names
    the limiting cap. When ``capped`` is false ``cap_hit`` must be ``None``.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    credits_earned: int = Field(ge=0, le=3)
    reason: str = Field(min_length=1, max_length=300)
    capped: bool = False
    cap_hit: CreditCapHit | None = None


class ProcessedAnswer(BaseModel):
    """Complete result of processing a user's research answer.

    Bundles everything a caller needs to advance the interview UI: the
    rubric-scored answer, the credit decision, the new matrix state, and
    a localised user-facing message.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    scored_answer: ScoredAnswer
    credit_decision: CreditDecision
    updated_matrix: EvidenceMatrix
    feedback_message: str = Field(min_length=1, max_length=500)
    evidence_entries_updated: int = Field(ge=0)


__all__ = [
    "CreditDecision",
    "ProcessedAnswer",
    "ScoredAnswer",
    "WeaknessProfile",
]
