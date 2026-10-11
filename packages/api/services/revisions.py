"""Shared API views and error mapping for revisioned documents (ADR 0001)."""

from __future__ import annotations

from datetime import datetime
from typing import NoReturn
from uuid import UUID

from fastapi import HTTPException, Request, status
from pydantic import BaseModel, ConfigDict

from packages.platform.document_models import (
    DocumentStoreError,
    RevisionKind,
    RevisionRecord,
)
from packages.platform.document_store import DocumentStore

_STATUS_BY_CODE: dict[str, int] = {
    "document_not_found": status.HTTP_404_NOT_FOUND,
    "revision_not_found": status.HTTP_404_NOT_FOUND,
    "proposal_not_found": status.HTTP_404_NOT_FOUND,
    "not_document_owner": status.HTTP_403_FORBIDDEN,
    "actor_mismatch": status.HTTP_403_FORBIDDEN,
    "kind_not_allowed": status.HTTP_403_FORBIDDEN,
    "idempotency_key_reused": status.HTTP_409_CONFLICT,
    "proposal_not_pending": status.HTTP_409_CONFLICT,
    "proposal_schema_mismatch": status.HTTP_409_CONFLICT,
    "document_kind_mismatch": status.HTTP_409_CONFLICT,
    "content_too_large": status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
    "unsupported_schema_version": status.HTTP_422_UNPROCESSABLE_ENTITY,
    "invalid_content": status.HTTP_422_UNPROCESSABLE_ENTITY,
}


class RevisionView(BaseModel):
    """Compact revision metadata for history navigation."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    parent_revision_id: UUID | None
    created_by: UUID | None
    actor: str
    kind: RevisionKind
    schema_version: int
    content_sha256: str
    created_at: datetime
    accepted_from_proposal_id: UUID | None = None

    @classmethod
    def of(cls, record: RevisionRecord) -> RevisionView:
        """Project a stored revision onto the wire shape."""

        return cls.model_validate(record.model_dump(exclude={"content", "document_id"}))


class RevisionListView(BaseModel):
    """Bounded revision history, newest first."""

    model_config = ConfigDict(extra="forbid")

    revisions: list[RevisionView]


def document_store(request: Request) -> DocumentStore:
    """The app's document gateway."""

    return request.app.state.documents


def raise_store_error(exc: DocumentStoreError) -> NoReturn:
    """Turn a refused SQL operation into its HTTP answer."""

    if exc.code == "invalid_citation":
        raise HTTPException(status_code=422, detail="citation_target_not_found") from exc
    code = _STATUS_BY_CODE.get(exc.code, status.HTTP_400_BAD_REQUEST)
    raise HTTPException(status_code=code, detail={"reason": exc.code}) from exc


def stale_revision(head_revision_id: str | None) -> HTTPException:
    """The 409 a writer gets when its base is no longer the head; carries the head."""

    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"reason": "stale_revision", "head_revision_id": head_revision_id},
    )


__all__ = [
    "RevisionListView",
    "RevisionView",
    "document_store",
    "raise_store_error",
    "stale_revision",
]
