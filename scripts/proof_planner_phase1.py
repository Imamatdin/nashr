"""Phase-1.5 proof harness for the Planner Pass + Thesis Classifier.

This script is the gate Phase 1 and Phase 1.5 set: a runnable end-to-end
demonstration that

* the planner produces a source-grounded DeckPlan for an Enlightenment
  source whose musical figures are Bach + Mozart (NOT Beethoven),
* the structural sync validator rejects a deliberately malformed plan,
* the async validator (using the multilingual Gemini Flash classifier)
  accepts a real 3-token agglutinative Karakalpak thesis that Phase 1's
  removed token-floor check would have rejected.

Run from the repo root:

    set ANTHROPIC_API_KEY=...
    set GOOGLE_API_KEY=...    # or set GEMINI_API_KEY=...
    python scripts/proof_planner_phase1.py

The script runs three plans:

* **Run A** — real Sonnet plan against the Karakalpak Enlightenment
  fixture. validate_plan_async passes; bars 1–4 assert the canonical
  anti-substitution properties (Bach + Mozart + Diderot present,
  Beethoven absent).
* **Run B** — hand-written BAD plan (out-of-roster Beethoven + thesis
  that restates its section name). validate_plan_async fails. Bar 6.
* **Run C** — hand-written Karakalpak torture plan: a 3-token
  agglutinative predication "Ilim bilikti sındıradı". Phase 1's
  removed token-floor check would have FAIL'd it; Phase 1.5 must PASS
  it. Bar 7.

For every run the classifier's `reason` for every section is printed in
English, so every verdict is auditable in the output regardless of
input language.

Exit code 0 iff every bar above is PASS.

This is a SCRIPT, not a pytest test, because ``.claude/rules/testing.md``
forbids hitting real LLM APIs from the test suite. The unit tests in
``tests/unit/test_plan_validator.py`` and
``tests/unit/test_thesis_classifier.py`` cover the same code with
fixture data and stub clients.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import sys
from pathlib import Path

# Windows consoles default to cp1252, which cannot render Karakalpak /
# Uzbek diacritics ("ı", "ǵ", "á"); reconfigure stdout/stderr to UTF-8
# so a successful plan does not blow up when we print it. Only
# TextIOWrapper instances expose reconfigure; redirected pipes (tee, a
# file) are already byte-streams and need no change.
for _stream in (sys.stdout, sys.stderr):
    if isinstance(_stream, io.TextIOWrapper):
        _stream.reconfigure(encoding="utf-8", errors="replace")

# Make the repo importable when running from anywhere.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from packages.core.enums import (  # noqa: E402
    AudienceType,
    ClaimStrength,
    ClaimType,
    Language,
    NarrativeEmphasis,
    NarrativePhase,
    SlideType,
)
from packages.core.models.presentation import (  # noqa: E402
    AuditCheckResult,
    DeckPlan,
    PlannedFigure,
    PlannedSection,
    PresentationInterviewAnswers,
)
from packages.core.models.source import (  # noqa: E402
    SourceChunkCreate,
    SourceClaimCreate,
    SourceMetadataExtracted,
)
from packages.presentation.plan_validator import (  # noqa: E402
    validate_plan_async,
)
from packages.presentation.planner import PlannerError, PlannerPass  # noqa: E402
from packages.presentation.thesis_classifier import (  # noqa: E402
    ThesisClassifier,
    ThesisClassifierError,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("proof_planner_phase1")


# ---------------------------------------------------------------------------
# Karakalpak Enlightenment fixture — explicitly names Bach + Mozart
# ---------------------------------------------------------------------------
#
# This text is constructed for this harness — it is NOT a verbatim copy
# of any classroom material. The figure inventory mirrors the actual
# pedagogical pattern of a Karakalpak Theme 13 Enlightenment lesson
# (philosophers, scientists, writers, AND composers) and is anchored to
# the existing tests/golden Karakalpak Enlightenment corpus in
# vocabulary and tone. The composers are deliberately Bach and Mozart
# so the planner's roster can be checked against an LLM prior that
# wants to substitute Beethoven.


_CHUNK_1_TEXT = """Ag'artıwshılıq XVII-XVIII ásirlerde Yevropada payda bolg'an úlken oyshılıq háreketi boldı. Bul háreket aqıl-oyg'a, ilim-pánge hám insan erkinligine tayanıp, pútkil materigti qamtıp aldı. Frantsiyada Volter (Fransua-Mari Aruet, 1694-1778) din erkinligi hám ádalat ushın gúresken bolsa, Sharl Monteske (1689-1755) Esprit des lois (1748) eserinde hákimiyat bólisiwi doktrinasın taqdim etti. Jan Jak Russo (1712-1778) Du contrat social (1762) kitabında jámiyetlik kelisim teoriyasın qálipke kirgizdi. Bul oyshılardın katarına Denis Diderot (1713-1784) hám D'Alembert qosılıp, Ensiklopediya proyektin baslattı: 28 tomlıq tekstler hám 11 tomlıq súwretler menen bilimnin demokratlasıwına jol salıp berdi.

Britaniyada Adam Smit (1723-1790) ózinin Halıqlardın bayligi sebepleri haqqindag'i izertlewinde bazar ekonomikasinin tiykarın qoydı. Tag'i bir áhmiyetli figura — Daniel Defoe (1660-1731) — bul dáwirdin eń kórnekli ádebiyatshısı edi: Robinzon Kruzo (1719) romanı ózi-ózin tárbiyalaw hám aqıl-oydı qoyıw idealına súwretledi. Onin zamandasi Jonatan Swift (1667-1745) bolsa Gulliverdin sayaxatları (1726) menen Ag'artıwshılıqtın'ın o'zine qarama-qarsı qarawı, satira retinde dúrtti."""


_CHUNK_2_TEXT = """Germaniyada Ag'artıwshılıq Imanuel Kant (1724-1804) penen tag'i bir burqama erdi: 1784-jılı Was ist Aufklärung? essesinde Sapere aude — 'óz aqlıń menen oyla' degen úndep, bul shaqırıq XX-ásir filosoflarına shekem qaytalandı. Ádebiyatta Yohan Volfgang Goethe (1749-1832) Faust hám Yosh Verterdin azapları menen jana intellektual era ashtı.

Bilim ilim-pán tárepinen de keńeydi. Sir Isaac Newton (1643-1727) Principia (1687) menen tabiatdın matematikalıq nızamların aspaqlatti; Gottfried Wilhelm Leibniz (1646-1716) menen Newton arasında differentsial esabı tabilgan dáwir tartisına aylandı. Швейцариялы matematik Leonhard Euler (1707-1783) bolsa analiz hám sanlar teoriyasına aytarliq úles qosti. Kalkylyatsiyalar úlken jańa kúshlikti tilegen edi: tek g'ana XVIII ásirde Yevropa qıtalı uluwma 90 mıńnan kóp baspaxana ásbabı menen ǵalaba tabiatlandı."""


_CHUNK_3_TEXT = """Ag'artıwshılıq dáwiri tek g'ana ideyalardı emes, musika menen de oyandı. Yohann Sebastian Bach (1685-1750) bolsa barokko musikasının eń tereń figurası, Matthäus-Passion (1727) hám Brandenburg konserttleri menen kontrapunkt sansatın eń jogarı dárejege jetkizdi. Onin keyninde keyingi áwlattıń wákili — Volfgang Amadey Motsart (1756-1791) — bolsa klassikalıq musikanın simvolıga aylandı: Don Juan (1787) operasi hám 41-symfoniyası Jovian (1788) ulıwma Yevropalıq musikanın túyini boldı. Aytmaq kerek, Mozart 35 jas ómirinde 600 den artıq kompozitsiya jaratıp, klassisizmnin tiykarın qaladı.

Sol dáwirdiń Ag'artıwshılıq oyshılları aqıl-oytı qurıwshı tiykar dep biledi. Olardın ideyaları AQSh konstitutsiyasının tiykarına aylandı: Tomas Jefferson, Ben Jamin Franklin hám John Adams sol Volter hám Russonın kitaplarınan inspiratsiya aldı. Frantsiyada bolsa 1789-jılg'ı Adam hám ataq huqıqları deklaratsiyası tikkeley jámiyetlik kelisim teoriyasınan ósip shıqtı. Búgingi kúnde de Ag'artıwshılıqtın mırasi — Bach hám Motsarttın notalarınan baslap, Volter hám Russonın essalarına shekem — tirisheń."""


def _build_fixture() -> tuple[
    PresentationInterviewAnswers,
    list[SourceChunkCreate],
    list[SourceClaimCreate],
    list[SourceMetadataExtracted],
]:
    """Return (interview, chunks, claims, metadata) for the harness."""

    interview = PresentationInterviewAnswers(
        audience=AudienceType.UNDERGRADUATE,
        language=Language.KAA,
        narrative_emphasis=NarrativeEmphasis.BALANCED,
        include_interactive=False,
        closing_ask="Talabalar bilim erkinligin qorg'awg'a qalay úles qosa aladı?",
    )

    chunks = [
        SourceChunkCreate(chunk_index=0, page=1, text=_CHUNK_1_TEXT),
        SourceChunkCreate(chunk_index=1, page=2, text=_CHUNK_2_TEXT),
        SourceChunkCreate(chunk_index=2, page=3, text=_CHUNK_3_TEXT),
    ]

    # A small representative claim list. Note the extractor's view here
    # is intentionally THIN — the planner pass's value is reading the
    # chunk text above, NOT relying on the claims to be complete.
    claims = [
        SourceClaimCreate(
            claim_text=(
                "Sharl Monteske Esprit des lois eserinde hákimiyat bólisiwi "
                "doktrinasın taqdim etti."
            ),
            quote="Esprit des lois (1748)",
            strength=ClaimStrength.STRONG,
            claim_type=ClaimType.THEORETICAL_ARGUMENT,
        ),
        SourceClaimCreate(
            claim_text=(
                "Imanuel Kant 1784-jılı 'Sapere aude — óz aqlıń menen oyla' shaqırıg'ın bayan etti."
            ),
            quote="Was ist Aufklärung?",
            strength=ClaimStrength.STRONG,
            claim_type=ClaimType.THEORETICAL_ARGUMENT,
        ),
        SourceClaimCreate(
            claim_text=(
                "Adam Smit Halıqlardın bayligi sebepleri kitabinda bazar "
                "ekonomikasinin tiykarın qoydı."
            ),
            strength=ClaimStrength.MODERATE,
            claim_type=ClaimType.THEORETICAL_ARGUMENT,
        ),
        SourceClaimCreate(
            claim_text=(
                "Mozart 35 jas ómirinde 600 den artıq kompozitsiya jaratıp, "
                "klassisizmnin tiykarın qaladı."
            ),
            strength=ClaimStrength.STRONG,
            claim_type=ClaimType.STATISTICAL_RESULT,
        ),
        SourceClaimCreate(
            claim_text=(
                "Newton Principia (1687) menen tabiatdın matematikalıq nızamların aspaqlatti."
            ),
            strength=ClaimStrength.STRONG,
            claim_type=ClaimType.THEORETICAL_ARGUMENT,
        ),
        SourceClaimCreate(
            claim_text=(
                "XVIII ásirde Yevropa qıtalı uluwma 90 mıńnan kóp baspaxana "
                "ásbabı menen ǵalaba tabiatlandı."
            ),
            strength=ClaimStrength.MODERATE,
            claim_type=ClaimType.STATISTICAL_RESULT,
        ),
    ]

    metadata = [
        SourceMetadataExtracted(
            title="Ag'artıwshılıq dáwiri (Tema 13)",
            authors=["Pedagogika klassi"],
            year=2024,
            page_count=3,
            word_count=900,
            language_detected="kaa",
        ),
    ]

    return interview, chunks, claims, metadata


# ---------------------------------------------------------------------------
# Hand-written BAD plan — proves the validator gate bites
# ---------------------------------------------------------------------------


def _build_bad_plan() -> DeckPlan:
    """A deliberately malformed DeckPlan the validator must reject.

    Violations seeded:
    * A section names Beethoven, who is NOT in the roster — source
      fidelity FAIL P-F1 (the canonical anti-substitution gate).
    * A section's thesis restates its section_name — arc FAIL P-A1.
    * A section's thesis is a bare 3-token noun phrase — predication
      FAIL P-A2.

    The why_in_source FAIL P-F2 is covered by the unit test rather than
    the harness because :class:`PlannedFigure` enforces ``min_length=1``
    on that field at construction time (with str_strip_whitespace=True),
    which makes constructing a whitespace-only figure from a script
    impossible. The unit test bypasses that with ``model_copy`` to
    confirm the validator's strip()-based gate still catches it.
    """

    return DeckPlan(
        thesis="Ag'artıwshılıq Yevropada XVIII ásirde oyıw háreketi edi.",
        audience_takeaway="Talabalar dáwirdiń tiykarg'i oyshılların biledi.",
        sections=[
            PlannedSection(
                section_name="Kirisiw",
                # Thesis identical to the section_name in normalised form
                # → arc.thesis_not_label FAIL P-A1.
                thesis="Kirisiw boyınsha kirisiw — kirisiw kirisiw.",
                phase=NarrativePhase.HOOK,
                figure_names=[],
                planned_slide_types=[],
            ),
            PlannedSection(
                section_name="Oyshılar",
                # 3 tokens, no predication → arc.thesis_is_a_clause FAIL P-A2.
                thesis="Volter Russo Monteske",
                phase=NarrativePhase.CORE,
                # Beethoven is NOT in the figures roster below
                # → source_fidelity.roster_subset FAIL P-F1.
                figure_names=["Volter", "Lyudvig van Beethoven"],
                planned_slide_types=[],
            ),
            PlannedSection(
                section_name="Juwmaq",
                thesis="Ag'artıwshılıqtın mırası búgün de tirisheń jasap turıptı.",
                phase=NarrativePhase.CLOSE,
                figure_names=[],
                planned_slide_types=[],
            ),
        ],
        figures=[
            PlannedFigure(
                name="Volter",
                years="1694-1778",
                why_in_source="Source describes Voltaire as the leading Enlightenment voice.",
            ),
            PlannedFigure(
                name="Russo",
                years="1712-1778",
                why_in_source="Source names Rousseau as the social-contract treatise author.",
            ),
        ],
        image_cohesion_note="Oil-paint portraits in candlelit interiors.",
    )


# ---------------------------------------------------------------------------
# Karakalpak torture plan — Phase 1.5's load-bearing case
# ---------------------------------------------------------------------------


def _build_karakalpak_torture_plan() -> DeckPlan:
    """A plan whose theses are real Karakalpak predications in 3-4 tokens.

    Phase 1's removed token-floor check would have FAIL'd every one of
    these on length grounds, AND the also-removed substring check would
    have FAIL'd the "Ilim" section (label appears verbatim in thesis).

    Phase 1.5's sync validator accepts these (no length or substring
    checks), and the multilingual classifier must verify each is a real
    predication. The aggregated result must PASS.

    The Karakalpak orthography here is proper Latin script (ı, ş, á, ǵ,
    ń) — the same alphabet the existing fixtures and tests/golden corpus
    use. Each thesis predicates something: ``sındıradı`` (breaks),
    ``ashtı`` (opened), ``qaladı`` (anchors/founds), ``berdi`` (gave).
    """

    return DeckPlan(
        thesis=(
            "Ag'artıwshılıq aqıl-oydı diniy hákimiyat astınan azat etip, "
            "ilim hám konstitutsiyalıq oyǵa jol ashtı."
        ),
        audience_takeaway=(
            "Talabalar XVIII ásirdiń bes tiykarǵı klassikalıq oyın hám "
            "olardıń búgingi mırasın atap aytadı."
        ),
        sections=[
            PlannedSection(
                # Section name appears verbatim in the thesis — Phase 1's
                # substring check (now removed) would have FAIL'd this.
                section_name="Ilim",
                # 3-token agglutinative predication: subject + accusative
                # object + present-tense verb (with subject suffix).
                thesis="Ilim bilikti sındıradı.",
                phase=NarrativePhase.HOOK,
                figure_names=["Sir Isaac Newton"],
                planned_slide_types=[SlideType.CONCEPT_DEFINITION],
            ),
            PlannedSection(
                section_name="Erkinlik",
                # 4-token predication; one new token vs the label would
                # have failed Phase 1's new-token-delta check.
                thesis="Volter erkinliktiń jolın ashtı.",
                phase=NarrativePhase.CORE,
                figure_names=["Volter"],
                planned_slide_types=[SlideType.GALLERY_PEOPLE],
            ),
            PlannedSection(
                section_name="Musika",
                # 4-token predication naming people from the roster.
                thesis="Bach hám Motsart klassisizmdi qaladı.",
                phase=NarrativePhase.EVIDENCE,
                figure_names=["Bach", "Motsart"],
                planned_slide_types=[SlideType.GALLERY_PEOPLE, SlideType.TIMELINE],
            ),
            PlannedSection(
                section_name="Miras",
                # 5-token predication for the closing section.
                thesis="Bul ideyalar zamanagóy demokratiyanı qurdı.",
                phase=NarrativePhase.CLOSE,
                figure_names=[],
                planned_slide_types=[SlideType.SUMMARY_TAKEAWAY],
            ),
        ],
        figures=[
            PlannedFigure(
                name="Sir Isaac Newton",
                years="1643-1727",
                why_in_source="Source names Newton's Principia as the mathematical-laws text.",
            ),
            PlannedFigure(
                name="Volter",
                years="1694-1778",
                why_in_source="Source names Voltaire as the leading Enlightenment polemicist.",
            ),
            PlannedFigure(
                name="Bach",
                years="1685-1750",
                why_in_source="Source names Bach as the deepest Baroque musical figure.",
            ),
            PlannedFigure(
                name="Motsart",
                years="1756-1791",
                why_in_source="Source names Mozart (Motsart) as the symbol of classical music.",
            ),
        ],
        image_cohesion_note=(
            "Eighteenth-century European candlelit-interior palette with copper-engraving line art."
        ),
    )


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------


_BAR_BACH_PRESENT = "Bach is in the roster (source-grounded)."
_BAR_MOZART_PRESENT = "Mozart is in the roster (source-grounded)."
_BAR_BEETHOVEN_ABSENT = "Beethoven is NOT in the roster (the substitution bug)."
_BAR_DIDEROT_PRESENT = "Diderot is in the roster (NOT in editorial's _PERSON_KEYWORDS today)."
_BAR_GOOD_PLAN_VALID = "Async validator passes the planner's plan (zero FAIL findings)."
_BAR_BAD_PLAN_REJECTED = "Async validator rejects the hand-written bad plan (≥1 FAIL findings)."
_BAR_KAA_SHORT_THESIS_PASSES = (
    "Short agglutinative Karakalpak thesis is accepted as a real predication."
)


def _name_set(plan: DeckPlan) -> set[str]:
    return {f.name.strip().casefold() for f in plan.figures}


def _has_name(plan: DeckPlan, *candidates: str) -> bool:
    names = _name_set(plan)
    for candidate in candidates:
        if candidate.casefold() in names:
            return True
        # Match name fragments since the source's Karakalpak spelling
        # may render Mozart as "Motsart", Bach as "Bax" etc.
        for name in names:
            if candidate.casefold() in name or name in candidate.casefold():
                return True
    return False


def _print_bar(label: str, ok: bool) -> None:
    tag = "PASS" if ok else "FAIL"
    print(f"  [{tag}] {label}")


def _print_findings(label: str, findings: list[AuditCheckResult]) -> None:
    if not findings:
        print(f"  {label}: (none)")
        return
    print(f"  {label}:")
    for finding in findings:
        idx = f" [section #{finding.slide_index}]" if finding.slide_index is not None else ""
        print(f"   - [{finding.severity.value}] {finding.check_id}{idx}: {finding.message}")


async def _run_planner() -> tuple[DeckPlan | None, str | None]:
    interview, chunks, claims, metadata = _build_fixture()
    planner = PlannerPass()
    try:
        plan = await planner.plan_deck(
            interview=interview,
            claims=claims,
            chunks=chunks,
            source_metadata=metadata,
        )
        return plan, None
    except PlannerError as exc:
        return None, str(exc)


async def _classify_for_print(
    classifier: ThesisClassifier,
    plan: DeckPlan,
    language: Language,
) -> list[object]:
    """Return verdicts alongside (or raise) so the harness can print reasons."""

    items = [(s.section_name, s.thesis) for s in plan.sections]
    verdicts = await classifier.classify(items, language)
    return list(verdicts)


def _print_section_verdicts(plan: DeckPlan, verdicts: list[object]) -> None:
    """Render the classifier's per-section verdict in English."""

    for index, section in enumerate(plan.sections):
        verdict = verdicts[index] if index < len(verdicts) else None
        tag = "?"
        reason = "(no verdict)"
        if verdict is not None:
            tag = "thesis" if getattr(verdict, "is_thesis", False) else "label"
            reason = getattr(verdict, "reason", "") or "(no reason)"
        print(f"   {index + 1}. [{tag}] {section.section_name}")
        print(f"      thesis: {section.thesis}")
        print(f"      reason: {reason}")


async def _run_async_validation(
    label: str,
    plan: DeckPlan,
    classifier: ThesisClassifier,
    language: Language,
) -> tuple[bool, str | None, list[object]]:
    """Return (passed, error_message, verdicts_for_printing).

    We classify once for printing and then call validate_plan_async — but
    we can also call validate_plan_async directly since it makes its
    OWN classifier call. To keep the cost to ONE Gemini call per plan,
    we classify explicitly here and let validate_plan_async build its
    own result deterministically. Final wiring: in production Phase 2 the
    orchestrator would call validate_plan_async directly; this harness
    splits the call so the reasons are printable per section.
    """

    try:
        verdicts = await _classify_for_print(classifier, plan, language)
    except ThesisClassifierError as exc:
        return False, f"classifier raised: {exc}", []
    print(f"  {label} — classifier verdicts:")
    _print_section_verdicts(plan, verdicts)

    # Re-run through validate_plan_async with a stub that replays the
    # already-obtained verdicts; this gives us the validator's merged
    # findings without a second Gemini call. The stub is local-only.
    class _ReplayClassifier(ThesisClassifier):
        def __init__(self, replay: list[object]) -> None:
            super().__init__(gemini=None)
            self._replay = replay

        async def classify(  # type: ignore[override]
            self,
            items: list[tuple[str, str]],
            language: Language,
        ) -> list[object]:  # type: ignore[override]
            del items, language
            return self._replay

    replay = _ReplayClassifier(verdicts)
    result = await validate_plan_async(plan, classifier=replay, language=language)  # type: ignore[arg-type]
    _print_findings(f"  {label} — validator findings", result.findings)
    return result.passed, None, verdicts


async def _amain() -> int:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print(
            "Set ANTHROPIC_API_KEY before running this harness — Phase 1.5's "
            "proof requires a real Sonnet call against the Karakalpak fixture."
        )
        return 2
    if not (os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")):
        print(
            "Set GOOGLE_API_KEY or GEMINI_API_KEY before running this harness — "
            "Phase 1.5 calls Gemini 3.5 Flash for the multilingual predication "
            "classifier."
        )
        return 2

    print("=" * 78)
    print("Phase 1.5 proof harness — PlannerPass + plan_validator + ThesisClassifier")
    print("=" * 78)
    print()

    classifier = ThesisClassifier()

    # -----------------------------------------------------------------------
    # Run A — real Sonnet plan against the Karakalpak Enlightenment fixture.
    # -----------------------------------------------------------------------

    print("[1] Running PlannerPass against the Karakalpak Enlightenment fixture...")
    plan, error = await _run_planner()
    if plan is None:
        print(f"  Planner raised PlannerError: {error}")
        print()
        print("OVERALL: FAIL (planner failed before any bars could be checked).")
        return 1
    print("  Planner returned a DeckPlan.")
    print()

    print("[2] DeckPlan as JSON:")
    print(json.dumps(plan.model_dump(mode="json"), indent=2, ensure_ascii=False))
    print()

    print("[3] Roster (printed for human eyeballing against the source):")
    for figure in plan.figures:
        years = f" ({figure.years})" if figure.years else ""
        print(f"   - {figure.name}{years} — {figure.why_in_source}")
    print()

    print("[4] Section arc (planner output):")
    for index, section in enumerate(plan.sections):
        print(f"   {index + 1}. [{section.phase.value}] {section.section_name}")
        print(f"      thesis: {section.thesis}")
        if section.figure_names:
            print(f"      figures: {', '.join(section.figure_names)}")
    print()

    print("[5] Running validate_plan_async on the planner's plan (Run A)...")
    good_passes, good_err, _good_verdicts = await _run_async_validation(
        "good plan", plan, classifier, language=Language.KAA
    )
    if good_err:
        print(f"  classifier error: {good_err}")
    print()

    # -----------------------------------------------------------------------
    # Run B — hand-written BAD plan.
    # -----------------------------------------------------------------------

    print("[6] Running validate_plan_async on the hand-written BAD plan (Run B)...")
    bad_plan = _build_bad_plan()
    bad_passes, bad_err, _bad_verdicts = await _run_async_validation(
        "bad plan", bad_plan, classifier, language=Language.KAA
    )
    if bad_err:
        print(f"  classifier error: {bad_err}")
    bad_fails = (not bad_passes) and bad_err is None  # the bad plan must FAIL, not error
    print()

    # -----------------------------------------------------------------------
    # Run C — Karakalpak short-thesis torture plan (the new Phase-1.5 bar).
    # -----------------------------------------------------------------------

    print("[7] Running validate_plan_async on the Karakalpak short-thesis plan (Run C)...")
    torture_plan = _build_karakalpak_torture_plan()
    print("  Karakalpak sections under test:")
    for index, section in enumerate(torture_plan.sections):
        n_tokens = len(section.thesis.split())
        print(f'   {index + 1}. {section.section_name}: "{section.thesis}" ({n_tokens} tokens)')
    print()
    torture_passes, torture_err, _torture_verdicts = await _run_async_validation(
        "Karakalpak torture", torture_plan, classifier, language=Language.KAA
    )
    if torture_err:
        print(f"  classifier error: {torture_err}")
    print()

    # -----------------------------------------------------------------------
    # Bars.
    # -----------------------------------------------------------------------

    print("[8] PASS / FAIL bars:")
    bach_ok = _has_name(plan, "Bach", "Bax")
    mozart_ok = _has_name(plan, "Mozart", "Motsart")
    beethoven_absent = not _has_name(plan, "Beethoven")
    diderot_ok = _has_name(plan, "Diderot")

    _print_bar(_BAR_BACH_PRESENT, bach_ok)
    _print_bar(_BAR_MOZART_PRESENT, mozart_ok)
    _print_bar(_BAR_BEETHOVEN_ABSENT, beethoven_absent)
    _print_bar(_BAR_DIDEROT_PRESENT, diderot_ok)
    _print_bar(_BAR_GOOD_PLAN_VALID, good_passes)
    _print_bar(_BAR_BAD_PLAN_REJECTED, bad_fails)
    _print_bar(_BAR_KAA_SHORT_THESIS_PASSES, torture_passes)
    print()

    all_pass = (
        bach_ok
        and mozart_ok
        and beethoven_absent
        and diderot_ok
        and good_passes
        and bad_fails
        and torture_passes
    )
    if all_pass:
        print("OVERALL: PASS — Phase 1.5 proof bar met.")
        return 0
    print("OVERALL: FAIL — one or more Phase 1.5 bars not met. See [8] above.")
    return 1


def main() -> int:
    return asyncio.run(_amain())


if __name__ == "__main__":
    sys.exit(main())
