"""Conflict-safe direct editing and rendering for presentation design documents.

Every write is one ``commit_revision`` call (ADR 0001). The database arbitrates
concurrency: a manual save on a stale base gets a 409 carrying the current head,
and an AI edit racing it becomes a proposal. Nothing here locks out a writer.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from packages.api.middleware.auth import Authenticated
from packages.api.routes.projects import owned_project
from packages.api.services.revisions import (
    RevisionListView,
    RevisionView,
    document_store,
    raise_store_error,
    stale_revision,
)
from packages.bot.orchestrators.deck_revisions import file_formats
from packages.core.enums import ExportFormat
from packages.core.models.presentation import DeckSpec
from packages.platform.document_models import (
    CommitOutcome,
    CommitStatus,
    DocumentHead,
    DocumentKind,
    DocumentStoreError,
    RevisionKind,
    user_actor,
)
from packages.platform.exports import renderer_version
from packages.platform.jobs import DuplicateActiveJobError, JobType
from packages.platform.rate_limit import DESIGN_RENDER_ACTION

router = APIRouter(prefix="/projects", tags=["design"])

_RENDER_FORMATS: list[ExportFormat] = [
    ExportFormat.HTML,
    ExportFormat.PPTX_EDITABLE,
    ExportFormat.PDF,
]


class SaveKind(StrEnum):
    """Which human write this is; both commit identically, history tells them apart."""

    MANUAL = "manual"
    AUTOSAVE = "autosave"


class DesignDocumentView(BaseModel):
    """The editable deck and exact immutable revision shown in the browser."""

    model_config = ConfigDict(extra="forbid")

    document_id: UUID
    revision_id: UUID
    content: DeckSpec
    updated_at: datetime


class SaveDesignRequest(BaseModel):
    """Compare-and-swap update for a manually edited deck."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    base_revision_id: UUID
    idempotency_key: str = Field(min_length=1, max_length=128)
    content: DeckSpec
    kind: SaveKind = SaveKind.MANUAL


class RenderDesignRequest(BaseModel):
    """Render one exact saved design revision."""

    model_config = ConfigDict(extra="forbid")

    revision_id: UUID


class RestoreDesignRequest(BaseModel):
    """Restore historical deck content as a new immutable head revision."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    revision_id: UUID
    base_revision_id: UUID
    idempotency_key: str = Field(min_length=1, max_length=128)


class RenderDesignView(BaseModel):
    """Queue acknowledgement consumed by the design workspace."""

    model_config = ConfigDict(extra="forbid")

    job_id: str
    status: str
    existing: bool = False
    revision_id: UUID
    renderer_version: str


def _deck(content: dict[str, Any], revision_id: str) -> DeckSpec:
    try:
        return DeckSpec.model_validate(content)
    except ValidationError as exc:
        # A legacy import kept verbatim (migration 016): readable as history,
        # not editable until a valid revision replaces it.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"reason": "legacy_invalid", "revision_id": revision_id},
        ) from exc


def _head_view(head: DocumentHead) -> DesignDocumentView:
    return DesignDocumentView(
        document_id=UUID(head.document_id),
        revision_id=UUID(head.revision_id),
        content=_deck(head.content, head.revision_id),
        updated_at=head.updated_at,
    )


async def _owned_presentation(request: Request, project_id: str, user_id: str) -> dict[str, Any]:
    project = await owned_project(request, project_id, user_id)
    if str(project.get("type")) not in ("presentation", "research_package"):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="not_presentation_project")
    return project


async def _head(request: Request, project_id: str) -> DocumentHead:
    head = await document_store(request).head(project_id, DocumentKind.PRESENTATION)
    if head is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="deck_not_ready")
    return head


async def _committed_view(request: Request, outcome: CommitOutcome) -> DesignDocumentView:
    if outcome.status is CommitStatus.CONFLICT or outcome.revision_id is None:
        raise stale_revision(outcome.head_revision_id)
    # The revision this call produced (or matched), not whatever the head is now.
    record = await document_store(request).revision(outcome.document_id, outcome.revision_id)
    if record is None or record.content is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="revision_not_found")
    return DesignDocumentView(
        document_id=UUID(outcome.document_id),
        revision_id=UUID(record.id),
        content=_deck(record.content, record.id),
        updated_at=record.created_at,
    )


async def _commit(
    request: Request,
    head: DocumentHead,
    base_revision_id: UUID,
    content: DeckSpec,
    *,
    kind: RevisionKind,
    user_id: str,
    idempotency_key: str,
) -> CommitOutcome:
    try:
        return await document_store(request).commit(
            head.document_id,
            str(base_revision_id),
            content.model_dump(mode="json"),
            kind=kind,
            actor=user_actor(user_id),
            idempotency_key=idempotency_key,
        )
    except DocumentStoreError as exc:
        raise_store_error(exc)


@router.get("/{project_id}/design", response_model=DesignDocumentView)
async def get_design(request: Request, project_id: str, auth: Authenticated) -> DesignDocumentView:
    """Open the head revision of the project's deck."""

    await _owned_presentation(request, project_id, str(auth.user_id))
    return _head_view(await _head(request, project_id))


@router.put("/{project_id}/design", response_model=DesignDocumentView)
async def save_design(
    request: Request, project_id: str, body: SaveDesignRequest, auth: Authenticated
) -> DesignDocumentView:
    """Commit direct slide edits; 409 with the current head when the base is stale."""

    user_id = str(auth.user_id)
    await _owned_presentation(request, project_id, user_id)
    if body.content.project_id != project_id:
        raise HTTPException(status_code=422, detail="project_id_mismatch")
    head = await _head(request, project_id)
    outcome = await _commit(
        request,
        head,
        body.base_revision_id,
        body.content,
        kind=RevisionKind(body.kind.value),
        user_id=user_id,
        idempotency_key=body.idempotency_key,
    )
    return await _committed_view(request, outcome)


@router.get("/{project_id}/design/revisions", response_model=RevisionListView)
async def list_design_revisions(
    request: Request, project_id: str, auth: Authenticated
) -> RevisionListView:
    """Return newest-first revision metadata for an owned presentation."""

    await _owned_presentation(request, project_id, str(auth.user_id))
    head = await _head(request, project_id)
    records = await document_store(request).list_revisions(head.document_id)
    return RevisionListView(revisions=[RevisionView.of(record) for record in records])


@router.post("/{project_id}/design/restore", response_model=DesignDocumentView)
async def restore_design(
    request: Request, project_id: str, body: RestoreDesignRequest, auth: Authenticated
) -> DesignDocumentView:
    """Restore an old deck snapshot by committing it as a new head revision."""

    user_id = str(auth.user_id)
    await _owned_presentation(request, project_id, user_id)
    head = await _head(request, project_id)
    previous = await document_store(request).revision(head.document_id, str(body.revision_id))
    if previous is None or previous.content is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="revision_not_found")
    content = _deck(previous.content, previous.id)
    if content.project_id != project_id:
        raise HTTPException(status_code=422, detail="project_id_mismatch")
    outcome = await _commit(
        request,
        head,
        body.base_revision_id,
        content,
        kind=RevisionKind.RESTORE,
        user_id=user_id,
        idempotency_key=body.idempotency_key,
    )
    return await _committed_view(request, outcome)


@router.post("/{project_id}/design/render", response_model=RenderDesignView)
async def render_design(
    request: Request, project_id: str, body: RenderDesignRequest, auth: Authenticated
) -> RenderDesignView:
    """Queue rendering of one exact revision; an identical active render is reused."""

    user_id = str(auth.user_id)
    await _owned_presentation(request, project_id, user_id)
    found = await document_store(request).revision_in_project(project_id, str(body.revision_id))
    if found is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="revision_not_found")
    revision = found[1]
    decision = await request.app.state.rate_limiter.check(
        action=DESIGN_RENDER_ACTION,
        user_id=user_id,
        ip=request.client.host if request.client else "unknown",
    )
    if not decision.allowed:
        raise HTTPException(status_code=429, detail="rate_limited")
    version = renderer_version()
    formats = file_formats(_RENDER_FORMATS)
    existing = await request.app.state.job_queue.get_active_render_job(
        revision.id, version, formats
    )
    if existing is not None:
        return RenderDesignView(
            job_id=existing.id,
            status=existing.status.value,
            existing=True,
            revision_id=UUID(revision.id),
            renderer_version=version,
        )
    try:
        job = await request.app.state.job_queue.enqueue(
            project_id=project_id,
            user_id=user_id,
            job_type=JobType.PRESENTATION_RENDER,
            payload={
                "document_id": revision.document_id,
                "revision_id": revision.id,
                "renderer_version": version,
                "formats": formats,
            },
        )
    except DuplicateActiveJobError as exc:
        job = exc.existing
        return RenderDesignView(
            job_id=job.id,
            status=job.status.value,
            existing=True,
            revision_id=UUID(revision.id),
            renderer_version=version,
        )
    return RenderDesignView(
        job_id=job.id,
        status=job.status.value,
        revision_id=UUID(revision.id),
        renderer_version=version,
    )
