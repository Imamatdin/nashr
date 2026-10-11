"""Migration 016's legacy-deck backfill on real PostgreSQL (test l).

Each scenario builds a database at 015, writes legacy rows the way the
pre-change code did, applies 016, and checks that every deck is kept: as the
head, as an unchanged head, or as a pending import proposal. A second run of
016 must add nothing.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from tests.db.conftest import LEGACY
from tests.db.support import (
    MIGRATIONS,
    Db,
    apply,
    connect,
    create_database,
    database_url,
    drop_database,
    migrations_through,
)

pytestmark = pytest.mark.skipif(LEGACY, reason="applies migration 016")

MIGRATION_016 = next(path for path in MIGRATIONS if path.name.startswith("016"))


async def _legacy_db() -> Db:
    return Db(await create_database(migrations_through("015")))


async def _deck_row(conn: Any, project: str, content: Any) -> str:
    deck_id = uuid.uuid4()
    await conn.execute(
        "insert into decks (id, project_id, title, language, audience, deck_json)"
        " values ($1, $2, 'T', 'uz', 'talaba', $3::jsonb)",
        deck_id,
        uuid.UUID(project),
        content,
    )
    return str(deck_id)


async def _counts(conn: Any) -> dict[str, int]:
    return {
        "documents": await conn.fetchval("select count(*) from documents"),
        "revisions": await conn.fetchval("select count(*) from document_revisions"),
        "proposals": await conn.fetchval("select count(*) from revision_proposals"),
        "legacy": await conn.fetchval("select count(*) from decks_legacy"),
    }


async def test_l_empty_database_migrates_cleanly() -> None:
    name = await create_database(migrations_through(None))
    try:
        conn = await connect(database_url(name))
        assert await _counts(conn) == {"documents": 0, "revisions": 0, "proposals": 0, "legacy": 0}
        relkind = await conn.fetchval("select relkind from pg_class where relname = 'decks'")
        assert relkind == "v"
        await conn.close()
    finally:
        await drop_database(name)


async def test_l_legacy_decks_are_imported_kept_and_never_duplicated() -> None:
    db = await _legacy_db()
    try:
        admin = await db.admin()
        owner = await db.user(444_000_444)
        fresh = await db.project(owner)
        invalid = await db.project(owner)
        diverged = await db.project(owner)
        same = await db.project(owner)
        await _deck_row(admin, fresh, {"title": "only in decks"})
        await _deck_row(admin, invalid, ["not", "an", "object"])
        # Bug (b) left these: a document head plus a decks row the bot edited later.
        for project, head_title in ((diverged, "web head"), (same, "same")):
            await admin.fetchrow(
                "select * from create_document_if_missing($1, 'presentation', 1, $2::jsonb, $3, 'i')",
                uuid.UUID(project),
                {"title": head_title},
                uuid.UUID(owner),
            )
        await _deck_row(admin, diverged, {"title": "bot edit only in decks"})
        await _deck_row(admin, same, {"title": "same"})

        await apply(admin, MIGRATION_016)

        heads = {
            str(row["project_id"]): row["deck_json"]
            for row in await admin.fetch("select project_id, deck_json from decks")
        }
        assert heads[fresh] == {"title": "only in decks"}
        assert heads[invalid] == {"legacy_raw": ["not", "an", "object"]}
        assert heads[diverged] == {"title": "web head"}
        assert heads[same] == {"title": "same"}
        proposal = await admin.fetchrow("select kind, content, status from revision_proposals")
        assert proposal["kind"] == "import" and proposal["status"] == "pending"
        assert proposal["content"] == {"title": "bot edit only in decks"}
        imported = await admin.fetchval(
            "select count(*) from document_revisions where actor = 'system:migration-016'"
        )
        assert imported == 2
        before = await _counts(admin)

        await apply(admin, MIGRATION_016)

        assert await _counts(admin) == before
    finally:
        await db.close()
        await drop_database(db.name)


async def test_l_legacy_revisions_gain_provenance_and_keep_their_hash() -> None:
    db = await _legacy_db()
    try:
        admin = await db.admin()
        owner = await db.user(555_000_555)
        project = await db.project(owner, kind="article")
        row = await admin.fetchrow(
            "select * from create_document_if_missing($1, 'article', 1, $2::jsonb, $3, 'i')",
            uuid.UUID(project),
            {"kind": "article", "title": "A", "blocks": []},
            uuid.UUID(owner),
        )
        before = await admin.fetchval(
            "select content_hash from document_revisions where id = $1", row["revision_id"]
        )

        await apply(admin, MIGRATION_016)

        after = await admin.fetchrow(
            "select content_sha256, kind, actor, schema_version from document_revisions where id = $1",
            row["revision_id"],
        )
        assert after["content_sha256"] == before
        assert (after["kind"], after["actor"], after["schema_version"]) == ("import", owner, 1)
        recomputed = await admin.fetchval(
            "select encode(sha256(convert_to(content::text, 'UTF8')), 'hex') from document_revisions"
            " where id = $1",
            row["revision_id"],
        )
        assert recomputed == before  # 011's digest() and 016's sha256() agree
    finally:
        await db.close()
        await drop_database(db.name)
