"""Queue client over the ``generation_jobs`` table (P2 job pipeline).

The row IS the truth: enqueue inserts it, workers claim it atomically through
the migration-006 ``claim_next_job`` SQL function (``FOR UPDATE SKIP LOCKED``),
heartbeat while running, and land it on a terminal status. The reaper turns a
lost worker into an honest failure (or a re-queue while attempts remain) —
never a zombie ``processing`` row.

All Supabase calls go through the injected :class:`DatabaseClient`'s raw query
seam, wrapped in ``asyncio.to_thread`` like every other platform module.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, cast

from pydantic import BaseModel, ConfigDict, Field

from packages.platform.database import DatabaseClient

DEFAULT_STALE_SECONDS: int = 120
HEARTBEAT_INTERVAL_SECONDS: float = 15.0


class JobType(StrEnum):
    """Wire-stable job types (generation_jobs.job_type CHECK, migration 006)."""

    SOURCE_PROCESSING = "source_processing"
    ARTICLE_GENERATION = "article_generation"
    PRESENTATION_GENERATION = "presentation_generation"
    EXPORT = "export"
    PRESENTATION_EDIT = "presentation_edit"
    IMAGE_REGEN = "image_regen"


class JobStatus(StrEnum):
    """Wire-stable job statuses (generation_jobs.status CHECK, migration 006)."""

    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class GenerationJob(BaseModel):
    """One generation_jobs row, as the queue layer reads it."""

    model_config = ConfigDict(extra="ignore")

    id: str
    project_id: str
    user_id: str | None = None
    job_type: JobType
    status: JobStatus
    payload: dict[str, Any] = Field(default_factory=dict)
    progress: dict[str, Any] = Field(default_factory=dict)
    worker_id: str | None = None
    attempts: int = 0
    max_attempts: int = 1
    error_message: str | None = None
    created_at: datetime | None = None
    claimed_at: datetime | None = None
    heartbeat_at: datetime | None = None
    completed_at: datetime | None = None


class DuplicateActiveJobError(Exception):
    """An active (queued/processing) job of this type already exists for the project."""

    def __init__(self, existing: GenerationJob) -> None:
        self.existing = existing
        super().__init__(f"active {existing.job_type} job {existing.id} already queued")


def _row_to_job(row: dict[str, Any]) -> GenerationJob:
    return GenerationJob.model_validate(row)


class JobQueue:
    """Enqueue / claim / heartbeat / terminal transitions for generation jobs."""

    def __init__(self, db: DatabaseClient) -> None:
        self._db = db

    async def get_active_job(self, project_id: str, job_type: JobType) -> GenerationJob | None:
        """Return the project's active job of this type, or None."""

        def run() -> Any:
            return (
                self._db._query("generation_jobs")  # pyright: ignore[reportPrivateUsage]
                .select("*")
                .eq("project_id", project_id)
                .eq("job_type", job_type.value)
                .in_("status", [JobStatus.QUEUED.value, JobStatus.PROCESSING.value])
                .limit(1)
                .execute()
            )

        result = await asyncio.to_thread(run)
        if not result.data:
            return None
        return _row_to_job(cast(dict[str, Any], result.data[0]))

    async def get_job(self, job_id: str) -> GenerationJob | None:
        """Fetch one job row by id."""

        def run() -> Any:
            return (
                self._db._query("generation_jobs")  # pyright: ignore[reportPrivateUsage]
                .select("*")
                .eq("id", job_id)
                .limit(1)
                .execute()
            )

        result = await asyncio.to_thread(run)
        if not result.data:
            return None
        return _row_to_job(cast(dict[str, Any], result.data[0]))

    async def enqueue(
        self,
        *,
        project_id: str,
        user_id: str,
        job_type: JobType,
        payload: dict[str, Any],
        max_attempts: int = 1,
    ) -> GenerationJob:
        """Insert a queued job row.

        The migration-006 partial unique index makes a concurrent double
        enqueue a constraint violation; that surfaces here as
        :class:`DuplicateActiveJobError` carrying the winning row so the
        caller can undo its side effects (the credit deduction) and return
        the existing job instead of executing twice.
        """

        row: dict[str, Any] = {
            "project_id": project_id,
            "user_id": user_id,
            "job_type": job_type.value,
            "status": JobStatus.QUEUED.value,
            "payload": payload,
            "max_attempts": max_attempts,
        }

        def run() -> Any:
            return self._db._query("generation_jobs").insert(row).execute()  # pyright: ignore[reportPrivateUsage]

        try:
            result = await asyncio.to_thread(run)
        except Exception as exc:
            existing = await self.get_active_job(project_id, job_type)
            if existing is not None:
                raise DuplicateActiveJobError(existing) from exc
            raise
        return _row_to_job(cast(dict[str, Any], result.data[0]))

    # ------------------------------------------------------------- worker side

    async def claim_next(self, worker_id: str) -> GenerationJob | None:
        """Atomically claim the oldest queued job, or None when the queue is empty."""

        result = await asyncio.to_thread(
            lambda: self._db.rpc("claim_next_job", {"p_worker_id": worker_id})
        )
        rows = cast(list[dict[str, Any]], list(result.data or []))
        if not rows:
            return None
        return _row_to_job(rows[0])

    async def claim_job(self, job_id: str, worker_id: str) -> GenerationJob | None:
        """Atomically claim ONE specific queued job (the --job-id path).

        A single guarded UPDATE: only a row still ``queued`` transitions, so a
        concurrent loop-worker claim makes this return None instead of
        double-running.
        """

        def run() -> Any:
            return (
                self._db._query("generation_jobs")  # pyright: ignore[reportPrivateUsage]
                .update(
                    {
                        "status": JobStatus.PROCESSING.value,
                        "worker_id": worker_id,
                        "claimed_at": datetime.now(UTC).isoformat(),
                        "heartbeat_at": datetime.now(UTC).isoformat(),
                    }
                )
                .eq("id", job_id)
                .eq("status", JobStatus.QUEUED.value)
                .execute()
            )

        result = await asyncio.to_thread(run)
        rows = cast(list[dict[str, Any]], list(result.data or []))
        if not rows:
            return None
        claimed = _row_to_job(rows[0])

        # attempts/started_at ride a follow-up write; claim atomicity is the
        # status CAS above, not these bookkeeping fields.
        def bump() -> Any:
            return (
                self._db._query("generation_jobs")  # pyright: ignore[reportPrivateUsage]
                .update(
                    {
                        "attempts": claimed.attempts + 1,
                        "started_at": claimed.claimed_at.isoformat()
                        if claimed.claimed_at
                        else datetime.now(UTC).isoformat(),
                    }
                )
                .eq("id", job_id)
                .eq("worker_id", worker_id)
                .execute()
            )

        await asyncio.to_thread(bump)
        return claimed

    async def heartbeat(self, job_id: str, worker_id: str) -> bool:
        """Bump heartbeat_at; False means the row is no longer ours (reaped)."""

        result = await asyncio.to_thread(
            lambda: self._db.rpc("heartbeat_job", {"p_job_id": job_id, "p_worker_id": worker_id})
        )
        return bool(result.data)

    async def set_progress(self, job_id: str, worker_id: str, progress: dict[str, Any]) -> None:
        """Write the UI-polling progress blob, guarded by worker identity."""

        def run() -> Any:
            return (
                self._db._query("generation_jobs")  # pyright: ignore[reportPrivateUsage]
                .update({"progress": progress})
                .eq("id", job_id)
                .eq("worker_id", worker_id)
                .eq("status", JobStatus.PROCESSING.value)
                .execute()
            )

        await asyncio.to_thread(run)

    async def complete(self, job_id: str, worker_id: str, telemetry: dict[str, Any]) -> None:
        """Land the job on ``completed`` with its cost telemetry."""

        await self._finish(job_id, worker_id, JobStatus.COMPLETED, None, telemetry)

    async def fail(
        self,
        job_id: str,
        worker_id: str,
        *,
        step: str,
        message: str,
        telemetry: dict[str, Any] | None = None,
    ) -> None:
        """Land the job on ``failed`` with an honest step-named error message."""

        error = f"{step}: {message}"[:4000]
        await self._finish(job_id, worker_id, JobStatus.FAILED, error, telemetry or {})

    async def _finish(
        self,
        job_id: str,
        worker_id: str,
        status: JobStatus,
        error_message: str | None,
        telemetry: dict[str, Any],
    ) -> None:
        payload: dict[str, Any] = {
            "status": status.value,
            "completed_at": datetime.now(UTC).isoformat(),
            **telemetry,
        }
        if error_message is not None:
            payload["error_message"] = error_message

        def run() -> Any:
            return (
                self._db._query("generation_jobs")  # pyright: ignore[reportPrivateUsage]
                .update(payload)
                .eq("id", job_id)
                .eq("worker_id", worker_id)
                .eq("status", JobStatus.PROCESSING.value)
                .execute()
            )

        await asyncio.to_thread(run)

    async def reap_stale(self, stale_seconds: int = DEFAULT_STALE_SECONDS) -> list[GenerationJob]:
        """Reap zombie processing rows; returns the jobs that were FAILED.

        Retryable zombies are silently re-queued inside the SQL function; only
        the terminally failed ones come back, and only to the single caller
        whose UPDATE won — the refund hook fires exactly once per job.
        """

        result = await asyncio.to_thread(
            lambda: self._db.rpc("reap_stale_jobs", {"p_stale_seconds": stale_seconds})
        )
        rows = cast(list[dict[str, Any]], list(result.data or []))
        return [_row_to_job(r) for r in rows]


__all__ = [
    "DEFAULT_STALE_SECONDS",
    "HEARTBEAT_INTERVAL_SECONDS",
    "DuplicateActiveJobError",
    "GenerationJob",
    "JobQueue",
    "JobStatus",
    "JobType",
]
