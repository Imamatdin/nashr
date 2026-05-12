"""Aiogram dispatcher middlewares for the Nashr Telegram bot.

Two middlewares are exported and registered in
:mod:`packages.bot.app`:

  * :class:`RateLimitMiddleware` — soft-rate-limits message, upload, and
    generation events on an in-memory sliding window (per user).
  * :class:`InputValidationMiddleware` — drops messages from bots and
    channel posts before they reach handlers.
"""

from __future__ import annotations

from packages.bot.middleware.input_validation import InputValidationMiddleware
from packages.bot.middleware.rate_limit import RateLimitMiddleware

__all__ = ["InputValidationMiddleware", "RateLimitMiddleware"]
