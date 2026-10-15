"""Recover a parked edit's answer from its job's receipt (B1-FIX3, Codex A1).

A queued edit's worker commits the revision with ``finish_generation_job`` and only
then answers the parked ``edit_slides`` call in a separate session write. If the
worker dies between the two, the edit is committed (and its allowance hold is
recorded, in the same transaction) but the conversation still ends in the
unanswered call. The job row is the receipt: ``finish_generation_job`` left it
``committed`` (or settled it) with the outcome and revision in ``progress``.

On load, a session whose history ends in an unanswered call is matched to the
project's latest edit job by the conversation length the API stamped on the job
when it parked the call. A match whose job has a receipt gets the answer the worker
would have written; the next session write persists it. A job that failed without
a receipt is left to the dangling-call repair, which answers with an honest error.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Final, cast

from packages.bot.sessions.fix_responses import (
    committed_response,
    delivered_response,
    proposed_response,
    unchanged_response,
)
from packages.bot.sessions.models import ApprovalState, BrainSession
from packages.bot.sessions.session_rows import dangling_call_parts
from packages.core.brain_loop import EDIT_SLIDES_TOOL_NAME
from packages.core.gemini_tools import FunctionResult, build_function_responses_content
from packages.core.models.presentation import DeckSpec
from packages.platform.database import DatabaseClient
from packages.platform.jobs import GenerationJob, JobQueue, JobStatus, JobType

logger = logging.getLogger(__name__)

# Job states that carry a finish receipt.
_SETTLED: Final[frozenset[JobStatus]] = frozenset(
    {JobStatus.COMMITTED, JobStatus.COMPLETED, JobStatus.DELIVERY_FAILED}
)
_COMMITTED_OUTCOMES: Final[frozenset[str]] = frozenset({"committed", "duplicate"})


def slides_changed(job: GenerationJob) -> int:
    """The number of slides the job's batch edits, as the API stamped it."""

    stamped = job.payload.get("slides_changed")
    if isinstance(stamped, int) and not isinstance(stamped, bool) and stamped >= 0:
        return stamped
    fixes = job.payload.get("fixes")
    return len(cast(list[Any], fixes)) if isinstance(fixes, list) else 0


async def receipt_for(db: DatabaseClient, session: BrainSession) -> GenerationJob | None:
    """The settled edit job that carries the session's unanswered call, if any."""

    if dangling_call_parts(session) == 0:
        return None
    job = await JobQueue(db).get_latest_job(session.project_id, JobType.PRESENTATION_EDIT)
    if job is None or job.status not in _SETTLED:
        return None
    if job.payload.get("history_len") != len(session.history):
        return None
    outcome = job.progress.get("outcome")
    if outcome not in (*_COMMITTED_OUTCOMES, "proposed", "unchanged"):
        return None
    return job


def answer_from_receipt(session: BrainSession, job: GenerationJob, deck: DeckSpec | None) -> None:
    """Answer the unanswered call with what the job's receipt says happened.

    ``deck`` is the deck of the receipt's revision when it committed one; the
    caller has loaded it and moves the session onto that revision.
    """

    outcome = str(job.progress.get("outcome"))
    changed = slides_changed(job)
    response: dict[str, object]
    if outcome in _COMMITTED_OUTCOMES and deck is not None:
        rendering = job.render_job_id is not None or job.progress.get("render_job_id") is not None
        response = (
            committed_response(deck, changed) if rendering else delivered_response(deck, changed)
        )
    elif outcome == "proposed":
        response = proposed_response()
    elif outcome == "unchanged":
        response = unchanged_response()
    else:
        response = {"error": "fix_failed", "detail": "edit_receipt_unreadable"}
    count = dangling_call_parts(session)
    parts = [FunctionResult(name=EDIT_SLIDES_TOOL_NAME, response=response) for _ in range(count)]
    session.history = [*session.history, build_function_responses_content(parts)]
    session.pending_action = None
    session.approval_state = ApprovalState.IDLE
    logger.warning(
        "session_answer_recovered %s",
        json.dumps({"project_id": session.project_id, "job_id": job.id, "outcome": outcome}),
    )


def receipt_revision(job: GenerationJob) -> str | None:
    """The revision the receipt committed, if it committed one."""

    if job.progress.get("outcome") not in _COMMITTED_OUTCOMES:
        return None
    revision = job.progress.get("revision_id")
    return revision if isinstance(revision, str) and revision else None


__all__ = ["answer_from_receipt", "receipt_for", "receipt_revision", "slides_changed"]
