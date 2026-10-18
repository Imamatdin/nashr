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
import json
import logging
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError

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
    """Wire-stable job statuses (generation_jobs.status CHECK, migration 016)."""

    QUEUED = "queued"
    PROCESSING = "processing"
    # A generation/edit job whose revision is committed while its render job
    # publishes the exports; it becomes COMPLETED (delivered) or DELIVERY_FAILED.
    COMMITTED = "committed"
    COMPLETED = "completed"
    FAILED = "failed"
    # The render failed for good: the job was refunded, the revision kept.
    DELIVERY_FAILED = "delivery_failed"
    CANCELLED = "cancelled"


# Statuses a job never leaves.
TERMINAL_STATUSES: frozenset[JobStatus] = frozenset(
    {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.DELIVERY_FAILED, JobStatus.CANCELLED}
)


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
    # The render job delivering this job's committed revision (B1-FIX2).
    render_job_id: str | None = None


class RenderRequest(BaseModel):
    """What ``request_render`` decided: nothing left, an active render reused, or queued."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["ready", "reused", "queued"]
    job_id: str | None = None
    formats: list[str] = Field(default_factory=list[str])


class DuplicateActiveJobError(Exception):
    """An active (queued/processing) job of this type already exists for the project."""

    def __init__(self, existing: GenerationJob) -> None:
        self.existing = existing
        super().__init__(f"active {existing.job_type} job {existing.id} already queued")


# Why migration 016 refuses an AI edit's identity (B1-FIX4, Codex F3).
EDIT_IDENTITY_REFUSALS: frozenset[str] = frozenset(
    {"edit_identity_missing", "edit_session_not_found", "edit_operation_stale"}
)


class EditIdentityRefusedError(Exception):
    """The database refused an AI edit: no session, someone else's, or a call no longer parked."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(f"AI edit refused: {code}")


def edit_identity_refusal(exc: BaseException) -> str | None:
    """The identity refusal an error from the database carries, if it is one."""

    text = f"{getattr(exc, 'message', '') or ''} {exc}"
    return next((code for code in sorted(EDIT_IDENTITY_REFUSALS) if code in text), None)


class JobDataInvalidError(Exception):
    """A persisted generation_jobs row does not parse (B1-FIX3, Codex A3).

    The generic queue schema allows any JSON in ``payload`` and ``progress``; the
    Python model requires objects. A read of such a row is a state error the API
    answers with 409 ``job_data_invalid``, never a 500, and the row is left as it is.
    """

    def __init__(self, job_id: str, detail: str) -> None:
        self.job_id = job_id
        self.detail = detail
        super().__init__(f"generation job {job_id} is malformed: {detail}")


def _row_to_job(row: dict[str, Any]) -> GenerationJob:
    try:
        return GenerationJob.model_validate(row)
    except ValidationError as exc:
        job_id = str(row.get("id") or "unknown")
        fields = sorted({".".join(str(p) for p in error["loc"]) for error in exc.errors()})
        detail = ",".join(fields) or "row"
        logger.error("job_data_invalid %s", json.dumps({"job_id": job_id, "fields": detail}))
        raise JobDataInvalidError(job_id, detail) from None


def validated_payload(payload: object) -> dict[str, Any]:
    """Refuse a job payload that is not a JSON object before it is written.

    Every reader parses the payload as an object; the enqueue boundary is where
    anything else is stopped (Codex A3).
    """

    if not isinstance(payload, dict):
        raise ValueError("job payload must be a JSON object")
    typed = cast(dict[Any, Any], payload)
    if not all(isinstance(key, str) for key in typed):
        raise ValueError("job payload keys must be strings")
    try:
        json.dumps(typed, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"job payload is not JSON: {exc}") from None
    return cast(dict[str, Any], typed)


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

    async def get_edit_job(
        self, project_id: str, session_id: str, operation_id: str
    ) -> GenerationJob | None:
        """The latest edit job queued for one parked call: its session AND its operation.

        A parked call is identified by both ids (B1-FIX4, Codex F2), never by the
        conversation's length, so another session's or another call's job cannot
        be taken for this one. An approval re-approved after its job failed queues
        a second job for the same call; the latest one carries the outcome.
        """

        def run() -> Any:
            return (
                self._db._query("generation_jobs")  # pyright: ignore[reportPrivateUsage]
                .select("*")
                .eq("project_id", project_id)
                .eq("job_type", JobType.PRESENTATION_EDIT.value)
                .eq("payload->>session_id", session_id)
                .eq("payload->>operation_id", operation_id)
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

    async def jobs_for_render(self, render_job_id: str) -> list[GenerationJob]:
        """Every job whose committed revision this render job delivers (B1-FIX2).

        A render completing flips each such parent to ``completed`` in the same
        transaction; the worker reads them back to deliver bot-enqueued edits to
        Telegram (B8.1). A row that does not parse is skipped, not fatal.
        """

        def run() -> Any:
            return (
                self._db._query("generation_jobs")  # pyright: ignore[reportPrivateUsage]
                .select("*")
                .eq("render_job_id", render_job_id)
                .execute()
            )

        result = await asyncio.to_thread(run)
        jobs: list[GenerationJob] = []
        for row in cast(list[dict[str, Any]], list(result.data or [])):
            try:
                jobs.append(_row_to_job(row))
            except JobDataInvalidError:
                continue
        return jobs

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
            "payload": validated_payload(payload),
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
            "payload": validated_payload(payload),
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

    async def request_render(
        self,
        *,
        project_id: str,
        user_id: str,
        revision_id: str,
        renderer_version: str,
        formats: list[str],
        max_attempts: int,
    ) -> RenderRequest:
        """Render the missing formats of a revision the user owns (``request_render``).

        One SQL decision under a per-revision lock: formats already registered are
        skipped, an active render whose formats cover the rest is reused (superset
        match), otherwise one render job is queued.
        """

        result = await asyncio.to_thread(
            lambda: self._db.rpc(
                "request_render",
                {
                    "p_project_id": project_id,
                    "p_user_id": user_id,
                    "p_revision_id": revision_id,
                    "p_renderer_version": renderer_version,
                    "p_formats": formats,
                    "p_max_attempts": max_attempts,
                },
            )
        )
        rows = cast(list[dict[str, Any]], list(result.data or []))
        if not rows:
            raise RuntimeError("request_render returned no decision")
        row = rows[0]
        return RenderRequest(
            status=row["status"],
            job_id=str(row["job_id"]) if row.get("job_id") else None,
            formats=[str(f) for f in cast(list[Any], row.get("formats") or [])],
        )

    async def _insert(self, row: dict[str, Any]) -> GenerationJob:
        def run() -> Any:
            return self._db._query("generation_jobs").insert(row).execute()  # pyright: ignore[reportPrivateUsage]

        try:
            result = await asyncio.to_thread(run)
        except Exception as exc:
            refusal = edit_identity_refusal(exc)
            if refusal is not None:
                raise EditIdentityRefusedError(refusal) from exc
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
        return await self._claimed(rows[0], worker_id)

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
        return await self._claimed(rows[0], worker_id)

    async def _claimed(self, row: dict[str, Any], worker_id: str) -> GenerationJob | None:
        """The claimed job, or None after failing a row no worker can run.

        A malformed row is failed under the claim just taken (and refunded, when it
        charged, by fail_job) instead of being retried by the reaper forever.
        """

        try:
            return _row_to_job(row)
        except JobDataInvalidError as exc:
            attempts = row.get("attempts")
            if isinstance(attempts, int):
                await self.fail(
                    exc.job_id, worker_id, attempts, step="claim", message="job_data_invalid"
                )
            return None

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
        """Fail the job and refund what it charged, in one transaction (``fail_job``).

        Returns True iff the caller still held the claim and the job is now
        failed (and, if it was paid, refunded exactly once). False means the claim
        was gone: whoever holds the job (the reaper, another worker) settles it.
        """

        result = await asyncio.to_thread(
            lambda: self._db.rpc(
                "fail_job",
                {
                    "p_job_id": job_id,
                    "p_worker_id": worker_id,
                    "p_claim_token": claim_token,
                    "p_step": step,
                    "p_message": message[:3900],
                },
            )
        )
        return bool(result.data)

    async def reap_stale(self, stale_seconds: int = DEFAULT_STALE_SECONDS) -> list[GenerationJob]:
        """Reap zombie rows; returns the jobs that were FAILED or DELIVERY_FAILED.

        Retryable zombies are re-queued inside the SQL function; exhausted ones
        are failed and, when paid, refunded in the same transaction. Committed jobs
        whose render is gone or failed are delivery_failed and refunded; those whose
        render completed are completed. The rows come back for logging only.
        """

        result = await asyncio.to_thread(
            lambda: self._db.rpc("reap_stale_jobs", {"p_stale_seconds": stale_seconds})
        )
        rows = cast(list[dict[str, Any]], list(result.data or []))
        reaped: list[GenerationJob] = []
        for row in rows:
            # Returned for logging only; a malformed row is already settled.
            try:
                reaped.append(_row_to_job(row))
            except JobDataInvalidError:
                continue
        return reaped


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
    "EDIT_IDENTITY_REFUSALS",
    "HEARTBEAT_INTERVAL_SECONDS",
    "TERMINAL_STATUSES",
    "DuplicateActiveJobError",
    "EditIdentityRefusedError",
    "GenerationJob",
    "JobDataInvalidError",
    "JobQueue",
    "JobStatus",
    "JobType",
    "RenderRequest",
    "edit_identity_refusal",
    "heartbeat_while",
    "validated_payload",
]
