"""Behaviour tests for :class:`SuggestionIntegrator`.

The integrator transforms approved suggestions into evidence-matrix
entries. Tests pin per-provider claim-type inference, status promotion,
section linkage, batch behaviour with partial failures, and matrix
preservation. No external services are involved, so no mocks.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from packages.core.enums import CitationStatus, ClaimStrength, ClaimType
from packages.core.models.evidence import EvidenceMatrix, EvidenceMatrixEntry
from packages.core.models.suggestion import (
    ApprovedSuggestion,
    BatchIntegrationResult,
    IntegrationResult,
    SectionNeed,
    SectionNeedType,
    Suggestion,
    SuggestionReport,
    SuggestionSource,
)
from packages.suggestions.integrator import SuggestionIntegrator


def _suggestion(
    title: str = "Findings on lipid metabolism",
    description: str = "Patients receiving the new therapy showed a 40% reduction in mortality.",
    provider: SuggestionSource = SuggestionSource.PUBMED,
    relevance: float = 0.85,
    authors: list[str] | None = None,
    year: int | None = 2024,
    doi: str | None = "10.1234/abcd",
) -> Suggestion:
    return Suggestion(
        title=title,
        description=description,
        source_provider=provider,
        relevance_score=relevance,
        authors=authors if authors is not None else ["Karimov A", "Petrov B"],
        year=year,
        doi=doi,
    )


def _approve(
    suggestion: Suggestion,
    section_id: str | None = None,
) -> ApprovedSuggestion:
    return ApprovedSuggestion(
        suggestion=suggestion,
        target_section_id=section_id or str(uuid4()),
    )


def _empty_matrix() -> EvidenceMatrix:
    return EvidenceMatrix(project_id=uuid4(), entries=[])


def _matrix_with_entries(count: int) -> EvidenceMatrix:
    project_id = uuid4()
    now = datetime.now(UTC)
    entries = [
        EvidenceMatrixEntry(
            project_id=project_id,
            claim_id=uuid4(),
            source_chunk_id=uuid4(),
            citation_status=CitationStatus.READY,
            created_at=now,
        )
        for _ in range(count)
    ]
    return EvidenceMatrix(project_id=project_id, entries=entries)


# ---------------------------------------------------------------------------
# Single integration
# ---------------------------------------------------------------------------


def test_integrate_creates_claim_and_chunk() -> None:
    integrator = SuggestionIntegrator()
    matrix = _empty_matrix()
    project_id = str(matrix.project_id)
    approved = _approve(_suggestion())
    result = integrator.integrate_approved(approved, matrix, project_id)

    assert result.success is True
    assert result.claim_created is not None
    assert result.chunk_created is not None
    assert result.matrix_entry_created is not None


def test_integrate_sets_status_ready() -> None:
    integrator = SuggestionIntegrator()
    matrix = _empty_matrix()
    project_id = str(matrix.project_id)
    result = integrator.integrate_approved(_approve(_suggestion()), matrix, project_id)
    assert result.matrix_entry_created is not None
    assert result.matrix_entry_created.citation_status is CitationStatus.READY


def test_integrate_sets_correct_section() -> None:
    integrator = SuggestionIntegrator()
    matrix = _empty_matrix()
    project_id = str(matrix.project_id)
    section_uuid = uuid4()
    approved = _approve(_suggestion(), section_id=str(section_uuid))
    result = integrator.integrate_approved(approved, matrix, project_id)
    assert result.matrix_entry_created is not None
    assert result.matrix_entry_created.article_section_id == section_uuid


def test_integrate_infers_pubmed_to_empirical() -> None:
    integrator = SuggestionIntegrator()
    matrix = _empty_matrix()
    project_id = str(matrix.project_id)
    sugg = _suggestion(provider=SuggestionSource.PUBMED)
    result = integrator.integrate_approved(_approve(sugg), matrix, project_id)
    assert result.claim_created is not None
    assert result.claim_created.claim_type is ClaimType.EMPIRICAL_FINDING


def test_integrate_infers_world_bank_to_statistical() -> None:
    integrator = SuggestionIntegrator()
    matrix = _empty_matrix()
    project_id = str(matrix.project_id)
    sugg = _suggestion(provider=SuggestionSource.WORLD_BANK)
    result = integrator.integrate_approved(_approve(sugg), matrix, project_id)
    assert result.claim_created is not None
    assert result.claim_created.claim_type is ClaimType.STATISTICAL_RESULT


def test_integrate_infers_academic_to_theoretical() -> None:
    integrator = SuggestionIntegrator()
    matrix = _empty_matrix()
    project_id = str(matrix.project_id)
    for prov in (
        SuggestionSource.SEMANTIC_SCHOLAR,
        SuggestionSource.OPENALEX,
        SuggestionSource.ARXIV,
    ):
        sugg = _suggestion(provider=prov)
        result = integrator.integrate_approved(_approve(sugg), matrix, project_id)
        assert result.claim_created is not None
        assert result.claim_created.claim_type is ClaimType.THEORETICAL_ARGUMENT, prov


def test_integrate_sets_strong_strength() -> None:
    integrator = SuggestionIntegrator()
    matrix = _empty_matrix()
    project_id = str(matrix.project_id)
    result = integrator.integrate_approved(_approve(_suggestion()), matrix, project_id)
    assert result.claim_created is not None
    assert result.claim_created.strength is ClaimStrength.STRONG


def test_integrate_claim_text_combines_title_and_description() -> None:
    integrator = SuggestionIntegrator()
    matrix = _empty_matrix()
    project_id = str(matrix.project_id)
    sugg = _suggestion(
        title="GDP Growth Rate",
        description="Uzbekistan GDP grew 5.6% in 2023, the highest since 2018.",
    )
    result = integrator.integrate_approved(_approve(sugg), matrix, project_id)
    assert result.claim_created is not None
    text = result.claim_created.claim_text
    assert "GDP Growth Rate" in text
    assert "5.6%" in text


def test_integrate_chunk_text_uses_description() -> None:
    integrator = SuggestionIntegrator()
    matrix = _empty_matrix()
    project_id = str(matrix.project_id)
    sugg = _suggestion(description="A specific authoritative finding from PubMed.")
    result = integrator.integrate_approved(_approve(sugg), matrix, project_id)
    assert result.chunk_created is not None
    assert result.chunk_created.text == "A specific authoritative finding from PubMed."


def test_integrate_invalid_section_id_returns_error() -> None:
    integrator = SuggestionIntegrator()
    matrix = _empty_matrix()
    project_id = str(matrix.project_id)
    approved = _approve(_suggestion(), section_id="not-a-uuid")
    result = integrator.integrate_approved(approved, matrix, project_id)
    assert result.success is False
    assert result.error is not None
    assert "section" in result.error.lower()


def test_integrate_invalid_project_id_returns_error() -> None:
    integrator = SuggestionIntegrator()
    matrix = _empty_matrix()
    result = integrator.integrate_approved(_approve(_suggestion()), matrix, "bad-project")
    assert result.success is False
    assert result.error is not None


# ---------------------------------------------------------------------------
# Batch integration
# ---------------------------------------------------------------------------


def test_integrate_batch_multiple() -> None:
    integrator = SuggestionIntegrator()
    matrix = _empty_matrix()
    project_id = str(matrix.project_id)
    section_id = str(uuid4())
    approved = [_approve(_suggestion(), section_id=section_id) for _ in range(3)]
    result = integrator.integrate_batch(approved, matrix, project_id)

    assert result.total == 3
    assert result.succeeded == 3
    assert result.failed == 0
    assert len(result.results) == 3
    assert len(result.updated_matrix.entries) == 3


def test_integrate_batch_partial_failure() -> None:
    integrator = SuggestionIntegrator()
    matrix = _empty_matrix()
    project_id = str(matrix.project_id)
    good = _approve(_suggestion(), section_id=str(uuid4()))
    bad = _approve(_suggestion(), section_id="not-a-uuid")
    another_good = _approve(_suggestion(), section_id=str(uuid4()))
    result = integrator.integrate_batch([good, bad, another_good], matrix, project_id)

    assert result.total == 3
    assert result.succeeded == 2
    assert result.failed == 1
    assert len(result.updated_matrix.entries) == 2


def test_integrate_batch_empty() -> None:
    integrator = SuggestionIntegrator()
    matrix = _matrix_with_entries(2)
    project_id = str(matrix.project_id)
    result = integrator.integrate_batch([], matrix, project_id)
    assert result.total == 0
    assert result.succeeded == 0
    assert result.failed == 0
    assert len(result.updated_matrix.entries) == 2


def test_integrate_preserves_existing_entries() -> None:
    integrator = SuggestionIntegrator()
    matrix = _matrix_with_entries(5)
    project_id = str(matrix.project_id)
    original_ids = [e.id for e in matrix.entries]
    approved = [_approve(_suggestion(), section_id=str(uuid4())) for _ in range(2)]
    result = integrator.integrate_batch(approved, matrix, project_id)

    assert len(result.updated_matrix.entries) == 7
    new_ids = [e.id for e in result.updated_matrix.entries]
    for orig in original_ids:
        assert orig in new_ids


# ---------------------------------------------------------------------------
# Model round-trips
# ---------------------------------------------------------------------------


def test_approved_suggestion_model_round_trip() -> None:
    a = _approve(_suggestion(), section_id=str(uuid4()))
    rebuilt = ApprovedSuggestion.model_validate(a.model_dump())
    assert rebuilt.target_section_id == a.target_section_id
    assert rebuilt.suggestion.title == a.suggestion.title
    assert isinstance(rebuilt.approved_at, datetime)


def test_integration_result_model_round_trip() -> None:
    res = IntegrationResult(success=True, suggestion_id=str(uuid4()))
    rebuilt = IntegrationResult.model_validate(res.model_dump())
    assert rebuilt == res


def test_batch_integration_result_model_round_trip() -> None:
    matrix = _empty_matrix()
    res = BatchIntegrationResult(
        total=0,
        succeeded=0,
        failed=0,
        results=[],
        updated_matrix=matrix,
    )
    rebuilt = BatchIntegrationResult.model_validate(res.model_dump())
    assert rebuilt.total == 0
    assert rebuilt.updated_matrix.project_id == matrix.project_id


def test_section_need_model_round_trip() -> None:
    need = SectionNeed(
        section_id=str(uuid4()),
        needs_suggestions=True,
        need_types=[SectionNeedType.THIN_EVIDENCE, SectionNeedType.WEAK_CLAIMS_ONLY],
        ready_claim_count=1,
        total_claim_count=3,
        reason="thin and weak",
    )
    rebuilt = SectionNeed.model_validate(need.model_dump())
    assert rebuilt == need


def test_suggestion_report_model_round_trip() -> None:
    from packages.core.models.suggestion import (
        AcademicDomain,
        DomainDetectionResult,
    )

    report = SuggestionReport(
        domains_detected=DomainDetectionResult(
            primary_domain=AcademicDomain.GENERAL,
            all_domains=[],
        ),
        sections_analyzed=3,
        sections_with_suggestions=1,
        sections_skipped=2,
        total_suggestions=2,
        providers_queried=["PubMed"],
        search_time_ms=10,
    )
    rebuilt = SuggestionReport.model_validate(report.model_dump())
    assert rebuilt == report


def test_integrate_uses_unique_uuids_per_call() -> None:
    integrator = SuggestionIntegrator()
    matrix = _empty_matrix()
    project_id = str(matrix.project_id)
    section_id = str(uuid4())
    a = integrator.integrate_approved(
        _approve(_suggestion(), section_id=section_id), matrix, project_id
    )
    b = integrator.integrate_approved(
        _approve(_suggestion(), section_id=section_id), matrix, project_id
    )
    assert a.matrix_entry_created is not None and b.matrix_entry_created is not None
    assert a.matrix_entry_created.id != b.matrix_entry_created.id
    assert a.matrix_entry_created.claim_id != b.matrix_entry_created.claim_id
    assert a.matrix_entry_created.source_chunk_id != b.matrix_entry_created.source_chunk_id


def test_integrate_chunk_and_claim_share_virtual_source() -> None:
    integrator = SuggestionIntegrator()
    matrix = _empty_matrix()
    project_id = str(matrix.project_id)
    result = integrator.integrate_approved(_approve(_suggestion()), matrix, project_id)
    assert result.chunk_created is not None
    assert result.claim_created is not None
    assert result.chunk_created.source_id == result.claim_created.source_chunk_id
    parsed = UUID(result.chunk_created.source_id)
    assert result.matrix_entry_created is not None
    assert result.matrix_entry_created.source_chunk_id == parsed
