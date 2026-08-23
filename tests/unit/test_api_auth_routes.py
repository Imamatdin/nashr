"""Route-level tests for the auth surface: real app factory, faked identity service.

Exercised through httpx's ASGI transport — the real FastAPI wiring (routers,
dependency, error mapping) runs; only the Supabase/Telegram boundaries are faked.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import datetime
from typing import Any
from urllib.parse import urlencode
from uuid import UUID, uuid4

import httpx
import pytest

from packages.api.app import create_app
from packages.api.services.identity import IdentityError
from packages.api.services.tokens import mint_app_jwt, verify_app_jwt
from packages.core.models.identity import TelegramAuthPayload
from packages.platform.config import PlatformConfig

_BOT_TOKEN = "12345:TEST-BOT-TOKEN"
_JWT_SECRET = "route-test-secret"


def _config(**overrides: Any) -> PlatformConfig:
    defaults: dict[str, Any] = {
        "supabase_url": "https://example.supabase.co",
        "supabase_service_key": "service",
        "telegram_bot_token": _BOT_TOKEN,
        "supabase_jwt_secret": _JWT_SECRET,
    }
    defaults.update(overrides)
    return PlatformConfig(**defaults)


def _signed_init_data(telegram_id: int = 555_000_222) -> str:
    fields = {
        "auth_date": str(int(time.time())),
        "user": json.dumps({"id": telegram_id, "first_name": "Iko"}, separators=(",", ":")),
    }
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", _BOT_TOKEN.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


class _FakeIdentityService:
    """Route-test double: real mint, scripted resolution."""

    def __init__(self, config: PlatformConfig) -> None:
        self._config = config
        self.known_user = uuid4()
        self.email_error: IdentityError | None = None
        self.link_merged = False
        self.calls: list[tuple[str, Any]] = []

    async def resolve_telegram(self, payload: TelegramAuthPayload) -> UUID:
        self.calls.append(("telegram", payload.telegram_id))
        return self.known_user

    async def resolve_email_exchange(self, token: str) -> UUID:
        self.calls.append(("email", token))
        if self.email_error is not None:
            raise self.email_error
        return self.known_user

    async def link_telegram(self, current_user_id: UUID, payload: TelegramAuthPayload) -> bool:
        self.calls.append(("link", (current_user_id, payload.telegram_id)))
        return self.link_merged

    def mint_session(self, user_id: UUID) -> Any:
        return mint_app_jwt(self._config.supabase_jwt_secret, user_id, 600)


def _client(config: PlatformConfig | None = None) -> tuple[httpx.AsyncClient, _FakeIdentityService]:
    resolved = config or _config()
    fake = _FakeIdentityService(resolved)
    app = create_app(config=resolved, db=object(), identity_service=fake)  # type: ignore[arg-type]
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://api.test"), fake


@pytest.mark.asyncio
async def test_health() -> None:
    client, _ = _client()
    async with client:
        response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "nashr-api"}


@pytest.mark.asyncio
async def test_telegram_login_happy_path_returns_session() -> None:
    client, fake = _client()
    async with client:
        response = await client.post("/auth/telegram", json={"init_data": _signed_init_data()})
    assert response.status_code == 200
    body = response.json()
    assert body["user_id"] == str(fake.known_user)
    assert body["token_type"] == "bearer"
    assert body["access_token"].count(".") == 2
    assert fake.calls == [("telegram", 555_000_222)]


@pytest.mark.asyncio
async def test_telegram_login_forged_init_data_is_401_and_never_reaches_service() -> None:
    client, fake = _client()
    forged = _signed_init_data().replace("hash=", "hash=0")
    async with client:
        response = await client.post("/auth/telegram", json={"init_data": forged})
    assert response.status_code == 401
    assert response.json()["detail"] == "bad_signature"
    assert fake.calls == []


@pytest.mark.asyncio
async def test_email_exchange_rejection_maps_to_401() -> None:
    client, fake = _client()
    fake.email_error = IdentityError("supabase_token_rejected")
    async with client:
        response = await client.post(
            "/auth/email/exchange", json={"supabase_access_token": "sb-token"}
        )
    assert response.status_code == 401
    assert response.json()["detail"] == "supabase_token_rejected"


@pytest.mark.asyncio
async def test_me_requires_bearer_and_returns_subject() -> None:
    client, fake = _client()
    token = mint_app_jwt(_JWT_SECRET, fake.known_user, 600).access_token
    async with client:
        anonymous = await client.get("/auth/me")
        garbage = await client.get("/auth/me", headers={"Authorization": "Bearer nope"})
        authed = await client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert anonymous.status_code == 401
    assert garbage.status_code == 401
    assert authed.status_code == 200
    assert authed.json() == {"user_id": str(fake.known_user)}


@pytest.mark.asyncio
async def test_link_telegram_requires_auth_then_reports_merge() -> None:
    client, fake = _client()
    fake.link_merged = True
    token = mint_app_jwt(_JWT_SECRET, fake.known_user, 600).access_token
    async with client:
        anonymous = await client.post(
            "/auth/link/telegram", json={"init_data": _signed_init_data()}
        )
        authed = await client.post(
            "/auth/link/telegram",
            json={"init_data": _signed_init_data()},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert anonymous.status_code == 401
    assert authed.status_code == 200
    assert authed.json()["merged"] is True
    assert ("link", (fake.known_user, 555_000_222)) in fake.calls


@pytest.mark.asyncio
async def test_missing_jwt_secret_fails_closed_as_503() -> None:
    client, _ = _client(_config(supabase_jwt_secret=""))
    async with client:
        response = await client.post("/auth/telegram", json={"init_data": _signed_init_data()})
    assert response.status_code == 503
    assert response.json()["detail"] == "server_missing_jwt_secret"


@pytest.mark.asyncio
async def test_protected_route_with_bearer_but_missing_secret_is_503_not_401() -> None:
    # Panel finding: an empty server secret is a deployment fault; a protected
    # route hit with a bearer token must surface 503, not mislabel it 401.
    good = mint_app_jwt(_JWT_SECRET, uuid4(), 600).access_token
    client, _ = _client(_config(supabase_jwt_secret=""))
    async with client:
        response = await client.get("/auth/me", headers={"Authorization": f"Bearer {good}"})
    assert response.status_code == 503
    assert response.json()["detail"] == "server_missing_jwt_secret"


@pytest.mark.asyncio
async def test_refresh_returns_a_usable_session_for_the_same_user() -> None:
    client, fake = _client()
    # Short TTL on the incoming bearer so the re-minted session's expiry is
    # strictly later without the test having to sleep.
    current = mint_app_jwt(_JWT_SECRET, fake.known_user, 60)
    async with client:
        response = await client.post(
            "/auth/refresh", headers={"Authorization": f"Bearer {current.access_token}"}
        )
    assert response.status_code == 200
    body = response.json()
    assert body["user_id"] == str(fake.known_user)
    assert body["token_type"] == "bearer"
    assert body["access_token"] != current.access_token
    refreshed_expiry = datetime.fromisoformat(body["expires_at"])
    assert refreshed_expiry > current.expires_at
    verified = verify_app_jwt(_JWT_SECRET, body["access_token"])
    assert verified.user_id == fake.known_user


@pytest.mark.asyncio
async def test_refresh_without_bearer_is_401() -> None:
    client, _ = _client()
    async with client:
        response = await client.post("/auth/refresh")
    assert response.status_code == 401
    assert response.json()["detail"] == "missing_bearer_token"


@pytest.mark.asyncio
async def test_refresh_cannot_rescue_an_already_expired_token() -> None:
    # The documented limitation of a sliding session: there is no second
    # credential, so a dead token has nothing left to prove identity with and
    # the web must refresh PROACTIVELY. This test pins that behaviour.
    client, fake = _client()
    dead = mint_app_jwt(_JWT_SECRET, fake.known_user, -10).access_token
    async with client:
        response = await client.post("/auth/refresh", headers={"Authorization": f"Bearer {dead}"})
    assert response.status_code == 401
    assert response.json()["detail"] == "expired"
