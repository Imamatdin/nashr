"""Owned, paginated source evidence and idempotent background processing."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from packages.api.middleware.auth import Authenticated
from packages.api.routes.jobs import JobView, client_ip, job_view
from packages.api.routes.projects import owned_project
from packages.core.constants import MAX_FILES_PER_PROJECT
from packages.core.models.source import SourceChunk
from packages.platform.jobs import DuplicateActiveJobError, JobType
from packages.platform.rate_limit import SOURCE_PROCESSING_ACTION

router = APIRouter(prefix="/projects", tags=["evidence"])
PAGE_SIZE = 50


class EvidenceSourceView(BaseModel):
    """Extraction readiness; ready means text exists, not that it is true."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    filename: str
    processed_at: datetime | None
    passage_count: int = 0
    warnings: list[str] = Field(default_factory=list)


class EvidenceView(BaseModel):
    """A page of passages plus the source library and most recent processing job."""

    model_config = ConfigDict(extra="forbid")

    sources: list[EvidenceSourceView]
    passages: list[SourceChunk]
    next_offset: int | None
    job: JobView | None


@router.get("/{project_id}/evidence", response_model=EvidenceView)
async def get_evidence(
    request: Request,
    project_id: UUID,
    auth: Authenticated,
    source_id: UUID | None = None,
    offset: int = Query(default=0, ge=0, le=100_000),
) -> EvidenceView:
    """Never expose another project's source text, even with a forged source ID."""

    project = str(project_id)
    await owned_project(request, project, str(auth.user_id))
    sources = await request.app.state.db.get_project_sources(project)
    rows = await request.app.state.db.get_source_passages(
        project, str(source_id) if source_id else None, offset, PAGE_SIZE + 1
    )
    job = await request.app.state.job_queue.get_latest_job(project, JobType.SOURCE_PROCESSING)
    return EvidenceView(
        sources=[
            EvidenceSourceView(
                id=row["id"],
                filename=row["filename"],
                processed_at=row.get("evidence_processed_at"),
                passage_count=row.get("evidence_passage_count", 0),
                warnings=row.get("evidence_warnings", []),
            )
            for row in sources
        ],
        passages=[SourceChunk.model_validate(row) for row in rows[:PAGE_SIZE]],
        next_offset=offset + PAGE_SIZE if len(rows) > PAGE_SIZE else None,
        job=await job_view(job) if job else None,
    )


@router.get("/{project_id}/evidence/passages/{passage_id}", response_model=SourceChunk)
async def get_passage(
    request: Request, project_id: UUID, passage_id: UUID, auth: Authenticated
) -> SourceChunk:
    """Inspect a citation even when its passage is outside the current library page."""

    await owned_project(request, str(project_id), str(auth.user_id))
    row = await request.app.state.db.get_evidence_passage(str(project_id), str(passage_id))
    if row is None:
        raise HTTPException(status_code=404, detail="passage_not_found")
    return SourceChunk.model_validate(row)


@router.post("/{project_id}/evidence/process", response_model=JobView)
async def process_evidence(request: Request, project_id: UUID, auth: Authenticated) -> JobView:
    """Queue registered, unprocessed uploads; no model call or credit deduction."""

    project, user = str(project_id), str(auth.user_id)
    await owned_project(request, project, user)
    queue = request.app.state.job_queue
    active = await queue.get_active_job(project, JobType.SOURCE_PROCESSING)
    if active:
        return await job_view(active, existing=True)
    decision = await request.app.state.rate_limiter.check(
        action=SOURCE_PROCESSING_ACTION, user_id=user, ip=client_ip(request)
    )
    if not decision.allowed:
        raise HTTPException(status_code=429, detail="rate_limited")
    sources = await request.app.state.db.get_project_sources(project)
    pending = [str(row["id"]) for row in sources if not row.get("evidence_processed_at")]
    if not pending:
        raise HTTPException(status_code=409, detail="no_sources_to_process")
    if len(pending) > MAX_FILES_PER_PROJECT:
        raise HTTPException(status_code=422, detail="too_many_sources")
    try:
        job = await queue.enqueue(
            project_id=project,
            user_id=user,
            job_type=JobType.SOURCE_PROCESSING,
            payload={"source_ids": pending},
        )
    except DuplicateActiveJobError as exc:
        return await job_view(exc.existing, existing=True)
    return await job_view(job)
