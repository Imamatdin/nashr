"""Gate B proof — single-slide regeneration end-to-end on a real deck.

Runs the full orchestrator chain:

    load deck (or generate fresh) → re-process source → regenerate_slide → render HTML

This is a SCRIPT, not pytest (real LLM + image + render calls). Unit wiring lives
in ``tests/unit/test_presentation_orchestrator.py`` and
``tests/unit/test_editorial_pass.py``.

Run on the droplet (inside the bot container, Vertex + storage env already set):

    python scripts/proof_slide_regen.py

Options:

    --deck /app/debug/last_deck.json   load an existing DeckSpec (default)
    --generate-fresh                     generate from the sCO2 fixture instead
    --slide-id UUID                      force a target slide (default: mid-deck pick)
    --output-dir /tmp/gate_b_regen       where HTML + deck JSON land

Exit 0 when regen completes and ``SlideRegenResult.passed`` is true; 1 otherwise.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import io
import json
import logging
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, cast
from unittest.mock import MagicMock

# Karakalpak / UTF-8 consoles
for _stream in (sys.stdout, sys.stderr):
    if isinstance(_stream, io.TextIOWrapper):
        _stream.reconfigure(encoding="utf-8", errors="replace")

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from packages.bot.orchestrators.article_orchestrator import SourceProcessingResult  # noqa: E402
from packages.bot.orchestrators.presentation_orchestrator import (  # noqa: E402
    PresentationOrchestrator,
)
from packages.core.constants import image_budget_for_package  # noqa: E402
from packages.core.enums import (  # noqa: E402
    ExportFormat,
    GenerationPackage,
    SlideType,
)
from packages.core.models.presentation import (  # noqa: E402
    DeckSpec,
    SlideRegenResult,
    SlideSpec,
)
from packages.platform.config import PlatformConfig  # noqa: E402
from packages.platform.storage import FileStorage  # noqa: E402
from packages.presentation.editorial import EditorialPass  # noqa: E402
from packages.presentation.image_pass import ImagePass  # noqa: E402
from packages.workers.source.pipeline import SourcePipeline  # noqa: E402
from scripts.proof_planner_phase2 import _design, _evidence_matrix  # noqa: E402
from scripts.sco2_source_fixture import build_sco2_source_fixture  # noqa: E402

_DEFAULT_DECK_PATH = Path("/app/debug/last_deck.json")
_FULL_DECK_IMAGE_BASELINE = 4  # deck 44 full pass logged four gemini_image_generated calls

_SKIP_REGEN_TYPES = frozenset(
    {
        SlideType.TITLE_HERO,
        SlideType.SECTION_BREAK,
        SlideType.TEAM_CREDITS,
        SlideType.INTERACTIVE_QUIZ_MCQ,
        SlideType.INTERACTIVE_MATCHING,
        SlideType.INTERACTIVE_CATEGORIZE,
        SlideType.INTERACTIVE_FILL_BLANK,
        SlideType.INTERACTIVE_TRUE_FALSE,
        SlideType.INTERACTIVE_DEBATE,
    }
)

_PREFERRED_REGEN_TYPES = (
    SlideType.DATA_EMPHASIS,
    SlideType.TYPOGRAPHIC_KEYWORDS,
    SlideType.CONTENT_SPLIT,
    SlideType.CHART_DATA,
    SlideType.COMPARISON,
)


class _GeminiImageCounter(logging.Handler):
    """Count ``gemini_image_generated`` log lines during the regen image stage."""

    def __init__(self) -> None:
        super().__init__()
        self.count = 0

    def emit(self, record: logging.LogRecord) -> None:
        if record.getMessage() == "gemini_image_generated":
            self.count += 1


class _ScopedImagePass(ImagePass):
    """ImagePass that records the last ``only_slide_ids`` scope for the report."""

    def __init__(self) -> None:
        super().__init__()
        self.last_only_slide_ids: frozenset[str] | None = None
        self.last_budget: int | None = None

    async def resolve_deck(
        self,
        deck: DeckSpec,
        *,
        storage: FileStorage,
        project_id: str,
        figures: list[Any],
        max_generated_images: int | None = None,
        only_slide_ids: frozenset[str] | None = None,
    ) -> DeckSpec:
        self.last_only_slide_ids = only_slide_ids
        self.last_budget = (
            self._max_generated if max_generated_images is None else max(0, max_generated_images)
        )
        return await super().resolve_deck(
            deck,
            storage=storage,
            project_id=project_id,
            figures=figures,
            max_generated_images=max_generated_images,
            only_slide_ids=only_slide_ids,
        )


def _slide_fingerprint(slide: SlideSpec) -> str:
    """Stable content fingerprint for unchanged-slide checks (excludes slide_index)."""

    payload = {
        "slide_id": slide.slide_id,
        "slide_type": slide.slide_type.value,
        "title": slide.content.title,
        "subtitle": slide.content.subtitle,
        "body_text": slide.content.body_text,
        "bullets": slide.content.bullets,
        "stats": [
            {"value": s.value, "label": s.label, "highlight": s.highlight}
            for s in (slide.content.stats or [])
        ],
        "figure_prompt": slide.content.figure_prompt,
        "figure_url": slide.content.figure_url,
        "background_url": slide.content.background_url,
        "source_claim_ids": list(slide.source_claim_ids),
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _pick_regen_target(deck: DeckSpec, forced_id: str | None) -> SlideSpec:
    if forced_id:
        for slide in deck.slides:
            if slide.slide_id == forced_id:
                return slide
        raise SystemExit(f"--slide-id {forced_id!r} not found in deck")

    lo = len(deck.slides) // 4
    hi = (3 * len(deck.slides)) // 4
    window = deck.slides[lo:hi] if hi > lo else deck.slides

    for preferred in _PREFERRED_REGEN_TYPES:
        for slide in window:
            if slide.slide_type is preferred:
                return slide
    for slide in window:
        if slide.slide_type not in _SKIP_REGEN_TYPES:
            return slide
    for slide in deck.slides:
        if slide.slide_type not in _SKIP_REGEN_TYPES:
            return slide
    raise SystemExit("no suitable content slide to regenerate")


async def _sources_from_sco2() -> SourceProcessingResult:
    """Re-process the sCO2 regression source through the live SourcePipeline."""

    _interview, chunks, _fixture_claims, metadata = build_sco2_source_fixture()
    text = "\n\n".join(chunk.text for chunk in chunks)
    pipeline = SourcePipeline()
    parsed = await pipeline.process(text.encode("utf-8"), "sco2_gate_b_paper.txt")
    if not parsed.validation.valid:
        reason = parsed.validation.rejection_reason or "validation failed"
        raise RuntimeError(f"sCO2 source re-process rejected: {reason}")
    if not parsed.claims and not parsed.chunks:
        raise RuntimeError("sCO2 source re-process produced no claims or chunks")

    figures: list[Any] = []
    if parsed.parsed is not None:
        figures = list(parsed.parsed.figures)
    return SourceProcessingResult(
        claims=list(parsed.claims),
        chunks=list(parsed.chunks),
        metadata=list(metadata),
        figures=figures,
        warnings=list(parsed.errors),
    )


async def _load_or_generate_deck(
    deck_path: Path | None,
    *,
    generate_fresh: bool,
) -> DeckSpec:
    if generate_fresh:
        interview, chunks, claims, metadata = build_sco2_source_fixture()
        editorial = EditorialPass()
        deck = await editorial.generate_deck_spec(
            interview=interview,
            design=_design(),
            evidence_matrix=_evidence_matrix(),
            claims=claims,
            chunks=chunks,
            source_metadata=metadata,
            project_id="gate-b-fresh",
        )
        print(f"  generated fresh deck: {deck.slide_count} slides")
        return deck

    path = deck_path or _DEFAULT_DECK_PATH
    if not path.is_file():
        raise SystemExit(f"deck file not found: {path} (use --generate-fresh)")
    deck = DeckSpec.model_validate_json(path.read_text(encoding="utf-8"))
    if deck.plan is None:
        raise SystemExit(f"{path} has no persisted plan — cannot regenerate")
    print(f"  loaded deck from {path}: {deck.slide_count} slides, plan present")
    return deck


def _build_orchestrator(
    storage: FileStorage | None,
) -> tuple[PresentationOrchestrator, _ScopedImagePass]:
    bot = cast(Any, MagicMock())
    db = cast(Any, MagicMock())
    credits = cast(Any, MagicMock())
    image_pass = _ScopedImagePass()
    orch = PresentationOrchestrator(
        bot=bot,
        db=db,
        credits=credits,
        storage=storage,
        image_pass=image_pass,
    )
    return orch, image_pass


async def _noop_progress(_name: str, _step: int, _total: int) -> None:
    return None


def _print_findings(result: SlideRegenResult) -> None:
    if not result.findings:
        print("  (no findings)")
        return
    for finding in result.findings:
        sev = finding.severity.value
        print(f"  [{finding.check_id}] {finding.check_name} severity={sev} passed={finding.passed}")
        if finding.message:
            print(f"      {finding.message}")


def _verify_other_slides_unchanged(
    before: DeckSpec,
    after: DeckSpec,
    target_id: str,
) -> tuple[int, list[str]]:
    """Return (unchanged_count, list of slide_ids that changed unexpectedly)."""

    before_map = {s.slide_id: _slide_fingerprint(s) for s in before.slides}
    after_map = {s.slide_id: _slide_fingerprint(s) for s in after.slides}
    drift: list[str] = []
    unchanged = 0
    for slide_id, fp in before_map.items():
        if slide_id == target_id:
            continue
        if slide_id not in after_map:
            drift.append(f"{slide_id} (missing after regen)")
            continue
        if after_map[slide_id] != fp:
            drift.append(slide_id)
        else:
            unchanged += 1
    return unchanged, drift


async def _amain(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Gate B — single-slide regen smoke test")
    parser.add_argument("--deck", type=Path, default=None, help="DeckSpec JSON path")
    parser.add_argument(
        "--generate-fresh",
        action="store_true",
        help="Generate a new sCO2 deck instead of loading --deck",
    )
    parser.add_argument("--slide-id", default=None, help="Force target slide_id")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(tempfile.gettempdir()) / "gate_b_regen",
    )
    parser.add_argument(
        "--package",
        default=GenerationPackage.PRESENTATION_STANDARD.value,
        choices=[p.value for p in GenerationPackage if p.value.startswith("presentation_")],
    )
    args = parser.parse_args(argv)

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Set ANTHROPIC_API_KEY — regen runs real Sonnet calls.")
        return 2
    if not (
        os.environ.get("VERTEX_PROJECT")
        or os.environ.get("GOOGLE_API_KEY")
        or os.environ.get("GEMINI_API_KEY")
    ):
        print("Set VERTEX_PROJECT or GOOGLE_API_KEY — image stage needs Gemini.")
        return 2

    package = GenerationPackage(args.package)
    budget = image_budget_for_package(package)
    output_dir: Path = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 78)
    print("Gate B — single-slide regeneration (orchestrator.regenerate_slide)")
    print("=" * 78)

    print("\n[1] Deck")
    deck = await _load_or_generate_deck(args.deck, generate_fresh=args.generate_fresh)
    project_id = deck.project_id

    print("\n[2] Re-process sCO2 source (SourcePipeline → SourceProcessingResult)")
    sources = await _sources_from_sco2()
    print(
        f"  claims={len(sources.claims)} chunks={len(sources.chunks)} "
        f"figures={len(sources.figures)}"
    )

    target = _pick_regen_target(deck, args.slide_id)
    before_fp = _slide_fingerprint(target)
    print(
        f"\n[3] Target slide: id={target.slide_id} "
        f"type={target.slide_type.value} index={target.slide_index}"
    )
    print(f"    title: {target.content.title}")
    print(f"    fingerprint before: {before_fp}")

    config = PlatformConfig.from_env()
    storage: FileStorage | None
    try:
        storage = FileStorage(config)
    except Exception as exc:
        print(f"  WARNING: FileStorage unavailable ({exc}); images may abstain")
        storage = None

    orch, image_pass = _build_orchestrator(storage)

    gemini_logger = logging.getLogger("packages.core.gemini_image")
    counter = _GeminiImageCounter()
    gemini_logger.addHandler(counter)
    gemini_logger.setLevel(logging.INFO)

    print("\n[4] orchestrator.regenerate_slide …")
    try:
        new_deck, outcome = await orch.regenerate_slide(
            deck,
            target.slide_id,
            sources,
            project_id,
            _noop_progress,
            package=package,
            instruction="Strengthen the takeaway; keep every number source-grounded.",
        )
    finally:
        gemini_logger.removeHandler(counter)

    regen_slide = outcome.slide
    after_fp = _slide_fingerprint(regen_slide)
    content_changed = before_fp != after_fp

    print("\n[5] SlideRegenResult")
    print(f"  passed: {outcome.passed}")
    print(f"  findings ({len(outcome.findings)}):")
    _print_findings(outcome)

    print("\n[6] Splice + scope checks")
    print(f"  slide_id preserved: {regen_slide.slide_id == target.slide_id}")
    print(f"  slide_type preserved: {regen_slide.slide_type == target.slide_type}")
    print(f"  content fingerprint changed: {content_changed} ({before_fp} → {after_fp})")
    print(f"  new title: {regen_slide.content.title}")

    unchanged, drift = _verify_other_slides_unchanged(deck, new_deck, target.slide_id)
    other_count = len(deck.slides) - 1
    print(f"  other slides unchanged: {unchanged}/{other_count}")
    if drift:
        print(f"  UNEXPECTED DRIFT on: {', '.join(drift)}")

    scoped = image_pass.last_only_slide_ids
    print("\n[7] Image re-resolution")
    print(f"  image_budget (tier {package.value}): {budget}")
    print(f"  resolve_deck budget passed: {image_pass.last_budget}")
    print(f"  only_slide_ids: {sorted(scoped) if scoped else None}")
    print(f"  gemini_image_generated during regen: {counter.count}")
    print(f"  full-deck baseline (deck 44): {_FULL_DECK_IMAGE_BASELINE}")
    scoped_ok = scoped == frozenset({target.slide_id})
    print(f"  scoped to target only: {scoped_ok}")
    print(f"  fewer images than full pass: {counter.count < _FULL_DECK_IMAGE_BASELINE}")

    deck_out = output_dir / "deck_after_regen.json"
    deck_out.write_text(new_deck.model_dump_json(indent=2), encoding="utf-8")

    print("\n[8] Render HTML …")
    render_result = await orch.render(
        new_deck,
        [ExportFormat.HTML],
        _noop_progress,
        project_id=project_id,
    )
    html_src = render_result.html_path
    if html_src is None:
        print("  RENDER FAILED — no HTML path")
        if render_result.warnings:
            for warning in render_result.warnings:
                print(f"    warning: {warning}")
        return 1

    html_dest = output_dir / "gate_b_regen.html"
    html_dest.write_bytes(html_src.read_bytes())
    print(f"  HTML: {html_dest.resolve()}")
    print(f"  deck JSON: {deck_out.resolve()}")

    ok = (
        outcome.passed
        and regen_slide.slide_id == target.slide_id
        and content_changed
        and not drift
        and scoped_ok
        and counter.count < _FULL_DECK_IMAGE_BASELINE
    )
    print()
    if ok:
        print("OVERALL: PASS — Gate B regen chain completed; eyeball the HTML.")
        return 0
    print("OVERALL: FAIL — see checks above (regen may have run but a bar failed).")
    return 1


def main() -> int:
    return asyncio.run(_amain())


if __name__ == "__main__":
    sys.exit(main())
