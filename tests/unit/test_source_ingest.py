"""Exercise the real queue executor, parsers and local storage together."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import pytest

from packages.platform.config import PlatformConfig
from packages.platform.jobs import GenerationJob
from packages.platform.storage import FileStorage
from scripts.worker_run_job import JobRunner

pytestmark = pytest.mark.asyncio
USER, PROJECT, SOURCE = (str(uuid4()) for _ in range(3))


class Database:
    """External Supabase boundary; committed data is observable."""

    def __init__(self) -> None:
        self.owner = USER
        self.ready = False
        self.commit_lands = True
        self.committed: list[tuple[object, ...]] = []
        self.extra_sources: list[dict[str, object]] = []

    async def get_project(self, project_id: str) -> dict[str, str]:
        return {"user_id": self.owner}

    async def get_project_sources(self, project_id: str) -> list[dict[str, object]]:
        return [
            {
                "id": SOURCE,
                "filename": "source.txt",
                "storage_key": "source.txt",
                "evidence_processed_at": "already" if self.ready else None,
            },
            *self.extra_sources,
        ]

    async def commit_source_evidence(self, *args: object) -> bool:
        self.committed.append(args)
        return self.commit_lands


class Queue:
    """External durable job transitions, with a worker-loss failure seam."""

    def __init__(self) -> None:
        self.alive = True
        self.completed: list[str] = []
        self.failed: list[str] = []
        self.tokens: list[int] = []

    async def heartbeat(self, job_id: str, worker_id: str, claim_token: int) -> bool:
        self.tokens.append(claim_token)
        return self.alive

    async def set_progress(
        self, job_id: str, worker_id: str, claim_token: int, progress: dict[str, object]
    ) -> None:
        self.tokens.append(claim_token)
        self.progress = progress

    async def complete(
        self, job_id: str, worker_id: str, claim_token: int, progress: dict[str, object]
    ) -> bool:
        self.tokens.append(claim_token)
        self.completed.append(job_id)
        return True

    async def fail(
        self, job_id: str, worker_id: str, claim_token: int, *, step: str, message: str
    ) -> bool:
        self.tokens.append(claim_token)
        self.failed.append(message)
        return True


async def setup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    data: bytes = b"Education research evidence. " * 20,
) -> tuple[JobRunner, GenerationJob, Database, Queue]:
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    config = PlatformConfig(
        supabase_url="https://example.supabase.co",
        supabase_service_key="s",
        telegram_bot_token="123:abc",
    )
    storage = FileStorage(config)
    upload = tmp_path / "source.txt"
    upload.write_bytes(data)
    await storage.upload(upload, "source.txt")
    db, queue = Database(), Queue()
    runner = JobRunner(
        config, cast(Any, db), cast(Any, queue), cast(Any, object()), storage, "worker"
    )
    job = GenerationJob(
        id=str(uuid4()),
        project_id=PROJECT,
        user_id=USER,
        job_type="source_processing",
        status="processing",
        payload={"source_ids": [SOURCE]},
        attempts=3,
    )
    return runner, job, db, queue


async def test_source_job_persists_exact_text_and_completes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner, job, db, queue = await setup(tmp_path, monkeypatch)
    await runner.run(job)
    assert queue.completed == [job.id]
    assert not queue.failed
    # Every queue call is made under this claim (attempt 3), never a stale one.
    assert queue.tokens and set(queue.tokens) == {3}
    chunks = cast(list[dict[str, Any]], db.committed[0][3])
    assert chunks[0]["text"].startswith("Education research evidence.")
    assert chunks[0]["page"] is None  # plain text has no page locations


async def test_retry_preserves_existing_passage_ids(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner, job, db, queue = await setup(tmp_path, monkeypatch)
    db.ready = True
    await runner.run(job)
    assert queue.completed == [job.id]
    assert not db.committed


@pytest.mark.parametrize("lost_at_commit", [False, True])
async def test_lost_worker_never_announces_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, lost_at_commit: bool
) -> None:
    runner, job, db, queue = await setup(tmp_path, monkeypatch)
    queue.alive = lost_at_commit
    db.commit_lands = False
    await runner.run(job)
    assert not queue.completed and not queue.failed
    assert len(db.committed) == int(lost_at_commit)


async def test_invalid_upload_fails_without_billing_or_partial_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner, job, db, queue = await setup(tmp_path, monkeypatch, b"")
    await runner.run(job)
    assert not queue.completed and not db.committed
    assert "source_extraction_failed" in queue.failed[0]


async def test_bad_source_does_not_block_valid_sources_after_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner, job, db, queue = await setup(tmp_path, monkeypatch, b"")
    other = str(uuid4())
    stored = tmp_path / ".nashr" / "storage" / "good.txt"
    stored.write_text("Actual valid research evidence. " * 10)
    db.extra_sources = [{"id": other, "filename": "good.txt", "storage_key": "good.txt"}]
    job.payload["source_ids"] = [SOURCE, other]
    await runner.run(job)
    assert db.committed[0][2] == other
    assert queue.failed and not queue.completed
    assert queue.progress["failed_sources"] == [SOURCE]
    assert queue.progress["completed_sources"] == 1


async def test_worker_rechecks_owner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runner, job, db, queue = await setup(tmp_path, monkeypatch)
    db.owner = str(uuid4())
    await runner.run(job)
    assert "source_project_not_owned" in queue.failed[0]
    assert not db.committed
