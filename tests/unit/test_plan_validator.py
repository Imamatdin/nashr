"""Behaviour tests for the Phase-1.5 plan validator.

The sync validator is pure-function; the async validator delegates the
predication judgement to a Gemini Flash classifier. These tests
construct hand-built :class:`DeckPlan` instances and a stub classifier
(no real Gemini call — testing.md forbids real LLMs in pytest) and
assert on the *specific* finding's check_id rather than just on counts,
pinning the gate to behaviour rather than implementation.

Phase 1.5 removed two checks that Phase 1 shipped:

* the 4-token thesis floor (biased against agglutinative languages),
* the 3-new-tokens-vs-label delta (same bias),
* the substring half of P-A1 (label-inside-thesis false-rejects any
  real thesis that names its subject — almost every Karakalpak thesis).

Those tests are deleted. The equality-only P-A1 backstop, source
fidelity, coverage warnings, and figure-claim grounding remain and are
exercised here. The new async path is exercised with a stub classifier.
"""

from __future__ import annotations

from collections.abc import Iterable

import pytest

from packages.core.enums import (
    AuditSeverity,
    ClaimStrength,
    ClaimType,
    Language,
    NarrativePhase,
    SlideType,
)
from packages.core.models.presentation import (
    AuditCheckResult,
    DeckPlan,
    PlannedFigure,
    PlannedSection,
    ThesisVerdict,
)
from packages.core.models.source import SourceClaimCreate
from packages.presentation.plan_validator import (
    validate_deck_against_plan,
    validate_plan,
    validate_plan_async,
)
from packages.presentation.thesis_classifier import ThesisClassifier

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _good_plan() -> DeckPlan:
    """A structurally sound, source-fidelity-compliant DeckPlan."""

    return DeckPlan(
        thesis=(
            "Eighteenth-century Enlightenment thinkers redistributed cultural "
            "authority from clergy and crown to readers and editors."
        ),
        audience_takeaway=(
            "Students leave able to name two Enlightenment debates that "
            "shaped modern constitutional thought."
        ),
        sections=[
            PlannedSection(
                section_name="Salon culture",
                thesis=(
                    "Parisian salons turned private hospitality into a public "
                    "venue for political argument."
                ),
                phase=NarrativePhase.HOOK,
                figure_names=["Voltaire"],
                planned_slide_types=[SlideType.CONTENT_SPLIT],
            ),
            PlannedSection(
                section_name="Constitutional ideas",
                thesis=(
                    "Montesquieu's separation of powers reshaped how thinkers "
                    "imagined a legitimate state."
                ),
                phase=NarrativePhase.CORE,
                figure_names=["Montesquieu", "Rousseau"],
                planned_slide_types=[SlideType.GALLERY_PEOPLE],
            ),
            PlannedSection(
                section_name="Music of the period",
                thesis=(
                    "Bach and Mozart anchored Enlightenment musical taste from "
                    "Baroque rigour to Classical clarity."
                ),
                phase=NarrativePhase.EVIDENCE,
                figure_names=["Bach", "Mozart"],
                planned_slide_types=[SlideType.TIMELINE],
            ),
            PlannedSection(
                section_name="Legacy",
                thesis=(
                    "The American and French revolutions translated salon "
                    "arguments into founding documents."
                ),
                phase=NarrativePhase.CLOSE,
                figure_names=[],
                planned_slide_types=[SlideType.SUMMARY_TAKEAWAY],
            ),
        ],
        figures=[
            PlannedFigure(
                name="Voltaire",
                years="1694-1778",
                why_in_source="Source names Voltaire as the leading Enlightenment polemicist.",
            ),
            PlannedFigure(
                name="Montesquieu",
                years="1689-1755",
                why_in_source="Source cites Esprit des lois as the separation-of-powers text.",
            ),
            PlannedFigure(
                name="Rousseau",
                years="1712-1778",
                why_in_source="Source names Du contrat social as the social-contract treatise.",
            ),
            PlannedFigure(
                name="Bach",
                years="1685-1750",
                why_in_source="Source names Bach as the deepest Baroque musical figure.",
            ),
            PlannedFigure(
                name="Mozart",
                years="1756-1791",
                why_in_source="Source names Mozart as the symbol of classical music.",
            ),
        ],
        image_cohesion_note=(
            "Warm oil-paint portraits and copper-engraving line art in an "
            "eighteenth-century European candlelit-interior palette."
        ),
    )


def _check_ids(findings: Iterable[AuditCheckResult]) -> list[str]:
    return [f.check_id for f in findings]


def _failure_ids(findings: Iterable[AuditCheckResult]) -> list[str]:
    return [f.check_id for f in findings if f.severity is AuditSeverity.FAIL]


class _StubClassifier(ThesisClassifier):
    """Replays scripted ThesisVerdict lists without an LLM call.

    The async tests use this so we can assert: (a) the classifier is
    called exactly once per ``validate_plan_async`` invocation, (b) the
    verdicts get translated into findings in section order, and (c) a
    classifier that raises propagates through ``validate_plan_async``.
    """

    def __init__(
        self,
        verdicts_per_call: list[list[ThesisVerdict]],
        raises: Exception | None = None,
    ) -> None:
        super().__init__(gemini=None)
        self._scripts = list(verdicts_per_call)
        self._raises = raises
        self.call_count = 0
        self.last_items: list[tuple[str, str]] | None = None
        self.last_language: Language | None = None

    async def classify(  # type: ignore[override]
        self,
        items: list[tuple[str, str]],
        language: Language,
    ) -> list[ThesisVerdict]:
        self.call_count += 1
        self.last_items = list(items)
        self.last_language = language
        if self._raises is not None:
            raise self._raises
        if not self._scripts:
            raise RuntimeError("stub classifier exhausted")
        return self._scripts.pop(0)


def _all_true_verdicts(n: int, reason: str = "Real predication.") -> list[ThesisVerdict]:
    return [ThesisVerdict(is_thesis=True, reason=reason) for _ in range(n)]


# ---------------------------------------------------------------------------
# Good-plan baseline (sync)
# ---------------------------------------------------------------------------


def test_good_plan_passes_with_no_failures_sync() -> None:
    plan = _good_plan()
    result = validate_plan(plan)
    assert result.passed, f"good plan unexpectedly failed: {_failure_ids(result.findings)}"
    assert result.failures == []


def test_good_plan_has_no_coverage_warnings_sync() -> None:
    plan = _good_plan()
    result = validate_plan(plan)
    assert result.warnings == []


# ---------------------------------------------------------------------------
# SOURCE-FIDELITY checks
# ---------------------------------------------------------------------------


def test_section_naming_out_of_roster_figure_fails_with_specific_id() -> None:
    """The canonical Beethoven test: a section names a figure the roster
    does not contain → fidelity FAIL P-F1."""

    plan = _good_plan()
    bad_section = PlannedSection(
        section_name="Music of the period",
        thesis=(
            "Beethoven anchored Enlightenment musical taste from Baroque "
            "rigour to Classical clarity."
        ),
        phase=NarrativePhase.EVIDENCE,
        figure_names=["Beethoven"],
        planned_slide_types=[SlideType.GALLERY_PEOPLE],
    )
    plan = plan.model_copy(update={"sections": [*plan.sections[:2], bad_section, plan.sections[3]]})
    result = validate_plan(plan)
    assert not result.passed
    assert "P-F1" in _failure_ids(result.findings)
    fidelity_failures = [f for f in result.failures if f.check_id == "P-F1"]
    assert any("Beethoven" in (f.message or "") for f in fidelity_failures)


def test_figure_with_empty_why_in_source_fails() -> None:
    """A figure with whitespace-only why_in_source → fidelity FAIL P-F2."""

    plan = _good_plan()
    figures = [
        plan.figures[0].model_copy(update={"why_in_source": "   "}),
        *plan.figures[1:],
    ]
    plan = plan.model_copy(update={"figures": figures})
    result = validate_plan(plan)
    assert not result.passed
    assert "P-F2" in _failure_ids(result.findings)


# ---------------------------------------------------------------------------
# ARC EQUALITY (the sync structural backstop)
# ---------------------------------------------------------------------------


def test_thesis_equal_to_section_name_fails_under_equality_check() -> None:
    """thesis ≡ section_name after normalisation → arc FAIL P-A1.

    Constructed so the normalised forms are identical: the trailing
    period strips during normalisation, so "Constitutional ideas."
    normalises to "constitutional ideas" — the same as the section name.
    """

    plan = _good_plan()
    plan = plan.model_copy(
        update={
            "sections": [
                PlannedSection(
                    section_name="Constitutional ideas",
                    thesis="Constitutional ideas.",
                    phase=NarrativePhase.CORE,
                ),
                *plan.sections[1:],
            ]
        }
    )
    result = validate_plan(plan)
    assert not result.passed
    assert "P-A1" in _failure_ids(result.findings)


def test_label_in_thesis_does_not_fail_phase_1_5() -> None:
    """The Phase-1 substring check is GONE — a thesis that mentions its
    section_name verbatim is no longer a sync FAIL.

    This is the Karakalpak-shaped case ("Ilim" + "Ilim bilikti sındıradı"):
    section name appears inside the thesis as part of a real predication.
    The sync gate must let it through (the classifier judges the
    predication itself in the async path).
    """

    plan = _good_plan()
    plan = plan.model_copy(
        update={
            "sections": [
                PlannedSection(
                    section_name="Ilim",
                    thesis="Ilim bilikti sındıradı.",
                    phase=NarrativePhase.CORE,
                ),
                *plan.sections[1:],
            ]
        }
    )
    result = validate_plan(plan)
    # No P-A1; the equality check accepts this — section name and thesis
    # normalise differently (different token sequences).
    assert "P-A1" not in _failure_ids(result.findings)


def test_short_agglutinative_thesis_passes_phase_1_5_sync() -> None:
    """A 3-token Karakalpak thesis is no longer a sync FAIL.

    Phase 1 rejected this on the 4-token floor; Phase 1.5 has no such
    floor. The sync validator must let it through; the classifier
    handles the predication question in the async path.
    """

    plan = _good_plan()
    plan = plan.model_copy(
        update={
            "sections": [
                PlannedSection(
                    section_name="Ilim",
                    thesis="Ilim bilikti sındıradı",
                    phase=NarrativePhase.CORE,
                ),
                *plan.sections[1:],
            ]
        }
    )
    result = validate_plan(plan)
    failures = _failure_ids(result.findings)
    assert "P-A2" not in failures  # the dropped token-floor check
    assert "P-A3" not in failures  # the dropped new-tokens-vs-label check


# ---------------------------------------------------------------------------
# STRUCTURAL COVERAGE warnings (not failures)
# ---------------------------------------------------------------------------


def test_arc_missing_opener_and_closer_warns_not_fails() -> None:
    """A plan that sits entirely on CORE → coverage WARN P-C1."""

    plan = _good_plan()
    flat_sections = [
        PlannedSection(
            section_name="Ideas",
            thesis="Enlightenment writers questioned inherited religious authority openly.",
            phase=NarrativePhase.CORE,
        ),
        PlannedSection(
            section_name="Debates",
            thesis="Salons turned debate into public political work across Europe.",
            phase=NarrativePhase.CORE,
        ),
    ]
    plan = plan.model_copy(update={"sections": flat_sections})
    result = validate_plan(plan)
    assert result.passed, _check_ids(result.findings)
    assert "P-C1" in _check_ids(result.warnings)


def test_unused_figure_roster_warns_not_fails() -> None:
    """Figures present but no section references them → WARN P-C2."""

    plan = _good_plan()
    sections_without_figures = [
        section.model_copy(update={"figure_names": []}) for section in plan.sections
    ]
    plan = plan.model_copy(update={"sections": sections_without_figures})
    result = validate_plan(plan)
    assert result.passed, _check_ids(result.findings)
    assert "P-C2" in _check_ids(result.warnings)


# ---------------------------------------------------------------------------
# FIGURE-CLAIM grounding (optional, only when claims passed)
# ---------------------------------------------------------------------------


def test_claim_grounding_check_is_noop_when_claims_omitted() -> None:
    plan = _good_plan()
    plan = plan.model_copy(
        update={
            "figures": [
                plan.figures[0].model_copy(update={"source_claim_ids": ["nonexistent-id"]}),
                *plan.figures[1:],
            ]
        }
    )
    result = validate_plan(plan)
    assert "P-F3" not in _check_ids(result.findings)


def test_claim_grounding_warns_on_unknown_claim_id_when_claims_supplied() -> None:
    plan = _good_plan()
    plan = plan.model_copy(
        update={
            "figures": [
                plan.figures[0].model_copy(
                    update={"source_claim_ids": ["this-claim-does-not-exist"]}
                ),
                *plan.figures[1:],
            ]
        }
    )
    claims = [
        SourceClaimCreate(
            claim_text="A real claim with at least ten characters of text.",
            strength=ClaimStrength.MODERATE,
            claim_type=ClaimType.GENERAL_FACT,
        ),
    ]
    result = validate_plan(plan, claims=claims)
    warn_ids = [f.check_id for f in result.warnings]
    assert "P-F3" in warn_ids


# ---------------------------------------------------------------------------
# Phase-2 seam
# ---------------------------------------------------------------------------


def test_validate_deck_against_plan_raises_until_phase_2() -> None:
    plan = _good_plan()
    with pytest.raises(NotImplementedError):
        validate_deck_against_plan(object(), plan)


# ---------------------------------------------------------------------------
# ASYNC PATH (Phase 1.5)
# ---------------------------------------------------------------------------


async def test_async_validator_calls_classifier_exactly_once_per_plan() -> None:
    """One Gemini call per plan, regardless of how many sections."""

    plan = _good_plan()  # 4 sections
    stub = _StubClassifier([_all_true_verdicts(4)])
    result = await validate_plan_async(plan, classifier=stub, language=Language.EN)
    assert stub.call_count == 1
    assert result.passed
    # The stub received the right number of items in the right order.
    assert stub.last_items is not None
    assert len(stub.last_items) == 4
    assert stub.last_items[0] == (plan.sections[0].section_name, plan.sections[0].thesis)
    assert stub.last_language is Language.EN


async def test_async_validator_passes_when_all_verdicts_true() -> None:
    plan = _good_plan()
    stub = _StubClassifier([_all_true_verdicts(4)])
    result = await validate_plan_async(plan, classifier=stub, language=Language.EN)
    assert result.passed
    assert all(f.check_id != "P-A3" for f in result.findings)


async def test_async_validator_appends_p_a3_for_each_false_verdict() -> None:
    plan = _good_plan()
    verdicts = [
        ThesisVerdict(is_thesis=True, reason="Real predication."),
        ThesisVerdict(
            is_thesis=False,
            reason="Topic label restating the section name without claim.",
        ),
        ThesisVerdict(is_thesis=True, reason="Real predication."),
        ThesisVerdict(is_thesis=False, reason="Meta-statement, no thesis."),
    ]
    stub = _StubClassifier([verdicts])
    result = await validate_plan_async(plan, classifier=stub, language=Language.EN)
    a3 = [f for f in result.findings if f.check_id == "P-A3"]
    assert len(a3) == 2
    # Section-index order: first False is at index 1, second at index 3.
    assert [f.slide_index for f in a3] == [1, 3]
    # The classifier's reason verbatim flows into the finding message.
    assert "Topic label restating the section name" in (a3[0].message or "")
    assert "Meta-statement, no thesis." in (a3[1].message or "")
    # The section names land in the message too.
    assert plan.sections[1].section_name in (a3[0].message or "")


async def test_async_validator_orders_findings_sync_first_then_classifier() -> None:
    """Sync findings (e.g. P-F1) precede classifier findings (P-A3)."""

    plan = _good_plan()
    # Inject a P-F1 (roster mismatch) at section 0.
    plan = plan.model_copy(
        update={
            "sections": [
                plan.sections[0].model_copy(update={"figure_names": ["NotInRoster"]}),
                *plan.sections[1:],
            ]
        }
    )
    verdicts = [
        ThesisVerdict(is_thesis=False, reason="Label restatement."),
        ThesisVerdict(is_thesis=True, reason="OK."),
        ThesisVerdict(is_thesis=True, reason="OK."),
        ThesisVerdict(is_thesis=True, reason="OK."),
    ]
    stub = _StubClassifier([verdicts])
    result = await validate_plan_async(plan, classifier=stub, language=Language.EN)
    check_order = [f.check_id for f in result.findings]
    # Every sync finding precedes every classifier finding.
    last_sync = max(i for i, c in enumerate(check_order) if c != "P-A3")
    first_a3 = next(i for i, c in enumerate(check_order) if c == "P-A3")
    assert last_sync < first_a3


async def test_async_validator_propagates_classifier_error() -> None:
    """The validator does NOT catch and downgrade — it raises through."""

    from packages.presentation.thesis_classifier import ThesisClassifierError

    plan = _good_plan()
    stub = _StubClassifier([], raises=ThesisClassifierError("boom"))
    with pytest.raises(ThesisClassifierError):
        await validate_plan_async(plan, classifier=stub, language=Language.EN)
