"""DB-backed conversational brain session for presentation editing (Build 2, Stage 4).

This package is the MACHINERY the Stage 5 brain runs in: the typed session
object, its (de)serialization to the ``brain_sessions`` jsonb columns, the
per-session budget cap, and the driver seam (a Protocol the real brain
implements; Stage 4 ships a scripted stub). The chat loop and approval gate that
drive this machinery live in :mod:`packages.bot.handlers.presentation_flow`.
"""

from __future__ import annotations

from packages.bot.sessions.budget import (
    SESSION_FIX_LIMITS,
    has_fixes_remaining,
    session_fix_limit,
    session_total_spend_usd,
)
from packages.bot.sessions.driver import BrainDriver, GeminiBrainDriver, ScriptedStubDriver
from packages.bot.sessions.models import (
    ApprovalState,
    BrainSession,
    PendingAction,
    TurnAction,
    TurnOutcome,
    requires_approval,
)
from packages.bot.sessions.serialization import deserialize_sources, serialize_sources
from packages.bot.sessions.store import (
    create_session,
    hydrate_figures,
    load_session,
    persist_session,
)

__all__ = [
    "SESSION_FIX_LIMITS",
    "ApprovalState",
    "BrainDriver",
    "BrainSession",
    "GeminiBrainDriver",
    "PendingAction",
    "ScriptedStubDriver",
    "TurnAction",
    "TurnOutcome",
    "create_session",
    "deserialize_sources",
    "has_fixes_remaining",
    "hydrate_figures",
    "load_session",
    "persist_session",
    "requires_approval",
    "serialize_sources",
    "session_fix_limit",
    "session_total_spend_usd",
]
