"""The parked call's operation identity: enqueue refusal, merge, receipt parsing (B1-FIX4).

The regressions that prove F2/F4 existed live in test_b1_fix4_regressions.py; these
pin the rules the fix is made of, through interfaces only the fix has.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import pytest

from packages.bot.sessions import load_session
from packages.bot.sessions.receipts import EditReceipt, ReceiptOutcome, receipt_of
from packages.bot.sessions.session_rows import SessionConflictError, merge
from packages.platform.jobs import (
    EditIdentityRefusedError,
    GenerationJob,
    JobDataInvalidError,
    JobQueue,
    JobStatus,
    JobType,
)
from packages.sessions_core.chat import has_dangling_call, repair_dangling_call
from tests.unit.test_b1_fix3_regressions import (
    _PROJECT,  # pyright: ignore[reportPrivateUsage]
    _USER,  # pyright: ignore[reportPrivateUsage]
)
from tests.unit.test_b1_fix4_regressions import (
    _paused_enqueue,  # pyright: ignore[reportPrivateUsage]
    _World4,  # pyright: ignore[reportPrivateUsage]
)
from tests.unit.test_session_cas import (
    _ANSWER,  # pyright: ignore[reportPrivateUsage]
    _MODEL_TURN,  # pyright: ignore[reportPrivateUsage]
    _USER_TURN,  # pyright: ignore[reportPrivateUsage]
    _columns,  # pyright: ignore[reportPrivateUsage]
)

pytestmark = pytest.mark.asyncio

_CALL = {"role": "model", "parts": [{"function_call": {"name": "edit_slides"}}]}
_OTHER_ANSWER = {
    "role": "user",
    "parts": [{"function_response": {"name": "edit_slides", "response": {"unchanged": True}}}],
}


# ------------------------------------------------------------------- enqueue


async def test_an_edit_whose_call_is_answered_before_it_is_queued_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = await _World4().open()
    reached, release = _paused_enqueue(monkeypatch)
    turn = asyncio.create_task(
        world.client.post(
            f"/projects/{_PROJECT}/chat", json={"message": "Tahrir"}, headers=world.headers
        )
    )
    await asyncio.wait_for(reached.wait(), 30)
    # Between the park and the enqueue, something else answers the call.
    session = await load_session(world.db, _PROJECT)
    assert session is not None and has_dangling_call(session) == 1
    await repair_dangling_call(world.db, session)

    release.set()
    response = await turn

    assert response.status_code == 409, response.text
    assert response.json()["detail"] == {"reason": "session_busy", "why": "edit_operation_stale"}
    assert len(await world.answers()) == 1, "the refused edit's call was answered again"
    assert [
        job
        for job in world.fake.tables.get("generation_jobs", [])
        if job["job_type"] == "presentation_edit"
    ] == [], "an edit for an answered call was queued"


@pytest.mark.parametrize(
    "payload",
    [{}, {"session_id": str(uuid.uuid4()), "operation_id": str(uuid.uuid4())}],
    ids=["no_identity", "unknown_session"],
)
async def test_the_queue_refuses_an_edit_without_a_real_parked_call(
    payload: dict[str, Any],
) -> None:
    world = await _World4().open()

    with pytest.raises(EditIdentityRefusedError) as refused:
        await JobQueue(world.db).enqueue(
            project_id=_PROJECT,
            user_id=str(_USER),
            job_type=JobType.PRESENTATION_EDIT,
            payload=payload,
        )

    expected = "edit_identity_missing" if not payload else "edit_session_not_found"
    assert refused.value.code == expected


# --------------------------------------------------------------------- merge


async def test_a_duplicate_answer_is_dropped_and_the_next_parked_call_kept() -> None:
    first, second = str(uuid.uuid4()), str(uuid.uuid4())
    base = _columns(history_json=[_USER_TURN, _CALL], parked_operation_id=first)
    ours = _columns(
        history_json=[_USER_TURN, _CALL, _ANSWER],
        parked_operation_id=None,
        accumulated_cost_usd=0.5,
    )
    # Theirs answered the same call first, had another turn, and parked a new call.
    theirs = _columns(
        history_json=[_USER_TURN, _CALL, _OTHER_ANSWER, _USER_TURN, _CALL],
        parked_operation_id=second,
    )

    merged = merge("p", base, ours, theirs)

    assert merged["history_json"] == theirs["history_json"]
    assert merged["parked_operation_id"] == second
    assert merged["accumulated_cost_usd"] == 0.5  # the rest of our write still lands


async def test_an_answer_followed_by_a_turn_does_not_override_a_different_answer() -> None:
    parked = str(uuid.uuid4())
    base = _columns(history_json=[_USER_TURN, _CALL], parked_operation_id=parked)
    ours = _columns(
        history_json=[_USER_TURN, _CALL, _ANSWER, _USER_TURN, _MODEL_TURN],
        parked_operation_id=None,
    )
    theirs = _columns(history_json=[_USER_TURN, _CALL, _OTHER_ANSWER], parked_operation_id=None)

    with pytest.raises(SessionConflictError):
        merge("p", base, ours, theirs)


# ------------------------------------------------------------------ receipts


def _settled(progress: dict[str, Any], **payload: Any) -> GenerationJob:
    return GenerationJob(
        id="job-1",
        project_id=_PROJECT,
        job_type=JobType.PRESENTATION_EDIT,
        status=JobStatus.COMPLETED,
        payload={
            "session_id": str(uuid.uuid4()),
            "operation_id": str(uuid.uuid4()),
            "slides_changed": 2,
            **payload,
        },
        progress=progress,
    )


async def test_a_well_formed_receipt_parses_for_every_outcome() -> None:
    revision = str(uuid.uuid4())
    unchanged = receipt_of(_settled({"outcome": "unchanged", "revision_id": revision}))
    proposed = receipt_of(_settled({"outcome": "proposed", "revision_id": None}))
    committed = receipt_of(
        _settled({"outcome": "committed", "revision_id": revision, "render_job_id": "r"})
    )

    assert (unchanged.outcome, str(unchanged.revision_id)) == (ReceiptOutcome.UNCHANGED, revision)
    assert (proposed.outcome, proposed.revision_id) == (ReceiptOutcome.PROPOSED, None)
    assert isinstance(committed, EditReceipt)
    assert (committed.slides_changed, committed.rendering) == (2, True)


@pytest.mark.parametrize(
    ("progress", "payload"),
    [
        ({"outcome": "proposed", "revision_id": str(uuid.uuid4())}, {}),
        ({"outcome": "committed", "revision_id": str(uuid.uuid4())}, {"operation_id": "x"}),
        ({"outcome": "committed", "revision_id": str(uuid.uuid4())}, {"slides_changed": -1}),
    ],
    ids=["proposal_with_revision", "operation_not_uuid", "negative_slides"],
)
async def test_a_receipt_inconsistent_with_itself_is_job_data_invalid(
    progress: dict[str, Any], payload: dict[str, Any]
) -> None:
    with pytest.raises(JobDataInvalidError) as invalid:
        receipt_of(_settled(progress, **payload))
    assert invalid.value.job_id == "job-1"
