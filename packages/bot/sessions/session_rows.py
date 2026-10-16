"""The brain_sessions row as columns: strict parsing, serialization and merging.

Three things the store needs and nothing else does (B1-FIX3):

* :func:`parse_row` turns a persisted row into a typed session or raises
  :class:`SessionDataInvalidError` naming the column, so a corrupt row is a 409
  ``session_invalid`` with a structured log, never a 500, and is never rewritten
  (Codex A3);
* :func:`columns_of` / :func:`columns_from_row` give the JSON value of every
  column a session write may change, the unit a compare-and-swap writes;
* :func:`merge` is the three-way merge of a write that lost its compare-and-swap:
  base (what the writer read), ours (what it wants), theirs (the row now). Nothing
  either side changed is lost (Codex A2); a conversation both sides extended in
  different ways is a :class:`SessionConflictError`.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Callable
from typing import Any, Final, cast

from packages.bot.orchestrators.article_orchestrator import SourceProcessingResult
from packages.bot.sessions.models import (
    ApprovalState,
    BrainSession,
    DeliveryNote,
    PendingAction,
)
from packages.bot.sessions.serialization import deserialize_sources, serialize_sources
from packages.core.brain_loop import EDIT_SLIDES_TOOL_NAME
from packages.core.enums import GenerationPackage
from packages.core.export_formats import parse_export_formats
from packages.core.gemini_tools import deserialize_history, serialize_history
from packages.core.models.presentation import DeckSpec

logger = logging.getLogger(__name__)

# Every column a session write may change (figures_json is write-once).
COLUMNS: Final[tuple[str, ...]] = (
    "history_json",
    "sources_json",
    "package",
    "formats_json",
    "approval_state",
    "pending_action_json",
    "parked_operation_id",
    "fixes_used",
    "accumulated_cost_usd",
    "accumulated_image_count",
    "revision_id",
    "delivery_notes_json",
)
_ADDITIVE: Final[frozenset[str]] = frozenset(
    {"fixes_used", "accumulated_cost_usd", "accumulated_image_count"}
)
_MAX_NOTES: Final[int] = 50
# What answering the parked call changes; a duplicate answer yields all of them.
_ANSWER_COLUMNS: Final[tuple[str, ...]] = (
    "history_json",
    "parked_operation_id",
    "pending_action_json",
    "approval_state",
)


class SessionDataInvalidError(Exception):
    """A persisted brain_sessions row does not parse; reads answer 409 session_invalid."""

    def __init__(self, project_id: str, column: str, detail: str) -> None:
        self.project_id = project_id
        self.column = column
        self.detail = detail
        super().__init__(f"session of project {project_id}: {column} is invalid: {detail}")


class SessionConflictError(Exception):
    """A session write cannot be merged: both sides extended the conversation."""

    def __init__(self, project_id: str, reason: str) -> None:
        self.project_id = project_id
        self.reason = reason
        super().__init__(f"session of project {project_id} conflict: {reason}")


def _invalid(project_id: str, column: str, detail: str) -> SessionDataInvalidError:
    logger.error(
        "session_invalid %s",
        json.dumps({"project_id": project_id, "column": column, "detail": detail[:300]}),
    )
    return SessionDataInvalidError(project_id, column, detail)


def _column[T](project_id: str, row: dict[str, Any], column: str, parse: Callable[[Any], T]) -> T:
    if column not in row:
        raise _invalid(project_id, column, "missing")
    try:
        return parse(row[column])
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise _invalid(project_id, column, f"{type(exc).__name__}: {exc}") from None


def _count(value: Any) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{value!r} is not a non-negative integer")
    return value


def _amount(value: Any) -> float:
    if not isinstance(value, int | float) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{value!r} is not a non-negative number")
    return float(value)


def _list(value: Any) -> list[Any]:
    if not isinstance(value, list):
        raise TypeError(f"expected a JSON array, got {type(value).__name__}")
    return cast(list[Any], value)


def _pending_action(value: Any) -> PendingAction | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise TypeError(f"expected a JSON object, got {type(value).__name__}")
    return PendingAction.model_validate(value)


def _operation(value: Any) -> str | None:
    if value is None:
        return None
    return str(uuid.UUID(str(value)))


def _sources(value: Any) -> SourceProcessingResult:
    if not isinstance(value, dict):
        raise TypeError(f"expected a JSON object, got {type(value).__name__}")
    return deserialize_sources(cast(dict[str, Any], value), None)


def parse_row(project_id: str, row: dict[str, Any]) -> BrainSession:
    """The typed session of a persisted row, without its deck and deliveries."""

    revision = row.get("revision_id")
    try:
        return BrainSession(
            project_id=project_id,
            session_id=_column(project_id, row, "id", str),
            version=_column(project_id, row, "version", _count),
            history=_column(
                project_id, row, "history_json", lambda v: deserialize_history(_list(v))
            ),
            sources=_column(project_id, row, "sources_json", _sources),
            revision_id=str(revision) if revision else None,
            package=_column(project_id, row, "package", GenerationPackage),
            formats=_column(project_id, row, "formats_json", parse_export_formats),
            approval_state=_column(project_id, row, "approval_state", ApprovalState),
            pending_action=_column(project_id, row, "pending_action_json", _pending_action),
            parked_operation_id=_column(project_id, row, "parked_operation_id", _operation),
            inline_fixes_used=_column(project_id, row, "fixes_used", _count),
            accumulated_cost_usd=_column(project_id, row, "accumulated_cost_usd", _amount),
            accumulated_image_count=_column(project_id, row, "accumulated_image_count", _count),
            delivery_notes=_column(
                project_id,
                row,
                "delivery_notes_json",
                lambda v: [DeliveryNote.model_validate(item) for item in _list(v)],
            ),
            figures_loaded=False,
        )
    except ValueError as exc:  # the assembled session breaks a model constraint
        raise _invalid(project_id, "session", str(exc)) from None


def columns_of(session: BrainSession) -> dict[str, object]:
    """The JSON value of every writable column, as the session now holds it."""

    light, _figures = serialize_sources(session.sources)
    return {
        "history_json": serialize_history(session.history),
        "sources_json": light,
        "package": session.package.value,
        "formats_json": [fmt.value for fmt in session.formats],
        "approval_state": session.approval_state.value,
        "pending_action_json": (
            session.pending_action.model_dump(mode="json") if session.pending_action else None
        ),
        "parked_operation_id": session.parked_operation_id,
        "fixes_used": session.inline_fixes_used,
        "accumulated_cost_usd": session.accumulated_cost_usd,
        "accumulated_image_count": session.accumulated_image_count,
        "revision_id": session.revision_id,
        "delivery_notes_json": [note.model_dump(mode="json") for note in session.delivery_notes],
    }


def columns_from_row(row: dict[str, Any]) -> dict[str, object]:
    """The JSON value of every writable column, as the row holds it."""

    values: dict[str, object] = {column: row.get(column) for column in COLUMNS}
    for column in ("revision_id", "parked_operation_id"):
        if values[column] is not None:
            values[column] = str(values[column])
    return values


def _is_answer(content: object) -> bool:
    """A serialized user turn made only of function responses."""

    if not isinstance(content, dict):
        return False
    body = cast(dict[str, Any], content)
    parts: object = body.get("parts")
    if body.get("role") != "user" or not isinstance(parts, list) or not parts:
        return False
    return all(
        isinstance(part, dict) and "function_response" in cast(dict[str, Any], part)
        for part in cast(list[object], parts)
    )


def _merge_history(
    project_id: str, base: list[Any], ours: list[Any], theirs: list[Any]
) -> list[Any]:
    if ours == base:
        return theirs
    if theirs == base or ours == theirs:
        return ours
    size = len(base)
    if ours[:size] != base or theirs[:size] != base:
        raise SessionConflictError(project_id, "history_rewritten")
    our_tail, their_tail = ours[size:], theirs[size:]
    if their_tail[: len(our_tail)] == our_tail:
        return theirs
    if our_tail[: len(their_tail)] == their_tail:
        return ours
    # A session parked before operation ids (B1-FIX4) answered by both sides:
    # theirs came first and the conversation continued from it, so ours is dropped.
    if len(our_tail) == 1 and _is_answer(our_tail[0]) and their_tail and _is_answer(their_tail[0]):
        return theirs
    raise SessionConflictError(project_id, "history_diverged")


def _only_answered(base: list[Any], ours: list[Any]) -> bool:
    """True when this writer's only change to the conversation is one answer turn."""

    tail = ours[len(base) :]
    return ours[: len(base)] == base and len(tail) == 1 and _is_answer(tail[0])


def _notes(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [cast(dict[str, Any], n) for n in cast(list[object], value) if isinstance(n, dict)]


def _merge_notes(ours: object, theirs: object) -> list[dict[str, Any]]:
    their_notes = _notes(theirs)
    seen = {str(note.get("job_id")) for note in their_notes}
    added = [note for note in _notes(ours) if str(note.get("job_id")) not in seen]
    return [*their_notes, *added][-_MAX_NOTES:]


def merge(
    project_id: str,
    base: dict[str, object],
    ours: dict[str, object],
    theirs: dict[str, object],
) -> dict[str, object]:
    """Three-way merge of a session write that lost its compare-and-swap."""

    merged: dict[str, object] = {}
    parked = base.get("parked_operation_id")
    if (
        parked is not None
        and ours.get("parked_operation_id") != parked != theirs.get("parked_operation_id")
        and _only_answered(_list(base.get("history_json")), _list(ours.get("history_json")))
    ):
        # Both sides answered the same parked call (B1-FIX4) and answering is all
        # this writer did: the row answered it first, so this answer is a duplicate
        # and is dropped with the parked/approval state it implied (theirs may have
        # parked the next call already). Everything else this writer changed still
        # merges. A writer that also continued the conversation falls through to the
        # history merge, which keeps it only if the row's answer is the same turn.
        answered = {column: theirs.get(column) for column in _ANSWER_COLUMNS}
        ours, base = {**ours, **answered}, {**base, **answered}
    for column in COLUMNS:
        b, o, t = base.get(column), ours.get(column), theirs.get(column)
        if column == "history_json":
            merged[column] = _merge_history(project_id, _list(b), _list(o), _list(t))
        elif column == "delivery_notes_json":
            merged[column] = _merge_notes(o, t)
        elif column in _ADDITIVE:
            delta = cast(float, o or 0) - cast(float, b or 0)
            total = cast(float, t or 0) + delta
            merged[column] = int(total) if column != "accumulated_cost_usd" else total
        else:
            merged[column] = o if o != b else t
    return merged


def dangling_call_parts(session: BrainSession) -> int:
    """Unanswered ``edit_slides`` call parts at the end of the conversation."""

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


def deck_or_none(content: dict[str, Any] | None) -> DeckSpec | None:
    """The deck a revision holds, or None when its content is not a deck."""

    if content is None:
        return None
    try:
        return DeckSpec.model_validate(content)
    except ValueError:
        return None


__all__ = [
    "COLUMNS",
    "SessionConflictError",
    "SessionDataInvalidError",
    "columns_from_row",
    "columns_of",
    "dangling_call_parts",
    "deck_or_none",
    "merge",
    "parse_row",
]
