"""Behaviour tests for :class:`SectionDrafter`, :class:`ArticleDrafter`,
quality validators, and hedging-language alignment.

The drafter makes 1-2 LLM calls per section, so every test that exercises
a draft uses a scripted :class:`_StubLLM` and asserts on either the
formatted prompt strings or the resulting :class:`DraftResult`. Per
``.claude/rules/testing.md`` we mock only the Anthropic LLM; everything
else (validators, hedging, model construction) runs against the real
implementation.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from packages.core.enums import (
    ArticleSectionStatus,
    ArticleStructure,
    CalibrationLevel,
    CitationStatus,
    ClaimStrength,
    ClaimType,
    ResearchQuestionType,
)
from packages.core.llm import LLMResponse
from packages.core.models import (
    ArticleDraftResult,
    ArticleOutline,
    ArticleQualitySummary,
    ArticleSection,
    DraftResult,
    EvidenceMatrix,
    EvidenceMatrixEntry,
    OutlineSection,
    Paragraph,
    QualityCheckResult,
    ResearchAnswer,
    ResearchQuestion,
    SourceChunkCreate,
    SourceClaimCreate,
)
from packages.core.models.evidence import AnswerScore
from packages.workers.article.drafter import (
    ArticleDrafter,
    SectionDrafter,
    format_evidence,
    format_previous_sections,
    format_user_contributions,
)
from packages.workers.article.hedging import (
    CAUTIOUS_LANGUAGE,
    CONFIDENT_LANGUAGE,
    MEASURED_LANGUAGE,
    check_hedging_alignment,
)
from packages.workers.article.quality_validators import (
    has_citations,
    has_contribution_statement,
    has_limitations,
    has_quantitative_result,
    has_research_gap,
    within_word_target,
)

# ---------------------------------------------------------------------------
# Shared helpers / stubs
# ---------------------------------------------------------------------------


class _StubLLM:
    """Stand-in for :class:`LLMClient` returning scripted responses in order."""

    def __init__(
        self,
        responses: list[str] | None = None,
        raise_on_call: Exception | None = None,
    ) -> None:
        self.responses = list(responses or [])
        self.raise_on_call = raise_on_call
        self.calls: list[tuple[str, str]] = []

    async def complete(
        self,
        system: str,
        user: str,
        model: str = "claude-haiku-4-5-20251001",
        max_tokens: int = 2000,
        temperature: float = 0.0,
    ) -> LLMResponse:
        self.calls.append((system, user))
        if self.raise_on_call is not None:
            raise self.raise_on_call
        if not self.responses:
            raise RuntimeError("LLM stub ran out of scripted responses")
        content = self.responses.pop(0)
        return LLMResponse(
            content=content,
            model=model,
            input_tokens=120,
            output_tokens=180,
            latency_ms=10,
            estimated_cost_usd=0.0005,
        )


def _make_claim(
    text: str,
    *,
    strength: ClaimStrength = ClaimStrength.MODERATE,
    claim_type: ClaimType = ClaimType.GENERAL_FACT,
    chunk_id: str = "0",
    quote: str | None = None,
) -> SourceClaimCreate:
    return SourceClaimCreate(
        source_chunk_id=chunk_id,
        claim_text=text if len(text) >= 10 else f"claim about {text}".ljust(12),
        strength=strength,
        claim_type=claim_type,
        quote=quote,
    )


def _make_chunk(text: str, *, index: int = 0, source_id: str = "") -> SourceChunkCreate:
    return SourceChunkCreate(
        source_id=source_id or str(index),
        chunk_index=index,
        text=text,
    )


def _make_entry(
    project_id: UUID,
    *,
    chunk_uuid: UUID,
    section_id: UUID | None = None,
    status: CitationStatus = CitationStatus.READY,
    claim_uuid: UUID | None = None,
) -> EvidenceMatrixEntry:
    return EvidenceMatrixEntry(
        project_id=project_id,
        claim_id=claim_uuid or uuid4(),
        source_chunk_id=chunk_uuid,
        article_section_id=section_id,
        citation_status=status,
        created_at=datetime.now(UTC),
    )


def _make_outline_section(
    *,
    title: str = "Introduction",
    purpose: str = "Introduce the topic and state the research gap.",
    section_thesis: str = "We argue X.",
    target_words: int = 400,
    min_citations: int = 1,
    quality_flags: list[str] | None = None,
) -> OutlineSection:
    return OutlineSection(
        title=title,
        target_words=target_words,
        key_claims_to_use=[],
        purpose=purpose,
        section_thesis=section_thesis,
        quality_flags=quality_flags
        or ["Identifies an explicit research gap", "States the research question"],
        needs_user_input=False,
        min_citations=min_citations,
    )


def _make_outline(sections: list[OutlineSection]) -> ArticleOutline:
    return ArticleOutline(
        title="Test article",
        structure=ArticleStructure.ILMIY_MAQOLA,
        sections=sections,
        thesis="A working thesis.",
        total_target_words=sum(s.target_words for s in sections),
        empirical_or_theoretical="theoretical",
        quality_flags=[],
    )


def _good_paragraph_response(
    *,
    source_id: UUID,
    claim_id: UUID,
    paragraph_text: str | None = None,
) -> str:
    text = paragraph_text or (
        "The literature shows that energy-efficient cooling systems "
        f"demonstrate substantial savings in arid climates [{source_id}]. "
        "Recent work establishes a research gap in semi-arid regions, "
        "where similar systems remain understudied. This paper contributes "
        "a comparative analysis grounded in measured field data, with "
        "p < 0.05 for the primary outcome and n = 240 households. The "
        "research question driving the study is whether the same gains "
        "translate to mid-latitude semi-arid contexts."
    )
    return json.dumps(
        {
            "paragraphs": [
                {
                    "text": text,
                    "citations": [{"source_id": str(source_id), "claim_id": str(claim_id)}],
                }
            ],
            "word_count": len(text.split()),
        }
    )


# ---------------------------------------------------------------------------
# Evidence formatting
# ---------------------------------------------------------------------------


class TestFormatEvidence:
    def test_includes_all_ready_claims(self) -> None:
        project_id = uuid4()
        section_id = uuid4()
        chunk_uuids = [uuid4() for _ in range(3)]
        claims = [
            _make_claim(
                f"Important finding number {i} about cooling systems",
                strength=ClaimStrength.STRONG,
                claim_type=ClaimType.EMPIRICAL_FINDING,
                chunk_id=str(i),
            )
            for i in range(3)
        ]
        chunks = [
            _make_chunk(f"Source text body {i} extends across many words", index=i)
            for i in range(3)
        ]
        entries = [
            _make_entry(
                project_id,
                chunk_uuid=chunk_uuids[i],
                section_id=section_id,
                status=CitationStatus.READY,
            )
            for i in range(3)
        ]
        matrix = EvidenceMatrix(project_id=project_id, entries=entries)

        text = format_evidence(section_id=section_id, matrix=matrix, claims=claims, chunks=chunks)
        for i in range(3):
            assert claims[i].claim_text in text
            assert "Strength:" in text
            assert "Source ID:" in text
        assert text.count("EVIDENCE ") == 3

    def test_excludes_unready_claims(self) -> None:
        project_id = uuid4()
        section_id = uuid4()
        chunk_uuids = [uuid4(), uuid4()]
        claims = [
            _make_claim("Ready claim about renewable cooling research", chunk_id="0"),
            _make_claim("Pending claim about mountainous regions data", chunk_id="1"),
        ]
        chunks = [
            _make_chunk("ready chunk text", index=0),
            _make_chunk("pending chunk text", index=1),
        ]
        entries = [
            _make_entry(
                project_id,
                chunk_uuid=chunk_uuids[0],
                section_id=section_id,
                status=CitationStatus.READY,
            ),
            _make_entry(
                project_id,
                chunk_uuid=chunk_uuids[1],
                section_id=section_id,
                status=CitationStatus.NEEDS_USER_INPUT,
            ),
        ]
        matrix = EvidenceMatrix(project_id=project_id, entries=entries)

        text = format_evidence(section_id=section_id, matrix=matrix, claims=claims, chunks=chunks)
        assert "Ready claim about renewable cooling research" in text
        assert "Pending claim about mountainous regions" not in text

    def test_empty_section_returns_explicit_message(self) -> None:
        project_id = uuid4()
        section_id = uuid4()
        other_section_id = uuid4()
        claims = [_make_claim("Some claim about other section work", chunk_id="0")]
        chunks = [_make_chunk("text body", index=0)]
        entries = [
            _make_entry(
                project_id,
                chunk_uuid=uuid4(),
                section_id=other_section_id,
                status=CitationStatus.READY,
            )
        ]
        matrix = EvidenceMatrix(project_id=project_id, entries=entries)

        text = format_evidence(section_id=section_id, matrix=matrix, claims=claims, chunks=chunks)
        assert "No verified evidence" in text

    def test_includes_claim_type(self) -> None:
        project_id = uuid4()
        section_id = uuid4()
        claim = _make_claim(
            "Statistical p-value of zero point zero five was observed",
            claim_type=ClaimType.STATISTICAL_RESULT,
            chunk_id="0",
        )
        chunks = [_make_chunk("body", index=0)]
        entries = [
            _make_entry(
                project_id,
                chunk_uuid=uuid4(),
                section_id=section_id,
                status=CitationStatus.READY,
            )
        ]
        matrix = EvidenceMatrix(project_id=project_id, entries=entries)
        text = format_evidence(section_id=section_id, matrix=matrix, claims=[claim], chunks=chunks)
        assert "statistical_result" in text

    def test_includes_source_context_excerpt(self) -> None:
        project_id = uuid4()
        section_id = uuid4()
        chunk_text = "A" * 500
        claim = _make_claim("Some claim about the long body content", chunk_id="0")
        chunks = [_make_chunk(chunk_text, index=0)]
        entries = [
            _make_entry(
                project_id,
                chunk_uuid=uuid4(),
                section_id=section_id,
                status=CitationStatus.READY,
            )
        ]
        matrix = EvidenceMatrix(project_id=project_id, entries=entries)
        text = format_evidence(section_id=section_id, matrix=matrix, claims=[claim], chunks=chunks)
        assert "A" * 300 in text
        assert "A" * 301 not in text


# ---------------------------------------------------------------------------
# User voice integration
# ---------------------------------------------------------------------------


def _make_question(text: str = "Local relevance?") -> ResearchQuestion:
    return ResearchQuestion(
        project_id=uuid4(),
        question_text=text,
        question_type=ResearchQuestionType.ORIGINALITY,
        related_source_ids=[],
        created_at=datetime.now(UTC),
    )


def _make_answer(
    *,
    project_id: UUID,
    question_id: UUID,
    text: str,
    usefulness: int,
    refs: list[UUID] | None = None,
) -> ResearchAnswer:
    return ResearchAnswer(
        project_id=project_id,
        question_id=question_id,
        answer_text=text,
        source_references_used=refs or [],
        score=AnswerScore(specificity=4, source_grounding=4, usefulness=usefulness),
        credits_earned=0,
        created_at=datetime.now(UTC),
    )


class TestFormatUserContributions:
    def test_filters_low_usefulness_scores(self) -> None:
        project_id = uuid4()
        section_id = uuid4()
        chunk_uuid = uuid4()
        matrix = EvidenceMatrix(
            project_id=project_id,
            entries=[
                _make_entry(
                    project_id,
                    chunk_uuid=chunk_uuid,
                    section_id=section_id,
                    status=CitationStatus.READY,
                )
            ],
        )
        question = _make_question("Why does this matter?")
        answers = [
            _make_answer(
                project_id=project_id,
                question_id=question.id,
                text="Weak filler answer",
                usefulness=1,
                refs=[chunk_uuid],
            ),
            _make_answer(
                project_id=project_id,
                question_id=question.id,
                text="Acceptable answer with context",
                usefulness=3,
                refs=[chunk_uuid],
            ),
            _make_answer(
                project_id=project_id,
                question_id=question.id,
                text="Excellent grounded analysis here",
                usefulness=5,
                refs=[chunk_uuid],
            ),
        ]
        text = format_user_contributions(
            section_id=section_id,
            matrix=matrix,
            answers=answers,
            questions=[question],
        )
        assert "Weak filler answer" not in text
        assert "Acceptable answer with context" in text
        assert "Excellent grounded analysis here" in text

    def test_includes_question_context(self) -> None:
        project_id = uuid4()
        section_id = uuid4()
        chunk_uuid = uuid4()
        matrix = EvidenceMatrix(
            project_id=project_id,
            entries=[
                _make_entry(
                    project_id,
                    chunk_uuid=chunk_uuid,
                    section_id=section_id,
                    status=CitationStatus.READY,
                )
            ],
        )
        question = _make_question("How does this apply locally?")
        answer = _make_answer(
            project_id=project_id,
            question_id=question.id,
            text="The local case includes Tashkent district pilots",
            usefulness=4,
            refs=[chunk_uuid],
        )
        text = format_user_contributions(
            section_id=section_id,
            matrix=matrix,
            answers=[answer],
            questions=[question],
        )
        assert "How does this apply locally?" in text

    def test_empty_when_no_answers(self) -> None:
        project_id = uuid4()
        section_id = uuid4()
        text = format_user_contributions(
            section_id=section_id,
            matrix=EvidenceMatrix(project_id=project_id, entries=[]),
            answers=[],
            questions=[],
        )
        assert "no user contributions" in text.lower()


# ---------------------------------------------------------------------------
# Inter-section context formatting
# ---------------------------------------------------------------------------


def _make_article_section(
    *, title: str = "Section", paragraphs: list[str] | None = None
) -> ArticleSection:
    paras = paragraphs or ["Body paragraph one." * 10]
    return ArticleSection(
        article_id=uuid4(),
        section_index=0,
        title=title,
        paragraphs=[Paragraph(text=t, citations=[]) for t in paras],
        word_count=sum(len(t.split()) for t in paras),
        status=ArticleSectionStatus.DRAFT,
        created_at=datetime.now(UTC),
    )


class TestFormatPreviousSections:
    def test_truncates_head_and_tail(self) -> None:
        long_text = "A" * 500 + " " + "B" * 200
        section_a = _make_article_section(title="Intro", paragraphs=[long_text])
        section_b = _make_article_section(
            title="Lit Review", paragraphs=["lit body text padded out for word count" * 5]
        )
        section_c = _make_article_section(
            title="Methods", paragraphs=["methods body text padded out for word count" * 5]
        )
        text = format_previous_sections([section_a, section_b, section_c])
        assert "Intro" in text
        assert "Lit Review" in text
        assert "Methods" in text
        # Head truncation: full long_text body should NOT appear
        assert "A" * 500 not in text
        # 200-char head limit ⇒ "A" * 200 may appear, but definitely not 250+
        assert "A" * 250 not in text

    def test_empty_when_no_previous_sections(self) -> None:
        text = format_previous_sections([])
        assert "no previous sections" in text.lower()


# ---------------------------------------------------------------------------
# Section drafting (LLM mocked)
# ---------------------------------------------------------------------------


def _build_basic_drafting_inputs() -> tuple[
    SectionDrafter,
    OutlineSection,
    ArticleOutline,
    EvidenceMatrix,
    list[SourceClaimCreate],
    list[SourceChunkCreate],
    UUID,
    UUID,
]:
    project_id = uuid4()
    section = _make_outline_section(
        quality_flags=[
            "Identifies an explicit research gap",
            "States the research question",
            "Previews the paper's contribution",
            "Contains quantitative result",
        ],
        target_words=120,
    )
    outline = _make_outline([section])
    chunk_uuid = uuid4()
    claim_uuid = uuid4()
    claim = _make_claim(
        "Field measurements demonstrate radiative cooling savings",
        strength=ClaimStrength.STRONG,
        claim_type=ClaimType.STATISTICAL_RESULT,
        chunk_id="0",
    )
    chunk = _make_chunk("Detailed field measurement context.", index=0)
    matrix = EvidenceMatrix(
        project_id=project_id,
        entries=[
            _make_entry(
                project_id,
                chunk_uuid=chunk_uuid,
                section_id=section.id,
                status=CitationStatus.READY,
                claim_uuid=claim_uuid,
            )
        ],
    )
    return (
        SectionDrafter(),
        section,
        outline,
        matrix,
        [claim],
        [chunk],
        chunk_uuid,
        claim_uuid,
    )


class TestDraftSection:
    @pytest.mark.asyncio
    async def test_produces_valid_article_section(self) -> None:
        drafter, section, outline, matrix, claims, chunks, chunk_uuid, claim_uuid = (
            _build_basic_drafting_inputs()
        )
        llm = _StubLLM(
            responses=[_good_paragraph_response(source_id=chunk_uuid, claim_id=claim_uuid)]
        )
        drafter._llm = llm  # type: ignore[assignment]

        result = await drafter.draft_section(
            section=section,
            outline=outline,
            evidence_matrix=matrix,
            claims=claims,
            chunks=chunks,
            user_answers=[],
            questions=[],
            previous_sections=[],
            language="en",
            calibration_level=CalibrationLevel.UNDERGRADUATE,
        )
        assert result.section.paragraphs
        assert result.section.paragraphs[0].text  # non-empty
        assert result.section.word_count > 0
        cite = result.section.paragraphs[0].citations[0]
        assert cite.source_id == chunk_uuid
        assert cite.claim_id == claim_uuid
        assert result.llm_calls_made >= 1

    @pytest.mark.asyncio
    async def test_passes_language_into_prompt(self) -> None:
        drafter, section, outline, matrix, claims, chunks, chunk_uuid, claim_uuid = (
            _build_basic_drafting_inputs()
        )
        llm = _StubLLM(
            responses=[_good_paragraph_response(source_id=chunk_uuid, claim_id=claim_uuid)]
        )
        drafter._llm = llm  # type: ignore[assignment]
        await drafter.draft_section(
            section=section,
            outline=outline,
            evidence_matrix=matrix,
            claims=claims,
            chunks=chunks,
            user_answers=[],
            questions=[],
            previous_sections=[],
            language="uz",
            calibration_level=CalibrationLevel.UNDERGRADUATE,
        )
        _, user_prompt = llm.calls[0]
        assert "language" in user_prompt.lower()
        assert "uz" in user_prompt

    @pytest.mark.asyncio
    async def test_includes_quality_check(self) -> None:
        drafter, section, outline, matrix, claims, chunks, chunk_uuid, claim_uuid = (
            _build_basic_drafting_inputs()
        )
        llm = _StubLLM(
            responses=[_good_paragraph_response(source_id=chunk_uuid, claim_id=claim_uuid)]
        )
        drafter._llm = llm  # type: ignore[assignment]
        result = await drafter.draft_section(
            section=section,
            outline=outline,
            evidence_matrix=matrix,
            claims=claims,
            chunks=chunks,
            user_answers=[],
            questions=[],
            previous_sections=[],
            language="en",
            calibration_level=CalibrationLevel.UNDERGRADUATE,
        )
        assert isinstance(result.quality_check, QualityCheckResult)
        assert isinstance(result.quality_check.checks_passed, list)
        assert isinstance(result.quality_check.checks_failed, list)

    @pytest.mark.asyncio
    async def test_revision_pass_on_low_quality(self) -> None:
        drafter, section, outline, matrix, claims, chunks, chunk_uuid, claim_uuid = (
            _build_basic_drafting_inputs()
        )
        # Make checks demanding so the bare draft fails
        section = section.model_copy(
            update={
                "quality_flags": [
                    "Identifies an explicit research gap",
                    "States the research question",
                    "Previews the paper's contribution",
                    "Contains quantitative result",
                    "Has thematic grouping",
                    "States the contribution",
                    "Addresses limitations",
                    "Includes local examples (Uzbekistan)",
                ],
                "target_words": 120,
                "min_citations": 3,
            }
        )
        outline = _make_outline([section])

        weak_text = "Short and bland." * 5  # passes very few checks
        weak_response = json.dumps(
            {
                "paragraphs": [{"text": weak_text, "citations": []}],
                "word_count": len(weak_text.split()),
            }
        )
        strong_text = (
            "The literature reveals a clear research gap: semi-arid regions are "
            f"understudied [{chunk_uuid}]. The research question is whether the "
            "savings reported in arid pilots transfer to semi-arid Uzbekistan. "
            "This paper contributes a comparative field analysis. The dataset "
            "covers n = 240 households with p < 0.05 for the headline outcome. "
            "We address limitations explicitly, including the small geographic "
            "spread. Local examples from Tashkent and Samarkand demonstrate "
            "the practical relevance of the findings. Sources broadly cluster "
            f"into two thematic strands [{chunk_uuid}]."
        )
        strong_response = json.dumps(
            {
                "paragraphs": [
                    {
                        "text": strong_text,
                        "citations": [{"source_id": str(chunk_uuid), "claim_id": str(claim_uuid)}],
                    }
                ],
                "word_count": len(strong_text.split()),
            }
        )
        llm = _StubLLM(responses=[weak_response, strong_response])
        drafter._llm = llm  # type: ignore[assignment]
        result = await drafter.draft_section(
            section=section,
            outline=outline,
            evidence_matrix=matrix,
            claims=claims,
            chunks=chunks,
            user_answers=[],
            questions=[],
            previous_sections=[],
            language="en",
            calibration_level=CalibrationLevel.UNDERGRADUATE,
        )
        assert result.revision_attempted is True
        assert result.revision_improved is True
        assert result.llm_calls_made == 2

    @pytest.mark.asyncio
    async def test_no_revision_on_good_quality(self) -> None:
        drafter, section, outline, matrix, claims, chunks, chunk_uuid, claim_uuid = (
            _build_basic_drafting_inputs()
        )
        # Use a checklist where the drafted text scores well
        section = section.model_copy(
            update={
                "quality_flags": [
                    "Has quantitative result",
                    "States the contribution",
                    "Identifies an explicit research gap",
                ],
                "target_words": 80,
                "min_citations": 1,
            }
        )
        outline = _make_outline([section])
        llm = _StubLLM(
            responses=[_good_paragraph_response(source_id=chunk_uuid, claim_id=claim_uuid)]
        )
        drafter._llm = llm  # type: ignore[assignment]
        result = await drafter.draft_section(
            section=section,
            outline=outline,
            evidence_matrix=matrix,
            claims=claims,
            chunks=chunks,
            user_answers=[],
            questions=[],
            previous_sections=[],
            language="en",
            calibration_level=CalibrationLevel.UNDERGRADUATE,
        )
        assert result.revision_attempted is False
        assert result.llm_calls_made == 1

    @pytest.mark.asyncio
    async def test_keeps_original_when_revision_worse(self) -> None:
        drafter, section, outline, matrix, claims, chunks, chunk_uuid, claim_uuid = (
            _build_basic_drafting_inputs()
        )
        section = section.model_copy(
            update={
                "quality_flags": [
                    "Identifies an explicit research gap",
                    "States the research question",
                    "Previews the paper's contribution",
                    "Has quantitative result",
                    "States the contribution",
                    "Addresses limitations",
                    "Has thematic grouping",
                    "Includes local examples",
                ],
                "target_words": 120,
                "min_citations": 1,
            }
        )
        outline = _make_outline([section])

        original_text = (
            "The literature reveals a clear research gap. We ask the research "
            f"question. This paper contributes a new analysis [{chunk_uuid}]."
        )
        original_response = json.dumps(
            {
                "paragraphs": [
                    {
                        "text": original_text,
                        "citations": [{"source_id": str(chunk_uuid), "claim_id": str(claim_uuid)}],
                    }
                ],
                "word_count": len(original_text.split()),
            }
        )
        weaker_text = "Short bland."
        weaker_response = json.dumps(
            {
                "paragraphs": [{"text": weaker_text, "citations": []}],
                "word_count": 2,
            }
        )
        llm = _StubLLM(responses=[original_response, weaker_response])
        drafter._llm = llm  # type: ignore[assignment]
        result = await drafter.draft_section(
            section=section,
            outline=outline,
            evidence_matrix=matrix,
            claims=claims,
            chunks=chunks,
            user_answers=[],
            questions=[],
            previous_sections=[],
            language="en",
            calibration_level=CalibrationLevel.UNDERGRADUATE,
        )
        assert result.revision_attempted is True
        assert result.revision_improved is False
        # original draft retained
        assert "research gap" in result.section.paragraphs[0].text

    @pytest.mark.asyncio
    async def test_zero_evidence_warning(self) -> None:
        project_id = uuid4()
        section = _make_outline_section(target_words=80, min_citations=0)
        outline = _make_outline([section])
        matrix = EvidenceMatrix(project_id=project_id, entries=[])
        llm = _StubLLM(
            responses=[
                json.dumps(
                    {
                        "paragraphs": [{"text": "General framing only here." * 5, "citations": []}],
                        "word_count": 25,
                    }
                )
            ]
        )
        drafter = SectionDrafter(llm=None)
        drafter._llm = llm  # type: ignore[assignment]
        result = await drafter.draft_section(
            section=section,
            outline=outline,
            evidence_matrix=matrix,
            claims=[],
            chunks=[],
            user_answers=[],
            questions=[],
            previous_sections=[],
            language="en",
            calibration_level=CalibrationLevel.UNDERGRADUATE,
        )
        assert any("no verified evidence" in w.lower() for w in result.warnings)

    @pytest.mark.asyncio
    async def test_handles_llm_failure(self) -> None:
        drafter, section, outline, matrix, claims, chunks, _, _ = _build_basic_drafting_inputs()
        llm = _StubLLM(raise_on_call=RuntimeError("API exploded"))
        drafter._llm = llm  # type: ignore[assignment]
        result = await drafter.draft_section(
            section=section,
            outline=outline,
            evidence_matrix=matrix,
            claims=claims,
            chunks=chunks,
            user_answers=[],
            questions=[],
            previous_sections=[],
            language="en",
            calibration_level=CalibrationLevel.UNDERGRADUATE,
        )
        assert result.section.paragraphs == []
        assert any("LLM call failed" in w or "invalid JSON" in w for w in result.warnings)


# ---------------------------------------------------------------------------
# Calibration levels
# ---------------------------------------------------------------------------


class TestCalibrationLevel:
    @pytest.mark.asyncio
    async def test_school_uses_clear_language(self) -> None:
        drafter, section, outline, matrix, claims, chunks, chunk_uuid, claim_uuid = (
            _build_basic_drafting_inputs()
        )
        llm = _StubLLM(
            responses=[_good_paragraph_response(source_id=chunk_uuid, claim_id=claim_uuid)]
        )
        drafter._llm = llm  # type: ignore[assignment]
        await drafter.draft_section(
            section=section,
            outline=outline,
            evidence_matrix=matrix,
            claims=claims,
            chunks=chunks,
            user_answers=[],
            questions=[],
            previous_sections=[],
            language="en",
            calibration_level=CalibrationLevel.SCHOOL,
        )
        _, user_prompt = llm.calls[0]
        assert "clear" in user_prompt.lower() and "accessible" in user_prompt.lower()

    @pytest.mark.asyncio
    async def test_doctoral_uses_precise_language(self) -> None:
        drafter, section, outline, matrix, claims, chunks, chunk_uuid, claim_uuid = (
            _build_basic_drafting_inputs()
        )
        llm = _StubLLM(
            responses=[_good_paragraph_response(source_id=chunk_uuid, claim_id=claim_uuid)]
        )
        drafter._llm = llm  # type: ignore[assignment]
        await drafter.draft_section(
            section=section,
            outline=outline,
            evidence_matrix=matrix,
            claims=claims,
            chunks=chunks,
            user_answers=[],
            questions=[],
            previous_sections=[],
            language="en",
            calibration_level=CalibrationLevel.DOCTORAL,
        )
        _, user_prompt = llm.calls[0]
        lower = user_prompt.lower()
        assert "publication-ready" in lower and "precis" in lower

    @pytest.mark.asyncio
    async def test_professional_uses_practitioner_language(self) -> None:
        drafter, section, outline, matrix, claims, chunks, chunk_uuid, claim_uuid = (
            _build_basic_drafting_inputs()
        )
        llm = _StubLLM(
            responses=[_good_paragraph_response(source_id=chunk_uuid, claim_id=claim_uuid)]
        )
        drafter._llm = llm  # type: ignore[assignment]
        await drafter.draft_section(
            section=section,
            outline=outline,
            evidence_matrix=matrix,
            claims=claims,
            chunks=chunks,
            user_answers=[],
            questions=[],
            previous_sections=[],
            language="en",
            calibration_level=CalibrationLevel.PROFESSIONAL,
        )
        _, user_prompt = llm.calls[0]
        lower = user_prompt.lower()
        assert "practitioner" in lower and "actionable" in lower


# ---------------------------------------------------------------------------
# Full article drafting
# ---------------------------------------------------------------------------


def _three_section_outline_and_evidence() -> tuple[
    ArticleOutline,
    EvidenceMatrix,
    list[SourceClaimCreate],
    list[SourceChunkCreate],
    list[UUID],
    list[UUID],
]:
    project_id = uuid4()
    sections = [
        _make_outline_section(
            title="Introduction",
            purpose="Introduce the topic and state the research gap.",
            target_words=80,
            min_citations=1,
            quality_flags=["Identifies an explicit research gap"],
        ),
        _make_outline_section(
            title="Methods",
            purpose="Describe the methodology used.",
            target_words=80,
            min_citations=1,
            quality_flags=["Justifies analysis techniques"],
        ),
        _make_outline_section(
            title="Conclusion",
            purpose="Restate the contribution.",
            target_words=80,
            min_citations=0,
            quality_flags=["Introduces no new factual claims"],
        ),
    ]
    outline = _make_outline(sections)
    chunk_uuids = [uuid4() for _ in sections]
    claim_uuids = [uuid4() for _ in sections]
    claims = [
        _make_claim(f"Section claim text number {i} for the model", chunk_id=str(i))
        for i, _ in enumerate(sections)
    ]
    chunks = [_make_chunk(f"Body text {i}", index=i) for i, _ in enumerate(sections)]
    entries = [
        _make_entry(
            project_id,
            chunk_uuid=chunk_uuids[i],
            section_id=sections[i].id,
            status=CitationStatus.READY,
            claim_uuid=claim_uuids[i],
        )
        for i in range(len(sections))
    ]
    matrix = EvidenceMatrix(project_id=project_id, entries=entries)
    return outline, matrix, claims, chunks, chunk_uuids, claim_uuids


class TestDraftArticle:
    @pytest.mark.asyncio
    async def test_sequential_with_previous_context(self) -> None:
        outline, matrix, claims, chunks, chunk_uuids, claim_uuids = (
            _three_section_outline_and_evidence()
        )
        responses = [
            _good_paragraph_response(
                source_id=chunk_uuids[i],
                claim_id=claim_uuids[i],
                paragraph_text=(
                    f"Section {i} draft body. Identifies an explicit research gap "
                    f"and states the contribution clearly [{chunk_uuids[i]}]."
                ),
            )
            for i in range(3)
        ]
        llm = _StubLLM(responses=responses)
        drafter = ArticleDrafter(SectionDrafter())
        drafter._section_drafter._llm = llm  # type: ignore[attr-defined]

        result = await drafter.draft_article(
            outline=outline,
            evidence_matrix=matrix,
            claims=claims,
            chunks=chunks,
            user_answers=[],
            questions=[],
            language="en",
            calibration_level=CalibrationLevel.UNDERGRADUATE,
        )
        assert len(result.sections) == 3
        # second call's user message should reference Introduction
        _, second_user = llm.calls[1]
        assert "Introduction" in second_user
        # third call's user message should reference both prior sections
        _, third_user = llm.calls[2]
        assert "Introduction" in third_user
        assert "Methods" in third_user

    @pytest.mark.asyncio
    async def test_abstract_drafted_last_but_positioned_first(self) -> None:
        project_id = uuid4()
        abstract_section = _make_outline_section(
            title="Abstract",
            purpose="Self-contained abstract: background, objective, method, result.",
            target_words=10,
            min_citations=0,
            quality_flags=["Self-contained: no citations"],
        )
        intro_section = _make_outline_section(
            title="Introduction",
            target_words=10,
            min_citations=1,
            quality_flags=["Identifies an explicit research gap"],
        )
        conclusion_section = _make_outline_section(
            title="Conclusion",
            target_words=10,
            min_citations=0,
            quality_flags=["Introduces no new factual claims"],
        )
        outline = _make_outline([abstract_section, intro_section, conclusion_section])

        chunk_uuid = uuid4()
        claim_uuid = uuid4()
        claim = _make_claim("Body claim about cooling research findings", chunk_id="0")
        chunk = _make_chunk("Body context here.", index=0)
        entries = [
            _make_entry(
                project_id,
                chunk_uuid=chunk_uuid,
                section_id=intro_section.id,
                status=CitationStatus.READY,
                claim_uuid=claim_uuid,
            )
        ]
        matrix = EvidenceMatrix(project_id=project_id, entries=entries)

        # Three responses — one per section. Response order matches CALL order
        # (intro, conclusion, abstract), not output order.
        responses = [
            _good_paragraph_response(
                source_id=chunk_uuid,
                claim_id=claim_uuid,
                paragraph_text=(f"Intro body identifies an explicit research gap [{chunk_uuid}]."),
            ),
            _good_paragraph_response(
                source_id=chunk_uuid,
                claim_id=claim_uuid,
                paragraph_text="Conclusion restates the overall goal of the paper cleanly.",
            ),
            _good_paragraph_response(
                source_id=chunk_uuid,
                claim_id=claim_uuid,
                paragraph_text="Abstract summarises the whole paper concisely with key result.",
            ),
        ]
        llm = _StubLLM(responses=responses)
        drafter = ArticleDrafter(SectionDrafter())
        drafter._section_drafter._llm = llm  # type: ignore[attr-defined]
        result = await drafter.draft_article(
            outline=outline,
            evidence_matrix=matrix,
            claims=[claim],
            chunks=[chunk],
            user_answers=[],
            questions=[],
            language="en",
            calibration_level=CalibrationLevel.UNDERGRADUATE,
        )
        # Output positioning: abstract first
        assert result.sections[0].section.title == "Abstract"
        assert result.sections[1].section.title == "Introduction"
        assert result.sections[2].section.title == "Conclusion"
        # Drafting order: abstract was the last LLM call. Three calls expected.
        assert len(llm.calls) == 3
        _, third_user_prompt = llm.calls[2]
        # The abstract is drafted last → its user prompt mentions the
        # Abstract section title, and includes the previously drafted
        # Intro + Conclusion as PREVIOUS SECTION context.
        assert "Abstract" in third_user_prompt
        assert "Introduction" in third_user_prompt
        assert "Conclusion" in third_user_prompt

    @pytest.mark.asyncio
    async def test_accumulates_stats(self) -> None:
        outline, matrix, claims, chunks, chunk_uuids, claim_uuids = (
            _three_section_outline_and_evidence()
        )
        responses = [
            _good_paragraph_response(
                source_id=chunk_uuids[i],
                claim_id=claim_uuids[i],
                paragraph_text=(
                    f"Section {i}. Identifies an explicit research gap "
                    f"and states the contribution [{chunk_uuids[i]}]."
                ),
            )
            for i in range(3)
        ]
        llm = _StubLLM(responses=responses)
        drafter = ArticleDrafter(SectionDrafter())
        drafter._section_drafter._llm = llm  # type: ignore[attr-defined]
        result = await drafter.draft_article(
            outline=outline,
            evidence_matrix=matrix,
            claims=claims,
            chunks=chunks,
            user_answers=[],
            questions=[],
            language="en",
            calibration_level=CalibrationLevel.UNDERGRADUATE,
        )
        assert result.total_word_count == sum(r.section.word_count for r in result.sections)
        assert result.total_llm_calls >= 3
        assert result.estimated_cost_usd > 0.0

    @pytest.mark.asyncio
    async def test_quality_summary_populated(self) -> None:
        outline, matrix, claims, chunks, chunk_uuids, claim_uuids = (
            _three_section_outline_and_evidence()
        )
        responses = [
            _good_paragraph_response(
                source_id=chunk_uuids[i],
                claim_id=claim_uuids[i],
                paragraph_text=(
                    f"Section {i}. Identifies an explicit research gap "
                    f"and states the contribution [{chunk_uuids[i]}]."
                ),
            )
            for i in range(3)
        ]
        llm = _StubLLM(responses=responses)
        drafter = ArticleDrafter(SectionDrafter())
        drafter._section_drafter._llm = llm  # type: ignore[attr-defined]
        result = await drafter.draft_article(
            outline=outline,
            evidence_matrix=matrix,
            claims=claims,
            chunks=chunks,
            user_answers=[],
            questions=[],
            language="en",
            calibration_level=CalibrationLevel.UNDERGRADUATE,
        )
        assert isinstance(result.quality_summary, ArticleQualitySummary)
        assert result.quality_summary.sections_passed + result.quality_summary.sections_failed == 3
        assert result.quality_summary.weakest_section
        assert result.quality_summary.strongest_section

    @pytest.mark.asyncio
    async def test_handles_partial_failure(self) -> None:
        outline, matrix, claims, chunks, chunk_uuids, claim_uuids = (
            _three_section_outline_and_evidence()
        )
        # Both initial AND retry of section 1 must be invalid JSON so the
        # drafter's retry-on-bad-JSON path does not silently consume a
        # later section's response.
        responses = [
            _good_paragraph_response(
                source_id=chunk_uuids[0],
                claim_id=claim_uuids[0],
                paragraph_text=(
                    f"Section zero body identifies an explicit research gap "
                    f"and contributes a new comparative analysis [{chunk_uuids[0]}]."
                ),
            ),
            "this is not valid json output at all{",  # methods initial — bad
            "still not json either }",  # methods retry — bad
            _good_paragraph_response(
                source_id=chunk_uuids[2],
                claim_id=claim_uuids[2],
                paragraph_text=(
                    f"Section two body. Introduces no new factual claims "
                    f"and concludes with the highest priority contribution [{chunk_uuids[2]}]."
                ),
            ),
        ]
        llm = _StubLLM(responses=responses)
        drafter = ArticleDrafter(SectionDrafter())
        drafter._section_drafter._llm = llm  # type: ignore[attr-defined]
        result = await drafter.draft_article(
            outline=outline,
            evidence_matrix=matrix,
            claims=claims,
            chunks=chunks,
            user_answers=[],
            questions=[],
            language="en",
            calibration_level=CalibrationLevel.UNDERGRADUATE,
        )
        assert len(result.sections) == 3
        # Section 1 (the bad-JSON one) ends up empty
        assert result.sections[1].section.paragraphs == []
        assert result.sections[0].section.paragraphs
        assert result.sections[2].section.paragraphs


# ---------------------------------------------------------------------------
# Hedging language
# ---------------------------------------------------------------------------


class TestHedgingLanguage:
    def test_confident_dictionary_has_three_languages(self) -> None:
        assert {"en", "uz", "ru"}.issubset(CONFIDENT_LANGUAGE.keys())
        assert "demonstrates" in CONFIDENT_LANGUAGE["en"]

    def test_cautious_dictionary_has_three_languages(self) -> None:
        assert {"en", "uz", "ru"}.issubset(CAUTIOUS_LANGUAGE.keys())
        assert "may indicate" in CAUTIOUS_LANGUAGE["en"]

    def test_measured_dictionary_has_three_languages(self) -> None:
        assert {"en", "uz", "ru"}.issubset(MEASURED_LANGUAGE.keys())
        assert "suggests" in MEASURED_LANGUAGE["en"]

    def test_alignment_warns_on_confident_near_weak_claim(self) -> None:
        weak_claim = _make_claim(
            "Weak anecdotal claim about cooling adoption rates",
            strength=ClaimStrength.WEAK,
            chunk_id="anec_chunk_1",
        )
        text = "The pilot data demonstrates a substantial gain [anec_chunk_1]."
        warnings = check_hedging_alignment(text, [weak_claim], "en")
        assert any("demonstrates" in w for w in warnings)

    def test_alignment_no_warning_when_aligned(self) -> None:
        moderate_claim = _make_claim(
            "Moderate finding about cooling adoption",
            strength=ClaimStrength.MODERATE,
            chunk_id="m_chunk_1",
        )
        text = "The data suggests an improvement [m_chunk_1]."
        warnings = check_hedging_alignment(text, [moderate_claim], "en")
        assert warnings == []


# ---------------------------------------------------------------------------
# Quality validators
# ---------------------------------------------------------------------------


class TestQualityValidators:
    def test_research_gap_english(self) -> None:
        assert has_research_gap("There is a clear gap in the literature.") is True

    def test_research_gap_uzbek(self) -> None:
        assert has_research_gap("Bu mavzu yetarlicha o'rganilmagan.") is True

    def test_research_gap_negative(self) -> None:
        assert has_research_gap("This paper covers cooling systems generally.") is False

    def test_quantitative_percentage(self) -> None:
        assert has_quantitative_result("savings of 94.4% were observed") is True

    def test_quantitative_pvalue(self) -> None:
        assert has_quantitative_result("results with p < 0.05 are reported") is True

    def test_quantitative_negative(self) -> None:
        assert has_quantitative_result("savings were observed across the sample") is False

    def test_citation_count(self) -> None:
        text = "Claim one [1]. Claim two [2]. Claim three [3]."
        assert has_citations(text, min_count=3) is True
        assert has_citations(text, min_count=4) is False

    def test_within_word_target_within_tolerance(self) -> None:
        text = " ".join(["w"] * 850)
        assert within_word_target(text, target=1000, tolerance=0.2) is True

    def test_within_word_target_outside_tolerance(self) -> None:
        text = " ".join(["w"] * 600)
        assert within_word_target(text, target=1000, tolerance=0.2) is False

    def test_limitations_english(self) -> None:
        assert has_limitations("However, this study is limited by sample size.") is True

    def test_contribution_statement_english(self) -> None:
        assert has_contribution_statement("This paper contributes a comparative analysis.") is True


# ---------------------------------------------------------------------------
# Model validation (round-trip + enum coverage)
# ---------------------------------------------------------------------------


class TestDrafterModels:
    def test_draft_result_round_trip(self) -> None:
        section = _make_article_section(title="x", paragraphs=["body of section"])
        result = DraftResult(
            section=section,
            quality_check=QualityCheckResult(
                passed=True,
                checks_passed=["a"],
                checks_failed=[],
                overall_score=1.0,
            ),
            revision_attempted=False,
            revision_improved=False,
            warnings=["minor"],
            llm_calls_made=1,
            tokens_used=240,
        )
        round_tripped = DraftResult.model_validate(result.model_dump(mode="json"))
        assert round_tripped.tokens_used == 240
        assert round_tripped.quality_check.overall_score == 1.0

    def test_quality_check_result_score(self) -> None:
        qc = QualityCheckResult(
            passed=False,
            checks_passed=["one", "two"],
            checks_failed=["three"],
            overall_score=2 / 3,
        )
        assert len(qc.checks_passed) == 2
        assert len(qc.checks_failed) == 1
        assert qc.passed is False

    def test_article_draft_result_round_trip(self) -> None:
        section = _make_article_section(title="x", paragraphs=["body"])
        draft = DraftResult(
            section=section,
            quality_check=QualityCheckResult(
                passed=True,
                checks_passed=["one"],
                checks_failed=[],
                overall_score=1.0,
            ),
            revision_attempted=False,
            revision_improved=False,
            warnings=[],
            llm_calls_made=1,
            tokens_used=200,
        )
        result = ArticleDraftResult(
            sections=[draft],
            total_word_count=draft.section.word_count,
            total_llm_calls=1,
            total_tokens=200,
            estimated_cost_usd=0.001,
            quality_summary=ArticleQualitySummary(
                sections_passed=1,
                sections_failed=0,
                sections_revised=0,
                overall_score=1.0,
                weakest_section=str(draft.section.id),
                strongest_section=str(draft.section.id),
            ),
            warnings=[],
        )
        round_tripped = ArticleDraftResult.model_validate(result.model_dump(mode="json"))
        assert round_tripped.total_llm_calls == 1
        assert round_tripped.quality_summary.sections_passed == 1

    def test_calibration_level_enum_values(self) -> None:
        names = {level.value for level in CalibrationLevel}
        assert names == {"school", "undergraduate", "masters", "doctoral", "professional"}
