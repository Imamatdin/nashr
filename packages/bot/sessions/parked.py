"""The parked ``edit_slides`` call and its operation identity (B1-FIX4, Codex F2/F3).

A turn that asks for an edit it cannot apply inline ends with the model's call
unanswered: queued for a worker, or held behind the approval button. Parking gives
that call an operation id, persisted as ``brain_sessions.parked_operation_id``.
The edit job carries it with the session id; the database admits the job, and its
commit, only while the session still has exactly that call parked; a dead worker's
answer is recovered only from the job carrying both ids. Answering the call, by
whichever path, clears it, so a call is answered at most once: a second answer
finds nothing parked and is refused or dropped.
"""

from __future__ import annotations

import uuid

from packages.bot.sessions.models import BrainSession
from packages.core.brain_loop import EDIT_SLIDES_TOOL_NAME
from packages.core.gemini_tools import FunctionResult, build_function_responses_content


def park_call(session: BrainSession) -> str:
    """Give the call the session just parked a new operation id, and return it."""

    session.parked_operation_id = str(uuid.uuid4())
    return session.parked_operation_id


def answer_calls(session: BrainSession, response: dict[str, object], *, count: int) -> None:
    """Answer each parked ``edit_slides`` call part with ``response``; nothing stays parked.

    Gemini requires every tool-call part that ended a turn to be answered by its
    own function_response part before the next user turn (else HTTP 400).
    """

    parts = [
        FunctionResult(name=EDIT_SLIDES_TOOL_NAME, response=response) for _ in range(max(1, count))
    ]
    session.history = [*session.history, build_function_responses_content(parts)]
    session.parked_operation_id = None


__all__ = ["answer_calls", "park_call"]
