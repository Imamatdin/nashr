"""Queue adapter for persistent evidence; independent of Telegram and model clients."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from packages.core.constants import MAX_FILE_SIZE_BYTES, MAX_FILES_PER_PROJECT
from packages.platform.database import DatabaseClient
from packages.platform.jobs import GenerationJob, JobQueue
from packages.platform.storage import FileStorage
from packages.workers.source.evidence import extract_passages


class SourceProcessingPayload(BaseModel):
    """Only IDs of registered uploads cross the enqueue boundary."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    source_ids: list[UUID] = Field(min_length=1, max_length=MAX_FILES_PER_PROJECT)


async def ingest_sources(
    job: GenerationJob,
    worker_id: str,
    db: DatabaseClient,
    queue: JobQueue,
    storage: FileStorage,
) -> None:
    """Commit each source atomically; retry skips already-published sources."""

    payload = SourceProcessingPayload.model_validate(job.payload)
    project = await db.get_project(job.project_id)
    if not project or str(project["user_id"]) != job.user_id:
        raise ValueError("source_project_not_owned")
    sources = {str(row["id"]): row for row in await db.get_project_sources(job.project_id)}
    failures: list[str] = []
    for index, source_id in enumerate(payload.source_ids):
        source = sources.get(str(source_id))
        if source is None:
            raise ValueError("source_not_found")
        if source.get("evidence_processed_at"):
            continue
        if not await queue.heartbeat(job.id, worker_id):
            return
        await queue.set_progress(
            job.id,
            worker_id,
            {
                "stage": "source_processing",
                "source_id": str(source_id),
                "completed_sources": index,
                "total_sources": len(payload.source_ids),
            },
        )
        try:
            data = await storage.get_bytes_limited(str(source["storage_key"]), MAX_FILE_SIZE_BYTES)
            prepared = await extract_passages(data, str(source["filename"]))
        except (ValueError, TimeoutError):
            # Preserve progress for other valid files; never call a partial job complete.
            failures.append(str(source_id))
            continue
        committed = await db.commit_source_evidence(
            job.id,
            worker_id,
            str(source_id),
            [chunk.model_dump(mode="json") for chunk in prepared.chunks],
            prepared.content_hash,
            prepared.warnings,
        )
        if not committed:
            return
    await queue.set_progress(
        job.id,
        worker_id,
        {
            "stage": "failed" if failures else "complete",
            "completed_sources": len(payload.source_ids) - len(failures),
            "total_sources": len(payload.source_ids),
            "failed_sources": failures,
        },
    )
    if failures:
        raise ValueError("source_extraction_failed")
    await queue.complete(job.id, worker_id, {})
