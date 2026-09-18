"""Behavior tests for versioned direct presentation design routes."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

import httpx
import pytest
from postgrest.exceptions import APIError

from packages.api.app import create_app
from packages.api.services.tokens import mint_app_jwt
from packages.core.enums import (
    AudienceType,
    BackgroundTreatment,
    PresentationMood,
    SlideType,
)
from packages.core.models.presentation import (
    ColorPalette,
    DeckSpec,
    DesignDirectionSpec,
    PresentationInterviewAnswers,
    SlideContent,
    SlideSpec,
)
from packages.platform.config import PlatformConfig
from packages.platform.jobs import GenerationJob, JobStatus, JobType
from packages.platform.rate_limit import RateDecision

pytestmark = pytest.mark.asyncio

_SECRET = "test-jwt-secret"
_USER_ID = uuid4()
_PROJECT_ID = str(uuid4())
_DOCUMENT_ID = str(uuid4())
_REVISION_ID = str(uuid4())


def _deck() -> DeckSpec:
    return DeckSpec(
        project_id=_PROJECT_ID,
        title="Learning",
        design=DesignDirectionSpec(
            mood=PresentationMood.WARM_HISTORICAL,
            palette=ColorPalette(
                background="#FFFCF0",
                surface="#F2F0E5",
                text="#100F0F",
                accent="#205EA6",
                text_secondary="#575653",
            ),
            heading_font="Source Serif 4",
            body_font="Inter",
            image_style_prefix="editorial classroom photograph, ",
            background_treatment=BackgroundTreatment.LIGHT,
        ),
        interview=PresentationInterviewAnswers(audience=AudienceType.UNDERGRADUATE),
        slides=[
            SlideSpec(
                slide_index=0,
                slide_type=SlideType.TITLE_HERO,
                content=SlideContent(title="Learning"),
            )
        ],
    )


class _FakeDb:
    def __init__(self) -> None:
        self.owner = str(_USER_ID)
        self.document: dict[str, Any] | None = None
        self.deck = _deck()
        self.revisions: dict[str, dict[str, Any]] = {}

    async def get_project(self, project_id: str) -> dict[str, Any] | None:
        return {"id": project_id, "user_id": self.owner, "type": "presentation"}

    async def get_deck(self, project_id: str) -> dict[str, Any] | None:
        return {"id": "deck-1", "deck_json": self.deck.model_dump(mode="json")}

    async def get_document(self, project_id: str, kind: str) -> dict[str, Any] | None:
        return self.document

    async def create_document_if_missing(
        self,
        project_id: str,
        kind: str,
        content: dict[str, Any],
        user_id: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        created_at = datetime.now(UTC)
        self.document = {
            "id": _DOCUMENT_ID,
            "document_id": _DOCUMENT_ID,
            "revision_id": _REVISION_ID,
            "content": content,
            "updated_at": created_at,
        }
        self.revisions[_REVISION_ID] = {
            "id": _REVISION_ID,
            "document_id": _DOCUMENT_ID,
            "parent_revision_id": None,
            "created_by": user_id,
            "content_hash": "a" * 64,
            "created_at": created_at,
            "content": content,
        }
        return self.document

    async def commit_document_revision(
        self,
        document_id: str,
        base_revision_id: str,
        content: dict[str, Any],
        user_id: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        assert self.document is not None
        if base_revision_id != self.document["revision_id"]:
            raise APIError(
                {"message": "stale_revision", "code": "P0001", "hint": None, "details": None}
            )
        revision_id = str(uuid4())
        created_at = datetime.now(UTC)
        self.revisions[revision_id] = {
            "id": revision_id,
            "document_id": document_id,
            "parent_revision_id": base_revision_id,
            "created_by": user_id,
            "content_hash": "b" * 64,
            "created_at": created_at,
            "content": content,
        }
        self.document = {
            **self.document,
            "revision_id": revision_id,
            "content": content,
            "updated_at": created_at,
        }
        return self.document

    async def list_document_revisions(
        self, document_id: str, limit: int = 50
    ) -> list[dict[str, Any]]:
        rows = sorted(self.revisions.values(), key=lambda row: row["created_at"], reverse=True)[
            :limit
        ]
        return [
            {
                key: row[key]
                for key in (
                    "id",
                    "parent_revision_id",
                    "created_by",
                    "content_hash",
                    "created_at",
                )
            }
            for row in rows
            if row["document_id"] == document_id
        ]

    async def get_document_revision(
        self, document_id: str, revision_id: str
    ) -> dict[str, Any] | None:
        row = self.revisions.get(revision_id)
        return row if row and row["document_id"] == document_id else None


class _FakeLimiter:
    async def check(self, *, action: str, user_id: str, ip: str) -> RateDecision:
        return RateDecision(
            allowed=True,
            scope="user",
            action=action,
            count=1,
            limit=120,
            resets_at=datetime.now(UTC) + timedelta(days=1),
        )


class _FakeQueue:
    def __init__(self) -> None:
        self.enqueued: list[dict[str, Any]] = []
        self.active: GenerationJob | None = None

    async def get_active_job(self, project_id: str, job_type: JobType) -> GenerationJob | None:
        if self.active is not None and self.active.job_type is job_type:
            return self.active
        return None

    async def enqueue(self, **kwargs: Any) -> GenerationJob:
        self.enqueued.append(kwargs)
        return GenerationJob(
            id="render-1",
            project_id=kwargs["project_id"],
            user_id=kwargs["user_id"],
            job_type=kwargs["job_type"],
            status=JobStatus.QUEUED,
            payload=kwargs["payload"],
        )


def _config() -> PlatformConfig:
    return PlatformConfig(
        supabase_url="https://example.supabase.co",
        supabase_service_key="service",
        telegram_bot_token="123:abc",
        supabase_jwt_secret=_SECRET,
    )


def _client() -> tuple[httpx.AsyncClient, _FakeDb, _FakeQueue]:
    db = _FakeDb()
    queue = _FakeQueue()
    app = create_app(
        config=_config(),
        db=cast(Any, db),
        identity_service=cast(Any, object()),
        credits=cast(Any, object()),
        job_queue=cast(Any, queue),
        rate_limiter=cast(Any, _FakeLimiter()),
        storage=cast(Any, object()),
    )
    return (
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test"),
        db,
        queue,
    )


def _headers(user_id: UUID = _USER_ID) -> dict[str, str]:
    session = mint_app_jwt(_SECRET, user_id, 3600)
    return {"Authorization": f"Bearer {session.access_token}"}


async def test_get_design_imports_current_deck_once() -> None:
    client, db, _queue = _client()
    response = await client.get(f"/projects/{_PROJECT_ID}/design", headers=_headers())
    assert response.status_code == 200
    assert response.json()["content"]["slides"][0]["content"]["title"] == "Learning"
    assert db.document is not None


async def test_save_design_creates_a_new_revision() -> None:
    client, _db, _queue = _client()
    opened = await client.get(f"/projects/{_PROJECT_ID}/design", headers=_headers())
    body = opened.json()
    body["content"]["slides"][0]["content"]["title"] = "Edited directly"
    saved = await client.put(
        f"/projects/{_PROJECT_ID}/design",
        json={
            "base_revision_id": body["revision_id"],
            "idempotency_key": "save-1",
            "content": body["content"],
        },
        headers=_headers(),
    )
    assert saved.status_code == 200
    assert saved.json()["revision_id"] != body["revision_id"]
    assert saved.json()["content"]["slides"][0]["content"]["title"] == "Edited directly"


async def test_render_queues_exact_current_revision_without_credit_charge() -> None:
    client, _db, queue = _client()
    opened = (await client.get(f"/projects/{_PROJECT_ID}/design", headers=_headers())).json()
    response = await client.post(
        f"/projects/{_PROJECT_ID}/design/render",
        json={"revision_id": opened["revision_id"]},
        headers=_headers(),
    )
    assert response.status_code == 200
    assert response.json() == {"job_id": "render-1", "status": "queued", "existing": False}
    assert queue.enqueued[0]["job_type"] is JobType.PRESENTATION_RENDER
    assert queue.enqueued[0]["payload"]["revision_id"] == opened["revision_id"]


async def test_design_history_lists_revisions_and_restore_creates_new_head() -> None:
    client, _db, _queue = _client()
    opened = (await client.get(f"/projects/{_PROJECT_ID}/design", headers=_headers())).json()
    original_revision = opened["revision_id"]
    opened["content"]["slides"][0]["content"]["title"] = "Second version"
    saved = (
        await client.put(
            f"/projects/{_PROJECT_ID}/design",
            json={
                "base_revision_id": original_revision,
                "idempotency_key": "save-history",
                "content": opened["content"],
            },
            headers=_headers(),
        )
    ).json()

    history = await client.get(f"/projects/{_PROJECT_ID}/design/revisions", headers=_headers())
    assert history.status_code == 200
    assert len(history.json()["revisions"]) == 2

    restored = await client.post(
        f"/projects/{_PROJECT_ID}/design/restore",
        json={
            "revision_id": original_revision,
            "base_revision_id": saved["revision_id"],
            "idempotency_key": "restore-original",
        },
        headers=_headers(),
    )
    assert restored.status_code == 200
    assert restored.json()["revision_id"] not in {
        original_revision,
        saved["revision_id"],
    }
    assert restored.json()["content"]["slides"][0]["content"]["title"] == "Learning"


async def test_restore_rejects_revision_from_another_document() -> None:
    client, _db, _queue = _client()
    opened = (await client.get(f"/projects/{_PROJECT_ID}/design", headers=_headers())).json()
    response = await client.post(
        f"/projects/{_PROJECT_ID}/design/restore",
        json={
            "revision_id": str(uuid4()),
            "base_revision_id": opened["revision_id"],
            "idempotency_key": "restore-missing",
        },
        headers=_headers(),
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "revision_not_found"


async def test_manual_save_is_rejected_while_ai_edit_owns_the_deck() -> None:
    client, _db, queue = _client()
    opened = (await client.get(f"/projects/{_PROJECT_ID}/design", headers=_headers())).json()
    queue.active = GenerationJob(
        id="edit-1",
        project_id=_PROJECT_ID,
        user_id=str(_USER_ID),
        job_type=JobType.PRESENTATION_EDIT,
        status=JobStatus.PROCESSING,
        payload={},
    )
    response = await client.put(
        f"/projects/{_PROJECT_ID}/design",
        json={
            "base_revision_id": opened["revision_id"],
            "idempotency_key": "save-while-busy",
            "content": opened["content"],
        },
        headers=_headers(),
    )
    assert response.status_code == 409
    assert response.json()["detail"]["reason"] == "design_busy"


async def test_other_user_cannot_open_design() -> None:
    client, _db, _queue = _client()
    response = await client.get(f"/projects/{_PROJECT_ID}/design", headers=_headers(uuid4()))
    assert response.status_code == 404
