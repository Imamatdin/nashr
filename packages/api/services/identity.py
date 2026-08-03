"""Identity orchestration: door proofs → canonical user → minted session (plan §5).

Three flows, each ending in the SAME shape (resolve or create the ``users`` row,
record the identity mapping, mint the Path A session JWT):

* Telegram door — a validated Mini App ``initData`` proof. Existing bot users
  are found via ``users.telegram_id`` (they predate identity rows) and their
  mapping is backfilled; the identity table is authoritative from then on.
* Email door — the browser proves email ownership through a Supabase magic
  link; the API verifies the resulting GoTrue access token against
  ``/auth/v1/user`` (works under either signing config), then exchanges it for
  the app session. The Supabase session is NOT the app credential.
* Link + merge — from an authenticated session, proving the second door either
  attaches the identity to the current user or, when the proof reveals a
  distinct pre-existing user, folds that orphan into the current user through
  the atomic ``merge_users`` RPC (005).
"""

from __future__ import annotations

import json
import logging
from typing import Any, Protocol
from uuid import UUID

import httpx

from packages.api.services.tokens import mint_app_jwt
from packages.core.enums import IdentityProvider
from packages.core.models.identity import MintedSession, TelegramAuthPayload
from packages.platform.config import PlatformConfig
from packages.platform.database import DatabaseClient
from packages.platform.identity_store import IdentityStore

logger = logging.getLogger(__name__)


class IdentityError(ValueError):
    """A failed identity resolution; ``reason`` is machine-readable."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class _StoreLike(Protocol):
    """The IdentityStore surface this service consumes (tests inject fakes)."""

    async def get_identity(self, provider: IdentityProvider, external_id: str) -> Any: ...

    async def upsert_identity(
        self,
        provider: IdentityProvider,
        external_id: str,
        user_id: UUID,
        auth_user_id: UUID | None = None,
    ) -> Any: ...

    async def create_email_first_user(self, language: str = "uz") -> dict[str, Any]: ...

    async def delete_user(self, user_id: UUID) -> None: ...

    async def set_user_telegram_id_if_null(self, user_id: UUID, telegram_id: int) -> None: ...

    async def merge_users(self, canonical: UUID, orphan: UUID) -> None: ...


class IdentityService:
    """Resolves door proofs to app users and mints sessions."""

    def __init__(
        self,
        config: PlatformConfig,
        db: DatabaseClient,
        store: _StoreLike | None = None,
    ) -> None:
        self._config = config
        self._db = db
        self._store: _StoreLike = store if store is not None else IdentityStore(config)

    # ------------------------------------------------------------ telegram door

    async def resolve_telegram(self, payload: TelegramAuthPayload) -> UUID:
        """Resolve a VALIDATED Telegram proof to the canonical users.id."""

        external_id = str(payload.telegram_id)
        identity = await self._store.get_identity(IdentityProvider.TELEGRAM, external_id)
        if identity is not None:
            return UUID(str(identity.user_id))
        # Pre-web bot users have no identity row yet: resolve by telegram_id and
        # backfill so the identity table is authoritative from here on.
        user = await self._db.get_user_by_telegram_id(payload.telegram_id)
        if user is None:
            try:
                user = await self._db.create_user(
                    telegram_id=payload.telegram_id,
                    full_name=payload.first_name,
                )
            except Exception:
                # Concurrent first login (panel finding): the parallel request
                # already inserted this telegram_id (UNIQUE), so create raised.
                # Re-resolve to the row it created instead of 500-ing.
                user = await self._db.get_user_by_telegram_id(payload.telegram_id)
                if user is None:
                    raise
            else:
                # Audit events embed their payload in the message string (the
                # 4409e72 pattern) so docker logs carry the fields verbatim.
                logger.info(
                    "identity_telegram_user_created %s",
                    json.dumps({"telegram_id": payload.telegram_id}),
                )
        user_id = UUID(str(user["id"]))
        await self._store.upsert_identity(IdentityProvider.TELEGRAM, external_id, user_id)
        return user_id

    # --------------------------------------------------------------- email door

    async def resolve_email_exchange(self, supabase_access_token: str) -> UUID:
        """Verify a Supabase (GoTrue) access token and resolve/create the app user.

        Verification is delegated to ``GET /auth/v1/user`` — GoTrue itself
        checks the signature, so this path is agnostic to the project's signing
        configuration (works under Path A and Path B alike).
        """

        email, auth_user_id = await self._fetch_gotrue_user(supabase_access_token)
        identity = await self._store.get_identity(IdentityProvider.EMAIL, email)
        if identity is not None:
            user_id = UUID(str(identity.user_id))
            if identity.auth_user_id is None:
                # First proof for a row whose Supabase auth user was never
                # recorded (or was deleted, FK set-null): bind it to the
                # just-proven auth user.
                await self._store.upsert_identity(
                    IdentityProvider.EMAIL, email, user_id, auth_user_id
                )
            elif identity.auth_user_id != auth_user_id:
                # Email recycled at the IdP (panel finding): a DIFFERENT Supabase
                # auth user now owns this address. Binding by email string alone
                # would hand the new owner the old app account. Refuse — an
                # intentional account move is a separate authenticated merge.
                raise IdentityError("email_auth_user_mismatch")
            return user_id
        created = await self._store.create_email_first_user()
        user_id = UUID(str(created["id"]))
        winner = await self._store.upsert_identity(
            IdentityProvider.EMAIL, email, user_id, auth_user_id
        )
        # Concurrent first-login race (panel finding): the unique(provider,
        # external_id) upsert returns the WINNING row. If another request won,
        # the user row we just created is an orphan — delete it and return the
        # canonical winner so both callers converge on one identity.
        winner_id = UUID(str(winner.user_id))
        if winner_id != user_id:
            await self._store.delete_user(user_id)
            logger.info(
                "identity_email_orphan_reclaimed %s",
                json.dumps({"orphan": str(user_id), "winner": str(winner_id)}),
            )
            return winner_id
        logger.info("identity_email_user_created %s", json.dumps({"user_id": str(user_id)}))
        return user_id

    async def _fetch_gotrue_user(self, access_token: str) -> tuple[str, UUID]:
        url = f"{self._config.supabase_url.rstrip('/')}/auth/v1/user"
        headers = {
            "apikey": self._config.supabase_anon_key,
            "Authorization": f"Bearer {access_token}",
        }
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(url, headers=headers)
        if response.status_code != 200:
            raise IdentityError("supabase_token_rejected")
        body = response.json()
        email = str(body.get("email") or "").strip().lower()
        if not email:
            raise IdentityError("supabase_user_has_no_email")
        try:
            auth_user_id = UUID(str(body.get("id")))
        except ValueError as exc:
            raise IdentityError("supabase_user_malformed") from exc
        return email, auth_user_id

    # ------------------------------------------------------------- link + merge

    async def link_telegram(self, current_user_id: UUID, payload: TelegramAuthPayload) -> bool:
        """Attach a VALIDATED Telegram proof to the authenticated user.

        Returns True when a distinct pre-existing user was merged into the
        current one (the caller may want to refresh everything), False for the
        plain attach. Merging is delegated to the atomic 005 RPC.
        """

        external_id = str(payload.telegram_id)
        # A users row holds at most ONE telegram_id (UNIQUE) and the bot resolves
        # ONLY by it, so a user who already has a DIFFERENT bot identity cannot
        # attach a second Telegram account (panel finding): merging would delete
        # the other account's row and strand it from the bot. Refuse up front.
        current = await self._db.get_user_by_id(str(current_user_id))
        current_tg = current.get("telegram_id") if current else None
        if current_tg is not None and int(current_tg) != payload.telegram_id:
            raise IdentityError("telegram_already_linked")

        identity = await self._store.get_identity(IdentityProvider.TELEGRAM, external_id)
        other_user_id: UUID | None = None
        if identity is not None:
            other_user_id = UUID(str(identity.user_id))
        else:
            existing = await self._db.get_user_by_telegram_id(payload.telegram_id)
            if existing is not None:
                other_user_id = UUID(str(existing["id"]))

        if other_user_id is not None and other_user_id != current_user_id:
            # BOTH doors are proven: the session proves the current user, the
            # validated initData proves the telegram account. Fold the orphan in.
            await self._store.merge_users(current_user_id, other_user_id)
            logger.info(
                "identity_users_merged %s",
                json.dumps({"canonical": str(current_user_id), "orphan": str(other_user_id)}),
            )
            merged = True
        else:
            merged = False
        await self._store.upsert_identity(IdentityProvider.TELEGRAM, external_id, current_user_id)
        # Bot-split guard (panel finding): the bot resolves users only through
        # users.telegram_id, so an email-first user linking an unclaimed
        # Telegram account must also gain the column value or the bot will
        # re-register them as a new user. No-op when already set; the merge
        # path's SQL performs the same carry-over inside its transaction.
        await self._store.set_user_telegram_id_if_null(current_user_id, payload.telegram_id)
        return merged

    # ------------------------------------------------------------------ session

    def mint_session(self, user_id: UUID) -> MintedSession:
        """Mint the Path A app session for a resolved user."""

        return mint_app_jwt(
            self._config.supabase_jwt_secret, user_id, self._config.app_jwt_ttl_seconds
        )
