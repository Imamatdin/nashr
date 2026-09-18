"""Conflict-safe direct editing and rendering for presentation design documents."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status
from postgrest.exceptions import APIError
from pydantic import BaseModel, ConfigDict, Field

from packages.api.middleware.auth import Authenticated
from packages.api.routes.documents import (
    RevisionListView,
    RevisionView,
    raise_document_commit_error,
)
from packages.api.routes.projects import owned_project
from packages.core.models.presentation import DeckSpec
from packages.platform.jobs import DuplicateActiveJobError, JobType
from packages.platform.rate_limit import DESIGN_RENDER_ACTION

router = APIRouter(prefix="/projects", tags=["design"])


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


def _view(row: dict[str, Any]) -> DesignDocumentView:
    return DesignDocumentView(
        document_id=row["document_id"] if "document_id" in row else row["id"],
        revision_id=row["revision_id"],
        content=DeckSpec.model_validate(row["content"]),
        updated_at=row["updated_at"],
    )


def _document_id(row: dict[str, Any]) -> str:
    return str(row["document_id"] if "document_id" in row else row["id"])


async def _owned_presentation(request: Request, project_id: str, user_id: str) -> dict[str, Any]:
    project = await owned_project(request, project_id, user_id)
    if str(project.get("type")) != "presentation":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="not_presentation_project")
    return project


async def current_or_import_design(
    request: Request, project_id: str, user_id: str
) -> dict[str, Any]:
    current = await request.app.state.db.get_document(project_id, "presentation")
    if current is not None:
        return current
    await refuse_if_ai_is_writing(request, project_id)
    deck = await request.app.state.db.get_deck(project_id)
    if deck is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="deck_not_ready")
    content = DeckSpec.model_validate(deck["deck_json"])
    return await request.app.state.db.create_document_if_missing(
        project_id,
        "presentation",
        content.model_dump(mode="json"),
        user_id,
        f"import:{project_id}",
    )


async def refuse_if_ai_is_writing(request: Request, project_id: str) -> None:
    """Prevent a manual write while generation or AI editing owns the deck."""

    for job_type in (JobType.PRESENTATION_GENERATION, JobType.PRESENTATION_EDIT):
        active = await request.app.state.job_queue.get_active_job(project_id, job_type)
        if active is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "reason": "design_busy",
                    "job_id": active.id,
                    "job_type": active.job_type.value,
                },
            )


@router.get("/{project_id}/design", response_model=DesignDocumentView)
async def get_design(request: Request, project_id: str, auth: Authenticated) -> DesignDocumentView:
    """Open the editable deck, importing the current generated deck once."""

    user_id = str(auth.user_id)
    await _owned_presentation(request, project_id, user_id)
    return _view(await current_or_import_design(request, project_id, user_id))


@router.put("/{project_id}/design", response_model=DesignDocumentView)
async def save_design(
    request: Request, project_id: str, body: SaveDesignRequest, auth: Authenticated
) -> DesignDocumentView:
    """Persist direct slide edits without running a model or charging credits."""

    user_id = str(auth.user_id)
    await _owned_presentation(request, project_id, user_id)
    await refuse_if_ai_is_writing(request, project_id)
    if body.content.project_id != project_id:
        raise HTTPException(status_code=422, detail="project_id_mismatch")
    current = await current_or_import_design(request, project_id, user_id)
    try:
        row = await request.app.state.db.commit_document_revision(
            _document_id(current),
            str(body.base_revision_id),
            body.content.model_dump(mode="json"),
            user_id,
            body.idempotency_key,
        )
    except APIError as exc:
        raise_document_commit_error(exc)
    return _view(row)


@router.get("/{project_id}/design/revisions", response_model=RevisionListView)
async def list_design_revisions(
    request: Request, project_id: str, auth: Authenticated
) -> RevisionListView:
    """Return newest-first revision metadata for an owned presentation."""

    user_id = str(auth.user_id)
    await _owned_presentation(request, project_id, user_id)
    current = await current_or_import_design(request, project_id, user_id)
    rows = await request.app.state.db.list_document_revisions(_document_id(current))
    return RevisionListView(revisions=[RevisionView.model_validate(row) for row in rows])


@router.post("/{project_id}/design/restore", response_model=DesignDocumentView)
async def restore_design(
    request: Request, project_id: str, body: RestoreDesignRequest, auth: Authenticated
) -> DesignDocumentView:
    """Restore an old deck snapshot by committing it as a new head revision."""

    user_id = str(auth.user_id)
    await _owned_presentation(request, project_id, user_id)
    await refuse_if_ai_is_writing(request, project_id)
    current = await current_or_import_design(request, project_id, user_id)
    previous = await request.app.state.db.get_document_revision(
        _document_id(current), str(body.revision_id)
    )
    if previous is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="revision_not_found")
    content = DeckSpec.model_validate(previous["content"])
    if content.project_id != project_id:
        raise HTTPException(status_code=422, detail="project_id_mismatch")
    try:
        row = await request.app.state.db.commit_document_revision(
            _document_id(current),
            str(body.base_revision_id),
            content.model_dump(mode="json"),
            user_id,
            body.idempotency_key,
        )
    except APIError as exc:
        raise_document_commit_error(exc)
    return _view(row)


@router.post("/{project_id}/design/render", response_model=RenderDesignView)
async def render_design(
    request: Request, project_id: str, body: RenderDesignRequest, auth: Authenticated
) -> RenderDesignView:
    """Queue export rendering for the exact current design revision."""

    user_id = str(auth.user_id)
    await _owned_presentation(request, project_id, user_id)
    await refuse_if_ai_is_writing(request, project_id)
    current = await current_or_import_design(request, project_id, user_id)
    if str(current["revision_id"]) != str(body.revision_id):
        raise HTTPException(status_code=409, detail="stale_revision")
    decision = await request.app.state.rate_limiter.check(
        action=DESIGN_RENDER_ACTION,
        user_id=user_id,
        ip=request.client.host if request.client else "unknown",
    )
    if not decision.allowed:
        raise HTTPException(status_code=429, detail="rate_limited")
    existing = await request.app.state.job_queue.get_active_job(
        project_id, JobType.PRESENTATION_RENDER
    )
    if existing is not None:
        return RenderDesignView(job_id=existing.id, status=existing.status.value, existing=True)
    try:
        job = await request.app.state.job_queue.enqueue(
            project_id=project_id,
            user_id=user_id,
            job_type=JobType.PRESENTATION_RENDER,
            payload={
                "document_id": _document_id(current),
                "revision_id": str(body.revision_id),
            },
        )
    except DuplicateActiveJobError as exc:
        job = exc.existing
        return RenderDesignView(job_id=job.id, status=job.status.value, existing=True)
    return RenderDesignView(job_id=job.id, status=job.status.value)
