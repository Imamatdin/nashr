"""Conflict-safe article document reads, saves, history, and restores.

Every write is one ``commit_revision`` call (ADR 0001): a save on a stale base
gets a 409 carrying the current head, an identical save is a no-op, and a
retried save with the same idempotency key returns the original revision.
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime
from enum import StrEnum
from typing import Any
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from packages.api.middleware.auth import Authenticated
from packages.api.routes.projects import owned_project
from packages.api.services.article_document_export import render_article_document_docx
from packages.api.services.document_citations import validate_document_citations
from packages.api.services.revisions import (
    RevisionListView,
    RevisionView,
    document_store,
    raise_store_error,
    stale_revision,
)
from packages.core.models.document import ArticleDocumentContent
from packages.platform.document_models import (
    CommitOutcome,
    CommitStatus,
    DocumentHead,
    DocumentKind,
    DocumentStoreError,
    RevisionKind,
    user_actor,
)

router = APIRouter(prefix="/projects", tags=["documents"])


class SaveKind(StrEnum):
    """Which human write this is; both commit identically, history tells them apart."""

    MANUAL = "manual"
    AUTOSAVE = "autosave"


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
    kind: SaveKind = SaveKind.MANUAL


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


def _article(content: dict[str, Any], revision_id: str) -> ArticleDocumentContent:
    try:
        return ArticleDocumentContent.model_validate(content)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"reason": "legacy_invalid", "revision_id": revision_id},
        ) from exc


def _head_view(head: DocumentHead) -> ArticleDocumentView:
    return ArticleDocumentView(
        document_id=UUID(head.document_id),
        revision_id=UUID(head.revision_id),
        content=_article(head.content, head.revision_id),
        updated_at=head.updated_at,
    )


async def _owned_article(request: Request, project_id: str, user_id: str) -> dict[str, Any]:
    project = await owned_project(request, project_id, user_id)
    if str(project.get("type")) not in ("article", "research_package"):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="not_article_project")
    return project


async def _head(request: Request, project_id: str) -> DocumentHead:
    head = await document_store(request).head(project_id, DocumentKind.ARTICLE)
    if head is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="document_not_found")
    return head


async def _view_of(request: Request, outcome: CommitOutcome) -> ArticleDocumentView:
    if outcome.status is CommitStatus.CONFLICT or outcome.revision_id is None:
        raise stale_revision(outcome.head_revision_id)
    record = await document_store(request).revision(outcome.document_id, outcome.revision_id)
    if record is None or record.content is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="revision_not_found")
    return ArticleDocumentView(
        document_id=UUID(outcome.document_id),
        revision_id=UUID(record.id),
        content=_article(record.content, record.id),
        updated_at=record.created_at,
    )


async def _commit(
    request: Request,
    document_id: str,
    base_revision_id: UUID | None,
    content: ArticleDocumentContent,
    *,
    kind: RevisionKind,
    user_id: str,
    idempotency_key: str,
) -> CommitOutcome:
    try:
        return await document_store(request).commit(
            document_id,
            str(base_revision_id) if base_revision_id is not None else None,
            content.model_dump(mode="json"),
            kind=kind,
            actor=user_actor(user_id),
            idempotency_key=idempotency_key,
        )
    except DocumentStoreError as exc:
        raise_store_error(exc)


@router.post("/{project_id}/documents/article", response_model=ArticleDocumentView)
async def initialize_article(
    request: Request, project_id: str, body: InitializeArticleRequest, auth: Authenticated
) -> ArticleDocumentView:
    """Create an empty article once; a retry or a racing init returns the existing head."""

    user_id = str(auth.user_id)
    await _owned_article(request, project_id, user_id)
    store = document_store(request)
    existing = await store.head(project_id, DocumentKind.ARTICLE)
    if existing is not None:
        return _head_view(existing)
    try:
        document_id = await store.ensure_document(
            project_id, DocumentKind.ARTICLE, user_actor(user_id)
        )
    except DocumentStoreError as exc:
        raise_store_error(exc)
    outcome = await _commit(
        request,
        document_id,
        None,
        ArticleDocumentContent(title=body.title),
        kind=RevisionKind.MANUAL,
        user_id=user_id,
        idempotency_key=body.idempotency_key,
    )
    if outcome.status is CommitStatus.CONFLICT:
        return _head_view(await _head(request, project_id))
    return await _view_of(request, outcome)


@router.get("/{project_id}/documents/article", response_model=ArticleDocumentView)
async def get_article(
    request: Request, project_id: str, auth: Authenticated
) -> ArticleDocumentView:
    """Return the current article revision for an owned article project."""

    await _owned_article(request, project_id, str(auth.user_id))
    return _head_view(await _head(request, project_id))


@router.get("/{project_id}/documents/article/export.docx")
async def export_article_docx(
    request: Request, project_id: str, auth: Authenticated, revision_id: UUID | None = None
) -> Response:
    """Download a specified revision; legacy callers may request the current head."""

    await _owned_article(request, project_id, str(auth.user_id))
    head = await _head(request, project_id)
    selected_revision = str(revision_id) if revision_id else head.revision_id
    if revision_id:
        revision = await document_store(request).revision(head.document_id, selected_revision)
        if revision is None or revision.content is None:
            raise HTTPException(status_code=404, detail="revision_not_found")
        content = _article(revision.content, revision.id)
    else:
        content = _article(head.content, head.revision_id)
    payload = await asyncio.to_thread(render_article_document_docx, content)
    safe_ascii = re.sub(r"[^A-Za-z0-9._-]+", "-", content.title).strip("-.")[:80]
    fallback = f"{safe_ascii or 'article'}.docx"
    encoded = quote(f"{content.title[:120]}.docx", safe="")
    return Response(
        content=payload,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "X-Document-Revision": selected_revision,
            "Cache-Control": "private, no-store",
            "Content-Disposition": (
                f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{encoded}"
            ),
        },
    )


@router.put("/{project_id}/documents/article", response_model=ArticleDocumentView)
async def save_article(
    request: Request, project_id: str, body: SaveArticleRequest, auth: Authenticated
) -> ArticleDocumentView:
    """Save a revision; 409 with the current head when the editor's base is stale."""

    user_id = str(auth.user_id)
    await _owned_article(request, project_id, user_id)
    head = await _head(request, project_id)
    content = body.content
    await validate_document_citations(request.app.state.db, project_id, content)
    outcome = await _commit(
        request,
        head.document_id,
        body.base_revision_id,
        content,
        kind=RevisionKind(body.kind.value),
        user_id=user_id,
        idempotency_key=body.idempotency_key,
    )
    return await _view_of(request, outcome)


@router.get("/{project_id}/documents/article/revisions", response_model=RevisionListView)
async def list_article_revisions(
    request: Request, project_id: str, auth: Authenticated
) -> RevisionListView:
    """Return newest-first revision metadata for the owned article."""

    await _owned_article(request, project_id, str(auth.user_id))
    head = await _head(request, project_id)
    records = await document_store(request).list_revisions(head.document_id)
    return RevisionListView(revisions=[RevisionView.of(record) for record in records])


@router.post("/{project_id}/documents/article/restore", response_model=ArticleDocumentView)
async def restore_article(
    request: Request, project_id: str, body: RestoreArticleRequest, auth: Authenticated
) -> ArticleDocumentView:
    """Restore an old snapshot by committing it as a new head revision."""

    user_id = str(auth.user_id)
    await _owned_article(request, project_id, user_id)
    head = await _head(request, project_id)
    previous = await document_store(request).revision(head.document_id, str(body.revision_id))
    if previous is None or previous.content is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="revision_not_found")
    content = _article(previous.content, previous.id)
    await validate_document_citations(request.app.state.db, project_id, content)
    outcome = await _commit(
        request,
        head.document_id,
        body.base_revision_id,
        content,
        kind=RevisionKind.RESTORE,
        user_id=user_id,
        idempotency_key=body.idempotency_key,
    )
    return await _view_of(request, outcome)
