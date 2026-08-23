"""Behaviour tests for the P2 job queue client (packages/platform/jobs.py).

The Supabase surface is replaced by a behavioural fake at the DatabaseClient
seam: ``_query`` returns a recording builder, ``rpc`` dispatches to canned
handlers. The SQL functions themselves (claim CAS, reaper transitions) live in
migration 006 and are exercised on the VM gate; here we pin the CLIENT
contract — what gets sent, and how responses are interpreted.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast

import pytest

from packages.platform.config import PlatformConfig
from packages.platform.database import DatabaseClient
from packages.platform.jobs import (
    DuplicateActiveJobError,
    GenerationJob,
    JobQueue,
    JobStatus,
    JobType,
)
from tests.unit.test_database_client import FakeSupabaseClient

pytestmark = pytest.mark.asyncio

_JOB_ROW: dict[str, Any] = {
    "id": "11111111-1111-1111-1111-111111111111",
    "project_id": "22222222-2222-2222-2222-222222222222",
    "user_id": "33333333-3333-3333-3333-333333333333",
    "job_type": "presentation_generation",
    "status": "queued",
    "payload": {"product_type": "presentation_standard"},
    "progress": {},
    "attempts": 0,
    "max_attempts": 1,
}


class _FakeBuilder:
    def __init__(self, db: _FakeDb, table: str) -> None:
        self._db = db
        self.table = table
        self.op: str | None = None
        self.op_payload: Any = None
        self.filters: list[tuple[str, str, Any]] = []

    def select(self, *_cols: str) -> _FakeBuilder:
        self.op = self.op or "select"
        return self

    def insert(self, payload: dict[str, Any]) -> _FakeBuilder:
        self.op = "insert"
        self.op_payload = payload
        return self

    def update(self, payload: dict[str, Any]) -> _FakeBuilder:
        self.op = "update"
        self.op_payload = payload
        return self

    def eq(self, col: str, value: Any) -> _FakeBuilder:
        self.filters.append(("eq", col, value))
        return self

    def in_(self, col: str, values: Any) -> _FakeBuilder:
        self.filters.append(("in", col, values))
        return self

    def limit(self, _n: int) -> _FakeBuilder:
        return self

    def execute(self) -> Any:
        return self._db.execute(self)


class _FakeDb:
    """Stands in for DatabaseClient: only _query and rpc are consumed."""

    def __init__(self) -> None:
        self.builders: list[_FakeBuilder] = []
        self.rpc_calls: list[tuple[str, dict[str, Any]]] = []
        self.select_rows: list[dict[str, Any]] = []
        self.insert_raises: Exception | None = None
        self.update_rows: list[dict[str, Any]] = []
        self.rpc_data: Any = []

    def _query(self, table: str) -> _FakeBuilder:
        builder = _FakeBuilder(self, table)
        self.builders.append(builder)
        return builder

    def rpc(self, fn: str, params: dict[str, Any]) -> Any:
        self.rpc_calls.append((fn, params))
        return SimpleNamespace(data=self.rpc_data)

    def execute(self, builder: _FakeBuilder) -> Any:
        if builder.op == "insert":
            if self.insert_raises is not None:
                raise self.insert_raises
            return SimpleNamespace(data=[{**_JOB_ROW, **cast(dict[str, Any], builder.op_payload)}])
        if builder.op == "update":
            return SimpleNamespace(data=self.update_rows)
        return SimpleNamespace(data=self.select_rows)


def _queue() -> tuple[JobQueue, _FakeDb]:
    fake = _FakeDb()
    return JobQueue(cast(DatabaseClient, fake)), fake


async def test_enqueue_inserts_queued_row_with_payload() -> None:
    queue, fake = _queue()
    job = await queue.enqueue(
        project_id="p1",
        user_id="u1",
        job_type=JobType.PRESENTATION_GENERATION,
        payload={"product_type": "presentation_basic"},
    )
    insert = next(b for b in fake.builders if b.op == "insert")
    sent = cast(dict[str, Any], insert.op_payload)
    assert sent["status"] == "queued"
    assert sent["job_type"] == "presentation_generation"
    assert sent["payload"] == {"product_type": "presentation_basic"}
    assert job.status is JobStatus.QUEUED


async def test_enqueue_conflict_surfaces_existing_active_job() -> None:
    queue, fake = _queue()
    fake.insert_raises = RuntimeError("duplicate key value violates uq_generation_jobs_active")
    fake.select_rows = [dict(_JOB_ROW)]
    with pytest.raises(DuplicateActiveJobError) as excinfo:
        await queue.enqueue(
            project_id=_JOB_ROW["project_id"],
            user_id="u1",
            job_type=JobType.PRESENTATION_GENERATION,
            payload={},
        )
    assert excinfo.value.existing.id == _JOB_ROW["id"]


async def test_enqueue_error_without_existing_job_reraises() -> None:
    queue, fake = _queue()
    fake.insert_raises = RuntimeError("network down")
    fake.select_rows = []
    with pytest.raises(RuntimeError, match="network down"):
        await queue.enqueue(
            project_id="p1", user_id="u1", job_type=JobType.PRESENTATION_GENERATION, payload={}
        )


async def test_claim_next_goes_through_rpc_and_parses_row() -> None:
    queue, fake = _queue()
    fake.rpc_data = [dict(_JOB_ROW, status="processing", worker_id="w1")]
    job = await queue.claim_next("w1")
    assert fake.rpc_calls == [("claim_next_job", {"p_worker_id": "w1"})]
    assert job is not None and job.status is JobStatus.PROCESSING


async def test_claim_next_empty_queue_returns_none() -> None:
    queue, fake = _queue()
    fake.rpc_data = []
    assert await queue.claim_next("w1") is None


async def test_heartbeat_reports_row_no_longer_ours() -> None:
    queue, fake = _queue()
    fake.rpc_data = False
    assert await queue.heartbeat("j1", "w1") is False
    fake.rpc_data = True
    assert await queue.heartbeat("j1", "w1") is True


async def test_fail_writes_step_named_error_guarded_by_worker_identity() -> None:
    queue, fake = _queue()
    await queue.fail("j1", "w1", step="render", message="boom")
    update = next(b for b in fake.builders if b.op == "update")
    sent = cast(dict[str, Any], update.op_payload)
    assert sent["status"] == "failed"
    assert sent["error_message"] == "render: boom"
    assert ("eq", "worker_id", "w1") in update.filters
    assert ("eq", "status", "processing") in update.filters


async def test_fail_returns_true_only_when_guarded_transition_lands() -> None:
    # F1: the boolean is the refund gate — False means the row was reaped
    # from under us and the reaping side owns the refund.
    queue, fake = _queue()
    fake.update_rows = [dict(_JOB_ROW, status="failed")]
    assert await queue.fail("j1", "w1", step="render", message="boom") is True
    fake.update_rows = []
    assert await queue.fail("j1", "w1", step="render", message="boom") is False


async def test_complete_returns_false_when_row_no_longer_ours() -> None:
    queue, fake = _queue()
    fake.update_rows = []
    assert await queue.complete("j1", "w1", telemetry={}) is False


async def test_fail_truncates_error_to_column_cap() -> None:
    queue, fake = _queue()
    await queue.fail("j1", "w1", step="render", message="x" * 5000)
    update = next(b for b in fake.builders if b.op == "update")
    assert len(cast(dict[str, Any], update.op_payload)["error_message"]) == 4000


async def test_set_progress_guarded_by_worker_and_status() -> None:
    queue, fake = _queue()
    await queue.set_progress("j1", "w1", {"step": "Rendering", "current": 7, "total": 7})
    update = next(b for b in fake.builders if b.op == "update")
    assert cast(dict[str, Any], update.op_payload)["progress"]["step"] == "Rendering"
    assert ("eq", "worker_id", "w1") in update.filters


async def test_reap_stale_returns_failed_jobs_for_refund() -> None:
    queue, fake = _queue()
    fake.rpc_data = [dict(_JOB_ROW, status="failed", error_message="reaped: ...")]
    reaped = await queue.reap_stale(90)
    assert fake.rpc_calls == [("reap_stale_jobs", {"p_stale_seconds": 90})]
    assert len(reaped) == 1 and reaped[0].status is JobStatus.FAILED


async def test_claim_job_cas_returns_none_when_not_queued() -> None:
    queue, fake = _queue()
    fake.update_rows = []
    assert await queue.claim_job("j1", "w1") is None


async def test_claim_job_cas_claims_and_bumps_attempts() -> None:
    queue, fake = _queue()
    fake.update_rows = [dict(_JOB_ROW, status="processing", worker_id="w1")]
    job = await queue.claim_job(_JOB_ROW["id"], "w1")
    assert job is not None and job.worker_id == "w1"
    updates = [b for b in fake.builders if b.op == "update"]
    assert any("attempts" in cast(dict[str, Any], b.op_payload) for b in updates)


async def test_get_active_job_filters_on_active_statuses() -> None:
    queue, fake = _queue()
    fake.select_rows = [dict(_JOB_ROW)]
    job = await queue.get_active_job("p1", JobType.PRESENTATION_GENERATION)
    assert job is not None
    select = fake.builders[0]
    in_filter = next(f for f in select.filters if f[0] == "in")
    assert set(in_filter[2]) == {"queued", "processing"}


def test_generation_job_tolerates_extra_columns() -> None:
    job = GenerationJob.model_validate({**_JOB_ROW, "estimated_cost_uzs": 0, "novel_col": 1})
    assert job.job_type is JobType.PRESENTATION_GENERATION


# ------------------------------------------- get_latest_job over the real fake


def _queue_over_supabase() -> tuple[JobQueue, FakeSupabaseClient]:
    """Drive JobQueue through DatabaseClient against the in-memory Supabase fake.

    ``_FakeDb`` records what was sent but answers every select with the same
    canned rows, so it cannot tell a scoped query from an unscoped one. The
    fake below really filters, orders and limits, which is what makes the
    ``get_latest_job`` scoping assertions below mean anything.
    """

    cfg = PlatformConfig(
        supabase_url="https://test.supabase.co",
        supabase_service_key="test",
        telegram_bot_token="test",
    )
    fake = FakeSupabaseClient()
    return JobQueue(DatabaseClient(cfg, client=cast(Any, fake))), fake


def _seed_job(
    fake: FakeSupabaseClient,
    *,
    job_id: str,
    created_at: datetime,
    project_id: str = "p1",
    job_type: JobType = JobType.PRESENTATION_GENERATION,
    status: JobStatus = JobStatus.COMPLETED,
) -> None:
    rows = fake.tables.setdefault("generation_jobs", [])
    rows.append(
        {
            **_JOB_ROW,
            "id": job_id,
            "project_id": project_id,
            "job_type": job_type.value,
            "status": status.value,
            "created_at": created_at.isoformat(),
        }
    )


_BASE_TS = datetime(2026, 5, 1, tzinfo=UTC)


async def test_get_latest_job_returns_newest_created_at_not_last_inserted() -> None:
    queue, fake = _queue_over_supabase()
    # Deliberately shuffled insert order: a naive "take the last row" reads
    # `old`, and a naive "take the first row" reads `middle`.
    _seed_job(fake, job_id="middle", created_at=_BASE_TS + timedelta(days=2))
    _seed_job(fake, job_id="newest", created_at=_BASE_TS + timedelta(days=3))
    _seed_job(fake, job_id="old", created_at=_BASE_TS + timedelta(days=1))

    job = await queue.get_latest_job("p1", JobType.PRESENTATION_GENERATION)
    assert job is not None and job.id == "newest"


async def test_get_latest_job_ignores_newer_row_of_another_job_type() -> None:
    # Why the route asks for the generation type by name: a conversational fix
    # runs as presentation_edit, and it must never displace the workspace's
    # view of the generation run.
    queue, fake = _queue_over_supabase()
    _seed_job(
        fake,
        job_id="generation",
        created_at=_BASE_TS,
        job_type=JobType.PRESENTATION_GENERATION,
    )
    _seed_job(
        fake,
        job_id="edit",
        created_at=_BASE_TS + timedelta(days=5),
        job_type=JobType.PRESENTATION_EDIT,
    )

    job = await queue.get_latest_job("p1", JobType.PRESENTATION_GENERATION)
    assert job is not None and job.id == "generation"

    edit = await queue.get_latest_job("p1", JobType.PRESENTATION_EDIT)
    assert edit is not None and edit.id == "edit"


async def test_get_latest_job_is_scoped_by_project() -> None:
    queue, fake = _queue_over_supabase()
    _seed_job(fake, job_id="mine", created_at=_BASE_TS, project_id="p1")
    _seed_job(fake, job_id="theirs", created_at=_BASE_TS + timedelta(days=9), project_id="p2")

    job = await queue.get_latest_job("p1", JobType.PRESENTATION_GENERATION)
    assert job is not None and job.id == "mine"


async def test_get_latest_job_returns_none_when_project_has_no_row_of_type() -> None:
    queue, fake = _queue_over_supabase()
    _seed_job(fake, job_id="edit", created_at=_BASE_TS, job_type=JobType.PRESENTATION_EDIT)

    assert await queue.get_latest_job("p1", JobType.PRESENTATION_GENERATION) is None
    assert await queue.get_latest_job("p-empty", JobType.PRESENTATION_EDIT) is None


async def test_get_latest_job_returns_terminal_rows() -> None:
    # The whole reason the method exists: get_active_job answers only "is
    # something running", so a finished-or-failed run would be invisible to a
    # returning user who no longer holds the ?job= URL.
    queue, fake = _queue_over_supabase()
    _seed_job(fake, job_id="completed", created_at=_BASE_TS, status=JobStatus.COMPLETED)
    _seed_job(
        fake,
        job_id="cancelled",
        created_at=_BASE_TS + timedelta(days=1),
        status=JobStatus.CANCELLED,
    )
    _seed_job(
        fake,
        job_id="failed",
        created_at=_BASE_TS + timedelta(days=2),
        status=JobStatus.FAILED,
    )

    job = await queue.get_latest_job("p1", JobType.PRESENTATION_GENERATION)
    assert job is not None
    assert job.id == "failed"
    assert job.status is JobStatus.FAILED
