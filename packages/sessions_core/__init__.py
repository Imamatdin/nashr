"""Brain-session chat machinery shared by the bot, the API and the worker.

The Way-2 editing loop was built inside ``packages/bot/handlers/presentation_flow``
and is therefore reachable only from Telegram. This package lifts the parts that
are not Telegram — load → turn → gate → park → apply — so the web API can drive
the same session without importing a bot HANDLER.

Layering: the API imports THIS package and ``packages.bot.sessions`` (typed
session objects + store); it never imports ``packages.bot.handlers`` and never
constructs an orchestrator. The orchestrator arrives at the one function that
needs it (:func:`~packages.sessions_core.chat.dispatch_fix`, worker-side) as an
injected :class:`~packages.sessions_core.chat.FixRunner`.

Known debt, deliberately not paid here: the bot's own ``_dispatch_fix`` is left
untouched, so the fix-apply logic exists twice (the bot's copy additionally
stashes local files for Telegram delivery, which the web path has no use for).
Rewiring the bot onto this core is a follow-on with its own gate.
"""

from __future__ import annotations

from packages.sessions_core.chat import (
    ChatSessionView,
    FixDispatchResult,
    FixRunner,
    PendingActionView,
    TurnKind,
    TurnResult,
    abandon_parked_fix,
    dispatch_fix,
    park_pending_for_apply,
    read_session,
    reject_pending,
    run_web_turn,
)

__all__ = [
    "ChatSessionView",
    "FixDispatchResult",
    "FixRunner",
    "PendingActionView",
    "TurnKind",
    "TurnResult",
    "abandon_parked_fix",
    "dispatch_fix",
    "park_pending_for_apply",
    "read_session",
    "reject_pending",
    "run_web_turn",
]
