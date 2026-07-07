"""Service-role persistence for ``user_auth_identities`` (migration 005).

Follows the :class:`packages.platform.database.DatabaseClient` idioms: every
public method is a coroutine dispatching the synchronous supabase-py call via
``asyncio.to_thread``; raw PostgREST dicts are parsed into typed models at this
boundary. Writes here are service-role-only by design — RLS exposes the table
read-only to owners, and linking/merging happen exclusively through the API
after it has verified an ownership proof.
"""

from __future__ import annotations

import asyncio
from typing import Any, cast
from uuid import UUID

from packages.core.enums import IdentityProvider
from packages.core.models.identity import AuthIdentity
from packages.platform.config import PlatformConfig
from packages.platform.database import generate_subscriber_id
from supabase import Client, create_client

_TABLE = "user_auth_identities"


class IdentityStore:
    """Reads and writes identity mappings with the service-role key."""

    def __init__(self, config: PlatformConfig, client: Client | None = None) -> None:
        self._config = config
        if client is not None:
            self._client = client
        else:
            self._client = create_client(config.supabase_url, config.supabase_service_key)

    async def get_identity(
        self, provider: IdentityProvider, external_id: str
    ) -> AuthIdentity | None:
        """Look up one identity row by its natural key."""

        result = await asyncio.to_thread(
            lambda: (
                self._client.table(_TABLE)
                .select("*")
                .eq("provider", provider.value)
                .eq("external_id", external_id)
                .limit(1)
                .execute()
            )
        )
        rows = cast(list[dict[str, Any]], result.data)
        if not rows:
            return None
        return AuthIdentity.model_validate(_strip_updated_at(rows[0]))

    async def upsert_identity(
        self,
        provider: IdentityProvider,
        external_id: str,
        user_id: UUID,
        auth_user_id: UUID | None = None,
    ) -> AuthIdentity:
        """Insert-or-update the mapping for ``(provider, external_id)``.

        Upsert (not insert) so repeat logins are idempotent and linking after a
        merge repoints in place. ``auth_user_id`` is only ever widened — an
        existing non-null link is preserved when the caller passes ``None``.
        """

        payload: dict[str, Any] = {
            "provider": provider.value,
            "external_id": external_id,
            "user_id": str(user_id),
        }
        if auth_user_id is not None:
            payload["auth_user_id"] = str(auth_user_id)
        result = await asyncio.to_thread(
            lambda: (
                self._client.table(_TABLE)
                .upsert(payload, on_conflict="provider,external_id")
                .execute()
            )
        )
        rows = cast(list[dict[str, Any]], result.data)
        return AuthIdentity.model_validate(_strip_updated_at(rows[0]))

    async def create_email_first_user(self, language: str = "uz") -> dict[str, Any]:
        """Create a users row with NO telegram identity (browser door, 005).

        Mirrors ``DatabaseClient.create_user`` minus the telegram_id (nullable
        since migration 005). The subscriber id keeps the same generator and
        UNIQUE backstop.
        """

        existing_result = await asyncio.to_thread(
            lambda: self._client.table("users").select("subscriber_id").execute()
        )
        existing = {
            row["subscriber_id"]
            for row in cast(list[dict[str, Any]], existing_result.data)
            if row.get("subscriber_id")
        }
        payload = {
            "language": language,
            "subscriber_id": generate_subscriber_id(existing),
        }
        result = await asyncio.to_thread(
            lambda: self._client.table("users").insert(payload).execute()
        )
        return cast(dict[str, Any], result.data[0])

    async def delete_user(self, user_id: UUID) -> None:
        """Hard-delete a users row — used to reclaim an orphan from a login race."""

        await asyncio.to_thread(
            lambda: self._client.table("users").delete().eq("id", str(user_id)).execute()
        )

    async def set_user_telegram_id_if_null(self, user_id: UUID, telegram_id: int) -> None:
        """Backfill ``users.telegram_id`` when the row has none (panel finding).

        The bot resolves users ONLY via ``users.telegram_id``; an email-first
        user who links an UNCLAIMED Telegram account would otherwise be
        re-registered by the bot as a brand-new user. The ``is null`` filter
        makes this a no-op when a bot identity already exists — the identity
        table remains the authority for additional linked accounts.
        """

        await asyncio.to_thread(
            lambda: (
                self._client.table("users")
                .update({"telegram_id": telegram_id})
                .eq("id", str(user_id))
                .is_("telegram_id", "null")
                .execute()
            )
        )

    async def merge_users(self, canonical: UUID, orphan: UUID) -> None:
        """Atomically fold ``orphan`` into ``canonical`` via the 005 RPC.

        The server-side function repoints projects/orders/invoices/credit_ledger/
        identities in one transaction and deletes the orphan users row —
        PostgREST cannot span statements, so the transaction MUST live in SQL.
        Callers verify ownership proofs for BOTH doors before invoking.
        """

        await asyncio.to_thread(
            lambda: self._client.rpc(
                "merge_users", {"canonical": str(canonical), "orphan": str(orphan)}
            ).execute()
        )


def _strip_updated_at(row: dict[str, Any]) -> dict[str, Any]:
    """Drop ``updated_at`` before validation — AuthIdentity models the stable row."""

    return {key: value for key, value in row.items() if key != "updated_at"}
