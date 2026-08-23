"""One Way-2 turn, driven from anywhere (Session W, P1.2).

The web split of the bot's chat loop. The bot runs a turn and applies the fix
in the same coroutine because a Telegram handler can afford to; a web request
cannot — ``apply_fixes_and_render`` re-runs editorial regeneration and the Node
renderer, minutes of work. So the turn and the apply are separated:

* :func:`run_web_turn` (API process) runs ONE brain turn and, when the turn
  requests edits the user themselves asked for, PARKS them: the session is
  persisted with the model's ``edit_slides`` call still UNANSWERED in history
  and the caller enqueues a ``presentation_edit`` job carrying the fixes.
* :func:`dispatch_fix` (worker process) applies the parked batch, answers the
  call, consumes one unit of the tier's fix allowance, and persists.

The unanswered call is the same interlock the approval gate already relies on:
no turn may run against a session that has one, because resending a dangling
``function_call`` to Gemini is a 400. It is durable (it lives in
``brain_sessions.history_json``), so it survives a restart of either process.

What the unanswered call cannot do by itself is notice that the job carrying
its answer died. That is :func:`repair_dangling_call`'s job: a session whose
history ends in an unanswered call while NO edit job is active is healed with
an honest error response instead of being wedged forever.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Protocol

from google.genai import types as genai_types

from packages.bot.sessions.budget import has_fixes_remaining, session_fix_limit
from packages.bot.sessions.models import (
    ApprovalState,
    BrainSession,
    PendingAction,
    requires_approval,
)
from packages.bot.sessions.roster_format import render_roster_payload
from packages.bot.sessions.store import hydrate_figures, load_session, persist_session
from packages.core.brain_loop import EDIT_SLIDES_TOOL_NAME
from packages.core.gemini_tools import FunctionResult, build_function_responses_content
from packages.core.models.presentation import SlideFix
from packages.platform.database import DatabaseClient

if TYPE_CHECKING:  # heavy (aiogram + the whole pipeline) — worker-side only
    from collections.abc import Awaitable, Callable, Sequence

    from packages.bot.orchestrators.presentation_orchestrator import FixAndRenderResult
    from packages.bot.sessions.driver import BrainDriver
    from packages.core.enums import ExportFormat, GenerationPackage

logger = logging.getLogger(__name__)

# The literal opening of the once-injected context prefix
# (``packages.bot.sessions.driver._context_block``). Matched exactly rather
# than splitting on the "---" separator, which a user's own message could
# legitimately contain.
_CONTEXT_PREFIX_MARKER = "DECK ROSTER (address slides by slide_id):"
_CONTEXT_SEPARATOR = "\n\n---\n\n"

_MAX_WIRE_MESSAGES = 200


class FixRunner(Protocol):
    """The one orchestrator capability this module needs, as a seam.

    Keeps ``packages.sessions_core`` free of the bot orchestrator (and therefore
    of aiogram) at import time: the worker passes the real
    :class:`~packages.bot.orchestrators.presentation_orchestrator.PresentationOrchestrator`,
    a test passes a fake.
    """

    async def apply_fixes_and_render(
        self,
        deck: Any,
        fixes: Sequence[SlideFix],
        sources: Any,
        project_id: str,
        formats: list[ExportFormat],
        progress: Callable[[str, int, int], Awaitable[None]],
        *,
        package: GenerationPackage,
    ) -> FixAndRenderResult: ...


class TurnKind(StrEnum):
    """What :func:`run_web_turn` resolved a message to."""

    REPLY = "reply"
    APPROVAL_REQUIRED = "approval_required"
    FIX_READY = "fix_ready"
    FIXES_EXHAUSTED = "fixes_exhausted"
    AWAITING_APPROVAL = "awaiting_approval"
    NO_SESSION = "no_session"


@dataclass(frozen=True)
class PendingActionView:
    """A parked change, as the caller renders it."""

    reason: str
    fixes: tuple[SlideFix, ...]
    call_count: int


@dataclass(frozen=True)
class TurnResult:
    """The turn's verdict plus everything a route needs to answer with."""

    kind: TurnKind
    reply_text: str | None = None
    pending: PendingActionView | None = None
    fixes: tuple[SlideFix, ...] = ()
    fix_call_count: int = 0
    fix_limit: int = 0
    fixes_used: int = 0


@dataclass
class ChatSessionView:
    """The persisted conversation as a read surface."""

    can_edit: bool
    messages: list[dict[str, str]] = field(default_factory=list[dict[str, str]])
    pending: PendingActionView | None = None
    fixes_used: int = 0
    fix_limit: int = 0
    package: str | None = None
    slide_count: int = 0


# --------------------------------------------------------------- history views


def _part_text(part: genai_types.Part) -> str:
    """The plain text of a part, or '' for a tool call/response part."""

    if part.function_call is not None or part.function_response is not None:
        return ""
    return (part.text or "").strip()


def _strip_context_prefix(text: str) -> str:
    """Drop the once-injected roster+claims block from the first user turn.

    The driver folds the deck roster and up to 60 source claims into the first
    user message so the context lives in a stable, never-rewritten prefix. That
    is model plumbing; replaying it as "what the user said" would open every
    conversation with a wall of machine text.
    """

    if not text.startswith(_CONTEXT_PREFIX_MARKER):
        return text
    _, separator, tail = text.partition(_CONTEXT_SEPARATOR)
    return tail if separator else text


def history_for_wire(session: BrainSession) -> list[dict[str, str]]:
    """The conversation as user/assistant text, tool plumbing removed."""

    messages: list[dict[str, str]] = []
    for index, content in enumerate(session.history):
        role = content.role or "model"
        if role not in ("user", "model"):
            continue
        text = " ".join(
            chunk for chunk in (_part_text(part) for part in (content.parts or [])) if chunk
        ).strip()
        if not text:
            # A pure tool-call or tool-response turn: real history, nothing to
            # show. Skipped rather than rendered as an empty bubble.
            continue
        if index == 0 and role == "user":
            text = _strip_context_prefix(text)
            if not text:
                continue
        messages.append({"role": "user" if role == "user" else "assistant", "text": text})
    return messages[-_MAX_WIRE_MESSAGES:]


def _pending_view(pending: PendingAction | None) -> PendingActionView | None:
    if pending is None:
        return None
    return PendingActionView(
        reason=pending.reason,
        fixes=tuple(pending.fixes),
        call_count=pending.call_count,
    )


# ------------------------------------------------------------ dangling repair


def has_dangling_call(session: BrainSession) -> int:
    """Count the unanswered ``edit_slides`` call parts at the end of history.

    Zero means the conversation is answerable. A positive count means a fix was
    parked and its answer never arrived — either it is in flight (an edit job is
    active) or the job that carried it is gone.
    """

    if not session.history:
        return 0
    last = session.history[-1]
    if (last.role or "") != "model":
        return 0
    return sum(
        1
        for part in (last.parts or [])
        if part.function_call is not None
        and (part.function_call.name or EDIT_SLIDES_TOOL_NAME) == EDIT_SLIDES_TOOL_NAME
    )


def append_fix_result(session: BrainSession, response: dict[str, object], *, count: int) -> None:
    """Answer every parked ``edit_slides`` call part with the fix's real outcome.

    Gemini requires one ``function_response`` per call part before the next user
    turn, so ``count`` responses are appended — never fewer.
    """

    parts = [
        FunctionResult(name=EDIT_SLIDES_TOOL_NAME, response=response) for _ in range(max(1, count))
    ]
    session.history = [*session.history, build_function_responses_content(parts)]


async def repair_dangling_call(db: DatabaseClient, session: BrainSession) -> bool:
    """Heal a session wedged behind a call whose job never answered it.

    Callers MUST have established that no edit job is active first — otherwise
    this races the worker and double-answers the call.
    """

    count = has_dangling_call(session)
    if count == 0:
        return False
    logger.warning(
        "chat_dangling_call_repaired project=%s parts=%d",
        session.project_id,
        count,
    )
    append_fix_result(session, {"error": "fix_failed", "detail": "edit_job_lost"}, count=count)
    session.pending_action = None
    session.approval_state = ApprovalState.IDLE
    await persist_session(db, session)
    return True


# ------------------------------------------------------------------- read side


async def read_session(db: DatabaseClient, project_id: str) -> ChatSessionView:
    """The chat pane's read: history, parked decision, allowance, deck size.

    ``can_edit=False`` is the honest answer for a project with no persisted
    deck — the session store refuses to invent one, and the UI must say so
    rather than offering an editor that cannot work.
    """

    session = await load_session(db, project_id)
    if session is None:
        return ChatSessionView(can_edit=False)
    return ChatSessionView(
        can_edit=session.deck is not None,
        messages=history_for_wire(session),
        pending=_pending_view(session.pending_action),
        fixes_used=session.fixes_used,
        fix_limit=session_fix_limit(session.package),
        package=session.package.value,
        slide_count=len(session.deck.slides) if session.deck is not None else 0,
    )


# ------------------------------------------------------------------ turn side


async def run_web_turn(
    db: DatabaseClient,
    driver: BrainDriver,
    *,
    project_id: str,
    user_text: str,
    edit_job_active: Callable[[], Awaitable[bool]],
) -> TurnResult:
    """Run ONE brain turn for a web caller and park any fix it asks for.

    Mirrors the bot's ``_run_chat_turn`` up to the point where the two diverge:
    where the bot would apply the fix inline, this persists the session with the
    call unanswered and hands the batch back for the caller to enqueue. Every
    exit path has already persisted the session.

    ``edit_job_active`` is a PROBE, not a flag: it is awaited only at the
    moment a dangling call is found, which is the only moment the answer
    matters. Passing a boolean computed earlier would make the repair path's
    safety depend on a check made somewhere else at some other time — and
    repairing while the worker is mid-apply double-answers the call.
    """

    session = await load_session(db, project_id)
    if session is None or session.deck is None:
        return TurnResult(TurnKind.NO_SESSION)

    if session.pending_action is not None:
        # A decision is parked behind the approval gate; its call is unanswered.
        # Route back to it rather than running a turn that would resend a
        # dangling function_call.
        return TurnResult(
            TurnKind.AWAITING_APPROVAL,
            pending=_pending_view(session.pending_action),
            fix_limit=session_fix_limit(session.package),
            fixes_used=session.fixes_used,
        )

    if has_dangling_call(session):
        if await edit_job_active():
            # The worker owns this call. Refusing here is the same drop-not-queue
            # semantics the bot's per-project lock has.
            return TurnResult(
                TurnKind.AWAITING_APPROVAL,
                pending=None,
                fix_limit=session_fix_limit(session.package),
                fixes_used=session.fixes_used,
            )
        await repair_dangling_call(db, session)

    outcome = await driver.run_turn(session, user_text)
    session.history = outcome.history
    session.accumulated_cost_usd += outcome.estimated_cost_usd
    fix_limit = session_fix_limit(session.package)

    if not outcome.fixes:
        await persist_session(db, session)
        return TurnResult(
            TurnKind.REPLY,
            reply_text=outcome.reply_text,
            fix_limit=fix_limit,
            fixes_used=session.fixes_used,
        )

    if requires_approval(outcome, user_initiated=True):
        # Unreachable while every web turn is a typed message (user_initiated is
        # a provenance fact, and a typed message IS the authorization). Kept as
        # the same code path the bot uses so a future model-initiated proposal
        # (Way 3) gates here instead of silently auto-applying.
        session.pending_action = PendingAction(
            fixes=list(outcome.fixes),
            reason=outcome.reason or "",
            call_count=max(1, outcome.fix_call_count),
        )
        session.approval_state = ApprovalState.AWAITING_APPROVAL
        await persist_session(db, session)
        return TurnResult(
            TurnKind.APPROVAL_REQUIRED,
            reply_text=outcome.reply_text,
            pending=_pending_view(session.pending_action),
            fix_limit=fix_limit,
            fixes_used=session.fixes_used,
        )

    if not has_fixes_remaining(session.fixes_used, session.package):
        # Refuse BEFORE the expensive apply, and answer the model's call so the
        # next turn sees a coherent call → result history. The worker's
        # dispatch_fix re-checks: this gate is for the user's benefit, that one
        # is the authority.
        append_fix_result(
            session,
            {"error": "fixes_exhausted", "fix_limit": fix_limit},
            count=outcome.fix_call_count,
        )
        await persist_session(db, session)
        return TurnResult(
            TurnKind.FIXES_EXHAUSTED,
            reply_text=outcome.reply_text,
            fix_limit=fix_limit,
            fixes_used=session.fixes_used,
        )

    # Park: history holds the unanswered call, so no other turn can run until a
    # worker answers it. Persist BEFORE the caller enqueues — a job that exists
    # without the parked call would answer a call that is not there.
    await persist_session(db, session)
    return TurnResult(
        TurnKind.FIX_READY,
        reply_text=outcome.reply_text,
        fixes=tuple(outcome.fixes),
        fix_call_count=max(1, outcome.fix_call_count),
        fix_limit=fix_limit,
        fixes_used=session.fixes_used,
    )


async def abandon_parked_fix(db: DatabaseClient, project_id: str, *, call_count: int) -> None:
    """Undo a park whose job could not be enqueued.

    Called by the route when the enqueue that was supposed to carry the parked
    batch fails; without it the session stays wedged until the next request
    happens to find it.
    """

    session = await load_session(db, project_id)
    if session is None:
        return
    if has_dangling_call(session) == 0:
        return
    append_fix_result(
        session, {"error": "fix_failed", "detail": "enqueue_failed"}, count=call_count
    )
    session.pending_action = None
    session.approval_state = ApprovalState.IDLE
    await persist_session(db, session)


async def park_pending_for_apply(db: DatabaseClient, project_id: str) -> PendingActionView | None:
    """Read back the parked decision an approve call is about to run.

    The pending action is deliberately NOT cleared here: it stays on the row
    until :func:`dispatch_fix` consumes it, so a lost job leaves the decision
    re-presentable rather than silently dropped.
    """

    session = await load_session(db, project_id)
    if session is None or session.pending_action is None:
        return None
    return _pending_view(session.pending_action)


async def reject_pending(db: DatabaseClient, project_id: str) -> bool:
    """Discard the parked change and answer its call. True iff one was parked."""

    session = await load_session(db, project_id)
    if session is None:
        return False
    if session.pending_action is None:
        return False
    append_fix_result(session, {"discarded": True}, count=session.pending_action.call_count)
    session.pending_action = None
    session.approval_state = ApprovalState.IDLE
    await persist_session(db, session)
    return True


# ----------------------------------------------------------------- apply side


@dataclass(frozen=True)
class FixDispatchResult:
    """What the worker's apply produced, for the job's terminal row."""

    delivered: bool
    slides_changed: int = 0
    warnings: tuple[str, ...] = ()
    reason: str | None = None


async def dispatch_fix(
    *,
    runner: FixRunner,
    db: DatabaseClient,
    project_id: str,
    fixes: Sequence[SlideFix],
    call_count: int,
    progress: Callable[[str, int, int], Awaitable[None]],
) -> FixDispatchResult:
    """Apply a parked fix batch, answer its call, and persist. Worker-side.

    Lifted from the bot's ``_dispatch_fix`` with its two invariants intact:

    * the allowance is consumed IFF the batch produced at least one deliverable
      file — a render that degraded every format is a failed fix, not a used
      edit;
    * every exit answers each parked call part, so the next turn's history is
      coherent whatever happened.

    The web path needs no local-file stashing: ``apply_fixes_and_render`` →
    ``render`` already uploads each format to its stable R2 key and refreshes
    the ``generated_files`` rows the deck route serves.
    """

    session = await load_session(db, project_id)
    if session is None or session.deck is None:
        return FixDispatchResult(False, reason="no_session")

    fix_limit = session_fix_limit(session.package)
    if not has_fixes_remaining(session.fixes_used, session.package):
        append_fix_result(
            session, {"error": "fixes_exhausted", "fix_limit": fix_limit}, count=call_count
        )
        session.pending_action = None
        session.approval_state = ApprovalState.IDLE
        await persist_session(db, session)
        return FixDispatchResult(False, reason="fixes_exhausted")

    try:
        await hydrate_figures(db, session)
        result = await runner.apply_fixes_and_render(
            session.deck,
            list(fixes),
            session.sources,
            session.project_id,
            session.formats,
            progress,
            package=session.package,
        )
    except Exception as exc:
        logger.warning(
            "chat_fix_chain_failed project=%s error_type=%s",
            session.project_id,
            type(exc).__name__,
        )
        session.pending_action = None
        session.approval_state = ApprovalState.IDLE
        append_fix_result(
            session, {"error": "fix_failed", "detail": type(exc).__name__}, count=call_count
        )
        await persist_session(db, session)
        return FixDispatchResult(False, reason=f"fix_failed:{type(exc).__name__}")

    session.deck = result.deck
    session.pending_action = None
    session.approval_state = ApprovalState.IDLE

    if not result.render.by_extension():
        append_fix_result(
            session,
            {"error": "render_failed", "warnings": list(result.render.warnings)},
            count=call_count,
        )
        await persist_session(db, session)
        return FixDispatchResult(
            False, warnings=tuple(result.render.warnings), reason="render_failed"
        )

    session.fixes_used += 1
    session.accumulated_cost_usd += result.estimated_cost_usd
    session.accumulated_image_count += result.image_count
    append_fix_result(
        session,
        {
            "delivered": True,
            "slides_changed": len(fixes),
            "roster": render_roster_payload(session.deck),
        },
        count=call_count,
    )
    await persist_session(db, session)
    return FixDispatchResult(
        True,
        slides_changed=len(fixes),
        warnings=tuple(result.render.warnings),
    )


__all__ = [
    "ChatSessionView",
    "FixDispatchResult",
    "FixRunner",
    "PendingActionView",
    "TurnKind",
    "TurnResult",
    "abandon_parked_fix",
    "append_fix_result",
    "dispatch_fix",
    "has_dangling_call",
    "history_for_wire",
    "park_pending_for_apply",
    "read_session",
    "reject_pending",
    "repair_dangling_call",
    "run_web_turn",
]
