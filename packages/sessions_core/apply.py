"""Apply one fix batch to a session's revision and resolve it (ADR 0001).

The single implementation behind every AI edit — the bot's inline fix, the web
worker's parked fix, an approved parked change. The edited deck is committed
against the revision the session is editing; only a committed revision is
rendered and published. Every exit answers each pending ``edit_slides`` call part
so the next turn's history stays coherent.

Allowance rule: one edit is consumed only when the edit was delivered —
committed, rendered and published. A refused, failed, unchanged, conflicting or
proposed edit consumes nothing. When the queued job's own render publishes the
exports (``deliver=None``), the committed edit holds one fix as a pending delivery
until that render settles (:mod:`packages.bot.sessions.delivery`): delivered, it
is counted; failed, the hold is released and the allowance restored.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol

from packages.bot.sessions.budget import has_fixes_remaining, session_fix_limit
from packages.bot.sessions.delivery import fixes_reserved
from packages.bot.sessions.models import ApprovalState, BrainSession, PendingDelivery
from packages.bot.sessions.roster_format import render_roster_payload
from packages.bot.sessions.store import hydrate_figures, persist_session
from packages.core.brain_loop import EDIT_SLIDES_TOOL_NAME
from packages.core.enums import ExportFormat, GenerationPackage
from packages.core.gemini_tools import FunctionResult, build_function_responses_content
from packages.core.models.presentation import DeckSpec, SlideFix
from packages.platform.database import DatabaseClient
from packages.platform.document_models import CommitOutcome, CommitStatus
from packages.platform.jobs import JobStatus

logger = logging.getLogger(__name__)

ProgressFn = Callable[[str, int, int], Awaitable[None]]
CommitDeck = Callable[[DeckSpec, str | None], Awaitable[CommitOutcome]]
DeliverRevision = Callable[[DeckSpec, str, list[ExportFormat]], Awaitable[Sequence[str]]]


class FixRunner(Protocol):
    """The one orchestrator capability an edit needs (a seam for tests)."""

    async def apply_fixes(
        self,
        deck: DeckSpec,
        fixes: Sequence[SlideFix],
        sources: Any,
        project_id: str,
        progress: ProgressFn,
        *,
        package: GenerationPackage,
    ) -> Any: ...


class FixStatus(StrEnum):
    """How a fix batch resolved."""

    DELIVERED = "delivered"
    # Committed; the job's render is publishing the exports (not yet delivered).
    COMMITTED = "committed"
    PROPOSED = "proposed"
    CONFLICT = "conflict"
    UNCHANGED = "unchanged"
    FAILED = "failed"
    RENDER_FAILED = "render_failed"
    EXHAUSTED = "fixes_exhausted"
    NO_SESSION = "no_session"


@dataclass(frozen=True)
class FixDispatchResult:
    """What applying a batch produced, for the caller's reply or job row."""

    status: FixStatus
    slides_changed: int = 0
    warnings: tuple[str, ...] = ()
    reason: str | None = None
    revision_id: str | None = None
    head_revision_id: str | None = None
    proposal_id: str | None = None

    @property
    def delivered(self) -> bool:
        """True when the edit was committed, rendered and published."""

        return self.status is FixStatus.DELIVERED


def answer_fix_calls(session: BrainSession, response: dict[str, object], *, count: int) -> None:
    """Answer each of the turn's ``edit_slides`` call parts with ``response``.

    Gemini requires every tool-call part that ended a turn to be answered by its
    own function_response part before the next user turn (else HTTP 400).
    """

    parts = [
        FunctionResult(name=EDIT_SLIDES_TOOL_NAME, response=response) for _ in range(max(1, count))
    ]
    session.history = [*session.history, build_function_responses_content(parts)]


async def _finish(
    db: DatabaseClient,
    session: BrainSession,
    response: dict[str, object],
    call_count: int,
    result: FixDispatchResult,
) -> FixDispatchResult:
    session.pending_action = None
    session.approval_state = ApprovalState.IDLE
    answer_fix_calls(session, response, count=call_count)
    await persist_session(db, session)
    return result


async def apply_fix_batch(
    *,
    runner: FixRunner,
    db: DatabaseClient,
    session: BrainSession,
    fixes: Sequence[SlideFix],
    call_count: int,
    progress: ProgressFn,
    commit: CommitDeck,
    deliver: DeliverRevision | None,
    delivery_job_id: str | None = None,
) -> FixDispatchResult:
    """Apply ``fixes`` to ``session.deck``, commit against ``session.revision_id``, resolve.

    ``commit(deck, base_revision_id)`` returns the commit outcome. ``deliver(deck,
    revision_id, formats)`` renders and publishes a committed revision in the
    session's formats and returns render warnings, raising on any failure (the
    bot's inline path). ``deliver=None`` means the queued job ``delivery_job_id``
    is delivering it through its own render: the edit is then COMMITTED and holds
    one fix until that render settles, unless every format already existed.
    """

    if deliver is None and delivery_job_id is None:
        raise ValueError("an edit without an inline deliver needs the job delivering it")
    # Edits still rendering hold their fix, so a burst of edits cannot overdraw.
    if not has_fixes_remaining(fixes_reserved(session), session.package):
        limit = session_fix_limit(session.package)
        return await _finish(
            db,
            session,
            {"error": "fixes_exhausted", "fix_limit": limit},
            call_count,
            FixDispatchResult(FixStatus.EXHAUSTED, reason="fixes_exhausted"),
        )
    if session.deck is None:
        return await _finish(
            db,
            session,
            {"error": "no_editable_deck"},
            call_count,
            FixDispatchResult(FixStatus.NO_SESSION, reason="no_editable_deck"),
        )

    try:
        await hydrate_figures(db, session)
        batch = await runner.apply_fixes(
            session.deck,
            list(fixes),
            session.sources,
            session.project_id,
            progress,
            package=session.package,
        )
    except Exception as exc:
        logger.warning(
            "fix_chain_failed project=%s error_type=%s", session.project_id, type(exc).__name__
        )
        return await _finish(
            db,
            session,
            {"error": "fix_failed", "detail": type(exc).__name__},
            call_count,
            FixDispatchResult(FixStatus.FAILED, reason=f"fix_failed:{type(exc).__name__}"),
        )
    edited: DeckSpec = batch.deck
    session.accumulated_cost_usd += float(batch.estimated_cost_usd)

    try:
        outcome = await commit(edited, session.revision_id)
    except Exception as exc:
        logger.warning(
            "fix_commit_failed project=%s error_type=%s", session.project_id, type(exc).__name__
        )
        return await _finish(
            db,
            session,
            {"error": "persist_failed", "detail": type(exc).__name__},
            call_count,
            FixDispatchResult(FixStatus.FAILED, reason=f"persist_failed:{type(exc).__name__}"),
        )

    if outcome.status is CommitStatus.CONFLICT:
        return await _finish(
            db,
            session,
            {
                "error": "deck_changed_elsewhere",
                "detail": "the deck was edited elsewhere; this edit was not applied",
            },
            call_count,
            FixDispatchResult(
                FixStatus.CONFLICT, reason="conflict", head_revision_id=outcome.head_revision_id
            ),
        )
    if outcome.status is CommitStatus.UNCHANGED:
        return await _finish(
            db,
            session,
            {"unchanged": True},
            call_count,
            FixDispatchResult(FixStatus.UNCHANGED, revision_id=outcome.revision_id),
        )
    if outcome.status is CommitStatus.PROPOSED:
        return await _finish(
            db,
            session,
            {
                "proposed": True,
                "detail": "the deck changed while this edit ran; it was saved for review",
            },
            call_count,
            FixDispatchResult(
                FixStatus.PROPOSED,
                proposal_id=outcome.proposal_id,
                head_revision_id=outcome.head_revision_id,
            ),
        )

    revision_id = str(outcome.revision_id)
    session.deck = edited
    session.revision_id = revision_id
    if deliver is None:
        assert delivery_job_id is not None
        # Images were generated (and paid for) whether or not the render succeeds.
        session.accumulated_image_count += int(batch.image_count)
        if outcome.job_status == JobStatus.COMMITTED.value:
            session.pending_deliveries = [
                *session.pending_deliveries,
                PendingDelivery(
                    job_id=delivery_job_id, revision_id=revision_id, slides_changed=len(fixes)
                ),
            ]
            return await _finish(
                db,
                session,
                {
                    "committed": True,
                    "delivery": "rendering",
                    "slides_changed": len(fixes),
                    "roster": render_roster_payload(edited),
                },
                call_count,
                FixDispatchResult(
                    FixStatus.COMMITTED, slides_changed=len(fixes), revision_id=revision_id
                ),
            )
        # Every format already existed for this revision: delivered in the commit.
        session.fixes_used += 1
        return await _finish(
            db,
            session,
            {
                "delivered": True,
                "slides_changed": len(fixes),
                "roster": render_roster_payload(edited),
            },
            call_count,
            FixDispatchResult(
                FixStatus.DELIVERED, slides_changed=len(fixes), revision_id=revision_id
            ),
        )
    try:
        warnings = tuple(await deliver(edited, revision_id, list(session.formats)))
    except Exception as exc:
        logger.warning(
            "fix_delivery_failed project=%s error_type=%s", session.project_id, type(exc).__name__
        )
        return await _finish(
            db,
            session,
            {"error": "render_failed", "detail": type(exc).__name__},
            call_count,
            FixDispatchResult(
                FixStatus.RENDER_FAILED,
                reason=f"render_failed:{type(exc).__name__}",
                revision_id=revision_id,
            ),
        )

    session.fixes_used += 1
    session.accumulated_image_count += int(batch.image_count)
    return await _finish(
        db,
        session,
        {
            "delivered": True,
            "slides_changed": len(fixes),
            "roster": render_roster_payload(edited),
        },
        call_count,
        FixDispatchResult(
            FixStatus.DELIVERED,
            slides_changed=len(fixes),
            warnings=warnings,
            revision_id=revision_id,
        ),
    )


__all__ = [
    "CommitDeck",
    "DeliverRevision",
    "FixDispatchResult",
    "FixRunner",
    "FixStatus",
    "answer_fix_calls",
    "apply_fix_batch",
]
