"""Random interleavings on real PostgreSQL (test n).

``test_n_interleaved_writers_never_lose_work`` runs 2–6 writers serially against
an exact model of the head: the head is the last committed revision, no
committed revision is lost, every losing ai_edit / regeneration write is a
proposal, and the decks view equals the head.

``test_concurrent_lifecycle_preserves_every_invariant`` (B1-FIX, Codex finding 8)
runs rounds of 2–4 operations at once on separate connections: manual saves,
worker finishes (edit and paid generation), accept and reject, claim reclaim and
expiry, worker failure, the reaper and render registration. After every round:
revisions are immutable, a worker's write exists only beside its completed job,
no completed job lacks its revision, every failed paid job has exactly one refund
and nothing else has one, exports belong to render jobs, accepted proposals point
at a revision, and the decks view is the head.
"""

from __future__ import annotations

import asyncio
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


# ----------------------------------------------- concurrent lifecycle (B1-FIX)

# Errors an operation may legitimately meet in a race; anything else (a deadlock,
# a serialization failure, an unexpected refusal) fails the property.
_RACE_REFUSALS = (
    "claim_lost",
    "claim_expired",
    "proposal_not_pending",
    "conflict",
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
    "expire",
    "worker_fail",
    "reap",
    "render",
]


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
        self.jobs: list[tuple[str, str, int]] = []  # (job, worker, token)
        self.counter = 0
        return self

    def key(self, prefix: str) -> str:
        self.counter += 1
        return f"{prefix}-{self.counter}"

    def pick(self, items: list[Any], choice: int) -> Any:
        return items[choice % len(items)] if items else None

    async def run(self, conn: Any, op: str, choice: int) -> None:
        base = self.pick(self.revisions, choice)
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
            if result["revision_id"]:
                self.revisions.append(str(result["revision_id"]))
        elif op in ("edit_job", "paid_generation"):
            paid = op == "paid_generation"
            worker = self.key("w")
            job = await self.db.job(
                self.project,
                self.owner,
                job_type="presentation_generation" if paid else "presentation_edit",
                worker=worker,
                payload={"deducted_amount": 5_000} if paid else {},
                conn=conn,
            )
            self.jobs.append((job, worker, 1))
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
                render_formats=["html"],
            )
            if result["revision_id"]:
                self.revisions.append(str(result["revision_id"]))
        elif op in ("accept", "reject"):
            pending = [
                str(r["id"])
                for r in await conn.fetch(
                    "select id from revision_proposals where status = 'pending'"
                    " and document_id = $1 order by created_at",
                    uuid.UUID(self.document),
                )
            ]
            proposal = self.pick(pending, choice)
            if proposal is None:
                return
            if op == "reject":
                await conn.execute(
                    "select reject_proposal($1, $2)", uuid.UUID(proposal), self.owner
                )
                return
            current = await head(conn, self.document)
            result = await accept(conn, proposal, current, self.owner, self.key("acc"))
            if result["revision_id"]:
                self.revisions.append(str(result["revision_id"]))
        elif op == "reclaim" and self.jobs:
            job, _worker, token = self.pick(self.jobs, choice)
            worker = self.key("w")
            updated = await conn.fetchval(
                "update generation_jobs set worker_id = $2, attempts = attempts + 1,"
                " heartbeat_at = now() where id = $1 and status = 'processing' returning attempts",
                uuid.UUID(job),
                worker,
            )
            if updated is not None:
                self.jobs.append((job, worker, int(updated)))
        elif op == "expire" and self.jobs:
            job, _worker, _token = self.pick(self.jobs, choice)
            await conn.execute(
                "update generation_jobs set heartbeat_at = now() - interval '10 minutes'"
                " where id = $1",
                uuid.UUID(job),
            )
        elif op == "worker_fail" and self.jobs:
            job, worker, token = self.pick(self.jobs, choice)
            await conn.fetchval(
                "select fail_job($1, $2, $3, 'pipeline', 'boom')", uuid.UUID(job), worker, token
            )
        elif op == "reap":
            await conn.fetch("select * from reap_stale_jobs(60)")
        elif op == "render":
            revision = self.pick(self.revisions, choice)
            worker = self.key("r")
            job = await self.db.job(
                self.project,
                self.owner,
                worker=worker,
                payload={"revision_id": revision},
                conn=conn,
            )
            await register(conn, job, worker, self.document, revision, sha=f"{choice:x}" * 64)
            await conn.fetchval(
                "select complete_job($1, $2, 1, '{}'::jsonb)", uuid.UUID(job), worker
            )

    async def round(self, ops: list[tuple[str, int]]) -> None:
        async def guarded(conn: Any, op: str, choice: int) -> None:
            try:
                await self.run(conn, op, choice)
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

    async def check(self) -> None:
        a = self.admin
        # Revisions are immutable: parent and content of every revision stay put.
        for row in await a.fetch(
            "select id, parent_revision_id, content_sha256 from document_revisions"
            " where document_id = $1",
            uuid.UUID(self.document),
        ):
            now = (
                str(row["parent_revision_id"]) if row["parent_revision_id"] else None,
                row["content_sha256"],
            )
            assert self.seen.setdefault(str(row["id"]), now) == now, "a revision changed"
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
        # A worker's revision or proposal exists only beside its completed job.
        orphaned = await a.fetchval(
            "select count(*) from ("
            " select substr(actor, 8)::uuid as job from document_revisions"
            "  where actor like 'worker:%' and accepted_from_proposal_id is null"
            " union all select source_job_id from revision_proposals where source_job_id is not null"
            ") w join generation_jobs j on j.id = w.job where j.status <> 'completed'"
        )
        assert orphaned == 0, "a worker's write exists beside a job that did not complete"
        # No completed generation or edit job lacks what it produced.
        lacking = await a.fetchval(
            "select count(*) from generation_jobs j"
            " where j.status = 'completed'"
            "   and j.job_type in ('presentation_generation', 'presentation_edit')"
            "   and coalesce(j.progress ->> 'outcome', '') <> 'unchanged'"
            "   and not exists (select 1 from document_revisions r where r.actor = 'worker:' || j.id)"
            "   and not exists (select 1 from revision_proposals q where q.source_job_id = j.id)"
        )
        assert lacking == 0, "a completed job lacks its revision"
        # Every failed paid job has exactly one refund; nothing else has any.
        refunds = await a.fetch(
            "select j.status, (j.payload ->> 'deducted_amount') is not null as paid,"
            " count(l.id) as n from generation_jobs j"
            " left join credit_ledger l on l.generation_job_id = j.id and l.action = 'refund'"
            " where j.project_id = $1 group by j.id",
            uuid.UUID(self.project),
        )
        for row in refunds:
            expected = 1 if row["status"] == "failed" and row["paid"] else 0
            assert row["n"] == expected, f"{row['status']} paid={row['paid']} refunds={row['n']}"
        # Exports belong to render jobs only, once per identity.
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
    for conn in [*world.pool, world.admin]:
        await conn.close()
