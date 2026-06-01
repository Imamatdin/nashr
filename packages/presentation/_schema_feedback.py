"""Translate Pydantic ``ValidationError`` detail into model-facing repair text.

Shared by the two LLM retry paths that recover a malformed response by telling
the model EXACTLY which field broke the contract — the planner
(:meth:`packages.presentation.planner.PlannerPass._call_with_retry`) and the
editorial executor
(:meth:`packages.presentation.editorial.EditorialPass._call_editorial_with_retry`).
Both run at temperature 0, where a blind resample re-rolls the same
near-boundary output; the only lever that moves the model off the boundary is
telling it what was wrong. Defined ONCE here so the two paths cannot drift —
the same define-once discipline as ``PEOPLE_RENDERING_SLIDE_TYPES``.

The translation leans on Pydantic's own ``msg``: for an ``enum`` error the
message already enumerates the valid set, and for a length/count error it
states the bound. So there is no hardcoded enum list or numeric cap here to
fall out of sync with the schema — the schema describes itself at runtime.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Final

from pydantic_core import ErrorDetails

# Cap how many errors we translate into a retry prompt / log line. A response
# with more violations than this is malformed beyond targeted repair; we show
# the first N and tell the model to re-check everything. Bounds prompt and log
# growth — the no-unbounded-LLM-input discipline the callers already apply to
# their source views.
MAX_SCHEMA_ERRORS_FEEDBACK: Final[int] = 20
MAX_SCHEMA_ERRORS_LOGGED: Final[int] = 12

# A pydantic error ``loc`` — a path of dict keys (str) and list indices (int).
Loc = tuple[int | str, ...]

# Per-error caveat hook: given an error's ``loc``, return extra guidance to
# append (or ""). Lets a caller add a field-specific note the generic
# translation cannot know — e.g. the planner forbids interactive_* values in
# ``planned_slide_types`` even though they are valid SlideType members.
Caveat = Callable[[Loc], str]


def loc_path(loc: Loc) -> str:
    """Render an error ``loc`` tuple as a dotted field path.

    ``('sections', 0, 'planned_slide_types', 0)`` -> ``sections.0.planned_slide_types.0``.
    """

    return ".".join(str(part) for part in loc)


def summarise_errors(errors: list[ErrorDetails], *, cap: int = MAX_SCHEMA_ERRORS_LOGGED) -> str:
    """Compact ``path (type)`` summary for the log line (and BUILD_STATE).

    Operator-facing: which field, which rule. Distinct from
    :func:`format_schema_feedback`, which is the model-facing repair text.
    Capped so a wildly malformed response cannot blow up the log.
    """

    shown = errors[:cap]
    summary = "; ".join(f"{loc_path(e['loc'])} ({e['type']})" for e in shown)
    if len(errors) > cap:
        summary += f"; (+{len(errors) - cap} more)"
    return summary


def format_schema_feedback(
    errors: list[ErrorDetails],
    *,
    header: str,
    cap: int = MAX_SCHEMA_ERRORS_FEEDBACK,
    caveat: Caveat | None = None,
) -> str:
    """Translate validation errors into model-facing repair instructions.

    The two recurring misreads get an explicit imperative; everything else
    passes Pydantic's ``msg`` through, which is already actionable ("List
    should have at most 8 items after validation, not 9"). ``header`` is the
    caller's framing (which contract failed and how to respond); ``caveat`` adds
    optional per-field guidance the generic translation cannot infer.
    """

    bullets: list[str] = []
    for err in errors[:cap]:
        path = loc_path(err["loc"])
        error_type = err["type"]
        message = err["msg"]
        if error_type == "extra_forbidden":
            field = err["loc"][-1] if err["loc"] else path
            bullets.append(
                f"  - Remove the field `{field}` (at `{path}`). The schema forbids "
                "any field it does not define — emit only the documented fields, "
                "nothing extra."
            )
        elif error_type == "enum":
            note = caveat(err["loc"]) if caveat is not None else ""
            bullets.append(f"  - The value at `{path}` is not allowed. {message}.{note}")
        elif error_type == "missing":
            bullets.append(f"  - Add the required field `{path}`.")
        else:
            bullets.append(f"  - Fix `{path}`: {message}.")
    if len(errors) > cap:
        bullets.append(
            f"  - (+{len(errors) - cap} more schema errors not shown — re-check "
            "every field against the documented schema.)"
        )
    return header + "\n".join(bullets)


__all__ = [
    "MAX_SCHEMA_ERRORS_FEEDBACK",
    "MAX_SCHEMA_ERRORS_LOGGED",
    "Caveat",
    "Loc",
    "format_schema_feedback",
    "loc_path",
    "summarise_errors",
]
