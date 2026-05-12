"""Rate limiting middleware for the Telegram bot.

Three independent sliding windows per user (in-memory):

  * ``message``  — 30 events per 60 seconds (general chatter)
  * ``upload``   — 5  events per 60 seconds (file uploads)
  * ``generate`` — 3  events per 3600 seconds (paid generations)

The middleware is **soft** in v1: when a limit is exceeded we log a
warning and still pass the event through. This buys observability
without the risk of locking out paying users during the first weeks of
production. The Redis-backed hard limiter is a drop-in replacement that
lands with multi-instance deployment.

Counters are per-process; restarting the bot resets every window. That
trade-off is acceptable because the limits are ceilings, not quotas.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Awaitable, Callable
from time import time
from typing import Any, Final

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

logger = logging.getLogger("nashr.ratelimit")

_GENERATION_CALLBACK_MARKERS: Final[tuple[str, ...]] = ("generate", "tier_", "pay_")


class RateLimitMiddleware(BaseMiddleware):
    """Soft rate limiter for bot dispatcher events.

    The class is intentionally stateful (one counter dict per instance).
    Register a single instance on ``dp.message.middleware()`` AND
    ``dp.callback_query.middleware()`` so message and callback counters
    share the same window — that matches user intuition (a malicious
    user spamming inline buttons does not get to bypass the message
    limit by alternating).
    """

    # Limits: (window_seconds, max_count) keyed by action label.
    LIMITS: Final[dict[str, tuple[int, int]]] = {
        "message": (60, 30),
        "upload": (60, 5),
        "generate": (3600, 3),
    }

    def __init__(self) -> None:
        self._counters: dict[str, list[float]] = defaultdict(list)

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user_id, action = self._classify(event)
        if user_id is not None:
            self._record(user_id, action)
        return await handler(event, data)

    def _classify(self, event: TelegramObject) -> tuple[str | None, str]:
        """Pull ``(user_id, action)`` out of an event; ``None`` if unowned."""

        if isinstance(event, Message):
            if event.from_user is None:
                return None, "message"
            user_id = str(event.from_user.id)
            if event.document is not None or event.photo:
                return user_id, "upload"
            return user_id, "message"
        if isinstance(event, CallbackQuery):
            # ``CallbackQuery.from_user`` is non-optional per the Bot API
            # spec — buttons can't be pressed by anonymous channels.
            user_id = str(event.from_user.id)
            payload = event.data or ""
            if any(marker in payload for marker in _GENERATION_CALLBACK_MARKERS):
                return user_id, "generate"
            return user_id, "message"
        return None, "message"

    def _record(self, user_id: str, action: str) -> None:
        """Append a timestamp; warn if the window is now over the cap."""

        window, max_count = self.LIMITS[action]
        key = f"{user_id}:{action}"
        now = time()
        existing = self._counters[key]
        # Drop entries that have aged out of the window before counting.
        fresh = [t for t in existing if now - t < window]
        if len(fresh) >= max_count:
            logger.warning(
                "rate_limit_exceeded",
                extra={"user_id": user_id, "action": action, "count": len(fresh)},
            )
        fresh.append(now)
        self._counters[key] = fresh


__all__ = ["RateLimitMiddleware"]
