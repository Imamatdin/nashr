"""Behaviour tests for :class:`EvidenceMatrixBuilder` and the matrix models.

These tests pin the contract that the article worker depends on:

* every claim becomes one matrix entry;
* strong claims from strong sources auto-promote to ``READY``;
* user research answers can promote, link, or be ignored based on score;
* matrix entries are routed to article sections via exact claim-id match;
* validation flags missing or fragile sections.

The builder methods are async (per spec) but currently do no I/O — that's
intentional, so the article-orchestrator can switch to a persistence-backed
implementation later without changing call sites.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from packages.core.enums import (
    ArticleStructure,
    CitationStatus,
    ClaimStrength,
    ResearchQuestionType,
    SourceQuality,
)
from packages.core.models import (
    AnswerScore,
    ArticleOutline,
    EvidenceMatrixEntry,
    OutlineSection,
    ResearchAnswer,
    SourceChunkCreate,
    SourceClaimCreate,
)
from packages.core.models.evidence import (
    EvidenceMatrix,
    EvidenceMatrixStats,
    MatrixValidationResult,
)
from packages.workers.article import EvidenceMatrixBuilder


def _now() -> datetime:
    return datetime.now(UTC)


def _chunks(count: int) -> list[SourceChunkCreate]:
    """Build ``count`` chunks with ``chunk_index`` 0..count-1 and matching source_id."""

    return [
        SourceChunkCreate(
            chunk_index=i,
            text=f"Chunk number {i} contains substantive content for testing.",
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


def _outline(section_titles: list[str], key_claims: list[list[str]]) -> ArticleOutline:
    """Build an outline whose sections carry the given key_claims_to_use lists."""

    sections = [
        OutlineSection(
            title=title,
            target_words=300,
            key_claims_to_use=keys,
            purpose=f"Purpose for {title}",
        )
        for title, keys in zip(section_titles, key_claims, strict=True)
    ]
    return ArticleOutline(
        title="Test article",
        structure=ArticleStructure.REFERAT,
        sections=sections,
        thesis="Test thesis statement.",
        total_target_words=300 * len(sections),
    )


# ---------------------------------------------------------------------------
# build_from_claims
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_from_claims_creates_entries() -> None:
    builder = EvidenceMatrixBuilder()
    project_id = uuid4()
    chunks = _chunks(3)
    claims = [
        _claim(0, "Claim alpha about chunk zero with detail."),
        _claim(0, "Claim beta about chunk zero with detail."),
        _claim(1, "Claim gamma about chunk one with detail."),
        _claim(2, "Claim delta about chunk two with detail."),
        _claim(2, "Claim epsilon about chunk two with detail."),
    ]

    matrix = await builder.build_from_claims(project_id, claims, chunks)

    assert len(matrix.entries) == 5
    assert all(e.project_id == project_id for e in matrix.entries)
    assert all(e.citation_status is CitationStatus.NEEDS_USER_INPUT for e in matrix.entries)


@pytest.mark.asyncio
async def test_build_auto_promotes_strong_claims() -> None:
    builder = EvidenceMatrixBuilder()
    chunks = _chunks(1)
    claims = [
        _claim(0, "A strong claim with detailed content here.", ClaimStrength.STRONG),
        _claim(0, "A moderate claim with detailed content here.", ClaimStrength.MODERATE),
    ]

    matrix = await builder.build_from_claims(
        uuid4(), claims, chunks, source_quality=SourceQuality.STRONG
    )

    assert matrix.entries[0].citation_status is CitationStatus.READY
    assert matrix.entries[1].citation_status is CitationStatus.NEEDS_USER_INPUT


@pytest.mark.asyncio
async def test_build_strong_claim_with_weak_source_stays_unready() -> None:
    builder = EvidenceMatrixBuilder()
    chunks = _chunks(1)
    claims = [_claim(0, "A strong claim from a weak source.", ClaimStrength.STRONG)]

    matrix = await builder.build_from_claims(
        uuid4(), claims, chunks, source_quality=SourceQuality.WEAK
    )

    assert matrix.entries[0].citation_status is CitationStatus.NEEDS_USER_INPUT


@pytest.mark.asyncio
async def test_build_weak_claims_stay_unready() -> None:
    builder = EvidenceMatrixBuilder()
    chunks = _chunks(1)
    claims = [
        _claim(0, "A weak claim with content here for testing.", ClaimStrength.WEAK),
    ]

    matrix = await builder.build_from_claims(
        uuid4(), claims, chunks, source_quality=SourceQuality.STRONG
    )

    assert matrix.entries[0].citation_status is CitationStatus.NEEDS_USER_INPUT


@pytest.mark.asyncio
async def test_build_skips_claims_with_unresolved_chunk() -> None:
    builder = EvidenceMatrixBuilder()
    chunks = _chunks(2)
    claims = [
        _claim(0, "A claim that resolves correctly here."),
        SourceClaimCreate(
            source_chunk_id="999",
            claim_text="A claim referencing a chunk that does not exist.",
            strength=ClaimStrength.MODERATE,
        ),
    ]

    matrix = await builder.build_from_claims(uuid4(), claims, chunks)

    assert len(matrix.entries) == 1


# ---------------------------------------------------------------------------
# update_with_answer
# ---------------------------------------------------------------------------


def _answer(
    project_id: UUID,
    chunk_uuids: list[UUID],
    score: AnswerScore,
) -> ResearchAnswer:
    return ResearchAnswer(
        project_id=project_id,
        question_id=uuid4(),
        answer_text="The user's explanation tying the claim to the thesis.",
        source_references_used=chunk_uuids,
        score=score,
        credits_earned=1,
        created_at=_now(),
    )


@pytest.mark.asyncio
async def test_update_with_strong_answer_promotes_to_ready() -> None:
    builder = EvidenceMatrixBuilder()
    project_id = uuid4()
    chunks = _chunks(1)
    claims = [_claim(0, "A claim that needs user grounding still here.")]
    matrix = await builder.build_from_claims(project_id, claims, chunks)

    chunk_uuid = matrix.entries[0].source_chunk_id
    answer = _answer(
        project_id,
        [chunk_uuid],
        AnswerScore(specificity=4, source_grounding=4, usefulness=3),  # total 11
    )

    updated = await builder.update_with_answer(matrix, answer)

    assert updated.entries[0].citation_status is CitationStatus.READY
    assert updated.entries[0].user_answer_id == answer.id


@pytest.mark.asyncio
async def test_update_with_weak_answer_keeps_needs_input_but_links() -> None:
    builder = EvidenceMatrixBuilder()
    project_id = uuid4()
    chunks = _chunks(1)
    claims = [_claim(0, "A claim awaiting weak grounding here please.")]
    matrix = await builder.build_from_claims(project_id, claims, chunks)

    chunk_uuid = matrix.entries[0].source_chunk_id
    answer = _answer(
        project_id,
        [chunk_uuid],
        AnswerScore(specificity=2, source_grounding=2, usefulness=2),  # total 6
    )

    updated = await builder.update_with_answer(matrix, answer)

    assert updated.entries[0].citation_status is CitationStatus.NEEDS_USER_INPUT
    assert updated.entries[0].user_answer_id == answer.id


@pytest.mark.asyncio
async def test_update_with_medium_answer_keeps_needs_input_but_links() -> None:
    builder = EvidenceMatrixBuilder()
    project_id = uuid4()
    chunks = _chunks(1)
    claims = [_claim(0, "A claim awaiting medium grounding here please.")]
    matrix = await builder.build_from_claims(project_id, claims, chunks)

    chunk_uuid = matrix.entries[0].source_chunk_id
    answer = _answer(
        project_id,
        [chunk_uuid],
        AnswerScore(specificity=3, source_grounding=3, usefulness=2),  # total 8
    )

    updated = await builder.update_with_answer(matrix, answer)

    assert updated.entries[0].citation_status is CitationStatus.NEEDS_USER_INPUT
    assert updated.entries[0].user_answer_id == answer.id


@pytest.mark.asyncio
async def test_update_only_affects_referenced_chunks() -> None:
    builder = EvidenceMatrixBuilder()
    project_id = uuid4()
    chunks = _chunks(2)
    claims = [
        _claim(0, "Claim about chunk zero awaiting input here."),
        _claim(1, "Claim about chunk one awaiting input here."),
    ]
    matrix = await builder.build_from_claims(project_id, claims, chunks)

    chunk0_uuid = next(
        e.source_chunk_id for e in matrix.entries if e.claim_id == matrix.entries[0].claim_id
    )
    answer = _answer(
        project_id,
        [chunk0_uuid],
        AnswerScore(specificity=5, source_grounding=5, usefulness=5),  # total 15
    )

    updated = await builder.update_with_answer(matrix, answer)

    chunk0_entry = next(e for e in updated.entries if e.source_chunk_id == chunk0_uuid)
    chunk1_entry = next(e for e in updated.entries if e.source_chunk_id != chunk0_uuid)

    assert chunk0_entry.citation_status is CitationStatus.READY
    assert chunk1_entry.citation_status is CitationStatus.NEEDS_USER_INPUT
    assert chunk1_entry.user_answer_id is None


# ---------------------------------------------------------------------------
# assign_to_sections
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_assign_to_sections() -> None:
    builder = EvidenceMatrixBuilder()
    project_id = uuid4()
    chunks = _chunks(3)
    claims = [
        _claim(0, "Claim alpha about chunk zero with detail."),
        _claim(1, "Claim beta about chunk one with detail."),
        _claim(2, "Claim gamma about chunk two with detail."),
    ]
    matrix = await builder.build_from_claims(project_id, claims, chunks)

    cid_a = str(matrix.entries[0].claim_id)
    cid_b = str(matrix.entries[1].claim_id)
    cid_c = str(matrix.entries[2].claim_id)

    outline = _outline(
        ["Kirish", "Asosiy qism", "Xulosa"],
        [[cid_a], [cid_b], [cid_c]],
    )

    updated = await builder.assign_to_sections(matrix, outline)

    section_ids = [s.id for s in outline.sections]
    assert updated.entries[0].article_section_id == section_ids[0]
    assert updated.entries[1].article_section_id == section_ids[1]
    assert updated.entries[2].article_section_id == section_ids[2]


@pytest.mark.asyncio
async def test_assign_to_sections_leaves_unmatched_unassigned() -> None:
    builder = EvidenceMatrixBuilder()
    chunks = _chunks(1)
    claims = [_claim(0, "An unrelated claim with detail here.")]
    matrix = await builder.build_from_claims(uuid4(), claims, chunks)

    outline = _outline(["Section"], [["non-existent-claim-id"]])

    updated = await builder.assign_to_sections(matrix, outline)

    assert updated.entries[0].article_section_id is None


# ---------------------------------------------------------------------------
# get_ready_claims_for_section
# ---------------------------------------------------------------------------


def test_get_ready_claims_for_section_filters_by_section_and_status() -> None:
    builder = EvidenceMatrixBuilder()
    project_id = uuid4()
    section_id = uuid4()
    other_section_id = uuid4()
    entries = [
        EvidenceMatrixEntry(
            project_id=project_id,
            claim_id=uuid4(),
            source_chunk_id=uuid4(),
            article_section_id=section_id,
            citation_status=CitationStatus.READY,
            created_at=_now(),
        ),
        EvidenceMatrixEntry(
            project_id=project_id,
            claim_id=uuid4(),
            source_chunk_id=uuid4(),
            article_section_id=section_id,
            citation_status=CitationStatus.VERIFIED,
            created_at=_now(),
        ),
        EvidenceMatrixEntry(
            project_id=project_id,
            claim_id=uuid4(),
            source_chunk_id=uuid4(),
            article_section_id=section_id,
            citation_status=CitationStatus.NEEDS_USER_INPUT,
            created_at=_now(),
        ),
        EvidenceMatrixEntry(
            project_id=project_id,
            claim_id=uuid4(),
            source_chunk_id=uuid4(),
            article_section_id=other_section_id,
            citation_status=CitationStatus.READY,
            created_at=_now(),
        ),
    ]
    matrix = EvidenceMatrix(project_id=project_id, entries=entries)

    ready = builder.get_ready_claims_for_section(matrix, section_id)

    assert len(ready) == 2
    assert all(e.article_section_id == section_id for e in ready)
    assert all(e.citation_status in (CitationStatus.READY, CitationStatus.VERIFIED) for e in ready)


def test_get_ready_excludes_unready_entries() -> None:
    builder = EvidenceMatrixBuilder()
    project_id = uuid4()
    section_id = uuid4()
    entries = [
        EvidenceMatrixEntry(
            project_id=project_id,
            claim_id=uuid4(),
            source_chunk_id=uuid4(),
            article_section_id=section_id,
            citation_status=CitationStatus.NEEDS_USER_INPUT,
            created_at=_now(),
        ),
        EvidenceMatrixEntry(
            project_id=project_id,
            claim_id=uuid4(),
            source_chunk_id=uuid4(),
            article_section_id=section_id,
            citation_status=CitationStatus.UNSUPPORTED,
            created_at=_now(),
        ),
    ]
    matrix = EvidenceMatrix(project_id=project_id, entries=entries)

    assert builder.get_ready_claims_for_section(matrix, section_id) == []


# ---------------------------------------------------------------------------
# get_ungrounded_claims
# ---------------------------------------------------------------------------


def test_get_ungrounded_claims_returns_only_needs_input() -> None:
    builder = EvidenceMatrixBuilder()
    project_id = uuid4()
    entries = [
        EvidenceMatrixEntry(
            project_id=project_id,
            claim_id=uuid4(),
            source_chunk_id=uuid4(),
            citation_status=CitationStatus.READY,
            created_at=_now(),
        ),
        EvidenceMatrixEntry(
            project_id=project_id,
            claim_id=uuid4(),
            source_chunk_id=uuid4(),
            citation_status=CitationStatus.NEEDS_USER_INPUT,
            created_at=_now(),
        ),
        EvidenceMatrixEntry(
            project_id=project_id,
            claim_id=uuid4(),
            source_chunk_id=uuid4(),
            citation_status=CitationStatus.UNSUPPORTED,
            created_at=_now(),
        ),
    ]
    matrix = EvidenceMatrix(project_id=project_id, entries=entries)

    ungrounded = builder.get_ungrounded_claims(matrix)

    assert len(ungrounded) == 1
    assert ungrounded[0].citation_status is CitationStatus.NEEDS_USER_INPUT


# ---------------------------------------------------------------------------
# get_matrix_stats
# ---------------------------------------------------------------------------


def test_matrix_stats_counts_and_coverage() -> None:
    builder = EvidenceMatrixBuilder()
    project_id = uuid4()
    section_id = uuid4()

    def make(status: CitationStatus, with_section: bool = False) -> EvidenceMatrixEntry:
        return EvidenceMatrixEntry(
            project_id=project_id,
            claim_id=uuid4(),
            source_chunk_id=uuid4(),
            article_section_id=section_id if with_section else None,
            citation_status=status,
            created_at=_now(),
        )

    entries = [
        make(CitationStatus.READY, with_section=True),
        make(CitationStatus.READY, with_section=True),
        make(CitationStatus.READY, with_section=True),
        make(CitationStatus.READY, with_section=True),
        make(CitationStatus.NEEDS_USER_INPUT),
        make(CitationStatus.NEEDS_USER_INPUT),
        make(CitationStatus.NEEDS_USER_INPUT),
        make(CitationStatus.UNSUPPORTED),
        make(CitationStatus.UNSUPPORTED),
        make(CitationStatus.VERIFIED, with_section=True),
    ]
    matrix = EvidenceMatrix(project_id=project_id, entries=entries)

    stats = builder.get_matrix_stats(matrix)

    assert stats.total_claims == 10
    assert stats.ready_claims == 4
    assert stats.needs_input_claims == 3
    assert stats.unsupported_claims == 2
    assert stats.verified_claims == 1
    assert stats.coverage_percentage == pytest.approx(50.0)
    assert stats.sections_with_claims == 1
    assert stats.sections_without_claims == 0


def test_matrix_stats_empty_matrix_zero_coverage() -> None:
    builder = EvidenceMatrixBuilder()
    matrix = EvidenceMatrix(project_id=uuid4(), entries=[])

    stats = builder.get_matrix_stats(matrix)

    assert stats.total_claims == 0
    assert stats.coverage_percentage == 0.0


# ---------------------------------------------------------------------------
# validate_matrix_completeness
# ---------------------------------------------------------------------------


def _entry(
    project_id: UUID,
    section_id: UUID | None,
    status: CitationStatus,
) -> EvidenceMatrixEntry:
    return EvidenceMatrixEntry(
        project_id=project_id,
        claim_id=uuid4(),
        source_chunk_id=uuid4(),
        article_section_id=section_id,
        citation_status=status,
        created_at=_now(),
    )


def test_validate_completeness_all_sections_covered() -> None:
    builder = EvidenceMatrixBuilder()
    project_id = uuid4()
    outline = _outline(["S1", "S2", "S3"], [[], [], []])
    s1, s2, s3 = (s.id for s in outline.sections)

    entries = [
        _entry(project_id, s1, CitationStatus.READY),
        _entry(project_id, s1, CitationStatus.READY),
        _entry(project_id, s2, CitationStatus.VERIFIED),
        _entry(project_id, s2, CitationStatus.READY),
        _entry(project_id, s3, CitationStatus.READY),
        _entry(project_id, s3, CitationStatus.VERIFIED),
    ]
    matrix = EvidenceMatrix(project_id=project_id, entries=entries)

    result = builder.validate_matrix_completeness(matrix, outline)

    assert result.is_complete is True
    assert result.sections_missing == []
    assert result.sections_weak == []
    assert result.total_ready == 6
    assert result.minimum_needed == 3
    assert set(result.sections_ready) == {str(s1), str(s2), str(s3)}


def test_validate_completeness_missing_section() -> None:
    builder = EvidenceMatrixBuilder()
    project_id = uuid4()
    outline = _outline(["S1", "S2"], [[], []])
    s1, s2 = (s.id for s in outline.sections)

    entries = [
        _entry(project_id, s1, CitationStatus.READY),
        _entry(project_id, s1, CitationStatus.READY),
        _entry(project_id, s2, CitationStatus.NEEDS_USER_INPUT),
    ]
    matrix = EvidenceMatrix(project_id=project_id, entries=entries)

    result = builder.validate_matrix_completeness(matrix, outline)

    assert result.is_complete is False
    assert str(s2) in result.sections_missing
    assert str(s1) not in result.sections_missing


def test_validate_completeness_weak_section_warns() -> None:
    builder = EvidenceMatrixBuilder()
    project_id = uuid4()
    outline = _outline(["S1", "S2"], [[], []])
    s1, s2 = (s.id for s in outline.sections)

    entries = [
        _entry(project_id, s1, CitationStatus.READY),
        _entry(project_id, s2, CitationStatus.READY),
        _entry(project_id, s2, CitationStatus.READY),
    ]
    matrix = EvidenceMatrix(project_id=project_id, entries=entries)

    result = builder.validate_matrix_completeness(matrix, outline)

    assert str(s1) in result.sections_weak
    assert str(s2) not in result.sections_weak
    assert any("S1" in w or str(s1) in w for w in result.warnings)


# ---------------------------------------------------------------------------
# Model round-trips
# ---------------------------------------------------------------------------


def test_evidence_matrix_model_roundtrip() -> None:
    project_id = uuid4()
    entries = [
        EvidenceMatrixEntry(
            project_id=project_id,
            claim_id=uuid4(),
            source_chunk_id=uuid4(),
            citation_status=CitationStatus.READY,
            created_at=_now(),
        ),
        EvidenceMatrixEntry(
            project_id=project_id,
            claim_id=uuid4(),
            source_chunk_id=uuid4(),
            citation_status=CitationStatus.NEEDS_USER_INPUT,
            created_at=_now(),
        ),
    ]
    matrix = EvidenceMatrix(project_id=project_id, entries=entries)

    dumped = matrix.model_dump()
    restored = EvidenceMatrix.model_validate(dumped)

    assert restored == matrix


def test_matrix_stats_model_validation() -> None:
    stats = EvidenceMatrixStats(
        total_claims=10,
        ready_claims=4,
        needs_input_claims=3,
        unsupported_claims=2,
        verified_claims=1,
        sections_with_claims=2,
        sections_without_claims=1,
        coverage_percentage=50.0,
    )

    assert stats.coverage_percentage == 50.0
    assert stats.total_claims == 10


def test_validation_result_model_fields() -> None:
    result = MatrixValidationResult(
        is_complete=False,
        sections_ready=["s1"],
        sections_missing=["s2"],
        sections_weak=["s3"],
        total_ready=3,
        minimum_needed=3,
        warnings=["section s3 is fragile"],
    )

    assert result.is_complete is False
    assert result.sections_missing == ["s2"]
    assert "fragile" in result.warnings[0]


# Suppress unused-import false positive for ResearchQuestionType which fixtures
# may exercise in future iterations.
_ = ResearchQuestionType
