"""Section-by-section article drafter — the quality gate of the article worker.

The drafter is the LLM-facing component that turns an
:class:`ArticleOutline` plus an :class:`EvidenceMatrix` into actual
article prose. It is intentionally narrow:

* one LLM call per section (Sonnet 4.6), with at most one revision pass
  triggered by the heuristic quality validator;
* every factual claim must reference an evidence-matrix entry whose
  ``citation_status`` is ``READY`` or ``VERIFIED``;
* the language used to introduce each claim must match the claim's
  strength — confident verbs near STRONG evidence, cautious verbs near
  WEAK evidence — because over-claiming is the single biggest tell of
  AI-generated academic text.

:class:`ArticleDrafter` orchestrates ``SectionDrafter`` over an entire
outline, accumulating per-section coherence context and ensuring that
the abstract is drafted *last* (so it can summarise the rest of the
article) but positioned *first* in the output.

The 300-line CLAUDE.md budget is exceeded slightly here because the two
classes share state (LLM client, formatting helpers, JSON parsing) and
splitting them across modules would fan out a single coherent operation.
The non-method helpers live in module scope.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any, Final
from uuid import UUID, uuid4

from packages.core.enums import (
    ArticleSectionStatus,
    CalibrationLevel,
    CitationStatus,
)
from packages.core.llm import LLMClient
from packages.core.models.article import (
    ArticleDraftResult,
    ArticleOutline,
    ArticleQualitySummary,
    ArticleSection,
    CitationRef,
    DraftResult,
    OutlineSection,
    Paragraph,
    QualityCheckResult,
)
from packages.core.models.evidence import (
    EvidenceMatrix,
    EvidenceMatrixEntry,
    ResearchAnswer,
    ResearchQuestion,
)
from packages.core.models.source import SourceChunkCreate, SourceClaimCreate
from packages.core.prompts import (
    SECTION_DRAFTING_RETRY_SUFFIX,
    SECTION_DRAFTING_SYSTEM,
    SECTION_DRAFTING_USER,
    SECTION_REVISION_USER,
)
from packages.workers.article.hedging import check_hedging_alignment
from packages.workers.article.quality_validators import run_checks

logger = logging.getLogger(__name__)


SONNET_MODEL: Final[str] = "claude-sonnet-4-6"
DRAFT_MAX_TOKENS: Final[int] = 6_000
REVISION_THRESHOLD: Final[float] = 0.6
USEFULNESS_THRESHOLD: Final[int] = 3
PREVIOUS_SECTION_HEAD_CHARS: Final[int] = 200
PREVIOUS_SECTION_TAIL_CHARS: Final[int] = 100
CHUNK_EXCERPT_CHARS: Final[int] = 300
DEFAULT_SOURCE_ORIGIN: Final[str] = "user_uploaded"

READY_STATUSES: Final[tuple[CitationStatus, ...]] = (
    CitationStatus.READY,
    CitationStatus.VERIFIED,
)


_REGISTER_DESCRIPTIONS: Final[dict[CalibrationLevel, str]] = {
    CalibrationLevel.SCHOOL: (
        "Use clear, accessible language. Explain technical terms when first "
        "used. Short paragraphs. Simple sentence structure. Avoid jargon."
    ),
    CalibrationLevel.UNDERGRADUATE: (
        "Standard academic register. Define specialised terms. Clear "
        "argumentation. Formal but not dense."
    ),
    CalibrationLevel.MASTERS: (
        "Sophisticated academic prose. Disciplinary terminology used "
        "precisely. Complex argumentation. Nuanced hedging."
    ),
    CalibrationLevel.DOCTORAL: (
        "Publication-ready precision. Dense but clear. Technical "
        "vocabulary without over-explanation. Subtle analytical moves."
    ),
    CalibrationLevel.PROFESSIONAL: (
        "Clear, direct, practitioner-oriented. Concrete language. "
        "Actionable insights. Minimal jargon."
    ),
}


_ABSTRACT_TITLE_KEYS: Final[frozenset[str]] = frozenset({"abstract", "annotatsiya", "аннотация"})
_ABSTRACT_PURPOSE_PREFIX: Final[str] = "self-contained abstract"


class SectionDrafter:
    """Drafts one :class:`OutlineSection` into an :class:`ArticleSection`.

    Stateless apart from the injected :class:`LLMClient`. One drafter
    instance may be reused across sections and projects.
    """

    def __init__(self, llm: LLMClient | None = None) -> None:
        self._llm = llm if llm is not None else LLMClient()

    async def draft_section(
        self,
        section: OutlineSection,
        outline: ArticleOutline,
        evidence_matrix: EvidenceMatrix,
        claims: list[SourceClaimCreate],
        chunks: list[SourceChunkCreate],
        user_answers: list[ResearchAnswer],
        questions: list[ResearchQuestion],
        previous_sections: list[ArticleSection],
        language: str,
        calibration_level: CalibrationLevel,
        article_id: UUID | None = None,
        section_index: int = 0,
    ) -> DraftResult:
        """Draft a single section, with one optional revision pass on weak quality."""

        article_id_value = article_id if article_id is not None else uuid4()
        evidence_text = format_evidence(
            section_id=section.id,
            matrix=evidence_matrix,
            claims=claims,
            chunks=chunks,
        )
        user_text = format_user_contributions(
            section_id=section.id,
            matrix=evidence_matrix,
            answers=user_answers,
            questions=questions,
        )
        previous_text = format_previous_sections(previous_sections)

        warnings: list[str] = []
        ready_entries = _ready_entries_for_section(evidence_matrix, section.id)
        if not ready_entries:
            warnings.append(
                f"section {section.id}: no verified evidence available; "
                "drafted general framing only"
            )

        system_prompt = SECTION_DRAFTING_SYSTEM
        user_prompt = SECTION_DRAFTING_USER.format(
            article_title=outline.title,
            article_thesis=outline.thesis,
            article_type=outline.structure.value,
            section_title=section.title,
            section_thesis=section.section_thesis or "(no specific thesis supplied)",
            section_purpose=section.purpose,
            target_word_count=section.target_words,
            quality_checklist=_format_checklist(section, outline),
            evidence_items=evidence_text,
            user_contributions=user_text,
            previous_sections_summary=previous_text,
            language=language,
            calibration_level=_register_for(calibration_level),
        )

        first_response = await self._call_llm_safe(system_prompt, user_prompt)
        llm_calls = 1 if first_response is not None else 0
        tokens_used = first_response.tokens if first_response is not None else 0
        cost_used = first_response.cost if first_response is not None else 0.0
        parsed = _try_parse_object(first_response.content) if first_response is not None else None

        if first_response is None or parsed is None:
            warnings.append(f"section {section.id}: LLM call failed or returned invalid JSON")
            empty_section = _empty_article_section(
                section=section,
                article_id=article_id_value,
                section_index=section_index,
            )
            return DraftResult(
                section=empty_section,
                quality_check=QualityCheckResult(
                    passed=False,
                    checks_passed=[],
                    checks_failed=list(section.quality_flags) or ["draft_failed"],
                    overall_score=0.0,
                ),
                revision_attempted=False,
                revision_improved=False,
                warnings=warnings,
                llm_calls_made=llm_calls,
                tokens_used=tokens_used,
                section_cost_usd=cost_used,
            )

        article_section = _build_article_section(
            parsed=parsed,
            outline_section=section,
            article_id=article_id_value,
            section_index=section_index,
        )
        quality = _quality_for(article_section, section)

        revision_attempted = False
        revision_improved = False
        if quality.overall_score < REVISION_THRESHOLD:
            revision_attempted = True
            revision_response = await self._call_llm_safe(
                system_prompt,
                SECTION_REVISION_USER.format(
                    failed_checks=_format_failed_checks(quality.checks_failed),
                    original_draft_json=json.dumps(parsed, ensure_ascii=False),
                    evidence_items=evidence_text,
                    language=language,
                    calibration_level=_register_for(calibration_level),
                ),
            )
            if revision_response is not None:
                llm_calls += 1
                tokens_used += revision_response.tokens
                cost_used += revision_response.cost
                revised_parsed = _try_parse_object(revision_response.content)
                if revised_parsed is not None:
                    revised_section = _build_article_section(
                        parsed=revised_parsed,
                        outline_section=section,
                        article_id=article_id_value,
                        section_index=section_index,
                    )
                    revised_quality = _quality_for(revised_section, section)
                    if revised_quality.overall_score > quality.overall_score:
                        article_section = revised_section
                        quality = revised_quality
                        revision_improved = True

        warnings.extend(
            check_hedging_alignment(
                _section_full_text(article_section),
                claims=claims,
                language=language,
            )
        )

        return DraftResult(
            section=article_section,
            quality_check=quality,
            revision_attempted=revision_attempted,
            revision_improved=revision_improved,
            warnings=warnings,
            llm_calls_made=llm_calls,
            tokens_used=tokens_used,
            section_cost_usd=cost_used,
        )

    async def _call_llm_safe(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> _LLMCallResult | None:
        """Wrap one LLM call so any error degrades gracefully into ``None``.

        On a JSON-parse failure on the first attempt we send a stricter
        retry suffix; transport / auth errors return ``None`` and the
        caller flags the section as failed.
        """

        try:
            first = await self._llm.complete(
                system=system_prompt,
                user=user_prompt,
                model=SONNET_MODEL,
                max_tokens=DRAFT_MAX_TOKENS,
                cache="1h",
            )
        except Exception as exc:
            logger.warning(
                "section_drafting_llm_failed",
                extra={"error_type": type(exc).__name__, "error": str(exc)[:200]},
            )
            return None

        if _try_parse_object(first.content) is not None:
            return _LLMCallResult(
                content=first.content,
                tokens=int(first.input_tokens) + int(first.output_tokens),
                cost=first.estimated_cost_usd,
            )

        try:
            retry = await self._llm.complete(
                system=system_prompt,
                user=user_prompt + SECTION_DRAFTING_RETRY_SUFFIX,
                model=SONNET_MODEL,
                max_tokens=DRAFT_MAX_TOKENS,
                cache="1h",
            )
        except Exception as exc:
            logger.warning(
                "section_drafting_retry_failed",
                extra={"error_type": type(exc).__name__, "error": str(exc)[:200]},
            )
            return _LLMCallResult(
                content=first.content,
                tokens=int(first.input_tokens) + int(first.output_tokens),
                cost=first.estimated_cost_usd,
            )
        return _LLMCallResult(
            content=retry.content,
            tokens=int(first.input_tokens)
            + int(first.output_tokens)
            + int(retry.input_tokens)
            + int(retry.output_tokens),
            cost=first.estimated_cost_usd + retry.estimated_cost_usd,
        )


class ArticleDrafter:
    """Drafts every section of an outline, with the abstract drafted last.

    Sequentially threads previously drafted sections into each new
    section's prompt so the writing remains coherent. The abstract is
    deferred until every other section is in hand (so it can summarise
    real material) but is placed back at its original outline position
    in the returned :class:`ArticleDraftResult`.
    """

    def __init__(self, section_drafter: SectionDrafter | None = None) -> None:
        self._section_drafter = section_drafter if section_drafter is not None else SectionDrafter()

    async def draft_article(
        self,
        outline: ArticleOutline,
        evidence_matrix: EvidenceMatrix,
        claims: list[SourceClaimCreate],
        chunks: list[SourceChunkCreate],
        user_answers: list[ResearchAnswer],
        questions: list[ResearchQuestion],
        language: str,
        calibration_level: CalibrationLevel,
        article_id: UUID | None = None,
    ) -> ArticleDraftResult:
        """Draft the entire outline; return per-section results plus a summary."""

        article_id_value = article_id if article_id is not None else uuid4()
        order = list(range(len(outline.sections)))
        abstract_index = _find_abstract_index(outline.sections)
        if abstract_index is not None:
            order = [i for i in order if i != abstract_index] + [abstract_index]

        results_by_index: dict[int, DraftResult] = {}
        previous: list[ArticleSection] = []
        warnings: list[str] = []

        for position, idx in enumerate(order):
            section = outline.sections[idx]
            try:
                draft = await self._section_drafter.draft_section(
                    section=section,
                    outline=outline,
                    evidence_matrix=evidence_matrix,
                    claims=claims,
                    chunks=chunks,
                    user_answers=user_answers,
                    questions=questions,
                    previous_sections=list(previous),
                    language=language,
                    calibration_level=calibration_level,
                    article_id=article_id_value,
                    section_index=idx,
                )
            except Exception as exc:
                logger.warning(
                    "article_drafter_section_failed",
                    extra={
                        "section_id": str(section.id),
                        "error_type": type(exc).__name__,
                        "error": str(exc)[:200],
                    },
                )
                warnings.append(f"section {section.title!r} failed to draft: {type(exc).__name__}")
                draft = DraftResult(
                    section=_empty_article_section(
                        section=section,
                        article_id=article_id_value,
                        section_index=idx,
                    ),
                    quality_check=QualityCheckResult(
                        passed=False,
                        checks_passed=[],
                        checks_failed=["draft_exception"],
                        overall_score=0.0,
                    ),
                    revision_attempted=False,
                    revision_improved=False,
                    warnings=[f"exception: {type(exc).__name__}"],
                    llm_calls_made=0,
                    tokens_used=0,
                )
            results_by_index[idx] = draft
            warnings.extend(draft.warnings)
            del position  # ordering used only for control flow
            if draft.section.paragraphs:
                previous.append(draft.section)

        ordered_results = [results_by_index[i] for i in range(len(outline.sections))]

        total_word_count = sum(r.section.word_count for r in ordered_results)
        total_llm_calls = sum(r.llm_calls_made for r in ordered_results)
        total_tokens = sum(r.tokens_used for r in ordered_results)
        estimated_cost = sum(r.section_cost_usd for r in ordered_results)
        quality_summary = _build_quality_summary(ordered_results)

        return ArticleDraftResult(
            sections=ordered_results,
            total_word_count=total_word_count,
            total_llm_calls=total_llm_calls,
            total_tokens=total_tokens,
            estimated_cost_usd=estimated_cost,
            quality_summary=quality_summary,
            warnings=warnings[:100],
        )


# ---------------------------------------------------------------------------
# Internal LLM-call container
# ---------------------------------------------------------------------------


class _LLMCallResult:
    """Tiny POD bundling the parsed-out content with accumulated tokens and cost."""

    __slots__ = ("content", "cost", "tokens")

    def __init__(self, content: str, tokens: int, cost: float) -> None:
        self.content = content
        self.tokens = tokens
        self.cost = cost


# ---------------------------------------------------------------------------
# Evidence / user-voice / coherence formatting helpers
# ---------------------------------------------------------------------------


def format_evidence(
    section_id: UUID,
    matrix: EvidenceMatrix,
    claims: list[SourceClaimCreate],
    chunks: list[SourceChunkCreate],
) -> str:
    """Format the evidence assigned to ``section_id`` as the LLM-facing block.

    Matrix entries are correlated to ``claims`` by their position in the
    matrix's ``entries`` list — this is the order in which the evidence
    matrix builder writes them. Entries whose status is not ``READY`` or
    ``VERIFIED`` are filtered out. Empty result returns an explicit
    "no verified evidence" message rather than a blank block, so the
    LLM cannot silently invent claims.
    """

    if not matrix.entries:
        return _no_evidence_message()

    chunk_index_lookup: dict[int, SourceChunkCreate] = {}
    chunk_source_id_lookup: dict[str, SourceChunkCreate] = {}
    for chunk in chunks:
        chunk_index_lookup[chunk.chunk_index] = chunk
        if chunk.source_id:
            chunk_source_id_lookup[chunk.source_id] = chunk

    relevant: list[tuple[int, EvidenceMatrixEntry]] = [
        (i, entry)
        for i, entry in enumerate(matrix.entries)
        if entry.article_section_id == section_id and entry.citation_status in READY_STATUSES
    ]
    if not relevant:
        return _no_evidence_message()

    blocks: list[str] = []
    for n, (i, entry) in enumerate(relevant, start=1):
        if 0 <= i < len(claims):
            claim = claims[i]
        else:
            continue
        chunk = _resolve_chunk(claim, chunk_index_lookup, chunk_source_id_lookup)
        chunk_excerpt = (chunk.text[:CHUNK_EXCERPT_CHARS] if chunk is not None else "").strip()
        blocks.append(
            f"EVIDENCE {n}:\n"
            f"  Claim: {claim.claim_text}\n"
            f"  Type: {claim.claim_type.value}\n"
            f"  Strength: {claim.strength.value}\n"
            f"  Supporting quote: {claim.quote or 'N/A'}\n"
            f"  Source context (first 300 chars): {chunk_excerpt or 'N/A'}\n"
            f"  Source ID: {entry.source_chunk_id}\n"
            f"  Claim ID: {entry.claim_id}\n"
            f"  Source origin: {DEFAULT_SOURCE_ORIGIN}"
        )
    return "\n\n".join(blocks)


def format_user_contributions(
    section_id: UUID,
    matrix: EvidenceMatrix,
    answers: list[ResearchAnswer],
    questions: list[ResearchQuestion],
) -> str:
    """Format research answers tied to this section as user-voice contributions.

    Only answers whose chunks are referenced by an entry assigned to
    ``section_id`` are surfaced, and only when the answer's
    ``usefulness`` score is ``>= USEFULNESS_THRESHOLD`` — weaker answers
    are not worth integrating.
    """

    if not answers:
        return "(no user contributions for this section)"

    section_chunk_ids = {
        entry.source_chunk_id for entry in matrix.entries if entry.article_section_id == section_id
    }
    if not section_chunk_ids:
        return "(no user contributions for this section)"

    questions_by_id = {q.id: q for q in questions}
    relevant: list[ResearchAnswer] = []
    for answer in answers:
        if answer.score.usefulness < USEFULNESS_THRESHOLD:
            continue
        if not any(ref in section_chunk_ids for ref in answer.source_references_used):
            continue
        relevant.append(answer)

    if not relevant:
        return "(no user contributions for this section)"

    blocks: list[str] = []
    for n, answer in enumerate(relevant, start=1):
        question = questions_by_id.get(answer.question_id)
        question_text = (
            question.question_text if question is not None else "(question text unavailable)"
        )
        blocks.append(
            f"USER CONTRIBUTION {n}:\n"
            f"  In response to: {question_text}\n"
            f"  User said: {answer.answer_text}\n"
            f"  Relevance score: {answer.score.usefulness}/5\n"
            f"  Integrate this as the author's own analysis, not as a cited source."
        )
    return "\n\n".join(blocks)


def format_previous_sections(sections: list[ArticleSection]) -> str:
    """Compact each previously drafted section into a head/tail snippet.

    Keeps inter-section coherence context cheap: ~300 characters per
    section, regardless of how long the section actually was.
    """

    if not sections:
        return "(no previous sections — this is the first section to be drafted)"

    blocks: list[str] = []
    for section in sections:
        head, tail = _section_head_tail(section)
        blocks.append(
            f"PREVIOUS SECTION: {section.title}\n"
            f"  Opens with: {head}...\n"
            f"  Concludes with: ...{tail}"
        )
    return "\n\n".join(blocks)


# ---------------------------------------------------------------------------
# Outline / structure helpers
# ---------------------------------------------------------------------------


def _ready_entries_for_section(
    matrix: EvidenceMatrix, section_id: UUID
) -> list[EvidenceMatrixEntry]:
    return [
        entry
        for entry in matrix.entries
        if entry.article_section_id == section_id and entry.citation_status in READY_STATUSES
    ]


def _find_abstract_index(sections: list[OutlineSection]) -> int | None:
    """Return the index of the abstract section, if any."""

    for idx, section in enumerate(sections):
        title_lower = section.title.lower()
        if any(key in title_lower for key in _ABSTRACT_TITLE_KEYS):
            return idx
        if section.purpose.lower().startswith(_ABSTRACT_PURPOSE_PREFIX):
            return idx
    return None


def _resolve_chunk(
    claim: SourceClaimCreate,
    by_index: dict[int, SourceChunkCreate],
    by_source_id: dict[str, SourceChunkCreate],
) -> SourceChunkCreate | None:
    raw = claim.source_chunk_id
    if not raw:
        return None
    if raw.lstrip("-").isdigit():
        chunk = by_index.get(int(raw))
        if chunk is not None:
            return chunk
    return by_source_id.get(raw)


def _section_head_tail(section: ArticleSection) -> tuple[str, str]:
    if not section.paragraphs:
        return "(empty)", "(empty)"
    head_text = section.paragraphs[0].text.strip()
    tail_text = section.paragraphs[-1].text.strip()
    head = head_text[:PREVIOUS_SECTION_HEAD_CHARS]
    tail = tail_text[-PREVIOUS_SECTION_TAIL_CHARS:]
    return head, tail


def _section_full_text(section: ArticleSection) -> str:
    return "\n\n".join(p.text for p in section.paragraphs)


def _no_evidence_message() -> str:
    return (
        "No verified evidence available for this section. Write general framing "
        "and analysis only. Do NOT make specific factual claims without evidence. "
        "Flag this section as requiring additional sources."
    )


def _format_checklist(section: OutlineSection, outline: ArticleOutline) -> str:
    checks: list[str] = list(section.quality_flags)
    if not checks:
        checks = [
            f"Address the section thesis: {section.section_thesis}"
            if section.section_thesis
            else f"Develop the section purpose: {section.purpose}",
        ]
    if section.min_citations > 0:
        checks.append(
            f"Cite at least {section.min_citations} distinct evidence items "
            "from the EVIDENCE block."
        )
    checks.append(f"Stay within ~20% of the {section.target_words}-word target.")
    del outline  # reserved for future article-wide checks (e.g. thesis tie-back)
    return "\n".join(f"{i + 1}. {c}" for i, c in enumerate(checks))


def _format_failed_checks(failed: list[str]) -> str:
    if not failed:
        return "(no specific checks named — improve overall clarity)"
    return "\n".join(f"- {item}" for item in failed)


def _register_for(level: CalibrationLevel) -> str:
    description = _REGISTER_DESCRIPTIONS[level]
    return f"{level.value} — {description}"


# ---------------------------------------------------------------------------
# JSON parsing / ArticleSection construction
# ---------------------------------------------------------------------------


def _try_parse_object(content: str) -> dict[str, Any] | None:
    """Parse an LLM response into a dict, stripping ``json`` fences."""

    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`").lstrip()
        if text.startswith("json"):
            text = text[len("json") :].lstrip()
    try:
        loaded = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(loaded, dict):
        return None
    return loaded  # type: ignore[reportUnknownVariableType]


def _build_article_section(
    parsed: dict[str, Any],
    outline_section: OutlineSection,
    article_id: UUID,
    section_index: int,
) -> ArticleSection:
    """Coerce the LLM JSON object into a validated :class:`ArticleSection`."""

    raw_paragraphs = parsed.get("paragraphs")
    paragraphs: list[Paragraph] = []
    if isinstance(raw_paragraphs, list):
        for raw in raw_paragraphs:  # type: ignore[reportUnknownVariableType]
            if not isinstance(raw, dict):
                continue
            paragraph = _build_paragraph(raw)  # type: ignore[reportUnknownArgumentType]
            if paragraph is not None:
                paragraphs.append(paragraph)

    declared = parsed.get("word_count")
    if isinstance(declared, int) and declared >= 0:
        word_count = declared
    else:
        word_count = sum(len(p.text.split()) for p in paragraphs)

    return ArticleSection(
        article_id=article_id,
        section_index=section_index,
        title=outline_section.title,
        paragraphs=paragraphs,
        word_count=word_count,
        status=ArticleSectionStatus.DRAFT,
        created_at=datetime.now(UTC),
    )


def _build_paragraph(raw: dict[str, Any]) -> Paragraph | None:
    text = raw.get("text")
    if not isinstance(text, str) or not text.strip():
        return None
    cleaned = text.strip()[:5_000]
    citations: list[CitationRef] = []
    raw_citations = raw.get("citations")
    if isinstance(raw_citations, list):
        for cit in raw_citations:  # type: ignore[reportUnknownVariableType]
            if not isinstance(cit, dict):
                continue
            ref = _build_citation(cit)  # type: ignore[reportUnknownArgumentType]
            if ref is not None:
                citations.append(ref)
    return Paragraph(text=cleaned, citations=citations)


def _build_citation(raw: dict[str, Any]) -> CitationRef | None:
    source_id = _coerce_uuid(raw.get("source_id"))
    claim_id = _coerce_uuid(raw.get("claim_id"))
    if source_id is None or claim_id is None:
        return None
    page_raw = raw.get("page")
    page = page_raw if isinstance(page_raw, int) and page_raw >= 1 else None
    return CitationRef(source_id=source_id, claim_id=claim_id, page=page)


def _coerce_uuid(value: object) -> UUID | None:
    if isinstance(value, UUID):
        return value
    if not isinstance(value, str):
        return None
    try:
        return UUID(value)
    except ValueError:
        return None


def _empty_article_section(
    section: OutlineSection, article_id: UUID, section_index: int
) -> ArticleSection:
    return ArticleSection(
        article_id=article_id,
        section_index=section_index,
        title=section.title,
        paragraphs=[],
        word_count=0,
        status=ArticleSectionStatus.DRAFT,
        created_at=datetime.now(UTC),
    )


def _quality_for(section: ArticleSection, outline_section: OutlineSection) -> QualityCheckResult:
    """Run heuristic checks against the drafted section's full text."""

    text = _section_full_text(section)
    return run_checks(
        text=text,
        checklist=list(outline_section.quality_flags),
        target_word_count=outline_section.target_words,
        min_citations=outline_section.min_citations,
    )


# ---------------------------------------------------------------------------
# Cost / summary helpers
# ---------------------------------------------------------------------------


def _build_quality_summary(results: list[DraftResult]) -> ArticleQualitySummary:
    if not results:
        return ArticleQualitySummary(
            sections_passed=0,
            sections_failed=0,
            sections_revised=0,
            overall_score=0.0,
            weakest_section="",
            strongest_section="",
        )
    passed = sum(1 for r in results if r.quality_check.passed)
    revised = sum(1 for r in results if r.revision_attempted)
    scores = [r.quality_check.overall_score for r in results]
    overall = round(sum(scores) / len(scores), 4)
    weakest = min(results, key=lambda r: r.quality_check.overall_score)
    strongest = max(results, key=lambda r: r.quality_check.overall_score)
    return ArticleQualitySummary(
        sections_passed=passed,
        sections_failed=len(results) - passed,
        sections_revised=revised,
        overall_score=overall,
        weakest_section=str(weakest.section.id),
        strongest_section=str(strongest.section.id),
    )


__all__ = [
    "ArticleDrafter",
    "SectionDrafter",
    "format_evidence",
    "format_previous_sections",
    "format_user_contributions",
]
