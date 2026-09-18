"""Project-scoped research discovery using the existing academic providers."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from packages.academic.search import AcademicSearchService
from packages.api.middleware.auth import Authenticated
from packages.api.routes.projects import owned_project
from packages.core.models.academic import AcademicPaper

router = APIRouter(prefix="/projects", tags=["research"])


class ResearchRequest(BaseModel):
    """A bounded user search, never an instruction to generate citations."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    query: str = Field(min_length=2, max_length=500)


class ResearchView(BaseModel):
    """Provider records and explicit availability, without internal errors."""

    model_config = ConfigDict(extra="forbid")

    papers: list[AcademicPaper]
    unavailable_providers: list[str]
    lex_uz_available: bool = False


@router.post("/{project_id}/research", response_model=ResearchView)
async def search_research(
    request: Request, project_id: str, body: ResearchRequest, auth: Authenticated
) -> ResearchView:
    """Search owned projects with a time bound and persisted abuse limits."""

    await owned_project(request, project_id, str(auth.user_id))
    decision = await request.app.state.rate_limiter.check(
        action="research",
        user_id=str(auth.user_id),
        ip=request.client.host if request.client else "unknown",
    )
    if not decision.allowed:
        raise HTTPException(status_code=429, detail="rate_limited")
    service = AcademicSearchService()
    try:
        result = await asyncio.wait_for(service.search(body.query, max_results=12), timeout=15)
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail="research_timeout") from exc
    finally:
        await service.close()
    return ResearchView(
        papers=result.papers,
        unavailable_providers=sorted({error.partition(":")[0] for error in result.errors}),
    )
