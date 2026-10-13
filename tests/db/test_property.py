"""Random interleavings on real PostgreSQL (test n).

``test_n_interleaved_writers_never_lose_work`` runs 2–6 writers serially against
an exact model of the head: the head is the last committed revision, no
committed revision is lost, every losing ai_edit / regeneration write is a
proposal, and the decks view equals the head.

``test_concurrent_lifecycle_preserves_every_invariant`` (B1-FIX, strengthened in
B1-FIX2) runs rounds of 2–4 operations at once on separate connections: manual
saves, worker finishes (edit and paid generation), accept and reject, reclaim
through the real reaper and claim RPCs, worker failure, the reaper, and renders
that succeed or fail through their own claims. A sequential prepare phase gives
every drawn transition what it needs (a pending proposal, a processing job, a
queued render) before the round races. After every round a linearizability
oracle holds: every writer of a round competes against the head as it was before
the round, so at most one write commits, and exactly one does when any write
reached the compare-and-swap from that head. Every revision sits on the single
parent chain from the head, every stored hash recomputes, and every id ever seen
still exists, beside the lifecycle invariants (workers write only beside a
settled job, refunds exactly once, exports only from render jobs). After the last
round every job is driven to rest, and each job that took money ended completed
or refunded exactly once.

Run with NASHR_TEST_MUTATION=no_document_lock (tests/db/support.py), the same
test must FAIL: without the document row lock same-base writers stop serializing.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any

import pytest

pytest.importorskip("hypothesis", reason="hypothesis runs in the CI database job")

import asyncpg  # pyright: ignore[reportMissingTypeStubs]
from hypothesis import HealthCheck, event, given, settings
from hypothesis import strategies as st

from tests.db.conftest import CURRENT
from tests.db.support import Db, accept, commit, ensure_document, finish, head, register

pytestmark = pytest.mark.skipif(
    not CURRENT, reason="exercises migration 016's functions (current schema only)"
)

KINDS = ["manual", "autosave", "ai_edit", "regeneration", "bot_edit", "restore"]
PROPOSING = {"ai_edit", "regeneration"}


@st.composite
def plans(draw: Any) -> tuple[list[str], list[tuple[int, str]]]:
    writers = draw(st.lists(st.sampled_from(KINDS), min_size=2, max_size=6))
    steps = draw(
        st.lists(
            st.tuples(st.integers(0, len(writers) - 1), st.sampled_from(["refresh", "commit"])),
            min_size=40,
            max_size=60,
        )
    )
    return writers, steps


def _actor(kind: str, owner: str, telegram: int) -> str:
    if kind == "bot_edit":
        return f"bot:{telegram}"
    return owner


@settings(
    max_examples=6,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow],
)
@given(plan=plans())
async def test_n_interleaved_writers_never_lose_work(
    db: Db, plan: tuple[list[str], list[tuple[int, str]]]
) -> None:
    writers, steps = plan
    owner = await db.user()  # a fresh Telegram id per example
    admin = await db.admin()
    project = await db.project(owner)
    conn = await db.as_role("service_role")
    telegram = await admin.fetchval("select telegram_id from users where id = $1", uuid.UUID(owner))
    document = await ensure_document(conn, project, owner)
    first = await commit(conn, document, None, {"step": -1}, kind="manual", actor=owner, key="seed")

    model_head = str(first["revision_id"])
    committed = [model_head]
    proposals: list[str] = []
    bases = [model_head for _ in writers]

    for index, (writer, action) in enumerate(steps):
        if action == "refresh":
            bases[writer] = model_head
            continue
        kind = writers[writer]
        content = {"step": index, "writer": writer}
        if kind in PROPOSING:
            # A worker writes through its fenced finish, one claimed job per write.
            job_type = "presentation_edit" if kind == "ai_edit" else "presentation_generation"
            job = await db.job(project, owner, job_type=job_type)
            result = await finish(
                conn, job, "w1", 1, bases[writer], content, kind=kind, key=f"op-{index}"
            )
        else:
            result = await commit(
                conn,
                document,
                bases[writer],
                content,
                kind=kind,
                actor=_actor(kind, owner, telegram),
                key=f"op-{index}",
            )
        if bases[writer] == model_head:
            assert result["status"] == "committed", (index, result)
            model_head = str(result["revision_id"])
            committed.append(model_head)
            bases[writer] = model_head
        elif kind in PROPOSING:
            assert result["status"] == "proposed", (index, result)
            proposals.append(f"op-{index}")
        else:
            assert result["status"] == "conflict", (index, result)

        assert await head(conn, document) == model_head
        stored = await conn.fetchval(
            "select count(*) from document_revisions where id = any($1::uuid[])",
            [uuid.UUID(r) for r in committed],
        )
        assert stored == len(committed)
        keys = {
            row["idempotency_key"]
            for row in await conn.fetch(
                "select idempotency_key from revision_proposals where document_id = $1",
                uuid.UUID(document),
            )
        }
        assert keys == set(proposals)
        view = await conn.fetchval(
            "select deck_json from decks where project_id = $1", uuid.UUID(project)
        )
        content = await conn.fetchval(
            "select content from document_revisions where id = $1", uuid.UUID(model_head)
        )
        assert view == content


# ----------------------------------------------- concurrent lifecycle (B1-FIX2)

# Errors an operation may legitimately meet in a race; anything else (a deadlock,
# a serialization failure, an unexpected refusal) fails the property.
_RACE_REFUSALS = (
    "claim_lost",
    "claim_expired",
    "proposal_not_pending",
    "job_revision_mismatch",
    # enqueue dedupe: one active job per (project, type), one active render per
    # (revision, renderer, formats); the app hands back the existing job
    "uq_generation_jobs_active",
)

OPS = [
    "manual",
    "edit_job",
    "paid_generation",
    "accept",
    "reject",
    "reclaim",
    "worker_fail",
    "reap",
    "render_ok",
    "render_fail",
]
WRITES = {"manual", "edit_job", "paid_generation", "accept"}
FORMATS = ["html", "pdf"]


@st.composite
def rounds(draw: Any) -> list[list[tuple[str, int]]]:
    return draw(
        st.lists(
            st.lists(st.tuples(st.sampled_from(OPS), st.integers(0, 9)), min_size=2, max_size=4),
            min_size=6,
            max_size=10,
        )
    )


class Lifecycle:
    """One project under concurrent writers, workers, reaper and renderer."""

    def __init__(self, db: Db) -> None:
        self.db = db

    async def build(self) -> Lifecycle:
        self.owner = await self.db.user()
        self.project = await self.db.project(self.owner)
        self.admin = await self.db.admin()
        self.pool = [await self.db.as_role("service_role") for _ in range(4)]
        self.document = await ensure_document(self.pool[0], self.project, self.owner)
        first = await commit(
            self.pool[0], self.document, None, {"seq": -1}, kind="manual", actor=self.owner, key="s"
        )
        self.revisions = [str(first["revision_id"])]
        self.seen: dict[str, tuple[str | None, str]] = {}
        self.seen_ids: dict[str, set[str]] = {"jobs": set(), "proposals": set()}
        # (job, worker, token) for every claim a worker ever held on a job.
        self.claims: list[tuple[str, str, int]] = []
        self.counter = 0
        self.results: list[tuple[str, str | None, str]] = []  # (op, base, status)
        return self

    def key(self, prefix: str) -> str:
        self.counter += 1
        return f"{prefix}-{self.counter}"

    def pick(self, items: list[Any], choice: int) -> Any:
        return items[choice % len(items)] if items else None

    async def head(self) -> str:
        current = await head(self.admin, self.document)
        assert current is not None
        return current

    async def _clear_active(self, conn: Any, *, paid: bool) -> None:
        """Settle an active job of this type as a worker giving up (setup only).

        One active job per (project, type) is allowed; setup needs its own.
        """

        job_type = "presentation_generation" if paid else "presentation_edit"
        row = await self.admin.fetchrow(
            "select id, status, worker_id, attempts from generation_jobs where project_id = $1"
            " and job_type = $2 and status in ('queued', 'processing')",
            uuid.UUID(self.project),
            job_type,
        )
        if row is None:
            return
        worker, token = row["worker_id"], int(row["attempts"])
        if row["status"] == "queued":
            worker = self.key("w")
            claimed = await conn.fetch("select * from claim_job($1, $2)", row["id"], worker)
            token = int(claimed[0]["attempts"])
        await conn.fetchval(
            "select fail_job($1, $2, $3, 'setup', 'cleared')", row["id"], worker, token
        )

    async def _worker_job(self, conn: Any, *, paid: bool) -> tuple[str, str]:
        worker = self.key("w")
        job = await self.db.job(
            self.project,
            self.owner,
            job_type="presentation_generation" if paid else "presentation_edit",
            worker=worker,
            payload={"deducted_amount": 5_000} if paid else {},
            conn=conn,
            max_attempts=3,
        )
        self.claims.append((job, worker, 1))
        return job, worker

    async def _finish(
        self, conn: Any, job: str, worker: str, base: str | None, *, paid: bool
    ) -> dict[str, Any]:
        kind = ("regeneration" if base else "generation") if paid else "ai_edit"
        result = await finish(
            conn,
            job,
            worker,
            1,
            base,
            {"seq": self.key("j")},
            kind=kind,
            key=self.key("job"),
            render_formats=FORMATS,
        )
        if result["revision_id"] and result["status"] == "committed":
            self.revisions.append(str(result["revision_id"]))
        return result

    # ------------------------------------------------ guaranteed setup

    async def prepare(self, ops: list[tuple[str, int]]) -> None:
        """Give every drawn transition its precondition, sequentially, before the race."""

        names = {op for op, _ in ops}
        conn = self.pool[0]
        if names & {"accept", "reject"} and not await self._pending():
            # A proposal needs a stale base: move the head, then edit the old one.
            stale = await self.head()
            moved = await commit(
                conn,
                self.document,
                stale,
                {"seq": self.key("p")},
                kind="manual",
                actor=self.owner,
                key=self.key("move"),
            )
            self.revisions.append(str(moved["revision_id"]))
            await self._clear_active(conn, paid=False)
            job, worker = await self._worker_job(conn, paid=False)
            result = await self._finish(conn, job, worker, stale, paid=False)
            assert result["status"] == "proposed", result
        if names & {"reclaim", "worker_fail"} and not await self._processing_workers():
            await self._clear_active(conn, paid=False)
            await self._worker_job(conn, paid=False)
        if names & {"render_ok", "render_fail"} and not await self._queued_renders():
            await self._clear_active(conn, paid=True)
            job, worker = await self._worker_job(conn, paid=True)
            await self._finish(conn, job, worker, await self.head(), paid=True)
        assert not (names & {"accept", "reject"}) or await self._pending()
        assert not (names & {"reclaim", "worker_fail"}) or await self._processing_workers()
        assert not (names & {"render_ok", "render_fail"}) or await self._queued_renders()

    async def _pending(self) -> list[str]:
        return [
            str(r["id"])
            for r in await self.admin.fetch(
                "select id from revision_proposals where status = 'pending'"
                " and document_id = $1 order by created_at",
                uuid.UUID(self.document),
            )
        ]

    async def _processing_workers(self) -> list[tuple[str, str, int]]:
        rows = await self.admin.fetch(
            "select id, worker_id, attempts from generation_jobs where project_id = $1"
            " and status = 'processing' and job_type <> 'presentation_render' order by created_at",
            uuid.UUID(self.project),
        )
        return [(str(r["id"]), str(r["worker_id"]), int(r["attempts"])) for r in rows]

    async def _queued_renders(self) -> list[str]:
        return [
            str(r["id"])
            for r in await self.admin.fetch(
                "select id from generation_jobs where project_id = $1 and status = 'queued'"
                " and job_type = 'presentation_render' order by created_at",
                uuid.UUID(self.project),
            )
        ]

    # ------------------------------------------------ operations

    async def run(self, conn: Any, op: str, choice: int, ctx: dict[str, Any]) -> None:
        base = self.pick(ctx["revisions"], choice)
        if op == "manual":
            result = await commit(
                conn,
                self.document,
                base,
                {"seq": self.key("m")},
                kind="manual",
                actor=self.owner,
                key=self.key("manual"),
            )
            if result["status"] == "committed":
                self.revisions.append(str(result["revision_id"]))
            self.results.append((op, base, str(result["status"])))
        elif op in ("edit_job", "paid_generation"):
            paid = op == "paid_generation"
            job, worker = await self._worker_job(conn, paid=paid)
            result = await self._finish(conn, job, worker, base, paid=paid)
            self.results.append((op, base, str(result["status"])))
        elif op in ("accept", "reject"):
            proposal = self.pick(ctx["pending"], choice)
            assert proposal is not None, "prepare guarantees a pending proposal"
            if op == "reject":
                await conn.execute(
                    "select reject_proposal($1, $2)", uuid.UUID(proposal), self.owner
                )
                return
            result = await accept(conn, proposal, ctx["head"], self.owner, self.key("acc"))
            if result["status"] == "committed":
                self.revisions.append(str(result["revision_id"]))
            self.results.append((op, ctx["head"], str(result["status"])))
        elif op == "reclaim":
            # The real path: the reaper re-queues a stale processing job (attempts
            # left), then another worker claims it with a new token.
            job, _worker, _token = self.pick(ctx["processing"], choice)
            await conn.fetch("select * from reap_stale_jobs(0)")
            worker = self.key("w")
            claimed = await conn.fetch("select * from claim_job($1, $2)", uuid.UUID(job), worker)
            if claimed:
                self.claims.append((job, worker, int(claimed[0]["attempts"])))
        elif op == "worker_fail":
            job, worker, token = self.pick(ctx["processing"], choice)
            await conn.fetchval(
                "select fail_job($1, $2, $3, 'pipeline', 'boom')", uuid.UUID(job), worker, token
            )
        elif op == "reap":
            await conn.fetch("select * from reap_stale_jobs(0)")
        elif op in ("render_ok", "render_fail"):
            render = self.pick(ctx["renders"], choice)
            assert render is not None, "prepare guarantees a queued render"
            worker = self.key("r")
            claimed = await conn.fetch("select * from claim_job($1, $2)", uuid.UUID(render), worker)
            if not claimed:
                return  # another operation of this round claimed it first
            token = int(claimed[0]["attempts"])
            if op == "render_fail":
                await conn.fetchval(
                    "select fail_job($1, $2, $3, 'render', 'chromium')",
                    uuid.UUID(render),
                    worker,
                    token,
                )
                return
            await self._publish(conn, claimed[0], worker, token)

    async def _publish(self, conn: Any, render: Any, worker: str, token: int) -> None:
        payload = render["payload"]
        payload = payload if isinstance(payload, dict) else json.loads(payload)
        for fmt in payload["formats"]:
            await register(
                conn,
                str(render["id"]),
                worker,
                self.document,
                str(payload["revision_id"]),
                fmt=fmt,
                sha=f"{self.counter % 16:x}" * 64,
                token=token,
            )
        await conn.fetchval(
            "select complete_job($1, $2, $3, '{}'::jsonb)", render["id"], worker, token
        )

    async def round(self, ops: list[tuple[str, int]]) -> None:
        await self.prepare(ops)
        ctx = {
            "head": await self.head(),
            "revisions": list(self.revisions),
            "pending": await self._pending(),
            "processing": await self._processing_workers(),
            "renders": await self._queued_renders(),
        }
        self.results = []

        async def guarded(conn: Any, op: str, choice: int) -> None:
            try:
                await self.run(conn, op, choice, ctx)
                event(f"{op}: ran")
            except asyncpg.PostgresError as exc:
                if not any(reason in str(exc) for reason in _RACE_REFUSALS):
                    raise AssertionError(f"{op} failed unexpectedly: {exc!r}") from exc
                event(f"{op}: refused in a race")

        # Wait for every operation of the round, then report the first failure:
        # a task left running would race into the next round's connections.
        outcomes = await asyncio.gather(
            *(
                guarded(self.pool[i % len(self.pool)], op, choice)
                for i, (op, choice) in enumerate(ops)
            ),
            return_exceptions=True,
        )
        for outcome in outcomes:
            if isinstance(outcome, BaseException):
                raise outcome
        self.oracle(ctx["head"])

    def oracle(self, head_before: str) -> None:
        """Linearizability: every write of a round competed against the same head."""

        reached = [r for r in self.results if r[2] in ("committed", "conflict", "proposed")]
        winners = [r for r in reached if r[2] == "committed"]
        assert len(winners) <= 1, (
            f"{len(winners)} writes committed against the same pre-round head: {winners}"
        )
        for _op, base, _status in winners:
            assert base == head_before, f"a write from a stale base committed: {winners}"
        if any(base == head_before for _op, base, _status in reached):
            assert len(winners) == 1, f"no write from the head committed: {self.results}"

    async def check(self) -> None:
        a = self.admin
        rows = await a.fetch(
            "select id, parent_revision_id, content_sha256,"
            " content_sha256 = _content_sha256(content) as hash_ok"
            " from document_revisions where document_id = $1",
            uuid.UUID(self.document),
        )
        parents: dict[str, str | None] = {}
        for row in rows:
            revision = str(row["id"])
            parent = str(row["parent_revision_id"]) if row["parent_revision_id"] else None
            parents[revision] = parent
            # Immutable: parent and content of every revision stay put.
            now = (parent, row["content_sha256"])
            assert self.seen.setdefault(revision, now) == now, "a revision changed"
            assert row["hash_ok"], f"stored content hash of {revision} does not recompute"
        # Retained: every revision ever seen still exists.
        assert set(self.seen) <= set(parents), "a revision disappeared"
        # One history: the parent chain from the head covers every revision.
        chain: list[str] = []
        cursor: str | None = await self.head()
        while cursor is not None:
            assert cursor not in chain, "the parent chain loops"
            chain.append(cursor)
            cursor = parents.get(cursor)
        assert set(chain) == set(parents), (
            f"{len(set(parents) - set(chain))} revision(s) are not on the head's parent chain"
        )
        # Retained: every job and proposal ever seen still exists.
        jobs = {
            str(r["id"])
            for r in await a.fetch(
                "select id from generation_jobs where project_id = $1", uuid.UUID(self.project)
            )
        }
        proposals = {
            str(r["id"])
            for r in await a.fetch(
                "select id from revision_proposals where document_id = $1",
                uuid.UUID(self.document),
            )
        }
        assert self.seen_ids["jobs"] <= jobs, "a job disappeared"
        assert self.seen_ids["proposals"] <= proposals, "a proposal disappeared"
        self.seen_ids["jobs"] |= jobs
        self.seen_ids["proposals"] |= proposals
        # The decks view is the head.
        view = await a.fetchval(
            "select deck_json from decks where project_id = $1", uuid.UUID(self.project)
        )
        head_content = await a.fetchval(
            "select r.content from documents d join document_revisions r on r.id = d.head_revision_id"
            " where d.id = $1",
            uuid.UUID(self.document),
        )
        assert view == head_content
        # A worker's revision or proposal exists only beside its settled job.
        orphaned = await a.fetchval(
            "select count(*) from ("
            " select substr(actor, 8)::uuid as job from document_revisions"
            "  where actor like 'worker:%' and accepted_from_proposal_id is null"
            " union all select source_job_id from revision_proposals where source_job_id is not null"
            ") w join generation_jobs j on j.id = w.job"
            " where j.status not in ('committed', 'completed', 'delivery_failed')"
        )
        assert orphaned == 0, "a worker's write exists beside a job that did not settle"
        # No settled generation or edit job lacks what it produced.
        lacking = await a.fetchval(
            "select count(*) from generation_jobs j"
            " where j.status in ('committed', 'completed', 'delivery_failed')"
            "   and j.job_type in ('presentation_generation', 'presentation_edit')"
            "   and coalesce(j.progress ->> 'outcome', '') <> 'unchanged'"
            "   and not exists (select 1 from document_revisions r where r.actor = 'worker:' || j.id)"
            "   and not exists (select 1 from revision_proposals q where q.source_job_id = j.id)"
        )
        assert lacking == 0, "a settled job lacks its revision"
        # A committed job is being delivered by a live render.
        undelivered = await a.fetchval(
            "select count(*) from generation_jobs p left join generation_jobs c"
            " on c.id = p.render_job_id where p.status = 'committed'"
            " and (c.id is null or c.status not in ('queued', 'processing'))"
        )
        assert undelivered == 0, "a committed job has no live render delivering it"
        # A completed render published every format it was asked for.
        incomplete = await a.fetchval(
            "select count(*) from generation_jobs j where j.job_type = 'presentation_render'"
            " and j.status = 'completed' and exists ("
            "  select 1 from jsonb_array_elements_text(j.payload -> 'formats') f"
            "  where not exists (select 1 from revision_exports e"
            "   where e.revision_id = (j.payload ->> 'revision_id')::uuid"
            "     and e.renderer_version = j.payload ->> 'renderer_version' and e.format = f))"
        )
        assert incomplete == 0, "a completed render is missing a format"
        await self._refunds_exactly_once(allow_in_flight=True)
        # Exports belong to render jobs only.
        assert (
            await a.fetchval(
                "select count(*) from revision_exports e join generation_jobs j on j.id = e.created_by_job"
                " where j.job_type <> 'presentation_render'"
            )
            == 0
        )
        # An accepted proposal points at a revision.
        assert (
            await a.fetchval(
                "select count(*) from revision_proposals where status = 'accepted'"
                " and accepted_revision_id is null"
            )
            == 0
        )

    async def _refunds_exactly_once(self, *, allow_in_flight: bool) -> None:
        rows = await self.admin.fetch(
            "select j.id, j.status, (j.payload ->> 'deducted_amount') is not null as paid,"
            " count(l.id) as n, coalesce(sum(l.amount), 0) as amount,"
            " bool_and(l.user_id is null or l.user_id = j.user_id) as to_owner"
            " from generation_jobs j"
            " left join credit_ledger l on l.generation_job_id = j.id and l.action = 'refund'"
            " where j.project_id = $1 group by j.id",
            uuid.UUID(self.project),
        )
        for row in rows:
            refunded = row["status"] in ("failed", "delivery_failed") and row["paid"]
            assert row["n"] == (1 if refunded else 0), (
                f"{row['status']} paid={row['paid']} refunds={row['n']}"
            )
            if refunded:
                assert row["amount"] == 5_000 and row["to_owner"], "refund amount or recipient"
            if row["paid"] and not allow_in_flight:
                assert row["status"] in ("completed", "failed", "delivery_failed"), (
                    f"a paid job ended {row['status']}: neither delivered nor refunded"
                )

    async def drain(self) -> None:
        """Drive every job to rest the way workers and the reaper would."""

        conn = self.pool[0]
        for _ in range(40):
            await conn.fetch("select * from reap_stale_jobs(0)")
            queued = await self.admin.fetch(
                "select id, job_type from generation_jobs where project_id = $1"
                " and status = 'queued' order by created_at",
                uuid.UUID(self.project),
            )
            if not queued:
                break
            for row in queued:
                worker = self.key("d")
                claimed = await conn.fetch("select * from claim_job($1, $2)", row["id"], worker)
                if not claimed:
                    continue
                token = int(claimed[0]["attempts"])
                if row["job_type"] == "presentation_render":
                    await self._publish(conn, claimed[0], worker, token)
                else:
                    # A re-queued generation whose worker is gone: it gives up.
                    await conn.fetchval(
                        "select fail_job($1, $2, $3, 'drain', 'abandoned')",
                        row["id"],
                        worker,
                        token,
                    )
        await conn.fetch("select * from reap_stale_jobs(0)")
        active = await self.admin.fetchval(
            "select count(*) from generation_jobs where project_id = $1"
            " and status in ('queued', 'processing', 'committed')",
            uuid.UUID(self.project),
        )
        assert active == 0, "jobs did not come to rest"


@settings(
    max_examples=25,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow],
)
@given(plan=rounds())
async def test_concurrent_lifecycle_preserves_every_invariant(
    db: Db, plan: list[list[tuple[str, int]]]
) -> None:
    world = await Lifecycle(db).build()
    for ops in plan:
        await world.round(ops)
        await world.check()
    await world.drain()
    await world.check()
    # A job that took money ends completed (delivered) or refunded exactly once.
    await world._refunds_exactly_once(allow_in_flight=False)  # pyright: ignore[reportPrivateUsage]
    for conn in [*world.pool, world.admin]:
        await conn.close()
