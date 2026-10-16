"""B1-FIX4 regressions (Codex review of B1-FIX3 at 3723d30), over the 016 emulator.

CI runs this module twice: against the application as of 3723d30 (the
``prefix-3723d30`` job), where every regression must fail for the reason pinned in
``tests/prefix/unit_fix3.json``, and against the fix, where every test passes. The
tests drive only interfaces 3723d30 already had: the HTTP routes, the session
store, ``dispatch_fix`` and the job functions (the B1-FIX3 world passes the call's
identity to ``dispatch_fix`` only where it accepts one).

F2  a reader matched a session's unanswered call to the project's latest edit job
    by conversation length alone, so a replacement session's call was answered with
    the old session's receipt (and moved onto its revision);
    and nothing tied a worker's answer to the call it was queued for, so a call
    already answered was answered again;
F4  a receipt whose outer row parses but whose revision id does not reached the
    revision query and turned the chat read into a 500.

The emulator carries the fixed SQL, so F1 (an unchanged edit's hold) and F3 (the
database refusing an edit without a real session) are gated on real PostgreSQL
(tests/db/test_b1_fix4_regressions.py); the one F1 test here is coverage of the
chat view.
"""

from __future__ import annotations

import asyncio
import copy
import logging
import uuid
from typing import Any, cast

import pytest

from packages.bot.orchestrators.presentation_orchestrator import FixBatchResult
from packages.bot.sessions import create_session, load_session
from packages.bot.sessions.models import BrainSession, TurnAction, TurnOutcome
from packages.core.enums import ExportFormat, GenerationPackage
from packages.core.models.presentation import SlideFix
from packages.platform.document_models import DocumentKind
from packages.platform.document_store import DocumentStore
from packages.platform.jobs import JobQueue, JobType
from packages.sessions_core.chat import has_dangling_call, repair_dangling_call
from tests.unit.test_b1_fix3_regressions import (
    _PROJECT,  # pyright: ignore[reportPrivateUsage]
    _job,  # pyright: ignore[reportPrivateUsage]
    _Killed,  # pyright: ignore[reportPrivateUsage]
    _World,  # pyright: ignore[reportPrivateUsage]
)
from tests.unit.test_brain_session import _make_sources  # pyright: ignore[reportPrivateUsage]
from tests.unit.test_sessions_core_chat import (
    _model_turn,  # pyright: ignore[reportPrivateUsage]
    _response_payload,  # pyright: ignore[reportPrivateUsage]
    _user_turn,  # pyright: ignore[reportPrivateUsage]
)

pytestmark = pytest.mark.asyncio


class _EditTurn:
    """A brain whose every turn asks for one edit: an ``edit_slides`` call it parks."""

    async def run_turn(self, session: BrainSession, user_text: str) -> TurnOutcome:
        return TurnOutcome(
            action=TurnAction.FIX,
            history=[*session.history, _user_turn(user_text), _model_turn("", calls=1)],
            fixes=(SlideFix(slide_id="s0", instruction=user_text),),
            fix_call_count=1,
        )


class _World4(_World):
    """The B1-FIX3 world whose chat turns park an edit, as a real brain's would."""

    def __init__(self) -> None:
        super().__init__()
        app = cast(Any, self.client._transport).app  # pyright: ignore[reportPrivateUsage]
        app.state.brain_driver_factory = _EditTurn

    async def open(self) -> _World4:
        await super().open()
        return self

    async def head(self) -> str:
        found = await DocumentStore(self.db).head(_PROJECT, DocumentKind.PRESENTATION)
        assert found is not None
        return found.revision_id

    async def answers(self) -> list[dict[str, Any]]:
        session = await load_session(self.db, _PROJECT)
        assert session is not None
        return [
            _response_payload(content)
            for content in session.history
            if content.parts and content.parts[0].function_response is not None
        ]


class _CountingRunner:
    """Records whether the edit was applied at all (the LLM spend)."""

    def __init__(self) -> None:
        self.calls = 0

    async def apply_fixes(self, *_args: Any, **_kwargs: Any) -> Any:
        self.calls += 1
        raise AssertionError("the worker applied an edit for a call that was not parked")


class _SameDeck:
    """An edit whose result is the deck it was given: the commit is ``unchanged``."""

    async def apply_fixes(self, deck: Any, *_args: Any, **_kwargs: Any) -> FixBatchResult:
        return FixBatchResult(deck=deck, estimated_cost_usd=0.0, image_count=0)


def _paused_enqueue(monkeypatch: pytest.MonkeyPatch) -> tuple[asyncio.Event, asyncio.Event]:
    """Hold every edit enqueue at the barrier until released: parked, not yet queued."""

    reached, release = asyncio.Event(), asyncio.Event()
    real = JobQueue.enqueue

    async def enqueue(self: JobQueue, **kwargs: Any) -> Any:
        if kwargs.get("job_type") is JobType.PRESENTATION_EDIT:
            reached.set()
            await release.wait()
        return await real(self, **kwargs)

    monkeypatch.setattr(JobQueue, "enqueue", enqueue)
    return reached, release


# ------------------------------------------------------------------------- F2


async def test_a_replacement_sessions_call_never_adopts_the_old_sessions_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = await _World4().open()
    # Session S1 parks an edit; its worker commits it and dies before answering.
    old_job = await world.park()
    with pytest.raises(_Killed):
        await world.dispatch(old_job, "Old session's edit", kill=True)
    old_revision = await world.head()
    # A regeneration replaces S1 with S2 on that revision.
    await create_session(
        world.db,
        project_id=_PROJECT,
        sources=_make_sources(with_figure=False),
        package=GenerationPackage.PRESENTATION_PREMIUM,
        formats=[ExportFormat.HTML],
        revision_id=old_revision,
        deck=world.deck,
    )
    # S2 parks its first edit: the same conversation length S1's call had.
    reached, release = _paused_enqueue(monkeypatch)
    turn = asyncio.create_task(
        world.client.post(
            f"/projects/{_PROJECT}/chat", json={"message": "Yangi tahrir"}, headers=world.headers
        )
    )
    await asyncio.wait_for(reached.wait(), 30)

    # The recovery read, between S2's park and its enqueue (S1's job is the latest).
    during = await load_session(world.db, _PROJECT)
    assert during is not None
    assert has_dangling_call(during) == 1, "S2's call was answered from S1's job receipt"
    view = await world.chat()
    assert view["fixes_pending"] == 0 and view["fixes_used"] == 0

    release.set()
    response = await turn
    assert response.status_code == 200, response.text
    new_job = str(response.json()["job_id"])
    queued = await load_session(world.db, _PROJECT)
    assert queued is not None and has_dangling_call(queued) == 1, "answered while queued"

    # The late worker answers S2's call with S2's own edit, exactly once.
    world.db.rpc("claim_job", {"p_job_id": new_job, "p_worker_id": "w1"})
    await world.dispatch(new_job, "New session's edit")
    answers = await world.answers()
    assert len(answers) == 1, f"S2's call was answered {len(answers)} times"
    assert answers[0]["committed"] is True
    final = await load_session(world.db, _PROJECT)
    assert final is not None and final.deck is not None
    assert final.deck.title == "New session's edit"
    assert final.revision_id == await world.head() != old_revision


async def test_a_worker_never_answers_a_call_that_was_already_answered() -> None:
    world = await _World4().open()
    job_id = await world.park()
    # The call is answered elsewhere first (the dangling-call repair, here).
    session = await load_session(world.db, _PROJECT)
    assert session is not None
    await repair_dangling_call(world.db, session)
    runner = _CountingRunner()

    await world.dispatch(job_id, "Late edit", runner=runner)

    assert runner.calls == 0, "the worker applied an edit for a call that was not parked"
    answers = await world.answers()
    assert len(answers) == 1, f"the call was answered {len(answers)} times"
    assert answers[0] == {"error": "fix_failed", "detail": "edit_job_lost"}
    assert _job(world.db, job_id).get("status") == "processing", "the stale job committed"


async def test_a_second_worker_for_the_same_call_answers_nothing() -> None:
    world = await _World4().open()
    job_id = await world.park()
    await world.dispatch(job_id, "Edited")
    revisions = len(world.fake.tables["document_revisions"])
    runner = _CountingRunner()

    # The same job runs again (a retried worker): its call is answered already.
    await world.dispatch(job_id, "Edited", runner=runner)

    assert runner.calls == 0, "the worker applied an edit for a call that was not parked"
    assert len(await world.answers()) == 1, "the call was answered twice"
    assert len(world.fake.tables["document_revisions"]) == revisions


# ------------------------------------------------------------------------- F4


def _malformed_receipt(world: _World4, job_id: str) -> None:
    _job(world.db, job_id).update(
        status="committed",
        progress={"outcome": "committed", "revision_id": "not-a-uuid"},
    )


async def test_a_receipt_with_a_malformed_revision_id_is_409_job_data_invalid(
    caplog: pytest.LogCaptureFixture,
) -> None:
    world = await _World4().open()
    job_id = await world.park()
    _malformed_receipt(world, job_id)
    session_row = copy.deepcopy(world.session_row())
    job_row = copy.deepcopy(_job(world.db, job_id))

    with caplog.at_level(logging.ERROR):
        for method, body in (("GET", None), ("POST", {"message": "Salom"})):
            response = await world.client.request(
                method, f"/projects/{_PROJECT}/chat", json=body, headers=world.headers
            )
            assert response.status_code == 409, f"{method}: {response.status_code} {response.text}"
            assert response.json()["detail"] == {"reason": "job_data_invalid", "job_id": job_id}

    # Nothing was repaired or rewritten.
    assert world.session_row() == session_row
    assert _job(world.db, job_id) == job_row
    logged = [r.getMessage() for r in caplog.records if "job_data_invalid" in r.getMessage()]
    assert any(job_id in line and "revision_id" in line for line in logged), logged


@pytest.mark.parametrize(
    "progress",
    [
        {"outcome": "committed", "revision_id": None},
        {"outcome": "teleported", "revision_id": str(uuid.uuid4())},
        {"outcome": "proposed", "revision_id": 7},
    ],
    ids=["committed_without_revision", "unknown_outcome", "revision_not_a_string"],
)
async def test_other_malformed_receipts_are_409_job_data_invalid(progress: dict[str, Any]) -> None:
    world = await _World4().open()
    job_id = await world.park()
    _job(world.db, job_id).update(status="committed", progress=progress)

    response = await world.client.get(f"/projects/{_PROJECT}/chat", headers=world.headers)

    assert response.status_code == 409, response.text
    assert response.json()["detail"]["reason"] == "job_data_invalid"


# ------------------------------------------------------------------- F1 view


async def test_an_unchanged_edit_shows_no_notice_and_spends_nothing() -> None:
    world = await _World4().open()
    job_id = await world.park()

    await world.dispatch(job_id, "unused", runner=_SameDeck())  # the edit changes nothing

    view = await world.chat()
    assert (view["fixes_used"], view["fixes_pending"]) == (0, 0)
    assert [m for m in view["messages"] if m["role"] == "system"] == []
    assert await world.answers() == [{"unchanged": True}]
