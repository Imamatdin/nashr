"""B1-FIX regressions (Codex B1 review), written once and run against two schemas.

CI runs this module with ``NASHR_TEST_SCHEMA=baseline`` (migration 016 exactly as
the review saw it, blob e2863406) where each regression must fail for the reason
listed in ``inventory_baseline.json``, and against the fixed chain where every
test must pass. The ``Baseline`` adapter reproduces the pre-fix write paths: the
worker committed through ``commit_revision`` as ``worker:<job>`` and then landed a
separate guarded completion (``JobQueue.complete``), in autocommitted statements.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import asyncpg  # pyright: ignore[reportMissingTypeStubs]
import pytest

from tests.db.conftest import BASELINE, LEGACY
from tests.db.support import Db, commit, ensure_document, finish, head

pytestmark = pytest.mark.skipif(LEGACY, reason="B1-FIX regressions compare 016 before and after")

OWNER_TG = 444_000_444


class Baseline:
    """What the reviewed code did, on the reviewed 016."""

    async def finish(
        self,
        conn: Any,
        job: str,
        worker: str,
        token: int,
        document: str,
        base: str | None,
        content: dict[str, Any],
        *,
        kind: str,
        key: str,
    ) -> dict[str, Any]:
        result = await commit(
            conn, document, base, content, kind=kind, actor=f"worker:{job}", key=key
        )
        await conn.execute(
            "update generation_jobs set status = 'completed', completed_at = now()"
            " where id = $1 and worker_id = $2 and status = 'processing'",
            uuid.UUID(job),
            worker,
        )
        return result


class Current:
    """The fixed write path: one claim-fenced finish."""

    async def finish(
        self,
        conn: Any,
        job: str,
        worker: str,
        token: int,
        document: str,
        base: str | None,
        content: dict[str, Any],
        *,
        kind: str,
        key: str,
    ) -> dict[str, Any]:
        return await finish(conn, job, worker, token, base, content, kind=kind, key=key)


SYSTEM: Baseline | Current = Baseline() if BASELINE else Current()


class Deck:
    """A presentation project with one committed head (r0) and an edit job's claim."""

    async def build(self, db: Db) -> Deck:
        self.db = db
        self.owner = await db.user(OWNER_TG)
        self.project = await db.project(self.owner)
        self.service = await db.as_role("service_role")
        self.document = await ensure_document(self.service, self.project, self.owner)
        first = await commit(
            self.service,
            self.document,
            None,
            {"t": "r0"},
            kind="manual",
            actor=self.owner,
            key="r0",
        )
        self.r0 = str(first["revision_id"])
        self.job = await db.job(
            self.project, self.owner, job_type="presentation_edit", worker="A", attempts=1
        )
        return self

    async def written_by_job(self) -> int:
        revisions = await self.service.fetchval(
            "select count(*) from document_revisions where actor = $1", f"worker:{self.job}"
        )
        proposals = await self.service.fetchval(
            "select count(*) from revision_proposals where source_job_id = $1 or actor = $2",
            uuid.UUID(self.job),
            f"worker:{self.job}",
        )
        return int(revisions) + int(proposals)

    async def job_status(self) -> str:
        return str(
            await self.service.fetchval(
                "select status from generation_jobs where id = $1", uuid.UUID(self.job)
            )
        )

    def finish_as_a(self, conn: Any, key: str = "edit") -> Any:
        return SYSTEM.finish(
            conn, self.job, "A", 1, self.document, self.r0, {"t": "ai"}, kind="ai_edit", key=key
        )


@pytest.fixture
async def deck(db: Db) -> Deck:
    return await Deck().build(db)


# ------------------------------------------------------------- 1. claim fencing


async def test_a_worker_whose_job_was_reclaimed_writes_nothing(deck: Deck) -> None:
    admin = await deck.db.admin()
    await admin.execute(
        "update generation_jobs set worker_id = 'B', attempts = 2, heartbeat_at = now()"
        " where id = $1",
        uuid.UUID(deck.job),
    )
    with pytest.raises(asyncpg.ObjectNotInPrerequisiteStateError, match="claim_lost"):
        await deck.finish_as_a(deck.service)
    assert await deck.written_by_job() == 0
    assert await head(deck.service, deck.document) == deck.r0


async def test_a_worker_whose_claim_expired_writes_nothing(deck: Deck) -> None:
    admin = await deck.db.admin()
    await admin.execute(
        "update generation_jobs set heartbeat_at = now() - interval '10 minutes' where id = $1",
        uuid.UUID(deck.job),
    )
    with pytest.raises(asyncpg.ObjectNotInPrerequisiteStateError, match="claim_expired"):
        await deck.finish_as_a(deck.service)
    assert await deck.written_by_job() == 0


async def test_a_reclaim_racing_a_finish_leaves_nothing_from_the_old_claim(deck: Deck) -> None:
    # The reaper re-queued the job and worker B claimed it, in a transaction that
    # is still open while worker A finishes.
    reclaimer = await deck.db.admin()
    await reclaimer.execute("begin")
    await reclaimer.execute(
        "update generation_jobs set worker_id = 'B', attempts = 2, heartbeat_at = now()"
        " where id = $1",
        uuid.UUID(deck.job),
    )
    worker = await deck.db.as_role("service_role")
    attempt = asyncio.create_task(deck.finish_as_a(worker))
    await asyncio.sleep(0.4)
    await reclaimer.execute("commit")
    try:
        await attempt
    except asyncpg.ObjectNotInPrerequisiteStateError as exc:
        assert "claim_lost" in str(exc)
    assert await deck.written_by_job() == 0, "a revision was written by a reclaimed worker"


async def test_a_status_change_during_finish_never_leaves_a_revision_beside_a_failed_job(
    deck: Deck,
) -> None:
    # The reaper fails the job in a transaction that is still open while the
    # worker commits its revision.
    reaper = await deck.db.admin()
    await reaper.execute("begin")
    await reaper.execute(
        "update generation_jobs set status = 'failed', completed_at = now(),"
        " error_message = 'reaped' where id = $1 and status = 'processing'",
        uuid.UUID(deck.job),
    )
    worker = await deck.db.as_role("service_role")
    attempt = asyncio.create_task(deck.finish_as_a(worker))
    await asyncio.sleep(0.4)
    await reaper.execute("commit")
    try:
        await attempt
    except asyncpg.ObjectNotInPrerequisiteStateError as exc:
        assert "claim_lost" in str(exc)
    status = await deck.job_status()
    written = await deck.written_by_job()
    assert not (status == "failed" and written > 0), "a revision was written beside a failed job"
    assert (status, written) == ("failed", 0)


async def test_a_fault_inside_finish_rolls_back_the_revision(deck: Deck) -> None:
    # Completion fails after the commit succeeded: by construction the revision
    # must go with it, never stay behind a job that did not complete.
    admin = await deck.db.admin()
    await admin.execute(
        """
        create function public.test_inject_fault() returns trigger language plpgsql as $$
        begin
            if new.status = 'completed' then
                raise exception 'injected_fault';
            end if;
            return new;
        end;
        $$;
        """
    )
    await admin.execute(
        "create trigger test_fault before update on generation_jobs"
        " for each row execute function public.test_inject_fault()"
    )
    with pytest.raises(asyncpg.RaiseError, match="injected_fault"):
        await deck.finish_as_a(deck.service)
    assert await deck.written_by_job() == 0, "a revision survived a failed completion"
    assert await deck.job_status() == "processing"
