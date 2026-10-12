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
from datetime import UTC, datetime, timedelta
from typing import Any

import asyncpg  # pyright: ignore[reportMissingTypeStubs]
import pytest

from packages.platform.storage import StoredObject
from scripts.gc_orphan_exports import find_orphans
from tests.db.conftest import BASELINE, LEGACY
from tests.db.support import Db, commit, ensure_document, export_key, finish, head

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


# ------------------------------------------------- 2. register_export contract


async def _register(
    conn: Any,
    job: str,
    worker: str | None,
    token: int,
    document: str,
    revision: str,
    *,
    fmt: str = "html",
    sha: str = "a" * 64,
    version: str = "pw-test",
) -> str:
    """register_export as each schema exposes it; returns the status."""

    key = export_key(document, revision, fmt, sha, version)
    if BASELINE:
        return str(
            await conn.fetchval(
                "select register_export($1, $2, $3, $4, $5, $6, $7, 10, null)",
                uuid.UUID(job),
                worker,
                uuid.UUID(revision),
                fmt,
                version,
                key,
                sha,
            )
        )
    row = await conn.fetchrow(
        "select * from register_export($1, $2, $3, $4, $5, $6, $7, $8, 10, null)",
        uuid.UUID(job),
        worker,
        token,
        uuid.UUID(revision),
        fmt,
        version,
        key,
        sha,
    )
    return str(row["status"])


async def _exports(deck: Deck) -> list[dict[str, Any]]:
    rows = await deck.service.fetch(
        "select format, storage_key, sha256 from revision_exports order by format"
    )
    return [dict(row) for row in rows]


async def test_a_render_job_cannot_be_created_with_a_null_target(deck: Deck) -> None:
    with pytest.raises(asyncpg.CheckViolationError, match="generation_jobs_render_payload_check"):
        await deck.db.job(
            deck.project,
            deck.owner,
            payload={"revision_id": None, "renderer_version": "pw-test", "formats": ["html"]},
        )


async def test_a_job_whose_payload_has_no_target_cannot_register(deck: Deck) -> None:
    # A generation job carries no render target: the reviewed predicate was
    # FALSE OR NOT (NULL OR FALSE) = NULL, and PL/pgSQL skips an IF on NULL.
    job = await deck.db.job(
        deck.project, deck.owner, job_type="presentation_generation", worker="R", payload={}
    )
    with pytest.raises(asyncpg.InsufficientPrivilegeError, match="job_type_not_allowed"):
        await _register(deck.service, job, "R", 1, deck.document, deck.r0)
    assert await _exports(deck) == []


async def test_a_legacy_render_job_with_a_json_null_target_cannot_register(deck: Deck) -> None:
    # A row from before the CHECK existed (it is NOT VALID for old rows).
    admin = await deck.db.admin()
    await admin.execute(
        "alter table generation_jobs drop constraint generation_jobs_render_payload_check"
    )
    job = await deck.db.job(
        deck.project,
        deck.owner,
        worker="R",
        payload={"revision_id": None, "renderer_version": "pw-test", "formats": ["html"]},
    )
    with pytest.raises(asyncpg.InsufficientPrivilegeError, match="job_revision_mismatch"):
        await _register(deck.service, job, "R", 1, deck.document, deck.r0)
    assert await _exports(deck) == []


async def test_a_render_job_of_another_user_cannot_register(deck: Deck) -> None:
    stranger = await deck.db.user()
    job = await deck.db.job(deck.project, stranger, worker="R", payload={"revision_id": deck.r0})
    with pytest.raises(asyncpg.InsufficientPrivilegeError, match="not_document_owner"):
        await _register(deck.service, job, "R", 1, deck.document, deck.r0)
    assert await _exports(deck) == []


async def test_a_job_without_a_claim_cannot_register(deck: Deck) -> None:
    # worker_id NULL on the job and NULL from the caller are not "the same claim".
    job = await deck.db.job(deck.project, deck.owner, worker=None, payload={"revision_id": deck.r0})
    with pytest.raises(asyncpg.ObjectNotInPrerequisiteStateError, match="claim_lost"):
        await _register(deck.service, job, None, 1, deck.document, deck.r0)
    assert await _exports(deck) == []


async def test_a_job_of_another_type_cannot_register(deck: Deck) -> None:
    job = await deck.db.job(
        deck.project,
        deck.owner,
        job_type="source_processing",
        worker="R",
        payload={"revision_id": deck.r0},
    )
    with pytest.raises(asyncpg.InsufficientPrivilegeError, match="job_type_not_allowed"):
        await _register(deck.service, job, "R", 1, deck.document, deck.r0)
    assert await _exports(deck) == []


async def test_a_format_the_job_did_not_request_cannot_be_registered(deck: Deck) -> None:
    job = await deck.db.job(deck.project, deck.owner, worker="R", payload={"revision_id": deck.r0})
    with pytest.raises(asyncpg.InsufficientPrivilegeError, match="format_not_requested"):
        await _register(deck.service, job, "R", 1, deck.document, deck.r0, fmt="pdf")
    assert await _exports(deck) == []


async def test_a_renderer_version_the_job_did_not_request_cannot_be_registered(
    deck: Deck,
) -> None:
    job = await deck.db.job(deck.project, deck.owner, worker="R", payload={"revision_id": deck.r0})
    with pytest.raises(asyncpg.InsufficientPrivilegeError, match="renderer_version_mismatch"):
        await _register(deck.service, job, "R", 1, deck.document, deck.r0, version="pw-other")
    assert await _exports(deck) == []


async def test_a_stale_claim_token_cannot_register(deck: Deck) -> None:
    # Same worker id, but the job has been claimed again since (attempt 2).
    job = await deck.db.job(
        deck.project, deck.owner, worker="R", attempts=2, payload={"revision_id": deck.r0}
    )
    with pytest.raises(asyncpg.ObjectNotInPrerequisiteStateError, match="claim_lost"):
        await _register(deck.service, job, "R", 1, deck.document, deck.r0)
    assert await _exports(deck) == []


# ------------------------------------------------ 3. first writer wins


def _orphans(uploaded: list[str], registered: list[dict[str, Any]]) -> list[str]:
    old = datetime.now(UTC) - timedelta(days=2)
    objects = [
        StoredObject(key=key, size=10, sha256_b64=None, last_modified=old) for key in uploaded
    ]
    keys = {str(row["storage_key"]) for row in registered}
    found = find_orphans(objects, keys, now=datetime.now(UTC), min_age=timedelta(hours=24))
    return [item.key for item in found]


async def test_rendering_a_revision_twice_keeps_the_first_export(deck: Deck) -> None:
    first = await deck.db.job(
        deck.project, deck.owner, worker="R", payload={"revision_id": deck.r0}
    )
    assert await _register(deck.service, first, "R", 1, deck.document, deck.r0) == "registered"
    await deck.db.finish_job(first)
    # A second render of the same revision produced different bytes (PPTX
    # timestamps): it must succeed and leave the first export in place.
    second = await deck.db.job(
        deck.project, deck.owner, worker="R2", payload={"revision_id": deck.r0}
    )
    status = await _register(deck.service, second, "R2", 1, deck.document, deck.r0, sha="b" * 64)

    assert status == "existing"
    rows = await _exports(deck)
    assert [row["sha256"] for row in rows] == ["a" * 64]
    uploaded = [
        export_key(deck.document, deck.r0, "html", "a" * 64),
        export_key(deck.document, deck.r0, "html", "b" * 64),
    ]
    assert _orphans(uploaded, rows) == [uploaded[1]]


async def test_a_recovery_render_after_a_crash_mid_publish_completes_the_set(deck: Deck) -> None:
    # The first render registered html, uploaded pdf, and died before
    # registering it; the reaper failed the job. The recovery render produces
    # both formats again with new bytes.
    formats = {"revision_id": deck.r0, "formats": ["html", "pdf"]}
    crashed = await deck.db.job(deck.project, deck.owner, worker="R", payload=formats)
    await _register(deck.service, crashed, "R", 1, deck.document, deck.r0)
    await deck.db.finish_job(crashed, "failed")
    recovery = await deck.db.job(deck.project, deck.owner, worker="R2", payload=formats)

    html = await _register(deck.service, recovery, "R2", 1, deck.document, deck.r0, sha="b" * 64)
    pdf = await _register(
        deck.service, recovery, "R2", 1, deck.document, deck.r0, fmt="pdf", sha="c" * 64
    )

    assert (html, pdf) == ("existing", "registered")
    rows = await _exports(deck)
    assert [(row["format"], row["sha256"]) for row in rows] == [
        ("html", "a" * 64),
        ("pdf", "c" * 64),
    ]
    uploaded = [
        export_key(deck.document, deck.r0, "html", "a" * 64),
        export_key(deck.document, deck.r0, "pdf", "d" * 64),  # the crashed upload
        export_key(deck.document, deck.r0, "html", "b" * 64),
        export_key(deck.document, deck.r0, "pdf", "c" * 64),
    ]
    assert sorted(_orphans(uploaded, rows)) == sorted([uploaded[1], uploaded[2]])
