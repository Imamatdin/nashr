"""Isolation through real PostgREST with user tokens (test j), in CI.

CI starts PostgREST against one fully migrated database and sets:
``NASHR_TEST_POSTGREST_URL``, ``NASHR_TEST_JWT_SECRET`` (the local test secret)
and ``NASHR_TEST_REST_DATABASE_URL`` (superuser URL of that database, for
seeding only). Every request below carries a minted user token, exactly what
the browser holds.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
import uuid
from typing import Any

import httpx
import pytest

from tests.db.support import connect

REST = os.environ.get("NASHR_TEST_POSTGREST_URL", "")
SECRET = os.environ.get("NASHR_TEST_JWT_SECRET", "")
DB_URL = os.environ.get("NASHR_TEST_REST_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not (REST and SECRET and DB_URL), reason="PostgREST is started by the CI database job"
)


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def token(sub: str | None, role: str = "authenticated") -> str:
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    claims: dict[str, Any] = {"role": role, "exp": int(time.time()) + 600}
    if sub:
        claims["sub"] = sub
    body = _b64(json.dumps(claims).encode())
    signature = hmac.new(SECRET.encode(), f"{header}.{body}".encode(), hashlib.sha256).digest()
    return f"{header}.{body}.{_b64(signature)}"


@pytest.fixture
async def world() -> dict[str, str]:
    conn = await connect(DB_URL)
    try:
        owner, other = str(uuid.uuid4()), str(uuid.uuid4())
        for user_id in (owner, other):
            await conn.execute(
                "insert into users (id, telegram_id) values ($1, $2)",
                uuid.UUID(user_id),
                9_000_000_000 + uuid.uuid4().int % 10**8,
            )
        project = str(uuid.uuid4())
        await conn.execute(
            "insert into projects (id, user_id, type, title, language, audience)"
            " values ($1, $2, 'presentation', 'T', 'uz', 'talaba')",
            uuid.UUID(project),
            uuid.UUID(owner),
        )
        await conn.execute("set role service_role")
        document = str(
            await conn.fetchval(
                "select ensure_document($1, 'presentation', $2)", uuid.UUID(project), owner
            )
        )
        row = await conn.fetchrow(
            "select * from commit_revision($1, null, $2::jsonb, 'manual', 1, $3, 'seed')",
            uuid.UUID(document),
            {"title": "A's deck"},
            owner,
        )
        return {
            "owner": owner,
            "other": other,
            "project": project,
            "document": document,
            "revision": str(row["revision_id"]),
        }
    finally:
        await conn.close()


async def _call(
    method: str, path: str, sub: str | None, body: Any = None, role: str = "authenticated"
) -> httpx.Response:
    async with httpx.AsyncClient(base_url=REST, timeout=10) as client:
        return await client.request(
            method,
            path,
            headers={
                "Authorization": f"Bearer {token(sub, role)}",
                "Content-Type": "application/json",
            },
            content=json.dumps(body) if body is not None else None,
        )


async def test_j_user_b_reads_nothing_of_user_a(world: dict[str, str]) -> None:
    for table in (
        "documents",
        "document_revisions",
        "revision_exports",
        "revision_proposals",
        "decks",
    ):
        response = await _call("GET", f"/{table}?select=*", world["other"])
        assert response.status_code == 200, (table, response.text)
        assert response.json() == [], table


async def test_j_user_b_cannot_commit_to_user_a(world: dict[str, str]) -> None:
    response = await _call(
        "POST",
        "/rpc/commit_revision",
        world["other"],
        {
            "p_document_id": world["document"],
            "p_base_revision_id": world["revision"],
            "p_content": {"title": "hijack"},
            "p_kind": "manual",
            "p_schema_version": 1,
            "p_actor": world["other"],
            "p_idempotency_key": "hijack",
        },
    )
    assert response.status_code >= 400
    assert "not_document_owner" in response.text


async def test_j_owner_reads_and_commits_as_themselves_only(world: dict[str, str]) -> None:
    rows = await _call(
        "GET", f"/document_revisions?document_id=eq.{world['document']}", world["owner"]
    )
    assert [row["id"] for row in rows.json()] == [world["revision"]]
    ok = await _call(
        "POST",
        "/rpc/commit_revision",
        world["owner"],
        {
            "p_document_id": world["document"],
            "p_base_revision_id": world["revision"],
            "p_content": {"title": "edited"},
            "p_kind": "manual",
            "p_schema_version": 1,
            "p_actor": world["owner"],
            "p_idempotency_key": "own-edit",
        },
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()[0]["status"] == "committed"
    impersonated = await _call(
        "POST",
        "/rpc/commit_revision",
        world["owner"],
        {
            "p_document_id": world["document"],
            "p_base_revision_id": ok.json()[0]["revision_id"],
            "p_content": {"title": "as a worker"},
            "p_kind": "ai_edit",
            "p_schema_version": 1,
            "p_actor": f"worker:{uuid.uuid4()}",
            "p_idempotency_key": "impersonate",
        },
    )
    assert impersonated.status_code >= 400 and "actor_mismatch" in impersonated.text


async def test_k_direct_writes_through_postgrest_are_refused(world: dict[str, str]) -> None:
    forged = await _call(
        "POST",
        "/document_revisions",
        world["owner"],
        {
            "document_id": world["document"],
            "idempotency_key": "f",
            "content": {},
            "content_sha256": "a" * 64,
            "kind": "manual",
            "schema_version": 1,
            "actor": world["owner"],
        },
    )
    assert forged.status_code in (401, 403), forged.text
    deck = await _call(
        "POST",
        "/decks",
        world["owner"],
        {
            "project_id": world["project"],
            "title": "t",
            "language": "uz",
            "audience": "talaba",
            "deck_json": {},
        },
    )
    # decks has an INSTEAD OF trigger, so the privilege check refuses: 42501, 403.
    assert deck.status_code == 403 and deck.json().get("code") == "42501", deck.text
    export = await _call(
        "POST",
        "/rpc/register_export",
        world["owner"],
        {
            "p_job_id": str(uuid.uuid4()),
            "p_worker_id": "w",
            "p_claim_token": 1,
            "p_revision_id": world["revision"],
            "p_format": "html",
            "p_renderer_version": "pw-x",
            "p_storage_key": "k",
            "p_sha256": "a" * 64,
            "p_byte_size": 1,
            "p_page_count": None,
        },
    )
    # The function exists with exactly these parameters; an end user lacks EXECUTE.
    assert export.status_code == 403 and export.json().get("code") == "42501", export.text
