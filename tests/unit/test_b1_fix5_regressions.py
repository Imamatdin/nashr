"""B1-FIX5 regressions (Codex review of B1-FIX4 at a1b2688, B1), over the 016 emulator.

CI runs this module twice: against the application as of a1b2688 (the
``prefix-a1b2688`` job), where every regression must fail for the reason pinned in
``tests/prefix/unit_fix4.json``, and against the fix, where every test passes. The
tests drive only interfaces a1b2688 already had: the HTTP routes (a body a1b2688
ignores), the session store, ``dispatch_fix`` and the bot's callback handlers.

B1  a request whose enqueue failed answered whatever call the project had parked
    by then: request A parks O1 and stalls before its enqueue, B repairs O1, parks
    O2 and queues it; A's enqueue is refused and its cleanup answered B's O2, so
    B's own job then found nothing parked. Same with a regeneration between them.
The audit's same class: approve and reject (web and bot buttons) acted on the
decision parked now, not the one the user saw.
"""

from __future__ import annotations

import asyncio
import base64
import copy
import uuid
from typing import Any, cast

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, Chat, Message, User

from packages.bot.handlers import presentation_flow as pf
from packages.bot.sessions import create_session, load_session, persist_session
from packages.bot.sessions.driver import ScriptedStubDriver, StubResponse
from packages.bot.sessions.models import ApprovalState, PendingAction, TurnAction
from packages.bot.sessions.parked import park_call
from packages.core.enums import ExportFormat, GenerationPackage
from packages.core.models.presentation import SlideFix
from packages.platform.jobs import JobQueue, JobType
from tests.unit.test_b1_fix3_regressions import (
    _PROJECT,  # pyright: ignore[reportPrivateUsage]
)
from tests.unit.test_b1_fix4_regressions import _World4  # pyright: ignore[reportPrivateUsage]
from tests.unit.test_brain_session import (
    OWNER_TELEGRAM_ID,
    _FakeOrchestrator,  # pyright: ignore[reportPrivateUsage]
    _make_sources,  # pyright: ignore[reportPrivateUsage]
    _provision,  # pyright: ignore[reportPrivateUsage]
)
from tests.unit.test_sessions_core_chat import (
    _model_turn,  # pyright: ignore[reportPrivateUsage]
    _user_turn,  # pyright: ignore[reportPrivateUsage]
)

pytestmark = pytest.mark.asyncio


def _pause_first_edit_enqueue(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[asyncio.Event, asyncio.Event]:
    """Hold the FIRST edit enqueue (request A) until released; later ones pass."""

    reached, release = asyncio.Event(), asyncio.Event()
    real = JobQueue.enqueue
    held: list[bool] = []

    async def enqueue(self: JobQueue, **kwargs: Any) -> Any:
        if kwargs.get("job_type") is JobType.PRESENTATION_EDIT and not held:
            held.append(True)
            reached.set()
            await release.wait()
        return await real(self, **kwargs)

    monkeypatch.setattr(JobQueue, "enqueue", enqueue)
    return reached, release


async def _post(world: _World4, message: str) -> Any:
    return await world.client.post(
        f"/projects/{_PROJECT}/chat", json={"message": message}, headers=world.headers
    )


async def _b_parks_and_queues_o2(world: _World4, first: str | None) -> tuple[str, str, Any]:
    response = await _post(world, "B")
    assert response.status_code == 200, response.text
    second = world.session_row()["parked_operation_id"]
    assert second is not None and second != first, "B did not park its own call"
    return str(response.json()["job_id"]), str(second), copy.deepcopy(world.session_row())


async def _a_is_refused_and_b_is_intact(
    world: _World4, a: asyncio.Task[Any], release: asyncio.Event, second: str, b_row: Any
) -> None:
    release.set()
    refused = await a
    assert refused.status_code == 409, refused.text
    row = world.session_row()
    assert row["parked_operation_id"] == second, "A's refused enqueue answered B's call O2"
    assert row["history_json"] == b_row["history_json"], "A's cleanup wrote into B's history"
    assert row["version"] == b_row["version"], "A's cleanup wrote B's session"


async def _b_job_applies(world: _World4, b_job: str) -> None:
    world.db.rpc("claim_job", {"p_job_id": b_job, "p_worker_id": "w1"})
    await world.dispatch(b_job, "B's edit")
    answers = await world.answers()
    assert answers[-1]["committed"] is True, f"B's call was answered with {answers[-1]}"
    final = await load_session(world.db, _PROJECT)
    assert final is not None and final.deck is not None
    assert final.deck.title == "B's edit"


# ------------------------------------------------------------------------- B1


async def test_a_refused_enqueue_never_answers_the_call_parked_after_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = await _World4().open()
    reached, release = _pause_first_edit_enqueue(monkeypatch)
    a = asyncio.create_task(_post(world, "A"))
    await asyncio.wait_for(reached.wait(), 30)  # A parked O1, not yet queued
    first = world.session_row()["parked_operation_id"]

    # B finds O1 with no job, repairs it, parks O2 and queues O2's job.
    b_job, second, b_row = await _b_parks_and_queues_o2(world, first)

    await _a_is_refused_and_b_is_intact(world, a, release, second, b_row)
    await _b_job_applies(world, b_job)


async def test_a_refused_enqueue_never_answers_a_replacement_sessions_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = await _World4().open()
    reached, release = _pause_first_edit_enqueue(monkeypatch)
    a = asyncio.create_task(_post(world, "A"))
    await asyncio.wait_for(reached.wait(), 30)  # A parked O1 in S1, not yet queued
    first = world.session_row()["parked_operation_id"]
    # A regeneration replaces S1 with S2; B parks O2 in S2 and queues it.
    await create_session(
        world.db,
        project_id=_PROJECT,
        sources=_make_sources(with_figure=False),
        package=GenerationPackage.PRESENTATION_PREMIUM,
        formats=[ExportFormat.HTML],
        revision_id=await world.head(),
        deck=world.deck,
    )
    b_job, second, b_row = await _b_parks_and_queues_o2(world, first)

    await _a_is_refused_and_b_is_intact(world, a, release, second, b_row)
    await _b_job_applies(world, b_job)


# ------------------------------------------------- approve / reject (web)


async def _park_decision(world: _World4, reason: str) -> dict[str, str]:
    """A gated decision on the session, as the bot parks one: its identity."""

    session = await load_session(world.db, _PROJECT)
    assert session is not None and session.session_id is not None
    session.history = [*session.history, _user_turn(reason), _model_turn("", calls=1)]
    session.pending_action = PendingAction(
        fixes=[SlideFix(slide_id="s0", instruction=reason)], reason=reason, call_count=1
    )
    session.approval_state = ApprovalState.AWAITING_APPROVAL
    operation_id = park_call(session)
    await persist_session(world.db, session)
    return {"session_id": session.session_id, "operation_id": operation_id}


async def _decide(world: _World4, action: str, decision: dict[str, str]) -> Any:
    return await world.client.post(
        f"/projects/{_PROJECT}/chat/{action}", json=decision, headers=world.headers
    )


@pytest.mark.parametrize("action", ["approve", "reject"])
async def test_a_stale_decision_never_acts_on_the_newer_one(action: str) -> None:
    world = await _World4().open()
    first = await _park_decision(world, "first")
    assert (await _decide(world, "reject", first)).status_code == 200
    await _park_decision(world, "second")
    before = copy.deepcopy(world.session_row())

    response = await _decide(world, action, first)  # a second tab still shows "first"

    assert world.session_row() == before, f"a stale {action} changed the newer decision"
    assert world.fake.tables.get("generation_jobs", []) == [], "a job was queued"
    assert response.status_code == 409, response.text
    assert response.json()["detail"] == {"reason": "decision_changed"}


# ------------------------------------------------- approve / reject (bot)


def _short(value: str) -> str:
    return base64.urlsafe_b64encode(uuid.UUID(value).bytes).decode("ascii").rstrip("=")


def _button(prefix: str, decision: dict[str, str]) -> str:
    """The callback data the approval keyboard sent for ``decision``."""

    return f"{prefix}:{_short(decision['session_id'])}:{_short(decision['operation_id'])}"


class _Bot:
    """Stands in for the aiogram Bot; the fake orchestrator never calls it."""


async def _press(
    monkeypatch: pytest.MonkeyPatch, db: Any, data: str, orchestrator: Any, approve: bool
) -> list[str]:
    """Press an approval button through the real callback handler; the replies sent."""

    sent: list[str] = []

    async def answer_message(self: Message, text: str, **_kwargs: Any) -> None:
        sent.append(text)

    async def answer_callback(self: CallbackQuery, *_args: Any, **_kwargs: Any) -> None:
        return None

    class _Typing:
        @staticmethod
        def typing(**_kwargs: Any) -> Any:
            class _Quiet:
                async def __aenter__(self) -> None:
                    return None

                async def __aexit__(self, *_exc: object) -> None:
                    return None

            return _Quiet()

    monkeypatch.setattr(Message, "answer", answer_message)
    monkeypatch.setattr(CallbackQuery, "answer", answer_callback)
    monkeypatch.setattr(pf, "ChatActionSender", _Typing)
    monkeypatch.setattr(pf, "_orchestrator", lambda *_args, **_kwargs: orchestrator)
    user = User(id=OWNER_TELEGRAM_ID, is_bot=False, first_name="U")
    message = Message.model_construct(
        message_id=1, date=0, chat=Chat(id=OWNER_TELEGRAM_ID, type="private"), from_user=user
    )
    callback = CallbackQuery.model_construct(
        id="c", from_user=user, chat_instance="i", message=message, data=data
    )
    state = FSMContext(
        storage=MemoryStorage(),
        key=StorageKey(bot_id=1, chat_id=OWNER_TELEGRAM_ID, user_id=OWNER_TELEGRAM_ID),
    )
    await state.set_data({"project_id": "proj-1"})
    await state.set_state(pf.PresentationStates.awaiting_approval)
    if approve:
        await pf.approve_redeliver(
            callback, state, cast(Any, _Bot()), db, cast(Any, object()), None
        )
    else:
        await pf.reject_redeliver(callback, state, db)
    return sent


async def _bot_decision(db: Any, deck: Any, reason: str) -> dict[str, str]:
    driver = ScriptedStubDriver()
    driver.queue(
        StubResponse(
            action=TurnAction.FIX,
            fixes=(SlideFix(slide_id="s0", instruction=reason),),
            reason=reason,
        )
    )
    result = await pf._run_chat_turn(  # pyright: ignore[reportPrivateUsage]
        driver=driver,
        orchestrator=cast(Any, _FakeOrchestrator(deck)),
        db=db,
        project_id="proj-1",
        user_text=reason,
        user_initiated=False,
        telegram_id=OWNER_TELEGRAM_ID,
    )
    assert result.outcome is pf._ChatOutcome.AWAITING_APPROVAL  # pyright: ignore[reportPrivateUsage]
    session = await load_session(db, "proj-1")
    assert session is not None and session.session_id is not None
    assert session.parked_operation_id is not None
    return {"session_id": session.session_id, "operation_id": session.parked_operation_id}


@pytest.mark.parametrize("approve", [True, False], ids=["approve", "reject"])
async def test_an_old_bot_button_never_acts_on_the_newer_decision(
    monkeypatch: pytest.MonkeyPatch, approve: bool
) -> None:
    db, fake, deck, _sources = await _provision()
    first = await _bot_decision(db, deck, "first")
    orchestrator = _FakeOrchestrator(deck)
    await _press(monkeypatch, db, _button("rej", first), orchestrator, approve=False)
    await _bot_decision(db, deck, "second")
    [before] = copy.deepcopy(fake.tables["brain_sessions"])

    # The user taps a button on the old "first" message.
    await _press(
        monkeypatch, db, _button("apr" if approve else "rej", first), orchestrator, approve
    )

    assert orchestrator.calls == [], "an old button applied the newer decision"
    [after] = fake.tables["brain_sessions"]
    assert after == before, "an old button changed the newer decision"
