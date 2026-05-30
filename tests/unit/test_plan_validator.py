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
from typing import Any

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
    PersonItem,
    PlannedFigure,
    PlannedSection,
    SlideContent,
    SlideSpec,
    ThesisVerdict,
    TimelineNode,
)
from packages.core.models.source import SourceClaimCreate
from packages.presentation.plan_validator import (
    critique_deck_adversarially,
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
# Deck-vs-plan checks (Phase 2)
# ---------------------------------------------------------------------------


def _deck_slide(
    slide_type: SlideType,
    *,
    section_name: str | None = None,
    people: list[str] | None = None,
    timeline_portraits: list[str] | None = None,
    title: str = "Slide",
) -> SlideSpec:
    """Build a SlideSpec with a resolved section_name and optional people.

    Mirrors what the editorial pass produces after it resolves each slide's
    ``section_index`` to the plan's canonical ``section_name``.
    """

    content_kwargs: dict[str, Any] = {"title": title}
    if people is not None:
        content_kwargs["people"] = [PersonItem(name=name) for name in people]
    if timeline_portraits is not None:
        content_kwargs["timeline_nodes"] = [
            TimelineNode(date="1700s", label=f"{name} and the period", portrait_prompt=name)
            for name in timeline_portraits
        ]
    return SlideSpec(
        slide_index=0,
        slide_type=slide_type,
        content=SlideContent(**content_kwargs),
        section_name=section_name,
    )


def _good_deck() -> list[SlideSpec]:
    """A deck that fills :func:`_good_plan` — every section covered, every
    planned figure portrayed, no figure outside the roster."""

    return [
        _deck_slide(SlideType.TITLE_HERO, section_name="Salon culture", title="The Enlightenment"),
        _deck_slide(SlideType.GALLERY_PEOPLE, section_name="Salon culture", people=["Voltaire"]),
        _deck_slide(
            SlideType.GALLERY_PEOPLE,
            section_name="Constitutional ideas",
            people=["Montesquieu", "Rousseau"],
        ),
        _deck_slide(
            SlideType.TIMELINE,
            section_name="Music of the period",
            timeline_portraits=["Bach", "Mozart"],
        ),
        _deck_slide(SlideType.SUMMARY_TAKEAWAY, section_name="Legacy"),
    ]


def test_deck_matching_plan_passes() -> None:
    result = validate_deck_against_plan(_good_deck(), _good_plan())
    assert result.passed, _failure_ids(result.findings)
    assert result.findings == []


def test_deck_missing_section_fails_d_s1() -> None:
    """A planned section that no slide covers → coverage FAIL D-S1."""

    deck = [s for s in _good_deck() if s.section_name != "Legacy"]
    result = validate_deck_against_plan(deck, _good_plan())
    assert not result.passed
    assert "D-S1" in _failure_ids(result.findings)
    d_s1 = next(f for f in result.failures if f.check_id == "D-S1")
    assert "Legacy" in (d_s1.message or "")


def test_deck_section_missing_planned_figure_fails_d_f1() -> None:
    """The Music section planned Bach+Mozart but its slide carries neither
    → figure-adherence FAIL D-F1 (the deck-side substitution gate)."""

    deck = _good_deck()
    deck[3] = _deck_slide(
        SlideType.TIMELINE, section_name="Music of the period", timeline_portraits=[]
    )
    result = validate_deck_against_plan(deck, _good_plan())
    assert not result.passed
    d_f1 = [f for f in result.failures if f.check_id == "D-F1"]
    assert len(d_f1) == 2  # one each for Bach and Mozart
    assert any("Bach" in (f.message or "") for f in d_f1)
    assert any("Mozart" in (f.message or "") for f in d_f1)


def test_deck_invented_figure_fails_d_x1() -> None:
    """A gallery slide portrays Beethoven, who is not in the roster
    → invented-figure FAIL D-X1 (the deck-side Beethoven gate)."""

    deck = _good_deck()
    deck[3] = _deck_slide(
        SlideType.GALLERY_PEOPLE, section_name="Music of the period", people=["Beethoven"]
    )
    result = validate_deck_against_plan(deck, _good_plan())
    assert not result.passed
    d_x1 = [f for f in result.failures if f.check_id == "D-X1"]
    assert any("Beethoven" in (f.message or "") for f in d_x1)
    # D-F1 also fires (Bach/Mozart absent) — both gates catch the substitution.
    assert "D-F1" in _failure_ids(result.findings)


def test_team_credits_authors_not_flagged_d_x1() -> None:
    """TEAM_CREDITS people are the deck's own authors, never source figures.
    They must NOT trip the invented-figure gate — the scoping fix."""

    deck = [
        *_good_deck(),
        _deck_slide(
            SlideType.TEAM_CREDITS,
            section_name="Legacy",
            people=["Ada Lovelace", "A Student Author"],
        ),
    ]
    result = validate_deck_against_plan(deck, _good_plan())
    assert result.passed, _failure_ids(result.findings)
    assert "D-X1" not in _check_ids(result.findings)
    # team_credits renders content.people legitimately, so it is exempt from the
    # misplaced-people structural gate too — neither roster nor placement fires.
    assert "D-X2" not in _check_ids(result.findings)


def test_non_rostered_person_on_keywords_slide_fails_d_x1() -> None:
    """The sCO2 run-2 leak shape: a non-rostered person attached to a
    typographic_keywords slide (NOT gallery/timeline) → D-X1 fires.

    D-X1 was scoped to gallery/timeline and missed exactly this — the executor
    put 'Ahn, Y. et al.' on a typographic_keywords slide and the deck-vs-plan
    gate waved it through. Widened to all-but-TEAM_CREDITS, D-X1 now catches a
    non-rostered person on ANY slide type. Driven against the validator directly:
    in the live path the editorial strip removes it before this gate runs, so
    this pins the gate's standalone behaviour, not the live pipeline."""

    deck = [
        *_good_deck(),
        _deck_slide(
            SlideType.TYPOGRAPHIC_KEYWORDS, section_name="Legacy", people=["Ahn, Y. et al."]
        ),
    ]
    result = validate_deck_against_plan(deck, _good_plan())
    assert not result.passed
    d_x1 = [f for f in result.failures if f.check_id == "D-X1"]
    assert any("Ahn" in (f.message or "") for f in d_x1)


def test_rostered_person_on_wrong_slide_type_fails_d_x2_not_d_x1() -> None:
    """A ROSTERED figure (Voltaire) on a typographic_keywords slide is malformed
    even though the roster check passes: D-X2 fires, D-X1 does NOT.

    This is the case widened-D-X1 alone misses — Voltaire IS in the roster, so
    the roster gate waves the slide through — and is exactly why D-X2 (the
    roster-independent structural placement check) earns its place."""

    deck = [
        *_good_deck(),
        _deck_slide(SlideType.TYPOGRAPHIC_KEYWORDS, section_name="Legacy", people=["Voltaire"]),
    ]
    result = validate_deck_against_plan(deck, _good_plan())
    assert not result.passed
    assert "D-X2" in _failure_ids(result.findings)
    # Voltaire is rostered, so the roster gate must NOT flag THIS slide as invented.
    appended_index = len(deck) - 1
    d_x1_here = [
        f for f in result.failures if f.check_id == "D-X1" and f.slide_index == appended_index
    ]
    assert d_x1_here == []


def test_deck_invented_section_warns_not_fails_d_a1() -> None:
    """A slide tagged with a section the plan never defined → WARN D-A1,
    not a FAIL (it does not block export)."""

    deck = [*_good_deck(), _deck_slide(SlideType.CONTENT_SPLIT, section_name="Bonus aside")]
    result = validate_deck_against_plan(deck, _good_plan())
    assert result.passed, _failure_ids(result.findings)
    assert "D-A1" in _check_ids(result.warnings)


def test_empty_roster_people_slide_fails_d_x1() -> None:
    """The sCO2-shaped guarantee: a plan that names NO figures, yet a gallery
    slide sprouts a person → D-X1. No fabricated people for a source that
    named nobody; there is no minimum-people quota to fill."""

    plan = _good_plan().model_copy(
        update={
            "figures": [],
            "sections": [s.model_copy(update={"figure_names": []}) for s in _good_plan().sections],
        }
    )
    deck = [
        _deck_slide(SlideType.TITLE_HERO, section_name="Salon culture", title="t"),
        _deck_slide(
            SlideType.GALLERY_PEOPLE, section_name="Constitutional ideas", people=["Newton"]
        ),
        _deck_slide(SlideType.CONTENT_SPLIT, section_name="Music of the period"),
        _deck_slide(SlideType.SUMMARY_TAKEAWAY, section_name="Legacy"),
    ]
    result = validate_deck_against_plan(deck, plan)
    assert not result.passed
    d_x1 = [f for f in result.failures if f.check_id == "D-X1"]
    assert any("Newton" in (f.message or "") for f in d_x1)


def test_name_match_tolerates_year_suffix() -> None:
    """The planner rosters "Voltaire"; the executor renders "Voltaire
    (1694-1778)". Normalised containment must treat them as the same person,
    so D-F1 is satisfied and D-X1 does not fire."""

    deck = _good_deck()
    deck[1] = _deck_slide(
        SlideType.GALLERY_PEOPLE, section_name="Salon culture", people=["Voltaire (1694-1778)"]
    )
    result = validate_deck_against_plan(deck, _good_plan())
    assert result.passed, _failure_ids(result.findings)


def test_critique_deck_adversarially_is_noop_not_raising() -> None:
    """The Phase-3 seam must not raise (it shares a module with the live
    path) — it returns an empty, passing result until Phase 3 implements it."""

    result = critique_deck_adversarially(_good_deck(), _good_plan())
    assert result.passed
    assert result.findings == []


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
