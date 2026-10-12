"""Typed gateway to canonical documents, revisions, proposals and exports (ADR 0001).

Every write is exactly one SQL function from migration 016; this module never
writes a table. Reads go through the service role and are scoped by the caller,
which has already proven project ownership. Rows are parsed into the models in
:mod:`packages.platform.document_models` on arrival.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Callable
from typing import Any, cast

from postgrest.exceptions import APIError

from packages.platform.database import DatabaseClient
from packages.platform.document_models import (
    CONTENT_SCHEMA_VERSION,
    ERROR_CODES,
    CommitOutcome,
    DocumentHead,
    DocumentKind,
    DocumentStoreError,
    ExportFileFormat,
    ExportRecord,
    ExportRegistration,
    ProposalRecord,
    ProposalStatus,
    RevisionKind,
    RevisionRecord,
)

_REVISION_COLUMNS = (
    "id,document_id,parent_revision_id,created_by,actor,kind,schema_version,"
    "content_sha256,created_at,accepted_from_proposal_id"
)
_PROPOSAL_COLUMNS = (
    "id,document_id,base_revision_id,kind,actor,status,schema_version,content_sha256,"
    "source_job_id,created_at,resolved_at,resolved_by,accepted_revision_id"
)


def _translate(exc: APIError) -> DocumentStoreError | None:
    """Map a PostgREST error raised by our SQL functions onto its code."""

    text = f"{exc.message or ''} {exc}"
    for code in ERROR_CODES:
        if re.search(rf"\b{code}\b", text):
            return DocumentStoreError(code)
    return None


class DocumentStore:
    """Calls the migration-016 functions and reads their tables."""

    def __init__(self, db: DatabaseClient) -> None:
        self._db = db

    # ---------------------------------------------------------------- writes

    async def _rpc(self, fn: str, params: dict[str, Any]) -> Any:
        try:
            result = await asyncio.to_thread(self._db.rpc, fn, params)
        except APIError as exc:
            translated = _translate(exc)
            if translated is not None:
                raise translated from exc
            raise
        return result.data

    async def ensure_document(self, project_id: str, kind: DocumentKind, actor: str) -> str:
        """Create the project's document of ``kind`` if missing; return its id."""

        data = await self._rpc(
            "ensure_document", {"p_project_id": project_id, "p_kind": kind.value, "p_actor": actor}
        )
        return str(data)

    async def commit(
        self,
        document_id: str,
        base_revision_id: str | None,
        content: dict[str, Any],
        *,
        kind: RevisionKind,
        actor: str,
        idempotency_key: str,
        schema_version: int = CONTENT_SCHEMA_VERSION,
    ) -> CommitOutcome:
        """Compare-and-swap a new revision onto the head (see commit_revision)."""

        rows = await self._rpc(
            "commit_revision",
            {
                "p_document_id": document_id,
                "p_base_revision_id": base_revision_id,
                "p_content": content,
                "p_kind": kind.value,
                "p_schema_version": schema_version,
                "p_actor": actor,
                "p_idempotency_key": idempotency_key,
            },
        )
        return _outcome(rows)

    async def finish_generation_job(
        self,
        *,
        job_id: str,
        worker_id: str,
        claim_token: int,
        base_revision_id: str | None,
        content: dict[str, Any],
        kind: RevisionKind,
        idempotency_key: str,
        renderer_version: str | None,
        render_formats: list[str],
        schema_version: int = CONTENT_SCHEMA_VERSION,
    ) -> CommitOutcome:
        """Commit a job's deck and complete the job in one claim-fenced transaction.

        Raises ``claim_lost``/``claim_expired`` when the caller no longer holds the
        job; then nothing was written. A committed revision gets a queued render
        job for ``render_formats`` in the same transaction.
        """

        rows = await self._rpc(
            "finish_generation_job",
            {
                "p_job_id": job_id,
                "p_worker_id": worker_id,
                "p_claim_token": claim_token,
                "p_base_revision_id": base_revision_id,
                "p_content": content,
                "p_kind": kind.value,
                "p_schema_version": schema_version,
                "p_idempotency_key": idempotency_key,
                "p_renderer_version": renderer_version,
                "p_render_formats": render_formats,
            },
        )
        return _outcome(rows)

    async def accept_proposal(
        self, proposal_id: str, expected_head_revision_id: str | None, actor: str, key: str
    ) -> CommitOutcome:
        """Replace the head the user saw with the proposal's content."""

        rows = await self._rpc(
            "accept_proposal",
            {
                "p_proposal_id": proposal_id,
                "p_expected_head_revision_id": expected_head_revision_id,
                "p_actor": actor,
                "p_idempotency_key": key,
            },
        )
        return _outcome(rows)

    async def reject_proposal(self, proposal_id: str, actor: str) -> None:
        """Mark a pending proposal rejected (idempotent)."""

        await self._rpc("reject_proposal", {"p_proposal_id": proposal_id, "p_actor": actor})

    async def register_export(
        self,
        *,
        job_id: str,
        worker_id: str,
        claim_token: int,
        revision_id: str,
        file_format: ExportFileFormat,
        renderer_version: str,
        storage_key: str,
        sha256: str,
        byte_size: int,
        page_count: int | None,
    ) -> ExportRegistration:
        """Record a verified upload under the render job's claim.

        ``registered``: this file is now the export. ``existing``: another render
        registered this (revision, format, renderer) first; the returned row is the
        export, and this call's upload is an orphan for the sweep.
        """

        data = await self._rpc(
            "register_export",
            {
                "p_job_id": job_id,
                "p_worker_id": worker_id,
                "p_claim_token": claim_token,
                "p_revision_id": revision_id,
                "p_format": file_format.value,
                "p_renderer_version": renderer_version,
                "p_storage_key": storage_key,
                "p_sha256": sha256,
                "p_byte_size": byte_size,
                "p_page_count": page_count,
            },
        )
        rows = cast(list[dict[str, Any]], data if isinstance(data, list) else [data])
        if not rows:
            raise DocumentStoreError("revision_not_found")
        return ExportRegistration.model_validate(rows[0])

    async def record_validation(
        self, revision_id: str, validator: str, valid: bool, detail: str | None
    ) -> str:
        """Write-once validation verdict for a revision; ``recorded`` or ``exists``."""

        data = await self._rpc(
            "record_revision_validation",
            {
                "p_revision_id": revision_id,
                "p_validator": validator,
                "p_status": "valid" if valid else "legacy_invalid",
                "p_detail": detail,
            },
        )
        return str(data)

    # ----------------------------------------------------------------- reads

    async def _rows(self, table: str, build: Callable[[Any], Any]) -> list[dict[str, Any]]:
        def run() -> Any:
            return build(self._db._query(table)).execute()  # pyright: ignore[reportPrivateUsage]

        result = await asyncio.to_thread(run)
        return cast(list[dict[str, Any]], list(result.data or []))

    async def document_id(self, project_id: str, kind: DocumentKind) -> str | None:
        """The project's document id of ``kind``, or None."""

        rows = await self._rows(
            "documents",
            lambda q: q.select("id").eq("project_id", project_id).eq("kind", kind.value).limit(1),
        )
        return str(rows[0]["id"]) if rows else None

    async def head(self, project_id: str, kind: DocumentKind) -> DocumentHead | None:
        """The document and its head content, or None when there is no head."""

        rows = await self._rows(
            "documents",
            lambda q: q.select("*").eq("project_id", project_id).eq("kind", kind.value).limit(1),
        )
        if not rows or rows[0].get("head_revision_id") is None:
            return None
        document = rows[0]
        revision = await self.revision(str(document["id"]), str(document["head_revision_id"]))
        if revision is None:
            return None
        return DocumentHead(
            document_id=str(document["id"]),
            project_id=str(document["project_id"]),
            kind=DocumentKind(str(document["kind"])),
            revision=revision,
            updated_at=document["updated_at"],
        )

    async def revision(self, document_id: str, revision_id: str) -> RevisionRecord | None:
        """One revision with content, constrained to ``document_id``."""

        rows = await self._rows(
            "document_revisions",
            lambda q: (
                q.select(f"{_REVISION_COLUMNS},content")
                .eq("document_id", document_id)
                .eq("id", revision_id)
                .limit(1)
            ),
        )
        return RevisionRecord.model_validate(rows[0]) if rows else None

    async def revision_in_project(
        self, project_id: str, revision_id: str
    ) -> tuple[DocumentHead | None, RevisionRecord] | None:
        """A revision (with content) that belongs to ``project_id``, plus that document's head."""

        rows = await self._rows(
            "document_revisions",
            lambda q: q.select(f"{_REVISION_COLUMNS},content").eq("id", revision_id).limit(1),
        )
        if not rows:
            return None
        revision = RevisionRecord.model_validate(rows[0])
        documents = await self._rows(
            "documents", lambda q: q.select("*").eq("id", revision.document_id).limit(1)
        )
        if not documents or str(documents[0]["project_id"]) != project_id:
            return None
        head = await self.head(project_id, DocumentKind(str(documents[0]["kind"])))
        return head, revision

    async def list_revisions(self, document_id: str, limit: int = 50) -> list[RevisionRecord]:
        """Revision metadata (no content), newest first."""

        rows = await self._rows(
            "document_revisions",
            lambda q: (
                q.select(_REVISION_COLUMNS)
                .eq("document_id", document_id)
                .order("created_at", desc=True)
                .limit(limit)
            ),
        )
        return [RevisionRecord.model_validate(row) for row in rows]

    async def list_proposals(
        self, document_id: str, status: ProposalStatus | None = ProposalStatus.PENDING
    ) -> list[ProposalRecord]:
        """Proposal metadata (no content), newest first."""

        def build(q: Any) -> Any:
            query = q.select(_PROPOSAL_COLUMNS).eq("document_id", document_id)
            if status is not None:
                query = query.eq("status", status.value)
            return query.order("created_at", desc=True).limit(50)

        rows = await self._rows("revision_proposals", build)
        return [ProposalRecord.model_validate(row) for row in rows]

    async def proposal(self, document_id: str, proposal_id: str) -> ProposalRecord | None:
        """One proposal with content, constrained to ``document_id``."""

        rows = await self._rows(
            "revision_proposals",
            lambda q: (
                q.select(f"{_PROPOSAL_COLUMNS},content")
                .eq("document_id", document_id)
                .eq("id", proposal_id)
                .limit(1)
            ),
        )
        return ProposalRecord.model_validate(rows[0]) if rows else None

    async def exports(self, revision_ids: list[str]) -> list[ExportRecord]:
        """Every registered export of the given revisions, newest first."""

        if not revision_ids:
            return []
        rows = await self._rows(
            "revision_exports",
            lambda q: q.select("*").in_("revision_id", revision_ids).order("created_at", desc=True),
        )
        return [ExportRecord.model_validate(row) for row in rows]


def _outcome(rows: Any) -> CommitOutcome:
    data = cast(list[dict[str, Any]], rows if isinstance(rows, list) else [rows])
    if not data:
        raise DocumentStoreError("document_not_found")
    return CommitOutcome.model_validate(
        {key: (str(value) if value is not None else None) for key, value in data[0].items()}
    )
