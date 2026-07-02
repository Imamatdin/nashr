"""Prompt SLOTS for the Build 2 brain (Stage 5a wires the slots; Iko fills the text).

Two system blocks are assembled from these constants:

* Way 2 (conversational editing) — :func:`assemble_brain_system` concatenates
  ``BRAIN_STANDARD`` + ``BRAIN_IDENTITY`` + ``BRAIN_ORCHESTRATOR`` +
  ``BRAIN_TOOL_DESCRIPTIONS`` into one FULLY STATIC system string (no per-turn
  content — the deck roster / source claims ride the conversation history, per
  the append-only rule in :mod:`packages.core.brain_loop`). Static so it caches
  cleanly once Gemini ``cached_content`` is wired in 5b.
* Way 1 (critic escalation) — ``BRAIN_FIX_ONLY_SYSTEM`` is the short, focused
  fix prompt; the findings / flagged slides / source claims ride that pass's one
  user turn.

Slot ownership. ``BRAIN_STANDARD`` / ``BRAIN_IDENTITY`` / ``BRAIN_ORCHESTRATOR``
are the brain's CHARACTER and STANDARD — Iko's external design artifacts; the
placeholders below are deliberately NOT real prompt text and must be replaced.
``BRAIN_TOOL_DESCRIPTIONS`` and ``BRAIN_FIX_ONLY_SYSTEM`` carry functional
operational defaults (mechanical grounding directives, not character) so Way 1
grounds and Way 2 routes correctly before Iko's polish; refine, don't rewrite.
``BRAIN_RETRIEVAL`` / ``BRAIN_MEMORY`` are 5b slots — defined but unused in 5a.

Follows the module-level ``str`` constant convention of :mod:`packages.core.prompts`.
"""

from __future__ import annotations

# --- Character / standard: IKO FILLS. Do not invent the brain's voice here. ---

BRAIN_STANDARD: str = "[IKO FILLS: the quality standard every edit and answer must hold.]"

BRAIN_IDENTITY: str = "[IKO FILLS: the brain's conversational identity — who it is to the user.]"

BRAIN_ORCHESTRATOR: str = (
    "[IKO FILLS: orchestration guidance — how the brain decides to answer vs. edit, "
    "and how it sequences its work across a conversation.]"
)

# --- Operational defaults (mechanical, not character): refine, don't rewrite. ---

BRAIN_TOOL_DESCRIPTIONS: str = """TOOL: edit_slides
Call edit_slides when the user asks you to change the deck — reword, fix, add, remove, or restructure a slide. Provide one fix per slide, each with the slide's stable slide_id (from the deck roster in the conversation) and a clear natural-language instruction. The editorial engine applies your instructions and re-renders the deck; you do not render slides yourself. Ground every edit only in the source claims shown to you — never introduce a fact, statistic, name, date, or citation the sources do not support. When the user is only asking a question or chatting, reply in text and do NOT call the tool."""

BRAIN_FIX_ONLY_SYSTEM: str = """You are a source-grounding fixer for an academic slide deck. You are given: (1) GROUNDING FINDINGS flagging slides whose claims the source does not support, (2) the current content of each flagged slide, and (3) the pool of verified SOURCE CLAIMS.

Your only job: call the edit_slides tool with one fix per flagged slide. Each fix's instruction must make that slide's claims fully supported by the SOURCE CLAIMS — either by replacing the unsupported statement with a grounded one drawn from the claims, or by removing the unsupported claim entirely. Never introduce a fact that is not in the SOURCE CLAIMS. Do not invent statistics, names, dates, or citations. If a flagged claim cannot be grounded from the SOURCE CLAIMS, instruct the slide to drop it rather than soften it.

Call edit_slides exactly once, with a fix for every flagged slide. Do not reply with prose."""

# --- 5b slots: defined but unused in Stage 5a. ---

BRAIN_RETRIEVAL: str = "[IKO FILLS (5b): source-retrieval tool guidance.]"

BRAIN_MEMORY: str = "[IKO FILLS (5b): cross-session memory guidance.]"


def assemble_brain_system() -> str:
    """Assemble the Way 2 conversational system block (fully static).

    Concatenates the standard, identity, orchestration, and tool-description slots
    in a fixed order. Per-turn content (deck roster, source claims, the user
    message) is NOT here — it rides the conversation history so this block stays
    stable and cacheable.
    """

    return "\n\n".join(
        (
            BRAIN_STANDARD,
            BRAIN_IDENTITY,
            BRAIN_ORCHESTRATOR,
            BRAIN_TOOL_DESCRIPTIONS,
        )
    )


__all__ = [
    "BRAIN_FIX_ONLY_SYSTEM",
    "BRAIN_IDENTITY",
    "BRAIN_MEMORY",
    "BRAIN_ORCHESTRATOR",
    "BRAIN_RETRIEVAL",
    "BRAIN_STANDARD",
    "BRAIN_TOOL_DESCRIPTIONS",
    "assemble_brain_system",
]
