"""Database client for the Nashr platform.

Wraps Supabase operations for every persisted entity the bot, API, and
workers touch: users, projects, sources, generated files, invoices, and
the credit ledger. Uses the service role key so all calls bypass RLS;
the Telegram bot is the trusted backend and every authenticated request
has already been resolved to a user_id before reaching this layer.

The supabase-py SDK is synchronous; every call is wrapped in
``asyncio.to_thread`` so worker event loops stay non-blocking. Tests
inject a mock ``client`` directly into the constructor to avoid hitting
the network.
"""

from __future__ import annotations

import asyncio
import random
import time
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from packages.platform.config import PlatformConfig
from supabase import Client, create_client

SUBSCRIBER_ID_MIN: int = 100_000
SUBSCRIBER_ID_MAX: int = 999_999
INVOICE_EXPIRY_HOURS: int = 24


def generate_subscriber_id(existing_ids: set[str]) -> str:
    """Generate a unique 6-digit subscriber ID.

    The ID is 6 digits, never starts with zero, and is guaranteed unique
    against the supplied ``existing_ids`` set. The 900 000-element
    search space dwarfs the projected v1 user base (< 10 000), so a
    simple rejection loop converges in O(1) expected attempts.
    """

    while True:
        candidate = str(random.randint(SUBSCRIBER_ID_MIN, SUBSCRIBER_ID_MAX))
        if candidate not in existing_ids:
            return candidate


def generate_invoice_number(subscriber_id: str) -> str:
    """Generate an invoice number from a subscriber ID and the current time.

    Format: ``{subscriber_id}-{timestamp_short}`` where the suffix is
    the last four digits of the current Unix timestamp. Uniqueness is
    enforced by the database (``invoice_number`` UNIQUE); collisions
    within the same 10 000-second window are guarded at insert time.
    """

    seq = str(int(time.time()))[-4:]
    return f"{subscriber_id}-{seq}"


class DatabaseClient:
    """Supabase-backed persistence layer for the Nashr platform.

    All public methods are coroutines; the underlying supabase-py calls
    are synchronous and dispatched via ``asyncio.to_thread`` so callers
    can ``await`` them inside async workers without blocking the loop.

    Tests construct ``DatabaseClient(config, client=mock_client)`` to
    inject a fake supabase Client; production callers pass only the
    config and rely on :func:`supabase.create_client` to do the work.
    """

    def __init__(self, config: PlatformConfig, client: Client | None = None) -> None:
        self._config = config
        if client is not None:
            self._client = client
        else:
            self._client = create_client(config.supabase_url, config.supabase_service_key)

    # ------------------------------------------------------------------ users

    async def create_user(
        self,
        telegram_id: int,
        language: str = "uz",
        calibration_level: str = "bakalavr",
        full_name: str | None = None,
    ) -> dict[str, Any]:
        """Register a new user with a unique 6-digit subscriber ID.

        The subscriber ID is the payment identifier the user types into
        Payme / Click / Uzum. We generate it client-side and rely on
        ``users.subscriber_id`` UNIQUE to catch the rare race; the
        rejection loop against the in-memory set keeps the happy path
        single-insert.
        """

        existing = await self._fetch_subscriber_ids()
        subscriber_id = generate_subscriber_id(existing)
        payload: dict[str, Any] = {
            "telegram_id": telegram_id,
            "language": language,
            "calibration_level": calibration_level,
            "subscriber_id": subscriber_id,
        }
        if full_name is not None:
            payload["full_name"] = full_name
        result = await asyncio.to_thread(
            lambda: self._client.table("users").insert(payload).execute()
        )
        return cast(dict[str, Any], result.data[0])

    async def _fetch_subscriber_ids(self) -> set[str]:
        result = await asyncio.to_thread(
            lambda: self._client.table("users").select("subscriber_id").execute()
        )
        rows = cast(list[dict[str, Any]], result.data)
        out: set[str] = set()
        for row in rows:
            sid = row.get("subscriber_id")
            if isinstance(sid, str):
                out.add(sid)
        return out

    async def get_user_by_telegram_id(self, telegram_id: int) -> dict[str, Any] | None:
        """Look up a user by their Telegram user ID."""

        result = await asyncio.to_thread(
            lambda: (
                self._client.table("users")
                .select("*")
                .eq("telegram_id", telegram_id)
                .limit(1)
                .execute()
            )
        )
        if not result.data:
            return None
        return cast(dict[str, Any], result.data[0])

    async def get_user_by_subscriber_id(self, subscriber_id: str) -> dict[str, Any] | None:
        """Look up a user by their 6-digit payment subscriber ID."""

        result = await asyncio.to_thread(
            lambda: (
                self._client.table("users")
                .select("*")
                .eq("subscriber_id", subscriber_id)
                .limit(1)
                .execute()
            )
        )
        if not result.data:
            return None
        return cast(dict[str, Any], result.data[0])

    async def update_user_language(self, user_id: str, language: str) -> None:
        """Update the user's preferred language."""

        await asyncio.to_thread(
            lambda: (
                self._client.table("users")
                .update({"language": language})
                .eq("id", user_id)
                .execute()
            )
        )

    async def update_user_calibration(self, user_id: str, level: str) -> None:
        """Update the user's calibration level."""

        await asyncio.to_thread(
            lambda: (
                self._client.table("users")
                .update({"calibration_level": level})
                .eq("id", user_id)
                .execute()
            )
        )

    # --------------------------------------------------------------- projects

    async def create_project(
        self,
        user_id: str,
        title: str,
        project_type: str,
        language: str = "uz",
        audience: str = "talaba",
    ) -> dict[str, Any]:
        """Create a new project for a user."""

        payload: dict[str, Any] = {
            "user_id": user_id,
            "title": title,
            "type": project_type,
            "language": language,
            "audience": audience,
        }
        result = await asyncio.to_thread(
            lambda: self._client.table("projects").insert(payload).execute()
        )
        return cast(dict[str, Any], result.data[0])

    async def get_project(self, project_id: str) -> dict[str, Any] | None:
        """Get a project by its UUID."""

        result = await asyncio.to_thread(
            lambda: (
                self._client.table("projects").select("*").eq("id", project_id).limit(1).execute()
            )
        )
        if not result.data:
            return None
        return cast(dict[str, Any], result.data[0])

    async def get_user_projects(self, user_id: str, limit: int = 20) -> list[dict[str, Any]]:
        """Get a user's projects, newest first."""

        result = await asyncio.to_thread(
            lambda: (
                self._client.table("projects")
                .select("*")
                .eq("user_id", user_id)
                .order("created_at", desc=True)
                .limit(limit)
                .execute()
            )
        )
        return cast(list[dict[str, Any]], list(result.data))

    async def update_project_status(self, project_id: str, status: str) -> None:
        """Update a project's lifecycle status."""

        await asyncio.to_thread(
            lambda: (
                self._client.table("projects")
                .update({"status": status})
                .eq("id", project_id)
                .execute()
            )
        )

    # ---------------------------------------------------------------- sources

    async def create_source(
        self,
        project_id: str,
        filename: str,
        file_type: str,
        file_size: int,
        storage_path: str,
    ) -> dict[str, Any]:
        """Register a source file for a project."""

        payload: dict[str, Any] = {
            "project_id": project_id,
            "filename": filename,
            "file_type": file_type,
            "file_size_bytes": file_size,
            "storage_key": storage_path,
        }
        result = await asyncio.to_thread(
            lambda: self._client.table("sources").insert(payload).execute()
        )
        return cast(dict[str, Any], result.data[0])

    async def get_project_sources(self, project_id: str) -> list[dict[str, Any]]:
        """Get every source uploaded for a project."""

        result = await asyncio.to_thread(
            lambda: (
                self._client.table("sources")
                .select("*")
                .eq("project_id", project_id)
                .order("created_at", desc=False)
                .execute()
            )
        )
        return cast(list[dict[str, Any]], list(result.data))

    # ------------------------------------------------------- generated_files

    async def create_generated_file(
        self,
        project_id: str,
        file_type: str,
        storage_path: str,
        file_size: int,
    ) -> dict[str, Any]:
        """Register an output file produced for a project."""

        payload: dict[str, Any] = {
            "project_id": project_id,
            "file_type": file_type,
            "storage_path": storage_path,
            "file_size": file_size,
        }
        result = await asyncio.to_thread(
            lambda: self._client.table("generated_files").insert(payload).execute()
        )
        return cast(dict[str, Any], result.data[0])

    async def get_project_files(self, project_id: str) -> list[dict[str, Any]]:
        """Get every generated output file for a project."""

        result = await asyncio.to_thread(
            lambda: (
                self._client.table("generated_files")
                .select("*")
                .eq("project_id", project_id)
                .order("created_at", desc=True)
                .execute()
            )
        )
        return cast(list[dict[str, Any]], list(result.data))

    # --------------------------------------------------------------- invoices

    async def create_invoice(
        self,
        user_id: str,
        project_id: str,
        amount_uzs: int,
        product_type: str,
    ) -> dict[str, Any]:
        """Create a payment invoice for a user+project at a product tier.

        The invoice number is derived from the user's subscriber ID and
        the current timestamp; uniqueness is enforced by the database.
        Expiry is set 24 hours from creation; pending invoices past that
        are swept by :meth:`mark_invoice_expired`.
        """

        user = await self.get_user_by_id(user_id)
        if user is None:
            raise ValueError(f"user {user_id} not found")
        subscriber_id = user.get("subscriber_id")
        if not isinstance(subscriber_id, str):
            raise ValueError(f"user {user_id} has no subscriber_id")
        invoice_number = generate_invoice_number(subscriber_id)
        expires_at = datetime.now(UTC) + timedelta(hours=INVOICE_EXPIRY_HOURS)
        payload: dict[str, Any] = {
            "user_id": user_id,
            "project_id": project_id,
            "invoice_number": invoice_number,
            "amount_uzs": amount_uzs,
            "product_type": product_type,
            "status": "pending",
            "expires_at": expires_at.isoformat(),
        }
        result = await asyncio.to_thread(
            lambda: self._client.table("invoices").insert(payload).execute()
        )
        return cast(dict[str, Any], result.data[0])

    async def get_user_by_id(self, user_id: str) -> dict[str, Any] | None:
        """Internal lookup by primary key (used during invoice creation)."""

        result = await asyncio.to_thread(
            lambda: self._client.table("users").select("*").eq("id", user_id).limit(1).execute()
        )
        if not result.data:
            return None
        return cast(dict[str, Any], result.data[0])

    async def get_invoice(self, invoice_id: str) -> dict[str, Any] | None:
        """Get an invoice by its UUID."""

        result = await asyncio.to_thread(
            lambda: (
                self._client.table("invoices").select("*").eq("id", invoice_id).limit(1).execute()
            )
        )
        if not result.data:
            return None
        return cast(dict[str, Any], result.data[0])

    async def get_pending_invoice(self, user_id: str, project_id: str) -> dict[str, Any] | None:
        """Get the most recent pending invoice for a user+project pair."""

        result = await asyncio.to_thread(
            lambda: (
                self._client.table("invoices")
                .select("*")
                .eq("user_id", user_id)
                .eq("project_id", project_id)
                .eq("status", "pending")
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            )
        )
        if not result.data:
            return None
        return cast(dict[str, Any], result.data[0])

    async def mark_invoice_paid(
        self,
        invoice_id: str,
        payment_provider: str,
        payment_reference: str,
    ) -> None:
        """Mark an invoice as paid and record the provider reference.

        The caller is responsible for writing the matching credit-grant
        row into the ledger; this method only flips the invoice state.
        Separating the two writes keeps the ledger append-only even if a
        webhook arrives twice.
        """

        payload: dict[str, Any] = {
            "status": "paid",
            "payment_provider": payment_provider,
            "payment_reference": payment_reference,
            "paid_at": datetime.now(UTC).isoformat(),
        }
        await asyncio.to_thread(
            lambda: self._client.table("invoices").update(payload).eq("id", invoice_id).execute()
        )

    async def mark_invoice_expired(self, invoice_id: str) -> None:
        """Mark a pending invoice as expired (after the 24h window)."""

        await asyncio.to_thread(
            lambda: (
                self._client.table("invoices")
                .update({"status": "expired"})
                .eq("id", invoice_id)
                .execute()
            )
        )

    # ---------------------------------------------------------- raw queries

    def _query(self, table: str) -> Any:
        """Return the underlying Supabase query builder for a table.

        Used by ``CreditLedger`` and any future caller that needs to
        build a query shape the high-level methods don't expose. Typed
        as ``Any`` because the supabase-py builder type is unstable
        across SDK releases.
        """

        return self._client.table(table)
