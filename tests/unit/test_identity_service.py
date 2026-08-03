"""Unit tests for the identity services (plan §5): initData, tokens, orchestration.

Real crypto against synthetic vectors (the HMAC math is the unit under test);
the Supabase boundaries (identity store, DatabaseClient, GoTrue) are faked per
testing rules.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any
from urllib.parse import urlencode
from uuid import UUID, uuid4

import pytest

from packages.api.services.identity import IdentityError, IdentityService
from packages.api.services.telegram_auth import InitDataError, validate_init_data
from packages.api.services.tokens import TokenError, mint_app_jwt, verify_app_jwt
from packages.core.enums import IdentityProvider
from packages.core.models.identity import AuthIdentity, TelegramAuthPayload
from packages.platform.config import PlatformConfig

_BOT_TOKEN = "12345:TEST-BOT-TOKEN"
_JWT_SECRET = "unit-test-jwt-secret"


def _signed_init_data(
    *,
    bot_token: str = _BOT_TOKEN,
    telegram_id: int = 777_000_111,
    auth_date: int | None = None,
    tamper_hash: bool = False,
) -> str:
    fields = {
        "auth_date": str(int(time.time()) if auth_date is None else auth_date),
        "query_id": "AAF-test",
        "user": json.dumps(
            {"id": telegram_id, "first_name": "Iko", "username": "iko_test"},
            separators=(",", ":"),
        ),
    }
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    digest = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    if tamper_hash:
        digest = ("0" if digest[0] != "0" else "1") + digest[1:]
    return urlencode({**fields, "hash": digest})


class TestValidateInitData:
    def test_valid_init_data_yields_payload(self) -> None:
        payload = validate_init_data(_signed_init_data(), _BOT_TOKEN)
        assert payload.telegram_id == 777_000_111
        assert payload.username == "iko_test"
        assert payload.first_name == "Iko"

    def test_tampered_hash_rejected(self) -> None:
        with pytest.raises(InitDataError) as excinfo:
            validate_init_data(_signed_init_data(tamper_hash=True), _BOT_TOKEN)
        assert excinfo.value.reason == "bad_signature"

    def test_wrong_bot_token_rejected(self) -> None:
        with pytest.raises(InitDataError) as excinfo:
            validate_init_data(_signed_init_data(), "999:OTHER-TOKEN")
        assert excinfo.value.reason == "bad_signature"

    def test_stale_auth_date_rejected_even_with_valid_signature(self) -> None:
        stale = int(time.time()) - 3600
        with pytest.raises(InitDataError) as excinfo:
            validate_init_data(_signed_init_data(auth_date=stale), _BOT_TOKEN)
        assert excinfo.value.reason == "stale_auth_date"

    def test_missing_hash_rejected(self) -> None:
        with pytest.raises(InitDataError) as excinfo:
            validate_init_data("auth_date=1&user=%7B%7D", _BOT_TOKEN)
        assert excinfo.value.reason == "missing_hash"

    def test_empty_bot_token_fails_closed(self) -> None:
        with pytest.raises(InitDataError) as excinfo:
            validate_init_data(_signed_init_data(), "")
        assert excinfo.value.reason == "server_missing_bot_token"


class TestAppJwt:
    def test_mint_verify_roundtrip(self) -> None:
        user_id = uuid4()
        session = mint_app_jwt(_JWT_SECRET, user_id, ttl_seconds=600)
        context = verify_app_jwt(_JWT_SECRET, session.access_token)
        assert context.user_id == user_id

    def test_wrong_secret_rejected(self) -> None:
        session = mint_app_jwt(_JWT_SECRET, uuid4(), ttl_seconds=600)
        with pytest.raises(TokenError) as excinfo:
            verify_app_jwt("other-secret", session.access_token)
        assert excinfo.value.reason == "bad_signature"

    def test_expired_token_rejected(self) -> None:
        session = mint_app_jwt(_JWT_SECRET, uuid4(), ttl_seconds=60)
        with pytest.raises(TokenError) as excinfo:
            verify_app_jwt(_JWT_SECRET, session.access_token, now=time.time() + 120)
        assert excinfo.value.reason == "expired"

    def test_malformed_token_rejected(self) -> None:
        with pytest.raises(TokenError) as excinfo:
            verify_app_jwt(_JWT_SECRET, "not.a.jwt.at.all")
        assert excinfo.value.reason == "malformed"

    def test_empty_secret_fails_closed_on_both_paths(self) -> None:
        with pytest.raises(TokenError):
            mint_app_jwt("", uuid4(), ttl_seconds=60)
        with pytest.raises(TokenError):
            verify_app_jwt("", "a.b.c")


class _FakeStore:
    def __init__(self) -> None:
        self.identities: dict[tuple[str, str], AuthIdentity] = {}
        self.created_users: list[dict[str, Any]] = []
        self.merges: list[tuple[UUID, UUID]] = []
        self.telegram_backfills: list[tuple[UUID, int]] = []
        self.deleted_users: list[UUID] = []

    async def get_identity(
        self, provider: IdentityProvider, external_id: str
    ) -> AuthIdentity | None:
        return self.identities.get((provider.value, external_id))

    async def upsert_identity(
        self,
        provider: IdentityProvider,
        external_id: str,
        user_id: UUID,
        auth_user_id: UUID | None = None,
    ) -> AuthIdentity:
        from datetime import UTC, datetime

        row = AuthIdentity(
            id=uuid4(),
            provider=provider,
            external_id=external_id,
            user_id=user_id,
            auth_user_id=auth_user_id,
            created_at=datetime.now(tz=UTC),
        )
        self.identities[(provider.value, external_id)] = row
        return row

    async def create_email_first_user(self, language: str = "uz") -> dict[str, Any]:
        user = {"id": str(uuid4()), "language": language}
        self.created_users.append(user)
        return user

    async def delete_user(self, user_id: UUID) -> None:
        self.deleted_users.append(user_id)

    async def set_user_telegram_id_if_null(self, user_id: UUID, telegram_id: int) -> None:
        self.telegram_backfills.append((user_id, telegram_id))

    async def merge_users(self, canonical: UUID, orphan: UUID) -> None:
        self.merges.append((canonical, orphan))


class _FakeDb:
    def __init__(self) -> None:
        self.users_by_telegram: dict[int, dict[str, Any]] = {}
        self.users_by_id: dict[str, dict[str, Any]] = {}
        self.created: list[int] = []
        # When set, create_user raises AFTER recording the row under telegram id,
        # simulating a UNIQUE violation from a parallel insert.
        self.create_raises_but_records = False

    async def get_user_by_telegram_id(self, telegram_id: int) -> dict[str, Any] | None:
        return self.users_by_telegram.get(telegram_id)

    async def get_user_by_id(self, user_id: str) -> dict[str, Any] | None:
        return self.users_by_id.get(user_id)

    async def create_user(self, telegram_id: int, **_: Any) -> dict[str, Any]:
        user = {"id": str(uuid4()), "telegram_id": telegram_id}
        self.users_by_telegram[telegram_id] = user
        self.users_by_id[user["id"]] = user
        self.created.append(telegram_id)
        if self.create_raises_but_records:
            raise RuntimeError("duplicate key value violates unique constraint")
        return user


def _config() -> PlatformConfig:
    return PlatformConfig(
        supabase_url="https://example.supabase.co",
        supabase_service_key="service",
        telegram_bot_token=_BOT_TOKEN,
        supabase_jwt_secret=_JWT_SECRET,
    )


def _payload(telegram_id: int = 777_000_111) -> TelegramAuthPayload:
    from datetime import UTC, datetime

    return TelegramAuthPayload(
        telegram_id=telegram_id, username="iko_test", first_name="Iko", auth_date=datetime.now(UTC)
    )


class TestIdentityServiceTelegram:
    @pytest.mark.asyncio
    async def test_existing_bot_user_is_backfilled_not_duplicated(self) -> None:
        store, db = _FakeStore(), _FakeDb()
        existing_id = str(uuid4())
        db.users_by_telegram[777_000_111] = {"id": existing_id, "telegram_id": 777_000_111}
        service = IdentityService(_config(), db, store)  # type: ignore[arg-type]

        user_id = await service.resolve_telegram(_payload())

        assert str(user_id) == existing_id
        assert db.created == []  # no duplicate user
        assert ("telegram", "777000111") in store.identities  # mapping backfilled

    @pytest.mark.asyncio
    async def test_new_telegram_user_created_once_then_resolved_from_identity(self) -> None:
        store, db = _FakeStore(), _FakeDb()
        service = IdentityService(_config(), db, store)  # type: ignore[arg-type]

        first = await service.resolve_telegram(_payload())
        second = await service.resolve_telegram(_payload())

        assert first == second
        assert db.created == [777_000_111]


class TestIdentityServiceLink:
    @pytest.mark.asyncio
    async def test_link_attaches_when_telegram_is_unclaimed(self) -> None:
        store, db = _FakeStore(), _FakeDb()
        service = IdentityService(_config(), db, store)  # type: ignore[arg-type]
        me = uuid4()

        merged = await service.link_telegram(me, _payload())

        assert merged is False
        assert store.merges == []
        assert store.identities[("telegram", "777000111")].user_id == me

    @pytest.mark.asyncio
    async def test_link_backfills_users_telegram_id_for_bot_resolution(self) -> None:
        # Panel finding: the bot resolves users ONLY via users.telegram_id — a
        # link that only writes the identity row would let the bot re-register
        # the same person as a brand-new user.
        store, db = _FakeStore(), _FakeDb()
        service = IdentityService(_config(), db, store)  # type: ignore[arg-type]
        me = uuid4()

        await service.link_telegram(me, _payload())

        assert store.telegram_backfills == [(me, 777_000_111)]

    @pytest.mark.asyncio
    async def test_link_merges_distinct_preexisting_user(self) -> None:
        store, db = _FakeStore(), _FakeDb()
        other = uuid4()
        await store.upsert_identity(IdentityProvider.TELEGRAM, "777000111", other)
        service = IdentityService(_config(), db, store)  # type: ignore[arg-type]
        me = uuid4()

        merged = await service.link_telegram(me, _payload())

        assert merged is True
        assert store.merges == [(me, other)]
        # The identity now points at the canonical (current) user.
        assert store.identities[("telegram", "777000111")].user_id == me

    @pytest.mark.asyncio
    async def test_link_same_user_is_idempotent_no_merge(self) -> None:
        store, db = _FakeStore(), _FakeDb()
        me = uuid4()
        await store.upsert_identity(IdentityProvider.TELEGRAM, "777000111", me)
        service = IdentityService(_config(), db, store)  # type: ignore[arg-type]

        merged = await service.link_telegram(me, _payload())

        assert merged is False
        assert store.merges == []

    @pytest.mark.asyncio
    async def test_merge_audit_event_embeds_json_payload_in_message(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        # F1 (4409e72 pattern): the audit payload must live IN the message
        # string so docker logs carry the fields verbatim, not in extra=.
        import json as _json

        store, db = _FakeStore(), _FakeDb()
        other = uuid4()
        await store.upsert_identity(IdentityProvider.TELEGRAM, "777000111", other)
        service = IdentityService(_config(), db, store)  # type: ignore[arg-type]
        me = uuid4()

        with caplog.at_level("INFO", logger="packages.api.services.identity"):
            await service.link_telegram(me, _payload())

        merged_msgs = [
            r.getMessage() for r in caplog.records if "identity_users_merged" in r.getMessage()
        ]
        assert len(merged_msgs) == 1
        payload = _json.loads(merged_msgs[0].split(" ", 1)[1])
        assert payload == {"canonical": str(me), "orphan": str(other)}


class TestTokenHardening:
    def test_raw_supabase_style_token_without_issuer_is_rejected(self) -> None:
        # Panel finding: a GoTrue token shares aud/role=authenticated. Forge one
        # with the SAME secret but no app issuer — it must NOT authenticate.
        import base64
        import hashlib
        import hmac
        import json
        import time as _time

        def _b64(d: bytes) -> str:
            return base64.urlsafe_b64encode(d).rstrip(b"=").decode()

        header = {"alg": "HS256", "typ": "JWT"}
        payload = {
            "sub": str(uuid4()),
            "role": "authenticated",
            "aud": "authenticated",
            "iss": "https://proj.supabase.co/auth/v1",
            "exp": int(_time.time()) + 600,
        }
        si = _b64(json.dumps(header).encode()) + "." + _b64(json.dumps(payload).encode())
        sig = hmac.new(_JWT_SECRET.encode(), si.encode(), hashlib.sha256).digest()
        with pytest.raises(TokenError) as excinfo:
            verify_app_jwt(_JWT_SECRET, f"{si}.{_b64(sig)}")
        assert excinfo.value.reason == "wrong_issuer"

    def test_non_hs256_alg_header_is_rejected(self) -> None:
        import base64
        import hashlib
        import hmac
        import json
        import time as _time

        def _b64(d: bytes) -> str:
            return base64.urlsafe_b64encode(d).rstrip(b"=").decode()

        header = {"alg": "none", "typ": "JWT"}
        payload = {
            "sub": str(uuid4()),
            "role": "authenticated",
            "aud": "authenticated",
            "iss": "nashr-api",
            "exp": int(_time.time()) + 600,
        }
        si = _b64(json.dumps(header).encode()) + "." + _b64(json.dumps(payload).encode())
        sig = hmac.new(_JWT_SECRET.encode(), si.encode(), hashlib.sha256).digest()
        with pytest.raises(TokenError) as excinfo:
            verify_app_jwt(_JWT_SECRET, f"{si}.{_b64(sig)}")
        assert excinfo.value.reason == "wrong_alg"

    def test_app_minted_token_still_roundtrips_with_issuer(self) -> None:
        uid = uuid4()
        session = mint_app_jwt(_JWT_SECRET, uid, ttl_seconds=600)
        assert verify_app_jwt(_JWT_SECRET, session.access_token).user_id == uid


class _FakeGoTrueService(IdentityService):
    """IdentityService with the GoTrue HTTP call stubbed to a fixed (email, id)."""

    def __init__(
        self, config: PlatformConfig, db: _FakeDb, store: _FakeStore, email: str, auth_id: UUID
    ) -> None:
        super().__init__(config, db, store)  # type: ignore[arg-type]
        self._stub = (email, auth_id)

    async def _fetch_gotrue_user(self, access_token: str):  # type: ignore[override]
        return self._stub


class TestEmailExchange:
    @pytest.mark.asyncio
    async def test_recycled_email_with_different_auth_user_is_rejected(self) -> None:
        # Panel finding: an email row bound to auth user A must not hand the
        # account to a different Supabase auth user B who now owns the address.
        store, db = _FakeStore(), _FakeDb()
        victim = uuid4()
        await store.upsert_identity(IdentityProvider.EMAIL, "a@x.com", victim, uuid4())
        svc = _FakeGoTrueService(_config(), db, store, "a@x.com", uuid4())
        with pytest.raises(IdentityError) as excinfo:
            await svc.resolve_email_exchange("tok")
        assert excinfo.value.reason == "email_auth_user_mismatch"

    @pytest.mark.asyncio
    async def test_first_login_binds_null_auth_user(self) -> None:
        store, db = _FakeStore(), _FakeDb()
        auth_id = uuid4()
        existing = uuid4()
        await store.upsert_identity(IdentityProvider.EMAIL, "a@x.com", existing, None)
        svc = _FakeGoTrueService(_config(), db, store, "a@x.com", auth_id)
        result = await svc.resolve_email_exchange("tok")
        assert result == existing
        assert store.identities[("email", "a@x.com")].auth_user_id == auth_id

    @pytest.mark.asyncio
    async def test_concurrent_first_login_reclaims_orphan(self) -> None:
        # Panel finding: two first logins create two users; the upsert winner is
        # canonical and the loser's user row is deleted, both callers converge.
        db = _FakeDb()
        winner_user = uuid4()

        class _RaceStore(_FakeStore):
            async def create_email_first_user(self, language: str = "uz"):
                return {"id": str(uuid4()), "language": language}

            async def upsert_identity(self, provider, external_id, user_id, auth_user_id=None):
                # Simulate the other request having already won the unique row.
                from datetime import UTC, datetime

                return AuthIdentity(
                    id=uuid4(),
                    provider=provider,
                    external_id=external_id,
                    user_id=winner_user,
                    auth_user_id=auth_user_id,
                    created_at=datetime.now(tz=UTC),
                )

        race = _RaceStore()
        svc = _FakeGoTrueService(_config(), db, race, "a@x.com", uuid4())
        result = await svc.resolve_email_exchange("tok")
        assert result == winner_user
        assert len(race.deleted_users) == 1  # the orphan we created lost the race


class TestTelegramRace:
    @pytest.mark.asyncio
    async def test_create_conflict_reresolves_instead_of_raising(self) -> None:
        # Panel finding: a parallel insert wins the telegram_id UNIQUE; create
        # raises but the row exists, so resolve returns it rather than 500-ing.
        store, db = _FakeStore(), _FakeDb()
        db.create_raises_but_records = True
        svc = IdentityService(_config(), db, store)  # type: ignore[arg-type]
        user_id = await svc.resolve_telegram(_payload())
        assert str(user_id) in db.users_by_id


class TestLinkSecondTelegram:
    @pytest.mark.asyncio
    async def test_link_rejected_when_user_already_has_different_telegram(self) -> None:
        # Panel finding: a users row holds one telegram_id and the bot resolves
        # only by it — a second, different Telegram account cannot be attached.
        store, db = _FakeStore(), _FakeDb()
        me = uuid4()
        db.users_by_id[str(me)] = {"id": str(me), "telegram_id": 111_222_333}
        svc = IdentityService(_config(), db, store)  # type: ignore[arg-type]
        with pytest.raises(IdentityError) as excinfo:
            await svc.link_telegram(me, _payload(telegram_id=999_888_777))
        assert excinfo.value.reason == "telegram_already_linked"
