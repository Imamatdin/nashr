"""Bugs ADR 0001 fixes, written once and run against BOTH schemas.

CI runs this module twice: with ``NASHR_TEST_SCHEMA=legacy`` (migrations
001–015, the pre-change database plus what the pre-change Python did against
it) where every test is expected to FAIL, and against the full chain where
every test must PASS. The ``Legacy`` adapter reproduces the old write paths
exactly: ``save_deck`` upserted ``decks``; renders upserted ``generated_files``
by (project, format) without any claim check; ``commit_document_revision``
raised ``stale_revision`` for every stale writer, AI or not.
"""

from __future__ import annotations

import uuid
from typing import Any

import asyncpg  # pyright: ignore[reportMissingTypeStubs]
import pytest

from tests.db.conftest import LEGACY
from tests.db.support import Db, commit, ensure_document, export_key, register

OWNER_TG = 333_000_333


class Legacy:
    """What the pre-change code did, on the pre-change schema."""

    def __init__(self, db: Db, conn: Any, project: str, owner: str) -> None:
        self.db, self.conn, self.project, self.owner = db, conn, project, owner

    async def start(self, content: dict[str, Any]) -> tuple[str, str]:
        row = await self.conn.fetchrow(
            "select * from create_document_if_missing($1, 'presentation', 1, $2::jsonb, $3, 'init')",
            uuid.UUID(self.project),
            content,
            uuid.UUID(self.owner),
        )
        return str(row["document_id"]), str(row["revision_id"])

    async def manual(self, doc: str, base: str, content: dict[str, Any], key: str) -> str | None:
        row = await self.conn.fetchrow(
            "select * from commit_document_revision($1, $2, $3::jsonb, $4, $5)",
            uuid.UUID(doc),
            uuid.UUID(base),
            content,
            uuid.UUID(self.owner),
            key,
        )
        return str(row["revision_id"])

    async def ai_edit(self, doc: str, base: str, content: dict[str, Any], key: str) -> None:
        # The web AI edit job: commit_presentation_revision_and_deck, which
        # raised stale_revision (the paid output was simply lost).
        try:
            await self.conn.fetchrow(
                "select * from commit_presentation_revision_and_deck($1, $2, $3::jsonb, $4, $5)",
                uuid.UUID(doc),
                uuid.UUID(base),
                content,
                uuid.UUID(self.owner),
                key,
            )
        except asyncpg.PostgresError:
            return

    async def bot_edit(self, doc: str, base: str, content: dict[str, Any]) -> None:
        # save_deck: upsert the decks row; documents untouched.
        await self.conn.execute(
            "insert into decks (project_id, title, language, audience, deck_json)"
            " values ($1, 'T', 'uz', 'talaba', $2::jsonb)"
            " on conflict (project_id) do update set deck_json = excluded.deck_json",
            uuid.UUID(self.project),
            content,
        )

    async def web_head(self, doc: str) -> Any:
        row = await self.conn.fetchrow(
            "select r.content from documents d join document_revisions r on r.id = d.head_revision_id"
            " where d.id = $1",
            uuid.UUID(doc),
        )
        return row["content"]

    async def publish(self, doc: str, revision: str, job: str, worker: str) -> None:
        # render() uploaded to generated/{project}/presentation.html and upserted
        # generated_files by (project, format): no claim, no revision.
        await self.conn.execute(
            "insert into generated_files (project_id, file_type, storage_path, file_size)"
            " values ($1, 'html', $2, 10)"
            " on conflict (project_id, file_type) do update set storage_path = excluded.storage_path",
            uuid.UUID(self.project),
            f"generated/{self.project}/presentation.html#{revision}",
        )

    async def downloads_for(self, doc: str, revision: str) -> list[str]:
        rows = await self.conn.fetch(
            "select storage_path from generated_files where project_id = $1",
            uuid.UUID(self.project),
        )
        return [str(r["storage_path"]) for r in rows]

    async def proposals(self, doc: str) -> int:
        exists = await self.conn.fetchval(
            "select to_regclass('public.revision_proposals') is not null"
        )
        if not exists:
            return 0
        return int(await self.conn.fetchval("select count(*) from revision_proposals"))

    async def reuse_key(self, doc: str, base: str) -> None:
        await self.manual(doc, base, {"title": "A"}, "same")
        await self.manual(doc, base, {"title": "B"}, "same")


class Current:
    """The migration-016 write paths."""

    def __init__(self, db: Db, conn: Any, project: str, owner: str) -> None:
        self.db, self.conn, self.project, self.owner = db, conn, project, owner

    async def start(self, content: dict[str, Any]) -> tuple[str, str]:
        doc = await ensure_document(self.conn, self.project, self.owner)
        row = await commit(
            self.conn, doc, None, content, kind="manual", actor=self.owner, key="init"
        )
        return doc, str(row["revision_id"])

    async def manual(self, doc: str, base: str, content: dict[str, Any], key: str) -> str | None:
        row = await commit(self.conn, doc, base, content, kind="manual", actor=self.owner, key=key)
        return row["revision_id"]

    async def ai_edit(self, doc: str, base: str, content: dict[str, Any], key: str) -> None:
        job = await self.db.job(self.project, self.owner, job_type="presentation_edit")
        await commit(self.conn, doc, base, content, kind="ai_edit", actor=f"worker:{job}", key=key)

    async def bot_edit(self, doc: str, base: str, content: dict[str, Any]) -> None:
        await commit(
            self.conn,
            doc,
            base,
            content,
            kind="bot_edit",
            actor=f"bot:{OWNER_TG}",
            key=f"bot-{uuid.uuid4()}",
        )

    async def web_head(self, doc: str) -> Any:
        return await self.conn.fetchval(
            "select deck_json from decks where project_id = $1", uuid.UUID(self.project)
        )

    async def publish(self, doc: str, revision: str, job: str, worker: str) -> None:
        await register(self.conn, job, worker, doc, revision)

    async def downloads_for(self, doc: str, revision: str) -> list[str]:
        rows = await self.conn.fetch(
            "select storage_key from revision_exports where revision_id = $1", uuid.UUID(revision)
        )
        return [str(r["storage_key"]) for r in rows]

    async def proposals(self, doc: str) -> int:
        return int(await self.conn.fetchval("select count(*) from revision_proposals"))

    async def reuse_key(self, doc: str, base: str) -> None:
        await self.manual(doc, base, {"title": "A"}, "same")
        await self.manual(doc, base, {"title": "B"}, "same")


async def _system(db: Db) -> tuple[Any, str, str]:
    owner = await db.user(OWNER_TG)
    project = await db.project(owner)
    conn = await db.as_role("service_role")
    adapter = (Legacy if LEGACY else Current)(db, conn, project, owner)
    return adapter, project, owner


async def test_a_rendering_an_older_revision_does_not_change_the_heads_downloads(db: Db) -> None:
    system, project, owner = await _system(db)
    doc, older = await system.start({"title": "older"})
    newer = await system.manual(doc, older, {"title": "newer"}, "newer")
    job_new = await db.job(project, owner, payload={"revision_id": newer})
    await system.publish(doc, newer, job_new, "w1")
    before = await system.downloads_for(doc, newer)
    # The first render finished before the second was asked for, so both schemas
    # accept the second job; only what it publishes can differ.
    await db.finish_job(job_new)

    job_old = await db.job(project, owner, payload={"revision_id": older})
    await system.publish(doc, older, job_old, "w1")

    assert await system.downloads_for(doc, newer) == before


async def test_b_a_bot_edit_reaches_the_head_the_web_reads(db: Db) -> None:
    system, _project, _owner = await _system(db)
    doc, first = await system.start({"title": "imported"})
    await system.bot_edit(doc, first, {"title": "bot edit"})
    assert await system.web_head(doc) == {"title": "bot edit"}


async def test_c_an_ai_edit_that_loses_the_race_is_kept(db: Db) -> None:
    system, _project, _owner = await _system(db)
    doc, base = await system.start({"title": "base"})
    await system.manual(doc, base, {"title": "manual"}, "manual")
    await system.ai_edit(doc, base, {"title": "ai"}, "ai")
    assert await system.proposals(doc) == 1


async def test_e_reusing_an_idempotency_key_for_other_content_is_refused(db: Db) -> None:
    system, _project, _owner = await _system(db)
    doc, base = await system.start({"title": "base"})
    with pytest.raises(asyncpg.UniqueViolationError, match="idempotency_key_reused"):
        await system.reuse_key(doc, base)


async def test_f_a_worker_without_the_claim_cannot_publish(db: Db) -> None:
    system, project, owner = await _system(db)
    doc, revision = await system.start({"title": "deck"})
    job = await db.job(project, owner, worker="someone-else", payload={"revision_id": revision})
    with pytest.raises(asyncpg.ObjectNotInPrerequisiteStateError, match="claim_lost"):
        await system.publish(doc, revision, job, "w1")


async def test_g_a_job_cannot_publish_a_revision_it_does_not_target(db: Db) -> None:
    system, project, owner = await _system(db)
    doc, x = await system.start({"title": "x"})
    y = await system.manual(doc, x, {"title": "y"}, "y")
    job = await db.job(project, owner, payload={"revision_id": x})
    with pytest.raises(asyncpg.InsufficientPrivilegeError, match="job_revision_mismatch"):
        await system.publish(doc, str(y), job, "w1")


async def test_h_a_job_cannot_be_refunded_twice(db: Db) -> None:
    owner = await db.user(OWNER_TG)
    project = await db.project(owner)
    job = await db.job(project, owner, job_type="presentation_generation")
    admin = await db.admin()
    insert = (
        "insert into credit_ledger (user_id, amount, reason, action, generation_job_id, status)"
        " values ($1, 5000, 'refund', 'refund', $2, 'confirmed')"
    )
    await admin.execute(insert, uuid.UUID(owner), uuid.UUID(job))
    with pytest.raises(asyncpg.UniqueViolationError):
        await admin.execute(insert, uuid.UUID(owner), uuid.UUID(job))


async def test_k_an_api_user_cannot_write_revisions_or_decks_directly(db: Db) -> None:
    system, project, owner = await _system(db)
    doc, _first = await system.start({"title": "deck"})
    user = await db.as_role("authenticated", owner)
    # The hash column was renamed by 016; name the one this schema has, so the
    # insert can only fail for lack of privilege, never for a missing column.
    hash_column = "content_hash" if LEGACY else "content_sha256"
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await user.execute(
            f"insert into document_revisions (document_id, idempotency_key, content, {hash_column})"
            " values ($1, 'forged', '{}', repeat('a', 64))",
            uuid.UUID(doc),
        )
    # After 016 `decks` is a join view: PostgreSQL's rewriter rejects the insert
    # as non-updatable at prepare time, before the executor's privilege check, so
    # either error means "refused". The privilege assertion below pins the grant
    # itself, so a future INSTEAD OF trigger on the view could not reopen writes.
    with pytest.raises(
        (asyncpg.InsufficientPrivilegeError, asyncpg.ObjectNotInPrerequisiteStateError)
    ):
        await user.execute(
            "insert into decks (project_id, title, language, audience, deck_json)"
            " values ($1, 'T', 'uz', 'talaba', '{}')",
            uuid.UUID(project),
        )
    for privilege in ("INSERT", "UPDATE", "DELETE"):
        assert await user.fetchval("select has_table_privilege('decks', $1)", privilege) is False


def test_export_key_shape() -> None:
    assert export_key("d", "r", "html", "s") == "exports/d/r/pw-test/html/s.html"
