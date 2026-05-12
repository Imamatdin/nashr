"""Input validation middleware.

Catches edge cases before they reach handlers:

  * Messages from bots — ignored (returns ``None`` without invoking the
    handler chain).
  * Channel posts (no ``from_user``) — ignored.
  * Very long text (> 4096 chars) — logged but passed through; aiogram
    already truncates outbound replies, and an inbound message that long
    is harmless to handlers (Telegram's own server-side cap is 4096).

Bot users see no error — silent drops are the right behaviour for spam
sources we do not control.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any, Final

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

logger = logging.getLogger("nashr.validation")

_MAX_TEXT_CHARS: Final[int] = 4096


class InputValidationMiddleware(BaseMiddleware):
    """Drop bot messages and channel posts; warn on extreme payloads."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if isinstance(event, Message):
            if event.from_user is None:
                return None
            if event.from_user.is_bot:
                return None
            if event.text is not None and len(event.text) > _MAX_TEXT_CHARS:
                logger.warning(
                    "input_validation_truncating_long_message",
                    extra={"user_id": event.from_user.id, "length": len(event.text)},
                )
        return await handler(event, data)


__all__ = ["InputValidationMiddleware"]
