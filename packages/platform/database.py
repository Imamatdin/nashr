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

from packages.core.models.presentation import DeckSpec
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

    async def set_project_package_tier(self, project_id: str, package_tier: str) -> None:
        """Stamp the package tier the user paid for onto a project (migration 010)."""

        await asyncio.to_thread(
            lambda: (
                self._client.table("projects")
                .update({"package_tier": package_tier})
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

    # ------------------------------------------------------------------ decks

    async def save_deck(self, project_id: str, deck_spec: DeckSpec) -> dict[str, Any]:
        """Persist a generated deck as the project's single current deck.

        Maintains exactly one ``decks`` row per project: the first call
        inserts, every later call (a regeneration, or a future brain edit)
        updates the same row in place. The upsert keys on the
        ``decks_project_id_key`` unique constraint, so "one current deck" is a
        database invariant rather than a convention a concurrent save could
        violate; row history is served by the conversation layer, not here.

        The denormalised ``title`` / ``language`` / ``audience`` columns come
        from the PROJECT row, never the spec. ``DeckSpec.interview.audience``
        is an ``AudienceType`` (school / undergraduate / …) that does not
        satisfy the ``decks.audience`` CHECK (talaba / oqituvchi / akademik /
        biznes), and ``DeckSpec.title`` permits 300 characters against the
        column's 200; the project row already holds DB-valid values for all
        three. Only ``deck_json`` is sourced from the spec. ``created_at`` and
        ``updated_at`` are owned by the column default and the
        ``trg_decks_updated_at`` trigger respectively, so neither is written.

        Raises :class:`ValueError` if the project does not exist — without it
        the denormalised columns cannot be filled (audience has no spec-side
        fallback) and the ``project_id`` foreign key would reject the insert
        anyway.
        """

        project = await self.get_project(project_id)
        if project is None:
            raise ValueError(f"project {project_id} not found; cannot persist deck")
        payload: dict[str, Any] = {
            "project_id": project_id,
            "title": str(project["title"]),
            "language": str(project["language"]),
            "audience": str(project["audience"]),
            "deck_json": deck_spec.model_dump(mode="json"),
        }
        result = await asyncio.to_thread(
            lambda: self._client.table("decks").upsert(payload, on_conflict="project_id").execute()
        )
        return cast(dict[str, Any], result.data[0])

    async def get_deck(self, project_id: str) -> dict[str, Any] | None:
        """Get the project's current deck row, or ``None`` if none persisted.

        Returns the single deck row maintained by :meth:`save_deck`. The
        ``order(created_at desc).limit(1)`` is a belt-and-braces tiebreak: the
        ``decks_project_id_key`` unique constraint guarantees at most one row
        per project, so the ordering is inert in practice but keeps the read
        deterministic if a stray duplicate ever predates the constraint.
        """

        result = await asyncio.to_thread(
            lambda: (
                self._client.table("decks")
                .select("*")
                .eq("project_id", project_id)
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            )
        )
        if not result.data:
            return None
        return cast(dict[str, Any], result.data[0])

    # --------------------------------------------------------- brain sessions

    # The brain editing session (Build 2, Stage 4). One row per project, upserted
    # on the ``brain_sessions_project_id_key`` unique constraint exactly like
    # decks, so the session is recoverable from project_id alone. This layer
    # deals only in JSON-ready values: the bot-side session store owns the
    # (de)serialization of the history / sources, which reference SDK and bot
    # types this platform module must not import. ``findings_json`` is omitted
    # from the payload so a Stage-4 upsert preserves whatever Stage 5 wrote.

    # Every session column EXCEPT the heavy figures_json — the light per-turn read.
    _SESSION_LIGHT_COLUMNS: str = (
        "id,project_id,history_json,sources_json,package,formats_json,"
        "approval_state,pending_action_json,fixes_used,accumulated_cost_usd,"
        "accumulated_image_count,findings_json,created_at,updated_at"
    )

    async def save_brain_session(
        self,
        project_id: str,
        *,
        history_json: list[dict[str, Any]],
        sources_json: dict[str, Any],
        package: str,
        formats_json: list[str],
        approval_state: str,
        pending_action_json: dict[str, Any] | None,
        fixes_used: int,
        accumulated_cost_usd: float,
        accumulated_image_count: int,
        figures_json: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Upsert the project's single brain session and return the saved row.

        The first call inserts, every later turn updates the same row in place
        (the unique constraint makes "one session per project" a DB invariant).
        Only the columns passed here are written; ``findings_json`` and the
        timestamp columns are left to Stage 5 and the DB defaults/trigger.

        ``figures_json`` is WRITE-ONCE: pass the figure list when creating the
        session, then omit it (``None``) on every per-turn save so the upsert
        preserves the stored figures rather than wiping them — the source figures
        never change during editing, only the deck and the conversation do.
        """

        payload: dict[str, Any] = {
            "project_id": project_id,
            "history_json": history_json,
            "sources_json": sources_json,
            "package": package,
            "formats_json": formats_json,
            "approval_state": approval_state,
            "pending_action_json": pending_action_json,
            "fixes_used": fixes_used,
            "accumulated_cost_usd": accumulated_cost_usd,
            "accumulated_image_count": accumulated_image_count,
        }
        if figures_json is not None:
            payload["figures_json"] = figures_json
        result = await asyncio.to_thread(
            lambda: (
                self._client.table("brain_sessions")
                .upsert(payload, on_conflict="project_id")
                .execute()
            )
        )
        return cast(dict[str, Any], result.data[0])

    async def get_brain_session(self, project_id: str) -> dict[str, Any] | None:
        """Get the project's brain session row WITHOUT figures, or ``None``.

        The restart-recovery read: keyed on project_id alone. Selects every
        column except ``figures_json`` so a text-only turn never transfers the
        megabytes of raster bytes — the fix path fetches those on demand via
        :meth:`get_brain_session_figures`.
        """

        result = await asyncio.to_thread(
            lambda: (
                self._client.table("brain_sessions")
                .select(self._SESSION_LIGHT_COLUMNS)
                .eq("project_id", project_id)
                .limit(1)
                .execute()
            )
        )
        if not result.data:
            return None
        return cast(dict[str, Any], result.data[0])

    async def get_brain_session_figures(self, project_id: str) -> list[dict[str, Any]] | None:
        """Get just the session's heavy ``figures_json``, or ``None`` if no row.

        The lazy-load half of the split: called only when a fix tool is about to
        fire, so the bot can hydrate the source figures the regen grounds against.
        """

        result = await asyncio.to_thread(
            lambda: (
                self._client.table("brain_sessions")
                .select("figures_json")
                .eq("project_id", project_id)
                .limit(1)
                .execute()
            )
        )
        if not result.data:
            return None
        row = cast(dict[str, Any], result.data[0])
        return cast(list[dict[str, Any]], row["figures_json"])

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

    async def get_invoice_by_number(self, invoice_number: str) -> dict[str, Any] | None:
        """Look up an invoice by its human-readable ``invoice_number`` field.

        The payment provider receives this string from the user, so this
        is the only entry point webhook handlers have into the invoice
        record. ``invoice_number`` is UNIQUE, so ``.limit(1)`` is a
        belt-and-braces guard against duplicate rows.
        """

        result = await asyncio.to_thread(
            lambda: (
                self._client.table("invoices")
                .select("*")
                .eq("invoice_number", invoice_number)
                .limit(1)
                .execute()
            )
        )
        if not result.data:
            return None
        return cast(dict[str, Any], result.data[0])

    async def expire_old_invoices(self) -> int:
        """Sweep pending invoices whose ``expires_at`` is in the past.

        Returns the number of invoices that transitioned to ``expired``.
        Implemented as a fetch-then-update pair rather than a single
        ``UPDATE ... WHERE`` because the supabase-py builder does not
        expose a comparison operator chain on update; correctness wins
        over the extra round-trip at v1 traffic levels.
        """

        now_iso = datetime.now(UTC).isoformat()

        def fetch() -> Any:
            return (
                self._client.table("invoices")
                .select("id")
                .eq("status", "pending")
                .lt("expires_at", now_iso)
                .execute()
            )

        fetched = await asyncio.to_thread(fetch)
        rows = cast(list[dict[str, Any]], list(fetched.data))
        count = 0
        for row in rows:
            invoice_id = row.get("id")
            if not isinstance(invoice_id, str):
                continue
            await self.mark_invoice_expired(invoice_id)
            count += 1
        return count

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

    # ------------------------------------------------------ generated upsert

    async def upsert_generated_file(
        self,
        project_id: str,
        file_type: str,
        storage_path: str,
        file_size: int,
    ) -> dict[str, Any]:
        """Register (or refresh) the project's single output row per format.

        Keys on the migration-007 ``uq_generated_files_project_type`` unique
        constraint, mirroring the stable R2 key layout
        ``generated/{project_id}/presentation.{ext}`` that overwrites in
        place — re-delivery updates the row instead of appending duplicates.
        """

        payload: dict[str, Any] = {
            "project_id": project_id,
            "file_type": file_type,
            "storage_path": storage_path,
            "file_size": file_size,
        }
        result = await asyncio.to_thread(
            lambda: (
                self._client.table("generated_files")
                .upsert(payload, on_conflict="project_id,file_type")
                .execute()
            )
        )
        return cast(dict[str, Any], result.data[0])

    # ------------------------------------------------------------ share links

    async def set_project_share_token(self, project_id: str, token: str | None) -> None:
        """Set (or clear, with ``None``) the project's public share token."""

        await asyncio.to_thread(
            lambda: (
                self._client.table("projects")
                .update({"share_token": token})
                .eq("id", project_id)
                .execute()
            )
        )

    async def get_project_by_share_token(self, token: str) -> dict[str, Any] | None:
        """Resolve a public share token to its project row, or ``None``.

        Indexed equality on the migration-009 unique constraint — constant
        lookup cost regardless of token shape, no prefix matching.
        """

        result = await asyncio.to_thread(
            lambda: (
                self._client.table("projects")
                .select("*")
                .eq("share_token", token)
                .limit(1)
                .execute()
            )
        )
        if not result.data:
            return None
        return cast(dict[str, Any], result.data[0])

    async def get_brain_session_sources(self, project_id: str) -> dict[str, Any] | None:
        """The session's light sources JSON alone (the provenance read).

        Narrower than :meth:`get_brain_session`: skips history and every other
        column so the provenance endpoint never transfers conversation state.
        """

        result = await asyncio.to_thread(
            lambda: (
                self._client.table("brain_sessions")
                .select("sources_json")
                .eq("project_id", project_id)
                .limit(1)
                .execute()
            )
        )
        if not result.data:
            return None
        row = cast(dict[str, Any], result.data[0])
        sources = row.get("sources_json")
        return cast("dict[str, Any] | None", sources if isinstance(sources, dict) else None)

    # ---------------------------------------------------------- raw queries

    def _query(self, table: str) -> Any:
        """Return the underlying Supabase query builder for a table.

        Used by ``CreditLedger`` and any future caller that needs to
        build a query shape the high-level methods don't expose. Typed
        as ``Any`` because the supabase-py builder type is unstable
        across SDK releases.
        """

        return self._client.table(table)

    def rpc(self, fn: str, params: dict[str, Any]) -> Any:
        """Call a Postgres function via PostgREST (synchronous; callers thread it).

        Used by the job queue (``claim_next_job`` / ``heartbeat_job`` /
        ``reap_stale_jobs``) and the rate limiter (``consume_rate_limit``) —
        operations that must be a single atomic statement server-side.
        """

        return self._client.rpc(fn, params).execute()
