"""The document row lock serializes writers, shown without timing (B1-FIX4, Codex N2).

The lifecycle property test catches a missing document lock only when its random
schedule happens to overlap two writers, so the mutation gate leaned on timing.
This test makes the overlap certain. A test-only trigger stops every writer at
the moment it inserts its revision, which is after it has read the head; the
test holds the advisory lock that trigger waits on, starts two writers on the
same head, and waits until the database reports both of them blocked. Then it
reads where each one is waiting and releases them.

With the lock, the first writer waits at the barrier holding the document row
and the second waits for that row, before it can read the head: one commit, one
conflict. Without it (NASHR_TEST_MUTATION=no_document_lock) both reach the
barrier carrying the same head and both commit. Neither outcome depends on a
sleep: the test proceeds when the waits it inspects are in place, and the lock
being tested is never asked to let both writers past the barrier.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest

from tests.db.conftest import CURRENT
from tests.db.support import Db, commit, ensure_document, head

pytestmark = pytest.mark.skipif(not CURRENT, reason="exercises the current 016 (and its mutation)")

_BARRIER = 7_004_242
_SETTLE_DEADLINE_SECONDS = 60.0

_TEST_BARRIER = f"""
create function test_after_head_barrier() returns trigger
language plpgsql as $$
begin
    perform pg_advisory_xact_lock_shared({_BARRIER});
    return new;
end;
$$;
create trigger test_after_head_barrier before insert on document_revisions
    for each row execute function test_after_head_barrier();
"""


async def _blocked_on(coordinator: Any, pids: list[int]) -> dict[int, str]:
    """Where each writer waits, once every one of them is blocked on a lock."""

    deadline = time.monotonic() + _SETTLE_DEADLINE_SECONDS
    while True:
        rows = await coordinator.fetch(
            "select pid, wait_event_type, wait_event from pg_stat_activity"
            " where pid = any($1::int[])",
            pids,
        )
        waits = {int(r["pid"]): f"{r['wait_event_type']}:{r['wait_event']}" for r in rows}
        if len(waits) == len(pids) and all(w.startswith("Lock:") for w in waits.values()):
            return waits
        if time.monotonic() > deadline:
            raise AssertionError(f"the writers never both blocked: {waits}")
        await asyncio.sleep(0.05)


async def test_two_writers_on_one_head_serialize_on_the_document_row(db: Db) -> None:
    owner = await db.user()
    project = await db.project(owner)
    service = await db.as_role("service_role")
    document = await ensure_document(service, project, owner)
    r0 = str(
        (await commit(service, document, None, {"t": 0}, kind="manual", actor=owner, key="r0"))[
            "revision_id"
        ]
    )
    admin = await db.admin()
    await admin.execute(_TEST_BARRIER)
    coordinator = await db.admin()
    await coordinator.execute(f"select pg_advisory_lock({_BARRIER})")

    writers = [await db.as_role("service_role") for _ in range(2)]
    pids = [int(conn.get_server_pid()) for conn in writers]
    tasks = [
        asyncio.create_task(
            commit(conn, document, r0, {"t": name}, kind="manual", actor=owner, key=name)
        )
        for conn, name in zip(writers, ("a", "b"), strict=True)
    ]
    try:
        waits = await _blocked_on(coordinator, pids)
    finally:
        await coordinator.execute(f"select pg_advisory_unlock({_BARRIER})")
    results = await asyncio.gather(*tasks)

    committed = [r for r in results if r["status"] == "committed"]
    assert len(committed) == 1, (
        f"{len(committed)} writes committed against the same pre-round head {r0}"
        f" (waits at the barrier: {sorted(waits.values())})"
    )
    assert sorted(r["status"] for r in results) == ["committed", "conflict"]
    # The loser never reached the barrier: it waited for the row, not for the head.
    assert sorted(waits.values())[0] == "Lock:advisory", waits
    assert sorted(waits.values())[1] in ("Lock:transactionid", "Lock:tuple"), waits
    assert await head(service, document) == committed[0]["revision_id"]
