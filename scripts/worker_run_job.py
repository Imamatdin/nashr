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
its step name in ``error_message``. The refund of the enqueue-time deduction is
written by the database in the same transaction (``fail_job`` / the reaper), so
a crash can never leave a failed paid job unrefunded (ADR 0001 §6.6).
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
from typing import TYPE_CHECKING, Any, cast

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


from packages.core.enums import ExportFormat, GenerationPackage
from packages.platform.config import PlatformConfig
from packages.platform.credits import CreditLedger
from packages.platform.database import DatabaseClient
from packages.platform.document_models import (
    CommitOutcome,
    DocumentKind,
    RevisionKind,
)
from packages.platform.document_store import DocumentStore
from packages.platform.exports import ExportPublisher, renderer_version
from packages.platform.jobs import (
    DEFAULT_STALE_SECONDS,
    HEARTBEAT_INTERVAL_SECONDS,
    GenerationJob,
    JobQueue,
    JobType,
)
from packages.platform.liveness import LivenessFile
from packages.platform.storage import FileStorage

if TYPE_CHECKING:
    from aiogram import Bot

    from packages.bot.orchestrators.presentation_orchestrator import PresentationOrchestrator

logger = logging.getLogger("nashr.worker")

POLL_INTERVAL_SECONDS = 5.0
# What a web edit is rendered into: every primary format (SPEC §0 rule 7).
WEB_FILE_FORMATS: tuple[str, ...] = ("html", "pdf", "pptx")


def _worker_id() -> str:
    return f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:6]}"


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
        liveness: LivenessFile | None = None,
    ) -> None:
        self._config = config
        self._db = db
        self._queue = queue
        self._credits = credits
        self._storage = storage
        self._worker_id = worker_id
        self._liveness = liveness if liveness is not None else LivenessFile()

    async def run(self, job: GenerationJob) -> None:
        heartbeat = asyncio.create_task(self._heartbeat_forever(job.id, job.attempts))
        try:
            await self._execute(job)
        finally:
            heartbeat.cancel()

    async def _heartbeat_forever(self, job_id: str, claim_token: int) -> None:
        while True:
            await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)
            try:
                alive = await self._queue.heartbeat(job_id, self._worker_id, claim_token)
                # Same tick, same evidence: the container is healthy exactly
                # when the worker is still talking to the queue.
                self._liveness.touch()
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
        # fail_job refunds a paid job in the failing transaction, once; when our
        # claim is already gone it changes nothing and the holder settles the job.
        runner = self._executor_for(job.job_type)
        if runner is None:
            await self._queue.fail(
                job.id,
                self._worker_id,
                job.attempts,
                step="dispatch",
                message=f"job_type {job.job_type.value} has no worker executor yet",
            )
            return
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
                job.id, self._worker_id, job.attempts, step=str(step), message=message
            )
            if not failed_by_us:
                logger.warning(
                    "worker_fail_row_not_ours %s",
                    json.dumps({"job_id": job.id, "step": str(step)}),
                )

    def _executor_for(self, job_type: JobType) -> Callable[[GenerationJob], Awaitable[None]] | None:
        """The coroutine that runs this job type, or None when unsupported."""

        if job_type is JobType.PRESENTATION_GENERATION:
            return self._run_presentation
        if job_type is JobType.PRESENTATION_EDIT:
            return self._run_presentation_edit
        if job_type is JobType.PRESENTATION_RENDER:
            return self._run_presentation_render
        if job_type is JobType.SOURCE_PROCESSING:
            return self._run_source_processing
        return None

    async def _run_source_processing(self, job: GenerationJob) -> None:
        """Extract durable page evidence without creating a bot or calling a model."""

        from packages.workers.source.ingest import ingest_sources

        await ingest_sources(job, self._worker_id, self._db, self._queue, self._storage)

    def _orchestrator(self, bot: Bot) -> PresentationOrchestrator:
        from packages.bot.orchestrators.presentation_orchestrator import (
            PresentationOrchestrator,
        )

        return PresentationOrchestrator(
            bot=bot,
            db=self._db,
            credits=self._credits,
            storage=self._storage,
        )

    def _progress(self, job: GenerationJob) -> Callable[[str, int, int], Awaitable[None]]:
        async def progress(step: str, current: int, total: int) -> None:
            await self._queue.set_progress(
                job.id,
                self._worker_id,
                job.attempts,
                {"step": step, "current": current, "total": total},
            )

        return progress

    async def _finish_completed(self, job: GenerationJob, outcome: dict[str, Any]) -> None:
        """Land the guarded completion of a job that committed nothing, with its outcome."""

        completed_by_us = await self._queue.complete(
            job.id, self._worker_id, job.attempts, {"step": "done", **outcome}
        )
        if not completed_by_us:
            logger.warning(
                "worker_complete_suppressed_row_not_ours %s", json.dumps({"job_id": job.id})
            )
            return
        logger.info(
            "worker_job_completed %s",
            json.dumps({"job_id": job.id, "project_id": job.project_id, **outcome}),
        )

    async def _run_presentation_render(self, job: GenerationJob) -> None:
        """Render one immutable revision and publish every requested format, or fail."""

        from aiogram import Bot

        from packages.bot.orchestrators.deck_revisions import render_and_publish, render_formats
        from packages.core.models.presentation import DeckSpec

        payload = job.payload
        revision_id = payload.get("revision_id")
        names = payload.get("formats")
        if not isinstance(revision_id, str) or not isinstance(names, list) or not names:
            raise RuntimeError("presentation_render job is missing its revision or formats")
        version = renderer_version()
        if payload.get("renderer_version") != version:
            # register_export binds exports to the payload's renderer; a worker
            # running other renderer code must not publish under that name.
            raise RuntimeError(
                f"presentation_render was requested for renderer {payload.get('renderer_version')}"
                f" but this worker is {version}"
            )
        store = DocumentStore(self._db)
        found = await store.revision_in_project(job.project_id, revision_id)
        if found is None:
            raise RuntimeError("presentation_render revision is not in this project")
        revision = found[1]
        publisher = ExportPublisher(store, self._storage)
        requested = sorted({str(name) for name in cast(list[Any], names)})
        # A retry or recovery render publishes only what is not registered yet;
        # the formats an earlier attempt registered are immutable and reused.
        already = await publisher.registered_formats(revision_id, version)
        missing = [name for name in requested if name not in {f.value for f in already}]
        if missing:
            deck = DeckSpec.model_validate(revision.content)
            bot = Bot(token=self._config.telegram_bot_token)
            try:
                await render_and_publish(
                    orchestrator=self._orchestrator(bot),
                    publisher=publisher,
                    job_id=job.id,
                    worker_id=self._worker_id,
                    claim_token=job.attempts,
                    document_id=revision.document_id,
                    revision_id=revision_id,
                    deck=deck,
                    formats=render_formats(missing),
                    progress=self._progress(job),
                )
            finally:
                await bot.session.close()
        await self._finish_completed(
            job,
            {
                "outcome": "rendered",
                "revision_id": revision_id,
                "renderer_version": version,
                "formats": requested,
                "rendered_formats": missing,
            },
        )

    async def _run_presentation_edit(self, job: GenerationJob) -> None:
        """Apply a parked fix batch against its base revision; commit or propose with the job.

        No charge and no refund: an edit spends the tier's fix allowance, not
        money. The API stamped ``base_revision_id`` (the revision the brain saw);
        if the deck moved since, the edit is stored as a proposal instead of
        overwriting newer work (ADR 0001).
        """

        from aiogram import Bot

        from packages.core.models.presentation import DeckSpec, SlideFix
        from packages.sessions_core import FixStatus, dispatch_fix, park_pending_for_apply

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
            # ALL-OR-NOTHING: skipping a malformed entry would apply part of an
            # approved batch and report success. A malformed payload is a bug.
            fixes: list[SlideFix] = []
            for entry in cast(list[Any], raw_fixes):
                if not isinstance(entry, dict):
                    raise RuntimeError("presentation_edit job carries a malformed fix entry")
                fixes.append(SlideFix.model_validate(cast(dict[str, Any], entry)))

        document_id = payload.get("document_id")
        base_revision_id = payload.get("base_revision_id")
        if not isinstance(document_id, str) or not isinstance(base_revision_id, str):
            raise RuntimeError("presentation_edit carries no document revision to edit")

        store = DocumentStore(self._db)
        bot = Bot(token=self._config.telegram_bot_token)
        orchestrator = self._orchestrator(bot)
        progress = self._progress(job)

        async def commit(deck: DeckSpec, base: str | None) -> CommitOutcome:
            # Commit and job completion are one fenced transaction; the render of
            # the committed revision is queued with it (ADR §6.3).
            return await store.finish_generation_job(
                job_id=job.id,
                worker_id=self._worker_id,
                claim_token=job.attempts,
                base_revision_id=base,
                content=deck.model_dump(mode="json"),
                kind=RevisionKind.AI_EDIT,
                idempotency_key=f"chat-edit:{job.id}",
                renderer_version=renderer_version(),
                render_formats=list(WEB_FILE_FORMATS),
            )

        async def deliver(
            deck: DeckSpec, revision_id: str, formats: list[ExportFormat]
        ) -> list[str]:
            # Rendering is the presentation_render job finish_generation_job queued.
            return []

        try:
            result = await dispatch_fix(
                runner=orchestrator,
                db=self._db,
                project_id=job.project_id,
                fixes=fixes,
                call_count=call_count,
                progress=progress,
                base_revision_id=base_revision_id,
                commit=commit,
                deliver=deliver,
            )
        finally:
            await bot.session.close()

        if result.status in (FixStatus.DELIVERED, FixStatus.PROPOSED, FixStatus.UNCHANGED):
            # finish_generation_job already completed the job with this outcome.
            logger.info(
                "worker_job_completed %s",
                json.dumps(
                    {
                        "job_id": job.id,
                        "outcome": result.status.value,
                        "revision_id": result.revision_id,
                        "proposal_id": result.proposal_id,
                        "slides_changed": result.slides_changed,
                    }
                ),
            )
            return
        # dispatch_fix already answered the parked call and persisted, so the
        # session is coherent; the job row just has to say what happened.
        failed_by_us = await self._queue.fail(
            job.id,
            self._worker_id,
            job.attempts,
            step="apply_fixes",
            message=result.reason or result.status.value,
        )
        if not failed_by_us:
            logger.warning("worker_edit_fail_row_not_ours %s", json.dumps({"job_id": job.id}))

    async def _run_presentation(self, job: GenerationJob) -> None:
        """Generate a deck, commit it as a revision (or proposal) with the job, open the session."""

        # Imported here so --help / unit tests never pull aiogram + the full
        # pipeline stack just to parse args.
        from aiogram import Bot

        from packages.bot.orchestrators.deck_revisions import file_formats, renderable

        payload = job.payload
        package = GenerationPackage(str(payload.get("package", "presentation_standard")))
        formats_raw = payload.get("formats")
        formats = [ExportFormat.HTML, ExportFormat.PPTX_EDITABLE]
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

        store = DocumentStore(self._db)
        head = await store.head(job.project_id, DocumentKind.PRESENTATION)
        base_revision_id = head.revision_id if head is not None else None
        bot = Bot(token=self._config.telegram_bot_token)
        orchestrator = self._orchestrator(bot)
        progress = self._progress(job)
        try:
            built = await orchestrator.build_deck(
                file_infos=file_infos,
                project_id=job.project_id,
                user_id=job.user_id,
                language=language,
                raw_answers=answers,
                progress=progress,
                package=package,
                topic=topic,
            )
            # One fenced transaction: the deck becomes a revision (or a proposal
            # when the head moved), the job completes, and the render of the
            # committed revision is queued. A lapsed claim writes none of it.
            outcome = await store.finish_generation_job(
                job_id=job.id,
                worker_id=self._worker_id,
                claim_token=job.attempts,
                base_revision_id=base_revision_id,
                content=built.deck.model_dump(mode="json"),
                kind=RevisionKind.GENERATION
                if base_revision_id is None
                else RevisionKind.REGENERATION,
                idempotency_key=f"job:{job.id}:deck",
                renderer_version=renderer_version(),
                render_formats=file_formats(formats),
            )
            revision_id = renderable(outcome)
        finally:
            await bot.session.close()

        if revision_id is not None:
            # The editing session starts on the revision just committed. Best-effort:
            # the deck is committed and its render queued; a failed session write
            # only means chat editing is unavailable until the next delivery.
            try:
                from packages.bot.sessions.store import create_session

                await create_session(
                    self._db,
                    project_id=job.project_id,
                    sources=built.sources,
                    package=package,
                    formats=formats,
                    revision_id=revision_id,
                    deck=built.deck,
                )
            except Exception as exc:
                logger.warning(
                    "worker_session_persist_failed %s",
                    json.dumps({"job_id": job.id, "error_type": type(exc).__name__}),
                )

        # finish_generation_job completed the job in the commit's transaction.
        logger.info(
            "worker_job_completed %s",
            json.dumps(
                {
                    "job_id": job.id,
                    "project_id": job.project_id,
                    "outcome": outcome.status.value,
                    "revision_id": revision_id,
                    "proposal_id": outcome.proposal_id,
                }
            ),
        )


async def _reap(queue: JobQueue, stale_seconds: int) -> None:
    try:
        failed = await queue.reap_stale(stale_seconds)
    except Exception as exc:
        logger.warning("worker_reap_error %s", json.dumps({"error_type": type(exc).__name__}))
        return
    for job in failed:
        # Failed and, when paid, refunded by reap_stale_jobs itself.
        logger.warning(
            "worker_job_reaped %s",
            json.dumps({"job_id": job.id, "error_message": job.error_message}),
        )


async def _amain(args: argparse.Namespace) -> int:
    config = PlatformConfig.from_env()
    db = DatabaseClient(config)
    queue = JobQueue(db)
    credits = CreditLedger(db, dev_mode=config.dev_mode)
    storage = FileStorage(config)
    worker_id = _worker_id()
    liveness = LivenessFile()
    runner = JobRunner(config, db, queue, credits, storage, worker_id, liveness)
    logger.info(
        "worker_started %s",
        json.dumps(
            {"worker_id": worker_id, "loop": args.loop, "liveness_file": str(liveness.path)}
        ),
    )
    # Mark alive at startup so the container is not reported dead for one whole
    # poll interval every time it restarts.
    liveness.touch()

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
        await _reap(queue, args.stale_seconds)
        # Touched per cycle, BEFORE the claim: the file then proves the loop is
        # turning even when the queue is empty, which is the worker's normal
        # state. Touching only on a claimed job would report an idle worker as
        # dead.
        liveness.touch()
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
