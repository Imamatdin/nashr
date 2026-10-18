"""Migration 017 on real PostgreSQL: the shared export-format layer (B2a).

The format lookup, kind-aware render enqueue, article_render claims and the
kind-aware register_export, exercised the way PostgREST drives them (service role
for the render functions). Current schema only.
"""

from __future__ import annotations

import uuid
from typing import Any

import asyncpg  # pyright: ignore[reportMissingTypeStubs]
import pytest

from packages.platform.document_models import EXPORT_FILE_FORMATS, DocumentKind
from tests.db.conftest import CURRENT
from tests.db.support import Db, commit, ensure_document

pytestmark = pytest.mark.skipif(
    not CURRENT, reason="exercises migration 017's functions (current schema only)"
)


class Doc:
    """One owner with a project, document and head revision of a chosen kind."""

    def __init__(self, db: Db) -> None:
        self.db = db

    async def build(self, kind: str) -> Doc:
        self.owner = await self.db.user()
        self.project = await self.db.project(self.owner, kind=kind)
        self.service = await self.db.as_role("service_role")
        self.document = await ensure_document(self.service, self.project, self.owner, kind=kind)
        first = await commit(
            self.service,
            self.document,
            None,
            {"title": "head"},
            kind="manual",
            actor=self.owner,
            key="head",
        )
        self.revision = str(first["revision_id"])
        return self


async def _refused(code: str, call: Any) -> None:
    with pytest.raises(asyncpg.PostgresError) as info:
        await call
    assert code in str(info.value)


async def _request_render(doc: Doc, formats: list[str]) -> dict[str, Any]:
    row = await doc.service.fetchrow(
        "select * from request_render($1, $2, $3, 'pw-test', $4, 3)",
        uuid.UUID(doc.project),
        uuid.UUID(doc.owner),
        uuid.UUID(doc.revision),
        formats,
    )
    return dict(row)


def _key(doc: Doc, fmt: str, sha: str, ext: str, version: str = "pw-test") -> str:
    return f"exports/{doc.document}/{doc.revision}/{version}/{fmt}/{sha}.{ext}"


# --------------------------------------------------------------- the lookup table


async def test_sql_lookup_matches_the_python_format_table(db: Db) -> None:
    conn = await db.admin()
    rows = await conn.fetch(
        "select format, file_extension, media_type, allowed_kinds from export_file_formats"
    )
    seeded = {
        row["format"]: (
            row["file_extension"],
            row["media_type"],
            frozenset(DocumentKind(k) for k in row["allowed_kinds"]),
        )
        for row in rows
    }
    expected = {
        fmt.value: (spec.file_extension, spec.media_type, spec.allowed_kinds)
        for fmt, spec in EXPORT_FILE_FORMATS.items()
    }
    assert seeded == expected


async def test_the_lookup_takes_no_writes_from_the_api_roles(db: Db) -> None:
    for role in ("authenticated", "service_role"):
        conn = await db.as_role(role, await db.user() if role == "authenticated" else None)
        await _refused(
            "permission denied",
            conn.execute("insert into export_file_formats values ('x', 'x', 'x', array['article'])"),
        )


async def test_revision_exports_format_is_bound_to_the_lookup(db: Db) -> None:
    doc = await Doc(db).build("presentation")
    conn = await db.admin()
    # The column now references export_file_formats, so a row with a format that
    # is not in the lookup is refused by the foreign key itself.
    await _refused(
        "foreign key",
        conn.execute(
            "insert into revision_exports"
            " (revision_id, format, renderer_version, storage_key, sha256, byte_size)"
            " values ($1, 'bogus', 'pw-test', $2, $3, 10)",
            uuid.UUID(doc.revision),
            _key(doc, "bogus", "a" * 64, "bogus"),
            "a" * 64,
        ),
    )


# --------------------------------------------------------------- kind-aware enqueue


async def test_enqueue_picks_the_job_type_from_the_document_kind(db: Db) -> None:
    deck = await Doc(db).build("presentation")
    deck_result = await _request_render(deck, ["pdf"])
    assert deck_result["status"] == "queued"
    assert (
        await deck.service.fetchval(
            "select job_type from generation_jobs where id = $1",
            deck_result["job_id"],
        )
        == "presentation_render"
    )

    article = await Doc(db).build("article")
    article_result = await _request_render(article, ["pdf"])
    assert article_result["status"] == "queued"
    assert (
        await article.service.fetchval(
            "select job_type from generation_jobs where id = $1",
            article_result["job_id"],
        )
        == "article_render"
    )


async def test_a_format_outside_the_kind_is_refused_at_enqueue(db: Db) -> None:
    article = await Doc(db).build("article")
    await _refused("invalid_render_formats", _request_render(article, ["png"]))
    await _refused("invalid_render_formats", _request_render(article, ["html"]))

    deck = await Doc(db).build("presentation")
    await _refused("invalid_render_formats", _request_render(deck, ["docx"]))
    # png and docx are the new formats; png is valid for a deck, docx is not.
    assert (await _request_render(deck, ["png"]))["status"] == "queued"


async def test_an_article_render_dedupes_on_the_revision(db: Db) -> None:
    article = await Doc(db).build("article")
    first = await _request_render(article, ["pdf"])
    second = await _request_render(article, ["pdf"])
    assert first["status"] == "queued"
    assert second["status"] == "reused" and second["job_id"] == first["job_id"]
    assert (
        await article.service.fetchval(
            "select count(*) from generation_jobs where job_type = 'article_render'"
        )
        == 1
    )


# --------------------------------------------------------------- claim and heartbeat


async def test_an_article_render_claims_and_heartbeats_like_a_deck_render(db: Db) -> None:
    article = await Doc(db).build("article")
    job_id = await db.job(
        article.project,
        article.owner,
        status="queued",
        job_type="article_render",
        payload={"revision_id": article.revision, "renderer_version": "pw-test", "formats": ["pdf"]},
    )
    claimed = await article.service.fetchrow(
        "select status, attempts from claim_job($1, 'w1')", uuid.UUID(job_id)
    )
    assert claimed["status"] == "processing"
    assert (
        await article.service.fetchval(
            "select heartbeat_job($1, 'w1', $2)", uuid.UUID(job_id), claimed["attempts"]
        )
        is True
    )


# --------------------------------------------------------------- register_export


async def test_register_uses_the_extension_from_the_lookup(db: Db) -> None:
    deck = await Doc(db).build("presentation")
    render = await db.job(
        deck.project, deck.owner, payload={"revision_id": deck.revision, "formats": ["png"]}
    )
    sha = "b" * 64
    status = await deck.service.fetchval(
        "select status from register_export($1, 'w1', 1, $2, 'png', 'pw-test', $3, $4, 1024, 3)",
        uuid.UUID(render),
        uuid.UUID(deck.revision),
        _key(deck, "png", sha, "zip"),
        sha,
    )
    assert status == "registered"
    stored = await deck.service.fetchval(
        "select storage_key from revision_exports where revision_id = $1 and format = 'png'",
        uuid.UUID(deck.revision),
    )
    assert stored.endswith(f"/png/{sha}.zip")


async def test_register_accepts_an_article_render(db: Db) -> None:
    article = await Doc(db).build("article")
    render = await db.job(
        article.project,
        article.owner,
        job_type="article_render",
        payload={"revision_id": article.revision, "renderer_version": "pw-test", "formats": ["docx"]},
    )
    sha = "c" * 64
    status = await article.service.fetchval(
        "select status from register_export($1, 'w1', 1, $2, 'docx', 'pw-test', $3, $4, 2048, null)",
        uuid.UUID(render),
        uuid.UUID(article.revision),
        _key(article, "docx", sha, "docx"),
        sha,
    )
    assert status == "registered"


async def test_register_refuses_a_wrong_extension_in_the_key(db: Db) -> None:
    deck = await Doc(db).build("presentation")
    render = await db.job(
        deck.project, deck.owner, payload={"revision_id": deck.revision, "formats": ["png"]}
    )
    sha = "d" * 64
    await _refused(
        "invalid_storage_key",
        deck.service.fetchrow(
            "select * from register_export($1, 'w1', 1, $2, 'png', 'pw-test', $3, $4, 10, null)",
            uuid.UUID(render),
            uuid.UUID(deck.revision),
            _key(deck, "png", sha, "png"),  # png extension, but png is stored as .zip
            sha,
        ),
    )


async def test_register_refuses_a_non_render_job(db: Db) -> None:
    deck = await Doc(db).build("presentation")
    edit = await db.job(deck.project, deck.owner, job_type="presentation_edit")
    sha = "e" * 64
    await _refused(
        "job_type_not_allowed",
        deck.service.fetchrow(
            "select * from register_export($1, 'w1', 1, $2, 'pdf', 'pw-test', $3, $4, 10, null)",
            uuid.UUID(edit),
            uuid.UUID(deck.revision),
            _key(deck, "pdf", sha, "pdf"),
            sha,
        ),
    )


async def test_register_refuses_a_format_outside_the_documents_kind(db: Db) -> None:
    # A job whose payload lists png for an article (which _enqueue_render would
    # never create) still cannot register it: the kind check in register_export
    # is the last line of defence.
    article = await Doc(db).build("article")
    render = await db.job(
        article.project,
        article.owner,
        job_type="article_render",
        payload={"revision_id": article.revision, "renderer_version": "pw-test", "formats": ["png"]},
    )
    sha = "f" * 64
    await _refused(
        "invalid_render_formats",
        article.service.fetchrow(
            "select * from register_export($1, 'w1', 1, $2, 'png', 'pw-test', $3, $4, 10, null)",
            uuid.UUID(render),
            uuid.UUID(article.revision),
            _key(article, "png", sha, "zip"),
            sha,
        ),
    )


async def test_a_deck_pdf_still_registers_unchanged(db: Db) -> None:
    deck = await Doc(db).build("presentation")
    render = await db.job(
        deck.project, deck.owner, payload={"revision_id": deck.revision, "formats": ["pdf"]}
    )
    sha = "1" * 64
    status = await deck.service.fetchval(
        "select status from register_export($1, 'w1', 1, $2, 'pdf', 'pw-test', $3, $4, 10, 5)",
        uuid.UUID(render),
        uuid.UUID(deck.revision),
        _key(deck, "pdf", sha, "pdf"),
        sha,
    )
    assert status == "registered"
