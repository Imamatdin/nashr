"""Asynchronous delivery of queued AI edits and paid jobs (B1-FIX2), over the 016 emulator.

A queued edit commits with its job, which stays ``committed`` while the render the
commit queued publishes the exports. Its edit_deliveries row holds one fix until
that render settles the job: delivered, the fix is counted and the chat says the
edit is ready; failed for good, the hold is released (the allowance is restored)
and the chat says so in the deck's language. The real-PostgreSQL versions of the
database half live in ``tests/db/test_b1_fix2_regressions.py`` and
``tests/db/test_b1_fix3_regressions.py``.
"""

from __future__ import annotations

import uuid
from typing import Any, cast

import pytest

from packages.bot.sessions.budget import session_fix_limit
from packages.bot.sessions.delivery import delivery_note_text, visible_notes
from packages.bot.sessions.models import DeliveryNoteKind
from packages.bot.sessions.store import load_session, persist_session
from packages.core.enums import Language
from packages.core.models.presentation import SlideFix
from packages.platform.database import DatabaseClient
from packages.platform.document_models import RevisionKind
from packages.platform.document_store import DocumentStore
from packages.platform.jobs import JobStatus
from packages.sessions_core.apply import FixStatus
from packages.sessions_core.chat import dispatch_fix, history_for_wire
from tests.unit.test_brain_session import _provision  # pyright: ignore[reportPrivateUsage]
from tests.unit.test_sessions_core_chat import (  # pyright: ignore[reportPrivateUsage]
    _FakeOrchestrator,
    _park_a_dangling_call,
    _progress,
    _response_payload,
    _session,
)

_VERSION = "pw-test"


def _tables(db: DatabaseClient) -> dict[str, list[dict[str, Any]]]:
    return db._client.tables  # pyright: ignore[reportPrivateUsage]


def _job(db: DatabaseClient, job_id: str) -> dict[str, Any]:
    return next(row for row in _tables(db)["generation_jobs"] if row["id"] == job_id)


async def _rpc(db: DatabaseClient, fn: str, params: dict[str, Any]) -> Any:
    return db.rpc(fn, params).data


async def _queued_edit(
    db: DatabaseClient, deck: Any, *, attempts: int = 2, title_slide: str = "s0"
) -> tuple[Any, str]:
    """Run one parked edit the way the worker does: finish with the job, deliver=None."""

    job_id = str(uuid.uuid4())
    _tables(db).setdefault("generation_jobs", []).append(
        {
            "id": job_id,
            "project_id": "proj-1",
            "user_id": "u1",
            "job_type": "presentation_edit",
            "status": "processing",
            "worker_id": "w1",
            "attempts": 1,
            "max_attempts": 1,
            # As the chat route stamps it (B1-FIX3).
            "payload": {"slides_changed": 1},
            "progress": {},
            "heartbeat_at": "2026-01-01T00:00:00+00:00",
        }
    )
    session = await _session(db)
    store = DocumentStore(db)

    async def commit(edited: Any, base: str | None) -> Any:
        return await store.finish_generation_job(
            job_id=job_id,
            worker_id="w1",
            claim_token=1,
            base_revision_id=base,
            content=edited.model_dump(mode="json"),
            kind=RevisionKind.AI_EDIT,
            idempotency_key=f"chat-edit:{job_id}",
            renderer_version=_VERSION,
            render_formats=["html", "pdf"],
            render_max_attempts=attempts,
        )

    result = await dispatch_fix(
        runner=cast(Any, _FakeOrchestrator(deck, images=1)),
        db=db,
        project_id="proj-1",
        fixes=[SlideFix(slide_id=title_slide, instruction="tighten")],
        call_count=1,
        progress=_progress(),
        base_revision_id=str(session.revision_id),
        commit=commit,
        deliver=None,
        delivery_job_id=job_id,
    )
    return result, job_id


def _register(db: DatabaseClient, render: dict[str, Any]) -> None:
    """The exports a successful render registered (rows as register_export writes them)."""

    payload = render["payload"]
    for fmt in payload["formats"]:
        _tables(db).setdefault("revision_exports", []).append(
            {
                "revision_id": payload["revision_id"],
                "format": fmt,
                "renderer_version": payload["renderer_version"],
                "storage_key": f"exports/d/{payload['revision_id']}/{_VERSION}/{fmt}/k.{fmt}",
                "sha256": "a" * 64,
                "byte_size": 1,
                "page_count": None,
                "created_by_job": render["id"],
                "created_at": "2026-01-01T00:00:00+00:00",
            }
        )


async def _claim(db: DatabaseClient, render_id: str, worker: str) -> int:
    [claimed] = await _rpc(db, "claim_job", {"p_job_id": render_id, "p_worker_id": worker})
    return int(claimed["attempts"])


async def _render_succeeds(db: DatabaseClient, render_id: str) -> None:
    token = await _claim(db, render_id, "r1")
    _register(db, _job(db, render_id))
    done = await _rpc(
        db,
        "complete_job",
        {"p_job_id": render_id, "p_worker_id": "r1", "p_claim_token": token, "p_progress": {}},
    )
    assert done is True


async def _render_fails(db: DatabaseClient, render_id: str) -> None:
    token = await _claim(db, render_id, "r1")
    failed = await _rpc(
        db,
        "fail_job",
        {
            "p_job_id": render_id,
            "p_worker_id": "r1",
            "p_claim_token": token,
            "p_step": "render",
            "p_message": "chromium crashed",
        },
    )
    assert failed is True


# ------------------------------------------------------------ the held fix


async def test_a_committed_edit_holds_a_fix_but_is_not_counted_until_published() -> None:
    db, _fake, deck, _sources = await _provision()
    await _park_a_dangling_call(db)

    result, job_id = await _queued_edit(db, deck)

    assert result.status is FixStatus.COMMITTED and result.delivered is False
    job = _job(db, job_id)
    assert job["status"] == "committed" and job["render_job_id"] is not None
    session = await _session(db)
    assert session.fixes_used == 0
    assert [p.job_id for p in session.pending_deliveries] == [job_id]
    # The model is told the edit is rendering, not that it was delivered.
    answer = _response_payload(session.history[-1])
    assert answer["committed"] is True and answer["delivery"] == "rendering"
    assert "delivered" not in answer


async def test_published_edit_is_counted_once_and_the_chat_says_it_is_ready() -> None:
    db, _fake, deck, _sources = await _provision()
    await _park_a_dangling_call(db)
    _result, job_id = await _queued_edit(db, deck)

    await _render_succeeds(db, _job(db, job_id)["render_job_id"])

    assert _job(db, job_id)["status"] == "completed"  # settled by complete_job itself
    session = await load_session(db, "proj-1")
    assert session is not None
    assert session.fixes_used == 1 and session.pending_deliveries == []
    expected = delivery_note_text(deck.language, DeliveryNoteKind.DELIVERED, 1)
    assert [note.text for note in visible_notes(session)] == [expected]
    assert history_for_wire(session)[-1] == {"role": "system", "text": expected}
    # Reading is idempotent: a second read counts nothing again, shows one notice.
    again = await load_session(db, "proj-1")
    assert again is not None and again.fixes_used == 1 and len(visible_notes(again)) == 1
    # The next session write folds the notice in and acknowledges its row, so it
    # keeps its place and is still shown exactly once.
    await persist_session(db, again)
    after = await load_session(db, "proj-1")
    assert after is not None and after.fixes_used == 1
    assert [note.text for note in after.delivery_notes] == [expected]
    assert after.unfolded_notes == [] and len(visible_notes(after)) == 1
    [row] = _tables(db)["edit_deliveries"]
    assert row["notice_acknowledged"] is True


async def test_a_render_failure_with_attempts_left_is_retried_and_the_edit_stays_held() -> None:
    db, _fake, deck, _sources = await _provision()
    await _park_a_dangling_call(db)
    _result, job_id = await _queued_edit(db, deck, attempts=2)
    render_id = _job(db, job_id)["render_job_id"]

    await _render_fails(db, render_id)

    render = _job(db, render_id)
    assert render["status"] == "queued" and render["error_message"] == "render: chromium crashed"
    assert _job(db, job_id)["status"] == "committed"
    session = await load_session(db, "proj-1")
    assert session is not None
    assert [p.job_id for p in session.pending_deliveries] == [job_id]
    assert session.delivery_notes == []


async def test_a_render_that_fails_for_good_restores_the_allowance_and_says_so() -> None:
    db, _fake, deck, _sources = await _provision()
    await _park_a_dangling_call(db)
    _result, job_id = await _queued_edit(db, deck, attempts=2)
    render_id = _job(db, job_id)["render_job_id"]

    await _render_fails(db, render_id)  # attempt 1: retried
    await _render_fails(db, render_id)  # attempt 2: final

    assert _job(db, render_id)["status"] == "failed"
    parent = _job(db, job_id)
    assert parent["status"] == "delivery_failed"
    assert parent["error_message"].startswith("render failed: render: chromium crashed")
    session = await load_session(db, "proj-1")
    assert session is not None
    assert session.fixes_used == 0 and session.pending_deliveries == []
    expected = delivery_note_text(deck.language, DeliveryNoteKind.FAILED, 1)
    assert [note.text for note in visible_notes(session)] == [expected]
    # The revision the edit committed stays: only the delivery failed.
    assert session.revision_id is not None


async def test_edits_still_rendering_count_against_the_allowance() -> None:
    db, _fake, deck, _sources = await _provision()
    await _park_a_dangling_call(db)
    session = await _session(db)
    limit = session_fix_limit(session.package)
    session.inline_fixes_used = limit - 1
    await persist_session(db, session)
    _first, _job_id = await _queued_edit(db, deck)

    await _park_a_dangling_call(db)
    second, _second_job = await _queued_edit(db, deck)

    # One delivered + one rendering = the limit: a third edit cannot overdraw it.
    assert second.status is FixStatus.EXHAUSTED


async def test_a_failed_delivery_frees_the_held_fix_for_the_next_edit() -> None:
    db, _fake, deck, _sources = await _provision()
    await _park_a_dangling_call(db)
    session = await _session(db)
    session.inline_fixes_used = session_fix_limit(session.package) - 1
    await persist_session(db, session)
    _first, job_id = await _queued_edit(db, deck, attempts=1)
    await _render_fails(db, _job(db, job_id)["render_job_id"])

    await _park_a_dangling_call(db)
    changed = deck.model_copy(update={"title": "A different edit"})
    second, _second_job = await _queued_edit(db, changed)

    assert second.status is FixStatus.COMMITTED


async def test_a_delivery_whose_job_is_gone_holds_nothing_and_counts_nothing() -> None:
    db, _fake, deck, _sources = await _provision()
    await _park_a_dangling_call(db)
    _result, job_id = await _queued_edit(db, deck)
    # Deleting a job cascades to its edit_deliveries row (as the foreign key does).
    _tables(db)["generation_jobs"] = [
        row for row in _tables(db)["generation_jobs"] if row["id"] != job_id
    ]
    _tables(db)["edit_deliveries"] = [
        row for row in _tables(db)["edit_deliveries"] if row["job_id"] != job_id
    ]

    session = await load_session(db, "proj-1")

    assert session is not None
    assert session.fixes_used == 0 and session.pending_deliveries == []


async def test_an_in_flight_delivery_stays_a_hold_on_every_read() -> None:
    db, _fake, deck, _sources = await _provision()
    await _park_a_dangling_call(db)
    _result, job_id = await _queued_edit(db, deck)

    for _ in range(2):
        session = await _session(db)
        assert [p.job_id for p in session.pending_deliveries] == [job_id]
        assert session.fixes_used == 0 and session.delivery_notes == []


@pytest.mark.parametrize("language", list(Language))
@pytest.mark.parametrize("kind", list(DeliveryNoteKind))
def test_every_delivery_notice_exists_in_every_language(
    language: Language, kind: DeliveryNoteKind
) -> None:
    text = delivery_note_text(language, kind, 3)
    assert text.strip() and "{" not in text
    if kind is DeliveryNoteKind.DELIVERED:
        assert "3" in text


def test_notices_differ_per_language() -> None:
    texts = {delivery_note_text(lang, DeliveryNoteKind.FAILED, 1) for lang in Language}
    assert len(texts) == len(Language)


# ------------------------------------------------- paid delivery (emulated SQL)


async def _paid_generation(db: DatabaseClient, *, attempts: int = 1) -> tuple[str, Any]:
    job_id = str(uuid.uuid4())
    _tables(db).setdefault("generation_jobs", []).append(
        {
            "id": job_id,
            "project_id": "proj-1",
            "user_id": "u1",
            "job_type": "presentation_generation",
            "status": "processing",
            "worker_id": "w1",
            "attempts": 1,
            "max_attempts": 1,
            "payload": {"deducted_amount": 10_000},
            "progress": {},
            "heartbeat_at": "2026-01-01T00:00:00+00:00",
        }
    )
    head = await DocumentStore(db).head(
        "proj-1", __import__("packages").platform.document_models.DocumentKind.PRESENTATION
    )
    assert head is not None
    content = dict(head.content)
    content["title"] = "Regenerated"
    outcome = await DocumentStore(db).finish_generation_job(
        job_id=job_id,
        worker_id="w1",
        claim_token=1,
        base_revision_id=head.revision_id,
        content=content,
        kind=RevisionKind.REGENERATION,
        idempotency_key=f"job:{job_id}:deck",
        renderer_version=_VERSION,
        render_formats=["html"],
        render_max_attempts=attempts,
    )
    return job_id, outcome


def _refunds(db: DatabaseClient, job_id: str) -> list[dict[str, Any]]:
    return [
        row
        for row in _tables(db).get("credit_ledger", [])
        if row.get("generation_job_id") == job_id and row.get("action") == "refund"
    ]


async def test_paid_generation_is_committed_until_its_render_delivers_it() -> None:
    db, _fake, _deck, _sources = await _provision()
    job_id, outcome = await _paid_generation(db)

    assert outcome.job_status == JobStatus.COMMITTED.value
    await _render_succeeds(db, outcome.render_job_id)

    assert _job(db, job_id)["status"] == "completed"
    assert _refunds(db, job_id) == []


async def test_paid_generation_whose_render_fails_for_good_is_refunded_exactly_once() -> None:
    db, _fake, _deck, _sources = await _provision()
    job_id, outcome = await _paid_generation(db)

    await _render_fails(db, outcome.render_job_id)

    assert _job(db, job_id)["status"] == "delivery_failed"
    [refund] = _refunds(db, job_id)
    assert refund["amount"] == 10_000 and refund["user_id"] == "u1"
    # A later failure path for the same job refunds nothing more.
    reaped = await _rpc(
        db,
        "fail_job",
        {
            "p_job_id": job_id,
            "p_worker_id": "w1",
            "p_claim_token": 1,
            "p_step": "x",
            "p_message": "y",
        },
    )
    assert reaped is False and len(_refunds(db, job_id)) == 1


async def test_finish_without_a_renderer_or_formats_is_refused() -> None:
    db, _fake, _deck, _sources = await _provision()
    store = DocumentStore(db)
    with pytest.raises(Exception, match="render_required"):
        await store.finish_generation_job(
            job_id=str(uuid.uuid4()),
            worker_id="w1",
            claim_token=1,
            base_revision_id=None,
            content={"title": "x"},
            kind=RevisionKind.GENERATION,
            idempotency_key="k",
            renderer_version=_VERSION,
            render_formats=[],
            render_max_attempts=1,
        )


async def test_a_replayed_finish_with_other_content_is_idempotency_key_reused() -> None:
    db, _fake, _deck, _sources = await _provision()
    job_id, _outcome = await _paid_generation(db)
    head = _tables(db)["document_revisions"][-1]
    with pytest.raises(Exception, match="idempotency_key_reused"):
        await DocumentStore(db).finish_generation_job(
            job_id=job_id,
            worker_id="w1",
            claim_token=1,
            base_revision_id=head["parent_revision_id"],
            content={**head["content"], "title": "Something else"},
            kind=RevisionKind.REGENERATION,
            idempotency_key=f"job:{job_id}:deck",
            renderer_version=_VERSION,
            render_formats=["html"],
            render_max_attempts=1,
        )
