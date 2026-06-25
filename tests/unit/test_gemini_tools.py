"""Behaviour tests for the Gemini tool-calling primitives.

These prove, at the unit level, the discipline that keeps a Gemini 3
conversation intact across a store-and-reload cycle:

* A model turn carrying a function call AND a raw-bytes ``thought_signature``
  survives ``serialize_history`` -> JSON -> ``deserialize_history`` byte-for-byte,
  along with the function_call and function_response payloads.
* The footgun is real and the helper avoids it: a naive ``json.dumps`` of a
  Content's native (``mode="python"``) dump raises ``TypeError`` on the raw
  bytes, while the ``mode="json"`` path used by ``serialize_history`` is safe.
* ``build_function_responses_content`` answers a multi-call turn with ONE
  user-role Content carrying one part per result, name- and order-matched.

The live gate (``scripts/gate_build2_stage1.py``) proves the same round-trip
with a REAL signature from a live call; this file proves it offline with
deliberately non-UTF8 bytes so the discipline is regression-locked.
"""

from __future__ import annotations

import json

import pytest
from google.genai import types as genai_types

from packages.core.gemini_tools import (
    FunctionResult,
    build_function_responses_content,
    deserialize_history,
    serialize_history,
)

# Deliberately non-UTF8: 0x80/0xFE/0xFF never appear in valid UTF-8, so a path
# that round-trips this is not silently relying on text decoding.
_NON_UTF8_SIGNATURE = b"\x80\x81\xfe\xff\x00\x10\x7f"


def _function_call_history() -> list[genai_types.Content]:
    """A 3-turn history: user prompt, model function-call turn, tool response."""

    user_turn = genai_types.Content(
        role="user",
        parts=[genai_types.Part(text="What is the value of 'answer'?")],
    )
    model_turn = genai_types.Content(
        role="model",
        parts=[
            genai_types.Part(
                function_call=genai_types.FunctionCall(name="get_value", args={"key": "answer"}),
                thought_signature=_NON_UTF8_SIGNATURE,
            )
        ],
    )
    tool_turn = build_function_responses_content(
        [FunctionResult(name="get_value", response={"value": "42"})]
    )
    return [user_turn, model_turn, tool_turn]


def test_serialize_history_roundtrip_preserves_non_utf8_signature() -> None:
    history = _function_call_history()

    blob = json.dumps(serialize_history(history))
    reloaded = deserialize_history(json.loads(blob))

    assert len(reloaded) == 3

    model_part = reloaded[1].parts[0]
    assert model_part.thought_signature == _NON_UTF8_SIGNATURE
    assert model_part.function_call is not None
    assert model_part.function_call.name == "get_value"
    assert model_part.function_call.args == {"key": "answer"}

    tool_part = reloaded[2].parts[0]
    assert reloaded[2].role == "user"
    assert tool_part.function_response is not None
    assert tool_part.function_response.name == "get_value"
    assert tool_part.function_response.response == {"value": "42"}


def test_naive_bytes_dump_raises_but_json_mode_roundtrips() -> None:
    """The footgun: raw-bytes signatures break ``json.dumps`` of a native dump."""

    content = genai_types.Content(
        role="model",
        parts=[genai_types.Part(thought_signature=_NON_UTF8_SIGNATURE)],
    )

    # mode="python" keeps thought_signature as raw bytes -> not JSON-serializable.
    with pytest.raises(TypeError):
        json.dumps(content.model_dump(mode="python", exclude_none=True))

    # mode="json" base64-encodes the bytes, so the serialize path is safe and lossless.
    blob = json.dumps(content.model_dump(mode="json", exclude_none=True))
    restored = genai_types.Content.model_validate(json.loads(blob))
    assert restored.parts[0].thought_signature == _NON_UTF8_SIGNATURE


def test_build_function_responses_content_is_one_content_with_n_parts() -> None:
    results = [
        FunctionResult(name="get_value", response={"value": "1"}),
        FunctionResult(name="get_other", response={"value": "2"}),
    ]

    content = build_function_responses_content(results)

    assert content.role == "user"
    assert content.parts is not None
    assert len(content.parts) == 2

    first, second = content.parts
    assert first.function_response is not None
    assert first.function_response.name == "get_value"
    assert first.function_response.response == {"value": "1"}
    assert second.function_response is not None
    assert second.function_response.name == "get_other"
    assert second.function_response.response == {"value": "2"}


def test_build_function_responses_content_rejects_empty() -> None:
    with pytest.raises(ValueError, match="at least one"):
        build_function_responses_content([])
