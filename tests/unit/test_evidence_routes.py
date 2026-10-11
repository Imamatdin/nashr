"""The source library is owned, bounded, and backed by durable queued work."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import uuid4

import httpx
import pytest

from packages.api.app import create_app
from packages.api.services.tokens import mint_app_jwt
from packages.platform.config import PlatformConfig
from packages.platform.jobs import DuplicateActiveJobError, GenerationJob, JobType
from packages.platform.rate_limit import RateDecision

pytestmark = pytest.mark.asyncio
USER, PROJECT, SOURCE, PASSAGE = (str(uuid4()) for _ in range(4))


class FakeDatabase:
    """External database seam; assertions inspect mutations and ownership."""

    def __init__(self) -> None:
        self.sources = [{"id": SOURCE, "filename": "study.txt", "evidence_processed_at": None}]
        self.reads = 0

    async def get_project(self, project_id: str) -> dict[str, str]:
        return {"id": project_id, "user_id": USER, "type": "article"}

    async def get_project_sources(self, project_id: str) -> list[dict[str, Any]]:
        self.reads += 1
        return self.sources

    async def get_source_passages(
        self, project_id: str, source_id: str | None, offset: int, limit: int
    ) -> list[dict[str, Any]]:
        self.reads += 1
        return [
            {
                "id": PASSAGE,
                "source_id": SOURCE,
                "project_id": PROJECT,
                "chunk_index": 0,
                "text": "An exact passage.",
                "page": 2,
                "is_ocr": False,
                "confidence": 100,
                "created_at": datetime.now(UTC),
            }
        ]


class FakeQueue:
    """External queue seam with a controllable concurrent enqueue result."""

    def __init__(self) -> None:
        self.active: GenerationJob | None = None
        self.enqueued: list[dict[str, Any]] = []
        self.race = False

    async def get_active_job(self, project_id: str, job_type: JobType) -> GenerationJob | None:
        return self.active

    async def get_latest_job(self, project_id: str, job_type: JobType) -> GenerationJob | None:
        return self.active

    async def enqueue(self, **kwargs: Any) -> GenerationJob:
        self.enqueued.append(kwargs)
        job = GenerationJob(id=str(uuid4()), status="queued", **kwargs)
        if self.race:
            raise DuplicateActiveJobError(job)
        self.active = job
        return job


class FakeLimiter:
    async def check(self, **kwargs: Any) -> RateDecision:
        return RateDecision(
            allowed=True,
            action="source_processing",
            scope="user",
            count=1,
            limit=60,
            resets_at=datetime.now(UTC) + timedelta(hours=1),
        )


def client() -> tuple[httpx.AsyncClient, FakeDatabase, FakeQueue, dict[str, str]]:
    db, queue = FakeDatabase(), FakeQueue()
    config = PlatformConfig(
        supabase_url="https://example.supabase.co",
        supabase_service_key="s",
        telegram_bot_token="123:abc",
        supabase_jwt_secret="secret",
    )
    app = create_app(
        config=config,
        db=cast(Any, db),
        job_queue=cast(Any, queue),
        identity_service=cast(Any, object()),
        credits=cast(Any, object()),
        rate_limiter=cast(Any, FakeLimiter()),
        storage=cast(Any, object()),
    )
    from uuid import UUID

    token = mint_app_jwt("secret", UUID(USER), 3600).access_token
    return (
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test"),
        db,
        queue,
        {"Authorization": f"Bearer {token}"},
    )


async def test_processing_snapshots_registered_source_ids_and_never_charges() -> None:
    http, _, queue, headers = client()
    response = await http.post(f"/projects/{PROJECT}/evidence/process", headers=headers)
    assert response.status_code == 200
    assert queue.enqueued[0]["payload"] == {"source_ids": [SOURCE]}
    assert queue.enqueued[0]["job_type"] == JobType.SOURCE_PROCESSING


async def test_ready_sources_are_not_reprocessed_and_no_uploads_is_actionable() -> None:
    http, db, queue, headers = client()
    db.sources = []
    response = await http.post(f"/projects/{PROJECT}/evidence/process", headers=headers)
    assert response.status_code == 409
    assert response.json()["detail"] == "no_sources_to_process"
    db.sources = [{"id": SOURCE, "filename": "ready.txt", "evidence_processed_at": "now"}]
    response = await http.post(f"/projects/{PROJECT}/evidence/process", headers=headers)
    assert response.status_code == 409
    assert not queue.enqueued


async def test_concurrent_enqueue_returns_the_winner() -> None:
    http, _, queue, headers = client()
    queue.race = True
    response = await http.post(f"/projects/{PROJECT}/evidence/process", headers=headers)
    assert response.status_code == 200
    assert response.json()["existing"]


async def test_library_returns_page_evidence_without_verification_claims() -> None:
    http, _, _, headers = client()
    response = await http.get(f"/projects/{PROJECT}/evidence", headers=headers)
    assert response.status_code == 200
    assert response.json()["passages"][0]["page"] == 2
    assert "verified" not in response.json()["passages"][0]


async def test_foreign_owner_cannot_read_or_start_processing() -> None:
    from uuid import UUID

    http, db, queue, _ = client()
    token = mint_app_jwt("secret", UUID(str(uuid4())), 3600).access_token
    headers = {"Authorization": f"Bearer {token}"}
    for method, suffix in (("GET", ""), ("POST", "/process")):
        response = await http.request(
            method, f"/projects/{PROJECT}/evidence{suffix}", headers=headers
        )
        assert response.status_code == 404
    assert not db.reads and not queue.enqueued


async def test_pagination_rejects_negative_offsets() -> None:
    http, _, _, headers = client()
    response = await http.get(f"/projects/{PROJECT}/evidence?offset=-1", headers=headers)
    assert response.status_code == 422
