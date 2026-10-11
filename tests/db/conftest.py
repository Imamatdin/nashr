"""Real-PostgreSQL suite: runs in CI against a Postgres service, skipped elsewhere.

Set ``NASHR_TEST_DATABASE_URL`` to a superuser URL on a cluster bootstrapped
with ``bootstrap_roles.sql``. ``NASHR_TEST_SCHEMA=legacy`` builds databases
from migrations 001–015 only: the pre-change schema the bug-regression tests
must fail against.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest

from tests.db.support import ADMIN_URL, Db, create_database, drop_database, migrations_through

LEGACY = os.environ.get("NASHR_TEST_SCHEMA") == "legacy"


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if ADMIN_URL:
        return
    skip = pytest.mark.skip(
        reason="NASHR_TEST_DATABASE_URL not set (real-PostgreSQL suite runs in CI)"
    )
    for item in items:
        if "tests/db/" in item.nodeid.replace("\\", "/"):
            item.add_marker(skip)


@pytest.fixture
async def db() -> AsyncIterator[Db]:
    """A fresh database with the migration chain applied (001–015 under legacy)."""

    name = await create_database(migrations_through("015" if LEGACY else None))
    database = Db(name)
    try:
        yield database
    finally:
        await database.close()
        await drop_database(name)
