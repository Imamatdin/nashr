"""Live droplet gate for Build 2, Stage 3 — the fix-and-render chain.

Drives ``PresentationOrchestrator.apply_fixes_and_render`` directly (no brain)
on a plan-bearing deck and a throwaway Supabase project, proving the batch edit
chain end-to-end:

    N slide fixes → regenerate per fix (scoped image) → persist ONCE →
    render ONCE → and the path-cache the download buttons read is REFRESHED to
    the new render (so the user's fix actually reaches them).

This synthesises Stage 0's real-DB provisioning (``gate_build2_stage0``) with
``proof_slide_regen``'s real LLM + image + render calls. It is a SCRIPT, not
pytest — it makes real Sonnet (editorial regen), Gemini (scoped image), and Node
(render) calls. The unit-level wiring lives in
``tests/unit/test_presentation_orchestrator.py``.

Run on the droplet, inside the bot container (Vertex + R2 + Supabase env set,
migration 003 applied):

    python scripts/gate_build2_stage3.py                 # loads /app/debug/last_deck.json
    python scripts/gate_build2_stage3.py --generate-fresh  # generates an sCO2 deck instead

Exit 0 when every check passes; 1 on any failed check or mid-run error; 2 when
the environment is not ready (missing creds/storage).
"""

from __future__ import annotations

import argparse
import asyncio
import io
import logging
import os
import random
import sys
from pathlib import Path
from typing import Any, cast
from unittest.mock import MagicMock

# Karakalpak / UTF-8 consoles (mirror proof_slide_regen).
for _stream in (sys.stdout, sys.stderr):
    if isinstance(_stream, io.TextIOWrapper):
        _stream.reconfigure(encoding="utf-8", errors="replace")

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from packages.bot.handlers.presentation_flow import (  # noqa: E402
    _PROJECT_CACHE,
    _register_outputs,
    _stash_outputs,
)
from packages.bot.orchestrators.presentation_orchestrator import (  # noqa: E402
    PresentationOrchestrator,
)
from packages.core.constants import image_budget_for_package  # noqa: E402
from packages.core.enums import ExportFormat, GenerationPackage  # noqa: E402
from packages.core.models.presentation import DeckSpec, SlideFix, SlideSpec  # noqa: E402
from packages.platform.config import PlatformConfig  # noqa: E402
from packages.platform.database import DatabaseClient  # noqa: E402
from packages.platform.storage import FileStorage  # noqa: E402
from packages.presentation.image_pass import ImagePass  # noqa: E402
from scripts.gate_build2_stage0 import (  # noqa: E402
    _cleanup,
    _count_deck_rows,
    _GateReporter,
)
from scripts.proof_slide_regen import (  # noqa: E402
    _SKIP_REGEN_TYPES,
    _GeminiImageCounter,
    _load_or_generate_deck,
    _slide_fingerprint,
    _sources_from_sco2,
)
from supabase import Client, create_client  # noqa: E402

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # python-dotenv is optional; env may be exported directly.
    pass

_GROUNDED_INSTRUCTIONS = (
    "Sharpen the takeaway and tighten the wording; keep every number and claim "
    "exactly as the source supports it — invent nothing."
)


class _ScopeRecordingImagePass(ImagePass):
    """Real ImagePass that records EVERY ``only_slide_ids`` scope, in order.

    ``proof_slide_regen._ScopedImagePass`` keeps only the last scope; a batch
    calls ``resolve_deck`` once per fix, so the gate needs the full list to prove
    each fix re-resolved exactly its own slide.
    """

    def __init__(self) -> None:
        super().__init__()
        self.scope_calls: list[frozenset[str] | None] = []
        self.budget_calls: list[int | None] = []

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
        self.scope_calls.append(only_slide_ids)
        self.budget_calls.append(max_generated_images)
        return await super().resolve_deck(
            deck,
            storage=storage,
            project_id=project_id,
            figures=figures,
            max_generated_images=max_generated_images,
            only_slide_ids=only_slide_ids,
        )


async def _noop_progress(_name: str, _step: int, _total: int) -> None:
    return None


def _pick_two_targets(deck: DeckSpec) -> list[SlideSpec]:
    """Pick two distinct mid-deck content slides to fix (skip title/interactive)."""

    lo = len(deck.slides) // 4
    hi = max(lo + 2, (3 * len(deck.slides)) // 4)
    ordered = deck.slides[lo:hi] + deck.slides  # window first, then whole deck as fallback
    picks: list[SlideSpec] = []
    seen: set[str] = set()
    for slide in ordered:
        if slide.slide_type in _SKIP_REGEN_TYPES or slide.slide_id in seen:
            continue
        picks.append(slide)
        seen.add(slide.slide_id)
        if len(picks) == 2:
            return picks
    raise SystemExit("deck has fewer than 2 regenerable content slides for the batch")


def _has_image(slide: SlideSpec) -> bool:
    return slide.content.figure_url is not None or slide.content.background_url is not None


def _slide_by_id(deck: DeckSpec, slide_id: str) -> SlideSpec:
    return next(s for s in deck.slides if s.slide_id == slide_id)


async def _run_gate(
    db: DatabaseClient,
    raw: Client,
    project_id: str,
    storage: FileStorage,
    *,
    generate_fresh: bool,
    deck_path: Path | None,
    package: GenerationPackage,
    formats: list[ExportFormat],
    reporter: _GateReporter,
) -> int:
    """Drive the chain on ``project_id`` and report each check. Returns image count."""

    print("\n[1] Deck (plan-bearing)")
    deck = await _load_or_generate_deck(deck_path, generate_fresh=generate_fresh)
    if deck.plan is None:  # _load_or_generate_deck guards this, belt-and-braces
        raise SystemExit("loaded deck has no plan — cannot regenerate")
    print(f"  {deck.slide_count} slides, plan present")

    print("\n[2] Re-process sCO2 source → SourceProcessingResult")
    sources = await _sources_from_sco2()
    print(
        f"  claims={len(sources.claims)} chunks={len(sources.chunks)} figures={len(sources.figures)}"
    )

    targets = _pick_two_targets(deck)
    target_ids = [t.slide_id for t in targets]
    before_titles = {t.slide_id: t.content.title for t in targets}
    before_fp = {s.slide_id: _slide_fingerprint(s) for s in deck.slides}
    print("\n[3] Batch targets (2 slides)")
    for t in targets:
        print(f"  id={t.slide_id} type={t.slide_type.value} title={t.content.title!r}")

    image_pass = _ScopeRecordingImagePass()
    orch = PresentationOrchestrator(
        bot=cast(Any, MagicMock()),
        db=db,
        credits=cast(Any, MagicMock()),
        storage=storage,
        image_pass=image_pass,
    )

    print("\n[4] Baseline: save_deck + render (pre-edit reference)")
    await db.save_deck(project_id, deck)
    baseline = await orch.render(deck, formats, _noop_progress, project_id=project_id)
    if baseline.html_path is None:
        raise SystemExit(f"baseline HTML render failed: {baseline.warnings}")
    baseline_html_path = baseline.html_path
    baseline_html_bytes = baseline_html_path.read_bytes()
    _stash_outputs(project_id, baseline)
    print(f"  baseline HTML: {baseline_html_path}")

    counter = _GeminiImageCounter()
    gemini_logger = logging.getLogger("packages.core.gemini_image")
    gemini_logger.addHandler(counter)
    gemini_logger.setLevel(logging.INFO)

    # Count chain renders without touching first-gen: wrap the instance method.
    render_calls: list[int] = []
    _orig_render = orch.render

    async def _counting_render(*args: Any, **kwargs: Any) -> Any:
        render_calls.append(1)
        return await _orig_render(*args, **kwargs)

    orch.render = _counting_render  # type: ignore[method-assign]

    fixes = [SlideFix(slide_id=sid, instruction=_GROUNDED_INSTRUCTIONS) for sid in target_ids]
    print(f"\n[5] apply_fixes_and_render — batch of {len(fixes)} fixes …")
    try:
        result = await orch.apply_fixes_and_render(
            deck,
            fixes,
            sources,
            project_id,
            formats,
            _noop_progress,
            package=package,
        )
    finally:
        gemini_logger.removeHandler(counter)

    # Re-delivery: refresh the path-cache (and registry) the bot serves from.
    _stash_outputs(project_id, result.render)
    await _register_outputs(db, project_id, result.render)

    chain_html_path = result.render.html_path
    if chain_html_path is None:
        reporter.check("chain rendered HTML", False, f"warnings={result.render.warnings}")
        return counter.count
    chain_html_bytes = chain_html_path.read_bytes()
    chain_html_text = chain_html_bytes.decode("utf-8", errors="replace")
    after_fp = {s.slide_id: _slide_fingerprint(s) for s in result.deck.slides}

    # ---- (E) render ONCE for the whole batch ---------------------------------
    reporter.check(
        "(E) batch rendered ONCE, not per-slide",
        len(render_calls) == 1,
        f"render calls={len(render_calls)}",
    )

    # ---- (A) the edits reached the rendered output ---------------------------
    # Gated signal is the content fingerprint (title/body/bullets/stats + the
    # re-resolved image urls), mirroring proof_slide_regen — NOT a title match:
    # a real regen may reword the body and leave the title, and Uzbek apostrophes
    # / HTML-escaped chars make verbatim substring matching fragile. A genuine
    # no-op regen SHOULD fail here, which a title check would miss anyway.
    reporter.check(
        "(A) chain HTML differs from baseline (edit reached the render)",
        chain_html_bytes != baseline_html_bytes,
        f"{len(baseline_html_bytes)} → {len(chain_html_bytes)} bytes",
    )
    for sid in target_ids:
        reporter.check(
            f"(A) edited slide {sid} content changed (fingerprint)",
            after_fp.get(sid) != before_fp[sid],
        )
        new_title = _slide_by_id(result.deck, sid).content.title
        print(
            f"  (A info) {sid} title {before_titles[sid]!r} → {new_title!r}; "
            f"present verbatim in HTML: {new_title in chain_html_text}"
        )

    # ---- (B) persisted deck reflects the edit, one row (upsert) --------------
    rows = await _count_deck_rows(raw, project_id)
    reporter.check(
        "(B) exactly one deck row after baseline+chain (upsert)", rows == 1, f"rows={rows}"
    )
    persisted = await db.get_deck(project_id)
    if persisted is None:
        reporter.check("(B) get_deck returns the persisted deck", False, "got None")
    else:
        restored = DeckSpec.model_validate(persisted["deck_json"])
        restored_fp = {s.slide_id: _slide_fingerprint(s) for s in restored.slides}
        reporter.check(
            "(B) persisted deck equals the chain's edited deck",
            restored_fp == after_fp,
            "fingerprints match" if restored_fp == after_fp else "DRIFT vs returned deck",
        )

    # ---- (C) the chain re-rendered to NEW files ------------------------------
    reporter.check(
        "(C) chain render path differs from baseline (fresh render)",
        chain_html_path != baseline_html_path,
        f"{baseline_html_path.name} vs {chain_html_path.name}",
    )
    reporter.check("(C) chain render file exists on disk", chain_html_path.exists())

    # ---- (D) scoped image re-resolution + drift ------------------------------
    expected_scopes = [frozenset({sid}) for sid in target_ids]
    reporter.check(
        "(D) image re-resolution scoped to each edited slide only",
        image_pass.scope_calls == expected_scopes,
        f"{[sorted(s) if s else None for s in image_pass.scope_calls]}",
    )
    changed = {sid for sid, fp in before_fp.items() if after_fp.get(sid) != fp}
    reporter.check(
        "(D) ONLY the edited slides changed (others byte-identical)",
        changed == set(target_ids),
        f"changed={sorted(changed)} expected={sorted(target_ids)}",
    )
    images_resolved = sum(1 for sid in target_ids if _has_image(_slide_by_id(result.deck, sid)))
    print(
        f"  (D soft) edited slides with a non-null image after re-resolution: "
        f"{images_resolved}/{len(target_ids)} (0 acceptable if Gemini abstained)"
    )

    # ---- (UX, decisive) the cache the download buttons read is refreshed -----
    # Assert the WHOLE map equals the WHOLE render output — every format, nothing
    # stale. _stash_outputs rebuilds the map from by_extension(), so a format that
    # failed on re-render is absent from BOTH the result and the refreshed cache
    # (the vanished-format case): no stale PPTX button can survive a re-render.
    cached = _PROJECT_CACHE.get(project_id, {}).get("files", {})
    expected_cache = {ext: str(path) for ext, path in result.render.by_extension().items()}
    reporter.check(
        "(UX) path-cache holds EXACTLY the new render's formats (no stale survivors)",
        cached == expected_cache,
        f"cache={cached} expected={expected_cache}",
    )

    return counter.count


async def main() -> int:
    parser = argparse.ArgumentParser(description="Build 2 Stage 3 — fix-and-render chain gate")
    parser.add_argument("--deck", type=Path, default=None, help="DeckSpec JSON path to load")
    parser.add_argument(
        "--generate-fresh",
        action="store_true",
        help="Generate a fresh sCO2 deck instead of loading --deck",
    )
    parser.add_argument(
        "--package",
        default=GenerationPackage.PRESENTATION_STANDARD.value,
        choices=[p.value for p in GenerationPackage if p.value.startswith("presentation_")],
    )
    args = parser.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Set ANTHROPIC_API_KEY — the editorial regen runs real Sonnet calls.")
        return 2
    if not (
        os.environ.get("VERTEX_PROJECT")
        or os.environ.get("GOOGLE_API_KEY")
        or os.environ.get("GEMINI_API_KEY")
    ):
        print(
            "Set VERTEX_PROJECT or GOOGLE_API_KEY / GEMINI_API_KEY — the image stage needs Gemini."
        )
        return 2

    config = PlatformConfig.from_env()
    if not config.supabase_url or not config.supabase_service_key:
        print(
            "Set SUPABASE_URL and SUPABASE_SERVICE_KEY — the gate exercises real save_deck/get_deck."
        )
        return 2

    storage: FileStorage | None
    try:
        storage = FileStorage(config)
    except Exception as exc:
        storage = None
        print(f"FileStorage init failed: {exc}")
    if storage is None:
        print(
            "Storage is required: scoped image re-resolution only runs when storage is configured."
        )
        return 2

    package = GenerationPackage(args.package)
    print("=" * 78)
    print("Build 2 Stage 3 gate — apply_fixes_and_render (batch fix → persist once → render once)")
    print(f"  package={package.value} image_budget={image_budget_for_package(package)} per fix")
    print("=" * 78)

    db = DatabaseClient(config)
    raw = create_client(config.supabase_url, config.supabase_service_key)
    reporter = _GateReporter()
    formats = [ExportFormat.HTML, ExportFormat.PPTX_EDITABLE]
    user: dict[str, Any] | None = None
    image_count = 0
    try:
        user = await db.create_user(telegram_id=random.randint(10_000_000, 2_000_000_000))
        project = await db.create_project(
            user_id=user["id"],
            title="Build2 Stage3 gate",
            project_type="presentation",
            language="uz",
            audience="talaba",
        )
        project_id = str(project["id"])
        print(f"Gate project: {project_id}")
        image_count = await _run_gate(
            db,
            raw,
            project_id,
            storage,
            generate_fresh=bool(args.generate_fresh),
            deck_path=args.deck,
            package=package,
            formats=formats,
            reporter=reporter,
        )
        _PROJECT_CACHE.pop(project_id, None)
    finally:
        if user is not None:
            await _cleanup(raw, user["id"])
            print("\nCleaned up throwaway user + cascaded project/deck/generated_files.")

    print(
        f"\nGemini images generated during the batch: {image_count} "
        f"(~${image_count * 0.039:.3f} at $0.039/image; plus deck-gen + 2 regen Sonnet calls)"
    )
    if reporter.failures:
        print(f"\nGATE FAILED: {reporter.failures} check(s) failed.")
        return 1
    print(
        "\nGATE PASSED: batch fix regenerated → persisted once → rendered once, "
        "and the download cache serves the updated deck."
    )
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
