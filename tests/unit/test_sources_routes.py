"""Behaviour tests for the P3 source upload routes (packages/api/routes/sources.py).

Presign gate order (rate limit → ownership → allowlist) and register-time
enforcement (key prefix ownership, per-project cap, duplicate, REAL object
size) are the contract; fakes record calls so tests assert what was and was
not reached.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

import httpx
import pytest

from packages.api.app import create_app
from packages.api.services.tokens import mint_app_jwt
from packages.core.constants import MAX_FILE_SIZE_BYTES, MAX_FILES_PER_PROJECT
from packages.platform.config import PlatformConfig
from packages.platform.rate_limit import RateDecision

pytestmark = pytest.mark.asyncio

_SECRET = "test-jwt-secret"
_USER_ID = uuid4()
_PROJECT_ID = str(uuid4())


def _config() -> PlatformConfig:
    return PlatformConfig(
        supabase_url="https://example.supabase.co",
        supabase_service_key="service",
        telegram_bot_token="123:abc",
        supabase_jwt_secret=_SECRET,
    )


class _FakeDb:
    def __init__(self) -> None:
        self.project_owner: str = str(_USER_ID)
        self.sources: list[dict[str, Any]] = []
        self.created: list[dict[str, Any]] = []

    async def get_project(self, project_id: str) -> dict[str, Any] | None:
        return {"id": project_id, "user_id": self.project_owner}

    async def get_project_sources(self, project_id: str) -> list[dict[str, Any]]:
        return self.sources

    async def create_source(self, **kwargs: Any) -> dict[str, Any]:
        row = {"id": str(uuid4()), **kwargs}
        self.created.append(row)
        return row


class _FakeStorage:
    def __init__(self) -> None:
        self.object_sizes: dict[str, int] = {}
        self.presigned: list[tuple[str, str]] = []

    async def presigned_put_url(self, key: str, content_type: str, expires_in: int = 900) -> str:
        self.presigned.append((key, content_type))
        return f"https://r2.example/{key}?sig=put"

    async def object_size(self, key: str) -> int | None:
        return self.object_sizes.get(key)


class _FakeLimiter:
    def __init__(self) -> None:
        self.allowed = True
        self.calls: list[dict[str, str]] = []

    async def check(self, *, action: str, user_id: str, ip: str) -> RateDecision:
        self.calls.append({"action": action, "user_id": user_id, "ip": ip})
        return RateDecision(
            allowed=self.allowed,
            scope="user",
            action=action,
            count=61,
            limit=60,
            resets_at=datetime.now(UTC) + timedelta(hours=1),
        )


def _client() -> tuple[httpx.AsyncClient, _FakeDb, _FakeStorage, _FakeLimiter]:
    db = _FakeDb()
    storage = _FakeStorage()
    limiter = _FakeLimiter()
    app = create_app(
        config=_config(),
        db=cast(Any, db),
        identity_service=cast(Any, object()),
        credits=cast(Any, object()),
        job_queue=cast(Any, object()),
        rate_limiter=cast(Any, limiter),
        storage=cast(Any, storage),
    )
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test"), db, storage, limiter


def _headers(user_id: UUID | None = None) -> dict[str, str]:
    session = mint_app_jwt(_SECRET, user_id or _USER_ID, 3600)
    return {"Authorization": f"Bearer {session.access_token}"}


def _presign_body(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "project_id": _PROJECT_ID,
        "filename": "maqola.pdf",
        "size_bytes": 1024,
    }
    body.update(overrides)
    return body


def _uploaded_key(filename: str = "maqola.pdf") -> str:
    return f"uploads/{_USER_ID}/{uuid4().hex}/{filename}"


def _register_body(storage_key: str, **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "project_id": _PROJECT_ID,
        "storage_key": storage_key,
        "filename": "maqola.pdf",
    }
    body.update(overrides)
    return body


async def test_presign_requires_auth() -> None:
    client, *_ = _client()
    response = await client.post("/sources/presign", json=_presign_body())
    assert response.status_code == 401


async def test_presign_over_cap_is_429_before_any_presign() -> None:
    client, _db, storage, limiter = _client()
    limiter.allowed = False
    response = await client.post("/sources/presign", json=_presign_body(), headers=_headers())
    assert response.status_code == 429
    assert response.json()["detail"]["reason"] == "rate_limited"
    assert storage.presigned == []


async def test_presign_non_owner_project_is_404() -> None:
    client, db, storage, _limiter = _client()
    db.project_owner = str(uuid4())
    response = await client.post("/sources/presign", json=_presign_body(), headers=_headers())
    assert response.status_code == 404
    assert storage.presigned == []


async def test_presign_blocked_extension_is_422() -> None:
    client, _db, storage, _limiter = _client()
    response = await client.post(
        "/sources/presign", json=_presign_body(filename="evil.exe"), headers=_headers()
    )
    assert response.status_code == 422
    assert response.json()["detail"]["reason"] == "file_type_not_allowed"
    assert storage.presigned == []


async def test_presign_oversize_declared_is_422() -> None:
    client, *_ = _client()
    response = await client.post(
        "/sources/presign",
        json=_presign_body(size_bytes=MAX_FILE_SIZE_BYTES + 1),
        headers=_headers(),
    )
    assert response.status_code == 422


async def test_presign_happy_path_mints_user_prefixed_key() -> None:
    client, _db, storage, limiter = _client()
    response = await client.post("/sources/presign", json=_presign_body(), headers=_headers())
    assert response.status_code == 200
    body = response.json()
    assert body["storage_key"].startswith(f"uploads/{_USER_ID}/")
    assert body["storage_key"].endswith("/maqola.pdf")
    assert body["content_type"] == "application/pdf"
    assert body["upload_url"].startswith("https://r2.example/uploads/")
    assert limiter.calls[0]["action"] == "upload"
    assert storage.presigned == [(body["storage_key"], "application/pdf")]


async def test_register_rejects_foreign_key_prefix() -> None:
    client, db, _storage, _limiter = _client()
    other_key = f"uploads/{uuid4()}/{uuid4().hex}/maqola.pdf"
    response = await client.post("/sources", json=_register_body(other_key), headers=_headers())
    assert response.status_code == 403
    assert db.created == []


async def test_register_missing_object_is_422() -> None:
    client, db, _storage, _limiter = _client()
    response = await client.post(
        "/sources", json=_register_body(_uploaded_key()), headers=_headers()
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "object_not_uploaded"
    assert db.created == []


async def test_register_oversize_actual_object_is_422() -> None:
    client, db, storage, _limiter = _client()
    key = _uploaded_key()
    storage.object_sizes[key] = MAX_FILE_SIZE_BYTES + 1
    response = await client.post("/sources", json=_register_body(key), headers=_headers())
    assert response.status_code == 422
    assert response.json()["detail"]["reason"] == "file_too_large"
    assert db.created == []


async def test_register_per_project_cap_is_422() -> None:
    client, db, storage, _limiter = _client()
    db.sources = [
        {"storage_key": f"uploads/{_USER_ID}/x/{i}.pdf"} for i in range(MAX_FILES_PER_PROJECT)
    ]
    key = _uploaded_key()
    storage.object_sizes[key] = 1024
    response = await client.post("/sources", json=_register_body(key), headers=_headers())
    assert response.status_code == 422
    assert response.json()["detail"]["reason"] == "too_many_sources"


async def test_register_duplicate_key_is_409() -> None:
    client, db, storage, _limiter = _client()
    key = _uploaded_key()
    db.sources = [{"storage_key": key}]
    storage.object_sizes[key] = 1024
    response = await client.post("/sources", json=_register_body(key), headers=_headers())
    assert response.status_code == 409


async def test_register_happy_path_uses_real_size_and_mapped_type() -> None:
    client, db, storage, _limiter = _client()
    key = _uploaded_key()
    storage.object_sizes[key] = 2048
    response = await client.post("/sources", json=_register_body(key), headers=_headers())
    assert response.status_code == 200
    body = response.json()
    assert body["file_type"] == "pdf"
    assert body["file_size_bytes"] == 2048
    assert body["storage_key"] == key
    assert db.created[0]["file_size"] == 2048
    assert db.created[0]["storage_path"] == key


async def test_register_maps_jpg_and_md_to_check_values() -> None:
    client, _db, storage, _limiter = _client()
    for filename, expected in (("rasm.jpg", "jpeg"), ("eslatma.md", "markdown")):
        key = _uploaded_key(filename)
        storage.object_sizes[key] = 100
        response = await client.post(
            "/sources",
            json=_register_body(key, filename=filename),
            headers=_headers(),
        )
        assert response.status_code == 200
        assert response.json()["file_type"] == expected
