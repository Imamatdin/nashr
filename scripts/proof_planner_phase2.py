"""Phase-2 proof harness — the full planner-bound editorial pass, end to end.

Phase 1/1.5 proved the planner + plan validator in isolation. Phase 2 wired
them into the LIVE editorial path and added the deck-vs-plan gate. This harness
is the real proof of the fix: it runs the FULL :meth:`EditorialPass.generate_deck_spec`
(real planner + real executor + real plan/deck validation) on TWO real sources
and asserts the bug is dead in production.

THE BARS
--------
Enlightenment (Karakalpak, the positive case — the source names real people):
  * generation SUCCEEDS — i.e. the deck passed the internal plan + deck-vs-plan
    gates (every planned section present, no person outside the roster), or
    generate_deck_spec would have raised.
  * people are NOT null — at least one slide carries real figures (the original
    bug was people=null on every slide).
  * the music figures are Bach + Mozart, and Beethoven is ABSENT (the canonical
    substitution the keyword roster + discarded source used to cause).
  * an INTERACTIVE_MATCHING slide is present — the regression guard for the
    SECOND consumer of people_mentioned (it is now regrounded from the plan).
  * the DeckSpec round-trips through the renderer contract.

sCO2 (English, the negative case — a real paper that names NO biographical
people, only bibliographic ``Ahn et al.``):
  * generation SUCCEEDS.
  * the deck grows NO people slide and names NOBODY — there is no minimum-people
    quota to fabricate (the no-hardcode guarantee at runtime).
  * charts/stats are still chosen (the DATA-SHAPE tree is intact).
  * the DeckSpec round-trips.

This is a SCRIPT, not pytest (``.claude/rules/testing.md`` forbids real LLM
calls in the suite). The stubbed unit coverage lives in
``tests/unit/test_editorial_pass.py``, ``tests/unit/test_plan_validator.py``,
and ``tests/unit/test_planner_pass.py``.

Run from the repo root, on the server (Vertex):

    set ANTHROPIC_API_KEY=...      # Sonnet — planner + editorial executor
    set VERTEX_PROJECT=...         # Vertex AI + ADC (gcloud auth ... login)
    # or, for AI Studio instead of Vertex: set GOOGLE_API_KEY=...
    python scripts/proof_planner_phase2.py

Exit code 0 iff every bar passes.
"""

from __future__ import annotations

import asyncio
import io
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

# Karakalpak diacritics blow up cp1252 consoles; force UTF-8 like Phase 1.
for _stream in (sys.stdout, sys.stderr):
    if isinstance(_stream, io.TextIOWrapper):
        _stream.reconfigure(encoding="utf-8", errors="replace")

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from packages.core.enums import (  # noqa: E402
    BackgroundTreatment,
    PresentationMood,
    SlideType,
)
from packages.core.models.evidence import EvidenceMatrix  # noqa: E402
from packages.core.models.presentation import (  # noqa: E402
    ColorPalette,
    DeckSpec,
    DesignDirectionSpec,
    PresentationInterviewAnswers,
)
from packages.core.models.source import (  # noqa: E402
    SourceChunkCreate,
    SourceClaimCreate,
    SourceMetadataExtracted,
)
from packages.presentation.editorial import (  # noqa: E402
    EditorialDeckPlanMismatchError,
    EditorialPass,
    EditorialPlanRejectedError,
)
from packages.presentation.planner import PlannerError, PlannerPass  # noqa: E402
from packages.presentation.thesis_classifier import ThesisClassifierError  # noqa: E402
from scripts.proof_planner_phase1 import build_enlightenment_fixture  # noqa: E402
from scripts.sco2_source_fixture import build_sco2_source_fixture  # noqa: E402

_PEOPLE_SLIDE_TYPES = frozenset({SlideType.GALLERY_PEOPLE, SlideType.TIMELINE})
_CHART_OR_STAT_TYPES = frozenset({SlideType.CHART_DATA, SlideType.DATA_EMPHASIS})


def _design() -> DesignDirectionSpec:
    """A valid DesignDirectionSpec. Editorial ``del``s design (palette is the
    renderer's concern), so the exact values do not affect the slide output;
    this just satisfies the signature without a second LLM (design) call."""

    return DesignDirectionSpec(
        mood=PresentationMood.CLEAN_PROFESSIONAL,
        palette=ColorPalette(
            background="#F8F8FA",
            surface="#FFFFFF",
            text="#2A2A2A",
            accent="#0A8A7A",
            text_secondary="#6A6A7A",
        ),
        heading_font="Inter",
        body_font="Inter",
        decorative_font=None,
        image_style_prefix="clean modern",
        background_treatment=BackgroundTreatment.LIGHT,
    )


def _evidence_matrix() -> EvidenceMatrix:
    return EvidenceMatrix(project_id=uuid4(), created_at=datetime.now(UTC))


def _deck_person_names(deck: DeckSpec) -> list[str]:
    """Every real-person name the deck portrays (PersonItem + timeline portraits)."""

    names: list[str] = []
    for slide in deck.slides:
        if slide.content.people:
            names.extend(p.name for p in slide.content.people)
        if slide.content.timeline_nodes:
            names.extend(
                n.portrait_prompt for n in slide.content.timeline_nodes if n.portrait_prompt
            )
    return names


def _mentions(names: list[str], *candidates: str) -> bool:
    """Casefold substring match in either direction (handles "Motsart"/"Bax"
    spellings and "Voltaire (1694-1778)" suffixes)."""

    folded = [n.casefold() for n in names]
    for candidate in candidates:
        cand = candidate.casefold()
        if any(cand in name or name in cand for name in folded):
            return True
    return False


async def _generate(
    fixture: tuple[
        PresentationInterviewAnswers,
        list[SourceChunkCreate],
        list[SourceClaimCreate],
        list[SourceMetadataExtracted],
    ],
) -> tuple[DeckSpec | None, str | None]:
    """Run the full editorial pass; return (deck, error_message)."""

    interview, chunks, claims, metadata = fixture
    editorial = EditorialPass()
    try:
        deck = await editorial.generate_deck_spec(
            interview=interview,
            design=_design(),
            evidence_matrix=_evidence_matrix(),
            claims=claims,
            chunks=chunks,
            source_metadata=metadata,
        )
        return deck, None
    except (
        PlannerError,
        ThesisClassifierError,
        EditorialPlanRejectedError,
        EditorialDeckPlanMismatchError,
    ) as exc:
        return None, f"{type(exc).__name__}: {exc}"


def _print_bar(label: str, ok: bool) -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}")


def _round_trips(deck: DeckSpec) -> bool:
    """The DeckSpec survives a serialise -> reconstruct cycle (renderer contract)."""

    try:
        rebuilt = DeckSpec.model_validate(deck.model_dump(mode="json"))
    except Exception:  # any failure to reconstruct is a renderer-contract break
        return False
    return rebuilt.slide_count == deck.slide_count


def _print_deck(deck: DeckSpec) -> None:
    print(f"  {deck.slide_count} slides:")
    for slide in deck.slides:
        section = f" <{slide.section_name}>" if slide.section_name else ""
        people = ", ".join(p.name for p in (slide.content.people or []))
        portraits = ", ".join(
            n.portrait_prompt for n in (slide.content.timeline_nodes or []) if n.portrait_prompt
        )
        who = f"  people=[{people or portraits}]" if (people or portraits) else ""
        print(
            f"   {slide.slide_index:>2}. {slide.slide_type.value}{section}: {slide.content.title}{who}"
        )


async def _bars_enlightenment() -> bool:
    print("=" * 78)
    print("[A] ENLIGHTENMENT (Karakalpak) — full generate_deck_spec")
    print("=" * 78)
    interview, chunks, claims, metadata = build_enlightenment_fixture()
    # interactive ON so the matching-slide guard (people_mentioned consumer #2)
    # is exercised; the source names 3+ people.
    interview = interview.model_copy(update={"include_interactive": True})
    deck, error = await _generate((interview, chunks, claims, metadata))
    if deck is None:
        print(f"  generate_deck_spec raised: {error}")
        _print_bar("Enlightenment generation succeeded", False)
        return False
    _print_deck(deck)
    print()

    names = _deck_person_names(deck)
    people_not_null = len(names) > 0
    bach = _mentions(names, "Bach", "Bax")
    mozart = _mentions(names, "Mozart", "Motsart")
    beethoven_absent = not _mentions(names, "Beethoven")
    has_matching = any(s.slide_type is SlideType.INTERACTIVE_MATCHING for s in deck.slides)
    round_trips = _round_trips(deck)

    print(f"  people portrayed by the deck: {names or '(none)'}")
    _print_bar("generation succeeded (plan + deck-vs-plan gates passed internally)", True)
    _print_bar("people are NOT null (a slide carries real figures)", people_not_null)
    _print_bar("Bach is portrayed", bach)
    _print_bar("Mozart is portrayed", mozart)
    _print_bar("Beethoven is ABSENT (the substitution bug)", beethoven_absent)
    _print_bar(
        "an INTERACTIVE_MATCHING slide is present (people_mentioned consumer #2)", has_matching
    )
    _print_bar("DeckSpec round-trips (renderer contract intact)", round_trips)
    return all([people_not_null, bach, mozart, beethoven_absent, has_matching, round_trips])


async def _bars_sco2() -> bool:
    print("=" * 78)
    print("[B] sCO2 (English, real paper) — full generate_deck_spec, no-people regression")
    print("=" * 78)
    interview, chunks, claims, metadata = build_sco2_source_fixture()

    # Roster-level proof (the planner's job): the paper CITES 'Ahn, Y. et al.' in
    # its references. A cited author is NOT a biographical subject the deck
    # portrays, so the planner's figure roster must EXCLUDE it. This is sharper
    # than roster size alone — it pins the author-vs-subject distinction.
    try:
        plan = await PlannerPass().plan_deck(
            interview=interview, claims=claims, chunks=chunks, source_metadata=metadata
        )
    except (PlannerError, ThesisClassifierError) as exc:
        print(f"  planner raised: {type(exc).__name__}: {exc}")
        _print_bar("sCO2 planner produced a roster", False)
        return False
    roster = [fig.name for fig in plan.figures]
    print(
        f"  planner figure roster ({len(roster)}): {roster or '(empty — correct for this source)'}"
    )
    ahn_excluded = not _mentions(roster, "Ahn")
    _print_bar(
        "planner roster EXCLUDES cited author 'Ahn' (author != portrayed subject)", ahn_excluded
    )
    print()

    deck, error = await _generate((interview, chunks, claims, metadata))
    if deck is None:
        print(f"  generate_deck_spec raised: {error}")
        _print_bar("sCO2 generation succeeded", False)
        return False
    _print_deck(deck)
    print()

    names = _deck_person_names(deck)
    no_people = len(names) == 0
    no_people_slide = not any(s.slide_type in _PEOPLE_SLIDE_TYPES for s in deck.slides)
    has_charts = any(s.slide_type in _CHART_OR_STAT_TYPES for s in deck.slides)
    round_trips = _round_trips(deck)

    print(f"  people portrayed by the deck: {names or '(none — correct for this source)'}")
    _print_bar("generation succeeded", True)
    _print_bar("NO person is portrayed (the source named nobody — no fabrication)", no_people)
    _print_bar("NO GALLERY_PEOPLE / TIMELINE slide was forced", no_people_slide)
    _print_bar("charts/stats present (DATA-SHAPE tree intact)", has_charts)
    _print_bar("DeckSpec round-trips (renderer contract intact)", round_trips)
    return all([ahn_excluded, no_people, no_people_slide, has_charts, round_trips])


async def _amain() -> int:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print(
            "Set ANTHROPIC_API_KEY — Phase 2 runs real Sonnet calls for the planner "
            "and the editorial executor."
        )
        return 2
    if not (
        os.environ.get("VERTEX_PROJECT")
        or os.environ.get("GOOGLE_API_KEY")
        or os.environ.get("GEMINI_API_KEY")
    ):
        print(
            "Set VERTEX_PROJECT (Vertex AI + ADC) — or GOOGLE_API_KEY / GEMINI_API_KEY "
            "for AI Studio. Phase 2 calls Gemini for the thesis classifier and the "
            "interactive pass."
        )
        return 2

    print("Phase 2 proof — planner-bound editorial, full generate_deck_spec on two sources.")
    print()
    enlightenment_ok = await _bars_enlightenment()
    print()
    sco2_ok = await _bars_sco2()
    print()
    if enlightenment_ok and sco2_ok:
        print("OVERALL: PASS — Phase 2 bug-fix proven end to end on both sources.")
        return 0
    print("OVERALL: FAIL — one or more Phase 2 bars not met. See above.")
    return 1


def main() -> int:
    return asyncio.run(_amain())


if __name__ == "__main__":
    sys.exit(main())
