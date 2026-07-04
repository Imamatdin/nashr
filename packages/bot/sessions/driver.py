"""The brain-driver seam and a scripted stub (Build 2, Stage 4).

Stage 4 builds the MACHINERY a brain runs in (load → turn → dispatch tool →
persist → reply); the INTELLIGENCE is Stage 5. :class:`BrainDriver` is the seam
between them — a Protocol the real brain implements by driving the
:func:`packages.core.gemini.GeminiClient.generate_with_tools` loop. Stage 4 ships
:class:`ScriptedStubDriver`, a deterministic stand-in that returns pre-programmed
turns AND appends real ``Content`` to the history, so the persistence and budget
machinery is exercised end-to-end without any model call.

Swapping the stub for the real brain in Stage 5 touches only the driver: the
machinery consumes a :class:`TurnOutcome` and never looks inside.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Final, Protocol

from google.genai import types as genai_types

from packages.bot.sessions.models import BrainSession, TurnAction, TurnOutcome
from packages.bot.sessions.roster_format import render_roster_text
from packages.core.brain_loop import run_brain_loop
from packages.core.brain_prompts import assemble_brain_system
from packages.core.gemini import GeminiClient
from packages.core.models.presentation import SlideFix
from packages.core.models.source import SourceClaimCreate

logger = logging.getLogger(__name__)

# The number of source claims the brain sees per session — mirrors the content
# critic's claim-pool cap. This is a display bound (what the brain reasons over),
# not the grounding check, which still runs against the full claim list.
_BRAIN_CLAIM_CONTEXT_LIMIT: Final[int] = 60


class BrainDriver(Protocol):
    """One conversational turn: given the session and the user's message, decide.

    The real brain (Stage 5) runs a multi-step tool-calling loop here; the
    returned :class:`TurnOutcome` carries the updated history, the turn's cost,
    and the verdict (reply / fix / propose). The implementation MUST return the
    full updated history so the machinery can persist it verbatim.
    """

    async def run_turn(self, session: BrainSession, user_text: str) -> TurnOutcome:
        """Run one turn against ``session`` for ``user_text``."""
        ...


@dataclass
class StubResponse:
    """One scripted turn for :class:`ScriptedStubDriver` to emit, in order."""

    action: TurnAction
    reply_text: str | None = None
    fixes: tuple[SlideFix, ...] = ()
    reason: str | None = None
    estimated_cost_usd: float = 0.0
    # How many edit_slides call parts this scripted turn stands in for (>= 1 when it
    # emits fixes). Lets a test script a multi-call turn so the dispatch layer's
    # one-response-per-call answering is exercised without a real model.
    call_count: int = 1


@dataclass
class ScriptedStubDriver:
    """A deterministic :class:`BrainDriver` stand-in for Stage 4 testing.

    Pops one :class:`StubResponse` per turn from ``script`` (falling back to a
    plain echo reply when the script is empty), then appends a synthetic user and
    model ``Content`` to the history so the round-trip through
    :func:`serialize_history` is genuinely tested. No prompts, no Gemini call —
    that is Stage 5. ``queue`` lets a gate script or test script the next turns.
    """

    script: list[StubResponse] = field(default_factory=list[StubResponse])

    def queue(self, response: StubResponse) -> None:
        """Append a scripted turn to emit on a later call."""

        self.script.append(response)

    async def run_turn(self, session: BrainSession, user_text: str) -> TurnOutcome:
        """Emit the next scripted turn (or an echo), with real history appended."""

        response = (
            self.script.pop(0)
            if self.script
            else StubResponse(action=TurnAction.REPLY, reply_text=f"echo: {user_text}")
        )
        model_text = response.reply_text or response.reason or response.action.value
        new_history = [
            *session.history,
            genai_types.Content(role="user", parts=[genai_types.Part(text=user_text)]),
            genai_types.Content(role="model", parts=[genai_types.Part(text=model_text)]),
        ]
        return TurnOutcome(
            action=response.action,
            history=new_history,
            estimated_cost_usd=response.estimated_cost_usd,
            reply_text=response.reply_text,
            fixes=response.fixes,
            reason=response.reason,
            fix_call_count=response.call_count if response.fixes else 0,
        )


@dataclass
class GeminiBrainDriver:
    """The real conversational brain (Build 2, Stage 5a) — Way 2.

    Drives the shared ``edit_slides`` loop (:func:`packages.core.brain_loop.run_brain_loop`)
    over the session's deck roster + source claims. Holds ONLY a ``GeminiClient``
    — never the orchestrator — so a requested fix can leave the turn ONLY as
    ``TurnOutcome.fixes`` (the fix-exit discipline): applying it is the chat
    loop's guarded job (counter → approval → delivery boundary), structurally
    impossible here. The static system block caches; per-session context rides the
    history once (see :func:`_turn_contents`).
    """

    gemini: GeminiClient
    system: str = field(default_factory=assemble_brain_system)

    async def run_turn(self, session: BrainSession, user_text: str) -> TurnOutcome:
        """Run one turn: answer the user, or REQUEST slide edits (never apply them)."""

        contents = _turn_contents(session, user_text)
        try:
            result = await run_brain_loop(
                self.gemini,
                history=contents,
                system=self.system,
            )
        except Exception as exc:  # a chat turn must never crash the bot — degrade to an apology
            logger.exception("brain_driver_turn_failed", extra={"project_id": session.project_id})
            logger.info(
                "brain_driver_turn %s",
                json.dumps(
                    {
                        "project_id": session.project_id,
                        "action": TurnAction.REPLY.value,
                        "tool_call_count": 0,
                        "estimated_cost_usd": 0.0,
                        "error": type(exc).__name__,
                    },
                    ensure_ascii=False,
                    default=str,
                ),
            )
            return TurnOutcome(action=TurnAction.REPLY, history=session.history, reply_text=None)
        if result.kind == "fix":
            logger.info(
                "brain_driver_turn %s",
                json.dumps(
                    {
                        "project_id": session.project_id,
                        "action": TurnAction.FIX.value,
                        "tool_call_count": result.tool_call_count,
                        "estimated_cost_usd": round(result.estimated_cost_usd, 6),
                        "reply_text": (result.reply_text or "")[:300],
                        "fixes": [
                            {"slide_id": fx.slide_id, "instruction": fx.instruction}
                            for fx in result.fixes
                        ],
                    },
                    ensure_ascii=False,
                    default=str,
                ),
            )
            return TurnOutcome(
                action=TurnAction.FIX,
                history=result.history,
                estimated_cost_usd=result.estimated_cost_usd,
                reply_text=result.reply_text,
                fixes=result.fixes,
                fix_call_count=result.tool_call_count,
            )
        logger.info(
            "brain_driver_turn %s",
            json.dumps(
                {
                    "project_id": session.project_id,
                    "action": TurnAction.REPLY.value,
                    "tool_call_count": 0,
                    "estimated_cost_usd": round(result.estimated_cost_usd, 6),
                    "reply_text": (result.reply_text or "")[:300],
                },
                ensure_ascii=False,
                default=str,
            ),
        )
        return TurnOutcome(
            action=TurnAction.REPLY,
            history=result.history,
            estimated_cost_usd=result.estimated_cost_usd,
            reply_text=result.reply_text,
        )


def _turn_contents(session: BrainSession, user_text: str) -> list[genai_types.Content]:
    """Build the model contents for this turn (append-only; context injected once).

    First turn (empty history): the deck roster + source claims are folded into
    the user turn and persisted, so they live in a stable prefix that is never
    rewritten. Later turns append only the user's message — deck changes reach the
    model through the ``edit_slides`` function_response, never by mutating the
    signed prefix (which would risk a Gemini 3 ``thought_signature`` 400).
    """

    if session.history:
        user_turn = genai_types.Content(role="user", parts=[genai_types.Part(text=user_text)])
        return [*session.history, user_turn]
    opening = f"{_context_block(session)}\n\n---\n\n{user_text}"
    return [genai_types.Content(role="user", parts=[genai_types.Part(text=opening)])]


def _context_block(session: BrainSession) -> str:
    """Render the once-injected deck roster + source-claims context."""

    return (
        "DECK ROSTER (address slides by slide_id):\n"
        f"{render_roster_text(session.deck)}\n\n"
        "SOURCE CLAIMS (ground every edit only in these):\n"
        f"{_render_claims(session.sources.claims)}"
    )


def _render_claims(claims: list[SourceClaimCreate]) -> str:
    if not claims:
        return "(no source claims)"
    capped = claims[:_BRAIN_CLAIM_CONTEXT_LIMIT]
    lines = [f"- {claim.claim_text}" for claim in capped]
    if len(claims) > _BRAIN_CLAIM_CONTEXT_LIMIT:
        lines.append(f"... (+{len(claims) - _BRAIN_CLAIM_CONTEXT_LIMIT} more claims omitted)")
    return "\n".join(lines)


__all__ = ["BrainDriver", "GeminiBrainDriver", "ScriptedStubDriver", "StubResponse"]
