"""Unit tests for the shared brain tool-calling loop (Build 2, Stage 5a).

The loop is exercised against a queue-backed fake that returns canned
``ToolTurnResult``s (or raises), mocking only the Gemini boundary. The behaviours
locked here: the fix-exit discipline (an ``edit_slides`` call exits the loop with
parsed fixes, never applied), terminal text becomes a reply, malformed tool args
are re-asked and then degrade, a degraded turn is retried once with a larger
budget, and the iteration cap halts a runaway.
"""

from __future__ import annotations

from collections.abc import Sequence

import pytest
from google.genai import types as genai_types

from packages.core.brain_loop import (
    BrainToolArgsError,
    build_edit_slides_tool,
    parse_edit_slides_call,
    run_brain_loop,
)
from packages.core.gemini import GeminiToolCallError
from packages.core.gemini_tools import ToolTurnResult

_STOP = genai_types.FinishReason.STOP
_ANY = genai_types.FunctionCallingConfigMode.ANY


def _fix_turn(fixes: list[dict[str, object]], *, cost: float = 0.001) -> ToolTurnResult:
    call = genai_types.FunctionCall(name="edit_slides", args={"fixes": fixes})
    content = genai_types.Content(role="model", parts=[genai_types.Part(function_call=call)])
    return ToolTurnResult(
        model_content=content,
        function_calls=[call],
        text=None,
        finish_reason=_STOP,
        model="fake",
        input_tokens=1,
        output_tokens=1,
        estimated_cost_usd=cost,
        latency_ms=1,
    )


def _multi_fix_turn(
    fix_lists: list[list[dict[str, object]]], *, cost: float = 0.001
) -> ToolTurnResult:
    """A model turn carrying SEVERAL edit_slides call parts (Gemini 3 may do this)."""

    calls = [genai_types.FunctionCall(name="edit_slides", args={"fixes": fl}) for fl in fix_lists]
    content = genai_types.Content(
        role="model", parts=[genai_types.Part(function_call=c) for c in calls]
    )
    return ToolTurnResult(
        model_content=content,
        function_calls=calls,
        text=None,
        finish_reason=_STOP,
        model="fake",
        input_tokens=1,
        output_tokens=1,
        estimated_cost_usd=cost,
        latency_ms=1,
    )


def _reply_turn(text: str, *, cost: float = 0.001) -> ToolTurnResult:
    content = genai_types.Content(role="model", parts=[genai_types.Part(text=text)])
    return ToolTurnResult(
        model_content=content,
        function_calls=[],
        text=text,
        finish_reason=_STOP,
        model="fake",
        input_tokens=1,
        output_tokens=1,
        estimated_cost_usd=cost,
        latency_ms=1,
    )


class _QueueClient:
    """A fake GeminiClient: each ``generate_with_tools`` call pops a queued outcome."""

    def __init__(self, outcomes: Sequence[ToolTurnResult | Exception]) -> None:
        self._outcomes = list(outcomes)
        self.calls: list[dict[str, object]] = []

    async def generate_with_tools(
        self,
        contents: list[genai_types.Content],
        tools: list[genai_types.Tool],
        *,
        system: str | None = None,
        tool_mode: object = None,
        allowed_function_names: list[str] | None = None,
        max_tokens: int | None = None,
        **_: object,
    ) -> ToolTurnResult:
        self.calls.append({"contents": list(contents), "max_tokens": max_tokens})
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _user_history() -> list[genai_types.Content]:
    return [genai_types.Content(role="user", parts=[genai_types.Part(text="fix slide 2")])]


@pytest.mark.asyncio
async def test_fix_call_exits_loop_with_parsed_fixes() -> None:
    client = _QueueClient(
        [_fix_turn([{"slide_id": "slide_02", "instruction": "drop the fake stat"}])]
    )

    result = await run_brain_loop(
        client,  # type: ignore[arg-type]
        history=_user_history(),
        system="sys",
        tool_mode=_ANY,
        allowed_function_names=["edit_slides"],
    )

    assert result.kind == "fix"
    assert len(result.fixes) == 1
    assert result.fixes[0].slide_id == "slide_02"
    assert result.fixes[0].instruction == "drop the fake stat"
    assert result.tool_call_count == 1  # one call part → one response part
    assert result.reply_text is None
    # The model's tool-call turn was appended verbatim; no fix was applied in-loop.
    assert result.history[-1].role == "model"
    assert result.history[-1].parts is not None
    assert result.history[-1].parts[0].function_call is not None
    assert result.estimated_cost_usd == pytest.approx(0.001)
    assert len(client.calls) == 1


@pytest.mark.asyncio
async def test_multiple_edit_slides_calls_merge_and_carry_count() -> None:
    # Two edit_slides call parts in one turn: their fixes merge into one batch, and
    # tool_call_count == 2 so the dispatch layer answers each call part with its own
    # function_response (else the next turn 400s on an under-answered history).
    client = _QueueClient(
        [
            _multi_fix_turn(
                [
                    [{"slide_id": "s1", "instruction": "reword slide 1"}],
                    [{"slide_id": "s2", "instruction": "reword slide 2"}],
                ]
            )
        ]
    )

    result = await run_brain_loop(
        client,  # type: ignore[arg-type]
        history=_user_history(),
        system="sys",
        tool_mode=_ANY,
        allowed_function_names=["edit_slides"],
    )

    assert result.kind == "fix"
    assert len(result.fixes) == 2  # merged from both calls
    assert {f.slide_id for f in result.fixes} == {"s1", "s2"}
    assert result.tool_call_count == 2  # one response part required per call part


@pytest.mark.asyncio
async def test_terminal_text_returns_reply() -> None:
    client = _QueueClient([_reply_turn("Your deck cites Ibn Sina on slide 3.", cost=0.002)])

    result = await run_brain_loop(client, history=_user_history(), system="sys")  # type: ignore[arg-type]

    assert result.kind == "reply"
    assert result.reply_text == "Your deck cites Ibn Sina on slide 3."
    assert result.fixes == ()
    assert result.estimated_cost_usd == pytest.approx(0.002)


@pytest.mark.asyncio
async def test_malformed_args_are_reasked_then_fixes() -> None:
    client = _QueueClient(
        [
            _fix_turn([]),  # empty fixes list — invalid, must be re-asked
            _fix_turn([{"slide_id": "slide_01", "instruction": "cite the source"}]),
        ]
    )

    result = await run_brain_loop(
        client,  # type: ignore[arg-type]
        history=_user_history(),
        system="sys",
        tool_mode=_ANY,
        allowed_function_names=["edit_slides"],
    )

    assert result.kind == "fix"
    assert result.fixes[0].slide_id == "slide_01"
    # Two model turns: an error function_response was fed back between them.
    assert len(client.calls) == 2
    # Cost accrues across both turns.
    assert result.estimated_cost_usd == pytest.approx(0.002)


@pytest.mark.asyncio
async def test_malformed_multi_call_reasks_answering_every_call() -> None:
    # A multi-call turn where one call is malformed: the re-ask must answer EVERY
    # call part (one error response each), else the retry request 400s (under-answered).
    client = _QueueClient(
        [
            _multi_fix_turn([[], [{"slide_id": "s2", "instruction": "ok"}]]),  # 1st call empty
            _fix_turn([{"slide_id": "s2", "instruction": "ok"}]),  # valid on retry
        ]
    )

    result = await run_brain_loop(
        client,  # type: ignore[arg-type]
        history=_user_history(),
        system="sys",
        tool_mode=_ANY,
        allowed_function_names=["edit_slides"],
    )

    assert result.kind == "fix"
    assert len(client.calls) == 2  # re-asked exactly once
    retry_contents = client.calls[1]["contents"]
    error_parts = [
        part
        for content in retry_contents
        for part in (content.parts or [])
        if part.function_response is not None and "error" in (part.function_response.response or {})
    ]
    assert len(error_parts) == 2  # one error response per original call part


@pytest.mark.asyncio
async def test_repeated_malformed_degrades_to_reply_at_cap() -> None:
    client = _QueueClient([_fix_turn([]), _fix_turn([]), _fix_turn([])])

    result = await run_brain_loop(
        client,  # type: ignore[arg-type]
        history=_user_history(),
        system="sys",
        tool_mode=_ANY,
        allowed_function_names=["edit_slides"],
        max_iterations=3,
    )

    assert result.kind == "reply"
    assert result.reply_text is None
    assert result.fixes == ()
    assert len(client.calls) == 3


@pytest.mark.asyncio
async def test_degraded_turn_is_retried_with_larger_budget() -> None:
    client = _QueueClient([GeminiToolCallError("MAX_TOKENS"), _reply_turn("recovered")])

    result = await run_brain_loop(client, history=_user_history(), system="sys")  # type: ignore[arg-type]

    assert result.kind == "reply"
    assert result.reply_text == "recovered"
    assert len(client.calls) == 2
    # The retry bumped the token budget above the first attempt's.
    assert client.calls[1]["max_tokens"] == 16384
    assert client.calls[0]["max_tokens"] == 8192


@pytest.mark.asyncio
async def test_persistently_degraded_gives_up_gracefully() -> None:
    client = _QueueClient([GeminiToolCallError("MAX_TOKENS"), GeminiToolCallError("MAX_TOKENS")])

    result = await run_brain_loop(client, history=_user_history(), system="sys")  # type: ignore[arg-type]

    assert result.kind == "reply"
    assert result.reply_text is None
    assert len(client.calls) == 2


def test_parse_edit_slides_call_valid() -> None:
    call = genai_types.FunctionCall(
        name="edit_slides",
        args={"fixes": [{"slide_id": "s1", "instruction": "reword"}]},
    )
    fixes = parse_edit_slides_call(call)
    assert len(fixes) == 1
    assert fixes[0].slide_id == "s1"


def test_parse_edit_slides_call_missing_fixes_raises() -> None:
    call = genai_types.FunctionCall(name="edit_slides", args={})
    with pytest.raises(BrainToolArgsError):
        parse_edit_slides_call(call)


def test_parse_edit_slides_call_invalid_item_raises() -> None:
    call = genai_types.FunctionCall(
        name="edit_slides",
        args={"fixes": [{"slide_id": "", "instruction": "x"}]},  # slide_id below min_length
    )
    with pytest.raises(BrainToolArgsError):
        parse_edit_slides_call(call)


def test_build_edit_slides_tool_shape() -> None:
    tool = build_edit_slides_tool()
    assert tool.function_declarations is not None
    assert len(tool.function_declarations) == 1
    assert tool.function_declarations[0].name == "edit_slides"
