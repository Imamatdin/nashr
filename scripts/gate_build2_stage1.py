"""Live droplet gate for Build 2, Stage 1 — the tool-calling transport.

Proves the thing the unit suite structurally cannot: that a REAL Gemini 3 Pro
``thought_signature`` (not constructed test bytes) is produced, can be resent
verbatim without a 400, and survives a store-and-reload through
``serialize_history`` -> JSON -> ``deserialize_history``. It then runs a NEGATIVE
CONTROL — dropping the signature on the resend — and proves that the call is
*rejected*, which is what makes the positive result meaningful: it shows the
signature is load-bearing and that preserving it is what keeps the conversation
valid.

The checks, in order:

  1. Turn 1: a tool call comes back AND the model turn carries a real
     ``thought_signature`` (load-bearing — without this the round-trip below is
     vacuous).
  2. Turn 2: appending that model turn verbatim + a function_response and calling
     again is ACCEPTED (no 400) — the live signature was preserved and resent.
  3. Reload: serialize -> JSON string -> reload reproduces the signature
     byte-for-byte, and the reloaded history is ACCEPTED on a fresh call (no 400)
     — a REAL signature survives store-and-reload.
  4. Negative control: the same resend with the signature dropped is REJECTED
     (HTTP 400). If the endpoint does not reject it, that is reported as a
     finding (the positive claim is then weaker), not silently skipped.

Run from the repo root with live Vertex creds:

    set VERTEX_PROJECT=...        # Vertex AI + ADC (gcloud auth ... login)
    # or, for AI Studio instead of Vertex: set GOOGLE_API_KEY=...
    python scripts/gate_build2_stage1.py

Exit 0 iff every check passes; 1 on any failure; 2 if creds are missing.

If turn 1 does not call the tool under AUTO, flip ``_TURN1_TOOL_MODE`` to ANY
(thinking — and thus the signature — is independent of tool mode) and re-run.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from google.genai import errors as genai_errors  # noqa: E402
from google.genai import types as genai_types  # noqa: E402

from packages.core.gemini import (  # noqa: E402
    GEMINI_PRO_3_1_MODEL,
    GeminiClient,
    GeminiToolCallError,
)
from packages.core.gemini_tools import (  # noqa: E402
    FunctionResult,
    build_function_responses_content,
    build_function_tool,
    deserialize_history,
    serialize_history,
)

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # python-dotenv is optional; env may be exported directly.
    pass


_SYSTEM = (
    "You are a precise assistant. When a tool can answer the user, call it, then report the value."
)
_MAX_TOKENS = (
    8192  # Gemini 3 Pro needs headroom to think; the signature is a by-product of thinking.
)

# AUTO mirrors the brain's real path (the model decides to call). If a run shows
# turn 1 did not call the tool, switch to ANY to force it — the signature checks
# stay valid either way.
_TURN1_TOOL_MODE = genai_types.FunctionCallingConfigMode.AUTO


class _GateReporter:
    """Collects pass/fail checks so every assertion runs and is reported."""

    def __init__(self) -> None:
        self.failures = 0

    def check(self, label: str, ok: bool, detail: str = "") -> None:
        mark = "PASS" if ok else "FAIL"
        suffix = f" — {detail}" if detail else ""
        print(f"  [{mark}] {label}{suffix}")
        if not ok:
            self.failures += 1


def _get_value_tool() -> genai_types.Tool:
    """A trivial one-arg tool the model can call to fetch a stored value."""

    return build_function_tool(
        [
            genai_types.FunctionDeclaration(
                name="get_value",
                description="Return the stored value for a given key.",
                parameters=genai_types.Schema(
                    type=genai_types.Type.OBJECT,
                    properties={
                        "key": genai_types.Schema(
                            type=genai_types.Type.STRING,
                            description="The key to look up.",
                        )
                    },
                    required=["key"],
                ),
            )
        ]
    )


def _signatures(content: genai_types.Content) -> list[bytes]:
    """Every non-empty ``thought_signature`` on a model turn's parts."""

    return [p.thought_signature for p in (content.parts or []) if p.thought_signature]


def _strip_signatures(content: genai_types.Content) -> genai_types.Content:
    """Copy a model turn with every ``thought_signature`` removed (negative control)."""

    stripped_parts = [
        part.model_copy(update={"thought_signature": None}) for part in (content.parts or [])
    ]
    return content.model_copy(update={"parts": stripped_parts})


async def _run_gate(
    client: GeminiClient, strict_client: GeminiClient, reporter: _GateReporter
) -> float:
    """Run the four checks; return the total live cost in USD."""

    tool = _get_value_tool()
    total_cost = 0.0
    user_turn = genai_types.Content(
        role="user",
        parts=[
            genai_types.Part(
                text=(
                    "I need the stored value for the key 'answer'. Call the get_value "
                    "tool to look it up, then tell me the value."
                )
            )
        ],
    )

    # --- Check 1: turn 1 yields a tool call carrying a real signature ---
    turn1 = await client.generate_with_tools(
        [user_turn], [tool], system=_SYSTEM, max_tokens=_MAX_TOKENS, tool_mode=_TURN1_TOOL_MODE
    )
    total_cost += turn1.estimated_cost_usd
    reporter.check(
        "turn 1 — model requested a function call",
        turn1.wants_tool,
        f"function_calls={[c.name for c in turn1.function_calls]}, finish={turn1.finish_reason}",
    )
    sigs = _signatures(turn1.model_content)
    reporter.check(
        "turn 1 — model turn carries a thought_signature (load-bearing)",
        bool(sigs),
        f"signature byte-lengths={[len(s) for s in sigs]}",
    )
    if not turn1.wants_tool or not sigs:
        print("\nGATE ABORTED: turn 1 did not yield a signed function call; nothing to round-trip.")
        return total_cost

    real_sig = sigs[0]
    call_name = turn1.function_calls[0].name
    if call_name is None:  # FunctionCall.name is Optional in the SDK; a nameless call is unusable.
        reporter.check("turn 1 — function call has a name", False, "function_call.name was None")
        return total_cost
    tool_response = build_function_responses_content(
        [FunctionResult(name=call_name, response={"value": "42"})]
    )
    # The model turn is appended VERBATIM — the signature rides on it untouched.
    history_after = [user_turn, turn1.model_content, tool_response]

    # --- Check 2: resend the real signature; must NOT 400 ---
    try:
        turn2 = await client.generate_with_tools(
            [*history_after], [tool], system=_SYSTEM, max_tokens=_MAX_TOKENS
        )
        total_cost += turn2.estimated_cost_usd
        reporter.check(
            "turn 2 — verbatim resend of real signature accepted (no 400)",
            True,
            f"text={turn2.text!r}",
        )
    except genai_errors.APIError as exc:
        reporter.check(
            "turn 2 — verbatim resend of real signature accepted (no 400)",
            False,
            f"{type(exc).__name__} code={getattr(exc, 'code', None)}: {exc}",
        )

    # --- Check 3: serialize -> JSON -> reload, byte-identical, still accepted ---
    blob = json.dumps(serialize_history(history_after))
    reloaded = deserialize_history(json.loads(blob))
    reloaded_sig = next(
        (s for content in reloaded for s in _signatures(content)),
        None,
    )
    reporter.check(
        "reload — signature byte-identical after serialize -> JSON -> reload",
        reloaded_sig == real_sig,
        f"orig len={len(real_sig)}, reloaded len={len(reloaded_sig) if reloaded_sig else 0}",
    )
    try:
        turn3 = await client.generate_with_tools(
            reloaded, [tool], system=_SYSTEM, max_tokens=_MAX_TOKENS
        )
        total_cost += turn3.estimated_cost_usd
        reporter.check(
            "reload — reloaded history accepted (no 400): REAL signature survived store+reload",
            True,
            f"text={turn3.text!r}",
        )
    except genai_errors.APIError as exc:
        reporter.check(
            "reload — reloaded history accepted (no 400)",
            False,
            f"{type(exc).__name__} code={getattr(exc, 'code', None)}: {exc}",
        )

    # --- Check 4 (negative control): dropped signature MUST be rejected (400) ---
    corrupted = [user_turn, _strip_signatures(turn1.model_content), tool_response]
    try:
        # strict_client has max_retries=0 so a permanent 400 surfaces on the first attempt.
        await strict_client.generate_with_tools(
            corrupted, [tool], system=_SYSTEM, max_tokens=_MAX_TOKENS
        )
        reporter.check(
            "negative control — dropped signature rejected (expected 400)",
            False,
            "no error raised — endpoint did NOT enforce the signature; positive claim is weaker",
        )
    except genai_errors.APIError as exc:
        code = getattr(exc, "code", None)
        reporter.check(
            "negative control — dropped signature rejected (expected 400)",
            code == 400,
            f"got code={code}",
        )
    except GeminiToolCallError as exc:
        reporter.check(
            "negative control — dropped signature rejected (expected 400)",
            False,
            f"surfaced as GeminiToolCallError, not a 400: {exc}",
        )

    return total_cost


async def _amain() -> int:
    if not (
        os.environ.get("VERTEX_PROJECT")
        or os.environ.get("GOOGLE_API_KEY")
        or os.environ.get("GEMINI_API_KEY")
    ):
        print(
            "Set VERTEX_PROJECT (Vertex AI + ADC) — or GOOGLE_API_KEY / GEMINI_API_KEY for AI "
            "Studio. This gate runs real Gemini 3.1 Pro tool calls."
        )
        return 2

    reporter = _GateReporter()
    client = GeminiClient()
    strict_client = GeminiClient(max_retries=0)
    print(f"Gate model: {GEMINI_PRO_3_1_MODEL}")
    try:
        total_cost = await _run_gate(client, strict_client, reporter)
    except (genai_errors.APIError, GeminiToolCallError) as exc:
        print(f"\nGATE ERRORED before completion: {type(exc).__name__}: {exc}")
        return 1

    print(f"\nTotal live cost (USD): {total_cost:.6f}")
    if reporter.failures:
        print(f"\nGATE FAILED: {reporter.failures} check(s) failed.")
        return 1
    print(
        "\nGATE PASSED: a real thought_signature was produced, resent verbatim, and survived "
        "serialize -> reload; the dropped-signature resend was rejected."
    )
    return 0


def main() -> int:
    return asyncio.run(_amain())


if __name__ == "__main__":
    sys.exit(main())
