"""Value types for canonical documents (ADR 0001): kinds, outcomes, records, actors.

Enum values mirror the migration-016 CHECK constraints. Revision ``content`` is the
one raw-JSON field: a legacy import may not validate against today's content
models and must still be kept and shown.
"""

from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

CONTENT_SCHEMA_VERSION: int = 1

_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


class DocumentKind(StrEnum):
    """documents.kind (migration 011 CHECK)."""

    ARTICLE = "article"
    PRESENTATION = "presentation"


class RevisionKind(StrEnum):
    """document_revisions.kind (migration 016 CHECK)."""

    GENERATION = "generation"
    REGENERATION = "regeneration"
    MANUAL = "manual"
    AUTOSAVE = "autosave"
    AI_EDIT = "ai_edit"
    BOT_EDIT = "bot_edit"
    IMPORT = "import"
    RESTORE = "restore"


class CommitStatus(StrEnum):
    """What commit_revision / accept_proposal did."""

    COMMITTED = "committed"
    DUPLICATE = "duplicate"
    UNCHANGED = "unchanged"
    PROPOSED = "proposed"
    CONFLICT = "conflict"


class ProposalStatus(StrEnum):
    """revision_proposals.status (migration 016 CHECK)."""

    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class ExportFileFormat(StrEnum):
    """revision_exports.format: the file extension of a rendered output."""

    HTML = "html"
    PPTX = "pptx"
    PDF = "pdf"


ERROR_CODES: frozenset[str] = frozenset(
    {
        "document_not_found",
        "not_document_owner",
        "actor_mismatch",
        "actor_job_not_active",
        "kind_not_allowed",
        "invalid_actor",
        "invalid_revision_kind",
        "invalid_idempotency_key",
        "unsupported_schema_version",
        "invalid_content",
        "content_too_large",
        "idempotency_key_reused",
        "invalid_document_kind",
        "document_kind_mismatch",
        "proposal_not_found",
        "proposal_not_pending",
        "proposal_schema_mismatch",
        "claim_lost",
        "claim_expired",
        "worker_must_finish_job",
        "job_must_finish_with_revision",
        "invalid_render_formats",
        "revision_not_found",
        "job_revision_mismatch",
        "invalid_storage_key",
        "export_conflict",
        "job_type_not_allowed",
        "renderer_version_mismatch",
        "format_not_requested",
        "invalid_citation",
    }
)


class DocumentStoreError(Exception):
    """A migration-016 function refused the operation; ``code`` names why."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def user_actor(user_id: str) -> str:
    """Actor string for an API call made on behalf of ``user_id``."""

    value = str(user_id).lower()
    if not _UUID_RE.match(value):
        raise ValueError(f"user actor must be a uuid, got {user_id!r}")
    return value


def worker_actor(job_id: str) -> str:
    """Actor string for a queue worker running ``job_id``."""

    return f"worker:{user_actor(job_id)}"


def bot_actor(telegram_id: int) -> str:
    """Actor string for the Telegram bot acting for ``telegram_id``."""

    if telegram_id <= 0:
        raise ValueError("telegram id must be positive")
    return f"bot:{telegram_id}"


class CommitOutcome(BaseModel):
    """The row commit_revision / accept_proposal returned."""

    model_config = ConfigDict(extra="forbid")

    status: CommitStatus
    document_id: str
    revision_id: str | None = None
    head_revision_id: str | None = None
    proposal_id: str | None = None


class RevisionRecord(BaseModel):
    """One immutable revision; ``content`` is present only when requested."""

    model_config = ConfigDict(extra="ignore")

    id: str
    document_id: str
    parent_revision_id: str | None = None
    created_by: str | None = None
    actor: str
    kind: RevisionKind
    schema_version: int
    content_sha256: str
    created_at: datetime
    accepted_from_proposal_id: str | None = None
    content: dict[str, Any] | None = None


class DocumentHead(BaseModel):
    """A document and the content of its head revision."""

    model_config = ConfigDict(extra="forbid")

    document_id: str
    project_id: str
    kind: DocumentKind
    revision: RevisionRecord
    updated_at: datetime

    @property
    def revision_id(self) -> str:
        """Id of the head revision."""

        return self.revision.id

    @property
    def content(self) -> dict[str, Any]:
        """Raw head content (always loaded for a head)."""

        return self.revision.content or {}


class ProposalRecord(BaseModel):
    """A stored losing write awaiting the owner's decision."""

    model_config = ConfigDict(extra="ignore")

    id: str
    document_id: str
    base_revision_id: str | None = None
    kind: RevisionKind
    actor: str
    status: ProposalStatus
    schema_version: int
    content_sha256: str
    source_job_id: str | None = None
    created_at: datetime
    resolved_at: datetime | None = None
    resolved_by: str | None = None
    accepted_revision_id: str | None = None
    content: dict[str, Any] | None = None


class ExportRecord(BaseModel):
    """One registered, immutable rendered file."""

    model_config = ConfigDict(extra="ignore")

    revision_id: str
    format: ExportFileFormat
    renderer_version: str
    storage_key: str
    sha256: str
    byte_size: int
    page_count: int | None = None
    created_by_job: str | None = None
    created_at: datetime


class ExportRegistration(BaseModel):
    """What register_export recorded: this call's file, or the first writer's."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["registered", "existing"]
    storage_key: str
    sha256: str
    byte_size: int


def export_storage_key(
    document_id: str,
    revision_id: str,
    renderer_version: str,
    file_format: ExportFileFormat,
    sha256: str,
) -> str:
    """The only key an export may live at (checked again by register_export)."""

    return (
        f"exports/{document_id}/{revision_id}/{renderer_version}/"
        f"{file_format.value}/{sha256}.{file_format.value}"
    )
