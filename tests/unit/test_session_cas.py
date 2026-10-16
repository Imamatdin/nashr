"""Compare-and-swap session writes, their three-way merge, and receipt matching (B1-FIX3).

The regressions that prove the race existed live in test_b1_fix3_regressions.py;
these pin the rules the fix is made of.
"""

from __future__ import annotations

from typing import Any

import pytest

from packages.bot.sessions.session_rows import SessionConflictError, merge
from packages.bot.sessions.store import load_session, persist_session
from packages.platform.document_models import CommitOutcome
from packages.platform.document_store import DocumentStore
from packages.sessions_core.chat import has_dangling_call
from tests.unit.test_b1_fix3_regressions import _job, _render_succeeds, _World
from tests.unit.test_sessions_core_chat import (  # pyright: ignore[reportPrivateUsage]
    _model_turn,
    _response_payload,
    _user_turn,
)

pytestmark = pytest.mark.asyncio

_USER_TURN = {"role": "user", "parts": [{"text": "hi"}]}
_MODEL_TURN = {"role": "model", "parts": [{"text": "hello"}]}
_ANSWER = {"role": "user", "parts": [{"function_response": {"name": "edit_slides"}}]}


def _columns(**values: Any) -> dict[str, object]:
    base: dict[str, object] = {
        "history_json": [],
        "sources_json": {},
        "package": "presentation_premium",
        "formats_json": ["html"],
        "approval_state": "idle",
        "pending_action_json": None,
        "fixes_used": 0,
        "accumulated_cost_usd": 0.0,
        "accumulated_image_count": 0,
        "revision_id": "r1",
        "delivery_notes_json": [],
    }
    return {**base, **values}


async def test_merge_keeps_both_sides_changes_to_different_columns() -> None:
    base = _columns()
    ours = _columns(revision_id="r2", accumulated_cost_usd=0.5, accumulated_image_count=1)
    theirs = _columns(history_json=[_USER_TURN, _MODEL_TURN], accumulated_cost_usd=0.25)

    merged = merge("p", base, ours, theirs)

    assert merged["revision_id"] == "r2"
    assert merged["history_json"] == [_USER_TURN, _MODEL_TURN]
    assert merged["accumulated_cost_usd"] == 0.75  # both spends kept
    assert merged["accumulated_image_count"] == 1


async def test_merge_unions_delivery_notices_by_job() -> None:
    note = {"kind": "delivered", "job_id": "a", "text": "t", "history_index": 0}
    other = {**note, "job_id": "b"}
    merged = merge(
        "p",
        _columns(),
        _columns(delivery_notes_json=[note]),
        _columns(delivery_notes_json=[note, other]),
    )
    assert merged["delivery_notes_json"] == [note, other]


async def test_merge_drops_our_answer_when_theirs_already_answered_and_continued() -> None:
    call = {"role": "model", "parts": [{"function_call": {"name": "edit_slides"}}]}
    base = _columns(history_json=[_USER_TURN, call])
    ours = _columns(history_json=[_USER_TURN, call, _ANSWER])
    theirs = _columns(history_json=[_USER_TURN, call, _ANSWER, _USER_TURN, _MODEL_TURN])

    assert merge("p", base, ours, theirs)["history_json"] == theirs["history_json"]


async def test_merge_refuses_two_diverging_conversations() -> None:
    base = _columns(history_json=[_USER_TURN])
    ours = _columns(history_json=[_USER_TURN, _MODEL_TURN])
    theirs = _columns(history_json=[_USER_TURN, {"role": "model", "parts": [{"text": "x"}]}])

    with pytest.raises(SessionConflictError):
        merge("p", base, ours, theirs)


async def test_a_stale_write_merges_instead_of_overwriting() -> None:
    world = await _World().open()
    stale = await load_session(world.db, "proj-1")
    fresh = await load_session(world.db, "proj-1")
    assert stale is not None and fresh is not None
    fresh.history = [*fresh.history, _user_turn("savol"), _model_turn("javob")]
    await persist_session(world.db, fresh)

    stale.accumulated_cost_usd += 0.5
    await persist_session(world.db, stale)

    final = await load_session(world.db, "proj-1")
    assert final is not None
    assert [c.parts[0].text for c in final.history if c.parts] == ["savol", "javob"]
    assert final.accumulated_cost_usd == pytest.approx(0.5)
    assert stale.history == final.history  # the writer now mirrors the merged row
    assert world.session_row()["version"] == 2


async def test_two_writers_extending_the_conversation_differently_conflict() -> None:
    world = await _World().open()
    first = await load_session(world.db, "proj-1")
    second = await load_session(world.db, "proj-1")
    assert first is not None and second is not None
    first.history = [*first.history, _user_turn("a")]
    await persist_session(world.db, first)
    second.history = [*second.history, _user_turn("b")]

    with pytest.raises(SessionConflictError):
        await persist_session(world.db, second)
    final = await load_session(world.db, "proj-1")
    assert final is not None and [c.parts[0].text for c in final.history if c.parts] == ["a"]


async def test_a_receipt_from_another_parked_call_is_not_used() -> None:
    world = await _World().open()
    job_id = await world.park()
    await world.dispatch(job_id, "Edited")  # answers normally
    second = await world.park()
    _job(world.db, second).update(status="failed")  # died without a receipt
    # The first call's settled job is the project's latest edit; it is still not
    # this call's (B1-FIX4: matched by session and operation, never recency).
    _job(world.db, job_id)["created_at"] = "2099-01-01T00:00:00+00:00"

    session = await load_session(world.db, "proj-1")
    assert session is not None and has_dangling_call(session) == 1


async def test_a_worker_finishing_after_a_turn_recovered_its_answer_keeps_the_turn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = await _World(replies=["Mana."]).open()
    job_id = await world.park()
    real_finish = DocumentStore.finish_generation_job

    async def finish_then_turn(self: DocumentStore, **kwargs: Any) -> CommitOutcome:
        # The worker committed; a turn runs (recovering the answer from the job's
        # receipt) before the worker's own answer is saved.
        outcome = await real_finish(self, **kwargs)
        response = await world.client.post(
            "/projects/proj-1/chat", json={"message": "Yana"}, headers=world.headers
        )
        assert response.status_code == 200, response.text
        return outcome

    monkeypatch.setattr(DocumentStore, "finish_generation_job", finish_then_turn)
    await world.dispatch(job_id, "Edited")
    monkeypatch.undo()
    await _render_succeeds(world.db, _job(world.db, job_id)["render_job_id"])

    session = await load_session(world.db, "proj-1")
    assert session is not None and has_dangling_call(session) == 0
    answers = [c for c in session.history if c.parts and c.parts[0].function_response]
    assert len(answers) == 1 and _response_payload(answers[0])["committed"] is True
    texts = [p.text for c in session.history for p in (c.parts or []) if p.text]
    assert texts[-2:] == ["Yana", "Mana."]
    assert session.fixes_used == 1
