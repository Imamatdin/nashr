"""Aiogram middlewares for the Nashr Telegram bot.

Three middlewares are exported. Two are registered on the **dispatcher**
in :mod:`packages.bot.app` (they see inbound updates):

  * :class:`RateLimitMiddleware` — soft-rate-limits message, upload, and
    generation events on an in-memory sliding window (per user).
  * :class:`InputValidationMiddleware` — drops messages from bots and
    channel posts before they reach handlers.

The third is registered on the **Bot session** (it sees outbound Telegram
API calls):

  * :class:`LivenessMiddleware` — touches a liveness file after every
    successful Telegram API call so the polling-mode Docker healthcheck can
    prove live connectivity (see ``scripts/healthcheck.py``).
"""

from __future__ import annotations

from packages.bot.middleware.input_validation import InputValidationMiddleware
from packages.bot.middleware.liveness import LivenessMiddleware
from packages.bot.middleware.rate_limit import RateLimitMiddleware

__all__ = ["InputValidationMiddleware", "LivenessMiddleware", "RateLimitMiddleware"]
