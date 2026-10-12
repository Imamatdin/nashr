"""Shared helpers for the real-PostgreSQL suite (ADR 0001).

Each test gets a fresh database built from the real migration chain on the CI
Postgres service. A test acts as an API role exactly the way PostgREST does:
``SET ROLE`` plus ``request.jwt.claims``.
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import asyncpg  # pyright: ignore[reportMissingTypeStubs]

ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = sorted((ROOT / "supabase" / "migrations").glob("*.sql"))
BOOTSTRAP = Path(__file__).with_name("bootstrap_database.sql")
# Migration 016 exactly as the first B1 review saw it (blob e2863406 at 848a3c9).
# The B1-FIX regression tests must fail against it and pass against the fixed 016.
BASELINE_016 = Path(__file__).with_name("baseline") / "016_canonical_document_state_848a3c9.sql"
ADMIN_URL = os.environ.get("NASHR_TEST_DATABASE_URL", "")
# legacy = 001–015 (pre-B1); baseline = 001–015 + the reviewed 016; current = all.
SCHEMA = os.environ.get("NASHR_TEST_SCHEMA", "current")
if SCHEMA not in ("legacy", "baseline", "current"):
    raise RuntimeError(f"NASHR_TEST_SCHEMA must be legacy, baseline or current, not {SCHEMA!r}")


def migrations_through(last_prefix: str | None) -> list[Path]:
    """Migration files in order, up to and including ``last_prefix`` (None = all)."""

    if last_prefix is None:
        return list(MIGRATIONS)
    return [path for path in MIGRATIONS if path.name[:3] <= last_prefix]


def migrations_for(schema: str = SCHEMA) -> list[Path]:
    """The migration chain a schema mode builds."""

    if schema == "legacy":
        return migrations_through("015")
    if schema == "baseline":
        return [*migrations_through("015"), BASELINE_016]
    return migrations_through(None)


def migration_016(schema: str = SCHEMA) -> Path:
    """The 016 file a schema mode applies (legacy has none)."""

    if schema == "legacy":
        raise RuntimeError("the legacy schema has no migration 016")
    return BASELINE_016 if schema == "baseline" else migrations_through(None)[-1]


def database_url(name: str) -> str:
    return ADMIN_URL.rsplit("/", 1)[0] + "/" + name


async def connect(dsn: str) -> Any:
    conn: Any = await asyncpg.connect(dsn)
    await conn.set_type_codec("jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog")
    return conn


async def create_database(migrations: Sequence[Path], name: str | None = None) -> str:
    """A fresh database with the Supabase surface and ``migrations`` applied."""

    name = name or f"t_{uuid.uuid4().hex[:16]}"
    admin: Any = await asyncpg.connect(ADMIN_URL)
    try:
        await admin.execute(f'create database "{name}"')
    finally:
        await admin.close()
    conn: Any = await asyncpg.connect(database_url(name))
    try:
        await conn.execute(BOOTSTRAP.read_text(encoding="utf-8"))
        for path in migrations:
            await apply(conn, path)
    finally:
        await conn.close()
    return name


async def apply(conn: Any, path: Path) -> None:
    """Run one migration file as a single transaction."""

    await conn.execute("begin")
    try:
        await conn.execute(path.read_text(encoding="utf-8"))
    except Exception:
        await conn.execute("rollback")
        raise
    await conn.execute("commit")


async def drop_database(name: str) -> None:
    admin: Any = await asyncpg.connect(ADMIN_URL)
    try:
        await admin.execute(f'drop database if exists "{name}" with (force)')
    finally:
        await admin.close()


class Db:
    """One test database: superuser seeding plus connections acting as API roles."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.dsn = database_url(name)
        self._open: list[Any] = []

    async def admin(self) -> Any:
        conn = await connect(self.dsn)
        self._open.append(conn)
        return conn

    async def as_role(self, role: str, sub: str | None = None) -> Any:
        """A connection acting as ``role`` the way PostgREST does."""

        conn = await self.admin()
        claims = {"role": role, **({"sub": sub} if sub else {})}
        await conn.execute("select set_config('request.jwt.claims', $1, false)", json.dumps(claims))
        await conn.execute(f"set role {role}")
        return conn

    async def close(self) -> None:
        for conn in self._open:
            if not conn.is_closed():
                await conn.close()

    # ------------------------------------------------------------- seeding

    async def user(self, telegram_id: int | None = None) -> str:
        conn = await self.admin()
        user_id = str(uuid.uuid4())
        await conn.execute(
            "insert into users (id, telegram_id) values ($1, $2)",
            uuid.UUID(user_id),
            telegram_id if telegram_id is not None else 8_000_000_000 + uuid.uuid4().int % 10**9,
        )
        return user_id

    async def project(self, user_id: str, kind: str = "presentation") -> str:
        conn = await self.admin()
        project_id = str(uuid.uuid4())
        await conn.execute(
            "insert into projects (id, user_id, type, title, language, audience)"
            " values ($1, $2, $3, 'Test', 'uz', 'talaba')",
            uuid.UUID(project_id),
            uuid.UUID(user_id),
            kind,
        )
        return project_id

    async def job(
        self,
        project_id: str,
        user_id: str,
        *,
        worker: str = "w1",
        status: str = "processing",
        job_type: str = "presentation_render",
        payload: dict[str, Any] | None = None,
        attempts: int = 1,
    ) -> str:
        """A job row; a processing one holds a live claim (``worker``, attempt ``attempts``)."""

        conn = await self.admin()
        job_id = str(uuid.uuid4())
        body = payload if payload is not None else {}
        if job_type == "presentation_render":
            body = {"renderer_version": "pw-test", "formats": ["html"], **body}
        await conn.execute(
            "insert into generation_jobs (id, project_id, user_id, job_type, status, worker_id,"
            " payload, attempts, max_attempts, claimed_at, heartbeat_at)"
            " values ($1, $2, $3, $4, $5, $6, $7::jsonb, $8, greatest($8, 1),"
            " case when $5 = 'processing' then now() end,"
            " case when $5 = 'processing' then now() end)",
            uuid.UUID(job_id),
            uuid.UUID(project_id),
            uuid.UUID(user_id),
            job_type,
            status,
            worker,
            body,
            attempts,
        )
        return job_id

    async def finish_job(self, job_id: str, status: str = "completed") -> None:
        """Land a job on a terminal status as an operator would (no claim involved)."""

        conn = await self.admin()
        await conn.execute(
            "update generation_jobs set status = $2, completed_at = now() where id = $1",
            uuid.UUID(job_id),
            status,
        )


# ------------------------------------------------------------------ calls


async def ensure_document(
    conn: Any, project_id: str, actor: str, kind: str = "presentation"
) -> str:
    return str(
        await conn.fetchval(
            "select ensure_document($1, $2, $3)", uuid.UUID(project_id), kind, actor
        )
    )


async def commit(
    conn: Any,
    document_id: str,
    base: str | None,
    content: dict[str, Any],
    *,
    kind: str,
    actor: str,
    key: str,
    schema_version: int = 1,
) -> dict[str, Any]:
    row = await conn.fetchrow(
        "select * from commit_revision($1, $2, $3::jsonb, $4, $5, $6, $7)",
        uuid.UUID(document_id),
        uuid.UUID(base) if base else None,
        content,
        kind,
        schema_version,
        actor,
        key,
    )
    return {k: (str(v) if isinstance(v, uuid.UUID) else v) for k, v in dict(row).items()}


async def accept(
    conn: Any, proposal_id: str, expected: str | None, actor: str, key: str
) -> dict[str, Any]:
    row = await conn.fetchrow(
        "select * from accept_proposal($1, $2, $3, $4)",
        uuid.UUID(proposal_id),
        uuid.UUID(expected) if expected else None,
        actor,
        key,
    )
    return {k: (str(v) if isinstance(v, uuid.UUID) else v) for k, v in dict(row).items()}


def export_key(
    document_id: str, revision_id: str, fmt: str, sha: str, version: str = "pw-test"
) -> str:
    return f"exports/{document_id}/{revision_id}/{version}/{fmt}/{sha}.{fmt}"


async def register(
    conn: Any,
    job_id: str,
    worker: str,
    document_id: str,
    revision_id: str,
    *,
    sha: str = "a" * 64,
    fmt: str = "html",
    size: int = 10,
) -> str:
    return str(
        await conn.fetchval(
            "select register_export($1, $2, $3, $4, 'pw-test', $5, $6, $7, null)",
            uuid.UUID(job_id),
            worker,
            uuid.UUID(revision_id),
            fmt,
            export_key(document_id, revision_id, fmt, sha),
            sha,
            size,
        )
    )


async def head(conn: Any, document_id: str) -> str | None:
    value = await conn.fetchval(
        "select head_revision_id from documents where id = $1", uuid.UUID(document_id)
    )
    return str(value) if value else None
