"""One Way-2 turn, driven from anywhere (Session W, P1.2).

The web split of the bot's chat loop. The bot runs a turn and applies the fix
in the same coroutine because a Telegram handler can afford to; a web request
cannot — applying fixes re-runs editorial regeneration and the Node renderer,
minutes of work. So the turn and the apply are separated:

* :func:`run_web_turn` (API process) runs ONE brain turn and, when the turn
  requests edits the user themselves asked for, PARKS them: the session is
  persisted with the model's ``edit_slides`` call still UNANSWERED in history
  and the caller enqueues a ``presentation_edit`` job carrying the fixes.
* :func:`dispatch_fix` (worker process) applies the parked batch against the
  revision the brain saw, commits it (or stores a proposal when the deck moved),
  renders and publishes the committed revision, answers the call, and persists
  (see :mod:`packages.sessions_core.apply`).

The unanswered call is the same interlock the approval gate already relies on:
no turn may run against a session that has one, because resending a dangling
``function_call`` to Gemini is a 400. It is durable (it lives in
``brain_sessions.history_json``), so it survives a restart of either process.

Parking also gives the call an operation id (B1-FIX4): the job carries it with
the session id, the database admits the job and its commit only while that call
is still parked, and the worker refuses a job for any other call. A call is
answered at most once.

What the unanswered call cannot do by itself is notice that the job carrying
its answer died. That is :func:`repair_dangling_call`'s job: a session whose
history ends in an unanswered call while NO edit job is active is healed with
an honest error response instead of being wedged forever.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

from google.genai import types as genai_types

from packages.bot.sessions.budget import has_fixes_remaining, session_fix_limit
from packages.bot.sessions.delivery import fixes_reserved, visible_notes
from packages.bot.sessions.models import (
    ApprovalState,
    BrainSession,
    PendingAction,
    requires_approval,
)
from packages.bot.sessions.parked import is_parked, park_call
from packages.bot.sessions.session_rows import dangling_call_parts
from packages.bot.sessions.store import (
    load_revision_deck,
    load_session,
    move_session_to_head,
    persist_session,
)
from packages.core.models.presentation import SlideFix
from packages.platform.database import DatabaseClient
from packages.sessions_core.apply import (
    CommitDeck,
    DeliverRevision,
    FixDispatchResult,
    FixRunner,
    FixStatus,
    answer_fix_calls,
    apply_fix_batch,
)

if TYPE_CHECKING:  # heavy (aiogram + the whole pipeline) — worker-side only
    from collections.abc import Awaitable, Callable, Sequence

    from packages.bot.sessions.driver import BrainDriver

logger = logging.getLogger(__name__)

# The literal opening of the once-injected context prefix
# (``packages.bot.sessions.driver._context_block``). Matched exactly rather
# than splitting on the "---" separator, which a user's own message could
# legitimately contain.
_CONTEXT_PREFIX_MARKER = "DECK ROSTER (address slides by slide_id):"
_CONTEXT_SEPARATOR = "\n\n---\n\n"

_MAX_WIRE_MESSAGES = 200


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
    """A parked change, as the caller renders it.

    ``session_id`` and ``operation_id`` identify the parked call; the API stamps
    both on the edit job that carries it (B1-FIX4).
    """

    reason: str
    fixes: tuple[SlideFix, ...]
    call_count: int
    session_id: str | None = None
    operation_id: str | None = None


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
    # Edits committed but still rendering: they hold allowance until settled.
    fixes_pending: int = 0
    # The revision the brain saw this turn: a parked edit commits against it.
    revision_id: str | None = None
    # Stamped on the edit job (B1-FIX4): the session whose allowance the edit
    # holds and the parked call it answers.
    session_id: str | None = None
    operation_id: str | None = None


@dataclass
class ChatSessionView:
    """The persisted conversation as a read surface."""

    can_edit: bool
    messages: list[dict[str, str]] = field(default_factory=list[dict[str, str]])
    pending: PendingActionView | None = None
    fixes_used: int = 0
    fixes_pending: int = 0
    delivering_job_ids: list[str] = field(default_factory=list[str])
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
    """The conversation as user/assistant text, tool plumbing removed.

    Delivery notices (an edit published, or saved but not rendered) are system
    lines placed after the turns that preceded them; they are never sent to the
    model.
    """

    messages: list[dict[str, str]] = []
    notes = sorted(visible_notes(session), key=lambda note: note.history_index)
    next_note = 0
    for index, content in enumerate(session.history):
        while next_note < len(notes) and notes[next_note].history_index <= index:
            messages.append({"role": "system", "text": notes[next_note].text})
            next_note += 1
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
    for note in notes[next_note:]:
        messages.append({"role": "system", "text": note.text})
    return messages[-_MAX_WIRE_MESSAGES:]


def _pending_view(
    pending: PendingAction | None, session: BrainSession | None = None
) -> PendingActionView | None:
    if pending is None:
        return None
    return PendingActionView(
        reason=pending.reason,
        fixes=tuple(pending.fixes),
        call_count=pending.call_count,
        session_id=session.session_id if session is not None else None,
        operation_id=session.parked_operation_id if session is not None else None,
    )


# ------------------------------------------------------------ dangling repair


def has_dangling_call(session: BrainSession) -> int:
    """Count the unanswered ``edit_slides`` call parts at the end of history.

    Zero means the conversation is answerable. A positive count means a fix was
    parked and its answer never arrived — either it is in flight (an edit job is
    active) or the job that carried it is gone. A job that committed before its
    worker died is not this case: loading answered its call from the receipt.
    """

    return dangling_call_parts(session)


def append_fix_result(session: BrainSession, response: dict[str, object], *, count: int) -> None:
    """Answer every parked ``edit_slides`` call part with the fix's real outcome.

    Gemini requires one ``function_response`` per call part before the next user
    turn, so ``count`` responses are appended — never fewer.
    """

    answer_fix_calls(session, response, count=count)


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

    A pure read (B1-FIX3): nothing is written, so a poll can never overwrite what
    a worker or another request saved meanwhile. ``can_edit=False`` is the honest
    answer for a project with no persisted deck — the session store refuses to
    invent one, and the UI must say so rather than offering an editor that cannot
    work.
    """

    session = await load_session(db, project_id)
    if session is None:
        return ChatSessionView(can_edit=False)
    return ChatSessionView(
        can_edit=session.deck is not None,
        messages=history_for_wire(session),
        pending=_pending_view(session.pending_action, session),
        fixes_used=session.fixes_used,
        fixes_pending=len(session.pending_deliveries),
        delivering_job_ids=[pending.job_id for pending in session.pending_deliveries],
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
    if session is None:
        return TurnResult(TurnKind.NO_SESSION)

    if session.pending_action is not None:
        # A decision is parked behind the approval gate; its call is unanswered.
        # Route back to it rather than running a turn that would resend a
        # dangling function_call.
        return TurnResult(
            TurnKind.AWAITING_APPROVAL,
            pending=_pending_view(session.pending_action, session),
            fix_limit=session_fix_limit(session.package),
            fixes_used=session.fixes_used,
            fixes_pending=len(session.pending_deliveries),
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
                fixes_pending=len(session.pending_deliveries),
            )
        await repair_dangling_call(db, session)

    # The web chat edits what the web shows: the head. (The bot instead keeps its
    # revision and asks the user to reload when the deck changed elsewhere.)
    await move_session_to_head(db, session)
    if session.deck is None:
        return TurnResult(TurnKind.NO_SESSION)

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
            fixes_pending=len(session.pending_deliveries),
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
        park_call(session)
        await persist_session(db, session)
        return TurnResult(
            TurnKind.APPROVAL_REQUIRED,
            reply_text=outcome.reply_text,
            pending=_pending_view(session.pending_action, session),
            fix_limit=fix_limit,
            fixes_used=session.fixes_used,
            fixes_pending=len(session.pending_deliveries),
        )

    if not has_fixes_remaining(fixes_reserved(session), session.package):
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
            fixes_pending=len(session.pending_deliveries),
        )

    # Park: history holds the unanswered call, so no other turn can run until a
    # worker answers it. Persist BEFORE the caller enqueues — the database admits
    # the job only for the call this write parks.
    operation_id = park_call(session)
    await persist_session(db, session)
    return TurnResult(
        TurnKind.FIX_READY,
        reply_text=outcome.reply_text,
        fixes=tuple(outcome.fixes),
        fix_call_count=max(1, outcome.fix_call_count),
        fix_limit=fix_limit,
        fixes_used=session.fixes_used,
        fixes_pending=len(session.pending_deliveries),
        revision_id=session.revision_id,
        session_id=session.session_id,
        operation_id=operation_id,
    )


class DecisionStaleError(Exception):
    """The parked decision the caller acted on is no longer the one parked (B1-FIX5).

    It was answered, or replaced by another call or another session, since the
    caller saw it. Nothing was written; the caller re-reads and re-presents.
    """

    def __init__(self, project_id: str) -> None:
        self.project_id = project_id
        super().__init__(f"the parked decision of project {project_id} has changed")


def _stale(project_id: str, action: str, session: BrainSession, session_id: str | None) -> None:
    logger.warning(
        "parked_call_stale project=%s action=%s session_matches=%s operation_parked=%s",
        project_id,
        action,
        session.session_id == session_id,
        session.parked_operation_id is not None,
    )


async def abandon_parked_fix(
    db: DatabaseClient,
    project_id: str,
    *,
    session_id: str | None,
    operation_id: str | None,
    call_count: int,
) -> bool:
    """Undo a park whose job could not be enqueued; True iff it answered the call.

    Called by the route when the enqueue that was supposed to carry the parked
    batch fails; without it the session stays wedged until the next request
    happens to find it. Only the call the failed request parked is answered
    (B1-FIX5, Codex B1): if that session or call has moved on (repaired, answered,
    replaced by another park or another session), nothing is written. A change
    landing after the check is handled by the write's compare-and-swap merge.
    """

    session = await load_session(db, project_id)
    if session is None:
        return False
    if not is_parked(session, session_id, operation_id) or has_dangling_call(session) == 0:
        _stale(project_id, "abandon", session, session_id)
        return False
    append_fix_result(
        session, {"error": "fix_failed", "detail": "enqueue_failed"}, count=call_count
    )
    session.pending_action = None
    session.approval_state = ApprovalState.IDLE
    await persist_session(db, session)
    return True


async def park_pending_for_apply(
    db: DatabaseClient, project_id: str, *, session_id: str, operation_id: str
) -> PendingActionView | None:
    """Read back the parked decision an approved job is about to run, if it is that job's.

    The pending action is deliberately NOT cleared here: it stays on the row
    until :func:`dispatch_fix` consumes it, so a lost job leaves the decision
    re-presentable rather than silently dropped. A decision that is not the job's
    own call (B1-FIX5) is not returned: the job must not apply someone else's batch.
    """

    session = await load_session(db, project_id)
    if session is None or session.pending_action is None:
        return None
    if not is_parked(session, session_id, operation_id):
        _stale(project_id, "apply_pending", session, session_id)
        return None
    return _pending_view(session.pending_action, session)


async def pending_for_approval(
    db: DatabaseClient, project_id: str, *, session_id: str, operation_id: str | None
) -> PendingActionView | None:
    """The parked decision the user approved, with its call's identity; None if none.

    ``session_id``/``operation_id`` are the decision the user saw; a different one
    raises :class:`DecisionStaleError` and nothing is written (B1-FIX5). A decision
    parked before operation ids existed (B1-FIX4; the user saw ``operation_id=None``)
    gets one now, persisted before the caller enqueues, so the database can admit
    the job. The decision itself stays on the row (see :func:`park_pending_for_apply`).
    """

    session = await load_session(db, project_id)
    if session is None or session.pending_action is None:
        return None
    if not is_parked(session, session_id, operation_id):
        _stale(project_id, "approve", session, session_id)
        raise DecisionStaleError(project_id)
    if session.parked_operation_id is None:
        park_call(session)
        await persist_session(db, session)
    return _pending_view(session.pending_action, session)


async def reject_pending(
    db: DatabaseClient, project_id: str, *, session_id: str, operation_id: str | None
) -> bool:
    """Discard the parked change the user saw and answer its call. True iff one was parked.

    A different decision than the one named raises :class:`DecisionStaleError` and
    nothing is written (B1-FIX5).
    """

    session = await load_session(db, project_id)
    if session is None:
        return False
    if session.pending_action is None:
        return False
    if not is_parked(session, session_id, operation_id):
        _stale(project_id, "reject", session, session_id)
        raise DecisionStaleError(project_id)
    append_fix_result(session, {"discarded": True}, count=session.pending_action.call_count)
    session.pending_action = None
    session.approval_state = ApprovalState.IDLE
    await persist_session(db, session)
    return True


# ----------------------------------------------------------------- apply side


async def dispatch_fix(
    *,
    runner: FixRunner,
    db: DatabaseClient,
    project_id: str,
    fixes: Sequence[SlideFix],
    call_count: int,
    progress: Callable[[str, int, int], Awaitable[None]],
    base_revision_id: str,
    commit: CommitDeck,
    deliver: DeliverRevision | None,
    session_id: str,
    operation_id: str,
    delivery_job_id: str | None = None,
) -> FixDispatchResult:
    """Apply a parked fix batch against the revision the brain saw. Worker-side.

    ``session_id`` and ``operation_id`` name the parked call the job was queued
    for. A session that was replaced, or whose call was answered meanwhile, is not
    this job's: nothing is applied, committed or answered (B1-FIX4), and the
    session is left exactly as it is.

    ``base_revision_id`` was stamped when the batch was parked. If the session has
    since moved (the bot reloaded, or a later web turn followed the head), the
    batch still applies to the deck it was asked about, so it is committed against
    that base and becomes a proposal or a conflict instead of overwriting newer work.
    """

    session = await load_session(db, project_id)
    if session is None:
        return FixDispatchResult(FixStatus.NO_SESSION, reason="no_session")
    if (session.session_id, session.parked_operation_id) != (session_id, operation_id):
        logger.warning(
            "fix_operation_stale project=%s session_matches=%s operation_parked=%s",
            project_id,
            session.session_id == session_id,
            session.parked_operation_id is not None,
        )
        return FixDispatchResult(FixStatus.OPERATION_STALE, reason="operation_stale")
    if session.revision_id != base_revision_id:
        revision_id, deck = await load_revision_deck(db, project_id, base_revision_id)
        if revision_id != base_revision_id:
            append_fix_result(
                session,
                {"error": "fix_failed", "detail": "base_revision_missing"},
                count=call_count,
            )
            session.pending_action = None
            session.approval_state = ApprovalState.IDLE
            await persist_session(db, session)
            return FixDispatchResult(FixStatus.FAILED, reason="base_revision_missing")
        session.revision_id, session.deck = revision_id, deck
    return await apply_fix_batch(
        runner=runner,
        db=db,
        session=session,
        fixes=fixes,
        call_count=call_count,
        progress=progress,
        commit=commit,
        deliver=deliver,
        delivery_job_id=delivery_job_id,
    )


__all__ = [
    "ChatSessionView",
    "DecisionStaleError",
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
    "pending_for_approval",
    "read_session",
    "reject_pending",
    "repair_dangling_call",
    "run_web_turn",
]
