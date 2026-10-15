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

from postgrest.exceptions import APIError

from packages.platform.config import PlatformConfig
from supabase import Client, create_client

SUBSCRIBER_ID_MIN: int = 100_000
SUBSCRIBER_ID_MAX: int = 999_999
INVOICE_EXPIRY_HOURS: int = 24


class SessionVersionConflictError(Exception):
    """A session write lost its compare-and-swap: the row moved since it was read."""

    def __init__(self, key: str) -> None:
        self.key = key
        super().__init__(f"brain session {key} changed since it was read")


def _is_session_conflict(exc: APIError) -> bool:
    """A unique violation (row created concurrently) or the CAS trigger's refusal."""

    return exc.code in ("23505", "40001") or "session_version_conflict" in str(exc.message)


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

    async def get_source_passages(
        self, project_id: str, source_id: str | None, offset: int, limit: int
    ) -> list[dict[str, Any]]:
        """Read a bounded, stable page of evidence within one project."""

        def run() -> Any:
            query = self._client.table("source_chunks").select("*").eq("project_id", project_id)
            if source_id:
                query = query.eq("source_id", source_id)
            return (
                query.order("source_id")
                .order("chunk_index")
                .range(offset, offset + limit - 1)
                .execute()
            )

        result = await asyncio.to_thread(run)
        return cast(list[dict[str, Any]], list(result.data))

    async def get_evidence_passage(self, project_id: str, passage_id: str) -> dict[str, Any] | None:
        """Read a selected passage using both its identity and project scope."""

        result = await asyncio.to_thread(
            lambda: (
                self._client.table("source_chunks")
                .select("*")
                .eq("project_id", project_id)
                .eq("id", passage_id)
                .limit(1)
                .execute()
            )
        )
        return cast(dict[str, Any], result.data[0]) if result.data else None

    async def commit_source_evidence(
        self,
        job_id: str,
        worker_id: str,
        source_id: str,
        chunks: list[dict[str, Any]],
        sha256: str,
        warnings: list[str],
    ) -> bool:
        """Atomically persist passages only while this worker owns the job."""

        result = await asyncio.to_thread(
            lambda: self.rpc(
                "commit_source_evidence",
                {
                    "p_job_id": job_id,
                    "p_worker_id": worker_id,
                    "p_source_id": source_id,
                    "p_chunks": chunks,
                    "p_sha256": sha256,
                    "p_warnings": warnings,
                },
            )
        )
        return bool(result.data)

    async def get_citation_targets(
        self, project_id: str, ids: list[str], *, claims: bool = False
    ) -> list[dict[str, Any]]:
        """Resolve citation identities in the project, never across owners."""

        table = "source_claims" if claims else "source_chunks"
        columns = "id,source_chunk_id" if claims else "id,source_id,page"
        rows: list[dict[str, Any]] = []

        def run(batch: list[str]) -> Any:
            return (
                self._client.table(table)
                .select(columns)
                .eq("project_id", project_id)
                .in_("id", batch)
                .execute()
            )

        for start in range(0, len(ids), 100):
            result = await asyncio.to_thread(run, ids[start : start + 100])
            rows.extend(cast(list[dict[str, Any]], result.data))
        return rows

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

    # ------------------------------------------------------------------ decks

    async def get_deck(self, project_id: str) -> dict[str, Any] | None:
        """Read the project's current deck from the ``decks`` view, or ``None``.

        Since migration 016 ``decks`` is a view of the presentation document's
        head revision (ADR 0001), so this can never return a stale deck. It is a
        read path only; decks are written as revisions through
        :class:`packages.platform.document_store.DocumentStore`.
        """

        result = await asyncio.to_thread(
            lambda: (
                self._client.table("decks")
                .select("*")
                .eq("project_id", project_id)
                .limit(1)
                .execute()
            )
        )
        if not result.data:
            return None
        return cast(dict[str, Any], result.data[0])

    # --------------------------------------------------------- brain sessions

    # The brain editing session (Build 2, Stage 4). One row per project (the
    # ``brain_sessions_project_id_key`` unique constraint), so the session is
    # recoverable from project_id alone. Every write is a compare-and-swap on
    # ``version`` (B1-FIX3); migration 016's trigger refuses any update that does
    # not advance it by one. This layer deals only in JSON-ready values: the
    # bot-side session store owns the (de)serialization and the merge on conflict.
    # ``findings_json`` is never written here, so Stage 5's value is preserved.

    # Every session column EXCEPT the heavy figures_json — the light per-turn read.
    _SESSION_LIGHT_COLUMNS: str = (
        "id,project_id,history_json,sources_json,package,formats_json,"
        "approval_state,pending_action_json,fixes_used,accumulated_cost_usd,"
        "accumulated_image_count,findings_json,revision_id,delivery_notes_json,version,"
        "created_at,updated_at"
    )

    async def insert_brain_session(self, project_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        """Create the project's session at version 0 and return the saved row.

        ``fields`` are JSON-ready column values. A row that already exists for
        the project (another writer created it first) is a version conflict.
        """

        payload: dict[str, Any] = {**fields, "project_id": project_id, "version": 0}
        try:
            result = await asyncio.to_thread(
                lambda: self._client.table("brain_sessions").insert(payload).execute()
            )
        except APIError as exc:
            if _is_session_conflict(exc):
                raise SessionVersionConflictError(project_id) from exc
            raise
        return cast(dict[str, Any], result.data[0])

    async def update_brain_session(
        self, session_id: str, expected_version: int, fields: dict[str, Any]
    ) -> dict[str, Any]:
        """Compare-and-swap the session row; return it at ``expected_version + 1``.

        Writes only ``fields`` (``figures_json`` stays write-once unless passed),
        and only if the row is still at ``expected_version``. Anything else - the
        row moved, or it was replaced - raises :class:`SessionVersionConflictError`
        so the caller reloads and merges instead of overwriting (Codex A2).
        """

        payload: dict[str, Any] = {**fields, "version": expected_version + 1}
        try:
            result = await asyncio.to_thread(
                lambda: (
                    self._client.table("brain_sessions")
                    .update(payload)
                    .eq("id", session_id)
                    .eq("version", expected_version)
                    .execute()
                )
            )
        except APIError as exc:
            if _is_session_conflict(exc):
                raise SessionVersionConflictError(session_id) from exc
            raise
        if not result.data:
            raise SessionVersionConflictError(session_id)
        return cast(dict[str, Any], result.data[0])

    async def delete_brain_session(self, session_id: str, expected_version: int) -> None:
        """Delete the session row only if it is still at ``expected_version``.

        A regeneration replaces the session: the old row goes (its edit deliveries
        keep their history, unattached) and a new one starts the new allowance.
        """

        result = await asyncio.to_thread(
            lambda: (
                self._client.table("brain_sessions")
                .delete()
                .eq("id", session_id)
                .eq("version", expected_version)
                .execute()
            )
        )
        if not result.data:
            raise SessionVersionConflictError(session_id)

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
