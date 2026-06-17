"""GATE A — live sCO2 generation proving the EXECUTOR authors slide emphasis.

Part A makes table/stat emphasis a first-class signal that the editorial EXECUTOR
authors as it writes each slide (table_preferred_column, table_hero_row, the hero
StatItem.highlight), with :mod:`packages.presentation.emphasis` as a last-resort
fallback. Because the emphasis is now LLM-authored, the contract gate is a LIVE
run, not a static dump: this script runs the full pipeline on the sCO2 fixture,
dumps the deck plus an emphasis-provenance sidecar, and proves — per field —
that the executor (not the fallback) set it.

THE GATE
--------
* Headline number: emphasis fields authored by the EXECUTOR vs filled by the
  FALLBACK. A non-zero fallback count on a table/stat slide means the executor
  prompt did not take — that is FIX-BEFORE-ENGINE, not a pass.
* Every table_compact slide with a clear subject must carry an EXECUTOR-authored
  table_preferred_column (the sCO2 column for this source).
* Every data_emphasis slide must carry exactly one EXECUTOR-authored highlighted
  stat.
* section_thesis must be present (source = plan) on the table/stat slides.

Special attention: a table whose own title omits "sCO₂" still must get the right
column — proving the executor reasoned from the deck subtitle / section thesis,
not from string-matching its own title.

Run from the repo root, with live creds (Vertex):

    set ANTHROPIC_API_KEY=...      # Sonnet — planner + editorial executor
    set VERTEX_PROJECT=...         # Vertex AI + ADC (gcloud auth ... login)
    # or, for AI Studio instead of Vertex: set GOOGLE_API_KEY=...
    python scripts/gate_a_emphasis_provenance.py

Exit 0 iff the gate passes; 1 on a gate failure; 2 if creds are missing.
"""

from __future__ import annotations

import asyncio
import io
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

# sCO2 slide titles carry subscript "₂"; force UTF-8 like the Phase 2 harness.
for _stream in (sys.stdout, sys.stderr):
    if isinstance(_stream, io.TextIOWrapper):
        _stream.reconfigure(encoding="utf-8", errors="replace")

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from packages.core.enums import BackgroundTreatment, PresentationMood, SlideType  # noqa: E402
from packages.core.models.evidence import EvidenceMatrix  # noqa: E402
from packages.core.models.presentation import (  # noqa: E402
    ColorPalette,
    DeckSpec,
    DesignDirectionSpec,
)
from packages.presentation.editorial import (  # noqa: E402
    EditorialDeckPlanMismatchError,
    EditorialPass,
    EditorialPlanRejectedError,
)
from packages.presentation.emphasis import EmphasisProvenance, EmphasisSource  # noqa: E402
from packages.presentation.planner import PlannerError  # noqa: E402
from packages.presentation.thesis_classifier import ThesisClassifierError  # noqa: E402
from scripts.sco2_source_fixture import build_sco2_source_fixture  # noqa: E402

_DEBUG_DIR = _REPO_ROOT / "debug"
_DECK_PATH = _DEBUG_DIR / "last_deck.json"
_PROV_PATH = _DEBUG_DIR / "last_deck.emphasis_provenance.json"


def _design() -> DesignDirectionSpec:
    """A valid DesignDirectionSpec (editorial ``del``s design; values don't
    affect slide output, this just satisfies the signature without a design LLM
    call)."""

    return DesignDirectionSpec(
        mood=PresentationMood.BOLD_TECHNICAL,
        palette=ColorPalette(
            background="#0A1520",
            surface="#112030",
            text="#E8F0F5",
            accent="#FF6B2B",
            text_secondary="#7AAFC4",
        ),
        heading_font="Space Grotesk",
        body_font="Inter",
        decorative_font=None,
        image_style_prefix="industrial photography, cool slate and teal tones",
        background_treatment=BackgroundTreatment.DARK,
    )


def _evidence_matrix() -> EvidenceMatrix:
    return EvidenceMatrix(project_id=uuid4(), created_at=datetime.now(UTC))


def _src(value: EmphasisSource | None) -> str:
    return value.value if value is not None else "—"


def _report(deck: DeckSpec, prov: EmphasisProvenance) -> int:
    """Print per-slide emphasis + provenance, compute PASS/FAIL."""

    print("=" * 78)
    print("GATE A — emphasis provenance on a LIVE sCO2 generation")
    print("=" * 78)
    print(f"  deck.title:    {deck.title}")
    print(f"  deck.subtitle: {deck.subtitle}")
    print(
        f"  HEADLINE: emphasis authored by EXECUTOR = {prov.executor_count}  |  "
        f"filled by FALLBACK = {prov.fallback_count}  |  "
        f"EXECUTOR out-of-range = {prov.invalid_count}"
    )
    print()

    table_ok = True
    data_ok = True
    saw_table = False
    saw_data = False

    by_index = {p.slide_index: p for p in prov.slides}
    for slide in deck.slides:
        p = by_index.get(slide.slide_index)
        if p is None:
            continue
        content = slide.content
        if slide.slide_type is SlideType.TABLE_COMPACT and content.table_headers:
            saw_table = True
            headers = content.table_headers
            col = content.table_preferred_column
            chosen = headers[col] if (col is not None and col < len(headers)) else "(none)"
            print(f"  [TABLE]  idx {slide.slide_index}: {content.title}")
            print(f"           headers: {headers}")
            print(
                f"           preferred_column = {col} -> '{chosen}' "
                f"[{_src(p.table_preferred_column)}]   "
                f"hero_row = {content.table_hero_row} [{_src(p.table_hero_row)}]   "
                f"section_thesis [{_src(p.section_thesis)}]"
            )
            if p.table_preferred_column is not EmphasisSource.EXECUTOR:
                table_ok = False
            if p.section_thesis is not EmphasisSource.PLAN:
                table_ok = False
            print()
        elif slide.slide_type is SlideType.DATA_EMPHASIS and content.stats:
            saw_data = True
            highlighted = [i for i, s in enumerate(content.stats) if s.highlight]
            lead = content.stats[highlighted[0]] if highlighted else None
            lead_text = f"{lead.value} {lead.unit} ({lead.label})" if lead else "(none)"
            print(f"  [DATA]   idx {slide.slide_index}: {content.title}")
            print(
                f"           highlighted stat = {highlighted} -> {lead_text} "
                f"[{_src(p.hero_stat)}]   section_thesis [{_src(p.section_thesis)}]"
            )
            if p.hero_stat is not EmphasisSource.EXECUTOR or len(highlighted) != 1:
                data_ok = False
            print()

    print("-" * 78)
    checks = {
        "a table_compact slide was generated": saw_table,
        "a data_emphasis slide was generated": saw_data,
        "every table preferred_column authored by EXECUTOR (+ section_thesis from plan)": table_ok,
        "every data_emphasis has exactly ONE EXECUTOR-authored highlight": data_ok,
        "no emphasis field needed the FALLBACK": prov.fallback_count == 0,
        "no EXECUTOR emphasis index was out of range": prov.invalid_count == 0,
    }
    for label, ok in checks.items():
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    passed = all(checks.values())
    print()
    print(f"  deck written to:       {_DECK_PATH}")
    print(f"  provenance written to: {_PROV_PATH}")
    print()
    print(f"OVERALL: {'PASS' if passed else 'FAIL'}")
    return 0 if passed else 1


async def _amain() -> int:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Set ANTHROPIC_API_KEY — the planner and editorial executor run real Sonnet calls.")
        return 2
    if not (
        os.environ.get("VERTEX_PROJECT")
        or os.environ.get("GOOGLE_API_KEY")
        or os.environ.get("GEMINI_API_KEY")
    ):
        print(
            "Set VERTEX_PROJECT (Vertex AI + ADC) — or GOOGLE_API_KEY / GEMINI_API_KEY for AI "
            "Studio. Gemini runs the thesis classifier."
        )
        return 2

    interview, chunks, claims, metadata = build_sco2_source_fixture()
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
    except (
        PlannerError,
        ThesisClassifierError,
        EditorialPlanRejectedError,
        EditorialDeckPlanMismatchError,
    ) as exc:
        print(f"generate_deck_spec raised: {type(exc).__name__}: {exc}")
        return 1

    provenance = editorial.last_emphasis_provenance
    if provenance is None:
        print("FAIL: editorial did not record emphasis provenance.")
        return 1

    _DEBUG_DIR.mkdir(exist_ok=True)
    _DECK_PATH.write_text(
        json.dumps(deck.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    _PROV_PATH.write_text(
        json.dumps(provenance.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return _report(deck, provenance)


def main() -> int:
    return asyncio.run(_amain())


if __name__ == "__main__":
    sys.exit(main())
