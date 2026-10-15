"""Real-PostgreSQL suite: runs in CI against a Postgres service, skipped elsewhere.

Set ``NASHR_TEST_DATABASE_URL`` to a superuser URL on a cluster bootstrapped
with ``bootstrap_roles.sql``. ``NASHR_TEST_SCHEMA`` picks the chain:
``legacy`` (001–015, the pre-B1 schema test_bug_regressions must fail against),
``baseline`` (001–015 plus the reviewed 016, the schema test_b1_fix_regressions
must fail against), ``fix1`` (001–015 plus 016 as of 8cc000b, the schema
test_b1_fix2_regressions must fail against), ``fix2`` (001–015 plus 016 as of
fdb14bc, the schema test_b1_fix3_regressions must fail against) or ``current``
(default, every migration).
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from tests.db.support import ADMIN_URL, SCHEMA, Db, create_database, drop_database, migrations_for

LEGACY = SCHEMA == "legacy"
BASELINE = SCHEMA == "baseline"
FIX1 = SCHEMA == "fix1"
FIX2 = SCHEMA == "fix2"
CURRENT = SCHEMA == "current"


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
    """A fresh database with the schema mode's migration chain applied."""

    name = await create_database(migrations_for())
    database = Db(name)
    try:
        yield database
    finally:
        await database.close()
        await drop_database(name)
