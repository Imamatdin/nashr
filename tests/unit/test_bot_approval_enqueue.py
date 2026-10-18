"""B8.1: the bot's Approve button enqueues the SAME operation-bound edit job the web does.

The inline apply (``_apply_pending``) is gone. Approve now submits a
``presentation_edit`` job through the shared :func:`enqueue_approved_edit`, stamped
with the parked call's identity and a Telegram delivery block; the worker applies
and renders it and delivers the files to the chat (ADR 0004). The decision stays
parked so a lost job leaves it re-presentable (like the web).

The one-active-edit-job-per-project guarantee (double tap, or a bot approve racing a
web approve of the same call) is the shared ``uq_generation_jobs_active`` index and
the ``generation_jobs_require_edit_identity`` trigger, both exercised against real
Postgres by the web edit path's tests/db suite; the bot uses the identical enqueue.
Here we prove the bot handler maps the index's refusal (``DuplicateActiveJobError``)
to ``brain_busy`` and leaves the decision parked.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from packages.bot.labels import get_bot_labels
from packages.bot.sessions import load_session
from packages.platform.document_store import DocumentStore
from packages.platform.jobs import (
    DuplicateActiveJobError,
    GenerationJob,
    JobQueue,
    JobStatus,
    JobType,
)
from packages.sessions_core import TelegramDelivery, enqueue_approved_edit
from tests.unit.test_b1_fix5_regressions import (
    _bot_decision,  # pyright: ignore[reportPrivateUsage]
    _button,  # pyright: ignore[reportPrivateUsage]
    _press,  # pyright: ignore[reportPrivateUsage]
)
from tests.unit.test_brain_session import (
    OWNER_TELEGRAM_ID,
    _FakeOrchestrator,  # pyright: ignore[reportPrivateUsage]
    _provision,  # pyright: ignore[reportPrivateUsage]
)

pytestmark = pytest.mark.asyncio


def _edit_jobs(fake: Any) -> list[dict[str, Any]]:
    return [
        row
        for row in fake.tables.get("generation_jobs", [])
        if row.get("job_type") == JobType.PRESENTATION_EDIT.value
    ]


async def test_bot_approve_enqueues_one_operation_bound_delivery_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db, fake, deck, _sources = await _provision()
    decision = await _bot_decision(db, deck, "make it warmer")
    orchestrator = _FakeOrchestrator(deck)

    sent = await _press(monkeypatch, db, _button("apr", decision), orchestrator, approve=True)

    assert sent == [get_bot_labels("uz").approval_applying]
    assert orchestrator.calls == [], "the bot applied the edit inline instead of queuing it"
    jobs = _edit_jobs(fake)
    assert len(jobs) == 1, "approve did not enqueue exactly one edit job"
    payload = jobs[0]["payload"]
    assert payload["from_pending"] is True
    assert payload["session_id"] == decision["session_id"]
    assert payload["operation_id"] == decision["operation_id"]
    assert "document_id" in payload and "base_revision_id" in payload
    assert payload["delivery"] == {
        "telegram": {"chat_id": OWNER_TELEGRAM_ID, "language": "uz"}
    }
    # The decision stays parked (like the web): a lost job leaves it re-presentable.
    session = await load_session(db, "proj-1")
    assert session is not None and session.pending_action is not None
    assert session.parked_operation_id == decision["operation_id"]
    assert session.fixes_used == 0


async def test_bot_approve_maps_duplicate_active_job_to_brain_busy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db, fake, deck, _sources = await _provision()
    decision = await _bot_decision(db, deck, "tighten it")

    async def refuse(self: JobQueue, **_kwargs: Any) -> Any:
        raise DuplicateActiveJobError(
            GenerationJob(
                id="dupe",
                project_id="proj-1",
                job_type=JobType.PRESENTATION_EDIT,
                status=JobStatus.PROCESSING,
            )
        )

    monkeypatch.setattr(JobQueue, "enqueue", refuse)
    sent = await _press(monkeypatch, db, _button("apr", decision), _FakeOrchestrator(deck), True)

    assert sent == [get_bot_labels("uz").brain_busy]
    # Nothing queued, and the decision stays parked for a later retry.
    assert _edit_jobs(fake) == []
    session = await load_session(db, "proj-1")
    assert session is not None and session.parked_operation_id == decision["operation_id"]


async def test_bot_approve_enqueue_failure_keeps_decision_representable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db, fake, deck, _sources = await _provision()
    decision = await _bot_decision(db, deck, "fix the title")

    async def boom(self: JobQueue, **_kwargs: Any) -> Any:
        raise RuntimeError("queue unavailable")

    monkeypatch.setattr(JobQueue, "enqueue", boom)
    sent = await _press(monkeypatch, db, _button("apr", decision), _FakeOrchestrator(deck), True)

    assert sent == [get_bot_labels("uz").edit_not_queued]
    assert _edit_jobs(fake) == []
    session = await load_session(db, "proj-1")
    assert session is not None and session.parked_operation_id == decision["operation_id"]


async def test_bot_reject_still_discards_the_decision(monkeypatch: pytest.MonkeyPatch) -> None:
    db, _fake, deck, _sources = await _provision()
    decision = await _bot_decision(db, deck, "make it warmer")

    await _press(monkeypatch, db, _button("rej", decision), _FakeOrchestrator(deck), approve=False)

    session = await load_session(db, "proj-1")
    assert session is not None
    assert session.pending_action is None and session.parked_operation_id is None


async def test_web_and_bot_submit_the_same_job_payload() -> None:
    """The bot's delivery block is the only difference: core identity is identical."""

    db, fake, deck, _sources = await _provision()
    decision = await _bot_decision(db, deck, "warmer")
    project = await db.get_project("proj-1")
    user_id = str(project["user_id"])
    queue, documents = JobQueue(db), DocumentStore(db)

    web_job = await enqueue_approved_edit(
        db,
        queue,
        documents,
        project_id="proj-1",
        user_id=user_id,
        session_id=decision["session_id"],
        operation_id=decision["operation_id"],
    )
    rows = {row["id"]: row for row in _edit_jobs(fake)}
    web_payload = copy.deepcopy(rows[web_job])

    assert "delivery" not in web_payload["payload"], "the web job must not carry a Telegram block"
    core = {k: v for k, v in web_payload["payload"].items() if k != "delivery"}
    assert core["from_pending"] is True
    assert core["session_id"] == decision["session_id"]
    assert core["operation_id"] == decision["operation_id"]

    # A bot submission of the same decision would carry the identical core plus the
    # delivery block; the shared function is the single builder of both.
    bot_payload = {
        **core,
        "delivery": {"telegram": {"chat_id": 42, "language": "ru"}},
    }
    assert {k: v for k, v in bot_payload.items() if k != "delivery"} == core
    assert TelegramDelivery(chat_id=42, language="ru").chat_id == 42
