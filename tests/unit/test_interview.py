"""Behaviour tests for :class:`ResearchInterviewEngine`.

We mock :class:`LLMClient.complete` for every test that touches the LLM
(question generation, answer scoring) so the suite remains hermetic and
fast. Pure-logic tests (weakness analysis, credit decisions, model
validation) do not mock anything.

Per ``.claude/rules/testing.md`` we mock only external APIs (Anthropic),
never local libraries or pydantic.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from packages.core.constants import CREDIT_CAPS
from packages.core.enums import (
    CitationStatus,
    ClaimStrength,
    CreditCapHit,
    InterviewMode,
    Language,
    ResearchQuestionType,
    SourceQuality,
    WeaknessDimension,
)
from packages.core.fallback_questions import (
    FALLBACK_QUESTIONS,
    fallback_questions_for,
)
from packages.core.llm import LLMResponse
from packages.core.models import (
    AnswerScore,
    CreditDecision,
    EvidenceMatrix,
    EvidenceMatrixEntry,
    ProcessedAnswer,
    ResearchQuestion,
    ScoredAnswer,
    SourceChunkCreate,
    SourceClaimCreate,
    SourceMetadataExtracted,
    WeaknessProfile,
)
from packages.workers.article import EvidenceMatrixBuilder, ResearchInterviewEngine

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


class _StubLLM:
    """Stand-in for :class:`LLMClient` that returns scripted responses.

    ``responses`` is a list of strings consumed in order. ``raise_on_call``
    forces every call to raise the supplied exception. When responses run
    out, raises ``RuntimeError`` so over-calling fails loudly.
    """

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
            input_tokens=100,
            output_tokens=50,
            latency_ms=10,
            estimated_cost_usd=0.001,
        )


def _now() -> datetime:
    return datetime.now(UTC)


def _chunks(count: int) -> list[SourceChunkCreate]:
    return [
        SourceChunkCreate(
            chunk_index=i,
            text=(
                f"Chunk {i} discusses radiative cooling and thermal management "
                "with detailed measurements and supporting calculations."
            ),
            source_id=str(i),
        )
        for i in range(count)
    ]


def _claim(
    chunk_idx: int,
    text: str,
    strength: ClaimStrength = ClaimStrength.MODERATE,
) -> SourceClaimCreate:
    return SourceClaimCreate(
        source_chunk_id=str(chunk_idx),
        claim_text=text,
        strength=strength,
    )


async def _build_matrix(
    chunks: list[SourceChunkCreate],
    claims: list[SourceClaimCreate],
    project_id: UUID,
    quality: SourceQuality = SourceQuality.MEDIUM,
) -> tuple[EvidenceMatrix, dict[str, UUID]]:
    """Build a matrix and return (matrix, chunk_uuid_map) for tests.

    Because :meth:`EvidenceMatrixBuilder.build_from_claims` mints fresh
    UUIDs internally, we recover the chunk-id → entry-uuid mapping by
    pairing each surviving entry with the claim that produced it (claims
    are processed in input order and entries are appended in that order).
    """

    builder = EvidenceMatrixBuilder()
    matrix = await builder.build_from_claims(project_id, claims, chunks, source_quality=quality)
    surviving_claims = [c for c in claims if any(_chunk_key_match(c, ch) for ch in chunks)]
    mapping: dict[str, UUID] = {}
    for claim, entry in zip(surviving_claims, matrix.entries, strict=False):
        mapping.setdefault(claim.source_chunk_id, entry.source_chunk_id)
    return matrix, mapping


def _chunk_key_match(claim: SourceClaimCreate, chunk: SourceChunkCreate) -> bool:
    if chunk.source_id and chunk.source_id == claim.source_chunk_id:
        return True
    return str(chunk.chunk_index) == claim.source_chunk_id


def _profile(**overrides: float) -> WeaknessProfile:
    base = {
        "thesis_clarity": 0.4,
        "source_coverage": 0.4,
        "contradiction_awareness": 1.0,
        "originality": 0.2,
        "evidence_depth": 0.3,
    }
    base.update(overrides)
    weakest = min(
        (
            (WeaknessDimension.THESIS_CLARITY, base["thesis_clarity"]),
            (WeaknessDimension.SOURCE_COVERAGE, base["source_coverage"]),
            (
                WeaknessDimension.CONTRADICTION_AWARENESS,
                base["contradiction_awareness"],
            ),
            (WeaknessDimension.ORIGINALITY, base["originality"]),
            (WeaknessDimension.EVIDENCE_DEPTH, base["evidence_depth"]),
        ),
        key=lambda kv: kv[1],
    )[0]
    return WeaknessProfile(
        thesis_clarity=base["thesis_clarity"],
        source_coverage=base["source_coverage"],
        contradiction_awareness=base["contradiction_awareness"],
        originality=base["originality"],
        evidence_depth=base["evidence_depth"],
        weakest_dimension=weakest,
        summary="Synthetic profile for testing.",
    )


def _question(
    project_id: UUID, qtype: ResearchQuestionType = ResearchQuestionType.SOURCE_COVERAGE
) -> ResearchQuestion:
    return ResearchQuestion(
        project_id=project_id,
        question_text="What is the main argument of source 0?",
        question_type=qtype,
        related_source_ids=[],
        created_at=_now(),
    )


def _questions_payload(
    count: int, qtype: str = "source_coverage", related: list[str] | None = None
) -> str:
    return json.dumps(
        [
            {
                "question_text": f"Generated question {i} about your sources?",
                "question_type": qtype,
                "related_source_ids": related or [],
                "purpose": "Tests source comprehension.",
            }
            for i in range(count)
        ]
    )


def _score_payload(
    specificity: int = 4,
    source_grounding: int = 4,
    usefulness: int = 4,
    referenced: list[str] | None = None,
    feedback: str = "Good answer.",
) -> str:
    return json.dumps(
        {
            "specificity": specificity,
            "source_grounding": source_grounding,
            "usefulness": usefulness,
            "referenced_chunks": referenced or [],
            "feedback": feedback,
        }
    )


# ---------------------------------------------------------------------------
# analyze_weaknesses (no LLM)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_analyze_weaknesses_all_strong() -> None:
    engine = ResearchInterviewEngine(llm=_StubLLM())
    project_id = uuid4()
    chunks = _chunks(3)
    claims = [
        _claim(
            i,
            "Radiative cooling delivers measurable thermal savings in arid climates.",
            ClaimStrength.STRONG,
        )
        for i in range(3)
    ]
    matrix, _ = await _build_matrix(chunks, claims, project_id, quality=SourceQuality.STRONG)

    profile = engine.analyze_weaknesses(matrix, claims, chunks)

    assert profile.thesis_clarity >= 0.7
    assert profile.source_coverage >= 0.7
    assert profile.contradiction_awareness >= 0.7
    assert profile.evidence_depth >= 0.7
    assert profile.originality == pytest.approx(0.2)


@pytest.mark.asyncio
async def test_analyze_weaknesses_no_claims() -> None:
    engine = ResearchInterviewEngine(llm=_StubLLM())
    matrix = EvidenceMatrix(project_id=uuid4(), entries=[])

    profile = engine.analyze_weaknesses(matrix, [], [])

    assert profile.thesis_clarity == 0.0
    assert profile.source_coverage == 0.0
    assert profile.evidence_depth == 0.0
    assert profile.weakest_dimension in {
        WeaknessDimension.THESIS_CLARITY,
        WeaknessDimension.SOURCE_COVERAGE,
        WeaknessDimension.ORIGINALITY,
        WeaknessDimension.EVIDENCE_DEPTH,
    }


@pytest.mark.asyncio
async def test_analyze_weaknesses_scattered_claims() -> None:
    engine = ResearchInterviewEngine(llm=_StubLLM())
    project_id = uuid4()
    chunks = _chunks(5)
    claims = [
        _claim(0, "Quantum chromodynamics describes strong nuclear forces."),
        _claim(1, "Medieval Persian poetry flourished under Timurid patronage."),
        _claim(2, "Photosynthesis converts solar energy into chemical bonds."),
        _claim(3, "Constitutional reform reshaped twentieth century governance."),
        _claim(4, "Plate tectonics explains continental drift over millennia."),
    ]
    matrix, _ = await _build_matrix(chunks, claims, project_id)

    profile = engine.analyze_weaknesses(matrix, claims, chunks)

    assert profile.thesis_clarity < 0.5


@pytest.mark.asyncio
async def test_analyze_weaknesses_source_gap() -> None:
    engine = ResearchInterviewEngine(llm=_StubLLM())
    project_id = uuid4()
    chunks = _chunks(5)
    claims = [
        _claim(0, "First chunk yields a substantive measurable claim."),
        _claim(1, "Second chunk yields a substantive measurable claim."),
    ]
    matrix, _ = await _build_matrix(chunks, claims, project_id)

    profile = engine.analyze_weaknesses(matrix, claims, chunks)

    assert profile.source_coverage < 0.5


@pytest.mark.asyncio
async def test_analyze_weaknesses_evidence_depth() -> None:
    engine = ResearchInterviewEngine(llm=_StubLLM())
    project_id = uuid4()
    entries: list[EvidenceMatrixEntry] = []
    for i in range(10):
        status = CitationStatus.READY if i < 3 else CitationStatus.NEEDS_USER_INPUT
        entries.append(
            EvidenceMatrixEntry(
                project_id=project_id,
                claim_id=uuid4(),
                source_chunk_id=uuid4(),
                citation_status=status,
                created_at=_now(),
            )
        )
    matrix = EvidenceMatrix(project_id=project_id, entries=entries)

    profile = engine.analyze_weaknesses(matrix, [], [])

    assert profile.evidence_depth == pytest.approx(0.3)


# ---------------------------------------------------------------------------
# generate_questions (LLM mocked)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_questions_guided_mode_count() -> None:
    stub = _StubLLM(responses=[_questions_payload(4)])
    engine = ResearchInterviewEngine(llm=stub)
    project_id = uuid4()
    chunks = _chunks(2)

    questions = await engine.generate_questions(
        project_id=project_id,
        profile=_profile(),
        matrix=EvidenceMatrix(project_id=project_id, entries=[]),
        claims=[],
        chunks=chunks,
        source_metadata=[SourceMetadataExtracted(title="A")],
        source_ids=[uuid4()],
        language=Language.EN,
        mode=InterviewMode.GUIDED,
    )

    assert 3 <= len(questions) <= 5


@pytest.mark.asyncio
async def test_generate_questions_research_mode_count() -> None:
    stub = _StubLLM(responses=[_questions_payload(10)])
    engine = ResearchInterviewEngine(llm=stub)
    project_id = uuid4()

    questions = await engine.generate_questions(
        project_id=project_id,
        profile=_profile(),
        matrix=EvidenceMatrix(project_id=project_id, entries=[]),
        claims=[],
        chunks=_chunks(2),
        source_metadata=[SourceMetadataExtracted(title="A")],
        source_ids=[uuid4()],
        language=Language.EN,
        mode=InterviewMode.RESEARCH,
    )

    assert 8 <= len(questions) <= 12


@pytest.mark.asyncio
async def test_generate_questions_targets_weakest_dimension() -> None:
    payload = json.dumps(
        [
            {
                "question_text": "What is your central thesis?",
                "question_type": "thesis_clarity",
                "related_source_ids": [],
                "purpose": "Pin the thesis.",
            },
            {
                "question_text": "Name source 0's main claim.",
                "question_type": "source_coverage",
                "related_source_ids": [],
                "purpose": "Engage source 0.",
            },
            {
                "question_text": "What local example applies here?",
                "question_type": "originality",
                "related_source_ids": [],
                "purpose": "Local relevance.",
            },
            {
                "question_text": "Pick the side between sources.",
                "question_type": "contradiction",
                "related_source_ids": [],
                "purpose": "Force a stand.",
            },
        ]
    )
    stub = _StubLLM(responses=[payload])
    engine = ResearchInterviewEngine(llm=stub)
    project_id = uuid4()

    questions = await engine.generate_questions(
        project_id=project_id,
        profile=_profile(thesis_clarity=0.1),
        matrix=EvidenceMatrix(project_id=project_id, entries=[]),
        claims=[],
        chunks=_chunks(1),
        source_metadata=[],
        source_ids=[],
        language=Language.EN,
        mode=InterviewMode.GUIDED,
    )

    assert any(q.question_type is ResearchQuestionType.THESIS_CLARITY for q in questions)


@pytest.mark.asyncio
async def test_generate_questions_fallback_on_llm_failure() -> None:
    stub = _StubLLM(raise_on_call=RuntimeError("network down"))
    engine = ResearchInterviewEngine(llm=stub)
    project_id = uuid4()

    questions = await engine.generate_questions(
        project_id=project_id,
        profile=_profile(),
        matrix=EvidenceMatrix(project_id=project_id, entries=[]),
        claims=[],
        chunks=_chunks(1),
        source_metadata=[],
        source_ids=[],
        language=Language.UZ,
        mode=InterviewMode.GUIDED,
    )

    assert len(questions) > 0
    assert all(q.project_id == project_id for q in questions)
    fallback_texts = {text for text, _ in fallback_questions_for(Language.UZ)}
    assert any(q.question_text in fallback_texts for q in questions)


@pytest.mark.asyncio
async def test_generate_questions_uzbek_language() -> None:
    payload = json.dumps(
        [
            {
                "question_text": "Asosiy tezisingiz nima va qaysi manba uni qo'llab-quvvatlaydi?",
                "question_type": "thesis_clarity",
                "related_source_ids": [],
                "purpose": "Tezisni aniqlash.",
            }
            for _ in range(4)
        ]
    )
    stub = _StubLLM(responses=[payload])
    engine = ResearchInterviewEngine(llm=stub)
    project_id = uuid4()

    questions = await engine.generate_questions(
        project_id=project_id,
        profile=_profile(),
        matrix=EvidenceMatrix(project_id=project_id, entries=[]),
        claims=[],
        chunks=_chunks(1),
        source_metadata=[SourceMetadataExtracted(title="Manba")],
        source_ids=[uuid4()],
        language=Language.UZ,
        mode=InterviewMode.GUIDED,
    )

    assert len(questions) == 4
    assert "Asosiy" in questions[0].question_text


@pytest.mark.asyncio
async def test_generate_questions_russian_language() -> None:
    payload = json.dumps(
        [
            {
                "question_text": "Каков ваш основной тезис?",
                "question_type": "thesis_clarity",
                "related_source_ids": [],
                "purpose": "Уточнить тезис.",
            }
            for _ in range(4)
        ]
    )
    stub = _StubLLM(responses=[payload])
    engine = ResearchInterviewEngine(llm=stub)
    project_id = uuid4()

    questions = await engine.generate_questions(
        project_id=project_id,
        profile=_profile(),
        matrix=EvidenceMatrix(project_id=project_id, entries=[]),
        claims=[],
        chunks=_chunks(1),
        source_metadata=[],
        source_ids=[],
        language=Language.RU,
        mode=InterviewMode.GUIDED,
    )

    assert len(questions) == 4
    assert "тезис" in questions[0].question_text.lower()


@pytest.mark.asyncio
async def test_generate_questions_validates_llm_json() -> None:
    stub = _StubLLM(responses=[_questions_payload(3, qtype="source_coverage")])
    engine = ResearchInterviewEngine(llm=stub)
    project_id = uuid4()

    questions = await engine.generate_questions(
        project_id=project_id,
        profile=_profile(),
        matrix=EvidenceMatrix(project_id=project_id, entries=[]),
        claims=[],
        chunks=_chunks(1),
        source_metadata=[],
        source_ids=[],
        language=Language.EN,
        mode=InterviewMode.GUIDED,
    )

    for q in questions:
        assert q.question_text
        assert q.question_type in ResearchQuestionType
        assert isinstance(q.related_source_ids, list)


@pytest.mark.asyncio
async def test_generate_questions_invalid_json_retries() -> None:
    stub = _StubLLM(responses=["not json at all", _questions_payload(4)])
    engine = ResearchInterviewEngine(llm=stub)
    project_id = uuid4()

    questions = await engine.generate_questions(
        project_id=project_id,
        profile=_profile(),
        matrix=EvidenceMatrix(project_id=project_id, entries=[]),
        claims=[],
        chunks=_chunks(1),
        source_metadata=[],
        source_ids=[],
        language=Language.EN,
        mode=InterviewMode.GUIDED,
    )

    assert len(questions) == 4
    assert len(stub.calls) == 2


@pytest.mark.asyncio
async def test_generate_questions_resolves_source_uuids() -> None:
    source_uuid = uuid4()
    payload = json.dumps(
        [
            {
                "question_text": "What does source 0 say about cooling?",
                "question_type": "source_coverage",
                "related_source_ids": ["source_0"],
                "purpose": "Engage source 0.",
            },
            {
                "question_text": "Generic question without source link.",
                "question_type": "source_coverage",
                "related_source_ids": [],
                "purpose": "No source.",
            },
            {
                "question_text": "Another generic prompt.",
                "question_type": "source_coverage",
                "related_source_ids": [],
                "purpose": "Filler.",
            },
            {
                "question_text": "Filler four.",
                "question_type": "source_coverage",
                "related_source_ids": [],
                "purpose": "Filler.",
            },
        ]
    )
    stub = _StubLLM(responses=[payload])
    engine = ResearchInterviewEngine(llm=stub)
    project_id = uuid4()

    questions = await engine.generate_questions(
        project_id=project_id,
        profile=_profile(),
        matrix=EvidenceMatrix(project_id=project_id, entries=[]),
        claims=[],
        chunks=_chunks(1),
        source_metadata=[SourceMetadataExtracted(title="Cooling")],
        source_ids=[source_uuid],
        language=Language.EN,
        mode=InterviewMode.GUIDED,
    )

    assert questions[0].related_source_ids == [source_uuid]


@pytest.mark.asyncio
async def test_generate_questions_strips_purpose_field() -> None:
    """ResearchQuestion has extra='forbid'; ``purpose`` must be filtered out."""

    stub = _StubLLM(responses=[_questions_payload(4)])
    engine = ResearchInterviewEngine(llm=stub)
    project_id = uuid4()

    questions = await engine.generate_questions(
        project_id=project_id,
        profile=_profile(),
        matrix=EvidenceMatrix(project_id=project_id, entries=[]),
        claims=[],
        chunks=_chunks(1),
        source_metadata=[],
        source_ids=[],
        language=Language.EN,
        mode=InterviewMode.GUIDED,
    )

    assert len(questions) == 4


@pytest.mark.asyncio
async def test_generate_questions_rejects_fast_mode() -> None:
    engine = ResearchInterviewEngine(llm=_StubLLM())
    project_id = uuid4()

    with pytest.raises(ValueError):
        await engine.generate_questions(
            project_id=project_id,
            profile=_profile(),
            matrix=EvidenceMatrix(project_id=project_id, entries=[]),
            claims=[],
            chunks=_chunks(1),
            source_metadata=[],
            source_ids=[],
            language=Language.EN,
            mode=InterviewMode.FAST,
        )


# ---------------------------------------------------------------------------
# score_answer (LLM mocked)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_score_answer_high_quality() -> None:
    stub = _StubLLM(responses=[_score_payload(specificity=5, source_grounding=4, usefulness=5)])
    engine = ResearchInterviewEngine(llm=stub)
    project_id = uuid4()

    scored = await engine.score_answer(
        question=_question(project_id),
        answer_text="Source 0 reports 94.4% water savings in Seattle field trials.",
        chunks=_chunks(2),
        language=Language.EN,
    )

    assert scored.score.specificity == 5
    assert scored.score.source_grounding == 4
    assert scored.score.usefulness == 5


@pytest.mark.asyncio
async def test_score_answer_low_quality() -> None:
    stub = _StubLLM(responses=[_score_payload(specificity=1, source_grounding=1, usefulness=2)])
    engine = ResearchInterviewEngine(llm=stub)
    project_id = uuid4()

    scored = await engine.score_answer(
        question=_question(project_id),
        answer_text="It's interesting and important.",
        chunks=_chunks(1),
        language=Language.EN,
    )

    total = scored.score.specificity + scored.score.source_grounding + scored.score.usefulness
    assert total < 7


@pytest.mark.asyncio
async def test_score_answer_llm_failure_returns_default() -> None:
    stub = _StubLLM(raise_on_call=RuntimeError("network down"))
    engine = ResearchInterviewEngine(llm=stub)
    project_id = uuid4()

    scored = await engine.score_answer(
        question=_question(project_id),
        answer_text="Some answer.",
        chunks=_chunks(1),
        language=Language.EN,
    )

    assert scored.score.specificity == 2
    assert scored.score.source_grounding == 2
    assert scored.score.usefulness == 2
    assert "could not evaluate" in scored.feedback.lower()


@pytest.mark.asyncio
async def test_score_answer_validates_score_range() -> None:
    stub = _StubLLM(responses=[_score_payload(specificity=7, source_grounding=-1, usefulness=3)])
    engine = ResearchInterviewEngine(llm=stub)
    project_id = uuid4()

    scored = await engine.score_answer(
        question=_question(project_id),
        answer_text="An answer.",
        chunks=_chunks(1),
        language=Language.EN,
    )

    assert 0 <= scored.score.specificity <= 5
    assert 0 <= scored.score.source_grounding <= 5
    assert scored.score.specificity == 5
    assert scored.score.source_grounding == 0


@pytest.mark.asyncio
async def test_score_answer_includes_feedback() -> None:
    stub = _StubLLM(responses=[_score_payload(feedback="Add a specific data point from source 0.")])
    engine = ResearchInterviewEngine(llm=stub)
    project_id = uuid4()

    scored = await engine.score_answer(
        question=_question(project_id),
        answer_text="An answer.",
        chunks=_chunks(1),
        language=Language.EN,
    )

    assert scored.feedback
    assert "specific" in scored.feedback.lower()


@pytest.mark.asyncio
async def test_score_answer_invalid_json_retries_then_succeeds() -> None:
    stub = _StubLLM(responses=["garbage", _score_payload()])
    engine = ResearchInterviewEngine(llm=stub)
    project_id = uuid4()

    scored = await engine.score_answer(
        question=_question(project_id),
        answer_text="An answer.",
        chunks=_chunks(1),
        language=Language.EN,
    )

    assert len(stub.calls) == 2
    assert scored.score.specificity == 4


# ---------------------------------------------------------------------------
# determine_credits (no LLM)
# ---------------------------------------------------------------------------


def _engine() -> ResearchInterviewEngine:
    return ResearchInterviewEngine(llm=_StubLLM())


def test_credits_high_score_earns_1() -> None:
    engine = _engine()
    score = AnswerScore(specificity=4, source_grounding=3, usefulness=3)  # total 10

    decision = engine.determine_credits(
        score, project_credits_used=0, daily_credits_used=0, weekly_credits_used=0
    )

    assert decision.credits_earned == 1
    assert decision.capped is False


def test_credits_exceptional_score_earns_2() -> None:
    engine = _engine()
    score = AnswerScore(specificity=5, source_grounding=4, usefulness=4)  # total 13

    decision = engine.determine_credits(
        score, project_credits_used=0, daily_credits_used=0, weekly_credits_used=0
    )

    assert decision.credits_earned == 2


def test_credits_low_score_earns_0() -> None:
    engine = _engine()
    score = AnswerScore(specificity=2, source_grounding=2, usefulness=3)  # total 7

    decision = engine.determine_credits(
        score, project_credits_used=0, daily_credits_used=0, weekly_credits_used=0
    )

    assert decision.credits_earned == 0
    assert decision.capped is False


def test_credits_capped_daily() -> None:
    engine = _engine()
    score = AnswerScore(specificity=5, source_grounding=4, usefulness=4)  # total 13

    decision = engine.determine_credits(
        score,
        project_credits_used=0,
        daily_credits_used=CREDIT_CAPS["daily"],
        weekly_credits_used=0,
    )

    assert decision.credits_earned == 0
    assert decision.capped is True
    assert decision.cap_hit is CreditCapHit.DAILY


def test_credits_capped_weekly() -> None:
    engine = _engine()
    score = AnswerScore(specificity=4, source_grounding=3, usefulness=3)  # total 10

    decision = engine.determine_credits(
        score,
        project_credits_used=0,
        daily_credits_used=0,
        weekly_credits_used=CREDIT_CAPS["weekly"],
    )

    assert decision.credits_earned == 0
    assert decision.capped is True
    assert decision.cap_hit is CreditCapHit.WEEKLY


def test_credits_capped_per_project() -> None:
    engine = _engine()
    score = AnswerScore(specificity=4, source_grounding=3, usefulness=3)  # total 10

    decision = engine.determine_credits(
        score,
        project_credits_used=CREDIT_CAPS["per_project"],
        daily_credits_used=0,
        weekly_credits_used=0,
    )

    assert decision.credits_earned == 0
    assert decision.capped is True
    assert decision.cap_hit is CreditCapHit.PER_PROJECT


# ---------------------------------------------------------------------------
# process_answer (LLM mocked for scoring; matrix update is real)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_process_answer_full_flow() -> None:
    project_id = uuid4()
    chunks = _chunks(2)
    claims = [_claim(0, "A claim awaiting grounding here.")]
    matrix, mapping = await _build_matrix(chunks, claims, project_id)

    chunk_key = "0"
    stub = _StubLLM(
        responses=[
            _score_payload(
                specificity=5,
                source_grounding=4,
                usefulness=4,
                referenced=[chunk_key],
            )
        ]
    )
    engine = ResearchInterviewEngine(llm=stub)

    result = await engine.process_answer(
        project_id=project_id,
        question=_question(project_id),
        answer_text="In Seattle field trials reported by source 0, savings reached 94.4%.",
        matrix=matrix,
        chunks=chunks,
        chunk_uuid_map=mapping,
        language=Language.EN,
        project_credits_used=0,
        daily_credits_used=0,
        weekly_credits_used=0,
    )

    assert result.scored_answer.score.specificity == 5
    assert result.credit_decision.credits_earned >= 1
    assert result.updated_matrix is not None
    assert "strengthened" in result.feedback_message


@pytest.mark.asyncio
async def test_process_answer_updates_evidence_matrix() -> None:
    project_id = uuid4()
    chunks = _chunks(1)
    claims = [_claim(0, "A claim that needs user grounding still here.")]
    matrix, mapping = await _build_matrix(chunks, claims, project_id)

    stub = _StubLLM(
        responses=[
            _score_payload(
                specificity=5,
                source_grounding=4,
                usefulness=4,
                referenced=["0"],
            )
        ]
    )
    engine = ResearchInterviewEngine(llm=stub)

    result = await engine.process_answer(
        project_id=project_id,
        question=_question(project_id),
        answer_text="Specific evidence drawn directly from source 0.",
        matrix=matrix,
        chunks=chunks,
        chunk_uuid_map=mapping,
        language=Language.EN,
        project_credits_used=0,
        daily_credits_used=0,
        weekly_credits_used=0,
    )

    assert result.evidence_entries_updated > 0
    updated_entry = result.updated_matrix.entries[0]
    assert updated_entry.user_answer_id is not None
    assert updated_entry.citation_status is CitationStatus.READY


@pytest.mark.asyncio
async def test_process_answer_feedback_uzbek() -> None:
    project_id = uuid4()
    chunks = _chunks(1)
    claims = [_claim(0, "A claim awaiting grounding still here.")]
    matrix, mapping = await _build_matrix(chunks, claims, project_id)

    stub = _StubLLM(
        responses=[
            _score_payload(
                specificity=5,
                source_grounding=4,
                usefulness=4,
                referenced=["0"],
            )
        ]
    )
    engine = ResearchInterviewEngine(llm=stub)

    result = await engine.process_answer(
        project_id=project_id,
        question=_question(project_id),
        answer_text="Manba 0 da aniq ma'lumot keltirilgan.",
        matrix=matrix,
        chunks=chunks,
        chunk_uuid_map=mapping,
        language=Language.UZ,
        project_credits_used=0,
        daily_credits_used=0,
        weekly_credits_used=0,
    )

    assert "kuchaydi" in result.feedback_message


@pytest.mark.asyncio
async def test_process_answer_feedback_russian() -> None:
    project_id = uuid4()
    chunks = _chunks(1)
    claims = [_claim(0, "A claim awaiting grounding still here.")]
    matrix, mapping = await _build_matrix(chunks, claims, project_id)

    stub = _StubLLM(
        responses=[
            _score_payload(
                specificity=5,
                source_grounding=4,
                usefulness=4,
                referenced=["0"],
            )
        ]
    )
    engine = ResearchInterviewEngine(llm=stub)

    result = await engine.process_answer(
        project_id=project_id,
        question=_question(project_id),
        answer_text="В источнике 0 приведены конкретные данные.",
        matrix=matrix,
        chunks=chunks,
        chunk_uuid_map=mapping,
        language=Language.RU,
        project_credits_used=0,
        daily_credits_used=0,
        weekly_credits_used=0,
    )

    assert "усилил" in result.feedback_message


@pytest.mark.asyncio
async def test_process_answer_feedback_english() -> None:
    project_id = uuid4()
    chunks = _chunks(1)
    claims = [_claim(0, "A claim awaiting grounding still here.")]
    matrix, mapping = await _build_matrix(chunks, claims, project_id)

    stub = _StubLLM(
        responses=[
            _score_payload(
                specificity=5,
                source_grounding=4,
                usefulness=4,
                referenced=["0"],
            )
        ]
    )
    engine = ResearchInterviewEngine(llm=stub)

    result = await engine.process_answer(
        project_id=project_id,
        question=_question(project_id),
        answer_text="Source 0 reports specific savings of 94.4% in field trials.",
        matrix=matrix,
        chunks=chunks,
        chunk_uuid_map=mapping,
        language=Language.EN,
        project_credits_used=0,
        daily_credits_used=0,
        weekly_credits_used=0,
    )

    assert "strengthened" in result.feedback_message


# ---------------------------------------------------------------------------
# Fallback questions
# ---------------------------------------------------------------------------


def test_fallback_questions_uzbek_exist() -> None:
    pool = fallback_questions_for(Language.UZ)
    assert len(pool) >= 5
    for text, qtype in pool:
        assert text
        assert qtype in ResearchQuestionType


def test_fallback_questions_russian_exist() -> None:
    pool = fallback_questions_for(Language.RU)
    assert len(pool) >= 5
    for text, qtype in pool:
        assert text
        assert qtype in ResearchQuestionType


def test_fallback_questions_english_exist() -> None:
    pool = fallback_questions_for(Language.EN)
    assert len(pool) >= 5


def test_fallback_questions_cover_all_types() -> None:
    for lang in (Language.UZ, Language.RU, Language.EN):
        types = {qt for _, qt in FALLBACK_QUESTIONS[lang]}
        for required in ResearchQuestionType:
            assert required in types, f"{lang.value} missing {required.value}"


# ---------------------------------------------------------------------------
# Model validation
# ---------------------------------------------------------------------------


def test_weakness_profile_bounds() -> None:
    with pytest.raises(ValidationError):
        WeaknessProfile(
            thesis_clarity=-0.1,
            source_coverage=0.5,
            contradiction_awareness=0.5,
            originality=0.5,
            evidence_depth=0.5,
            weakest_dimension=WeaknessDimension.ORIGINALITY,
            summary="x",
        )
    with pytest.raises(ValidationError):
        WeaknessProfile(
            thesis_clarity=0.5,
            source_coverage=1.1,
            contradiction_awareness=0.5,
            originality=0.5,
            evidence_depth=0.5,
            weakest_dimension=WeaknessDimension.ORIGINALITY,
            summary="x",
        )


def test_scored_answer_model() -> None:
    scored = ScoredAnswer(
        question_id=uuid4(),
        answer_text="An answer.",
        score=AnswerScore(specificity=3, source_grounding=3, usefulness=3),
        referenced_chunk_ids=["0", "1"],
        feedback="OK.",
    )
    restored = ScoredAnswer.model_validate(scored.model_dump())
    assert restored == scored


def test_credit_decision_model() -> None:
    decision = CreditDecision(credits_earned=1, reason="ok", capped=False, cap_hit=None)
    restored = CreditDecision.model_validate(decision.model_dump())
    assert restored == decision

    with pytest.raises(ValidationError):
        CreditDecision(credits_earned=-1, reason="x")


def test_processed_answer_model() -> None:
    project_id = uuid4()
    matrix = EvidenceMatrix(project_id=project_id, entries=[])
    scored = ScoredAnswer(
        question_id=uuid4(),
        answer_text="An answer.",
        score=AnswerScore(specificity=3, source_grounding=3, usefulness=3),
        referenced_chunk_ids=[],
        feedback="OK.",
    )
    decision = CreditDecision(credits_earned=1, reason="ok")
    processed = ProcessedAnswer(
        scored_answer=scored,
        credit_decision=decision,
        updated_matrix=matrix,
        feedback_message="Done.",
        evidence_entries_updated=0,
    )
    restored = ProcessedAnswer.model_validate(processed.model_dump())
    assert restored == processed
