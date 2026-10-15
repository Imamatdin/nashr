"""B1-FIX3 regressions (Codex Review A of fdb14bc), run against two schemas.

CI runs this module with ``NASHR_TEST_SCHEMA=fix2`` (migration 016 exactly as
Review A saw it, blob 07b3809c at fdb14bc), where each regression must fail for
the reason listed in ``inventory_fix2.json``, and against the fixed chain, where
every test must pass.

What the review found at the database level: an AI edit's allowance hold lived
only in the session JSON, written after ``finish_generation_job`` returned, so a
worker that died in between lost it (A1); and nothing stopped a session write
that had not seen the latest version from overwriting it (A2).
"""

from __future__ import annotations

import uuid
from typing import Any

import asyncpg  # pyright: ignore[reportMissingTypeStubs]
import pytest

from tests.db.conftest import BASELINE, FIX1, LEGACY
from tests.db.support import Db
from tests.db.test_b1_fix2_regressions import Paid

pytestmark = pytest.mark.skipif(
    LEGACY or BASELINE or FIX1, reason="B1-FIX3 regressions compare 016 at fdb14bc with the fix"
)


class Edit(Paid):
    """A presentation with a session and a claimed AI-edit job parked on it."""

    async def build_edit(self, db: Db, *, slides: int = 2) -> Edit:
        await self.build(db, job_type="presentation_edit")
        self.session = str(uuid.uuid4())
        await self.admin.execute(
            "insert into brain_sessions (id, project_id, package, formats_json)"
            " values ($1, $2, 'presentation_premium', '[\"html\"]')",
            uuid.UUID(self.session),
            uuid.UUID(self.project),
        )
        await self.admin.execute(
            "update generation_jobs set payload = $2::jsonb where id = $1",
            uuid.UUID(self.job),
            {"slides_changed": slides, "session_id": self.session, "history_len": 2},
        )
        return self

    async def holds(self) -> list[dict[str, Any]]:
        rows = await self.admin.fetch(
            "select job_id::text, session_id::text, status, slides_changed, notice_acknowledged,"
            " settled_at is not null as settled from edit_deliveries order by created_at"
        )
        return [dict(row) for row in rows]


@pytest.fixture
async def edit(db: Db) -> Edit:
    return await Edit().build_edit(db)


async def test_finish_records_the_edit_hold_in_the_commit_transaction(edit: Edit) -> None:
    await edit.finish(attempts=1)

    holds = await edit.holds()
    assert holds == [
        {
            "job_id": edit.job,
            "session_id": edit.session,
            "status": "reserved",
            "slides_changed": 2,
            "notice_acknowledged": False,
            "settled": False,
        }
    ]


async def test_a_finish_that_rolls_back_leaves_no_hold(edit: Edit) -> None:
    transaction = edit.service.transaction()
    await transaction.start()
    await edit.finish(attempts=1)
    inside = await edit.service.fetchval("select count(*) from edit_deliveries")
    await transaction.rollback()

    # Commit and hold are one transaction: a crash before it commits leaves neither.
    assert inside == 1, "finish recorded no hold"
    assert await edit.admin.fetchval("select count(*) from edit_deliveries") == 0
    assert await edit.status() == "processing"


async def test_the_render_completing_delivers_the_hold_with_the_parent(edit: Edit) -> None:
    await edit.finish(attempts=1)
    render, token = await edit.claim_render()
    await edit.publish(render, token)

    assert await edit.service.fetchval(
        "select complete_job($1, 'r1', $2, '{}'::jsonb)", uuid.UUID(render), token
    )

    assert await edit.status() == "completed"
    [hold] = await edit.holds()
    assert (hold["status"], hold["settled"]) == ("delivered", True)


async def test_the_render_failing_for_good_releases_the_hold_with_the_parent(edit: Edit) -> None:
    await edit.finish(attempts=1)

    await edit.fail_render()

    assert await edit.status() == "delivery_failed"
    [hold] = await edit.holds()
    assert (hold["status"], hold["settled"]) == ("released", True)


async def test_the_reaper_settles_the_hold_when_it_settles_the_parent(db: Db) -> None:
    gone = await Edit().build_edit(db)
    await gone.finish(attempts=1)
    render = await gone.render()
    await gone.admin.execute("delete from generation_jobs where id = $1", render["id"])

    await gone.service.fetch("select * from reap_stale_jobs(120)")

    assert await gone.status() == "delivery_failed"
    [hold] = await gone.holds()
    assert hold["status"] == "released", "the reaper failed the delivery but kept the hold"


async def test_acknowledging_a_notice_marks_only_settled_rows_of_that_session(edit: Edit) -> None:
    await edit.finish(attempts=1)
    acknowledged = await edit.service.fetchval(
        "select acknowledge_edit_notices($1, $2)", uuid.UUID(edit.session), [uuid.UUID(edit.job)]
    )
    assert acknowledged == 0, "a notice was acknowledged before its edit settled"
    await edit.fail_render()

    other = await edit.service.fetchval(
        "select acknowledge_edit_notices($1, $2)", uuid.uuid4(), [uuid.UUID(edit.job)]
    )
    mine = await edit.service.fetchval(
        "select acknowledge_edit_notices($1, $2)", uuid.UUID(edit.session), [uuid.UUID(edit.job)]
    )

    assert (other, mine) == (0, 1)
    [hold] = await edit.holds()
    assert hold["notice_acknowledged"] is True


@pytest.mark.parametrize("role", ["authenticated", "service_role"])
async def test_no_api_role_writes_a_hold_directly(edit: Edit, role: str) -> None:
    await edit.finish(attempts=1)
    conn = await edit.db.as_role(role, edit.owner)
    for statement in (
        "update edit_deliveries set status = 'delivered'",
        "delete from edit_deliveries",
        "insert into edit_deliveries (job_id, project_id, revision_id, slides_changed, status)"
        " select job_id, project_id, revision_id, 0, 'delivered' from edit_deliveries",
    ):
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await conn.execute(statement)
    [hold] = await edit.holds()
    assert hold["status"] == "reserved"


async def test_only_the_owner_reads_their_holds(edit: Edit) -> None:
    await edit.finish(attempts=1)
    stranger = await edit.db.user()
    mine = await edit.db.as_role("authenticated", edit.owner)
    theirs = await edit.db.as_role("authenticated", stranger)

    assert await mine.fetchval("select count(*) from edit_deliveries") == 1
    assert await theirs.fetchval("select count(*) from edit_deliveries") == 0


async def test_a_session_write_must_advance_the_version_by_one(edit: Edit) -> None:
    service = edit.service
    session = uuid.UUID(edit.session)
    with pytest.raises(asyncpg.SerializationError, match="session_version_conflict"):
        await service.execute(
            "update brain_sessions set history_json = '[]' where id = $1", session
        )
    moved = await service.fetchval(
        "update brain_sessions set version = version + 1 where id = $1 and version = 0"
        " returning version",
        session,
    )
    assert moved == 1
    stale = await service.fetch(
        "update brain_sessions set version = 1, history_json = '[]'"
        " where id = $1 and version = 0 returning id",
        session,
    )
    assert stale == [], "a writer holding version 0 overwrote version 1"
