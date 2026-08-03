"""Behaviour tests for the worker entrypoint helpers and backup scripts."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

import pytest

from packages.platform.credits import CreditLedger
from packages.platform.jobs import GenerationJob, JobType
from scripts.backup_db import (
    BACKUP_PREFIX,
    RETENTION_DAYS,
    _dump_key,
    _seconds_until_nightly,
)
from scripts.worker_run_job import JobRunner, _refund_amount, _refund_job


def _job(**overrides: Any) -> GenerationJob:
    row: dict[str, Any] = {
        "id": "11111111-1111-1111-1111-111111111111",
        "project_id": "p1",
        "user_id": "u1",
        "job_type": "presentation_generation",
        "status": "processing",
        "payload": {"product_type": "presentation_standard"},
    }
    row.update(overrides)
    return GenerationJob.model_validate(row)


class _FakeCredits:
    def __init__(self) -> None:
        self.refunds: list[tuple[str, str, int, str]] = []

    async def refund(self, user_id: str, project_id: str, amount: int, reason: str) -> None:
        self.refunds.append((user_id, project_id, amount, reason))


class _FakeQueue:
    def __init__(self) -> None:
        self.failed: list[dict[str, Any]] = []
        self.completed: list[str] = []

    async def fail(
        self,
        job_id: str,
        worker_id: str,
        *,
        step: str,
        message: str,
        telemetry: dict[str, Any] | None = None,
    ) -> None:
        self.failed.append({"job_id": job_id, "step": step, "message": message})

    async def complete(self, job_id: str, worker_id: str, telemetry: dict[str, Any]) -> None:
        self.completed.append(job_id)

    async def heartbeat(self, job_id: str, worker_id: str) -> bool:
        return True


def test_refund_amount_reads_product_type_pricing() -> None:
    assert (
        _refund_amount({"product_type": "presentation_standard"})
        == (CreditLedger.PRICING["presentation_standard"])
    )
    assert _refund_amount({"product_type": "nonsense"}) is None
    assert _refund_amount({}) is None


@pytest.mark.asyncio
async def test_refund_job_writes_priced_refund() -> None:
    credits = _FakeCredits()
    await _refund_job(cast(Any, credits), _job(), "refund:job:x:render")
    assert credits.refunds == [("u1", "p1", 10_000, "refund:job:x:render")]


@pytest.mark.asyncio
async def test_refund_job_skips_unpriced_payload() -> None:
    credits = _FakeCredits()
    await _refund_job(cast(Any, credits), _job(payload={}), "refund:job:x:render")
    assert credits.refunds == []


def _runner(queue: _FakeQueue, credits: _FakeCredits) -> JobRunner:
    return JobRunner(
        cast(Any, object()),
        cast(Any, object()),
        cast(Any, queue),
        cast(Any, credits),
        cast(Any, object()),
        "w-test",
    )


@pytest.mark.asyncio
async def test_unsupported_job_type_fails_honestly_and_refunds() -> None:
    queue, credits = _FakeQueue(), _FakeCredits()
    runner = _runner(queue, credits)
    job = _job(job_type=JobType.IMAGE_REGEN.value)
    await runner._execute(job)  # pyright: ignore[reportPrivateUsage]
    assert queue.failed[0]["step"] == "dispatch"
    assert "image_regen" in queue.failed[0]["message"]
    assert len(credits.refunds) == 1


@pytest.mark.asyncio
async def test_orchestrator_error_lands_step_named_failure_and_refund(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue, credits = _FakeQueue(), _FakeCredits()
    runner = _runner(queue, credits)

    class _StepError(Exception):
        def __init__(self) -> None:
            super().__init__("editorial blew up")
            self.step = "editorial"
            self.original = RuntimeError("schema cascade")

    async def boom(job: GenerationJob) -> None:
        raise _StepError()

    monkeypatch.setattr(runner, "_run_presentation", boom)
    await runner._execute(_job())  # pyright: ignore[reportPrivateUsage]
    assert queue.failed[0]["step"] == "editorial"
    assert "schema cascade" in queue.failed[0]["message"]
    assert credits.refunds[0][3].endswith(":editorial")


@pytest.mark.asyncio
async def test_success_path_never_refunds(monkeypatch: pytest.MonkeyPatch) -> None:
    queue, credits = _FakeQueue(), _FakeCredits()
    runner = _runner(queue, credits)

    async def ok(job: GenerationJob) -> None:
        await queue.complete(job.id, "w-test", telemetry={})

    monkeypatch.setattr(runner, "_run_presentation", ok)
    await runner._execute(_job())  # pyright: ignore[reportPrivateUsage]
    assert queue.failed == [] and credits.refunds == []


# ------------------------------------------------------------------- backup


def test_dump_key_is_timestamped_under_backups_prefix() -> None:
    key = _dump_key(datetime(2026, 8, 3, 2, 0, 0, tzinfo=UTC))
    assert key == f"{BACKUP_PREFIX}nashr_20260803T020000Z.dump"


def test_seconds_until_nightly_rolls_to_next_day() -> None:
    before = datetime(2026, 8, 3, 1, 0, 0, tzinfo=UTC)
    after = datetime(2026, 8, 3, 3, 0, 0, tzinfo=UTC)
    assert _seconds_until_nightly(before) == 3600.0
    assert _seconds_until_nightly(after) == 23 * 3600.0


def test_retention_days_is_fourteen() -> None:
    assert RETENTION_DAYS == 14
