"""Job enqueue + polling routes (P2 pipeline; plan §5 "Job queue").

The FIRST publicly reachable credit-burning surface, so the order of gates is
load-bearing and spends zero model tokens before rejection:

1. persisted abuse caps (per-user AND per-IP) → 429 with visible counter state;
2. project ownership → 404 (existence is not leaked to non-owners);
3. idempotency — an active job for (project, job_type) is returned, not re-run;
4. entitlement — the existing balance path (``has_sufficient_credits`` +
   ``deduct_for_generation``) → 402 with balance/required, rejected pre-spend;
5. insert; a lost enqueue race refunds the deduction and returns the winner.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from packages.api.middleware.auth import Authenticated
from packages.core.enums import ExportFormat, GenerationPackage
from packages.platform.credits import CreditLedger
from packages.platform.jobs import DuplicateActiveJobError, GenerationJob, JobQueue, JobType
from packages.platform.rate_limit import ENQUEUE_ACTION, RateLimiter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/jobs", tags=["jobs"])

_MAX_SOURCES = 10

_PACKAGE_TO_JOB_TYPE: dict[GenerationPackage, JobType] = {
    GenerationPackage.PRESENTATION_BASIC: JobType.PRESENTATION_GENERATION,
    GenerationPackage.PRESENTATION_STANDARD: JobType.PRESENTATION_GENERATION,
    GenerationPackage.PRESENTATION_PREMIUM: JobType.PRESENTATION_GENERATION,
}


class SourceRef(BaseModel):
    """One already-uploaded source file, referenced by its R2 key."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    storage_key: str = Field(min_length=1, max_length=512)
    filename: str = Field(min_length=1, max_length=255)


class EnqueueRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    project_id: str = Field(min_length=1, max_length=64)
    package: GenerationPackage
    sources: list[SourceRef] = Field(min_length=1, max_length=_MAX_SOURCES)
    language: str = Field(default="uz", max_length=8)
    formats: list[ExportFormat] | None = None
    answers: dict[str, Any] | None = None


class JobView(BaseModel):
    """The polling shape the UI reads (also returned by enqueue)."""

    model_config = ConfigDict(extra="forbid")

    id: str
    project_id: str
    job_type: str
    status: str
    progress: dict[str, Any]
    error_message: str | None
    existing: bool = False


def _view(job: GenerationJob, *, existing: bool = False) -> JobView:
    return JobView(
        id=job.id,
        project_id=job.project_id,
        job_type=job.job_type.value,
        status=job.status.value,
        progress=job.progress,
        error_message=job.error_message,
        existing=existing,
    )


def _client_ip(request: Request) -> str:
    """Caller address for the per-IP cap.

    Caddy APPENDS the peer address to X-Forwarded-For, so only the LAST entry
    is trustworthy — a client can stuff arbitrary leading entries to dodge the
    per-IP cap. Take the last one.
    """

    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"


@router.post("", response_model=JobView)
async def enqueue_job(request: Request, body: EnqueueRequest, auth: Authenticated) -> JobView:
    """Enqueue a presentation generation job for a project the caller owns."""

    limiter: RateLimiter = request.app.state.rate_limiter
    queue: JobQueue = request.app.state.job_queue
    credits: CreditLedger = request.app.state.credits
    user_id = str(auth.user_id)

    decision = await limiter.check(action=ENQUEUE_ACTION, user_id=user_id, ip=_client_ip(request))
    if not decision.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "reason": "rate_limited",
                "scope": decision.scope,
                "count": decision.count,
                "limit": decision.limit,
                "resets_at": decision.resets_at.isoformat(),
            },
        )

    job_type = _PACKAGE_TO_JOB_TYPE.get(body.package)
    if job_type is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="package_not_enqueueable",
        )

    project = await request.app.state.db.get_project(body.project_id)
    if project is None or str(project.get("user_id")) != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="project_not_found")

    existing = await queue.get_active_job(body.project_id, job_type)
    if existing is not None:
        return _view(existing, existing=True)

    # Every source must be a row this project registered (POST /sources): the
    # worker fetches whatever key the payload names with the service role, so
    # an unvalidated key would let a caller feed it arbitrary bucket objects.
    registered = {
        str(row.get("storage_key")): row
        for row in await request.app.state.db.get_project_sources(body.project_id)
    }
    resolved_sources: list[dict[str, Any]] = []
    for ref in body.sources:
        row = registered.get(ref.storage_key)
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"reason": "unregistered_source", "filename": ref.filename},
            )
        resolved_sources.append(
            {
                "storage_key": ref.storage_key,
                "filename": str(row.get("filename") or ref.filename),
                # Threaded into claim/chunk stamping for the provenance view.
                "source_id": str(row.get("id") or ""),
            }
        )

    product_type = body.package.value
    if not await credits.has_sufficient_credits(user_id, product_type):
        balance = await credits.get_balance(user_id)
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "reason": "insufficient_balance",
                "balance": balance,
                "required": CreditLedger.PRICING[product_type],
            },
        )
    deduction = await credits.deduct_for_generation(user_id, body.project_id, product_type)

    payload: dict[str, Any] = {
        "package": body.package.value,
        "product_type": product_type,
        # The exact amount deducted, so a failure refunds what was charged
        # even if PRICING changes between enqueue and refund.
        "deducted_amount": -deduction.amount,
        "language": body.language,
        "sources": resolved_sources,
        # Web delivery is all three primary formats (SPEC §0 rule 7): an
        # omitted list means html+pptx+pdf, not the orchestrator's bot-era
        # two-format default (P2 gate defect 3).
        "formats": [f.value for f in body.formats]
        if body.formats
        else [ExportFormat.HTML.value, ExportFormat.PPTX_EDITABLE.value, ExportFormat.PDF.value],
        "answers": body.answers,
    }
    try:
        job = await queue.enqueue(
            project_id=body.project_id,
            user_id=user_id,
            job_type=job_type,
            payload=payload,
        )
    except DuplicateActiveJobError as exc:
        # Lost the enqueue race: undo our deduction, hand back the winner.
        await credits.refund(
            user_id,
            body.project_id,
            -deduction.amount,
            reason=f"refund:duplicate_enqueue:{exc.existing.id}",
        )
        return _view(exc.existing, existing=True)
    logger.info(
        "job_enqueued project=%s job=%s type=%s user=%s",
        body.project_id,
        job.id,
        job_type.value,
        user_id,
    )
    return _view(job)


@router.get("/{job_id}", response_model=JobView)
async def get_job(request: Request, job_id: str, auth: Authenticated) -> JobView:
    """Poll one job's status/progress (owner only)."""

    queue: JobQueue = request.app.state.job_queue
    job = await queue.get_job(job_id)
    if job is None or job.user_id != str(auth.user_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job_not_found")
    return _view(job)
