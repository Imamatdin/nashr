"""Job enqueue + polling routes (P2 pipeline; plan §5 "Job queue").

The FIRST publicly reachable credit-burning surface, so the order of gates is
load-bearing and spends zero model tokens before rejection:

1. persisted abuse caps (per-user AND per-IP) → 429 with visible counter state;
2. package/job-type resolution — an explicit non-enqueueable package is 422;
3. project ownership → 404 (existence is not leaked to non-owners);
4. tier resolution for an omitted package, off the project row just fetched;
5. idempotency — an active job for (project, job_type) is returned, not re-run;
6. entitlement — the existing balance path (``has_sufficient_credits`` +
   ``deduct_for_generation``) → 402 with balance/required, rejected pre-spend;
7. insert; a lost enqueue race refunds the deduction and returns the winner.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, status
from postgrest.exceptions import APIError
from pydantic import BaseModel, ConfigDict, Field

from packages.api.middleware.auth import Authenticated
from packages.core.enums import ExportFormat, GenerationPackage
from packages.platform.credits import CreditLedger
from packages.platform.jobs import (
    DuplicateActiveJobError,
    GenerationJob,
    JobQueue,
    JobStatus,
    JobType,
)
from packages.platform.rate_limit import ENQUEUE_ACTION, RateLimiter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/jobs", tags=["jobs"])

_MAX_SOURCES = 10

_PACKAGE_TO_JOB_TYPE: dict[GenerationPackage, JobType] = {
    GenerationPackage.PRESENTATION_BASIC: JobType.PRESENTATION_GENERATION,
    GenerationPackage.PRESENTATION_STANDARD: JobType.PRESENTATION_GENERATION,
    GenerationPackage.PRESENTATION_PREMIUM: JobType.PRESENTATION_GENERATION,
}

# Only for project rows that predate migration 010 (package_tier NULL/absent)
# or carry a tier this route cannot enqueue. Never a substitute for a tier the
# project actually has.
_LEGACY_PACKAGE = GenerationPackage.PRESENTATION_STANDARD


class SourceRef(BaseModel):
    """One already-uploaded source file, referenced by its R2 key."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    storage_key: str = Field(min_length=1, max_length=512)
    filename: str = Field(min_length=1, max_length=255)


class EnqueueRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    project_id: str = Field(min_length=1, max_length=64)
    # Omitted means "charge what this project already committed to": the tier
    # persisted by an earlier enqueue. The workspace re-generate button sends
    # nothing, so it can no longer silently downgrade a premium project.
    package: GenerationPackage | None = None
    sources: list[SourceRef] = Field(min_length=1, max_length=_MAX_SOURCES)
    language: str = Field(default="uz", max_length=8)
    formats: list[ExportFormat] | None = None
    answers: dict[str, Any] | None = None
    # The user's own framing of what they want out of these sources. Steering
    # context for the editorial pass, never evidence: the grounding discipline
    # is unchanged downstream, so a topic the sources cannot support still
    # hard-stops rather than being fabricated to.
    topic: str | None = Field(default=None, max_length=2000)


class JobView(BaseModel):
    """The polling shape the UI reads (also returned by enqueue).

    Everything past ``existing`` is state the row already carried and the web
    could not see: timestamps for elapsed/stall detection, the AUTHORITATIVE
    tier and charged amount (the project's ``package_tier`` is best-effort and
    can disagree), and whether the failure was refunded — a fact, read from the
    job-stamped ledger row, not a guess.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    project_id: str
    job_type: str
    status: str
    progress: dict[str, Any]
    error_message: str | None
    existing: bool = False
    created_at: datetime | None = None
    started_at: datetime | None = None
    heartbeat_at: datetime | None = None
    completed_at: datetime | None = None
    package: str | None = None
    deducted_amount: int | None = None
    refunded: bool = False


def _payload_str(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    return value if isinstance(value, str) and value else None


def _payload_int(payload: dict[str, Any], key: str) -> int | None:
    value = payload.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


async def _view(
    job: GenerationJob,
    credits: CreditLedger | None = None,
    *,
    existing: bool = False,
) -> JobView:
    """Render one job row for the wire, resolving the refund fact when relevant.

    The ledger probe fires ONLY for a failed job: a queued/processing/completed
    row cannot have been refunded by the worker's failure path, and the web
    polls this shape every few seconds.
    """

    refunded = False
    if credits is not None and job.status is JobStatus.FAILED and job.user_id:
        refunded = await credits.has_refund_for_job(job.user_id, job.id)
    return JobView(
        id=job.id,
        project_id=job.project_id,
        job_type=job.job_type.value,
        status=job.status.value,
        progress=job.progress,
        error_message=job.error_message,
        existing=existing,
        created_at=job.created_at,
        started_at=job.started_at,
        heartbeat_at=job.heartbeat_at,
        completed_at=job.completed_at,
        package=_payload_str(job.payload, "package"),
        deducted_amount=_payload_int(job.payload, "deducted_amount"),
        refunded=refunded,
    )


def _persisted_package(project: dict[str, Any]) -> GenerationPackage:
    """Resolve a project's stored tier, falling back to the legacy package.

    ``dict.get`` rather than indexing: migration 010 is human-applied, so in
    the window between deploying this code and applying it the column simply
    is not in the row. An unparseable or non-enqueueable stored value is
    treated the same as a missing one.
    """

    stored = project.get("package_tier")
    if not isinstance(stored, str):
        return _LEGACY_PACKAGE
    try:
        package = GenerationPackage(stored)
    except ValueError:
        return _LEGACY_PACKAGE
    if package not in _PACKAGE_TO_JOB_TYPE:
        return _LEGACY_PACKAGE
    return package


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

    if body.package is not None and body.package not in _PACKAGE_TO_JOB_TYPE:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="package_not_enqueueable",
        )

    project = await request.app.state.db.get_project(body.project_id)
    if project is None or str(project.get("user_id")) != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="project_not_found")

    package = body.package if body.package is not None else _persisted_package(project)
    job_type = _PACKAGE_TO_JOB_TYPE[package]

    existing = await queue.get_active_job(body.project_id, job_type)
    if existing is not None:
        return await _view(existing, credits, existing=True)

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

    product_type = package.value
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
        "package": package.value,
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
        "topic": body.topic or None,
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
        return await _view(exc.existing, credits, existing=True)

    if body.package is not None:
        # Stamped only for an EXPLICIT choice, and only after the job is safely
        # queued — persisting the resolved value would freeze the legacy
        # fallback onto pre-010 projects as if the user had picked it.
        #
        # Best-effort: the credits are already spent and the job is already
        # running, so a stamp that fails (most plausibly because migration 010
        # is not yet applied to prod) must not turn a successful enqueue into
        # an error the user sees as "nothing happened, money gone".
        try:
            await request.app.state.db.set_project_package_tier(body.project_id, body.package.value)
        except APIError:
            logger.warning(
                "package_tier_stamp_failed project=%s package=%s",
                body.project_id,
                body.package.value,
                exc_info=True,
            )

    logger.info(
        "job_enqueued project=%s job=%s type=%s package=%s user=%s",
        body.project_id,
        job.id,
        job_type.value,
        package.value,
        user_id,
    )
    return await _view(job, credits)


@router.get("", response_model=JobView)
async def get_latest_project_job(
    request: Request,
    auth: Authenticated,
    project_id: str = Query(min_length=1, max_length=64),
    job_type: JobType = JobType.PRESENTATION_GENERATION,
) -> JobView:
    """The project's most recent job of ``job_type``, whatever its status.

    The discovery route the workspace derives its state from: without it a
    returning user who no longer holds ``?job=`` sees an idle pay button over a
    running, failed or delivered project.

    ``job_type`` defaults to the generation job on purpose — the workspace's
    state machine is about the deck's run, and an edit job (which carries no
    charge and does not change deck readiness) must not displace it. The chat
    pane tracks its own edit job from the id the chat route hands back.

    Ownership is enforced on the JOB row (``user_id``), the same check
    ``GET /jobs/{id}`` makes, and a project with no such job is 404 — the same
    shape as an unknown project, so existence is not leaked either way.
    """

    queue: JobQueue = request.app.state.job_queue
    credits: CreditLedger = request.app.state.credits

    project = await request.app.state.db.get_project(project_id)
    if project is None or str(project.get("user_id")) != str(auth.user_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="project_not_found")

    job = await queue.get_latest_job(project_id, job_type)
    if job is None or (job.user_id is not None and job.user_id != str(auth.user_id)):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job_not_found")
    return await _view(job, credits)


@router.get("/{job_id}", response_model=JobView)
async def get_job(request: Request, job_id: str, auth: Authenticated) -> JobView:
    """Poll one job's status/progress (owner only)."""

    queue: JobQueue = request.app.state.job_queue
    credits: CreditLedger = request.app.state.credits
    job = await queue.get_job(job_id)
    if job is None or job.user_id != str(auth.user_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job_not_found")
    return await _view(job, credits)
