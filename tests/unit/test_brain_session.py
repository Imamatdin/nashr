"""Behaviour tests for the brain editing session machinery (Build 2, Stage 4).

Drives the real machinery — the split session (de)serialization, the DB layer,
the budget cap, the approval predicate, and the chat-loop core functions — with
a scripted stub standing in for the Stage 5 brain and a fake orchestrator
standing in for the real fix-chain. The DB is the same in-memory
``FakeSupabaseClient`` the database-client tests use, so the upsert/select column
semantics (including write-once figures) are exercised, not mocked away.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from aiogram.types import CallbackQuery, Message

import packages.bot.handlers.presentation_flow as pf
from packages.bot.keyboards import presentation_chat_keyboard
from packages.bot.orchestrators.article_orchestrator import SourceProcessingResult
from packages.bot.orchestrators.presentation_orchestrator import (
    FixAndRenderResult,
    PresentationRenderResult,
)
from packages.bot.sessions import (
    ApprovalState,
    create_session,
    hydrate_figures,
    load_session,
    persist_session,
    requires_approval,
)
from packages.bot.sessions.budget import (
    SESSION_FIX_LIMITS,
    has_fixes_remaining,
    session_fix_limit,
    session_total_spend_usd,
)
from packages.bot.sessions.driver import ScriptedStubDriver, StubResponse
from packages.bot.sessions.models import (
    TurnAction,
    TurnOutcome,
)
from packages.bot.sessions.serialization import deserialize_sources, serialize_sources
from packages.bot.states import PresentationStates
from packages.core.enums import (
    AudienceType,
    ClaimStrength,
    ClaimType,
    ExportFormat,
    GenerationPackage,
)
from packages.core.gemini_image import IMAGE_COST_USD
from packages.core.models.presentation import SlideFix
from packages.core.models.source import (
    SourceChunkCreate,
    SourceClaimCreate,
    SourceFigure,
    SourceMetadataExtracted,
)
from tests.unit.test_database_client import _make_db, _make_deck, _seed_project

_RAW_PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\xff\xd8\xff\xe0JFIF"
_FORMATS = [ExportFormat.HTML, ExportFormat.PPTX_EDITABLE]


def _make_sources(*, with_figure: bool = True) -> SourceProcessingResult:
    """A realistic SourceProcessingResult with every field populated."""

    figures = (
        [
            SourceFigure(
                page_number=2,
                data=_RAW_PNG,
                content_type="image/png",
                width=800,
                height=600,
                caption="Figure 2",
                context="cooling power vs temperature",
            )
        ]
        if with_figure
        else []
    )
    return SourceProcessingResult(
        claims=[
            SourceClaimCreate(
                source_chunk_id="c1",
                project_id="proj-1",
                claim_text="Radiative cooling cut water use by 94 percent.",
                strength=ClaimStrength.STRONG,
                claim_type=ClaimType.STATISTICAL_RESULT,
            )
        ],
        chunks=[
            SourceChunkCreate(
                source_id="s1", project_id="proj-1", chunk_index=0, text="The cooler radiates."
            )
        ],
        metadata=[SourceMetadataExtracted(title="Cooling", authors=["Iko"], year=2024)],
        source_ids=[uuid4()],
        figures=figures,
        warnings=["one source skipped"],
        failed_sources=[("scan.pdf", "low confidence")],
    )


class _FakeOrchestrator:
    """Stands in for the real fix-chain; records calls and returns a fixed result.

    ``deliver=False`` simulates render() recording per-format failures and
    returning a result with ZERO output files (the partial-delivery case).
    """

    def __init__(
        self, deck: Any, *, cost: float = 0.25, images: int = 1, deliver: bool = True
    ) -> None:
        self._deck = deck
        self._cost = cost
        self._images = images
        self._deliver = deliver
        self.calls: list[dict[str, Any]] = []

    async def apply_fixes_and_render(
        self,
        deck: Any,
        fixes: Any,
        sources: SourceProcessingResult,
        project_id: str,
        formats: Any,
        progress: Any,
        *,
        package: GenerationPackage,
    ) -> FixAndRenderResult:
        del deck, progress
        self.calls.append(
            {
                "fix_count": len(list(fixes)),
                "project_id": project_id,
                "package": package,
                "figures_seen": len(sources.figures),
                "formats": list(formats),
            }
        )
        render = (
            PresentationRenderResult(html_path=Path("nashr_fake.html"))
            if self._deliver
            else PresentationRenderResult(warnings=["html: render timed out"])
        )
        return FixAndRenderResult(
            deck=self._deck,
            render=render,
            estimated_cost_usd=self._cost,
            image_count=self._images,
        )


class _RaisingOrchestrator:
    """Stands in for a fix-chain that fails — apply_fixes_and_render raises."""

    async def apply_fixes_and_render(self, *_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("editorial regen failed")


async def _provision(
    *,
    package: GenerationPackage = GenerationPackage.PRESENTATION_PREMIUM,
    with_figure: bool = True,
) -> tuple[Any, Any, Any, SourceProcessingResult]:
    """Seed project + deck, create a session, return (db, fake, deck, sources)."""

    db, fake = _make_db()
    _seed_project(fake)
    deck = _make_deck(title="Cooling", audience=AudienceType.UNDERGRADUATE)
    await db.save_deck("proj-1", deck)
    sources = _make_sources(with_figure=with_figure)
    await create_session(
        db, project_id="proj-1", sources=sources, package=package, formats=_FORMATS
    )
    return db, fake, deck, sources


# --------------------------------------------------------------- serialization


def test_sources_round_trip_through_session_jsonb_equal() -> None:
    sources = _make_sources()
    light, figures = serialize_sources(sources)
    # Prove both halves survive a real JSON encode (the jsonb column path).
    light_reloaded = json.loads(json.dumps(light))
    figures_reloaded = json.loads(json.dumps(figures))
    full = deserialize_sources(light_reloaded, figures_reloaded)
    assert full.figures[0].data == sources.figures[0].data
    assert full == sources


def test_light_deserialize_omits_figures_but_keeps_text() -> None:
    sources = _make_sources()
    light, _figures = serialize_sources(sources)
    lighted = deserialize_sources(json.loads(json.dumps(light)), None)
    assert lighted.figures == []
    assert lighted.warnings == sources.warnings
    assert lighted.claims == sources.claims


# --------------------------------------------------------------- session store


async def test_create_then_load_session_reconstructs() -> None:
    db, _fake, deck, _sources = await _provision()
    session = await load_session(db, "proj-1")
    assert session is not None
    assert session.project_id == "proj-1"
    assert session.history == []
    assert session.package is GenerationPackage.PRESENTATION_PREMIUM
    assert session.formats == _FORMATS
    assert session.approval_state is ApprovalState.IDLE
    assert session.accumulated_cost_usd == 0.0
    assert session.accumulated_image_count == 0
    assert session.deck is not None
    assert session.deck.title == deck.title
    # Light load: figures not hydrated.
    assert session.figures_loaded is False
    assert session.sources.figures == []
    # ...but the light source TEXT is present.
    assert session.sources.warnings == ["one source skipped"]


async def test_load_session_returns_none_when_absent() -> None:
    db, _fake = _make_db()
    assert await load_session(db, "ghost") is None


async def test_hydrate_figures_recovers_bytes_byte_for_byte() -> None:
    db, _fake, _deck, sources = await _provision()
    session = await load_session(db, "proj-1")
    assert session is not None
    await hydrate_figures(db, session)
    assert session.figures_loaded is True
    assert len(session.sources.figures) == 1
    assert session.sources.figures[0].data == sources.figures[0].data


async def test_persist_session_preserves_write_once_figures() -> None:
    db, _fake, _deck, sources = await _provision()
    # Light load (no figures) then persist: must NOT wipe the stored figures.
    session = await load_session(db, "proj-1")
    assert session is not None
    session.accumulated_cost_usd = 0.123
    await persist_session(db, session)
    figures_json = await db.get_brain_session_figures("proj-1")
    assert figures_json is not None and len(figures_json) == 1
    # And a fresh hydrate still recovers the original bytes.
    reloaded = await load_session(db, "proj-1")
    assert reloaded is not None
    assert reloaded.accumulated_cost_usd == 0.123
    await hydrate_figures(db, reloaded)
    assert reloaded.sources.figures[0].data == sources.figures[0].data


async def test_session_recoverable_by_project_id_after_pointer_lost() -> None:
    # The restart-survival contract: with the FSM pointer gone, the session is
    # still recoverable from project_id ALONE (its data is in the DB).
    db, _fake, deck, sources = await _provision()
    recovered = await load_session(db, "proj-1")
    assert recovered is not None
    assert recovered.deck is not None and recovered.deck.title == deck.title
    await hydrate_figures(db, recovered)
    assert recovered.sources.figures[0].data == sources.figures[0].data


# --------------------------------------------------------------- approval gate


def _outcome(action: TurnAction, *, fixes: int = 0) -> TurnOutcome:
    return TurnOutcome(
        action=action,
        history=[],
        fixes=tuple(SlideFix(slide_id=f"s{i}", instruction="x") for i in range(fixes)),
    )


def test_model_proposed_redelivery_requires_button_under_any_label_or_size() -> None:
    # The bug Codex found: a re-delivery the model emits on its OWN initiative
    # (user_initiated=False) MUST gate — regardless of how many slides it touches
    # or which label the model picks. A small batch must not slip the gate.
    for batch in (1, 2, 7):
        out = _outcome(TurnAction.FIX, fixes=batch)
        assert requires_approval(out, user_initiated=False) is True


def test_user_initiated_edit_does_not_require_button() -> None:
    out = _outcome(TurnAction.FIX, fixes=1)
    assert requires_approval(out, user_initiated=True) is False


def test_turn_action_label_alone_never_skips_the_button() -> None:
    # No value of TurnAction can authorize skipping the gate; only the code-side
    # provenance (user_initiated) can. The gate keys on bool(fixes), not action.
    for action in TurnAction:
        out = _outcome(action, fixes=1)
        assert requires_approval(out, user_initiated=False) is True


def test_pure_reply_never_gates() -> None:
    assert requires_approval(_outcome(TurnAction.REPLY), user_initiated=False) is False
    assert requires_approval(_outcome(TurnAction.FIX, fixes=0), user_initiated=False) is False


# --------------------------------------------------------------- fix counter


def test_session_fix_limits_by_tier() -> None:
    assert session_fix_limit(GenerationPackage.PRESENTATION_PREMIUM) == 3
    assert session_fix_limit(GenerationPackage.PRESENTATION_STANDARD) == 2
    assert session_fix_limit(GenerationPackage.PRESENTATION_BASIC) == 1
    assert SESSION_FIX_LIMITS[GenerationPackage.PRESENTATION_PREMIUM] == 3


def test_has_fixes_remaining_counts_down_to_the_tier_limit() -> None:
    basic = GenerationPackage.PRESENTATION_BASIC
    assert has_fixes_remaining(0, basic) is True
    assert has_fixes_remaining(1, basic) is False  # basic gets exactly one
    premium = GenerationPackage.PRESENTATION_PREMIUM
    assert has_fixes_remaining(2, premium) is True
    assert has_fixes_remaining(3, premium) is False  # premium gets exactly three


def test_total_spend_is_analytics_only_not_the_cap() -> None:
    # The actual cost is still summed for billing/analytics; it just doesn't gate.
    assert session_total_spend_usd(0.10, 3) == 0.10 + 3 * IMAGE_COST_USD


# --------------------------------------------------------------- chat loop


async def test_chat_turn_reply_persists_history() -> None:
    db, _fake, deck, _sources = await _provision()
    driver = ScriptedStubDriver()
    driver.queue(StubResponse(action=TurnAction.REPLY, reply_text="here you go"))
    orch = _FakeOrchestrator(deck)

    result = await pf._run_chat_turn(
        driver=driver,
        orchestrator=orch,
        db=db,
        project_id="proj-1",
        user_text="hi",
        user_initiated=True,
    )

    assert result.outcome is pf._ChatOutcome.REPLY
    assert result.reply_text == "here you go"
    assert orch.calls == []
    # History (user + model turn) persisted and reloadable.
    reloaded = await load_session(db, "proj-1")
    assert reloaded is not None
    assert len(reloaded.history) == 2


async def test_chat_turn_small_fix_auto_applies_and_accumulates() -> None:
    db, _fake, deck, _sources = await _provision()
    driver = ScriptedStubDriver()
    driver.queue(
        StubResponse(
            action=TurnAction.FIX,
            fixes=(SlideFix(slide_id="s0", instruction="tighten the title"),),
            estimated_cost_usd=0.05,
        )
    )
    orch = _FakeOrchestrator(deck, cost=0.25, images=1)

    # A user-directed edit (user_initiated=True) auto-applies without the button.
    result = await pf._run_chat_turn(
        driver=driver,
        orchestrator=orch,
        db=db,
        project_id="proj-1",
        user_text="fix slide",
        user_initiated=True,
    )

    assert result.outcome is pf._ChatOutcome.REDELIVERED
    assert result.slides_changed == 1
    # Tool fired once, and the figures were hydrated before grounding.
    assert len(orch.calls) == 1
    assert orch.calls[0]["figures_seen"] == 1
    reloaded = await load_session(db, "proj-1")
    assert reloaded is not None
    # The successful fix consumed exactly one edit from the counter.
    assert reloaded.fixes_used == 1
    # Actual spend is recorded for analytics (turn cost + fix LLM cost / images).
    assert reloaded.accumulated_cost_usd == 0.05 + 0.25
    assert reloaded.accumulated_image_count == 1


async def test_chat_turn_model_proposed_fix_gates_even_at_one_slide() -> None:
    # BUG 1 at the loop level: a re-delivery the model proposes on its own
    # (user_initiated=False) parks at the button, NOT auto-applied — even though
    # it is a single-slide FIX the old size/label gate would have waved through.
    db, _fake, deck, _sources = await _provision()
    driver = ScriptedStubDriver()
    driver.queue(
        StubResponse(
            action=TurnAction.FIX,
            fixes=(SlideFix(slide_id="s0", instruction="restructure"),),
            reason="I think the deck should open differently",
        )
    )
    orch = _FakeOrchestrator(deck)

    result = await pf._run_chat_turn(
        driver=driver,
        orchestrator=orch,
        db=db,
        project_id="proj-1",
        user_text="ok",
        user_initiated=False,
    )

    assert result.outcome is pf._ChatOutcome.AWAITING_APPROVAL
    assert orch.calls == []  # gated: nothing fired
    reloaded = await load_session(db, "proj-1")
    assert reloaded is not None
    assert reloaded.approval_state is ApprovalState.AWAITING_APPROVAL
    assert reloaded.pending_action is not None
    assert len(reloaded.pending_action.fixes) == 1


async def test_approve_fires_pending_and_clears_gate() -> None:
    db, _fake, deck, _sources = await _provision()
    driver = ScriptedStubDriver()
    driver.queue(
        StubResponse(
            action=TurnAction.FIX,
            fixes=(SlideFix(slide_id="s0", instruction="big change"),),
            reason="significant",
        )
    )
    orch = _FakeOrchestrator(deck, cost=0.30, images=2)
    await pf._run_chat_turn(
        driver=driver,
        orchestrator=orch,
        db=db,
        project_id="proj-1",
        user_text="ok",
        user_initiated=False,
    )
    assert orch.calls == []  # still gated (model-proposed)

    result = await pf._apply_pending(orchestrator=orch, db=db, project_id="proj-1")

    assert result.outcome is pf._ChatOutcome.REDELIVERED
    assert len(orch.calls) == 1
    reloaded = await load_session(db, "proj-1")
    assert reloaded is not None
    assert reloaded.approval_state is ApprovalState.IDLE
    assert reloaded.pending_action is None
    assert reloaded.accumulated_image_count == 2


async def test_reject_discards_pending_without_firing_tool() -> None:
    db, _fake, deck, _sources = await _provision()
    driver = ScriptedStubDriver()
    driver.queue(
        StubResponse(
            action=TurnAction.FIX,
            fixes=(SlideFix(slide_id="s0", instruction="big change"),),
            reason="significant",
        )
    )
    orch = _FakeOrchestrator(deck)
    await pf._run_chat_turn(
        driver=driver,
        orchestrator=orch,
        db=db,
        project_id="proj-1",
        user_text="ok",
        user_initiated=False,
    )

    result = await pf._reject_pending(db=db, project_id="proj-1")

    assert result.outcome is pf._ChatOutcome.DISCARDED
    assert orch.calls == []
    reloaded = await load_session(db, "proj-1")
    assert reloaded is not None
    assert reloaded.approval_state is ApprovalState.IDLE
    assert reloaded.pending_action is None


async def test_turn_still_runs_when_the_fix_allowance_is_spent() -> None:
    # No pre-TURN gate: with the fix counter spent, the user can still chat — a
    # REPLY turn runs and is answered. Only a FIX re-delivery is capped.
    db, _fake, deck, _sources = await _provision(package=GenerationPackage.PRESENTATION_BASIC)
    session = await load_session(db, "proj-1")
    assert session is not None
    session.fixes_used = 1  # basic's single edit already used
    await persist_session(db, session)

    driver = ScriptedStubDriver()
    driver.queue(StubResponse(action=TurnAction.REPLY, reply_text="still here"))
    orch = _FakeOrchestrator(deck)

    result = await pf._run_chat_turn(
        driver=driver,
        orchestrator=orch,
        db=db,
        project_id="proj-1",
        user_text="a question",
        user_initiated=True,
    )

    assert result.outcome is pf._ChatOutcome.REPLY
    assert result.reply_text == "still here"
    assert orch.calls == []


def _queue_fix(driver: ScriptedStubDriver) -> None:
    driver.queue(
        StubResponse(action=TurnAction.FIX, fixes=(SlideFix(slide_id="s0", instruction="x"),))
    )


async def test_fix_counter_refuses_once_the_tier_allowance_is_spent() -> None:
    # Basic gets exactly ONE edit: the first fix applies, the second is refused
    # PRE-fire (the tool never runs) — the count can never be exceeded.
    db, _fake, deck, _sources = await _provision(package=GenerationPackage.PRESENTATION_BASIC)
    driver = ScriptedStubDriver()
    orch = _FakeOrchestrator(deck)

    _queue_fix(driver)
    first = await pf._run_chat_turn(
        driver=driver,
        orchestrator=orch,
        db=db,
        project_id="proj-1",
        user_text="fix",
        user_initiated=True,
    )
    assert first.outcome is pf._ChatOutcome.REDELIVERED

    _queue_fix(driver)
    second = await pf._run_chat_turn(
        driver=driver,
        orchestrator=orch,
        db=db,
        project_id="proj-1",
        user_text="again",
        user_initiated=True,
    )
    assert second.outcome is pf._ChatOutcome.FIXES_EXHAUSTED
    assert second.fix_limit == 1
    assert len(orch.calls) == 1  # only the first fix ever fired
    reloaded = await load_session(db, "proj-1")
    assert reloaded is not None
    assert reloaded.fixes_used == 1


async def test_premium_allows_three_fixes_then_refuses_the_fourth() -> None:
    db, _fake, deck, _sources = await _provision(package=GenerationPackage.PRESENTATION_PREMIUM)
    driver = ScriptedStubDriver()
    orch = _FakeOrchestrator(deck)

    for _ in range(3):
        _queue_fix(driver)
        result = await pf._run_chat_turn(
            driver=driver,
            orchestrator=orch,
            db=db,
            project_id="proj-1",
            user_text="fix",
            user_initiated=True,
        )
        assert result.outcome is pf._ChatOutcome.REDELIVERED
    assert len(orch.calls) == 3

    _queue_fix(driver)
    fourth = await pf._run_chat_turn(
        driver=driver,
        orchestrator=orch,
        db=db,
        project_id="proj-1",
        user_text="fix",
        user_initiated=True,
    )
    assert fourth.outcome is pf._ChatOutcome.FIXES_EXHAUSTED
    assert len(orch.calls) == 3  # the fourth never fired
    reloaded = await load_session(db, "proj-1")
    assert reloaded is not None
    assert reloaded.fixes_used == 3


async def test_failed_fix_does_not_consume_the_counter() -> None:
    # A fix that raises (apply_fixes_and_render fails) must NOT burn an edit: the
    # counter is bumped only after success, so fixes_used stays put.
    db, _fake, _deck, _sources = await _provision(package=GenerationPackage.PRESENTATION_BASIC)
    driver = ScriptedStubDriver()
    _queue_fix(driver)
    orch = _RaisingOrchestrator()

    with pytest.raises(RuntimeError):
        await pf._run_chat_turn(
            driver=driver,
            orchestrator=orch,
            db=db,
            project_id="proj-1",
            user_text="fix",
            user_initiated=True,
        )

    reloaded = await load_session(db, "proj-1")
    assert reloaded is not None
    assert reloaded.fixes_used == 0  # the failed fix consumed nothing


async def test_zero_file_render_is_a_failed_fix_not_a_delivered_one() -> None:
    # DELIVERY BOUNDARY: apply_fixes_and_render RETURNS (no raise) with zero output
    # files when every render format fails. That is NOT a delivered fix: the count
    # must not be consumed, the user is told it failed (not "applied"), and the
    # prior good download paths are preserved (not clobbered with an empty map).
    db, _fake, deck, _sources = await _provision(package=GenerationPackage.PRESENTATION_PREMIUM)
    pf._PROJECT_CACHE["proj-1"] = {"files": {"html": "/prior/good.html"}}
    driver = ScriptedStubDriver()
    _queue_fix(driver)
    orch = _FakeOrchestrator(deck, deliver=False)  # every render format fails

    result = await pf._run_chat_turn(
        driver=driver,
        orchestrator=orch,
        db=db,
        project_id="proj-1",
        user_text="fix",
        user_initiated=True,
    )

    assert result.outcome is pf._ChatOutcome.RENDER_FAILED
    assert len(orch.calls) == 1  # the chain DID run; it just delivered nothing
    reloaded = await load_session(db, "proj-1")
    assert reloaded is not None
    assert reloaded.fixes_used == 0  # allowance intact — the fix was not delivered
    # The prior good download survived — not overwritten with an empty map.
    assert pf._PROJECT_CACHE["proj-1"]["files"] == {"html": "/prior/good.html"}
    pf._PROJECT_CACHE.clear()


# --------------------------------------------------------------- concurrency


def test_session_lock_is_per_project() -> None:
    pf._SESSION_LOCKS.clear()
    lock_p = pf._session_lock("p")
    assert pf._session_lock("p") is lock_p
    assert pf._session_lock("q") is not lock_p


async def test_session_lock_serializes_overlapping_turns() -> None:
    pf._SESSION_LOCKS.clear()
    order: list[str] = []

    async def worker(tag: str) -> None:
        async with pf._session_lock("p"):
            order.append(f"start-{tag}")
            await asyncio.sleep(0.01)
            order.append(f"end-{tag}")

    await asyncio.gather(worker("1"), worker("2"))
    # Whichever wins, the two critical sections never interleave.
    assert order in (
        ["start-1", "end-1", "start-2", "end-2"],
        ["start-2", "end-2", "start-1", "end-1"],
    )


# --------------------------------------------------------------- routing (no dead buttons)


def _callback_handler_states(name: str) -> set[str]:
    """The set of FSM state strings a named callback handler is filtered to."""

    found: set[str] = set()
    for handler in pf.router.callback_query.handlers:
        if handler.callback.__name__ != name:
            continue
        for flt in handler.filters:
            states = getattr(getattr(flt, "callback", flt), "states", None)
            if states:
                found.update(s.state for s in states)
    return found


def test_chat_keyboard_buttons_all_route_in_talking_to_brain() -> None:
    # Every button the re-delivery keyboard shows must reach a live handler in
    # talking_to_brain — and it must NOT carry the reviewing_output-only
    # regenerate button (which would re-run the whole pipeline mid-edit).
    datas = {
        b.callback_data for row in presentation_chat_keyboard("uz").inline_keyboard for b in row
    }
    assert datas == {"download_html", "download_pptx", "download_pdf", "done"}
    talking = PresentationStates.talking_to_brain.state
    for handler_name in ("send_html", "send_pptx", "send_pdf", "finish"):
        assert talking in _callback_handler_states(handler_name), handler_name


# Keep the aiogram symbols referenced so the import proves the handlers' deps
# resolve in this environment (the handlers themselves are exercised via the
# core functions above, which take no aiogram types).
assert Message is not None and CallbackQuery is not None
