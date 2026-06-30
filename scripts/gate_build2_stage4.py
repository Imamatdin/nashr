"""Live droplet gate for Build 2, Stage 4 — the bot session surface.

Drives the SESSION MACHINERY (not the brain — a scripted stub stands in) against
the REAL Supabase, a REAL plan-bearing deck, REAL sources, and the REAL
orchestrator fix-chain, proving end-to-end what the unit suite cannot:

  1. FIX TURN — a stubbed fix-tool turn dispatches to apply_fixes_and_render
     ABOVE the orchestrator: the deck changes, the path-cache the download
     buttons read is refreshed, and the session persists the new history + the
     REAL editorial/image spend.
  2. APPROVAL GATE — a proposed re-delivery parks at awaiting_approval (nothing
     fires); the approve callback then fires the parked change; a second
     proposal, rejected, is discarded without firing.
  3. RESTART RECOVERY — with every in-memory pointer dropped (the FSM/caches
     wiped), the session is recovered from project_id ALONE: history, sources
     (figures byte-for-byte), deck, and spend all come back. No restart orphans
     a session.
  4. FIX COUNTER — the tier's edit allowance spent, the next FIX is refused
     pre-fire (the tool never runs) while plain chat still works.

It synthesises Stage 0's real-DB provisioning, Stage 3's real fix-chain, and the
Stage 4 session store. It is a SCRIPT, not pytest: it makes real Sonnet
(editorial regen), Gemini (scoped image), and Node (render) calls. The unit-level
wiring lives in ``tests/unit/test_brain_session.py``.

Run on the droplet, inside the bot container (Vertex + R2 + Supabase env set,
migration 004 applied):

    python scripts/gate_build2_stage4.py                 # loads /app/debug/last_deck.json
    python scripts/gate_build2_stage4.py --generate-fresh  # generates an sCO2 deck instead

Exit 0 when every check passes; 1 on any failed check or mid-run error; 2 when
the environment is not ready (missing creds/storage).
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
    _apply_pending,
    _ChatOutcome,
    _reject_pending,
    _run_chat_turn,
)
from packages.bot.orchestrators.presentation_orchestrator import (  # noqa: E402
    PresentationOrchestrator,
)
from packages.bot.sessions import (  # noqa: E402
    ApprovalState,
    create_session,
    hydrate_figures,
    load_session,
    persist_session,
)
from packages.bot.sessions.budget import session_fix_limit, session_total_spend_usd  # noqa: E402
from packages.bot.sessions.driver import ScriptedStubDriver, StubResponse  # noqa: E402
from packages.bot.sessions.models import TurnAction  # noqa: E402
from packages.core.enums import ExportFormat, GenerationPackage  # noqa: E402
from packages.core.models.presentation import DeckSpec, SlideFix  # noqa: E402
from packages.platform.config import PlatformConfig  # noqa: E402
from packages.platform.database import DatabaseClient  # noqa: E402
from packages.platform.storage import FileStorage  # noqa: E402
from scripts.gate_build2_stage0 import _cleanup, _GateReporter  # noqa: E402
from scripts.gate_build2_stage3 import (  # noqa: E402
    _GROUNDED_INSTRUCTIONS,
    _pick_two_targets,
    _slide_by_id,
)
from scripts.proof_slide_regen import (  # noqa: E402
    _GeminiImageCounter,
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


async def _run_gate(
    db: DatabaseClient,
    project_id: str,
    storage: FileStorage,
    *,
    generate_fresh: bool,
    deck_path: Path | None,
    reporter: _GateReporter,
) -> float:
    """Drive the session machinery on ``project_id``; return total USD spend."""

    print("\n[1] Real plan-bearing deck + real sources")
    deck = await _load_or_generate_deck(deck_path, generate_fresh=generate_fresh)
    if deck.plan is None:
        raise SystemExit("loaded deck has no plan — cannot regenerate")
    sources = await _sources_from_sco2()
    print(f"  {deck.slide_count} slides; sources figures={len(sources.figures)}")

    await db.save_deck(project_id, deck)
    await create_session(
        db, project_id=project_id, sources=sources, package=_PACKAGE, formats=_FORMATS
    )

    counter = _GeminiImageCounter()
    image_logger = logging.getLogger("packages.core.gemini_image")
    image_logger.addHandler(counter)
    image_logger.setLevel(logging.INFO)

    orch = PresentationOrchestrator(
        bot=cast(Any, MagicMock()),
        db=db,
        credits=cast(Any, MagicMock()),
        storage=storage,
    )
    targets = _pick_two_targets(deck)
    driver = ScriptedStubDriver()

    # --- CHECK 1: a fix turn dispatches the real chain and persists ----------
    print("\n[2] Fix turn → apply_fixes_and_render")
    before_fp = _slide_fingerprint(targets[0])
    driver.queue(
        StubResponse(
            action=TurnAction.FIX,
            fixes=(SlideFix(slide_id=targets[0].slide_id, instruction=_GROUNDED_INSTRUCTIONS),),
        )
    )
    res1 = await _run_chat_turn(
        driver=driver,
        orchestrator=orch,
        db=db,
        project_id=project_id,
        user_text="tighten it",
        user_initiated=True,
    )
    reporter.check("fix turn re-delivered", res1.outcome is _ChatOutcome.REDELIVERED)
    reporter.check("download cache refreshed", "files" in _PROJECT_CACHE.get(project_id, {}))
    s1 = await load_session(db, project_id)
    assert s1 is not None
    reporter.check("history persisted (user+model)", len(s1.history) == 2)
    reporter.check(
        "real editing spend accumulated",
        s1.accumulated_cost_usd > 0.0,
        f"cost=${s1.accumulated_cost_usd:.4f} images={s1.accumulated_image_count}",
    )
    after = await db.get_deck(project_id)
    assert after is not None
    after_slide = _slide_by_id(DeckSpec.model_validate(after["deck_json"]), targets[0].slide_id)
    reporter.check("deck slide regenerated", _slide_fingerprint(after_slide) != before_fp)

    # --- CHECK 2: the approval gate ------------------------------------------
    # A MODEL-PROPOSED re-delivery (user_initiated=False) must park at the button,
    # no matter that it is a single-slide FIX — the model cannot self-grant.
    print("\n[3] Approval gate: model-proposed change → approve, then → reject")
    driver.queue(
        StubResponse(
            action=TurnAction.FIX,
            fixes=(SlideFix(slide_id=targets[1].slide_id, instruction=_GROUNDED_INSTRUCTIONS),),
            reason="a significant re-delivery",
        )
    )
    res2 = await _run_chat_turn(
        driver=driver,
        orchestrator=orch,
        db=db,
        project_id=project_id,
        user_text="ok",
        user_initiated=False,
    )
    reporter.check(
        "model-proposed fix parks at awaiting_approval",
        res2.outcome is _ChatOutcome.AWAITING_APPROVAL,
    )
    parked = await load_session(db, project_id)
    assert parked is not None
    reporter.check(
        "pending change persisted",
        parked.approval_state is ApprovalState.AWAITING_APPROVAL
        and parked.pending_action is not None,
    )
    res_app = await _apply_pending(orchestrator=orch, db=db, project_id=project_id)
    reporter.check("approve fires the parked change", res_app.outcome is _ChatOutcome.REDELIVERED)
    cleared = await load_session(db, project_id)
    assert cleared is not None
    reporter.check(
        "gate cleared after approve",
        cleared.approval_state is ApprovalState.IDLE and cleared.pending_action is None,
    )

    driver.queue(
        StubResponse(
            action=TurnAction.FIX,
            fixes=(SlideFix(slide_id=targets[0].slide_id, instruction=_GROUNDED_INSTRUCTIONS),),
            reason="another significant change",
        )
    )
    await _run_chat_turn(
        driver=driver,
        orchestrator=orch,
        db=db,
        project_id=project_id,
        user_text="ok",
        user_initiated=False,
    )
    res_rej = await _reject_pending(db=db, project_id=project_id)
    reporter.check("reject discards the change", res_rej.outcome is _ChatOutcome.DISCARDED)
    rejected = await load_session(db, project_id)
    assert rejected is not None
    reporter.check("pending cleared after reject", rejected.pending_action is None)

    # --- CHECK 3: restart recovery by project_id ALONE -----------------------
    print("\n[4] Restart recovery: drop every in-memory pointer, recover by project_id")
    spend_before = rejected.accumulated_cost_usd
    images_before = rejected.accumulated_image_count
    _PROJECT_CACHE.clear()
    pf._SESSION_LOCKS.clear()
    recovered = await load_session(db, project_id)
    reporter.check("session recovered from project_id alone", recovered is not None)
    assert recovered is not None
    reporter.check("history recovered", len(recovered.history) >= 2)
    reporter.check("deck recovered", recovered.deck is not None)
    reporter.check(
        "spend recovered intact",
        recovered.accumulated_cost_usd == spend_before
        and recovered.accumulated_image_count == images_before,
    )
    await hydrate_figures(db, recovered)
    reporter.check(
        "sources/figures recovered byte-for-byte",
        len(recovered.sources.figures) == len(sources.figures)
        and all(
            a.data == b.data
            for a, b in zip(recovered.sources.figures, sources.figures, strict=True)
        ),
    )

    # --- CHECK 4: the fix counter refuses past the tier allowance -------------
    print("\n[5] Fix counter: spend the tier's edit allowance, confirm refusal")
    limit = session_fix_limit(_PACKAGE)
    capped = await load_session(db, project_id)
    assert capped is not None
    capped.fixes_used = limit  # the tier's edits are spent
    await persist_session(db, capped)
    driver.queue(
        StubResponse(
            action=TurnAction.FIX,
            fixes=(SlideFix(slide_id=targets[0].slide_id, instruction=_GROUNDED_INSTRUCTIONS),),
        )
    )
    res_b = await _run_chat_turn(
        driver=driver,
        orchestrator=orch,
        db=db,
        project_id=project_id,
        user_text="one more edit",
        user_initiated=True,
    )
    reporter.check(
        "fix counter refuses past the allowance", res_b.outcome is _ChatOutcome.FIXES_EXHAUSTED
    )
    # No pre-turn gate: a plain chat turn still works once the edits are spent.
    driver.queue(StubResponse(action=TurnAction.REPLY, reply_text="still chatting"))
    res_chat = await _run_chat_turn(
        driver=driver,
        orchestrator=orch,
        db=db,
        project_id=project_id,
        user_text="can I still ask things?",
        user_initiated=True,
    )
    reporter.check("chat still works after edits are spent", res_chat.outcome is _ChatOutcome.REPLY)

    final = await load_session(db, project_id)
    assert final is not None
    total = session_total_spend_usd(spend_before, images_before)
    print(f"\n  gemini images observed: {counter.count} | fixes used: {final.fixes_used}")
    return total


async def main() -> int:
    """Provision a throwaway user+project, run the gate, clean up, report."""

    parser = argparse.ArgumentParser(description="Build 2 Stage 4 session gate")
    parser.add_argument("--generate-fresh", action="store_true", help="generate a fresh sCO2 deck")
    parser.add_argument("--deck", type=Path, default=Path("/app/debug/last_deck.json"))
    args = parser.parse_args()

    config = PlatformConfig.from_env()
    if not config.supabase_url or not config.supabase_service_key:
        print("ENV NOT READY: SUPABASE_URL and SUPABASE_SERVICE_KEY must be set.", file=sys.stderr)
        return 2
    storage: FileStorage | None
    try:
        storage = FileStorage(config)
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
            title="Build2 Stage4 gate",
            project_type="presentation",
            language="uz",
            audience="talaba",
        )
        print(f"Gate project: {project['id']}")
        deck_path = None if args.generate_fresh else args.deck
        total = await _run_gate(
            db,
            project["id"],
            storage,
            generate_fresh=args.generate_fresh,
            deck_path=deck_path,
            reporter=reporter,
        )
        print(f"\nTotal session editing spend: ${total:.4f}")
    finally:
        if user is not None:
            await _cleanup(raw, user["id"])
            print("Cleaned up throwaway user + cascaded project/deck/session.")

    if reporter.failures:
        print(f"\nGATE FAILED: {reporter.failures} check(s) failed.")
        return 1
    print("\nGATE PASSED: session persists, gates, recovers by project_id, and counts edits.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
