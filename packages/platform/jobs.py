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
import contextlib
import logging
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, cast

from pydantic import BaseModel, ConfigDict, Field

from packages.platform.database import DatabaseClient

logger = logging.getLogger("nashr.jobs")

DEFAULT_STALE_SECONDS: int = 120
HEARTBEAT_INTERVAL_SECONDS: float = 15.0


class JobType(StrEnum):
    """Wire-stable job types (generation_jobs.job_type CHECK, migration 006)."""

    SOURCE_PROCESSING = "source_processing"
    ARTICLE_GENERATION = "article_generation"
    PRESENTATION_GENERATION = "presentation_generation"
    EXPORT = "export"
    PRESENTATION_EDIT = "presentation_edit"
    PRESENTATION_RENDER = "presentation_render"
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
    started_at: datetime | None = None
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

    async def get_latest_job(self, project_id: str, job_type: JobType) -> GenerationJob | None:
        """Return the project's most recent job of this type, whatever its status.

        The discovery seam a returning web user needs: ``get_active_job`` only
        answers "is something running", so a finished-or-failed run is
        invisible to anyone who no longer holds the ``?job=`` URL. Ordered by
        ``created_at`` because that is the only timestamp every row has (a
        queued row has no ``started_at``/``completed_at``).
        """

        def run() -> Any:
            return (
                self._db._query("generation_jobs")  # pyright: ignore[reportPrivateUsage]
                .select("*")
                .eq("project_id", project_id)
                .eq("job_type", job_type.value)
                .order("created_at", desc=True)
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

        return await self._insert(row)

    async def start_inline(
        self,
        *,
        project_id: str,
        user_id: str,
        job_type: JobType,
        payload: dict[str, Any],
        worker_id: str,
    ) -> GenerationJob:
        """Insert a job already claimed by ``worker_id`` (an in-process runner).

        The bot renders in its own process; its exports must still be registered
        under a job claim (ADR 0001). Inserting the row ``processing`` with the
        claim in place means the queue worker can never pick it up in between.
        The caller must heartbeat (:func:`heartbeat_while`) and finish it.
        """

        now = datetime.now(UTC).isoformat()
        row: dict[str, Any] = {
            "project_id": project_id,
            "user_id": user_id,
            "job_type": job_type.value,
            "status": JobStatus.PROCESSING.value,
            "payload": payload,
            "max_attempts": 1,
            "attempts": 1,
            "worker_id": worker_id,
            "claimed_at": now,
            "heartbeat_at": now,
            "started_at": now,
        }
        return await self._insert(row)

    async def get_active_render_job(
        self, revision_id: str, renderer_version: str, formats: list[str]
    ) -> GenerationJob | None:
        """The active render job for exactly this revision, renderer and format set."""

        def run() -> Any:
            return (
                self._db._query("generation_jobs")  # pyright: ignore[reportPrivateUsage]
                .select("*")
                .eq("job_type", JobType.PRESENTATION_RENDER.value)
                .eq("payload->>revision_id", revision_id)
                .eq("payload->>renderer_version", renderer_version)
                .in_("status", [JobStatus.QUEUED.value, JobStatus.PROCESSING.value])
                .execute()
            )

        result = await asyncio.to_thread(run)
        wanted = sorted(formats)
        for row in cast(list[dict[str, Any]], list(result.data or [])):
            job = _row_to_job(row)
            if sorted(cast(list[str], job.payload.get("formats", []))) == wanted:
                return job
        return None

    async def _insert(self, row: dict[str, Any]) -> GenerationJob:
        def run() -> Any:
            return self._db._query("generation_jobs").insert(row).execute()  # pyright: ignore[reportPrivateUsage]

        try:
            result = await asyncio.to_thread(run)
        except Exception as exc:
            existing = await self._existing_for(row)
            if existing is not None:
                raise DuplicateActiveJobError(existing) from exc
            raise
        return _row_to_job(cast(dict[str, Any], result.data[0]))

    async def _existing_for(self, row: dict[str, Any]) -> GenerationJob | None:
        """The active job a duplicate insert of ``row`` collided with."""

        job_type = JobType(str(row["job_type"]))
        payload = cast(dict[str, Any], row["payload"])
        if job_type is JobType.PRESENTATION_RENDER:
            return await self.get_active_render_job(
                str(payload.get("revision_id")),
                str(payload.get("renderer_version")),
                cast(list[str], payload.get("formats", [])),
            )
        return await self.get_active_job(str(row["project_id"]), job_type)

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

        One SQL statement (``claim_job``): only a row still ``queued``
        transitions, and the claim token (``attempts``) increments with it, so a
        concurrent loop-worker claim makes this return None instead of
        double-running.
        """

        result = await asyncio.to_thread(
            lambda: self._db.rpc("claim_job", {"p_job_id": job_id, "p_worker_id": worker_id})
        )
        rows = cast(list[dict[str, Any]], list(result.data or []))
        if not rows:
            return None
        return _row_to_job(rows[0])

    async def heartbeat(self, job_id: str, worker_id: str, claim_token: int) -> bool:
        """Bump heartbeat_at; False means the claim is no longer ours (reaped or reclaimed)."""

        result = await asyncio.to_thread(
            lambda: self._db.rpc(
                "heartbeat_job",
                {"p_job_id": job_id, "p_worker_id": worker_id, "p_claim_token": claim_token},
            )
        )
        return bool(result.data)

    async def set_progress(
        self, job_id: str, worker_id: str, claim_token: int, progress: dict[str, Any]
    ) -> None:
        """Write the UI-polling progress blob, guarded by the caller's claim."""

        def run() -> Any:
            return (
                self._db._query("generation_jobs")  # pyright: ignore[reportPrivateUsage]
                .update({"progress": progress})
                .eq("id", job_id)
                .eq("worker_id", worker_id)
                .eq("attempts", claim_token)
                .eq("status", JobStatus.PROCESSING.value)
                .execute()
            )

        await asyncio.to_thread(run)

    async def complete(
        self, job_id: str, worker_id: str, claim_token: int, progress: dict[str, Any]
    ) -> bool:
        """Complete a job that commits no revision; False means the claim was lost.

        Generation and edit jobs complete only through
        ``DocumentStore.finish_generation_job``, together with their revision.
        """

        result = await asyncio.to_thread(
            lambda: self._db.rpc(
                "complete_job",
                {
                    "p_job_id": job_id,
                    "p_worker_id": worker_id,
                    "p_claim_token": claim_token,
                    "p_progress": progress,
                },
            )
        )
        return bool(result.data)

    async def fail(
        self,
        job_id: str,
        worker_id: str,
        claim_token: int,
        *,
        step: str,
        message: str,
    ) -> bool:
        """Land the job on ``failed`` with an honest step-named error message.

        Returns True iff OUR guarded transition landed. False means the row
        was already taken from us (reaped, possibly re-queued and refunded) —
        the caller must NOT refund on False or a stalled-but-alive worker
        racing the reaper double-refunds.
        """

        error = f"{step}: {message}"[:4000]

        def run() -> Any:
            return (
                self._db._query("generation_jobs")  # pyright: ignore[reportPrivateUsage]
                .update(
                    {
                        "status": JobStatus.FAILED.value,
                        "completed_at": datetime.now(UTC).isoformat(),
                        "error_message": error,
                    }
                )
                .eq("id", job_id)
                .eq("worker_id", worker_id)
                .eq("attempts", claim_token)
                .eq("status", JobStatus.PROCESSING.value)
                .execute()
            )

        result = await asyncio.to_thread(run)
        return bool(cast(list[dict[str, Any]], list(result.data or [])))

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


@contextlib.asynccontextmanager
async def heartbeat_while(
    queue: JobQueue,
    job_id: str,
    worker_id: str,
    claim_token: int,
    interval: float = HEARTBEAT_INTERVAL_SECONDS,
) -> AsyncGenerator[None]:
    """Keep ``job_id``'s claim alive while the body runs (for inline runners).

    The reaper fails a processing row whose heartbeat is older than
    :data:`DEFAULT_STALE_SECONDS`; a render takes longer than that. A lost claim is
    not raised here: ``register_export`` and the guarded terminal write already
    refuse a worker that no longer owns the row.
    """

    async def beat() -> None:
        while True:
            await asyncio.sleep(interval)
            try:
                if not await queue.heartbeat(job_id, worker_id, claim_token):
                    logger.warning("inline_job_heartbeat_lost job=%s", job_id)
            except Exception as exc:
                logger.warning(
                    "inline_job_heartbeat_error job=%s error_type=%s", job_id, type(exc).__name__
                )

    task = asyncio.create_task(beat())
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


__all__ = [
    "DEFAULT_STALE_SECONDS",
    "HEARTBEAT_INTERVAL_SECONDS",
    "DuplicateActiveJobError",
    "GenerationJob",
    "JobQueue",
    "JobStatus",
    "JobType",
    "heartbeat_while",
]
