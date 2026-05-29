"""Plan-adherence validator.

Gate over a :class:`DeckPlan`. Phase 1 shipped this as a pure-function
module; Phase 1.5 adds an async path that calls a multilingual LLM
classifier (:class:`packages.presentation.thesis_classifier.ThesisClassifier`)
for the predication judgement and removes the structural arc checks that
were biased against agglutinative languages. The sync path stays
callable for offline contexts (unit tests, ad-hoc tools).

Why the change: Phase 1 enforced "thesis is not a label" with two
numeric thresholds — at least 4 tokens, and at least 3 tokens not in the
section_name. Plus a substring containment check (label-in-thesis or
thesis-in-label) under P-A1. All three are tuned to English prose:

* A genuine Karakalpak / Uzbek / Turkish thesis like "Ilim bilikti
  sındıradı" ("science breaks authority") is 3 tokens, because tense,
  person, and case pack into suffixes. The 4-token floor false-rejects
  it.
* The same thesis against section_name "Ilim" fails the substring check
  too: "ilim" appears verbatim in the thesis. A real predication that
  names its subject is exactly the failure mode the structural check
  flagged.

The numeric thresholds are a hardcoded-list anti-pattern in disguise:
they impose an English-prose-shaped constraint on languages that don't
share that shape. They are the no-hardcode rule expressed as numbers
instead of strings. They go.

Checks (Phase 1.5):

1. **SOURCE-FIDELITY (FAIL)** — every name a section names in
   ``figure_names`` must appear verbatim in the deck-level
   :attr:`DeckPlan.figures` roster, and every :class:`PlannedFigure`
   must carry a non-empty ``why_in_source``. Language-neutral, retained.

2. **ARC NON-GENERICNESS — EQUALITY (FAIL, SYNC)** — the strict
   structural backstop: a section thesis that normalises to exactly the
   same string as its section name is a hard failure. Catches a
   degenerate "section_name = thesis" plan without any LLM cost. We do
   NOT keep the substring check from Phase 1 — see module docstring.

3. **ARC NON-GENERICNESS — PREDICATION (FAIL, ASYNC ONLY)** — the
   classifier's verdict. One Gemini Flash call per plan returns a
   :class:`ThesisVerdict` per section; the async path appends a P-A3
   finding for every verdict where ``is_thesis is False``, carrying the
   classifier's English-language reason.

4. **STRUCTURAL COVERAGE (WARN)** — the plan's narrative arc covers
   real phases, not a flatline; and when the plan carries figures the
   sections actually use them. Language-neutral, retained.

5. **FIGURE-CLAIM GROUNDING (WARN, OPTIONAL)** — when the caller passes
   the project's :class:`SourceClaimCreate` list, every
   ``source_claim_ids`` entry must reference a real claim. No-op when
   claims is ``None``.

Finding order is deterministic: sync findings first, then any classifier
verdicts in section-index order. Callers and tests can assert on that.

Phase 2 adds the deck-vs-plan gate :func:`validate_deck_against_plan`: a
pure-function structural check (no LLM) that the editorial pass runs over a
generated slide sequence to confirm it filled the plan — every planned
section covered (D-S1), every section's planned figures portrayed (D-F1), no
person outside the roster on a people slide (D-X1), and a WARN for any slide
tagged with an unplanned section (D-A1). :func:`critique_deck_adversarially`
is the Phase-3 seam; it is a no-op (never raises) until Phase 3 lands.
"""

from __future__ import annotations

from typing import Final

from packages.core.enums import AuditSeverity, Language, NarrativePhase, SlideType
from packages.core.models.presentation import (
    AuditCheckResult,
    DeckPlan,
    PlanValidationResult,
    SlideSpec,
    ThesisVerdict,
)
from packages.core.models.source import SourceClaimCreate
from packages.presentation.thesis_classifier import ThesisClassifier

# Check identifiers used in the AuditCheckResult.check_id field. Kept short
# so they remain useful as log tags and CLI prefixes; the rule_reference
# attribute carries the longer mnemonic in case the planner-pass invariants
# land in INVARIANTS.md later.
_CHECK_FIDELITY_ROSTER: Final[str] = "P-F1"
_CHECK_FIDELITY_WHY: Final[str] = "P-F2"
_CHECK_FIDELITY_CLAIMS: Final[str] = "P-F3"
_CHECK_ARC_EQUALITY: Final[str] = "P-A1"
_CHECK_ARC_PREDICATION: Final[str] = "P-A3"
_CHECK_COVERAGE_PHASES: Final[str] = "P-C1"
_CHECK_COVERAGE_FIGURES: Final[str] = "P-C2"

# Deck-vs-plan check identifiers (Phase 2). The plan-time checks above (P-*)
# judge the plan in isolation; these (D-*) judge a generated deck against the
# plan it was supposed to fill.
_CHECK_DECK_SECTION_COVERAGE: Final[str] = "D-S1"
_CHECK_DECK_FIGURE_ADHERENCE: Final[str] = "D-F1"
_CHECK_DECK_INVENTED_FIGURE: Final[str] = "D-X1"
_CHECK_DECK_INVENTED_SECTION: Final[str] = "D-A1"

# Slide types whose people are SOURCE figures subject to the roster gate.
# TEAM_CREDITS is excluded on purpose: its ``people`` are the deck's own
# authors/presenters, never figures the source named, so D-X1 must not flag
# them. GALLERY_PEOPLE carries names in ``content.people``; TIMELINE carries
# them in each node's ``portrait_prompt``.
_PEOPLE_BEARING_TYPES: Final[frozenset[SlideType]] = frozenset(
    {SlideType.GALLERY_PEOPLE, SlideType.TIMELINE}
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def validate_plan(
    plan: DeckPlan,
    *,
    claims: list[SourceClaimCreate] | None = None,
) -> PlanValidationResult:
    """Run every sync plan check and return the aggregated result.

    The sync path runs the structural gates that need no LLM access:
    source fidelity, equality-only arc check, structural coverage, and
    (optional) figure-claim grounding. Phase 1.5 callers that want the
    predication classifier should call :func:`validate_plan_async`
    instead; the sync result remains useful as an offline pre-check.

    ``claims`` is optional: when supplied the validator additionally
    checks that any ``PlannedFigure.source_claim_ids`` entry references
    a real extracted claim by id. When absent that check is a no-op so
    the validator stays callable from contexts (unit tests, harness
    fallback) that have no project-scoped claims at hand.
    """

    findings: list[AuditCheckResult] = []
    findings.extend(_check_source_fidelity(plan))
    findings.extend(_check_arc_equality(plan))
    findings.extend(_check_structural_coverage(plan))
    findings.extend(_check_figure_claim_grounding(plan, claims))
    return PlanValidationResult(findings=findings)


async def validate_plan_async(
    plan: DeckPlan,
    *,
    classifier: ThesisClassifier,
    language: Language,
    claims: list[SourceClaimCreate] | None = None,
) -> PlanValidationResult:
    """Run every sync check plus the multilingual predication classifier.

    The classifier is called ONCE per plan, classifying every section in
    a single Gemini call so cost and latency are O(plan), not O(section).
    If the classifier raises (:class:`ThesisClassifierError`), the
    exception propagates — Phase 2's orchestrator decides policy. The
    validator does not catch and downgrade, because the silent-pass-on-
    failure pattern is what reintroduces the bug class the validator
    exists to prevent.

    Findings are appended in a deterministic order: every sync finding
    (source fidelity, equality, coverage, grounding) precedes every
    classifier-driven finding, and classifier findings are emitted in
    ``plan.sections`` order. Callers and tests may rely on this.
    """

    sync_result = validate_plan(plan, claims=claims)
    items = [(s.section_name, s.thesis) for s in plan.sections]
    verdicts = await classifier.classify(items, language)
    classifier_findings = _findings_from_verdicts(plan, verdicts)
    return PlanValidationResult(findings=[*sync_result.findings, *classifier_findings])


def validate_deck_against_plan(slides: list[SlideSpec], plan: DeckPlan) -> PlanValidationResult:
    """Verify a generated slide sequence stays inside its :class:`DeckPlan`.

    Pure functions, no LLM — the LLM judgement was the plan-time thesis check
    (:func:`validate_plan_async`); the deck-vs-plan gate is structural. Called
    by the live editorial path on the post-processed CONTENT slides, BEFORE the
    interactive pass and assembly: interactive slides carry no ``section_name``
    and would pollute the coverage and invented-figure checks.

    Section membership is the resolved canonical ``SlideSpec.section_name``:
    the executor tags each slide with a ``section_index`` and the editorial
    pass resolves it to ``plan.sections[i].section_name`` at materialise time,
    so the join here is by section name. Comparison is normalised (see
    :func:`_normalize`) so a trailing period or case never breaks a match.

    Checks (FAIL blocks export; WARN is informational):

    * **D-S1 (section coverage, FAIL)** — every :attr:`PlannedSection.section_name`
      has at least one slide. A planned section with no slide is the executor
      dropping part of the argument.
    * **D-F1 (figure adherence, FAIL)** — for every section that planned
      ``figure_names``, that section's slides collectively portray those
      people (by :class:`PersonItem` name, or by a TIMELINE node's
      ``portrait_prompt``). The deck-side enforcement of the substitution gate.
    * **D-X1 (no invented figures, FAIL)** — no GALLERY_PEOPLE / TIMELINE slide
      portrays a person absent from the :attr:`DeckPlan.figures` roster.
      TEAM_CREDITS is out of scope (its people are the deck's authors). This is
      the deck-side Beethoven gate and the no-fabricated-people guarantee for
      sources that name nobody.
    * **D-A1 (invented section, WARN)** — a slide tagged with a ``section_name``
      that matches no planned section. The executor added structure beyond the
      plan; informational, never blocks export.

    Name matching (D-F1 / D-X1) is normalised substring containment in either
    direction (:func:`_name_matches`) — robust to "Volter" vs
    "Volter (1694-1778)" without an alias table or any hardcoded names.
    """

    findings: list[AuditCheckResult] = []
    findings.extend(_check_deck_section_coverage(slides, plan))
    findings.extend(_check_deck_figure_adherence(slides, plan))
    findings.extend(_check_deck_invented_figures(slides, plan))
    findings.extend(_check_deck_invented_sections(slides, plan))
    return PlanValidationResult(findings=findings)


def critique_deck_adversarially(slides: list[SlideSpec], plan: DeckPlan) -> PlanValidationResult:
    """Phase-3 seam — adversarial deck critic. Not yet implemented.

    Phase 3 will add an LLM critic that reads each slide against the plan's
    section theses and ``why_in_source`` anchors and flags claims the source
    does not support. Until then this is a NO-OP that returns an empty
    (passing) result — deliberately NOT a ``NotImplementedError``, because
    unlike the Phase-1 stub this function shares a module with the live
    deck-vs-plan path; a raising stub here would be one accidental import away
    from breaking production. The Phase-2 live path does not call this.
    """

    del slides, plan
    return PlanValidationResult(findings=[])


# ---------------------------------------------------------------------------
# Check 1: source fidelity
# ---------------------------------------------------------------------------


def _check_source_fidelity(plan: DeckPlan) -> list[AuditCheckResult]:
    """Sections may only name figures the roster contains; every figure
    must justify its place with ``why_in_source``.

    The roster ↔ source binding is the planner LLM's job (enforced by
    PLANNER_SYSTEM rule 1). What the validator can verify mechanically
    is the *internal consistency* between the sections and the roster:
    a section that names a figure absent from the roster is a plan that
    contradicts its own ground truth, which is exactly the failure
    pattern the planner exists to prevent.
    """

    out: list[AuditCheckResult] = []
    roster_names = {fig.name.strip() for fig in plan.figures}

    for index, section in enumerate(plan.sections):
        for name in section.figure_names:
            cleaned = name.strip()
            if cleaned and cleaned not in roster_names:
                out.append(
                    AuditCheckResult(
                        check_id=_CHECK_FIDELITY_ROSTER,
                        check_name="planner.source_fidelity.roster_subset",
                        passed=False,
                        severity=AuditSeverity.FAIL,
                        slide_index=index,
                        rule_reference="P-F1",
                        message=(
                            f"Section '{section.section_name}' names figure "
                            f"'{cleaned}' which is not in the DeckPlan figure "
                            "roster. Sections may only portray figures the "
                            "source actually names."
                        ),
                    )
                )

    for index, figure in enumerate(plan.figures):
        if not figure.why_in_source.strip():
            out.append(
                AuditCheckResult(
                    check_id=_CHECK_FIDELITY_WHY,
                    check_name="planner.source_fidelity.why_in_source",
                    passed=False,
                    severity=AuditSeverity.FAIL,
                    slide_index=index,
                    rule_reference="P-F2",
                    message=(
                        f"Figure '{figure.name}' carries no why_in_source. "
                        "Every figure must justify its place in the roster "
                        "with one short sentence grounded in the source."
                    ),
                )
            )
    return out


# ---------------------------------------------------------------------------
# Check 2: arc equality (the sync structural backstop)
# ---------------------------------------------------------------------------


def _check_arc_equality(plan: DeckPlan) -> list[AuditCheckResult]:
    """The minimal structural anchor: thesis ≠ section_name after normalisation.

    Phase 1 also rejected substring containment (label inside thesis, or
    thesis inside label). Phase 1.5 drops both directions because the
    label-in-thesis case false-rejects every legitimate thesis that
    names its subject — which is most theses in any language, and
    ALMOST EVERY thesis in agglutinative languages where the subject is
    short and frequently appears verbatim. The equality check alone is
    enough as a structural anchor; the predication classifier handles
    paraphrase and topic-list failures.
    """

    out: list[AuditCheckResult] = []
    for index, section in enumerate(plan.sections):
        norm_thesis = _normalize(section.thesis)
        norm_label = _normalize(section.section_name)
        if norm_thesis and norm_label and norm_thesis == norm_label:
            out.append(
                AuditCheckResult(
                    check_id=_CHECK_ARC_EQUALITY,
                    check_name="planner.arc.thesis_not_label",
                    passed=False,
                    severity=AuditSeverity.FAIL,
                    slide_index=index,
                    rule_reference="P-A1",
                    message=(
                        f"Section '{section.section_name}' has a thesis that "
                        "normalises to its section name. A thesis is what the "
                        "section argues, not what it is named."
                    ),
                )
            )
    return out


# ---------------------------------------------------------------------------
# Check 3: classifier verdicts (async path only)
# ---------------------------------------------------------------------------


def _findings_from_verdicts(
    plan: DeckPlan,
    verdicts: list[ThesisVerdict],
) -> list[AuditCheckResult]:
    """Translate classifier verdicts into validator findings.

    Order: section-index ascending. The classifier returns one verdict
    per section in input order; mismatches at this layer indicate a
    classifier-contract violation (the classifier should have raised
    :class:`ThesisClassifierError` instead of returning a wrong-length
    list), so we assert defensively.
    """

    if len(verdicts) != len(plan.sections):
        raise RuntimeError(
            f"verdict/section length mismatch: got {len(verdicts)} verdicts "
            f"for {len(plan.sections)} sections. The classifier should have "
            "raised before returning."
        )
    out: list[AuditCheckResult] = []
    for index, (section, verdict) in enumerate(zip(plan.sections, verdicts, strict=True)):
        if verdict.is_thesis:
            continue
        out.append(
            AuditCheckResult(
                check_id=_CHECK_ARC_PREDICATION,
                check_name="planner.arc.thesis_is_real_predication",
                passed=False,
                severity=AuditSeverity.FAIL,
                slide_index=index,
                rule_reference="P-A3",
                message=(
                    f"Section '{section.section_name}' has a thesis that "
                    f"the classifier rejected: {verdict.reason}"
                ),
            )
        )
    return out


# ---------------------------------------------------------------------------
# Check 4: structural coverage (warnings, not failures)
# ---------------------------------------------------------------------------


def _check_structural_coverage(plan: DeckPlan) -> list[AuditCheckResult]:
    """Warn — not fail — when the arc is degenerate or the figure roster
    is present but unused.

    A degenerate arc (all CORE, or no opening / no closing phase) often
    still ships a usable deck, so this is informational. A roster with
    figures that no section references is the canonical original-bug
    signature in inverted form: the source named real people, but the
    plan portrays none — exactly the visual void the Beethoven
    substitution filled.
    """

    out: list[AuditCheckResult] = []

    phases_used = {section.phase for section in plan.sections}
    has_opener = NarrativePhase.HOOK in phases_used or NarrativePhase.CONTEXT in phases_used
    has_closer = NarrativePhase.CLOSE in phases_used or NarrativePhase.IMPLICATIONS in phases_used
    if not has_opener or not has_closer:
        missing = ", ".join(
            label
            for ok, label in [
                (has_opener, "an opener (HOOK or CONTEXT)"),
                (has_closer, "a closer (IMPLICATIONS or CLOSE)"),
            ]
            if not ok
        )
        out.append(
            AuditCheckResult(
                check_id=_CHECK_COVERAGE_PHASES,
                check_name="planner.coverage.arc_shape",
                passed=False,
                severity=AuditSeverity.WARN,
                rule_reference="P-C1",
                message=(
                    f"Plan covers {len(phases_used)} narrative phase(s) but "
                    f"is missing {missing}. The deck may read as a flat "
                    "list rather than an argument."
                ),
            )
        )

    if plan.figures:
        named_anywhere = {
            name.strip()
            for section in plan.sections
            for name in section.figure_names
            if name.strip()
        }
        if not named_anywhere:
            out.append(
                AuditCheckResult(
                    check_id=_CHECK_COVERAGE_FIGURES,
                    check_name="planner.coverage.figures_used",
                    passed=False,
                    severity=AuditSeverity.WARN,
                    rule_reference="P-C2",
                    message=(
                        f"Plan rosters {len(plan.figures)} figure(s) but no "
                        "section lists any figure_names. The source names "
                        "real people, but no slide will portray them — "
                        "the executor will leave the portrait engine idle."
                    ),
                )
            )
    return out


# ---------------------------------------------------------------------------
# Check 5: figure ↔ claim grounding (optional, only when claims are given)
# ---------------------------------------------------------------------------


def _check_figure_claim_grounding(
    plan: DeckPlan,
    claims: list[SourceClaimCreate] | None,
) -> list[AuditCheckResult]:
    """When claims are supplied, every figure's ``source_claim_ids`` must
    reference an extracted claim by id.

    SourceClaimCreate.source_chunk_id defaults to "" because the chunker
    runs before persistence assigns claim ids. We therefore key on the
    claim text identity rather than UUIDs in Phase 1 — the planner
    schema's ``source_claim_ids`` is a forward-looking field, and this
    check verifies callers that DO populate it have done so against the
    real claim list. The check no-ops when claims is None so the
    validator stays decoupled from the evidence matrix.
    """

    if claims is None:
        return []

    out: list[AuditCheckResult] = []
    known: set[str] = {claim.claim_text for claim in claims}
    for index, figure in enumerate(plan.figures):
        for claim_ref in figure.source_claim_ids:
            cleaned = claim_ref.strip()
            if cleaned and cleaned not in known:
                out.append(
                    AuditCheckResult(
                        check_id=_CHECK_FIDELITY_CLAIMS,
                        check_name="planner.source_fidelity.claim_ids",
                        passed=False,
                        severity=AuditSeverity.WARN,
                        slide_index=index,
                        rule_reference="P-F3",
                        message=(
                            f"Figure '{figure.name}' references "
                            f"source_claim_id '{cleaned}' which does not "
                            "match any extracted claim in the supplied list."
                        ),
                    )
                )
    return out


# ---------------------------------------------------------------------------
# Deck-vs-plan checks (Phase 2, structural, no LLM)
# ---------------------------------------------------------------------------


def _section_index_of(slide: SlideSpec, plan: DeckPlan) -> int | None:
    """The plan-section index a slide belongs to, by normalised name, or None.

    A slide with no ``section_name`` (untagged) returns None — it covers no
    planned section and is not, by itself, an invented one.
    """

    name = (slide.section_name or "").strip()
    if not name:
        return None
    norm = _normalize(name)
    for index, section in enumerate(plan.sections):
        if _normalize(section.section_name) == norm:
            return index
    return None


def _slide_person_names(slide: SlideSpec) -> list[str]:
    """Real-person names a slide portrays: PersonItem names + timeline portraits.

    GALLERY_PEOPLE (and any slide populating ``content.people``) contributes
    each :class:`PersonItem` name; TIMELINE contributes each node's
    ``portrait_prompt`` (the editorial prompt sets it to the person's name).
    """

    names: list[str] = []
    content = slide.content
    if content.people:
        names.extend(person.name for person in content.people)
    if content.timeline_nodes:
        names.extend(
            node.portrait_prompt for node in content.timeline_nodes if node.portrait_prompt
        )
    return names


def _name_matches(query: str, candidate: str) -> bool:
    """Normalised substring containment in either direction.

    After normalising (casefold, strip surrounding punctuation, collapse
    whitespace) ``query`` matches ``candidate`` when either normalised form
    contains the other — so "Volter" matches "Volter (1694-1778)" and vice
    versa. No alias table, no hardcoded names.
    """

    nq, nc = _normalize(query), _normalize(candidate)
    if not nq or not nc:
        return False
    return nq in nc or nc in nq


def _check_deck_section_coverage(slides: list[SlideSpec], plan: DeckPlan) -> list[AuditCheckResult]:
    """D-S1: every planned section must appear on at least one slide."""

    covered = {index for slide in slides if (index := _section_index_of(slide, plan)) is not None}
    out: list[AuditCheckResult] = []
    for index, section in enumerate(plan.sections):
        if index not in covered:
            out.append(
                AuditCheckResult(
                    check_id=_CHECK_DECK_SECTION_COVERAGE,
                    check_name="deck.section_coverage",
                    passed=False,
                    severity=AuditSeverity.FAIL,
                    slide_index=index,
                    rule_reference=_CHECK_DECK_SECTION_COVERAGE,
                    message=(
                        f"Planned section '{section.section_name}' (#{index}) is "
                        "covered by no slide in the deck. The executor dropped a "
                        "section the plan committed to."
                    ),
                )
            )
    return out


def _check_deck_figure_adherence(slides: list[SlideSpec], plan: DeckPlan) -> list[AuditCheckResult]:
    """D-F1: a section that planned figures must portray them on its slides."""

    out: list[AuditCheckResult] = []
    for index, section in enumerate(plan.sections):
        required = [name.strip() for name in section.figure_names if name.strip()]
        if not required:
            continue
        carried = [
            name
            for slide in slides
            if _section_index_of(slide, plan) == index
            for name in _slide_person_names(slide)
        ]
        for figure in required:
            if not any(_name_matches(figure, person) for person in carried):
                out.append(
                    AuditCheckResult(
                        check_id=_CHECK_DECK_FIGURE_ADHERENCE,
                        check_name="deck.figure_adherence",
                        passed=False,
                        severity=AuditSeverity.FAIL,
                        slide_index=index,
                        rule_reference=_CHECK_DECK_FIGURE_ADHERENCE,
                        message=(
                            f"Section '{section.section_name}' planned figure "
                            f"'{figure}' but no slide in that section portrays them. "
                            "A planned people section that comes back without its "
                            "named people is the substitution failure."
                        ),
                    )
                )
    return out


def _check_deck_invented_figures(slides: list[SlideSpec], plan: DeckPlan) -> list[AuditCheckResult]:
    """D-X1: no people slide may portray someone outside the roster."""

    roster = [figure.name.strip() for figure in plan.figures if figure.name.strip()]
    out: list[AuditCheckResult] = []
    for slide_index, slide in enumerate(slides):
        if slide.slide_type not in _PEOPLE_BEARING_TYPES:
            continue
        for name in _slide_person_names(slide):
            if not any(_name_matches(name, roster_name) for roster_name in roster):
                out.append(
                    AuditCheckResult(
                        check_id=_CHECK_DECK_INVENTED_FIGURE,
                        check_name="deck.no_invented_figures",
                        passed=False,
                        severity=AuditSeverity.FAIL,
                        slide_index=slide_index,
                        rule_reference=_CHECK_DECK_INVENTED_FIGURE,
                        message=(
                            f"Slide #{slide_index} ({slide.slide_type.value}) portrays "
                            f"'{name}', who is not in the DeckPlan figure roster. The "
                            "deck must not introduce a person the source did not name."
                        ),
                    )
                )
    return out


def _check_deck_invented_sections(
    slides: list[SlideSpec], plan: DeckPlan
) -> list[AuditCheckResult]:
    """D-A1 (WARN): a slide tagged with a section the plan does not define."""

    out: list[AuditCheckResult] = []
    for slide_index, slide in enumerate(slides):
        name = (slide.section_name or "").strip()
        if not name:
            continue
        if _section_index_of(slide, plan) is None:
            out.append(
                AuditCheckResult(
                    check_id=_CHECK_DECK_INVENTED_SECTION,
                    check_name="deck.invented_section",
                    passed=False,
                    severity=AuditSeverity.WARN,
                    slide_index=slide_index,
                    rule_reference=_CHECK_DECK_INVENTED_SECTION,
                    message=(
                        f"Slide #{slide_index} is tagged section '{name}', which "
                        "matches no planned section. The executor added structure "
                        "beyond the plan."
                    ),
                )
            )
    return out


def failing_section_indices(
    failures: list[AuditCheckResult], slides: list[SlideSpec], plan: DeckPlan
) -> set[int]:
    """Map deck-vs-plan FAIL findings to the plan-section indices to repair.

    D-S1 / D-F1 pin a section directly via ``slide_index`` (it IS the section
    index). D-X1 pins the offending DECK slide, so we resolve that slide back to
    its section. The editorial pass uses this to scope its one repair attempt to
    only the failing sections. Findings that pin nothing resolvable are skipped.
    """

    out: set[int] = set()
    for finding in failures:
        index = finding.slide_index
        if index is None:
            continue
        if finding.check_id in (_CHECK_DECK_SECTION_COVERAGE, _CHECK_DECK_FIGURE_ADHERENCE):
            if 0 <= index < len(plan.sections):
                out.add(index)
        elif finding.check_id == _CHECK_DECK_INVENTED_FIGURE and 0 <= index < len(slides):
            section = _section_index_of(slides[index], plan)
            if section is not None:
                out.add(section)
    return out


# ---------------------------------------------------------------------------
# Normalisation helper
# ---------------------------------------------------------------------------


def _normalize(value: str) -> str:
    """Lowercase, strip surrounding punctuation, whitespace-collapse.

    Used by the equality check to compare a thesis to its section name
    without being fooled by case, surrounding whitespace, or a trailing
    period that turns "Constitutional ideas." into a non-match for
    "Constitutional ideas". Internal punctuation stays so hyphenated
    Karakalpak terms ("g'oyalar-háreketi") remain one token. ``casefold()``
    handles Turkic dotted/dotless I for KAA/UZ without an explicit table.
    """

    tokens: list[str] = []
    for raw in value.casefold().split():
        cleaned = raw.strip(".,;:!?—–-«»\"'()[]{}")
        if cleaned:
            tokens.append(cleaned)
    return " ".join(tokens)


__all__ = [
    "critique_deck_adversarially",
    "failing_section_indices",
    "validate_deck_against_plan",
    "validate_plan",
    "validate_plan_async",
]
