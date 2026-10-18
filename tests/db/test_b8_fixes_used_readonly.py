"""B8.2 (migration 019): brain_sessions.fixes_used is read-only legacy history.

The bot's inline edit counter is frozen: queued edits create edit_deliveries rows and
nothing increments fixes_used again, on any surface or role. These run against real
Postgres in CI (skipped when NASHR_TEST_DATABASE_URL is unset).
"""

from __future__ import annotations

import uuid

import asyncpg
import pytest

from tests.db.support import Db

pytestmark = pytest.mark.asyncio


async def _seed_session(db: Db, *, fixes_used: int = 0) -> tuple[str, str, str]:
    """A user, their presentation project, and a brain_sessions row; ids as strings."""

    user = await db.user()
    project = await db.project(user)
    conn = await db._seed()  # pyright: ignore[reportPrivateUsage]
    session = await conn.fetchval(
        "insert into brain_sessions (project_id, package, formats_json, fixes_used)"
        " values ($1, 'presentation_premium', '[\"html\"]', $2) returning id",
        uuid.UUID(project),
        fixes_used,
    )
    return user, project, str(session)


async def _fixes_used(db: Db, session_id: str) -> int:
    conn = await db._seed()  # pyright: ignore[reportPrivateUsage]
    return int(
        await conn.fetchval(
            "select fixes_used from brain_sessions where id = $1", uuid.UUID(session_id)
        )
    )


async def test_insert_with_nonzero_fixes_used_is_rejected(db: Db) -> None:
    user = await db.user()
    project = await db.project(user)
    conn = await db._seed()  # pyright: ignore[reportPrivateUsage]
    with pytest.raises(asyncpg.PostgresError, match="fixes_used_read_only"):
        await conn.execute(
            "insert into brain_sessions (project_id, package, formats_json, fixes_used)"
            " values ($1, 'presentation_premium', '[\"html\"]', 5)",
            uuid.UUID(project),
        )


async def test_insert_with_zero_fixes_used_is_allowed(db: Db) -> None:
    _user, _project, session = await _seed_session(db, fixes_used=0)
    assert await _fixes_used(db, session) == 0


async def test_service_role_cannot_change_fixes_used(db: Db) -> None:
    _user, _project, session = await _seed_session(db)
    conn = await db.as_role("service_role")
    with pytest.raises(asyncpg.PostgresError, match="fixes_used_read_only"):
        await conn.execute(
            "update brain_sessions set fixes_used = 1, version = version + 1 where id = $1",
            uuid.UUID(session),
        )
    assert await _fixes_used(db, session) == 0


async def test_an_update_that_leaves_fixes_used_alone_is_allowed(db: Db) -> None:
    _user, _project, session = await _seed_session(db)
    conn = await db.as_role("service_role")
    # A normal session write (CAS advances version) that does not touch fixes_used.
    await conn.execute(
        "update brain_sessions set package = 'presentation_standard', version = version + 1"
        " where id = $1",
        uuid.UUID(session),
    )
    row = await conn.fetchrow(
        "select package, fixes_used from brain_sessions where id = $1", uuid.UUID(session)
    )
    assert row["package"] == "presentation_standard" and row["fixes_used"] == 0


async def test_authenticated_owner_cannot_change_fixes_used(db: Db) -> None:
    user, _project, session = await _seed_session(db)
    conn = await db.as_role("authenticated", sub=user)
    # Either the trigger rejects it (the owner's row is reachable) or RLS hides the
    # row (no-op); either way fixes_used must not change.
    try:
        await conn.execute(
            "update brain_sessions set fixes_used = 2, version = version + 1 where id = $1",
            uuid.UUID(session),
        )
    except asyncpg.PostgresError as exc:
        assert "fixes_used_read_only" in str(exc)
    assert await _fixes_used(db, session) == 0


async def test_anon_cannot_change_fixes_used(db: Db) -> None:
    _user, _project, session = await _seed_session(db)
    conn = await db.as_role("anon")
    # RLS hides the row from anon, so the update matches nothing; if it ever reached
    # the row the trigger would reject it. fixes_used stays put either way.
    try:
        await conn.execute(
            "update brain_sessions set fixes_used = 3, version = version + 1 where id = $1",
            uuid.UUID(session),
        )
    except asyncpg.PostgresError as exc:
        assert "fixes_used_read_only" in str(exc)
    assert await _fixes_used(db, session) == 0
