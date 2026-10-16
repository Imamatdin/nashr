"""Recover a parked edit's answer from its job's receipt (B1-FIX3; identity since B1-FIX4).

A queued edit's worker commits the revision with ``finish_generation_job`` and only
then answers the parked ``edit_slides`` call in a separate session write. If the
worker dies between the two, the edit is committed (and its allowance hold is
recorded, in the same transaction) but the conversation still ends in the
unanswered call. The job row is the receipt: ``finish_generation_job`` left it
``committed`` (or settled it) with the outcome and revision in ``progress``.

On load, a session with a parked call is matched to the edit job queued for that
exact call: the job's payload names the session and the parked operation
(Codex F2). Nothing else matches, so another conversation's receipt is never
adopted. The receipt is parsed into :class:`EditReceipt` before anything is read
with it; a receipt that does not parse is a :class:`JobDataInvalidError` (409
``job_data_invalid``), never a query with a malformed id (Codex F4). A matched job
that failed without a receipt is left to the dangling-call repair, which answers
with an honest error.
"""

from __future__ import annotations

import json
import logging
import uuid
from enum import StrEnum
from typing import Any, Final, Self, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from packages.bot.sessions.fix_responses import (
    committed_response,
    delivered_response,
    proposed_response,
    unchanged_response,
)
from packages.bot.sessions.models import ApprovalState, BrainSession
from packages.bot.sessions.parked import answer_calls
from packages.bot.sessions.session_rows import dangling_call_parts
from packages.core.models.presentation import DeckSpec
from packages.platform.database import DatabaseClient
from packages.platform.jobs import GenerationJob, JobDataInvalidError, JobQueue, JobStatus

logger = logging.getLogger(__name__)

# Job states that carry a finish receipt.
_SETTLED: Final[frozenset[JobStatus]] = frozenset(
    {JobStatus.COMMITTED, JobStatus.COMPLETED, JobStatus.DELIVERY_FAILED}
)


class ReceiptOutcome(StrEnum):
    """What ``finish_generation_job`` did with the edit (its ``progress.outcome``)."""

    COMMITTED = "committed"
    DUPLICATE = "duplicate"
    PROPOSED = "proposed"
    UNCHANGED = "unchanged"


_WITH_REVISION: Final[frozenset[ReceiptOutcome]] = frozenset(
    {ReceiptOutcome.COMMITTED, ReceiptOutcome.DUPLICATE, ReceiptOutcome.UNCHANGED}
)


class EditReceipt(BaseModel):
    """A settled edit job's receipt, as the session reads it.

    ``session_id`` and ``operation_id`` are the parked call the job was queued for;
    ``revision_id`` is the revision the edit committed (or, unchanged, the head it
    matched), absent only for a proposal.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    job_id: str = Field(min_length=1)
    session_id: uuid.UUID
    operation_id: uuid.UUID
    outcome: ReceiptOutcome
    revision_id: uuid.UUID | None
    slides_changed: int = Field(ge=0, le=1000)
    rendering: bool

    @model_validator(mode="after")
    def _revision_matches_outcome(self) -> Self:
        if (self.outcome in _WITH_REVISION) != (self.revision_id is not None):
            raise ValueError(f"outcome {self.outcome.value} with revision_id {self.revision_id}")
        return self


def _slides_changed(payload: dict[str, Any]) -> object:
    """The number of slides the batch edits, as the API stamped it."""

    if "slides_changed" in payload:
        return payload["slides_changed"]
    fixes = payload.get("fixes")
    return len(cast(list[Any], fixes)) if isinstance(fixes, list) else 0


def receipt_of(job: GenerationJob) -> EditReceipt:
    """Parse a settled edit job's receipt, or raise :class:`JobDataInvalidError`.

    The row is not touched: the structured log names the job and the fields, and
    the reader answers 409 ``job_data_invalid``.
    """

    progress = job.progress
    try:
        return EditReceipt.model_validate(
            {
                "job_id": job.id,
                "session_id": job.payload.get("session_id"),
                "operation_id": job.payload.get("operation_id"),
                "outcome": progress.get("outcome"),
                "revision_id": progress.get("revision_id"),
                "slides_changed": _slides_changed(job.payload),
                "rendering": job.render_job_id is not None
                or progress.get("render_job_id") is not None,
            }
        )
    except ValidationError as exc:
        fields = sorted(
            {".".join(str(p) for p in error["loc"]) or "receipt" for error in exc.errors()}
        )
        detail = "receipt:" + ",".join(fields)
        logger.error("job_data_invalid %s", json.dumps({"job_id": job.id, "fields": detail}))
        raise JobDataInvalidError(job.id, detail) from None


async def receipt_for(db: DatabaseClient, session: BrainSession) -> EditReceipt | None:
    """The receipt of the edit job queued for the session's parked call, if it settled."""

    if dangling_call_parts(session) == 0:
        return None
    if session.session_id is None or session.parked_operation_id is None:
        return None
    job = await JobQueue(db).get_edit_job(
        session.project_id, session.session_id, session.parked_operation_id
    )
    if job is None or job.status not in _SETTLED:
        return None
    receipt = receipt_of(job)
    if (str(receipt.session_id), str(receipt.operation_id)) != (
        session.session_id,
        session.parked_operation_id,
    ):
        logger.error(
            "job_data_invalid %s",
            json.dumps({"job_id": job.id, "fields": "receipt:identity_mismatch"}),
        )
        raise JobDataInvalidError(job.id, "receipt:identity_mismatch")
    return receipt


def answer_from_receipt(session: BrainSession, receipt: EditReceipt, deck: DeckSpec | None) -> None:
    """Answer the parked call with what the job's receipt says happened.

    ``deck`` is the deck of the receipt's revision when it committed one; the
    caller has loaded it and moves the session onto that revision.
    """

    response: dict[str, object]
    committed = receipt.outcome in (ReceiptOutcome.COMMITTED, ReceiptOutcome.DUPLICATE)
    if committed and deck is not None:
        response = (
            committed_response(deck, receipt.slides_changed)
            if receipt.rendering
            else delivered_response(deck, receipt.slides_changed)
        )
    elif receipt.outcome is ReceiptOutcome.PROPOSED:
        response = proposed_response()
    elif receipt.outcome is ReceiptOutcome.UNCHANGED:
        response = unchanged_response()
    else:
        response = {"error": "fix_failed", "detail": "edit_receipt_unreadable"}
    answer_calls(session, response, count=dangling_call_parts(session))
    session.pending_action = None
    session.approval_state = ApprovalState.IDLE
    logger.warning(
        "session_answer_recovered %s",
        json.dumps(
            {
                "project_id": session.project_id,
                "job_id": receipt.job_id,
                "operation_id": str(receipt.operation_id),
                "outcome": receipt.outcome.value,
            }
        ),
    )


def receipt_revision(receipt: EditReceipt) -> str | None:
    """The revision the receipt committed, if it committed one."""

    if receipt.outcome not in (ReceiptOutcome.COMMITTED, ReceiptOutcome.DUPLICATE):
        return None
    return str(receipt.revision_id)


__all__ = [
    "EditReceipt",
    "ReceiptOutcome",
    "answer_from_receipt",
    "receipt_for",
    "receipt_of",
    "receipt_revision",
]
