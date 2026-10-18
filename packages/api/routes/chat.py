"""Conversational deck editing over HTTP (Session W, P1.2).

The Way-2 loop existed end to end and was reachable only from Telegram. These
four routes expose it, keeping every discipline the bot path enforces:

* the fix allowance is a per-tier COUNTER, consumed only by a DELIVERED fix;
* a fix turn NEVER charges — editing a deck the user already paid for is not a
  second sale;
* a re-delivery the user did not ask for is parked behind an approval the model
  cannot grant itself;
* one turn at a time per project, enforced against the JOB TABLE (durable
  across processes), not an in-process lock.

The expensive half — applying the fix and re-rendering — runs in the worker as
a ``presentation_edit`` job. The route returns the job id; the client watches it
the same way it watches a generation.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from packages.api.middleware.auth import Authenticated
from packages.core.models.presentation import SlideFix
from packages.platform.jobs import (
    DuplicateActiveJobError,
    EditIdentityRefusedError,
    JobQueue,
    JobType,
)
from packages.platform.rate_limit import CHAT_ACTION, RateLimiter
from packages.sessions_core import (
    DecisionStaleError,
    NoPendingActionError,
    PendingActionView,
    SessionNotReadyError,
    TurnKind,
    TurnResult,
    abandon_parked_fix,
    enqueue_approved_edit,
    enqueue_edit,
    read_session,
    reject_pending,
    run_web_turn,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/projects", tags=["chat"])

_MAX_MESSAGE_CHARS = 4000


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    message: str = Field(min_length=1, max_length=_MAX_MESSAGE_CHARS)


class FixView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slide_id: str
    instruction: str


class PendingView(BaseModel):
    """A parked decision; ``session_id``/``operation_id`` are what approve/reject name.

    ``operation_id`` is null only for a decision parked before operation ids
    existed (B1-FIX4); it is the identity the client sends back (B1-FIX5).
    """

    model_config = ConfigDict(extra="forbid")

    session_id: str | None
    operation_id: str | None
    reason: str
    fixes: list[FixView]


class ChatMessageView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: str
    text: str


class ChatHistoryView(BaseModel):
    """Everything the chat pane renders on mount."""

    model_config = ConfigDict(extra="forbid")

    can_edit: bool
    messages: list[ChatMessageView]
    pending_action: PendingView | None
    fixes_used: int
    fix_limit: int
    fixes_remaining: int
    package: str | None
    slide_count: int
    # An edit job is running: the deck is being re-rendered right now, so the
    # composer is disabled and the client watches this job.
    applying_job_id: str | None
    # Edits committed whose exports are still rendering (B1-FIX2). Each holds one
    # fix (``fixes_pending``); the client polls these jobs and re-reads the chat
    # when they settle, which is when the delivery notice appears.
    fixes_pending: int = 0
    delivering_job_ids: list[str] = []


class ChatTurnView(BaseModel):
    """One turn's outcome.

    Exactly one of ``reply``, ``pending_action`` or ``job_id`` carries the
    result; ``kind`` says which, so the client never has to guess from nulls.
    """

    model_config = ConfigDict(extra="forbid")

    kind: str
    reply: str | None = None
    pending_action: PendingView | None = None
    job_id: str | None = None
    fixes_used: int = 0
    fix_limit: int = 0
    fixes_remaining: int = 0
    fixes_pending: int = 0


def _fix_views(fixes: tuple[SlideFix, ...]) -> list[FixView]:
    return [FixView(slide_id=fix.slide_id, instruction=fix.instruction) for fix in fixes]


def _pending_view(pending: PendingActionView | None) -> PendingView | None:
    if pending is None:
        return None
    return PendingView(
        session_id=pending.session_id,
        operation_id=pending.operation_id,
        reason=pending.reason,
        fixes=_fix_views(pending.fixes),
    )


class DecisionRequest(BaseModel):
    """The parked decision the user is approving or rejecting, as the chat showed it.

    The route acts only on that decision (B1-FIX5): one answered or replaced since
    (another tab, the bot, a regeneration) is 409 ``decision_changed``, nothing
    written, and the client re-reads the chat.
    """

    model_config = ConfigDict(extra="forbid")

    session_id: uuid.UUID
    operation_id: uuid.UUID | None


def _decision_changed() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT, detail={"reason": "decision_changed"}
    )


def _client_ip(request: Request) -> str:
    """Last X-Forwarded-For entry (Caddy appends the peer; see the jobs route)."""

    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"


async def _owned_project(request: Request, project_id: str, user_id: str) -> dict[str, Any]:
    project = await request.app.state.db.get_project(project_id)
    if project is None or str(project.get("user_id")) != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="project_not_found")
    return project


async def _rate_limit(request: Request, user_id: str) -> None:
    limiter: RateLimiter = request.app.state.rate_limiter
    decision = await limiter.check(action=CHAT_ACTION, user_id=user_id, ip=_client_ip(request))
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


async def _active_edit_job_id(queue: JobQueue, project_id: str) -> str | None:
    job = await queue.get_active_job(project_id, JobType.PRESENTATION_EDIT)
    return job.id if job is not None else None


async def _has_active_edit_job(queue: JobQueue, project_id: str) -> bool:
    """Fresh queue read, for the turn machinery's dangling-call repair."""

    return (await _active_edit_job_id(queue, project_id)) is not None


async def _refuse_if_busy(queue: JobQueue, project_id: str) -> None:
    """Drop-not-queue: one operation at a time against a project's deck.

    A generation is writing the deck the session grounds on; an edit is
    rewriting it. Either makes a turn unsafe, so the caller is told to wait
    rather than being silently queued behind minutes of work.
    """

    for job_type in (JobType.PRESENTATION_GENERATION, JobType.PRESENTATION_EDIT):
        active = await queue.get_active_job(project_id, job_type)
        if active is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "reason": "brain_busy",
                    "job_id": active.id,
                    "job_type": active.job_type.value,
                },
            )


def _driver(request: Request) -> Any:
    """The brain driver for this turn.

    Injected on ``app.state`` (like every other dependency) so route tests run a
    scripted stub; production builds the real Gemini-backed driver lazily, which
    is why the API process now needs the same Vertex credentials the worker has.
    """

    factory = getattr(request.app.state, "brain_driver_factory", None)
    if factory is None:
        from packages.bot.sessions.driver import GeminiBrainDriver
        from packages.core.gemini import GeminiClient

        return GeminiBrainDriver(gemini=GeminiClient())
    return factory()


@router.get("/{project_id}/chat", response_model=ChatHistoryView)
async def get_chat(request: Request, project_id: str, auth: Authenticated) -> ChatHistoryView:
    """The persisted conversation, the parked decision, and what is left to spend."""

    await _owned_project(request, project_id, str(auth.user_id))
    queue: JobQueue = request.app.state.job_queue

    view = await read_session(request.app.state.db, project_id)
    return ChatHistoryView(
        can_edit=view.can_edit,
        messages=[ChatMessageView(role=m["role"], text=m["text"]) for m in view.messages],
        pending_action=_pending_view(view.pending),
        fixes_used=view.fixes_used,
        fix_limit=view.fix_limit,
        fixes_remaining=max(0, view.fix_limit - view.fixes_used - view.fixes_pending),
        fixes_pending=view.fixes_pending,
        delivering_job_ids=list(view.delivering_job_ids),
        package=view.package,
        slide_count=view.slide_count,
        applying_job_id=await _active_edit_job_id(queue, project_id),
    )


def _identity_refused(exc: EditIdentityRefusedError) -> HTTPException:
    """The database refused the edit's identity: the parked call changed under us.

    To the user this is the conversation moving underneath the request, the same
    answer a lost session write gets (``session_busy``); ``why`` names the refusal.
    """

    return HTTPException(
        status_code=status.HTTP_409_CONFLICT, detail={"reason": "session_busy", "why": exc.code}
    )


async def _abandon(db: Any, project_id: str, result: TurnResult) -> None:
    """Answer the call THIS request parked, and only that one (B1-FIX5, Codex B1)."""

    await abandon_parked_fix(
        db,
        project_id,
        session_id=result.session_id,
        operation_id=result.operation_id,
        call_count=result.fix_call_count,
    )


@router.post("/{project_id}/chat", response_model=ChatTurnView)
async def post_chat(
    request: Request, project_id: str, body: ChatRequest, auth: Authenticated
) -> ChatTurnView:
    """Run one brain turn. A plain answer returns inline; an edit becomes a job."""

    user_id = str(auth.user_id)
    await _owned_project(request, project_id, user_id)
    await _rate_limit(request, user_id)
    queue: JobQueue = request.app.state.job_queue
    await _refuse_if_busy(queue, project_id)

    db = request.app.state.db
    result = await run_web_turn(
        db,
        _driver(request),
        project_id=project_id,
        user_text=body.message,
        # Probed lazily, and only if the turn finds a dangling call: the
        # busy refusal above already covers the common path, but the repair
        # decision must be made against the queue as it is AT THAT MOMENT.
        edit_job_active=lambda: _has_active_edit_job(queue, project_id),
    )

    remaining = max(0, result.fix_limit - result.fixes_used - result.fixes_pending)

    if result.kind is TurnKind.NO_SESSION:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"reason": "session_not_ready"},
        )
    if result.kind is TurnKind.FIXES_EXHAUSTED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "reason": "fixes_exhausted",
                "fix_limit": result.fix_limit,
                "fixes_used": result.fixes_used,
            },
        )
    if result.kind in (TurnKind.APPROVAL_REQUIRED, TurnKind.AWAITING_APPROVAL):
        return ChatTurnView(
            kind=TurnKind.APPROVAL_REQUIRED.value,
            reply=result.reply_text,
            pending_action=_pending_view(result.pending),
            fixes_used=result.fixes_used,
            fix_limit=result.fix_limit,
            fixes_remaining=remaining,
            fixes_pending=result.fixes_pending,
        )
    if result.kind is TurnKind.REPLY:
        return ChatTurnView(
            kind=TurnKind.REPLY.value,
            reply=result.reply_text,
            fixes_used=result.fixes_used,
            fix_limit=result.fix_limit,
            fixes_remaining=remaining,
            fixes_pending=result.fixes_pending,
        )

    # FIX_READY: the session is parked with the call unanswered; the job carries
    # the batch. An enqueue that fails must un-park, or the session stays wedged.
    try:
        job_id = await enqueue_edit(
            db,
            queue,
            request.app.state.documents,
            project_id=project_id,
            user_id=user_id,
            fixes=result.fixes,
            call_count=result.fix_call_count,
            reply_text=result.reply_text,
            revision_id=result.revision_id,
            session_id=result.session_id,
            operation_id=result.operation_id,
        )
    except SessionNotReadyError:
        await _abandon(db, project_id, result)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail={"reason": "session_not_ready"}
        ) from None
    except DuplicateActiveJobError:
        await _abandon(db, project_id, result)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail={"reason": "brain_busy"}
        ) from None
    except EditIdentityRefusedError as exc:
        # The call this turn parked was answered or replaced before the job could
        # be queued; un-parking answers it only if it is still there.
        await _abandon(db, project_id, result)
        raise _identity_refused(exc) from None
    except Exception:
        await _abandon(db, project_id, result)
        logger.exception("chat_edit_enqueue_failed project=%s", project_id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail={"reason": "edit_not_queued"}
        ) from None

    logger.info(
        "chat_edit_enqueued project=%s job=%s fixes=%d", project_id, job_id, len(result.fixes)
    )
    return ChatTurnView(
        kind=TurnKind.FIX_READY.value,
        reply=result.reply_text,
        job_id=job_id,
        fixes_used=result.fixes_used,
        fix_limit=result.fix_limit,
        fixes_remaining=remaining,
        fixes_pending=result.fixes_pending,
    )


@router.post("/{project_id}/chat/approve", response_model=ChatTurnView)
async def approve_pending(
    request: Request, project_id: str, body: DecisionRequest, auth: Authenticated
) -> ChatTurnView:
    """Run the parked change. A BUTTON got here — never the model."""

    user_id = str(auth.user_id)
    await _owned_project(request, project_id, user_id)
    await _rate_limit(request, user_id)
    queue: JobQueue = request.app.state.job_queue
    await _refuse_if_busy(queue, project_id)

    db = request.app.state.db
    # The batch is NOT copied into the payload: it stays on the session row so a
    # lost job leaves the decision re-presentable instead of silently dropped. No
    # un-parking on failure (unlike the turn route) for the same reason.
    try:
        job_id = await enqueue_approved_edit(
            db,
            queue,
            request.app.state.documents,
            project_id=project_id,
            user_id=user_id,
            session_id=str(body.session_id),
            operation_id=str(body.operation_id) if body.operation_id else None,
        )
    except DecisionStaleError:
        raise _decision_changed() from None
    except NoPendingActionError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail={"reason": "no_pending_action"}
        ) from None
    except SessionNotReadyError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail={"reason": "session_not_ready"}
        ) from None
    except DuplicateActiveJobError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail={"reason": "brain_busy"}
        ) from None
    except EditIdentityRefusedError as exc:
        raise _identity_refused(exc) from None
    except Exception:
        # The client still gets the same machine-readable reason its sibling
        # returns rather than an opaque 500.
        logger.exception("chat_approve_enqueue_failed project=%s", project_id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail={"reason": "edit_not_queued"}
        ) from None

    view = await read_session(db, project_id)
    return ChatTurnView(
        kind=TurnKind.FIX_READY.value,
        job_id=job_id,
        fixes_used=view.fixes_used,
        fix_limit=view.fix_limit,
        fixes_remaining=max(0, view.fix_limit - view.fixes_used - view.fixes_pending),
        fixes_pending=view.fixes_pending,
    )


@router.post("/{project_id}/chat/reject", response_model=ChatTurnView)
async def reject_pending_action(
    request: Request, project_id: str, body: DecisionRequest, auth: Authenticated
) -> ChatTurnView:
    """Discard the parked change and unblock the conversation.

    Deliberately NOT rate-limited, unlike the other two POSTs: rejecting spends
    no model tokens and runs no job, and a user who has hit the chat cap must
    still be able to clear a decision that is blocking their own conversation.
    """

    user_id = str(auth.user_id)
    await _owned_project(request, project_id, user_id)
    queue: JobQueue = request.app.state.job_queue
    await _refuse_if_busy(queue, project_id)

    db = request.app.state.db
    try:
        rejected = await reject_pending(
            db,
            project_id,
            session_id=str(body.session_id),
            operation_id=str(body.operation_id) if body.operation_id else None,
        )
    except DecisionStaleError:
        raise _decision_changed() from None
    if not rejected:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail={"reason": "no_pending_action"}
        )
    view = await read_session(db, project_id)
    return ChatTurnView(
        kind=TurnKind.REPLY.value,
        fixes_used=view.fixes_used,
        fix_limit=view.fix_limit,
        fixes_remaining=max(0, view.fix_limit - view.fixes_used - view.fixes_pending),
        fixes_pending=view.fixes_pending,
    )


__all__ = ["router"]
