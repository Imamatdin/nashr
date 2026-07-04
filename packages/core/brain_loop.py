"""The shared Gemini tool-calling loop the brain runs on (Build 2, Stage 5a).

Both brain paths drive the SAME loop over the SAME ``edit_slides`` tool:

* Way 1 (critic escalation, generation-time) calls it with a focused fix-only
  system prompt and ``tool_mode=ANY`` so the model must emit slide edits.
* Way 2 (conversational editing, session-time) calls it with the assembled
  conversational system and ``tool_mode=AUTO`` so the model may reply *or* edit.

THE FIX-EXIT DISCIPLINE. ``edit_slides`` is a REQUEST, not an action. When the
model calls it, :func:`run_brain_loop` parses the requested fixes and RETURNS
(``kind="fix"``) — it never applies them inside the loop. Applying a fix is the
caller's job, through the guarded delivery path (Way 2's ``_dispatch_fix``
counter/approval/delivery-boundary; Way 1's ``regenerate_slide_content`` +
re-critique). A read-only tool that executes-and-continues does not exist in 5a,
so ``edit_slides`` is the only tool and it always exits the loop.

The loop obeys the verbatim-append rule (:mod:`packages.core.gemini_tools`): the
model's turn is appended to the history byte-for-byte so Gemini 3's
``thought_signature`` survives. History is treated as append-only — a caller that
persists ``BrainLoopResult.history`` may resend it without a 400.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Final, Literal, cast

from google.genai import types as genai_types
from pydantic import ValidationError

from packages.core.gemini import GeminiClient, GeminiToolCallError
from packages.core.gemini_tools import (
    FunctionResult,
    build_function_responses_content,
    build_function_tool,
)
from packages.core.models.presentation import SlideFix

logger = logging.getLogger(__name__)

EDIT_SLIDES_TOOL_NAME: Final[str] = "edit_slides"

# The loop can only iterate on a RETRY (a degraded turn re-tried with a larger
# budget) or a MALFORMED-args re-ask; a clean tool call or a terminal reply exits
# on the first turn. The cap is a runaway backstop, not a normal control knob.
BRAIN_LOOP_MAX_ITERATIONS: Final[int] = 6
_BRAIN_LOOP_MAX_TOKENS: Final[int] = 8192
_BRAIN_LOOP_RETRY_MAX_TOKENS: Final[int] = 16384


class BrainToolArgsError(RuntimeError):
    """The model called ``edit_slides`` with arguments that are not valid fixes.

    Raised at the untyped LLM boundary when the ``fixes`` payload is missing, not
    a non-empty list, or fails :class:`SlideFix` validation. The loop answers it
    with an error ``function_response`` and re-asks (bounded by the iteration cap)
    rather than crashing the turn.
    """


@dataclass(frozen=True)
class BrainLoopResult:
    """The outcome of one :func:`run_brain_loop` call.

    ``kind`` is ``"fix"`` when the model requested slide edits (``fixes`` is the
    parsed, non-empty batch) or ``"reply"`` for a terminal text answer / a
    graceful degradation (``reply_text`` may be ``None`` when the loop degraded).
    ``history`` is the append-only conversation INCLUDING the model's final turn
    (verbatim, signature intact); a caller may persist and resend it.
    ``estimated_cost_usd`` sums every turn the loop spent.

    A frozen dataclass, not a pydantic model, because ``history`` holds live
    bytes-bearing SDK ``Content`` — the same reason :class:`TurnOutcome` is one.
    """

    kind: Literal["fix", "reply"]
    fixes: tuple[SlideFix, ...]
    reply_text: str | None
    history: list[genai_types.Content]
    estimated_cost_usd: float
    # The number of edit_slides CALL parts in the terminal model turn. Gemini 3 may
    # emit several calls in one turn (their fixes are merged into ``fixes``); each
    # call part must be answered by its own function_response part downstream, so the
    # dispatch layer needs this count, not len(fixes). Zero on a reply.
    tool_call_count: int = 0


def build_edit_slides_tool() -> genai_types.Tool:
    """Build the ``edit_slides`` tool: request a batch of ``{slide_id, instruction}``.

    One tool, one OBJECT parameter ``fixes`` — an ARRAY of the :class:`SlideFix`
    shape. The model addresses each slide by its stable ``slide_id`` and gives a
    natural-language ``instruction`` the editorial regeneration pass acts on.
    """

    fix_item = genai_types.Schema(
        type=genai_types.Type.OBJECT,
        properties={
            "slide_id": genai_types.Schema(
                type=genai_types.Type.STRING,
                description="Stable id of the slide to edit (never a positional index).",
            ),
            "instruction": genai_types.Schema(
                type=genai_types.Type.STRING,
                description=(
                    "Natural-language edit for this slide, grounded only in the "
                    "provided source claims."
                ),
            ),
        },
        required=["slide_id", "instruction"],
    )
    declaration = genai_types.FunctionDeclaration(
        name=EDIT_SLIDES_TOOL_NAME,
        description=(
            "Request edits to one or more slides. Each fix names a slide by its stable "
            "slide_id and gives an instruction for how to change it. Applied in order; "
            "each edit builds on the previous. Use only source-grounded facts."
        ),
        parameters=genai_types.Schema(
            type=genai_types.Type.OBJECT,
            properties={
                "fixes": genai_types.Schema(
                    type=genai_types.Type.ARRAY,
                    description="The slide edits to apply, in order.",
                    items=fix_item,
                )
            },
            required=["fixes"],
        ),
    )
    return build_function_tool([declaration])


def parse_edit_slides_call(call: genai_types.FunctionCall) -> tuple[SlideFix, ...]:
    """Parse one ``edit_slides`` call's args into a validated :class:`SlideFix` batch.

    ``call.args`` is raw, unvalidated LLM output (the one legitimate ``Any``
    boundary); it is parsed into typed ``SlideFix`` on the next line. Raises
    :class:`BrainToolArgsError` when the payload is missing, empty, or invalid.
    """

    args = call.args
    if not args or "fixes" not in args:
        raise BrainToolArgsError(f"{EDIT_SLIDES_TOOL_NAME} call is missing a 'fixes' argument")
    raw_fixes = args["fixes"]  # raw LLM output at the untyped boundary
    if not isinstance(raw_fixes, list) or not raw_fixes:
        raise BrainToolArgsError(f"{EDIT_SLIDES_TOOL_NAME} 'fixes' must be a non-empty list")
    items = cast("list[object]", raw_fixes)  # each item is validated into SlideFix below
    try:
        return tuple(SlideFix.model_validate(item) for item in items)
    except ValidationError as exc:
        raise BrainToolArgsError(
            f"{EDIT_SLIDES_TOOL_NAME} 'fixes' failed validation: {exc}"
        ) from exc


def _collect_edit_slides_fixes(
    calls: list[genai_types.FunctionCall],
) -> tuple[SlideFix, ...]:
    """Merge every ``edit_slides`` call in one model turn into a single fix batch."""

    edits = [call for call in calls if call.name == EDIT_SLIDES_TOOL_NAME]
    if not edits:
        raise BrainToolArgsError(
            f"expected an {EDIT_SLIDES_TOOL_NAME} call; got {[call.name for call in calls]}"
        )
    fixes: list[SlideFix] = []
    for call in edits:
        fixes.extend(parse_edit_slides_call(call))
    return tuple(fixes)


def _tool_error_responses(
    calls: list[genai_types.FunctionCall], message: str
) -> genai_types.Content:
    """Re-ask after malformed args: ONE error function_response per call part.

    A turn may carry several edit_slides call parts; Gemini requires every one
    answered, so answering only one (when N were emitted) under-answers the history
    and 400s the retry. One error part per call keeps the re-ask request valid.
    """

    return build_function_responses_content(
        [
            FunctionResult(name=call.name or EDIT_SLIDES_TOOL_NAME, response={"error": message})
            for call in calls
        ]
    )


async def run_brain_loop(
    gemini: GeminiClient,
    *,
    history: list[genai_types.Content],
    system: str,
    tool_mode: genai_types.FunctionCallingConfigMode = (genai_types.FunctionCallingConfigMode.AUTO),
    allowed_function_names: list[str] | None = None,
    max_iterations: int = BRAIN_LOOP_MAX_ITERATIONS,
    max_tokens: int = _BRAIN_LOOP_MAX_TOKENS,
    retry_max_tokens: int = _BRAIN_LOOP_RETRY_MAX_TOKENS,
) -> BrainLoopResult:
    """Drive the ``edit_slides`` tool loop and return on the first fix or reply.

    Exits ``kind="fix"`` the moment the model requests edits (the fix-exit
    discipline — the caller applies them), ``kind="reply"`` on a terminal text
    turn, and degrades to a ``kind="reply"`` (``reply_text=None``) if a turn stays
    degraded after a larger-budget retry or the iteration cap is hit. Never
    applies a fix, never hangs. ``history`` is copied, not mutated.
    """

    tool = build_edit_slides_tool()
    working = list(history)
    total_cost = 0.0
    budget = max_tokens
    for _iteration in range(max_iterations):
        try:
            result = await gemini.generate_with_tools(
                working,
                [tool],
                system=system,
                tool_mode=tool_mode,
                allowed_function_names=allowed_function_names,
                max_tokens=budget,
            )
        except GeminiToolCallError:
            if budget < retry_max_tokens:
                budget = retry_max_tokens
                logger.warning("brain_loop_retry_larger_budget", extra={"max_tokens": budget})
                continue
            logger.warning("brain_loop_degraded_giving_up")
            return BrainLoopResult("reply", (), None, working, total_cost)
        total_cost += result.estimated_cost_usd
        working = [*working, result.model_content]  # APPEND RULE: verbatim, signature intact
        if not result.wants_tool:
            return BrainLoopResult("reply", (), result.text, working, total_cost)
        try:
            fixes = _collect_edit_slides_fixes(result.function_calls)
        except BrainToolArgsError as exc:
            working = [*working, _tool_error_responses(result.function_calls, str(exc))]
            logger.warning("brain_loop_bad_tool_args", extra={"error": str(exc)})
            continue
        call_count = sum(1 for c in result.function_calls if c.name == EDIT_SLIDES_TOOL_NAME)
        return BrainLoopResult(
            "fix", fixes, result.text, working, total_cost, tool_call_count=call_count
        )
    logger.warning("brain_loop_max_iterations_reached", extra={"max_iterations": max_iterations})
    return BrainLoopResult("reply", (), None, working, total_cost)


__all__ = [
    "BRAIN_LOOP_MAX_ITERATIONS",
    "EDIT_SLIDES_TOOL_NAME",
    "BrainLoopResult",
    "BrainToolArgsError",
    "build_edit_slides_tool",
    "parse_edit_slides_call",
    "run_brain_loop",
]
