"""Migration 016 on real PostgreSQL: the canonical write path (ADR 0001, tests a–m).

Concurrency tests use two connections, so the row lock in commit_revision is the
real one. Callers act as PostgREST does (SET ROLE + request.jwt.claims).
"""

from __future__ import annotations

import asyncio
import json
import os
import statistics
import time
import uuid
from pathlib import Path
from typing import Any, cast

import asyncpg  # pyright: ignore[reportMissingTypeStubs]
import pytest

from tests.db.conftest import CURRENT
from tests.db.support import Db, accept, commit, ensure_document, finish, head, register

pytestmark = pytest.mark.skipif(
    not CURRENT, reason="exercises migration 016's functions (current schema only)"
)

OWNER_TG = 111_000_111
OTHER_TG = 222_000_222


class World:
    """User A owns project P (document D, head R0); user B owns nothing of A's."""

    def __init__(self, db: Db) -> None:
        self.db = db

    async def build(self) -> World:
        self.owner = await self.db.user(OWNER_TG)
        self.other = await self.db.user(OTHER_TG)
        self.project = await self.db.project(self.owner)
        self.service = await self.db.as_role("service_role")
        self.document = await ensure_document(self.service, self.project, self.owner)
        first = await commit(
            self.service,
            self.document,
            None,
            {"title": "R0"},
            kind="manual",
            actor=self.owner,
            key="r0",
        )
        self.r0 = str(first["revision_id"])
        return self

    async def worker_job(self, **payload: Any) -> str:
        return await self.db.job(
            self.project, self.owner, job_type="presentation_edit", payload=payload
        )


@pytest.fixture
async def world(db: Db) -> World:
    return await World(db).build()


async def _refused(code: str, call: Any) -> None:
    with pytest.raises(asyncpg.PostgresError) as info:
        await call
    assert code in str(info.value)


# ------------------------------------------------------------------ basics


async def test_a_commit_on_the_head_advances_it_and_the_decks_view_follows(world: World) -> None:
    result = await commit(
        world.service,
        world.document,
        world.r0,
        {"title": "R1"},
        kind="manual",
        actor=world.owner,
        key="r1",
    )
    assert result["status"] == "committed"
    assert await head(world.service, world.document) == result["revision_id"]
    row = await world.service.fetchrow(
        "select deck_json, revision_id from decks where project_id = $1", uuid.UUID(world.project)
    )
    assert row["deck_json"] == {"title": "R1"} and str(row["revision_id"]) == result["revision_id"]
    parent = await world.service.fetchval(
        "select parent_revision_id from document_revisions where id = $1",
        uuid.UUID(result["revision_id"]),
    )
    assert str(parent) == world.r0


async def test_b_bot_edit_after_web_import_advances_the_head_the_web_reads(world: World) -> None:
    imported = await commit(
        world.service,
        world.document,
        world.r0,
        {"title": "imported"},
        kind="import",
        actor="system:test",
        key="import",
    )
    bot = await commit(
        world.service,
        world.document,
        imported["revision_id"],
        {"title": "bot edit"},
        kind="bot_edit",
        actor=f"bot:{OWNER_TG}",
        key="bot-1",
    )
    assert bot["status"] == "committed"
    as_owner = await world.db.as_role("authenticated", world.owner)
    web = await as_owner.fetchrow(
        "select deck_json from decks where project_id = $1", uuid.UUID(world.project)
    )
    assert web["deck_json"] == {"title": "bot edit"}


async def test_c_concurrent_manual_save_and_ai_edit_on_one_base_lose_nothing(world: World) -> None:
    job = await world.worker_job()
    manual_conn = await world.db.as_role("service_role")
    ai_conn = await world.db.as_role("service_role")
    await manual_conn.execute("begin")
    manual = await commit(
        manual_conn,
        world.document,
        world.r0,
        {"title": "manual"},
        kind="manual",
        actor=world.owner,
        key="manual",
    )
    ai_task = asyncio.create_task(
        finish(
            ai_conn,
            job,
            "w1",
            1,
            world.r0,
            {"title": "ai"},
            kind="ai_edit",
            key="ai",
        )
    )
    await asyncio.sleep(0.3)
    assert not ai_task.done()  # blocked on the document row lock
    await manual_conn.execute("commit")
    ai = await ai_task

    assert manual["status"] == "committed" and ai["status"] == "proposed"
    assert await head(world.service, world.document) == manual["revision_id"]
    proposal = await world.service.fetchrow(
        "select base_revision_id, content, kind, source_job_id from revision_proposals where id = $1",
        uuid.UUID(ai["proposal_id"]),
    )
    assert str(proposal["base_revision_id"]) == world.r0
    assert proposal["content"] == {"title": "ai"} and proposal["kind"] == "ai_edit"
    assert str(proposal["source_job_id"]) == job


async def test_d_concurrent_manual_saves_one_commits_one_conflicts(world: World) -> None:
    first_conn = await world.db.as_role("service_role")
    second_conn = await world.db.as_role("service_role")
    await first_conn.execute("begin")
    first = await commit(
        first_conn,
        world.document,
        world.r0,
        {"title": "one"},
        kind="manual",
        actor=world.owner,
        key="one",
    )
    second_task = asyncio.create_task(
        commit(
            second_conn,
            world.document,
            world.r0,
            {"title": "two"},
            kind="autosave",
            actor=world.owner,
            key="two",
        )
    )
    await asyncio.sleep(0.3)
    await first_conn.execute("commit")
    second = await second_task

    assert first["status"] == "committed"
    assert second["status"] == "conflict"
    assert second["head_revision_id"] == first["revision_id"]
    assert second["revision_id"] is None
    count = await world.service.fetchval(
        "select count(*) from document_revisions where document_id = $1", uuid.UUID(world.document)
    )
    assert count == 2


# ------------------------------------------------------------ idempotency (e)


async def test_e_retried_commit_is_a_duplicate_and_key_reuse_is_an_error(world: World) -> None:
    first = await commit(
        world.service,
        world.document,
        world.r0,
        {"title": "x"},
        kind="manual",
        actor=world.owner,
        key="k",
    )
    again = await commit(
        world.service,
        world.document,
        world.r0,
        {"title": "x"},
        kind="manual",
        actor=world.owner,
        key="k",
    )
    assert again["status"] == "duplicate" and again["revision_id"] == first["revision_id"]
    await _refused(
        "idempotency_key_reused",
        commit(
            world.service,
            world.document,
            world.r0,
            {"title": "y"},
            kind="manual",
            actor=world.owner,
            key="k",
        ),
    )


async def test_e_retried_proposal_and_accept_and_register_are_idempotent(world: World) -> None:
    job = await world.worker_job()
    await commit(
        world.service,
        world.document,
        world.r0,
        {"title": "moved"},
        kind="manual",
        actor=world.owner,
        key="move",
    )
    proposed = await finish(
        world.service,
        job,
        "w1",
        1,
        world.r0,
        {"title": "ai"},
        kind="ai_edit",
        key="ai",
    )
    again = await finish(
        world.service,
        job,
        "w1",
        1,
        world.r0,
        {"title": "ai"},
        kind="ai_edit",
        key="ai",
    )
    assert again["status"] == "proposed" and again["proposal_id"] == proposed["proposal_id"]

    current = await head(world.service, world.document)
    accepted = await accept(world.service, proposed["proposal_id"], current, world.owner, "acc")
    replay = await accept(world.service, proposed["proposal_id"], current, world.owner, "acc")
    assert replay["status"] == "duplicate" and replay["revision_id"] == accepted["revision_id"]

    render = await world.db.job(
        world.project, world.owner, payload={"revision_id": accepted["revision_id"]}
    )
    assert (
        await register(world.service, render, "w1", world.document, accepted["revision_id"])
        == "registered"
    )
    assert (
        await register(world.service, render, "w1", world.document, accepted["revision_id"])
        == "existing"
    )
    # First writer wins: other bytes for the same export never replace it.
    assert (
        await register(
            world.service, render, "w1", world.document, accepted["revision_id"], sha="b" * 64
        )
        == "existing"
    )
    stored = await world.service.fetchval(
        "select sha256 from revision_exports where revision_id = $1",
        uuid.UUID(accepted["revision_id"]),
    )
    assert stored == "a" * 64


async def test_identical_content_is_unchanged_and_does_not_turn_an_ai_edit_into_a_proposal(
    world: World,
) -> None:
    job = await world.worker_job()
    same = await commit(
        world.service,
        world.document,
        world.r0,
        {"title": "R0"},
        kind="autosave",
        actor=world.owner,
        key="same",
    )
    assert same["status"] == "unchanged" and same["revision_id"] == world.r0
    assert await head(world.service, world.document) == world.r0
    ai = await finish(
        world.service,
        job,
        "w1",
        1,
        world.r0,
        {"title": "ai"},
        kind="ai_edit",
        key="ai",
    )
    assert ai["status"] == "committed"


# --------------------------------------------------------- exports (f, g, m)


async def test_f_a_worker_without_the_claim_cannot_register(world: World) -> None:
    render = await world.db.job(
        world.project, world.owner, worker="w2", payload={"revision_id": world.r0}
    )
    await _refused("claim_lost", register(world.service, render, "w1", world.document, world.r0))
    done = await world.db.job(
        world.project, world.owner, status="completed", payload={"revision_id": world.r0}
    )
    await _refused("claim_lost", register(world.service, done, "w1", world.document, world.r0))
    rows = await world.service.fetchval("select count(*) from revision_exports")
    assert rows == 0


async def test_g_a_job_for_revision_x_cannot_register_revision_y(world: World) -> None:
    y = await commit(
        world.service,
        world.document,
        world.r0,
        {"title": "Y"},
        kind="manual",
        actor=world.owner,
        key="y",
    )
    render = await world.db.job(world.project, world.owner, payload={"revision_id": world.r0})
    await _refused(
        "job_revision_mismatch",
        register(world.service, render, "w1", world.document, y["revision_id"]),
    )
    bad_key = world.service.fetchval(
        "select status from register_export($1, 'w1', 1, $2, 'html', 'pw-test',"
        " 'exports/elsewhere.html', $3, 10, null)",
        uuid.UUID(render),
        uuid.UUID(world.r0),
        "a" * 64,
    )
    await _refused("invalid_storage_key", bad_key)


async def test_a_an_older_revisions_exports_never_change_the_heads(world: World) -> None:
    newer = await commit(
        world.service,
        world.document,
        world.r0,
        {"title": "new"},
        kind="manual",
        actor=world.owner,
        key="new",
    )
    render = await world.db.job(world.project, world.owner, payload={"revision_id": world.r0})
    await register(world.service, render, "w1", world.document, world.r0)
    head_exports = await world.service.fetchval(
        "select count(*) from revision_exports where revision_id = $1",
        uuid.UUID(newer["revision_id"]),
    )
    assert head_exports == 0


async def test_m_project_deleted_mid_job_fails_cleanly(world: World) -> None:
    render = await world.db.job(world.project, world.owner, payload={"revision_id": world.r0})
    admin = await world.db.admin()
    await admin.execute("delete from projects where id = $1", uuid.UUID(world.project))
    await _refused("claim_lost", register(world.service, render, "w1", world.document, world.r0))
    await _refused(
        "document_not_found",
        commit(
            world.service,
            world.document,
            None,
            {"title": "late"},
            kind="manual",
            actor=world.owner,
            key="late",
        ),
    )


async def test_h_a_job_can_hold_only_one_refund(world: World) -> None:
    job = await world.worker_job()
    admin = await world.db.admin()
    insert = (
        "insert into credit_ledger (user_id, amount, reason, action, generation_job_id, status)"
        " values ($1, 5000, 'refund', 'refund', $2, 'confirmed')"
    )
    await admin.execute(insert, uuid.UUID(world.owner), uuid.UUID(job))
    with pytest.raises(asyncpg.UniqueViolationError):
        await admin.execute(insert, uuid.UUID(world.owner), uuid.UUID(job))


# ---------------------------------------------------------- isolation (j, k)


async def test_j_another_user_cannot_read_or_write_the_document(world: World) -> None:
    job = await world.worker_job()
    await commit(
        world.service,
        world.document,
        world.r0,
        {"title": "moved"},
        kind="manual",
        actor=world.owner,
        key="m",
    )
    proposal = await finish(
        world.service,
        job,
        "w1",
        1,
        world.r0,
        {"title": "ai"},
        kind="ai_edit",
        key="ai",
    )
    render = await world.db.job(world.project, world.owner, payload={"revision_id": world.r0})
    await register(world.service, render, "w1", world.document, world.r0)

    stranger = await world.db.as_role("authenticated", world.other)
    for table in (
        "documents",
        "document_revisions",
        "revision_proposals",
        "revision_exports",
        "decks",
    ):
        assert await stranger.fetchval(f"select count(*) from {table}") == 0, table
    await _refused(
        "not_document_owner",
        commit(
            stranger,
            world.document,
            world.r0,
            {"title": "x"},
            kind="manual",
            actor=world.other,
            key="s",
        ),
    )
    await _refused(
        "not_document_owner", accept(stranger, proposal["proposal_id"], None, world.other, "s-acc")
    )

    owner = await world.db.as_role("authenticated", world.owner)
    assert await owner.fetchval("select count(*) from document_revisions") >= 2
    assert await owner.fetchval("select count(*) from revision_exports") == 1
    await _refused(
        "actor_mismatch",
        commit(owner, world.document, None, {"t": 1}, kind="manual", actor=world.other, key="a"),
    )
    await _refused(
        "kind_not_allowed",
        commit(owner, world.document, None, {"t": 1}, kind="ai_edit", actor=world.owner, key="b"),
    )


@pytest.mark.parametrize("role", ["authenticated", "service_role"])
async def test_k_no_application_role_can_write_the_tables_directly(world: World, role: str) -> None:
    conn = await world.db.as_role(role, world.owner)
    statements = [
        (
            "insert into decks (project_id, title, language, audience, deck_json)"
            " values ($1, 't', 'uz', 'talaba', '{}')",
            [uuid.UUID(world.project)],
        ),
        (
            "insert into document_revisions (document_id, idempotency_key, content, content_sha256, kind,"
            " schema_version, actor) values ($1, 'x', '{}', repeat('a', 64), 'manual', 1, $2)",
            [uuid.UUID(world.document), world.owner],
        ),
        (
            "update document_revisions set content = '{}' where document_id = $1",
            [uuid.UUID(world.document)],
        ),
        ("update documents set head_revision_id = null where id = $1", [uuid.UUID(world.document)]),
        ("delete from document_revisions where document_id = $1", [uuid.UUID(world.document)]),
        (
            "insert into revision_exports (revision_id, format, renderer_version, storage_key, sha256,"
            " byte_size) values ($1, 'html', 'pw-x', 'k', repeat('a', 64), 1)",
            [uuid.UUID(world.r0)],
        ),
        ("update revision_proposals set status = 'accepted'", []),
    ]
    for sql, args in statements:
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await conn.execute(sql, *args)


# ---------------------------------------------------------------- accept


async def test_accept_replaces_the_head_the_user_saw_and_a_moved_head_conflicts(
    world: World,
) -> None:
    job = await world.worker_job()
    user_head = await commit(
        world.service,
        world.document,
        world.r0,
        {"title": "by hand"},
        kind="manual",
        actor=world.owner,
        key="hand",
    )
    proposal = await finish(
        world.service,
        job,
        "w1",
        1,
        world.r0,
        {"title": "ai"},
        kind="ai_edit",
        key="ai",
    )

    moved = await commit(
        world.service,
        world.document,
        user_head["revision_id"],
        {"title": "again"},
        kind="manual",
        actor=world.owner,
        key="again",
    )
    stale = await accept(
        world.service, proposal["proposal_id"], user_head["revision_id"], world.owner, "a1"
    )
    assert stale["status"] == "conflict" and stale["head_revision_id"] == moved["revision_id"]

    done = await accept(
        world.service, proposal["proposal_id"], moved["revision_id"], world.owner, "a2"
    )
    assert done["status"] == "committed"
    row = await world.service.fetchrow(
        "select parent_revision_id, kind, accepted_from_proposal_id, content from document_revisions"
        " where id = $1",
        uuid.UUID(done["revision_id"]),
    )
    assert str(row["parent_revision_id"]) == moved["revision_id"]
    assert (
        row["kind"] == "ai_edit"
        and str(row["accepted_from_proposal_id"]) == proposal["proposal_id"]
    )
    assert row["content"] == {"title": "ai"}
    status = await world.service.fetchval(
        "select status from revision_proposals where id = $1", uuid.UUID(proposal["proposal_id"])
    )
    assert status == "accepted"
    replaced = await world.service.fetchval(
        "select content from document_revisions where id = $1", uuid.UUID(moved["revision_id"])
    )
    assert replaced == {"title": "again"}  # still restorable from history


async def test_accept_refuses_a_schema_mismatch(world: World) -> None:
    job = await world.worker_job()
    await commit(
        world.service,
        world.document,
        world.r0,
        {"title": "moved"},
        kind="manual",
        actor=world.owner,
        key="m",
    )
    proposal = await finish(
        world.service,
        job,
        "w1",
        1,
        world.r0,
        {"title": "ai"},
        kind="ai_edit",
        key="ai",
    )
    admin = await world.db.admin()
    await admin.execute(
        "update revision_proposals set schema_version = 2 where id = $1",
        uuid.UUID(proposal["proposal_id"]),
    )
    current = await head(world.service, world.document)
    await _refused(
        "proposal_schema_mismatch",
        accept(world.service, proposal["proposal_id"], current, world.owner, "acc"),
    )


# ---------------------------------------------------------------- limits


async def test_content_limits_and_schema_versions_are_enforced(world: World) -> None:
    await _refused(
        "unsupported_schema_version",
        commit(
            world.service,
            world.document,
            world.r0,
            {"t": 1},
            kind="manual",
            actor=world.owner,
            key="v",
            schema_version=7,
        ),
    )
    await _refused(
        "content_too_large",
        commit(
            world.service,
            world.document,
            world.r0,
            {"blob": "x" * 2_200_000},
            kind="manual",
            actor=world.owner,
            key="big",
        ),
    )
    await _refused(
        "invalid_revision_kind",
        commit(
            world.service,
            world.document,
            world.r0,
            {"t": 1},
            kind="whatever",
            actor=world.owner,
            key="kind",
        ),
    )


async def test_a_worker_writes_only_through_its_fenced_finish(world: World) -> None:
    live = await world.worker_job()
    await _refused(
        "worker_must_finish_job",
        commit(
            world.service,
            world.document,
            world.r0,
            {"t": 1},
            kind="ai_edit",
            actor=f"worker:{live}",
            key="w",
        ),
    )
    finished = await world.db.job(
        world.project, world.owner, status="completed", job_type="presentation_edit"
    )
    await _refused(
        "claim_lost",
        finish(world.service, finished, "w1", 1, world.r0, {"t": 1}, kind="ai_edit", key="w"),
    )
    await _refused(
        "kind_not_allowed",
        finish(world.service, live, "w1", 1, world.r0, {"t": 1}, kind="manual", key="m"),
    )
    await _refused(
        "not_document_owner",
        commit(
            world.service,
            world.document,
            world.r0,
            {"t": 1},
            kind="bot_edit",
            actor=f"bot:{OTHER_TG}",
            key="b",
        ),
    )
    assert await head(world.service, world.document) == world.r0


# ------------------------------------------------- NULL safety (B1-FIX audit)


async def test_a_render_job_with_no_target_key_cannot_be_created(world: World) -> None:
    # A CHECK passes when its expression is NULL; the render-job CHECK is
    # coalesced so an absent key fails it like a JSON null does.
    admin = await world.db.admin()
    with pytest.raises(asyncpg.CheckViolationError, match="generation_jobs_render_payload_check"):
        await admin.execute(
            "insert into generation_jobs (project_id, user_id, job_type, status, payload)"
            " values ($1, $2, 'presentation_render', 'queued',"
            ' \'{"renderer_version": "pw-test", "formats": ["html"]}\'::jsonb)',
            uuid.UUID(world.project),
            uuid.UUID(world.owner),
        )


async def test_a_null_document_kind_is_refused(world: World) -> None:
    await _refused(
        "invalid_document_kind",
        world.service.fetchval(
            "select ensure_document($1, null, $2)", uuid.UUID(world.project), world.owner
        ),
    )


async def test_a_finish_with_a_null_kind_or_format_writes_nothing(world: World) -> None:
    job = await world.worker_job()
    await _refused(
        "kind_not_allowed",
        world.service.fetchrow(
            "select * from finish_generation_job($1, 'w1', 1, $2, '{\"t\": 1}'::jsonb,"
            " null, 1, 'k', null, '{}')",
            uuid.UUID(job),
            uuid.UUID(world.r0),
        ),
    )
    await _refused(
        "invalid_render_formats",
        finish(
            world.service,
            job,
            "w1",
            1,
            world.r0,
            {"t": 2},
            kind="ai_edit",
            key="k2",
            render_formats=["html", cast(str, None)],
        ),
    )
    assert await head(world.service, world.document) == world.r0
    status = await world.service.fetchval(
        "select status from generation_jobs where id = $1", uuid.UUID(job)
    )
    assert status == "processing"


# ---------------------------------------------------------------- latency


async def test_commit_latency_at_200_kb(world: World) -> None:
    """Reported, not gated: median commit_revision time for a 200 KB deck."""

    body = {"slides": [{"slide_id": f"s{i}", "text": "x" * 1000} for i in range(200)]}
    assert 190_000 < len(json.dumps(body)) < 220_000
    timings: list[float] = []
    base = world.r0
    for i in range(20):
        body["slides"][0]["text"] = f"edit {i}" + "x" * 994
        started = time.perf_counter()
        result = await commit(
            world.service,
            world.document,
            base,
            body,
            kind="autosave",
            actor=world.owner,
            key=f"lat-{i}",
        )
        timings.append((time.perf_counter() - started) * 1000)
        base = result["revision_id"]
    report = {
        "median_ms": round(statistics.median(timings), 2),
        "p95_ms": round(sorted(timings)[18], 2),
    }
    print(f"\ncommit_revision 200KB latency: {report}")
    out = os.environ.get("NASHR_TEST_ARTIFACTS")
    if out:
        Path(out).mkdir(parents=True, exist_ok=True)
        (Path(out) / "commit_latency.json").write_text(json.dumps(report))
