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

from dataclasses import dataclass, field
from typing import Protocol

from google.genai import types as genai_types

from packages.bot.sessions.models import BrainSession, TurnAction, TurnOutcome
from packages.core.models.presentation import SlideFix


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
        )


__all__ = ["BrainDriver", "ScriptedStubDriver", "StubResponse"]
