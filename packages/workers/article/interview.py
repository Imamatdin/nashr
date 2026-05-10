"""Research-interview engine: weakness analysis, question generation, answer scoring.

This is the module that makes Nashr different from generic AI writing
tools: instead of one-shotting an article from a prompt, the engine asks
source-specific questions that probe the user's understanding of their
own uploaded material. User answers feed back into the evidence matrix,
strengthening claims and unlocking better article output.

The engine is intentionally stateless. It receives the current matrix,
sources, claims, and a single answer at a time, and returns the new
state. Session management belongs to the surrounding worker.

Two LLM calls live here: question generation (Sonnet-grade quality, but
Haiku is acceptable since prompts are well-constrained) and answer
scoring (always Haiku — pure rubric work). Both calls go through the
shared :class:`packages.core.llm.LLMClient` so timeout/retry/cost
logging is uniform with the rest of the platform.

The 300-line file budget in ``CLAUDE.md`` is exceeded slightly here
because splitting the five cohesive methods on the same engine would
fragment a multi-step pipeline (analyze → generate → score → credit →
process). The non-method helpers live in module scope where they
belong.
"""

from __future__ import annotations

import json
import logging
import re
from collections import Counter
from datetime import UTC, datetime
from typing import Any, Final
from uuid import UUID

from packages.core.constants import CREDIT_CAPS
from packages.core.enums import (
    CitationStatus,
    CreditCapHit,
    InterviewMode,
    Language,
    ResearchQuestionType,
    WeaknessDimension,
)
from packages.core.fallback_questions import fallback_questions_for
from packages.core.llm import LLMClient
from packages.core.models.evidence import (
    AnswerScore,
    EvidenceMatrix,
    ResearchAnswer,
    ResearchQuestion,
)
from packages.core.models.interview import (
    CreditDecision,
    ProcessedAnswer,
    ScoredAnswer,
    WeaknessProfile,
)
from packages.core.models.source import (
    SourceChunkCreate,
    SourceClaimCreate,
    SourceMetadataExtracted,
)
from packages.core.prompts import (
    ANSWER_SCORING_RETRY_SUFFIX,
    ANSWER_SCORING_SYSTEM,
    ANSWER_SCORING_USER,
    INTERVIEW_QUESTION_RETRY_SUFFIX,
    INTERVIEW_QUESTION_SYSTEM,
    INTERVIEW_QUESTION_USER,
)
from packages.workers.article.evidence_matrix import (
    READY_STATUSES,
    EvidenceMatrixBuilder,
)

logger = logging.getLogger(__name__)


GUIDED_QUESTION_COUNT: Final[int] = 4
RESEARCH_QUESTION_COUNT: Final[int] = 10
MAX_CHUNKS_IN_PROMPT: Final[int] = 20
CHUNK_EXCERPT_CHARS: Final[int] = 200
MAX_SOURCES_IN_PROMPT: Final[int] = 10
DEFAULT_FEEDBACK: Final[str] = (
    "Could not evaluate. Try providing more specific details from your sources."
)

PROMOTE_SCORE_THRESHOLD: Final[int] = 10
EXCEPTIONAL_SCORE_THRESHOLD: Final[int] = 13
MEDIUM_SCORE_THRESHOLD: Final[int] = 7

_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"[\w']+", re.UNICODE)

_STOPWORDS: Final[frozenset[str]] = frozenset(
    {
        "the",
        "and",
        "of",
        "is",
        "in",
        "to",
        "for",
        "a",
        "an",
        "on",
        "at",
        "by",
        "with",
        "from",
        "as",
        "that",
        "this",
        "are",
        "was",
        "were",
        "be",
        "or",
        "it",
        "its",
        "into",
        "but",
        "not",
        "va",
        "bir",
        "bu",
        "bilan",
        "uchun",
        "ham",
        "lekin",
        "yoki",
        "agar",
        "shu",
        "har",
        "и",
        "в",
        "на",
        "с",
        "по",
        "для",
        "не",
        "что",
        "это",
        "как",
        "к",
        "из",
        "от",
        "о",
        "а",
        "но",
        "же",
        "у",
        "за",
        "до",
    }
)

_POSITIVE_MARKERS: Final[frozenset[str]] = frozenset(
    {
        "increase",
        "increases",
        "increased",
        "rise",
        "rises",
        "grow",
        "grows",
        "growth",
        "support",
        "supports",
        "improve",
        "improves",
        "improved",
        "advance",
        "advances",
        "confirm",
        "confirms",
        "ortadi",
        "oshadi",
        "qollab",
        "ozadi",
        "kuchaydi",
        "увеличение",
        "увеличивает",
        "рост",
        "растёт",
        "поддерживает",
        "поддержка",
        "положительн",
    }
)
_NEGATIVE_MARKERS: Final[frozenset[str]] = frozenset(
    {
        "decrease",
        "decreases",
        "decreased",
        "fall",
        "falls",
        "decline",
        "declines",
        "oppose",
        "opposes",
        "reduce",
        "reduces",
        "drop",
        "drops",
        "contradict",
        "contradicts",
        "reject",
        "rejects",
        "kamayadi",
        "kamaydi",
        "qarshi",
        "kamayish",
        "снижение",
        "уменьшение",
        "падение",
        "снижается",
        "противоречит",
        "отрицательн",
    }
)


_FEEDBACK_HIGH: Final[dict[Language, str]] = {
    Language.UZ: "Javobingiz tufayli muhokama bo'limi kuchaydi. +{n} bepul kredit.",
    Language.RU: "Ваш ответ усилил раздел обсуждения. +{n} бесплатный кредит.",
    Language.EN: "Your answer strengthened the discussion section. +{n} free credit.",
}
_FEEDBACK_HIGH_CAPPED: Final[dict[Language, str]] = {
    Language.UZ: "Javobingiz kuchli, lekin kreditlar chegarasiga yetdingiz.",
    Language.RU: "Ваш ответ сильный, но вы достигли лимита кредитов.",
    Language.EN: "Strong answer, but you have reached your credit cap.",
}
_FEEDBACK_MEDIUM: Final[dict[Language, str]] = {
    Language.UZ: (
        "Yaxshi javob. Manbalardan aniqroq ma'lumot qo'shsangiz, maqola yanada kuchayadi."
    ),
    Language.RU: (
        "Хороший ответ. Если добавите более точную информацию из источников, "
        "статья станет ещё сильнее."
    ),
    Language.EN: (
        "Good answer. Adding more specific info from your source will strengthen the "
        "article further."
    ),
}
_FEEDBACK_LOW: Final[dict[Language, str]] = {
    Language.UZ: "Javob juda umumiy. Manbalardan bitta aniq fikrni eslatib o'ting.",
    Language.RU: "Ответ слишком общий. Упомяните одну конкретную идею из источников.",
    Language.EN: "Answer is too general. Mention one specific idea from your sources.",
}


class ResearchInterviewEngine:
    """Generates adaptive research questions and scores user answers."""

    def __init__(
        self,
        llm: LLMClient | None = None,
        builder: EvidenceMatrixBuilder | None = None,
    ) -> None:
        self._llm = llm if llm is not None else LLMClient()
        self._builder = builder if builder is not None else EvidenceMatrixBuilder()

    # ------------------------------------------------------------------
    # 1. analyze_weaknesses
    # ------------------------------------------------------------------

    def analyze_weaknesses(
        self,
        matrix: EvidenceMatrix,
        claims: list[SourceClaimCreate],
        chunks: list[SourceChunkCreate],
    ) -> WeaknessProfile:
        """Score the matrix on five dimensions and pick the weakest one."""

        thesis_clarity = _thesis_clarity(claims)
        source_coverage = _source_coverage(claims, chunks)
        contradiction_awareness = _contradiction_awareness(claims)
        originality = 0.2
        evidence_depth = _evidence_depth(matrix)

        scores: dict[WeaknessDimension, float] = {
            WeaknessDimension.THESIS_CLARITY: thesis_clarity,
            WeaknessDimension.SOURCE_COVERAGE: source_coverage,
            WeaknessDimension.CONTRADICTION_AWARENESS: contradiction_awareness,
            WeaknessDimension.ORIGINALITY: originality,
            WeaknessDimension.EVIDENCE_DEPTH: evidence_depth,
        }
        weakest = min(scores.items(), key=lambda kv: kv[1])[0]
        summary = (
            f"Weakest dimension: {weakest.value} ({scores[weakest]:.2f}). "
            f"thesis_clarity={thesis_clarity:.2f}, source_coverage={source_coverage:.2f}, "
            f"contradiction_awareness={contradiction_awareness:.2f}, "
            f"originality={originality:.2f}, evidence_depth={evidence_depth:.2f}."
        )

        return WeaknessProfile(
            thesis_clarity=thesis_clarity,
            source_coverage=source_coverage,
            contradiction_awareness=contradiction_awareness,
            originality=originality,
            evidence_depth=evidence_depth,
            weakest_dimension=weakest,
            summary=summary[:500],
        )

    # ------------------------------------------------------------------
    # 2. generate_questions
    # ------------------------------------------------------------------

    async def generate_questions(
        self,
        *,
        project_id: UUID,
        profile: WeaknessProfile,
        matrix: EvidenceMatrix,
        claims: list[SourceClaimCreate],
        chunks: list[SourceChunkCreate],
        source_metadata: list[SourceMetadataExtracted],
        source_ids: list[UUID],
        language: Language,
        mode: InterviewMode,
    ) -> list[ResearchQuestion]:
        """Ask the LLM for an adaptive question list, with safe fallback."""

        if mode is InterviewMode.FAST:
            raise ValueError("Fast mode skips the interview; engine should not be called.")

        num_questions = (
            GUIDED_QUESTION_COUNT if mode is InterviewMode.GUIDED else RESEARCH_QUESTION_COUNT
        )
        distribution = _question_distribution(profile, num_questions)
        source_summaries = _format_source_summaries(source_metadata, source_ids, chunks)
        user_prompt = INTERVIEW_QUESTION_USER.format(
            num_questions=num_questions,
            language=language.value,
            mode=mode.value,
            weakness_profile=_format_profile(profile),
            question_type_distribution=_format_distribution(distribution),
            source_summaries=source_summaries,
        )

        try:
            raw_items = await self._call_questions_with_retry(
                INTERVIEW_QUESTION_SYSTEM, user_prompt
            )
        except Exception as exc:
            logger.warning(
                "interview_question_llm_failed",
                extra={"error_type": type(exc).__name__, "error": str(exc)[:200]},
            )
            return _fallback_research_questions(project_id, language, num_questions)

        if raw_items is None:
            return _fallback_research_questions(project_id, language, num_questions)

        questions = _items_to_questions(raw_items, project_id, source_ids)
        if not questions:
            return _fallback_research_questions(project_id, language, num_questions)
        return questions

    async def _call_questions_with_retry(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> list[dict[str, Any]] | None:
        """Call the LLM; retry once on bad JSON; return ``None`` on final failure."""

        first = await self._llm.complete(system=system_prompt, user=user_prompt, max_tokens=4_000)
        parsed = _try_parse_array(first.content)
        if parsed is not None:
            return parsed

        retry_prompt = user_prompt + INTERVIEW_QUESTION_RETRY_SUFFIX
        second = await self._llm.complete(system=system_prompt, user=retry_prompt, max_tokens=4_000)
        parsed = _try_parse_array(second.content)
        if parsed is not None:
            return parsed

        logger.error(
            "interview_question_json_parse_failed",
            extra={"first_excerpt": first.content[:200]},
        )
        return None

    # ------------------------------------------------------------------
    # 3. score_answer
    # ------------------------------------------------------------------

    async def score_answer(
        self,
        *,
        question: ResearchQuestion,
        answer_text: str,
        chunks: list[SourceChunkCreate],
        language: Language,
    ) -> ScoredAnswer:
        """Have the LLM score one answer; on failure, return a conservative default."""

        chunk_summaries = _format_chunk_summaries(chunks)
        user_prompt = ANSWER_SCORING_USER.format(
            language=language.value,
            question_text=question.question_text,
            answer_text=answer_text,
            source_chunk_summaries=chunk_summaries,
        )

        try:
            raw = await self._call_scoring_with_retry(ANSWER_SCORING_SYSTEM, user_prompt)
        except Exception as exc:
            logger.warning(
                "interview_score_llm_failed",
                extra={"error_type": type(exc).__name__, "error": str(exc)[:200]},
            )
            raw = None

        if raw is None:
            return _default_scored_answer(question.id, answer_text)

        spec = _clamp_score(raw.get("specificity"))
        ground = _clamp_score(raw.get("source_grounding"))
        useful = _clamp_score(raw.get("usefulness"))
        feedback = _coerce_feedback(raw.get("feedback"))
        referenced = _coerce_referenced_chunks(raw.get("referenced_chunks"))

        return ScoredAnswer(
            question_id=question.id,
            answer_text=answer_text[:5_000],
            score=AnswerScore(specificity=spec, source_grounding=ground, usefulness=useful),
            referenced_chunk_ids=referenced,
            feedback=feedback,
        )

    async def _call_scoring_with_retry(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> dict[str, Any] | None:
        """Call the LLM; retry once on bad JSON; return ``None`` on final failure."""

        first = await self._llm.complete(system=system_prompt, user=user_prompt, max_tokens=800)
        parsed = _try_parse_object(first.content)
        if parsed is not None:
            return parsed

        retry_prompt = user_prompt + ANSWER_SCORING_RETRY_SUFFIX
        second = await self._llm.complete(system=system_prompt, user=retry_prompt, max_tokens=800)
        parsed = _try_parse_object(second.content)
        if parsed is not None:
            return parsed

        logger.error(
            "interview_score_json_parse_failed",
            extra={"first_excerpt": first.content[:200]},
        )
        return None

    # ------------------------------------------------------------------
    # 4. determine_credits
    # ------------------------------------------------------------------

    def determine_credits(
        self,
        score: AnswerScore,
        *,
        project_credits_used: int,
        daily_credits_used: int,
        weekly_credits_used: int,
    ) -> CreditDecision:
        """Apply the score-to-credit table and the cap rules."""

        total = score.specificity + score.source_grounding + score.usefulness
        if total >= EXCEPTIONAL_SCORE_THRESHOLD:
            would_earn = 2
        elif total >= PROMOTE_SCORE_THRESHOLD:
            would_earn = 1
        else:
            would_earn = 0

        if would_earn == 0:
            return CreditDecision(
                credits_earned=0,
                reason=f"Total score {total} below threshold {PROMOTE_SCORE_THRESHOLD}.",
                capped=False,
                cap_hit=None,
            )

        cap_hit = _which_cap_hit(
            project_credits_used=project_credits_used,
            daily_credits_used=daily_credits_used,
            weekly_credits_used=weekly_credits_used,
        )
        if cap_hit is not None:
            return CreditDecision(
                credits_earned=0,
                reason=f"Would have earned {would_earn} but {cap_hit.value} cap was hit.",
                capped=True,
                cap_hit=cap_hit,
            )

        return CreditDecision(
            credits_earned=would_earn,
            reason=f"Total score {total} earned {would_earn} credit(s).",
            capped=False,
            cap_hit=None,
        )

    # ------------------------------------------------------------------
    # 5. process_answer
    # ------------------------------------------------------------------

    async def process_answer(
        self,
        *,
        project_id: UUID,
        question: ResearchQuestion,
        answer_text: str,
        matrix: EvidenceMatrix,
        chunks: list[SourceChunkCreate],
        chunk_uuid_map: dict[str, UUID],
        language: Language,
        project_credits_used: int,
        daily_credits_used: int,
        weekly_credits_used: int,
    ) -> ProcessedAnswer:
        """Score, award credits, update the matrix, and craft user feedback."""

        scored = await self.score_answer(
            question=question, answer_text=answer_text, chunks=chunks, language=language
        )
        decision = self.determine_credits(
            scored.score,
            project_credits_used=project_credits_used,
            daily_credits_used=daily_credits_used,
            weekly_credits_used=weekly_credits_used,
        )

        referenced_uuids = _resolve_uuids(scored.referenced_chunk_ids, chunk_uuid_map)
        research_answer = ResearchAnswer(
            project_id=project_id,
            question_id=question.id,
            answer_text=answer_text[:10_000],
            source_references_used=referenced_uuids,
            score=scored.score,
            credits_earned=decision.credits_earned,
            created_at=datetime.now(UTC),
        )

        before = {
            entry.id: (entry.user_answer_id, entry.citation_status) for entry in matrix.entries
        }
        updated_matrix = await self._builder.update_with_answer(matrix, research_answer)
        entries_updated = sum(
            1
            for entry in updated_matrix.entries
            if before.get(entry.id) != (entry.user_answer_id, entry.citation_status)
        )

        feedback_message = _build_feedback_message(scored.score, decision, language)

        return ProcessedAnswer(
            scored_answer=scored,
            credit_decision=decision,
            updated_matrix=updated_matrix,
            feedback_message=feedback_message,
            evidence_entries_updated=entries_updated,
        )


# ---------------------------------------------------------------------------
# Pure-function helpers
# ---------------------------------------------------------------------------


def _thesis_clarity(claims: list[SourceClaimCreate]) -> float:
    if not claims:
        return 0.0
    per_claim_tokens: list[set[str]] = [_tokenize(c.claim_text) for c in claims]
    counter: Counter[str] = Counter()
    for tokens in per_claim_tokens:
        counter.update(tokens)
    if not counter:
        return 0.0
    top = {word for word, _ in counter.most_common(5)}
    matched = sum(1 for tokens in per_claim_tokens if tokens & top)
    return matched / len(claims)


def _source_coverage(claims: list[SourceClaimCreate], chunks: list[SourceChunkCreate]) -> float:
    if not chunks:
        return 0.0
    chunk_keys: set[str] = {_chunk_key(chunk) for chunk in chunks}
    referenced: set[str] = {claim.source_chunk_id for claim in claims if claim.source_chunk_id}
    covered = len(referenced & chunk_keys)
    return covered / len(chunk_keys)


def _contradiction_awareness(claims: list[SourceClaimCreate]) -> float:
    has_positive = False
    has_negative = False
    for claim in claims:
        tokens = _tokenize(claim.claim_text)
        if tokens & _POSITIVE_MARKERS:
            has_positive = True
        if tokens & _NEGATIVE_MARKERS:
            has_negative = True
        if has_positive and has_negative:
            return 0.5
    return 1.0


def _evidence_depth(matrix: EvidenceMatrix) -> float:
    if not matrix.entries:
        return 0.0
    ready = sum(1 for entry in matrix.entries if entry.citation_status in READY_STATUSES)
    return ready / len(matrix.entries)


def _tokenize(text: str) -> set[str]:
    return {
        match.group(0).lower()
        for match in _TOKEN_RE.finditer(text)
        if match.group(0).lower() not in _STOPWORDS and len(match.group(0)) > 2
    }


def _chunk_key(chunk: SourceChunkCreate) -> str:
    return chunk.source_id if chunk.source_id else str(chunk.chunk_index)


def _question_distribution(
    profile: WeaknessProfile, num_questions: int
) -> dict[ResearchQuestionType, int]:
    """Decide how many questions of each type to request from the LLM."""

    dist: dict[ResearchQuestionType, int] = dict.fromkeys(ResearchQuestionType, 0)
    remaining = num_questions

    def add(qt: ResearchQuestionType, want: int) -> None:
        nonlocal remaining
        give = max(0, min(want, remaining))
        dist[qt] += give
        remaining -= give

    if profile.thesis_clarity < 0.5:
        add(ResearchQuestionType.THESIS_CLARITY, 2)
    if profile.source_coverage < 0.5:
        add(ResearchQuestionType.SOURCE_COVERAGE, 2)
    if profile.contradiction_awareness < 1.0:
        add(ResearchQuestionType.CONTRADICTION, 1)
    if profile.originality < 0.5:
        add(ResearchQuestionType.ORIGINALITY, 2)
    add(ResearchQuestionType.SOURCE_COVERAGE, remaining)
    return dist


def _format_profile(profile: WeaknessProfile) -> str:
    return (
        f"thesis_clarity={profile.thesis_clarity:.2f}, "
        f"source_coverage={profile.source_coverage:.2f}, "
        f"contradiction_awareness={profile.contradiction_awareness:.2f}, "
        f"originality={profile.originality:.2f}, "
        f"evidence_depth={profile.evidence_depth:.2f}; "
        f"weakest={profile.weakest_dimension.value}"
    )


def _format_distribution(distribution: dict[ResearchQuestionType, int]) -> str:
    parts = [f"{qt.value}: {count}" for qt, count in distribution.items() if count > 0]
    return ", ".join(parts) if parts else "source_coverage: all"


def _format_source_summaries(
    metadata: list[SourceMetadataExtracted],
    source_ids: list[UUID],
    chunks: list[SourceChunkCreate],
) -> str:
    """Build a compact source-and-chunk summary for the LLM prompt."""

    lines: list[str] = []
    if metadata:
        lines.append("Sources:")
        for index, meta in enumerate(metadata[:MAX_SOURCES_IN_PROMPT]):
            sid = f"source_{index}"
            label = (meta.title or "Untitled").strip()[:120]
            authors = ", ".join(meta.authors[:3])
            year = meta.year
            extra_parts = [p for p in (authors, str(year) if year else "") if p]
            extra = f" ({', '.join(extra_parts)})" if extra_parts else ""
            uuid_hint = f" [uuid={source_ids[index]}]" if index < len(source_ids) else ""
            lines.append(f"- {sid}: {label}{extra}{uuid_hint}")
    lines.append("")
    lines.append("Chunk excerpts (id: text):")
    for chunk in chunks[:MAX_CHUNKS_IN_PROMPT]:
        excerpt = chunk.text.strip().replace("\n", " ")[:CHUNK_EXCERPT_CHARS]
        lines.append(f"{_chunk_key(chunk)}: {excerpt}")
    return "\n".join(lines)


def _format_chunk_summaries(chunks: list[SourceChunkCreate]) -> str:
    if not chunks:
        return "(no source chunks available)"
    lines: list[str] = []
    for chunk in chunks[:MAX_CHUNKS_IN_PROMPT]:
        excerpt = chunk.text.strip().replace("\n", " ")[:CHUNK_EXCERPT_CHARS]
        lines.append(f"{_chunk_key(chunk)}: {excerpt}")
    return "\n".join(lines)


def _try_parse_array(content: str) -> list[dict[str, Any]] | None:
    text = _strip_fences(content)
    try:
        loaded = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(loaded, list):
        return None
    items: list[dict[str, Any]] = []
    for item in loaded:  # type: ignore[reportUnknownVariableType]
        if isinstance(item, dict):
            items.append(item)  # type: ignore[reportUnknownArgumentType]
        else:
            return None
    return items


def _try_parse_object(content: str) -> dict[str, Any] | None:
    text = _strip_fences(content)
    try:
        loaded = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(loaded, dict):
        return None
    return loaded  # type: ignore[reportUnknownVariableType]


def _strip_fences(content: str) -> str:
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[len("json") :]
        text = text.strip()
    return text


def _items_to_questions(
    items: list[dict[str, Any]],
    project_id: UUID,
    source_ids: list[UUID],
) -> list[ResearchQuestion]:
    questions: list[ResearchQuestion] = []
    now = datetime.now(UTC)
    for raw in items:
        text_obj = raw.get("question_text")
        type_obj = raw.get("question_type")
        rel_obj = raw.get("related_source_ids", [])

        if not isinstance(text_obj, str):
            continue
        text = text_obj.strip()
        if not text or len(text) > 2_000:
            continue

        if not isinstance(type_obj, str):
            continue
        try:
            qtype = ResearchQuestionType(type_obj)
        except ValueError:
            continue

        related = _resolve_source_uuids(rel_obj, source_ids)

        questions.append(
            ResearchQuestion(
                project_id=project_id,
                question_text=text,
                question_type=qtype,
                related_source_ids=related,
                created_at=now,
            )
        )
    return questions


def _resolve_source_uuids(raw: object, source_ids: list[UUID]) -> list[UUID]:
    """Map LLM-returned source labels (``source_0``, raw UUIDs) back to UUIDs."""

    if not isinstance(raw, list):
        return []
    out: list[UUID] = []
    for item in raw:  # type: ignore[reportUnknownVariableType]
        if not isinstance(item, str):
            continue
        text = item.strip()
        if text.startswith("source_"):
            tail = text[len("source_") :]
            if tail.isdigit():
                idx = int(tail)
                if 0 <= idx < len(source_ids):
                    out.append(source_ids[idx])
                    continue
        try:
            out.append(UUID(text))
        except ValueError:
            continue
    return out


def _fallback_research_questions(
    project_id: UUID, language: Language, num_questions: int
) -> list[ResearchQuestion]:
    """Build a localised fallback list when LLM generation fails."""

    pool = fallback_questions_for(language)
    if not pool:
        pool = fallback_questions_for(Language.EN)
    selected = pool[:num_questions] if num_questions <= len(pool) else pool
    now = datetime.now(UTC)
    return [
        ResearchQuestion(
            project_id=project_id,
            question_text=text,
            question_type=qtype,
            related_source_ids=[],
            created_at=now,
        )
        for text, qtype in selected
    ]


def _clamp_score(value: object) -> int:
    try:
        as_int = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 2
    return max(0, min(5, as_int))


def _coerce_feedback(value: object) -> str:
    if not isinstance(value, str):
        return DEFAULT_FEEDBACK
    text = value.strip()
    if not text:
        return DEFAULT_FEEDBACK
    return text[:1_000]


def _coerce_referenced_chunks(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:  # type: ignore[reportUnknownVariableType]
        if isinstance(item, str):
            stripped = item.strip()
            if stripped:
                out.append(stripped[:64])
    return out[:100]


def _default_scored_answer(question_id: UUID, answer_text: str) -> ScoredAnswer:
    return ScoredAnswer(
        question_id=question_id,
        answer_text=answer_text[:5_000],
        score=AnswerScore(specificity=2, source_grounding=2, usefulness=2),
        referenced_chunk_ids=[],
        feedback=DEFAULT_FEEDBACK,
    )


def _which_cap_hit(
    *,
    project_credits_used: int,
    daily_credits_used: int,
    weekly_credits_used: int,
) -> CreditCapHit | None:
    """Return the strictest cap that blocks an award, or ``None`` if all clear."""

    if daily_credits_used >= CREDIT_CAPS["daily"]:
        return CreditCapHit.DAILY
    if weekly_credits_used >= CREDIT_CAPS["weekly"]:
        return CreditCapHit.WEEKLY
    if project_credits_used >= CREDIT_CAPS["per_project"]:
        return CreditCapHit.PER_PROJECT
    return None


def _resolve_uuids(referenced: list[str], chunk_uuid_map: dict[str, UUID]) -> list[UUID]:
    out: list[UUID] = []
    seen: set[UUID] = set()
    for key in referenced:
        target = chunk_uuid_map.get(key)
        if target is None:
            continue
        if target in seen:
            continue
        seen.add(target)
        out.append(target)
    return out


def _build_feedback_message(
    score: AnswerScore, decision: CreditDecision, language: Language
) -> str:
    total = score.specificity + score.source_grounding + score.usefulness
    if total >= PROMOTE_SCORE_THRESHOLD:
        if decision.capped:
            template = _FEEDBACK_HIGH_CAPPED.get(language, _FEEDBACK_HIGH_CAPPED[Language.EN])
            return template
        template = _FEEDBACK_HIGH.get(language, _FEEDBACK_HIGH[Language.EN])
        return template.format(n=decision.credits_earned)
    if total >= MEDIUM_SCORE_THRESHOLD:
        return _FEEDBACK_MEDIUM.get(language, _FEEDBACK_MEDIUM[Language.EN])
    return _FEEDBACK_LOW.get(language, _FEEDBACK_LOW[Language.EN])


# Track CitationStatus for type-narrowing in helper modules that import this.
_ = CitationStatus

__all__ = ["ResearchInterviewEngine"]
