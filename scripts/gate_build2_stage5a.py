"""Live droplet gate for Build 2, Stage 5a — the brain, live and working.

Extends the Stage 4 session gate by swapping the scripted stub for the REAL
Gemini tool-calling brain and exercising BOTH brain paths against real Supabase,
a real plan-bearing deck, real sources, real Sonnet/Gemini/Node calls:

  WAY 2 (conversational editing) — a real user-edit message is driven through the
  REAL :func:`presentation_flow._brain_driver` (a live GeminiBrainDriver). The
  mechanical proof: the brain CALLED ``edit_slides`` (its call turn is in the
  history), the fix routed through ``apply_fixes_and_render`` and re-delivered,
  the fix counter incremented, the download cache refreshed, AND the fix's outcome
  was fed back as an ``edit_slides`` function_response (so the next turn is
  coherent — no dangling call → no Gemini 400).

  WAY 1 (critic escalation) — a slide is planted with an ungroundable statistic and
  a C-FB hard finding; :meth:`EditorialPass._attempt_brain_grounding` runs the REAL
  escalation (brain fix pass → Sonnet regen → re-critique). The mechanical proof:
  the escalation engaged and the critic RE-RAN on the brain-fixed deck, and EITHER
  the deck came back clean (grounded → would deliver) OR a finding survived (would
  hard-stop → refund). Either way "no fabrication ships": delivery requires a clean
  re-critique, unfixable fabrication still refunds. The invariant's refund branch
  is proven deterministically in tests/unit/test_editorial_pass.py.

MECHANICAL vs EYEBALL. This gate asserts the WIRING (fired / changed / re-ran /
history / counter). Whether the brain's edit was GOOD, whether the grounding
actually improved the slide, whether the brain held its standard — that is Iko's
eyeball on the real output (Gate 5 proper, spanning 5a + 5b), and it requires the
seven prompt slots in packages/core/brain_prompts.py to be filled first.

Run on the droplet, inside the bot container (Vertex + R2 + Supabase env set,
migration 004 applied, brain prompt slots filled):

    python scripts/gate_build2_stage5a.py                  # loads /app/debug/last_deck.json
    python scripts/gate_build2_stage5a.py --generate-fresh # generates an sCO2 deck instead

Exit 0 when every check passes; 1 on any failed check or mid-run error; 2 when the
environment is not ready (missing creds/storage).
"""

from __future__ import annotations

import argparse
import asyncio
import io
import logging
import random
import sys
from pathlib import Path
from typing import Any, cast
from unittest.mock import MagicMock

for _stream in (sys.stdout, sys.stderr):
    if isinstance(_stream, io.TextIOWrapper):
        _stream.reconfigure(encoding="utf-8", errors="replace")

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import packages.bot.handlers.presentation_flow as pf  # noqa: E402
from packages.bot.handlers.presentation_flow import (  # noqa: E402
    _PROJECT_CACHE,
    _ChatOutcome,
    _run_chat_turn,
)
from packages.bot.orchestrators.presentation_orchestrator import (  # noqa: E402
    PresentationOrchestrator,
)
from packages.bot.sessions import create_session, load_session  # noqa: E402
from packages.core.enums import AuditSeverity, ExportFormat, GenerationPackage  # noqa: E402
from packages.core.models.presentation import AuditCheckResult, DeckSpec  # noqa: E402
from packages.platform.config import PlatformConfig  # noqa: E402
from packages.platform.database import DatabaseClient  # noqa: E402
from packages.platform.storage import FileStorage  # noqa: E402
from packages.presentation.editorial import EditorialPass  # noqa: E402
from scripts.gate_build2_stage0 import _cleanup, _GateReporter  # noqa: E402
from scripts.gate_build2_stage3 import _pick_two_targets, _slide_by_id  # noqa: E402
from scripts.proof_slide_regen import (  # noqa: E402
    _load_or_generate_deck,
    _slide_fingerprint,
    _sources_from_sco2,
)
from supabase import Client, create_client  # noqa: E402

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

_PACKAGE = GenerationPackage.PRESENTATION_PREMIUM
_FORMATS = [ExportFormat.HTML, ExportFormat.PPTX_EDITABLE]
_PLANTED_FABRICATION = (
    "System efficiency reached 99.97 percent across every evaluated climate zone."
)


class _EscalationWatcher(logging.Handler):
    """Captures the editorial ``brain_escalation_complete`` log WITH its evidence.

    ``recritiques`` is the real proof point: it is > 0 only when the critic actually
    RE-RAN on a brain-fixed deck. The completion line fires even when the escalation
    broke early (no fix produced/applied), so asserting on the line alone is vacuous —
    the gate asserts on ``recritiques`` instead.
    """

    def __init__(self) -> None:
        super().__init__()
        self.records: list[dict[str, Any]] = []

    def emit(self, record: logging.LogRecord) -> None:
        if record.getMessage() == "editorial_brain_escalation_complete":
            self.records.append(
                {
                    "grounded": getattr(record, "grounded", None),
                    "recritiques": getattr(record, "recritiques", 0),
                }
            )


def _edit_function_call(content: Any) -> Any:
    """The ``edit_slides`` function_call in a model turn, or None."""

    for part in content.parts or []:
        if part.function_call is not None and part.function_call.name == "edit_slides":
            return part.function_call
    return None


def _edit_function_response(content: Any) -> Any:
    """The ``edit_slides`` function_response in a turn, or None."""

    for part in content.parts or []:
        if part.function_response is not None and part.function_response.name == "edit_slides":
            return part.function_response
    return None


async def _run_gate(
    db: DatabaseClient,
    project_id: str,
    storage: FileStorage,
    *,
    generate_fresh: bool,
    deck_path: Path | None,
    reporter: _GateReporter,
) -> None:
    """Drive both brain paths on ``project_id`` against the real backends."""

    print("\n[1] Real plan-bearing deck + real sources")
    deck = await _load_or_generate_deck(deck_path, generate_fresh=generate_fresh)
    if deck.plan is None:
        raise SystemExit("loaded deck has no plan — cannot run the escalation")
    sources = await _sources_from_sco2()
    print(f"  {deck.slide_count} slides; sources figures={len(sources.figures)}")

    await db.save_deck(project_id, deck)
    await create_session(
        db, project_id=project_id, sources=sources, package=_PACKAGE, formats=_FORMATS
    )
    orch = PresentationOrchestrator(
        bot=cast(Any, MagicMock()),
        db=db,
        credits=cast(Any, MagicMock()),
        storage=storage,
    )
    targets = _pick_two_targets(deck)

    # --- WAY 2: a real user edit through the REAL brain ----------------------
    print("\n[2] WAY 2 — real brain edit turn (edit_slides → dispatch → re-deliver)")
    before_fp = _slide_fingerprint(targets[0])
    edit_text = (
        f"Please tighten and sharpen the wording on the slide titled "
        f"'{targets[0].content.title}'. Keep every claim grounded in the sources."
    )
    res = await _run_chat_turn(
        driver=pf._brain_driver(),  # the LIVE GeminiBrainDriver
        orchestrator=orch,
        db=db,
        project_id=project_id,
        user_text=edit_text,
        user_initiated=True,
    )
    reporter.check(
        "brain edit re-delivered",
        res.outcome is _ChatOutcome.REDELIVERED,
        f"outcome={res.outcome.value}",
    )
    reporter.check("download cache refreshed", "files" in _PROJECT_CACHE.get(project_id, {}))

    s1 = await load_session(db, project_id)
    assert s1 is not None
    reporter.check("fix counter incremented", s1.fixes_used == 1, f"fixes_used={s1.fixes_used}")
    reporter.check(
        "real editing spend accumulated",
        s1.accumulated_cost_usd > 0.0,
        f"cost=${s1.accumulated_cost_usd:.4f} images={s1.accumulated_image_count}",
    )
    # The brain CALLED edit_slides: its call turn precedes the fed-back result.
    called = any(_edit_function_call(c) is not None for c in s1.history if c.role == "model")
    reporter.check("brain called edit_slides", called)
    # The feed-result-back seam: the LAST turn answers that call (coherent history).
    fed_back = _edit_function_response(s1.history[-1]) if s1.history else None
    reporter.check(
        "fix outcome fed back to history",
        fed_back is not None and fed_back.response.get("delivered") is True,
    )
    after = await db.get_deck(project_id)
    assert after is not None

    after_slide = _slide_by_id(DeckSpec.model_validate(after["deck_json"]), targets[0].slide_id)
    reporter.check("deck slide regenerated", _slide_fingerprint(after_slide) != before_fp)

    # --- WAY 1: the real critic escalation on a planted fabrication -----------
    print("\n[3] WAY 1 — brain escalation on a planted ungroundable claim")
    target = targets[1]
    planted = target.model_copy(
        update={"content": target.content.model_copy(update={"body_text": _PLANTED_FABRICATION})}
    )
    slides = [planted if s.slide_id == target.slide_id else s for s in deck.slides]
    finding = AuditCheckResult(
        check_id="C-FB",
        check_name="content_critic.fabricated_data",
        passed=False,
        severity=AuditSeverity.FAIL,
        slide_index=planted.slide_index,
        slide_id=planted.slide_id,
        rule_reference="C-FB",
        message="Slide asserts '99.97 percent' efficiency, which the source does not support.",
    )
    editorial = EditorialPass()  # real Sonnet + real Gemini
    gemini = editorial._get_gemini()
    watcher = _EscalationWatcher()
    editorial_logger = logging.getLogger("packages.presentation.editorial")
    editorial_logger.addHandler(watcher)
    editorial_logger.setLevel(logging.INFO)
    try:
        grounded_slides, surviving = await editorial._attempt_brain_grounding(
            findings=[finding],
            current_slides=slides,
            interview=deck.interview,
            design=deck.design,
            plan=deck.plan,
            project_id=project_id,
            claims=sources.claims,
            gemini=gemini,
        )
    finally:
        editorial_logger.removeHandler(watcher)

    recritiques = watcher.records[-1]["recritiques"] if watcher.records else 0
    reporter.check(
        "brain escalation RE-RAN the critic on the brain-fixed deck",
        recritiques >= 1,
        f"recritiques={recritiques} (0 ⇒ brain produced/applied no fix; re-critique never ran)",
    )
    # The invariant: delivery requires a clean re-critique. Grounded → would deliver;
    # otherwise the (unchanged) hard stop fires and the deck refunds. Never ships dirty.
    if not surviving:
        reporter.check(
            "escalation GROUNDED the fabrication (would deliver clean)",
            len(grounded_slides) == len(slides),
        )
        planted_after = _slide_by_id_or_none(grounded_slides, planted.slide_id)
        reporter.check(
            "planted fabrication removed from the delivered slide",
            planted_after is not None and "99.97" not in (planted_after.content.body_text or ""),
        )
    else:
        # The brain could not ground it — the caller raises the UNCHANGED hard stop.
        reporter.check(
            "unfixable fabrication would REFUND (invariant held)",
            any(f.check_id == "C-FB" for f in surviving),
            f"surviving={[f.check_id for f in surviving]}",
        )


def _slide_by_id_or_none(slides: list[Any], slide_id: str) -> Any:
    for slide in slides:
        if slide.slide_id == slide_id:
            return slide
    return None


async def main() -> int:
    """Provision a throwaway user+project, run both brain paths, clean up, report."""

    parser = argparse.ArgumentParser(description="Build 2 Stage 5a brain gate")
    parser.add_argument("--generate-fresh", action="store_true", help="generate a fresh sCO2 deck")
    parser.add_argument("--deck", type=Path, default=Path("/app/debug/last_deck.json"))
    args = parser.parse_args()

    config = PlatformConfig.from_env()
    if not config.supabase_url or not config.supabase_service_key:
        print("ENV NOT READY: SUPABASE_URL and SUPABASE_SERVICE_KEY must be set.", file=sys.stderr)
        return 2
    try:
        storage: FileStorage | None = FileStorage(config)
    except Exception as exc:
        storage = None
        print(f"FileStorage init failed: {exc}", file=sys.stderr)
    if storage is None:
        print("ENV NOT READY: R2 storage required for scoped image re-resolution.", file=sys.stderr)
        return 2

    db = DatabaseClient(config)
    raw: Client = create_client(config.supabase_url, config.supabase_service_key)
    reporter = _GateReporter()
    user: dict[str, Any] | None = None
    try:
        user = await db.create_user(telegram_id=random.randint(10_000_000, 2_000_000_000))
        project = await db.create_project(
            user_id=user["id"],
            title="Build2 Stage5a gate",
            project_type="presentation",
            language="uz",
            audience="talaba",
        )
        print(f"Gate project: {project['id']}")
        deck_path = None if args.generate_fresh else args.deck
        await _run_gate(
            db,
            project["id"],
            storage,
            generate_fresh=args.generate_fresh,
            deck_path=deck_path,
            reporter=reporter,
        )
    finally:
        if user is not None:
            await _cleanup(raw, user["id"])
            print("Cleaned up throwaway user + cascaded project/deck/session.")

    if reporter.failures:
        print(f"\nGATE FAILED: {reporter.failures} check(s) failed.")
        return 1
    print("\nGATE PASSED: the real brain edits (Way 2) and escalates (Way 1); invariant held.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
