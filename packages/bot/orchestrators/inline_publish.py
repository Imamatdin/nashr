"""Publish the bot's in-process renders under a job claim (ADR 0001).

The bot renders inside its own process so Telegram can deliver the files at
once. Its exports must still obey the same fence as the queue worker's:
registered only under a job claim the registering process holds, for the
revision that job targets. So the bot inserts a render job already claimed by
itself, heartbeats it, publishes, and lands the guarded completion.

A publishing failure never blocks Telegram delivery of the local files; it fails
the inline job, and the web shows "render needed" for that revision.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import tempfile
import uuid
from pathlib import Path

from packages.bot.orchestrators.deck_revisions import file_formats
from packages.bot.orchestrators.presentation_orchestrator import PresentationRenderResult
from packages.core.enums import ExportFormat
from packages.platform.database import DatabaseClient
from packages.platform.document_models import ExportFileFormat, bot_actor
from packages.platform.document_store import DocumentStore
from packages.platform.exports import ExportPublisher, file_format, renderer_version
from packages.platform.jobs import DuplicateActiveJobError, JobQueue, JobType, heartbeat_while
from packages.platform.storage import FileStorage

logger = logging.getLogger(__name__)


def bot_worker_id() -> str:
    """Claim identity of this bot process for inline jobs."""

    return f"bot:{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:6]}"


async def owner_bot_actor(db: DatabaseClient, user_id: str) -> str:
    """The ``bot:<telegram id>`` actor for ``user_id``; raises when they have no Telegram id."""

    user = await db.get_user_by_id(user_id)
    telegram_id = user.get("telegram_id") if user is not None else None
    if not isinstance(telegram_id, int):
        raise ValueError(f"user {user_id} has no Telegram identity")
    return bot_actor(telegram_id)


async def publish_inline(
    *,
    db: DatabaseClient,
    storage: FileStorage | None,
    project_id: str,
    user_id: str,
    document_id: str,
    revision_id: str,
    render: PresentationRenderResult,
    formats: list[ExportFormat],
) -> bool:
    """Register ``render`` as exports of ``revision_id``; True when every file is published."""

    if storage is None:
        logger.warning("inline_publish_skipped_no_storage project=%s", project_id)
        return False
    queue = JobQueue(db)
    worker_id = bot_worker_id()
    version = renderer_version()
    files = {file_format(ext): path for ext, path in render.by_extension().items()}
    try:
        job = await queue.start_inline(
            project_id=project_id,
            user_id=user_id,
            job_type=JobType.PRESENTATION_RENDER,
            payload={
                "document_id": document_id,
                "revision_id": revision_id,
                "renderer_version": version,
                "formats": file_formats(formats),
            },
            worker_id=worker_id,
        )
    except DuplicateActiveJobError as exc:
        # Another process is already rendering exactly this revision; it publishes.
        logger.info("inline_publish_deferred project=%s job=%s", project_id, exc.existing.id)
        return False
    try:
        async with heartbeat_while(queue, job.id, worker_id, job.attempts):
            await ExportPublisher(DocumentStore(db), storage).publish(
                job_id=job.id,
                worker_id=worker_id,
                document_id=document_id,
                revision_id=revision_id,
                files=files,
                version=version,
            )
    except Exception as exc:
        logger.warning(
            "inline_publish_failed %s",
            json.dumps({"job_id": job.id, "error_type": type(exc).__name__}),
        )
        await queue.fail(
            job.id, worker_id, job.attempts, step="publish", message=f"{type(exc).__name__}: {exc}"
        )
        return False
    return await queue.complete(job.id, worker_id, job.attempts, {"outcome": "rendered"})


async def fetch_exports(
    db: DatabaseClient, storage: FileStorage | None, revision_id: str
) -> dict[str, Path]:
    """Download the current renderer's exports of ``revision_id`` for Telegram delivery."""

    if storage is None:
        return {}
    version = renderer_version()
    records = [
        record
        for record in await DocumentStore(db).exports([revision_id])
        if record.renderer_version == version
    ]
    if not any(record.format is ExportFileFormat.HTML for record in records):
        return {}
    directory = Path(tempfile.mkdtemp(prefix="nashr_reload_"))
    files: dict[str, Path] = {}
    for record in records:
        target = directory / f"presentation.{record.format.value}"
        await storage.download(record.storage_key, target)
        files[record.format.value] = target
    return files


__all__ = ["bot_worker_id", "fetch_exports", "owner_bot_actor", "publish_inline"]
