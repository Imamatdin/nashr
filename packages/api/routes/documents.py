"""Conflict-safe article document reads, saves, history, and restores."""

from __future__ import annotations

import asyncio
import re
from datetime import datetime
from typing import Any, NoReturn
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response, status
from postgrest.exceptions import APIError
from pydantic import BaseModel, ConfigDict, Field

from packages.api.middleware.auth import Authenticated
from packages.api.routes.projects import owned_project
from packages.api.services.article_document_export import render_article_document_docx
from packages.core.models.document import ArticleDocumentContent

router = APIRouter(prefix="/projects", tags=["documents"])


class InitializeArticleRequest(BaseModel):
    """Initial state for a manually editable article."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=300)
    idempotency_key: str = Field(min_length=1, max_length=128)


class SaveArticleRequest(BaseModel):
    """A compare-and-swap save against the revision the editor loaded."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    base_revision_id: UUID
    idempotency_key: str = Field(min_length=1, max_length=128)
    content: ArticleDocumentContent


class RestoreArticleRequest(BaseModel):
    """Restore historical content as a new revision without erasing history."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    revision_id: UUID
    base_revision_id: UUID
    idempotency_key: str = Field(min_length=1, max_length=128)


class ArticleDocumentView(BaseModel):
    """Current article document and the exact immutable revision it came from."""

    model_config = ConfigDict(extra="forbid")

    document_id: UUID
    revision_id: UUID
    content: ArticleDocumentContent
    updated_at: datetime


class RevisionView(BaseModel):
    """Compact revision metadata for history navigation."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    parent_revision_id: UUID | None
    created_by: UUID | None
    content_hash: str
    created_at: datetime


class RevisionListView(BaseModel):
    """Bounded article revision history."""

    model_config = ConfigDict(extra="forbid")

    revisions: list[RevisionView]


def _view(row: dict[str, Any]) -> ArticleDocumentView:
    return ArticleDocumentView(
        document_id=row["document_id"] if "document_id" in row else row["id"],
        revision_id=row["revision_id"],
        content=ArticleDocumentContent.model_validate(row["content"]),
        updated_at=row["updated_at"],
    )


async def _owned_article(request: Request, project_id: str, user_id: str) -> dict[str, Any]:
    project = await owned_project(request, project_id, user_id)
    if str(project.get("type")) != "article":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="not_article_project")
    return project


def raise_document_commit_error(exc: APIError) -> NoReturn:
    message = str(exc)
    if "stale_revision" in message:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="stale_revision") from exc
    if "document_not_found" in message:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="document_not_found"
        ) from exc
    raise exc


@router.post("/{project_id}/documents/article", response_model=ArticleDocumentView)
async def initialize_article(
    request: Request, project_id: str, body: InitializeArticleRequest, auth: Authenticated
) -> ArticleDocumentView:
    """Create an empty article once; retries return the existing document."""

    await _owned_article(request, project_id, str(auth.user_id))
    content = ArticleDocumentContent(title=body.title)
    row = await request.app.state.db.create_document_if_missing(
        project_id,
        "article",
        content.model_dump(mode="json"),
        str(auth.user_id),
        body.idempotency_key,
    )
    return _view(row)


@router.get("/{project_id}/documents/article", response_model=ArticleDocumentView)
async def get_article(
    request: Request, project_id: str, auth: Authenticated
) -> ArticleDocumentView:
    """Return the current article revision for an owned article project."""

    await _owned_article(request, project_id, str(auth.user_id))
    row = await request.app.state.db.get_document(project_id, "article")
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="document_not_found")
    return _view(row)


@router.get("/{project_id}/documents/article/export.docx")
async def export_article_docx(request: Request, project_id: str, auth: Authenticated) -> Response:
    """Download the current article head as an editable Word document."""

    await _owned_article(request, project_id, str(auth.user_id))
    row = await request.app.state.db.get_document(project_id, "article")
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="document_not_found")
    content = ArticleDocumentContent.model_validate(row["content"])
    payload = await asyncio.to_thread(render_article_document_docx, content)
    safe_ascii = re.sub(r"[^A-Za-z0-9._-]+", "-", content.title).strip("-.")[:80]
    fallback = f"{safe_ascii or 'article'}.docx"
    encoded = quote(f"{content.title[:120]}.docx", safe="")
    return Response(
        content=payload,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Content-Disposition": (
                f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{encoded}"
            )
        },
    )


@router.put("/{project_id}/documents/article", response_model=ArticleDocumentView)
async def save_article(
    request: Request, project_id: str, body: SaveArticleRequest, auth: Authenticated
) -> ArticleDocumentView:
    """Save a revision, rejecting an editor whose base revision is stale."""

    await _owned_article(request, project_id, str(auth.user_id))
    current = await request.app.state.db.get_document(project_id, "article")
    if current is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="document_not_found")
    try:
        row = await request.app.state.db.commit_document_revision(
            str(current["id"]),
            str(body.base_revision_id),
            body.content.model_dump(mode="json"),
            str(auth.user_id),
            body.idempotency_key,
        )
    except APIError as exc:
        raise_document_commit_error(exc)
    return _view(row)


@router.get("/{project_id}/documents/article/revisions", response_model=RevisionListView)
async def list_article_revisions(
    request: Request, project_id: str, auth: Authenticated
) -> RevisionListView:
    """Return newest-first revision metadata for the owned article."""

    await _owned_article(request, project_id, str(auth.user_id))
    current = await request.app.state.db.get_document(project_id, "article")
    if current is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="document_not_found")
    rows = await request.app.state.db.list_document_revisions(str(current["id"]))
    return RevisionListView(revisions=[RevisionView.model_validate(row) for row in rows])


@router.post("/{project_id}/documents/article/restore", response_model=ArticleDocumentView)
async def restore_article(
    request: Request, project_id: str, body: RestoreArticleRequest, auth: Authenticated
) -> ArticleDocumentView:
    """Restore an old snapshot by committing it as a new head revision."""

    await _owned_article(request, project_id, str(auth.user_id))
    current = await request.app.state.db.get_document(project_id, "article")
    if current is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="document_not_found")
    previous = await request.app.state.db.get_document_revision(
        str(current["id"]), str(body.revision_id)
    )
    if previous is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="revision_not_found")
    content = ArticleDocumentContent.model_validate(previous["content"])
    try:
        row = await request.app.state.db.commit_document_revision(
            str(current["id"]),
            str(body.base_revision_id),
            content.model_dump(mode="json"),
            str(auth.user_id),
            body.idempotency_key,
        )
    except APIError as exc:
        raise_document_commit_error(exc)
    return _view(row)
