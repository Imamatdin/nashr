"""Queue worker over generation_jobs (P2): claim → run → heartbeat → terminal row.

Two modes::

    python scripts/worker_run_job.py --job-id <uuid>   # run ONE specific job
    python scripts/worker_run_job.py --loop            # VM compose service

The loop mode polls ``claim_next_job`` (atomic, SKIP LOCKED), runs each claimed
job through the REAL :class:`PresentationOrchestrator` (a real aiogram Bot —
bot-enqueued jobs carry Telegram file_ids, web jobs carry R2 storage keys; the
orchestrator handles both), and reaps zombie ``processing`` rows every tick,
refunding the honest-failed ones through the existing ledger path.

Failure contract: an ``_OrchestratorError`` lands the job on ``failed`` with
its step name in ``error_message`` AND refunds the enqueue-time deduction —
exactly the bot handler's refund discipline, moved queue-side.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import socket
import sys
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, cast

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from packages.core.enums import ExportFormat, GenerationPackage
from packages.platform.config import PlatformConfig
from packages.platform.credits import CreditLedger
from packages.platform.database import DatabaseClient
from packages.platform.jobs import (
    DEFAULT_STALE_SECONDS,
    HEARTBEAT_INTERVAL_SECONDS,
    GenerationJob,
    JobQueue,
    JobType,
)
from packages.platform.storage import FileStorage

logger = logging.getLogger("nashr.worker")

POLL_INTERVAL_SECONDS = 5.0


def _worker_id() -> str:
    return f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:6]}"


def _refund_amount(payload: dict[str, Any]) -> int | None:
    # Prefer the amount actually deducted at enqueue time (stamped into the
    # payload by the route); PRICING is only the fallback for rows enqueued
    # before deducted_amount existed. Refunding current-price on a stale row
    # would mismatch the ledger after a price change.
    deducted = payload.get("deducted_amount")
    if isinstance(deducted, int) and deducted > 0:
        return deducted
    product_type = payload.get("product_type")
    if isinstance(product_type, str) and product_type in CreditLedger.PRICING:
        return CreditLedger.PRICING[product_type]
    return None


async def _refund_job(credits: CreditLedger, job: GenerationJob, reason: str) -> None:
    """Refund a failed job's deduction; a job with no priced payload is skipped."""

    amount = _refund_amount(job.payload)
    if amount is None or job.user_id is None:
        logger.warning(
            "worker_refund_skipped %s",
            json.dumps({"job_id": job.id, "reason": "no product_type or user_id"}),
        )
        return
    # Stamped with the job id so GET /jobs can state the refund as a FACT
    # rather than inferring it from timestamps (JobView.refunded).
    await credits.refund(
        job.user_id,
        job.project_id,
        amount,
        reason=reason[:200],
        generation_job_id=job.id,
    )
    logger.info(
        "worker_job_refunded %s",
        json.dumps({"job_id": job.id, "amount": amount, "reason": reason[:200]}),
    )


class JobRunner:
    """Executes one claimed job with a live heartbeat and progress writes."""

    def __init__(
        self,
        config: PlatformConfig,
        db: DatabaseClient,
        queue: JobQueue,
        credits: CreditLedger,
        storage: FileStorage,
        worker_id: str,
    ) -> None:
        self._config = config
        self._db = db
        self._queue = queue
        self._credits = credits
        self._storage = storage
        self._worker_id = worker_id

    async def run(self, job: GenerationJob) -> None:
        heartbeat = asyncio.create_task(self._heartbeat_forever(job.id))
        try:
            await self._execute(job)
        finally:
            heartbeat.cancel()

    async def _heartbeat_forever(self, job_id: str) -> None:
        while True:
            await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)
            try:
                alive = await self._queue.heartbeat(job_id, self._worker_id)
                if not alive:
                    logger.warning(
                        "worker_heartbeat_lost %s",
                        json.dumps({"job_id": job_id, "worker_id": self._worker_id}),
                    )
            except Exception as exc:
                logger.warning(
                    "worker_heartbeat_error %s",
                    json.dumps({"job_id": job_id, "error_type": type(exc).__name__}),
                )

    async def _execute(self, job: GenerationJob) -> None:
        # Refunds are gated on OUR guarded fail() transition landing: if the
        # reaper already took the row (stalled-but-alive worker), the reaping
        # side owns the refund and ours must not fire — one refund per job.
        #
        # An EDIT job is never refundable: no credit was taken for it (a fix
        # spends the tier's fix allowance, not money), so its payload carries no
        # price and a refund attempt would be a no-op with a misleading log.
        runner = self._executor_for(job.job_type)
        if runner is None:
            failed_by_us = await self._queue.fail(
                job.id,
                self._worker_id,
                step="dispatch",
                message=f"job_type {job.job_type.value} has no worker executor yet",
            )
            if failed_by_us:
                await _refund_job(self._credits, job, f"refund:job:{job.id}:unsupported_type")
            return
        refundable = job.job_type is JobType.PRESENTATION_GENERATION
        try:
            await runner(job)
        except Exception as exc:
            step = getattr(exc, "step", "pipeline")
            original = getattr(exc, "original", exc)
            message = f"{type(original).__name__}: {original}"
            logger.exception(
                "worker_job_failed %s",
                json.dumps({"job_id": job.id, "step": step}),
            )
            failed_by_us = await self._queue.fail(
                job.id, self._worker_id, step=str(step), message=message
            )
            if failed_by_us and refundable:
                await _refund_job(self._credits, job, f"refund:job:{job.id}:{step}")
            elif not failed_by_us:
                logger.warning(
                    "worker_refund_suppressed_row_not_ours %s",
                    json.dumps({"job_id": job.id, "step": str(step)}),
                )

    def _executor_for(self, job_type: JobType) -> Callable[[GenerationJob], Awaitable[None]] | None:
        """The coroutine that runs this job type, or None when unsupported."""

        if job_type is JobType.PRESENTATION_GENERATION:
            return self._run_presentation
        if job_type is JobType.PRESENTATION_EDIT:
            return self._run_presentation_edit
        return None

    async def _run_presentation_edit(self, job: GenerationJob) -> None:
        """Apply a parked Way-2 fix batch and re-render. No charge, no refund.

        The API ran the brain turn and parked the batch (its ``edit_slides``
        call is still unanswered in the session history); this answers it. The
        deck-persist and the R2 upload of every re-rendered format both happen
        inside ``apply_fixes_and_render`` → ``render``, so the web's deck route
        serves the edited files without any extra wiring here.
        """

        from aiogram import Bot

        from packages.bot.orchestrators.presentation_orchestrator import (
            PresentationOrchestrator,
        )
        from packages.core.models.presentation import SlideFix
        from packages.sessions_core import dispatch_fix, park_pending_for_apply

        payload = job.payload
        call_count = 1
        raw_count = payload.get("call_count")
        if isinstance(raw_count, int) and raw_count >= 1:
            call_count = raw_count

        if payload.get("from_pending") is True:
            pending = await park_pending_for_apply(self._db, job.project_id)
            if pending is None:
                raise RuntimeError("approved change is no longer parked on the session")
            fixes = list(pending.fixes)
            call_count = pending.call_count
        else:
            raw_fixes = payload.get("fixes")
            if not isinstance(raw_fixes, list) or not raw_fixes:
                raise RuntimeError("presentation_edit job carries no fixes")
            # ALL-OR-NOTHING, matching apply_fixes_and_render's atomic batch
            # semantics. Skipping malformed entries would apply part of an
            # approved batch, consume the tier's fix allowance for it, and
            # report success — the user would pay an edit for a change they
            # never fully got. A malformed payload is a bug; fail the job.
            fixes: list[SlideFix] = []
            for entry in cast(list[Any], raw_fixes):
                if not isinstance(entry, dict):
                    raise RuntimeError("presentation_edit job carries a malformed fix entry")
                fixes.append(SlideFix.model_validate(cast(dict[str, Any], entry)))

        bot = Bot(token=self._config.telegram_bot_token)
        orchestrator = PresentationOrchestrator(
            bot=bot,
            db=self._db,
            credits=self._credits,
            storage=self._storage,
        )

        async def progress(step: str, current: int, total: int) -> None:
            await self._queue.set_progress(
                job.id,
                self._worker_id,
                {"step": step, "current": current, "total": total},
            )

        try:
            result = await dispatch_fix(
                runner=orchestrator,
                db=self._db,
                project_id=job.project_id,
                fixes=fixes,
                call_count=call_count,
                progress=progress,
            )
        finally:
            await bot.session.close()

        if not result.delivered:
            # dispatch_fix already answered the parked call and persisted, so
            # the session is coherent; the job row just has to say what happened.
            failed_by_us = await self._queue.fail(
                job.id,
                self._worker_id,
                step="apply_fixes",
                message=result.reason or "edit produced no deliverable files",
            )
            if not failed_by_us:
                logger.warning("worker_edit_fail_row_not_ours %s", json.dumps({"job_id": job.id}))
            return

        completed_by_us = await self._queue.complete(job.id, self._worker_id, telemetry={})
        if not completed_by_us:
            logger.warning(
                "worker_complete_suppressed_row_not_ours %s", json.dumps({"job_id": job.id})
            )
            return
        logger.info(
            "worker_edit_completed %s",
            json.dumps(
                {
                    "job_id": job.id,
                    "project_id": job.project_id,
                    "slides_changed": result.slides_changed,
                    "warnings": list(result.warnings),
                }
            ),
        )

    async def _run_presentation(self, job: GenerationJob) -> None:
        # Imported here so --help / unit tests never pull aiogram + the full
        # pipeline stack just to parse args.
        from aiogram import Bot

        from packages.bot.orchestrators.presentation_orchestrator import (
            PresentationOrchestrator,
        )

        payload = job.payload
        package = GenerationPackage(str(payload.get("package", "presentation_standard")))
        formats_raw = payload.get("formats")
        formats: list[ExportFormat] | None = None
        if isinstance(formats_raw, list) and formats_raw:
            formats = [ExportFormat(str(f)) for f in cast(list[Any], formats_raw)]
        sources_raw = payload.get("sources")
        file_infos: list[dict[str, object]] = []
        if isinstance(sources_raw, list):
            for entry in cast(list[Any], sources_raw):
                if isinstance(entry, dict):
                    file_infos.append(cast(dict[str, object], entry))
        answers_raw = payload.get("answers")
        answers: dict[str, object] | None = (
            cast(dict[str, object], answers_raw) if isinstance(answers_raw, dict) else None
        )
        language = str(payload.get("language", "uz"))
        topic_raw = payload.get("topic")
        topic = topic_raw if isinstance(topic_raw, str) and topic_raw.strip() else None
        if job.user_id is None:
            raise RuntimeError("job has no user_id; cannot run entitled pipeline")

        bot = Bot(token=self._config.telegram_bot_token)
        orchestrator = PresentationOrchestrator(
            bot=bot,
            db=self._db,
            credits=self._credits,
            storage=self._storage,
        )

        async def progress(step: str, current: int, total: int) -> None:
            await self._queue.set_progress(
                job.id,
                self._worker_id,
                {"step": step, "current": current, "total": total},
            )

        try:
            result = await orchestrator.run_full_pipeline(
                file_infos=file_infos,
                project_id=job.project_id,
                user_id=job.user_id,
                language=language,
                raw_answers=answers,
                requested_formats=formats,
                progress=progress,
                package=package,
                topic=topic,
            )
        finally:
            await bot.session.close()

        files = {ext: str(path) for ext, path in result.render.by_extension().items()}

        # Persist the brain session the bot's delivery handler would have
        # created: web jobs have no Telegram delivery, and the session row is
        # what the provenance view (and later web editing) reads. Best-effort —
        # the deck is already rendered and uploaded, so a session write failure
        # degrades provenance, not delivery.
        try:
            from packages.bot.sessions.store import create_session

            await create_session(
                self._db,
                project_id=job.project_id,
                sources=result.sources,
                package=package,
                formats=formats or [ExportFormat.HTML, ExportFormat.PPTX_EDITABLE],
            )
        except Exception as exc:
            logger.warning(
                "worker_session_persist_failed %s",
                json.dumps({"job_id": job.id, "error_type": type(exc).__name__}),
            )

        completed_by_us = await self._queue.complete(job.id, self._worker_id, telemetry={})
        if not completed_by_us:
            # Reaped while we were (slowly) finishing: the row is failed or
            # re-queued and possibly refunded — do not report success. The
            # --job-id exit code re-reads the row and will reflect this.
            logger.warning(
                "worker_complete_suppressed_row_not_ours %s",
                json.dumps({"job_id": job.id}),
            )
            return
        logger.info(
            "worker_job_completed %s",
            json.dumps({"job_id": job.id, "project_id": job.project_id, "files": files}),
        )


async def _reap(queue: JobQueue, credits: CreditLedger, stale_seconds: int) -> None:
    try:
        failed = await queue.reap_stale(stale_seconds)
    except Exception as exc:
        logger.warning("worker_reap_error %s", json.dumps({"error_type": type(exc).__name__}))
        return
    for job in failed:
        logger.warning(
            "worker_job_reaped %s",
            json.dumps({"job_id": job.id, "error_message": job.error_message}),
        )
        await _refund_job(credits, job, f"refund:job:{job.id}:reaped")


async def _amain(args: argparse.Namespace) -> int:
    config = PlatformConfig.from_env()
    db = DatabaseClient(config)
    queue = JobQueue(db)
    credits = CreditLedger(db, dev_mode=config.dev_mode)
    storage = FileStorage(config)
    worker_id = _worker_id()
    runner = JobRunner(config, db, queue, credits, storage, worker_id)
    logger.info("worker_started %s", json.dumps({"worker_id": worker_id, "loop": args.loop}))

    if args.job_id:
        claimed = await queue.claim_job(args.job_id, worker_id)
        if claimed is None:
            job = await queue.get_job(args.job_id)
            state = job.status.value if job is not None else "not_found"
            logger.error(
                "worker_job_not_claimable %s",
                json.dumps({"job_id": args.job_id, "status": state}),
            )
            return 1
        await runner.run(claimed)
        final = await queue.get_job(args.job_id)
        return 0 if final is not None and final.status.value == "completed" else 1

    while True:
        await _reap(queue, credits, args.stale_seconds)
        try:
            job = await queue.claim_next(worker_id)
        except Exception as exc:
            logger.warning("worker_claim_error %s", json.dumps({"error_type": type(exc).__name__}))
            job = None
        if job is None:
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
            continue
        logger.info(
            "worker_job_claimed %s",
            json.dumps({"job_id": job.id, "job_type": job.job_type.value}),
        )
        await runner.run(job)


def main() -> int:
    parser = argparse.ArgumentParser(description="Nashr generation-jobs worker")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--job-id", help="run one specific queued job, then exit")
    group.add_argument("--loop", action="store_true", help="poll-claim-run forever (VM service)")
    parser.add_argument(
        "--stale-seconds",
        type=int,
        default=DEFAULT_STALE_SECONDS,
        help="heartbeat age after which a processing row is reaped",
    )
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    return asyncio.run(_amain(args))


if __name__ == "__main__":
    raise SystemExit(main())
