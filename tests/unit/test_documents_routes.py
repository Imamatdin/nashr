"""Behavior tests for article document initialization, saves, and history."""

from __future__ import annotations

from datetime import UTC, datetime
from io import BytesIO
from typing import Any, cast
from uuid import UUID, uuid4

import httpx
import pytest
from docx import Document
from postgrest.exceptions import APIError

from packages.api.app import create_app
from packages.api.services.tokens import mint_app_jwt
from packages.platform.config import PlatformConfig

pytestmark = pytest.mark.asyncio

_SECRET = "test-jwt-secret"
_USER_ID = uuid4()
_PROJECT_ID = str(uuid4())
_DOCUMENT_ID = str(uuid4())
_REVISION_ID = str(uuid4())


def _content(title: str = "Learning") -> dict[str, Any]:
    return {"kind": "article", "schema_version": 1, "title": title, "blocks": []}


class _FakeDb:
    def __init__(self) -> None:
        self.owner = str(_USER_ID)
        self.project_type = "article"
        self.revision_id = _REVISION_ID
        self.content = _content()
        self.saved: list[dict[str, Any]] = []

    async def get_project(self, project_id: str) -> dict[str, Any] | None:
        if project_id != _PROJECT_ID:
            return None
        return {"id": project_id, "user_id": self.owner, "type": self.project_type}

    async def create_document_if_missing(
        self,
        project_id: str,
        kind: str,
        content: dict[str, Any],
        user_id: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        self.content = content
        return self._rpc_row()

    async def get_document(self, project_id: str, kind: str) -> dict[str, Any] | None:
        return {
            "id": _DOCUMENT_ID,
            "project_id": project_id,
            "kind": kind,
            "revision_id": self.revision_id,
            "content": self.content,
            "updated_at": datetime.now(UTC),
        }

    async def commit_document_revision(
        self,
        document_id: str,
        base_revision_id: str,
        content: dict[str, Any],
        user_id: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        if base_revision_id != self.revision_id:
            raise APIError(
                {"message": "stale_revision", "code": "P0001", "hint": None, "details": None}
            )
        self.saved.append(content)
        self.content = content
        self.revision_id = str(uuid4())
        return self._rpc_row()

    async def list_document_revisions(self, document_id: str) -> list[dict[str, Any]]:
        return [
            {
                "id": self.revision_id,
                "parent_revision_id": None,
                "created_by": str(_USER_ID),
                "content_hash": "a" * 64,
                "created_at": datetime.now(UTC),
            }
        ]

    async def get_document_revision(
        self,
        document_id: str,
        revision_id: str,
    ) -> dict[str, Any] | None:
        if revision_id == "00000000-0000-0000-0000-000000000001":
            return {"content": _content("Previous")}
        return None

    def _rpc_row(self) -> dict[str, Any]:
        return {
            "document_id": _DOCUMENT_ID,
            "revision_id": self.revision_id,
            "content": self.content,
            "updated_at": datetime.now(UTC),
        }


def _config() -> PlatformConfig:
    return PlatformConfig(
        supabase_url="https://example.supabase.co",
        supabase_service_key="service",
        telegram_bot_token="123:abc",
        supabase_jwt_secret=_SECRET,
    )


def _client() -> tuple[httpx.AsyncClient, _FakeDb]:
    db = _FakeDb()
    app = create_app(
        config=_config(),
        db=cast(Any, db),
        identity_service=cast(Any, object()),
        credits=cast(Any, object()),
        job_queue=cast(Any, object()),
        rate_limiter=cast(Any, object()),
        storage=cast(Any, object()),
    )
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test"), db


def _headers(user_id: UUID = _USER_ID) -> dict[str, str]:
    session = mint_app_jwt(_SECRET, user_id, 3600)
    return {"Authorization": f"Bearer {session.access_token}"}


async def test_initialize_article_creates_empty_revision() -> None:
    client, _db = _client()
    response = await client.post(
        f"/projects/{_PROJECT_ID}/documents/article",
        json={"title": "Learning", "idempotency_key": "init-1"},
        headers=_headers(),
    )
    assert response.status_code == 200
    assert response.json()["content"] == _content()


async def test_save_article_advances_revision() -> None:
    client, db = _client()
    body = {
        "base_revision_id": _REVISION_ID,
        "idempotency_key": "save-1",
        "content": _content("Changed"),
    }
    response = await client.put(
        f"/projects/{_PROJECT_ID}/documents/article", json=body, headers=_headers()
    )
    assert response.status_code == 200
    assert response.json()["revision_id"] != _REVISION_ID
    assert db.saved == [_content("Changed")]


async def test_stale_save_is_a_visible_conflict() -> None:
    client, _db = _client()
    response = await client.put(
        f"/projects/{_PROJECT_ID}/documents/article",
        json={
            "base_revision_id": str(uuid4()),
            "idempotency_key": "save-stale",
            "content": _content("Changed"),
        },
        headers=_headers(),
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "stale_revision"


async def test_other_user_cannot_read_document() -> None:
    client, _db = _client()
    response = await client.get(
        f"/projects/{_PROJECT_ID}/documents/article", headers=_headers(uuid4())
    )
    assert response.status_code == 404


async def test_presentation_project_cannot_open_article_editor() -> None:
    client, db = _client()
    db.project_type = "presentation"
    response = await client.get(f"/projects/{_PROJECT_ID}/documents/article", headers=_headers())
    assert response.status_code == 409
    assert response.json()["detail"] == "not_article_project"


async def test_restore_commits_historical_content_as_new_head() -> None:
    client, db = _client()
    response = await client.post(
        f"/projects/{_PROJECT_ID}/documents/article/restore",
        json={
            "revision_id": "00000000-0000-0000-0000-000000000001",
            "base_revision_id": _REVISION_ID,
            "idempotency_key": "restore-1",
        },
        headers=_headers(),
    )
    assert response.status_code == 200
    assert response.json()["content"]["title"] == "Previous"
    assert db.saved == [_content("Previous")]


async def test_export_article_returns_current_revision_as_docx() -> None:
    client, db = _client()
    db.content = {
        **_content("Evidence based teaching"),
        "blocks": [
            {
                "id": str(uuid4()),
                "type": "heading",
                "text": "Methods",
                "level": 2,
                "citations": [],
            },
            {
                "id": str(uuid4()),
                "type": "paragraph",
                "text": "Students compared two approaches.",
                "level": None,
                "citations": [],
            },
        ],
    }
    response = await client.get(
        f"/projects/{_PROJECT_ID}/documents/article/export.docx", headers=_headers()
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert "attachment" in response.headers["content-disposition"]
    rendered = Document(BytesIO(response.content))
    assert [paragraph.text for paragraph in rendered.paragraphs] == [
        "Evidence based teaching",
        "Methods",
        "Students compared two approaches.",
    ]
