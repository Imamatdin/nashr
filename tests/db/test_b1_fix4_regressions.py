"""B1-FIX4 regressions (Codex review of B1-FIX3 at 3723d30), run against two schemas.

CI runs this module with ``NASHR_TEST_SCHEMA=fix3`` (migration 016 exactly as the
review saw it, blob 0a90a2cb at 3723d30), where each regression must fail for the
reason listed in ``inventory_fix3.json``, and against the fixed chain, where every
test must pass.

What the review found at the database level:

F1  an AI edit whose content equals the head (outcome ``unchanged``) still got an
    edit_deliveries row, so it spent one edit of the allowance;
F3  nothing required a queued AI edit to name a real session: a job with no
    session, someone else's, or one replaced since, committed an edit that counted
    against nobody.

The setup never depends on the fix's own objects, so on 3723d30 each test fails on
behaviour: a hold that should not exist, or a write that should have been refused.
"""

from __future__ import annotations

import uuid
from typing import Any

import asyncpg  # pyright: ignore[reportMissingTypeStubs]
import pytest

from tests.db.conftest import BASELINE, FIX1, FIX2, LEGACY
from tests.db.support import Db, register
from tests.db.test_b1_fix2_regressions import Paid

pytestmark = pytest.mark.skipif(
    LEGACY or BASELINE or FIX1 or FIX2,
    reason="B1-FIX4 regressions compare 016 at 3723d30 with the fix",
)


class Edit(Paid):
    """A presentation (head r0) with a claimed AI-edit job queued the way the API queues it."""

    async def build_edit(self, db: Db) -> Edit:
        await self.build(db, job_type="presentation_edit")
        self.session = await self.admin.fetchval(
            "select payload ->> 'session_id' from generation_jobs where id = $1",
            uuid.UUID(self.job),
        )
        return self

    async def holds(self) -> list[dict[str, Any]]:
        rows = await self.admin.fetch(
            "select job_id::text, status from edit_deliveries order by created_at"
        )
        return [dict(row) for row in rows]

    async def renders_requested(self) -> int:
        return int(
            await self.admin.fetchval(
                "select count(*) from generation_jobs where job_type = 'presentation_render'"
                " and payload ->> 'requested_by_job' = $1",
                self.job,
            )
        )

    async def publish_head(self) -> None:
        """Every format the edit renders already exists for r0 (a completed render)."""

        render = await self.db.job(
            self.project,
            self.owner,
            worker="rh",
            payload={"revision_id": self.r0, "document_id": self.document},
        )
        assert await register(self.service, render, "rh", self.document, self.r0) == "registered"
        assert await self.service.fetchval(
            "select complete_job($1, 'rh', 1, '{}'::jsonb)", uuid.UUID(render)
        )

    async def progress(self) -> dict[str, Any]:
        return dict(
            await self.admin.fetchval(
                "select progress from generation_jobs where id = $1", uuid.UUID(self.job)
            )
        )

    async def written(self) -> int:
        """Revisions and proposals this job wrote."""

        return int(
            await self.admin.fetchval(
                "select (select count(*) from document_revisions where actor = $1)"
                " + (select count(*) from revision_proposals where source_job_id = $2)",
                f"worker:{self.job}",
                uuid.UUID(self.job),
            )
        )


@pytest.fixture
async def edit(db: Db) -> Edit:
    return await Edit().build_edit(db)


async def _has_parking(edit: Edit) -> bool:
    return await edit.db.parks_operations()


# ------------------------------------------------------------------------- F1


@pytest.mark.parametrize("exports", ["complete", "incomplete"])
async def test_an_unchanged_edit_holds_spends_and_renders_nothing(edit: Edit, exports: str) -> None:
    if exports == "complete":
        await edit.publish_head()

    first = await edit.finish(content={"t": "r0"})  # the head's own content

    assert (first["status"], first["revision_id"]) == ("unchanged", edit.r0)
    assert await edit.holds() == [], "an edit that changed nothing took an allowance hold"
    assert await edit.renders_requested() == 0, "an edit that changed nothing queued a render"
    assert (await edit.status(), first["job_status"]) == ("completed", "completed")
    progress = await edit.progress()
    assert (progress["outcome"], progress["revision_id"]) == ("unchanged", edit.r0)


async def test_a_replayed_unchanged_finish_returns_the_same_receipt_and_holds_nothing(
    edit: Edit,
) -> None:
    first = await edit.finish(content={"t": "r0"})
    replay = await edit.finish(content={"t": "r0"})

    assert replay == first
    assert await edit.holds() == [], "the replay of an unchanged edit took an allowance hold"


async def test_a_changed_edit_still_holds_one_fix(edit: Edit) -> None:
    await edit.finish(content={"t": "changed"})

    assert await edit.holds() == [{"job_id": edit.job, "status": "reserved"}]


# ------------------------------------------------------------------------- F3


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"session_id": "S"},
        {"operation_id": "O"},
        {"session_id": "S", "operation_id": "not-a-uuid"},
        {"session_id": "S", "operation_id": 7},
    ],
    ids=["no_identity", "no_operation", "no_session", "operation_not_uuid", "operation_number"],
)
async def test_an_edit_without_a_full_identity_is_refused_at_enqueue(
    edit: Edit, payload: dict[str, Any]
) -> None:
    session = str(edit.session or uuid.uuid4())
    body = {
        k: (session if v == "S" else str(uuid.uuid4()) if v == "O" else v)
        for k, v in payload.items()
    }
    await edit.db.finish_job(edit.job, "failed")  # the project's one active edit slot

    with pytest.raises(asyncpg.PostgresError, match="edit_identity_missing"):
        await edit.service.execute(
            "insert into generation_jobs (project_id, user_id, job_type, status, payload)"
            " values ($1, $2, 'presentation_edit', 'queued', $3::jsonb)",
            uuid.UUID(edit.project),
            uuid.UUID(edit.owner),
            body,
        )


async def test_an_edit_for_another_users_session_is_refused_at_enqueue(edit: Edit) -> None:
    stranger = await edit.db.user()
    elsewhere = await edit.db.project(stranger)
    session, operation = (
        await edit.db.park(elsewhere)
        if await _has_parking(edit)
        else (await _bare_session(edit, elsewhere), str(uuid.uuid4()))
    )
    await edit.db.finish_job(edit.job, "failed")

    with pytest.raises(asyncpg.PostgresError, match="edit_session_not_found"):
        await edit.service.execute(
            "insert into generation_jobs (project_id, user_id, job_type, status, payload)"
            " values ($1, $2, 'presentation_edit', 'queued', $3::jsonb)",
            uuid.UUID(edit.project),
            uuid.UUID(edit.owner),
            {"session_id": session, "operation_id": operation},
        )


async def test_an_edit_for_a_call_no_longer_parked_is_refused_at_enqueue(edit: Edit) -> None:
    session = str(edit.session) if edit.session else await _bare_session(edit, edit.project)
    if await _has_parking(edit):
        await edit.db.park(edit.project)  # a later turn parked another call
    await edit.db.finish_job(edit.job, "failed")

    with pytest.raises(asyncpg.PostgresError, match="edit_operation_stale"):
        await edit.service.execute(
            "insert into generation_jobs (project_id, user_id, job_type, status, payload)"
            " values ($1, $2, 'presentation_edit', 'queued', $3::jsonb)",
            uuid.UUID(edit.project),
            uuid.UUID(edit.owner),
            {"session_id": session, "operation_id": str(uuid.uuid4())},
        )


async def test_finish_refuses_an_edit_whose_session_was_replaced(edit: Edit) -> None:
    if edit.session is None:  # 016 as of 3723d30: stamp a session the way B1-FIX3 did
        edit.session = await _bare_session(edit, edit.project)
        await edit.admin.execute(
            "update generation_jobs set payload = payload || $2::jsonb where id = $1",
            uuid.UUID(edit.job),
            {"session_id": edit.session},
        )
    # A regeneration replaces the session while the edit is running.
    await edit.admin.execute("delete from brain_sessions where id = $1", uuid.UUID(edit.session))

    with pytest.raises(asyncpg.PostgresError, match="edit_session_not_found"):
        await edit.finish(content={"t": "changed"})
    assert await edit.written() == 0, "a sessionless edit committed"
    assert await edit.status() == "processing"


async def test_finish_refuses_an_edit_whose_call_was_answered_elsewhere(edit: Edit) -> None:
    if await _has_parking(edit):
        # The call was answered (and cleared) by another writer while the edit ran.
        await edit.admin.execute(
            "update brain_sessions set parked_operation_id = null, version = version + 1"
            " where id = $1",
            uuid.UUID(str(edit.session)),
        )

    with pytest.raises(asyncpg.PostgresError, match="edit_operation_stale"):
        await edit.finish(content={"t": "changed"})
    assert await edit.written() == 0, "an edit for an answered call committed"
    assert await edit.holds() == []


async def _bare_session(edit: Edit, project: str) -> str:
    return str(
        await edit.admin.fetchval(
            "insert into brain_sessions (project_id, package, formats_json)"
            " values ($1, 'presentation_premium', '[\"html\"]') returning id",
            uuid.UUID(project),
        )
    )
