"""B1-FIX2 regressions (Codex B1-FIX review of 8cc000b), run against two schemas.

CI runs this module with ``NASHR_TEST_SCHEMA=fix1`` (migration 016 exactly as the
B1-FIX review saw it, blob 1d38a9cc at 8cc000b), where each regression must fail
for the reason listed in ``inventory_fix1.json``, and against the fixed chain,
where every test must pass.

What the review found: a paid generation completed before its render ran, so a
render that failed for good left the job completed and charged; nothing linked
the job to the render that delivered it; a finish replay ignored changed
content; claim freshness was judged at transaction start; and overlapping export
requests duplicated renders.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import asyncpg  # pyright: ignore[reportMissingTypeStubs]
import pytest

from tests.db.conftest import BASELINE, LEGACY
from tests.db.support import Db, commit, ensure_document, finish, register

pytestmark = pytest.mark.skipif(
    LEGACY or BASELINE, reason="B1-FIX2 regressions compare 016 at 8cc000b with the fix"
)

OWNER_TG = 555_000_555
PRICE = 5_000


class Paid:
    """A presentation with a committed head (r0) and a paid generation job's claim."""

    async def build(self, db: Db, *, job_type: str = "presentation_generation") -> Paid:
        self.db = db
        self.owner = await db.user(OWNER_TG)
        self.project = await db.project(self.owner)
        self.service = await db.as_role("service_role")
        self.admin = await db.admin()
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
        paid = job_type == "presentation_generation"
        self.job = await db.job(
            self.project,
            self.owner,
            job_type=job_type,
            worker="w1",
            payload={"deducted_amount": PRICE} if paid else {},
        )
        return self

    async def finish(
        self,
        *,
        content: dict[str, Any] | None = None,
        formats: list[str] | None = None,
        renderer: str | None = "pw-test",
        attempts: int = 1,
        conn: Any = None,
    ) -> dict[str, Any]:
        kind = "regeneration" if await self.job_type() == "presentation_generation" else "ai_edit"
        return await finish(
            conn if conn is not None else self.service,
            self.job,
            "w1",
            1,
            self.r0,
            content if content is not None else {"t": "generated"},
            kind=kind,
            key=f"job:{self.job}",
            render_formats=formats,
            renderer_version=renderer,
            render_max_attempts=attempts,
        )

    async def job_type(self) -> str:
        return str(
            await self.admin.fetchval(
                "select job_type from generation_jobs where id = $1", uuid.UUID(self.job)
            )
        )

    async def status(self, job: str | None = None) -> str:
        return str(
            await self.admin.fetchval(
                "select status from generation_jobs where id = $1", uuid.UUID(job or self.job)
            )
        )

    async def render(self) -> dict[str, Any]:
        """The render job queued for this job's revision (by payload, on either schema)."""

        row = await self.admin.fetchrow(
            "select * from generation_jobs where job_type = 'presentation_render'"
            " and payload ->> 'requested_by_job' = $1",
            self.job,
        )
        assert row is not None, "finish queued no render for the committed revision"
        return dict(row)

    async def refunds(self) -> list[dict[str, Any]]:
        return [
            dict(r)
            for r in await self.admin.fetch(
                "select amount, user_id from credit_ledger where generation_job_id = $1"
                " and action = 'refund'",
                uuid.UUID(self.job),
            )
        ]

    async def claim_render(self, worker: str = "r1", conn: Any = None) -> tuple[str, int]:
        render = await self.render()
        rows = await (conn or self.service).fetch(
            "select * from claim_job($1, $2)", render["id"], worker
        )
        assert rows, "the render job was not claimable"
        return str(render["id"]), int(rows[0]["attempts"])

    async def fail_render(self, conn: Any = None) -> None:
        render, token = await self.claim_render(conn=conn)
        await (conn or self.service).fetchval(
            "select fail_job($1, 'r1', $2, 'render', 'chromium crashed')",
            uuid.UUID(render),
            token,
        )

    async def publish(self, render: str, token: int, conn: Any = None) -> None:
        payload = await self.admin.fetchval(
            "select payload from generation_jobs where id = $1", uuid.UUID(render)
        )
        for fmt in payload["formats"]:
            await register(
                conn or self.service,
                render,
                "r1",
                self.document,
                payload["revision_id"],
                fmt=fmt,
                token=token,
            )


@pytest.fixture
async def paid(db: Db) -> Paid:
    return await Paid().build(db)


# ------------------------------------------------ 1. paid delivery lifecycle


async def test_a_paid_job_waits_for_its_render_before_it_counts_as_delivered(paid: Paid) -> None:
    await paid.finish()
    status = await paid.status()
    assert status == "committed", f"the paid job was {status} before its render ran"
    render = await paid.render()
    linked = await paid.admin.fetchval(
        "select render_job_id from generation_jobs where id = $1", uuid.UUID(paid.job)
    )
    assert str(linked) == str(render["id"])


async def test_a_render_that_fails_for_good_leaves_the_paid_job_delivery_failed_and_refunded_once(
    paid: Paid,
) -> None:
    await paid.finish(attempts=1)

    await paid.fail_render()

    status = await paid.status()
    assert status == "delivery_failed", f"the paid job stayed {status} after its render failed"
    refunds = await paid.refunds()
    assert len(refunds) == 1, f"{len(refunds)} refunds for an undelivered paid job"
    assert refunds[0]["amount"] == PRICE and str(refunds[0]["user_id"]) == paid.owner
    # The revision the job committed stays: it is canonical history.
    kept = await paid.admin.fetchval(
        "select count(*) from document_revisions where actor = $1", f"worker:{paid.job}"
    )
    assert kept == 1


async def test_a_render_that_succeeds_completes_the_paid_job_without_a_refund(paid: Paid) -> None:
    await paid.finish(attempts=1)
    assert await paid.status() == "committed", "the paid job did not wait for its render"
    render, token = await paid.claim_render()
    await paid.publish(render, token)

    done = await paid.service.fetchval(
        "select complete_job($1, 'r1', $2, '{}'::jsonb)", uuid.UUID(render), token
    )

    assert done is True
    assert await paid.status() == "completed"
    assert await paid.refunds() == []


async def test_a_failed_render_is_retried_before_the_delivery_fails(paid: Paid) -> None:
    await paid.finish(attempts=3)

    await paid.fail_render()
    render = await paid.render()
    assert render["status"] == "queued", f"a first render failure was terminal ({render['status']})"
    assert await paid.status() == "committed"
    await paid.fail_render()
    await paid.fail_render()

    assert await paid.status() == "delivery_failed"
    assert len(await paid.refunds()) == 1


async def test_a_render_cannot_complete_without_every_requested_format(paid: Paid) -> None:
    await paid.finish(formats=["html", "pdf"])
    render, token = await paid.claim_render()
    await register(
        paid.service,
        render,
        "r1",
        paid.document,
        (await paid.render())["payload"]["revision_id"],
        fmt="html",
        token=token,
    )
    with pytest.raises(asyncpg.PostgresError, match="render_incomplete"):
        await paid.service.fetchval(
            "select complete_job($1, 'r1', $2, '{}'::jsonb)", uuid.UUID(render), token
        )


async def test_an_ai_edit_job_also_waits_for_its_render(db: Db) -> None:
    edit = await Paid().build(db, job_type="presentation_edit")
    await edit.finish()
    status = await edit.status()
    assert status == "committed", f"the edit job was {status} before its render ran"


# ------------------------------------------------ reaper


async def test_the_reaper_fails_the_delivery_of_a_committed_job_whose_render_is_gone(
    paid: Paid,
) -> None:
    await paid.finish()
    render = await paid.render()
    await paid.admin.execute("delete from generation_jobs where id = $1", render["id"])

    await paid.service.fetch("select * from reap_stale_jobs(120)")

    status = await paid.status()
    assert status == "delivery_failed", f"the reaper left the orphaned paid job {status}"
    assert len(await paid.refunds()) == 1


async def test_a_render_completing_while_the_reaper_runs_delivers_once(paid: Paid) -> None:
    await paid.finish()
    assert await paid.status() == "committed", "the paid job did not wait for its render"
    worker_conn = await paid.db.as_role("service_role")
    render, token = await paid.claim_render(conn=worker_conn)
    await paid.publish(render, token, conn=worker_conn)

    await worker_conn.execute("begin")
    assert await worker_conn.fetchval(
        "select complete_job($1, 'r1', $2, '{}'::jsonb)", uuid.UUID(render), token
    )
    # The render's transaction holds its row and its parents; the reaper must
    # neither wait on it nor settle the parent from a stale view.
    reaped = await asyncio.wait_for(
        paid.service.fetch("select * from reap_stale_jobs(120)"), timeout=10
    )
    await worker_conn.execute("commit")

    assert [str(r["id"]) for r in reaped] == []
    assert await paid.status() == "completed"
    assert await paid.refunds() == []


async def test_a_render_failing_while_the_reaper_runs_refunds_exactly_once(paid: Paid) -> None:
    await paid.finish(attempts=1)
    assert await paid.status() == "committed", "the paid job did not wait for its render"
    worker_conn = await paid.db.as_role("service_role")
    render, token = await paid.claim_render(conn=worker_conn)

    await worker_conn.execute("begin")
    assert await worker_conn.fetchval(
        "select fail_job($1, 'r1', $2, 'render', 'boom')", uuid.UUID(render), token
    )
    await asyncio.wait_for(paid.service.fetch("select * from reap_stale_jobs(0)"), timeout=10)
    await worker_conn.execute("commit")
    await paid.service.fetch("select * from reap_stale_jobs(0)")

    assert await paid.status() == "delivery_failed"
    assert len(await paid.refunds()) == 1


# ------------------------------------------------ 3. finish replay compares input


async def test_a_finish_replay_with_other_content_is_idempotency_key_reused(paid: Paid) -> None:
    await paid.finish(content={"t": "generated"})
    with pytest.raises(asyncpg.UniqueViolationError, match="idempotency_key_reused"):
        await paid.finish(content={"t": "something else"})


async def test_a_finish_replay_with_the_same_input_replays(paid: Paid) -> None:
    first = await paid.finish(content={"t": "generated"})
    again = await paid.finish(content={"t": "generated"})
    assert again["status"] == "duplicate" and again["revision_id"] == first["revision_id"]


# ------------------------------------------------ the render is not optional


async def test_a_finish_without_a_renderer_is_refused(paid: Paid) -> None:
    with pytest.raises(asyncpg.PostgresError, match="render_required"):
        await paid.finish(renderer=None)
    assert await paid.status() == "processing"


async def test_a_finish_without_formats_is_refused(paid: Paid) -> None:
    with pytest.raises(asyncpg.PostgresError, match="render_required"):
        await paid.finish(formats=[])
    assert await paid.status() == "processing"


# ------------------------------------------------ 4. freshness at decision time


async def test_claim_freshness_is_judged_when_the_finish_decides(paid: Paid) -> None:
    # The heartbeat is 118 s old when the transaction starts and over 120 s old
    # when finish decides: now() (transaction start) says fresh, the wall clock
    # says expired.
    await paid.admin.execute(
        "update generation_jobs set heartbeat_at = clock_timestamp() - interval '118 seconds'"
        " where id = $1",
        uuid.UUID(paid.job),
    )
    conn = await paid.db.as_role("service_role")
    await conn.execute("begin")
    await conn.execute("select pg_sleep(3)")
    with pytest.raises(asyncpg.ObjectNotInPrerequisiteStateError, match="claim_expired"):
        await paid.finish(conn=conn)
    await conn.execute("rollback")


# ------------------------------------------------ 5. overlapping export requests


async def test_update_exports_reuses_an_active_render_whose_formats_cover_it(
    paid: Paid,
) -> None:
    await paid.finish(formats=["html", "pdf", "pptx"])
    render = await paid.render()
    rows = await paid.service.fetch(
        "select * from request_render($1, $2, $3, 'pw-test', '{html,pdf,pptx}', 3)",
        uuid.UUID(paid.project),
        uuid.UUID(paid.owner),
        uuid.UUID(render["payload"]["revision_id"]),
    )
    assert rows[0]["status"] == "reused" and str(rows[0]["job_id"]) == str(render["id"])
    active = await paid.admin.fetchval(
        "select count(*) from generation_jobs where job_type = 'presentation_render'"
        " and status in ('queued', 'processing')"
    )
    assert active == 1
