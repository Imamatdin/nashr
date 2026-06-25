"""Manual (declaration-only) tool-calling primitives for the Gemini transport.

This module holds the *caller-facing* pieces of Build 2's tool-calling spine —
the typed turn result, the conversation-history serialization, and the helper
that hands tool results back to the model. The actual SDK call lives on
:meth:`packages.core.gemini.GeminiClient.generate_with_tools`; these are the
pure, client-independent parts kept here so ``gemini.py`` stays focused on the
transport itself.

The brain (a later build stage) drives a multi-turn loop on top of the
single-turn primitive. The protocol it must follow — and the one footgun that
silently corrupts Gemini 3 conversations — is documented here because this is
where the conversation state is shaped and persisted.

The verbatim-append cycle
--------------------------
Gemini 3 attaches an opaque ``thought_signature`` (raw bytes) to the parts of a
model turn that emits a function call. On the *next* request the model requires
that signature back, byte-for-byte, or it returns HTTP 400. So the loop is:

1. ``result = await client.generate_with_tools(history, tools, ...)``
2. If ``result.wants_tool``: append ``result.model_content`` to ``history``
   **VERBATIM** (the exact :class:`~google.genai.types.Content` the SDK
   returned — never hand-reconstruct it, or the signature is lost), run the
   tool(s), then append :func:`build_function_responses_content` with one entry
   per call, and go to 1.
3. Otherwise the model finished without a tool call: ``result.text`` is the
   answer. A DEGRADED terminal turn (truncated, malformed, or blocked) never
   reaches this branch — ``generate_with_tools`` raises
   :class:`~packages.core.gemini.GeminiToolCallError` for it rather than
   returning a result whose ``wants_tool`` is falsely ``False``, so the caller's
   ``if not result.wants_tool: deliver result.text`` path cannot ship truncated
   or blocked output as a finished answer.

The serialization footgun
--------------------------
``thought_signature`` is ``bytes``. A naive ``json.dumps`` of a Content's
``model_dump(mode="python")`` raises ``TypeError`` because raw bytes are not
JSON-serializable. The discipline — enforced by :func:`serialize_history` — is
that history is **only ever** serialized via ``Content.model_dump(mode="json")``,
which base64-encodes bytes (the SDK base model sets ``ser_json_bytes='base64'``
/ ``val_json_bytes='base64'``), so it round-trips byte-for-byte through
:func:`deserialize_history`. Never serialize a Content any other way.
"""

from __future__ import annotations

from dataclasses import dataclass

from google.genai import types as genai_types
from pydantic import BaseModel, ConfigDict, Field


@dataclass(frozen=True)
class ToolTurnResult:
    """The outcome of ONE manual tool-calling turn (one ``generate_content`` call).

    A transient transport value, not a persisted model: it holds live SDK
    handles (:class:`~google.genai.types.Content`, the function-call list, the
    finish reason) and is intentionally a frozen dataclass rather than a
    pydantic model — wrapping the bytes-bearing ``Content`` in a pydantic field
    would re-validate it on construction for no benefit. The durable form of a
    conversation is :func:`serialize_history` over the ``Content`` list, which
    honours the project's "everything serializes losslessly" rule through the
    proper SDK channel.

    ``model_content`` is the model's full turn and MUST be appended to the
    history verbatim when :attr:`wants_tool` is true (see the module docstring).
    ``function_calls`` is the full list — Gemini 3 may emit several calls in one
    turn — so the caller answers each with one entry in
    :func:`build_function_responses_content`. A ``ToolTurnResult`` only ever
    represents a USABLE turn: a tool request (``wants_tool``) or a clean
    completion (``finish_reason`` ``STOP`` / ``FINISH_REASON_UNSPECIFIED`` /
    ``None``). A degraded terminal turn never becomes a result —
    ``generate_with_tools`` raises instead — so ``wants_tool`` is a signal the
    caller can trust.
    """

    model_content: genai_types.Content
    function_calls: list[genai_types.FunctionCall]
    text: str | None
    finish_reason: genai_types.FinishReason | None
    model: str
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float
    latency_ms: int

    @property
    def wants_tool(self) -> bool:
        """True when the model emitted at least one function call to run."""

        return bool(self.function_calls)


class FunctionResult(BaseModel):
    """One tool's output, to be returned to the model as a ``function_response``.

    ``response`` is the tool's result payload. It is typed ``dict[str, object]``
    rather than a domain model because it is the boundary handed straight to the
    SDK's ``Part.from_function_response`` (whose ``response`` is free-form JSON):
    different tools return different shapes, and the transport forwards whatever
    the tool produced without interpreting it. The brain validates each tool's
    own result before constructing this; here it is opaque JSON.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=128)
    response: dict[str, object] = Field(default_factory=dict)


def build_function_responses_content(
    results: list[FunctionResult],
) -> genai_types.Content:
    """Build the single user-role Content that returns N tool outputs to the model.

    The protocol requires **one** Content carrying one ``function_response`` part
    per call — name-matched, in the order the calls arrived — NOT one Content per
    result. This mirrors :attr:`ToolTurnResult.function_calls` being a list:
    answer a multi-call turn with a single Content of multiple parts.

    Raises :class:`ValueError` on an empty list — an empty function-response turn
    is never valid and would otherwise produce a partless Content the API rejects.
    """

    if not results:
        raise ValueError("build_function_responses_content requires at least one FunctionResult")
    parts = [
        genai_types.Part.from_function_response(name=result.name, response=result.response)
        for result in results
    ]
    return genai_types.Content(role="user", parts=parts)


def build_function_tool(
    declarations: list[genai_types.FunctionDeclaration],
) -> genai_types.Tool:
    """Wrap function declarations in a single :class:`~google.genai.types.Tool`.

    Thin sugar so callers (the gate, and the brain later) express intent without
    repeating the ``Tool(function_declarations=...)`` shape at every call site.
    """

    return genai_types.Tool(function_declarations=declarations)


def serialize_history(history: list[genai_types.Content]) -> list[dict[str, object]]:
    """Serialize a tool-calling history to a JSON-safe structure for the session store.

    Every Content goes through ``model_dump(mode="json")`` — the ONLY safe path:
    it base64-encodes ``thought_signature`` (raw bytes) so the result is plain
    JSON, where a naive dump of the native ``bytes`` would raise ``TypeError``
    (see the module docstring). ``exclude_none=True`` drops the SDK ``Part``'s
    many unset optional fields, which round-trips identically and keeps the
    stored payload small. No ``by_alias`` is needed: the SDK base model sets
    ``populate_by_name=True``, so snake-case keys reload cleanly via
    :func:`deserialize_history`.
    """

    return [content.model_dump(mode="json", exclude_none=True) for content in history]


def deserialize_history(data: list[dict[str, object]]) -> list[genai_types.Content]:
    """Reconstruct a tool-calling history produced by :func:`serialize_history`.

    ``Content.model_validate`` decodes the base64 ``thought_signature`` back to
    the exact original bytes (``val_json_bytes='base64'`` on the SDK base model),
    so a stored-then-reloaded model turn can be resent without a 400.
    """

    return [genai_types.Content.model_validate(item) for item in data]
