"""Model-level tests for :class:`DeckPlan` and its component models.

Pins the field bounds, the round-trip contract from
``.claude/rules/core-models.md``, and the
:class:`PlanValidationResult` properties (passed / failures / warnings).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from packages.core.enums import AuditSeverity, NarrativePhase, SlideType
from packages.core.models.presentation import (
    AuditCheckResult,
    DeckPlan,
    PlannedFigure,
    PlannedSection,
    PlanValidationResult,
    ThesisVerdict,
)


def _minimal_section(
    *,
    section_name: str = "Salon culture",
    thesis: str = "Salons turned private hospitality into public political work.",
    phase: NarrativePhase = NarrativePhase.HOOK,
    figure_names: list[str] | None = None,
    planned_slide_types: list[SlideType] | None = None,
) -> PlannedSection:
    return PlannedSection(
        section_name=section_name,
        thesis=thesis,
        phase=phase,
        figure_names=figure_names or [],
        planned_slide_types=planned_slide_types or [],
    )


def _minimal_plan() -> DeckPlan:
    return DeckPlan(
        thesis="Enlightenment thinkers redistributed cultural authority across Europe.",
        audience_takeaway="Students name two debates that shaped constitutional thought.",
        sections=[
            _minimal_section(),
            _minimal_section(
                section_name="Legacy",
                thesis="The American and French revolutions translated salon arguments into documents.",
                phase=NarrativePhase.CLOSE,
            ),
        ],
        figures=[
            PlannedFigure(
                name="Voltaire",
                years="1694-1778",
                why_in_source="Source names Voltaire as the leading Enlightenment polemicist.",
            ),
        ],
        image_cohesion_note="Warm oil-paint portraits in candlelit interiors.",
    )


# ---------------------------------------------------------------------------
# Field bounds
# ---------------------------------------------------------------------------


def test_plan_requires_at_least_two_sections() -> None:
    with pytest.raises(ValidationError):
        DeckPlan(
            thesis="A specific thesis at least twenty chars long indeed.",
            audience_takeaway="At least twelve chars.",
            sections=[_minimal_section()],
            image_cohesion_note="Warm oil-paint candlelit interiors.",
        )


def test_plan_rejects_more_than_eight_sections() -> None:
    sections = [
        _minimal_section(section_name=f"Sec {i}", thesis=f"Section {i} argues thing {i} clearly.")
        for i in range(9)
    ]
    with pytest.raises(ValidationError):
        DeckPlan(
            thesis="A specific thesis at least twenty chars long indeed.",
            audience_takeaway="At least twelve chars.",
            sections=sections,
            image_cohesion_note="Warm oil-paint candlelit interiors.",
        )


def test_plan_rejects_blank_thesis() -> None:
    with pytest.raises(ValidationError):
        DeckPlan(
            thesis="too short",  # < 20 chars
            audience_takeaway="At least twelve chars.",
            sections=[_minimal_section(), _minimal_section(section_name="Other")],
            image_cohesion_note="Warm oil-paint candlelit interiors.",
        )


def test_planned_section_thesis_requires_min_length() -> None:
    with pytest.raises(ValidationError):
        PlannedSection(
            section_name="Salon culture",
            thesis="too short",  # < 12 chars
            phase=NarrativePhase.HOOK,
        )


def test_planned_figure_why_in_source_required() -> None:
    with pytest.raises(ValidationError):
        PlannedFigure(name="Voltaire", years="1694-1778", why_in_source="")


def test_plan_rejects_overlong_image_cohesion_note() -> None:
    with pytest.raises(ValidationError):
        DeckPlan(
            thesis="A specific thesis at least twenty chars long indeed.",
            audience_takeaway="At least twelve chars.",
            sections=[_minimal_section(), _minimal_section(section_name="Other")],
            image_cohesion_note="x" * 501,
        )


def test_planned_section_planned_slide_types_uses_real_enum() -> None:
    """Per core-models.md: every finite-value field uses a StrEnum."""

    section = PlannedSection(
        section_name="Music of the period",
        thesis="Bach and Mozart anchored Enlightenment musical taste across decades.",
        phase=NarrativePhase.EVIDENCE,
        planned_slide_types=[SlideType.GALLERY_PEOPLE, SlideType.TIMELINE],
    )
    assert section.planned_slide_types == [SlideType.GALLERY_PEOPLE, SlideType.TIMELINE]


def test_plan_extra_field_forbidden() -> None:
    with pytest.raises(ValidationError):
        DeckPlan(
            thesis="A specific thesis at least twenty chars long indeed.",
            audience_takeaway="At least twelve chars.",
            sections=[_minimal_section(), _minimal_section(section_name="Other")],
            image_cohesion_note="Warm oil-paint candlelit interiors.",
            unexpected_field="x",  # type: ignore[call-arg]
        )


# ---------------------------------------------------------------------------
# Round-trip serialisation (core-models.md hard rule)
# ---------------------------------------------------------------------------


def test_plan_round_trips_through_dict() -> None:
    plan = _minimal_plan()
    reconstructed = DeckPlan.model_validate(plan.model_dump())
    assert reconstructed == plan


def test_plan_round_trips_through_json_mode() -> None:
    plan = _minimal_plan()
    reconstructed = DeckPlan.model_validate(plan.model_dump(mode="json"))
    assert reconstructed == plan


# ---------------------------------------------------------------------------
# PlanValidationResult properties
# ---------------------------------------------------------------------------


def _finding(*, passed: bool, severity: AuditSeverity, check_id: str = "T-1") -> AuditCheckResult:
    return AuditCheckResult(
        check_id=check_id,
        check_name="test.synthetic",
        passed=passed,
        severity=severity,
        message="synthetic finding",
    )


def test_plan_validation_result_passed_true_when_no_failures() -> None:
    result = PlanValidationResult(
        findings=[
            _finding(passed=False, severity=AuditSeverity.WARN, check_id="T-WARN"),
            _finding(passed=True, severity=AuditSeverity.WARN, check_id="T-OK"),
        ]
    )
    assert result.passed
    assert result.failures == []
    assert len(result.warnings) == 2


def test_plan_validation_result_passed_false_on_any_fail() -> None:
    fail_finding = _finding(passed=False, severity=AuditSeverity.FAIL, check_id="T-FAIL")
    warn_finding = _finding(passed=False, severity=AuditSeverity.WARN, check_id="T-WARN")
    result = PlanValidationResult(findings=[fail_finding, warn_finding])
    assert not result.passed
    assert result.failures == [fail_finding]
    assert result.warnings == [warn_finding]


def test_plan_validation_result_empty_passes() -> None:
    result = PlanValidationResult()
    assert result.passed
    assert result.failures == []
    assert result.warnings == []


# ---------------------------------------------------------------------------
# ThesisVerdict (Phase 1.5)
# ---------------------------------------------------------------------------


def test_thesis_verdict_round_trips_through_dict() -> None:
    verdict = ThesisVerdict(
        is_thesis=True,
        reason="The thesis predicates a redistribution of authority.",
    )
    reconstructed = ThesisVerdict.model_validate(verdict.model_dump())
    assert reconstructed == verdict


def test_thesis_verdict_rejects_empty_reason() -> None:
    with pytest.raises(ValidationError):
        ThesisVerdict(is_thesis=True, reason="")


def test_thesis_verdict_rejects_overlong_reason() -> None:
    with pytest.raises(ValidationError):
        ThesisVerdict(is_thesis=False, reason="x" * 201)


def test_thesis_verdict_extra_field_forbidden() -> None:
    with pytest.raises(ValidationError):
        ThesisVerdict(
            is_thesis=True,
            reason="ok",
            unexpected="x",  # type: ignore[call-arg]
        )
