"""Build 1 live gate — content critic + Gemini 3.x swap on two real fixtures.

Runs the FULL :meth:`EditorialPass.generate_deck_spec` on Enlightenment (Karakalpak,
people-rich) and sCO2 (English paper, no biographical subjects). Dumps deck JSONs,
prints structured telemetry for eyeball review. Does NOT judge planner roster quality
or critic correctness — reports facts only.

Run from repo root with live creds (Vertex global endpoint):

    python scripts/proof_build1_critic.py

Exit 0 iff both decks generated without an unhandled exception; 1 on generation
failure; 2 if creds are missing.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import sys
import traceback
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

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
    EditorialContentCriticError,
    EditorialDeckPlanMismatchError,
    EditorialPass,
    EditorialPlanRejectedError,
)
from packages.presentation.planner import PlannerError, PlannerPass  # noqa: E402
from packages.presentation.thesis_classifier import ThesisClassifierError  # noqa: E402
from scripts.proof_planner_phase1 import build_enlightenment_fixture  # noqa: E402
from scripts.sco2_source_fixture import build_sco2_source_fixture  # noqa: E402

_DEBUG_DIR = _REPO_ROOT / "debug"
_ENLIGHTENMENT_DECK = _DEBUG_DIR / "build1_enlightenment_deck.json"
_SCO2_DECK = _DEBUG_DIR / "build1_sco2_deck.json"
_LOG_PATH = _DEBUG_DIR / "build1_gate.log"

_PEOPLE_SLIDE_TYPES = frozenset({SlideType.GALLERY_PEOPLE, SlideType.TIMELINE})


def _configure_logging() -> None:
    """Structured INFO to stdout so docker exec captures critic/planner events."""

    root = logging.getLogger()
    root.handlers.clear()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    for name in (
        "packages.presentation.content_critic",
        "packages.presentation.editorial",
        "packages.presentation.planner",
        "packages.core.gemini",
        "packages.core.gemini_image",
        "packages.presentation.image_generation",
        "packages.presentation.image_pass",
    ):
        logging.getLogger(name).setLevel(logging.INFO)


def _design(mood: PresentationMood = PresentationMood.CLEAN_PROFESSIONAL) -> DesignDirectionSpec:
    return DesignDirectionSpec(
        mood=mood,
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


def _deck_person_names(deck: DeckSpec) -> dict[int, list[str]]:
    """Per-slide people on gallery/timeline slides."""

    by_slide: dict[int, list[str]] = {}
    for slide in deck.slides:
        if slide.slide_type not in _PEOPLE_SLIDE_TYPES:
            continue
        names: list[str] = []
        if slide.content.people:
            names.extend(p.name for p in slide.content.people)
        if slide.content.timeline_nodes:
            names.extend(
                n.portrait_prompt
                for n in slide.content.timeline_nodes
                if n.portrait_prompt
            )
        if names:
            by_slide[slide.slide_index] = names
    return by_slide


def _image_slot_summary(deck: DeckSpec) -> tuple[int, int]:
    """Count resolved vs pending image slots (generate_deck_spec does not run ImagePass)."""

    resolved = 0
    pending = 0
    for slide in deck.slides:
        content = slide.content
        for person in content.people or []:
            if person.name:
                if person.portrait_url:
                    resolved += 1
                else:
                    pending += 1
        for node in content.timeline_nodes or []:
            if node.portrait_prompt:
                if node.portrait_url:
                    resolved += 1
                else:
                    pending += 1
        if content.figure_prompt:
            if content.figure_url:
                resolved += 1
            else:
                pending += 1
        if slide.slide_type is SlideType.TITLE_HERO:
            if content.background_url:
                resolved += 1
            else:
                pending += 1
    return resolved, pending


def _interactive_slides(deck: DeckSpec) -> list[str]:
    return [
        f"idx {s.slide_index}: {s.slide_type.value} — {s.content.title}"
        for s in deck.slides
        if s.slide_type.value.startswith("interactive_")
    ]


def _print_deck_summary(label: str, deck: DeckSpec, deck_path: Path) -> None:
    print("=" * 78)
    print(f"[{label}] deck generated — {deck.slide_count} slides")
    print("=" * 78)
    print(f"  title:    {deck.title}")
    print(f"  subtitle: {deck.subtitle}")
    print(f"  dumped:   {deck_path}")
    print()
    print("  section structure:")
    seen: set[str] = set()
    for slide in deck.slides:
        sec = slide.section_name or "(no section)"
        if sec not in seen:
            seen.add(sec)
            print(f"    - {sec}")
    print()
    people_by_slide = _deck_person_names(deck)
    if people_by_slide:
        print("  gallery/timeline people roster:")
        for idx, names in sorted(people_by_slide.items()):
            slide = deck.slides[idx]
            print(
                f"    slide {idx} ({slide.slide_type.value}): {names}"
            )
    else:
        print("  gallery/timeline people roster: (none)")
    print()
    resolved, nulls = _image_slot_summary(deck)
    print(
        f"  image slots (pre-ImagePass): resolved={resolved}, pending={nulls}"
    )
    interactives = _interactive_slides(deck)
    print(f"  interactive slides ({len(interactives)}):")
    for line in interactives:
        print(f"    {line}")
    print()
    print("  slide inventory:")
    for slide in deck.slides:
        section = f" <{slide.section_name}>" if slide.section_name else ""
        print(
            f"   {slide.slide_index:>2}. {slide.slide_type.value}{section}: "
            f"{slide.content.title}"
        )
    print()


async def _run_planner_roster(
    label: str,
    interview: PresentationInterviewAnswers,
    chunks: list[SourceChunkCreate],
    claims: list[SourceClaimCreate],
    metadata: list[SourceMetadataExtracted],
) -> None:
    try:
        plan = await PlannerPass().plan_deck(
            interview=interview, claims=claims, chunks=chunks, source_metadata=metadata
        )
        roster = [fig.name for fig in plan.figures]
        print(f"  [{label}] planner figure roster ({len(roster)}): {roster}")
        print(f"  [{label}] planner sections ({len(plan.sections)}):")
        for sec in plan.sections:
            print(f"    - {sec.name}: {len(sec.slides)} planned slides")
    except (PlannerError, ThesisClassifierError) as exc:
        print(f"  [{label}] planner raised: {type(exc).__name__}: {exc}")


async def _generate_deck(
    label: str,
    fixture: tuple[
        PresentationInterviewAnswers,
        list[SourceChunkCreate],
        list[SourceClaimCreate],
        list[SourceMetadataExtracted],
    ],
    *,
    include_interactive: bool,
    deck_path: Path,
) -> bool:
    interview, chunks, claims, metadata = fixture
    if include_interactive:
        interview = interview.model_copy(update={"include_interactive": True})

    print(f"\n>>> Starting {label} — planner roster probe")
    await _run_planner_roster(label, interview, chunks, claims, metadata)
    print(f"\n>>> Starting {label} — full generate_deck_spec")

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
    except EditorialContentCriticError as exc:
        print(f"\n[{label}] EditorialContentCriticError (hard-stop):")
        for f in exc.findings:
            print(f"  - {f.check_id} slide={f.slide_id}: {f.message}")
        print(f"  findings count: {len(exc.findings)}")
        return False
    except (
        PlannerError,
        ThesisClassifierError,
        EditorialPlanRejectedError,
        EditorialDeckPlanMismatchError,
    ) as exc:
        print(f"\n[{label}] generate_deck_spec raised: {type(exc).__name__}: {exc}")
        return False
    except Exception:
        print(f"\n[{label}] UNHANDLED exception:")
        traceback.print_exc()
        return False

    _DEBUG_DIR.mkdir(exist_ok=True)
    deck_path.write_text(
        json.dumps(deck.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _print_deck_summary(label, deck, deck_path)
    return True


async def _amain() -> int:
    _configure_logging()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Set ANTHROPIC_API_KEY — editorial executor runs real Sonnet calls.")
        return 2
    if not (
        os.environ.get("VERTEX_PROJECT")
        or os.environ.get("GOOGLE_API_KEY")
        or os.environ.get("GEMINI_API_KEY")
    ):
        print(
            "Set VERTEX_PROJECT (Vertex AI + ADC) — or GOOGLE_API_KEY / GEMINI_API_KEY."
        )
        return 2

    vertex_loc = os.environ.get("VERTEX_LOCATION", "global")
    vertex_proj = os.environ.get("VERTEX_PROJECT", "(unset)")
    print("Build 1 gate — content critic + Gemini 3.x swap")
    print(f"  VERTEX_PROJECT={vertex_proj}  VERTEX_LOCATION={vertex_loc}")
    print(f"  log file (tee): {_LOG_PATH}")
    print()

    _DEBUG_DIR.mkdir(exist_ok=True)
    log_file = _LOG_PATH.open("w", encoding="utf-8")

    class _Tee(io.TextIOBase):
        def write(self, s: str) -> int:
            sys.stdout.write(s)
            log_file.write(s)
            return len(s)

        def flush(self) -> None:
            sys.stdout.flush()
            log_file.flush()

    # Re-wrap stdout for tee (logging already configured on root handler).
    sys.stdout = _Tee()  # type: ignore[assignment]

    enlightenment_ok = await _generate_deck(
        "ENLIGHTENMENT",
        build_enlightenment_fixture(),
        include_interactive=True,
        deck_path=_ENLIGHTENMENT_DECK,
    )
    sco2_ok = await _generate_deck(
        "sCO2",
        build_sco2_source_fixture(),
        include_interactive=False,
        deck_path=_SCO2_DECK,
    )

    log_file.close()

    print()
    print("=" * 78)
    print("BUILD 1 GATE SUMMARY")
    print("=" * 78)
    print(f"  Enlightenment: {'OK' if enlightenment_ok else 'FAILED'}")
    print(f"  sCO2:          {'OK' if sco2_ok else 'FAILED'}")
    print(f"  deck dumps:    {_ENLIGHTENMENT_DECK}, {_SCO2_DECK}")
    print(f"  full log:      {_LOG_PATH}")
    print()
    if enlightenment_ok and sco2_ok:
        print("OVERALL: both decks generated end-to-end (no unhandled exception).")
        return 0
    print("OVERALL: one or both decks failed — see log above.")
    return 1


def main() -> int:
    return asyncio.run(_amain())


if __name__ == "__main__":
    sys.exit(main())
