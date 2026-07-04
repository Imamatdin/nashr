"""Liveness-tracking session middleware for the Telegram bot.

The bot runs in **polling** mode in production (``docker-compose.yml``
overrides the image ``CMD`` to drop ``--webhook``), so nothing binds the
webhook port and the ``/health`` HTTP route never exists. Container
liveness therefore cannot be probed over HTTP.

This Bot **session** middleware sits on the outbound Telegram API call
chain (registered via ``bot.session.middleware``). After every
*successful* Telegram API call it touches a small liveness file. Because
``getUpdates`` flows through the session on every long-poll cycle — even
when the bot is idle — the file's modification time proves live
connectivity to Telegram, not merely that the process is running.
``scripts/healthcheck.py`` reads that mtime for the Docker ``HEALTHCHECK``.

Failures are never masked: if the underlying request raises, the
exception propagates untouched and the file is left alone (a stale mtime
then correctly signals trouble). The touch itself is best-effort — a
filesystem error is logged once and swallowed so a health-probe side
effect can never break a real request.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, Final

from aiogram.client.session.middlewares.base import (
    BaseRequestMiddleware,
    NextRequestMiddlewareType,
)
from aiogram.methods import TelegramMethod
from aiogram.methods.base import Response, TelegramType

if TYPE_CHECKING:
    from aiogram import Bot

logger = logging.getLogger("nashr.liveness")

LIVENESS_FILE_ENV: Final[str] = "NASHR_LIVENESS_FILE"
DEFAULT_LIVENESS_FILE: Final[str] = "/tmp/nashr-bot-liveness"


class LivenessMiddleware(BaseRequestMiddleware):
    """Touch a liveness file after each successful Telegram API call."""

    def __init__(self, liveness_file: str | os.PathLike[str] | None = None) -> None:
        """Resolve the liveness file path once (arg > env var > default).

        :param liveness_file: Explicit path; when ``None`` the
            ``NASHR_LIVENESS_FILE`` environment variable is read, falling
            back to ``/tmp/nashr-bot-liveness``. Resolved at construction
            so the per-request touch stays cheap.
        """

        resolved = (
            liveness_file
            if liveness_file is not None
            else os.environ.get(LIVENESS_FILE_ENV, DEFAULT_LIVENESS_FILE)
        )
        self._path = Path(resolved)
        self._touch_error_logged = False

    async def __call__(
        self,
        make_request: NextRequestMiddlewareType[TelegramType],
        bot: Bot,
        method: TelegramMethod[TelegramType],
    ) -> Response[TelegramType]:
        """Run the request; on success, best-effort touch the liveness file.

        The touch happens only after ``make_request`` returns — a raising
        request propagates unchanged and leaves the file untouched, so a
        dropped Telegram connection lets the file go stale.
        """

        response = await make_request(bot, method)
        self._touch()
        return response

    def _touch(self) -> None:
        """Update the liveness file's mtime; log-once and swallow on error."""

        try:
            self._path.touch()
        except OSError as exc:
            if not self._touch_error_logged:
                logger.warning(
                    "liveness_touch_failed",
                    extra={"path": str(self._path), "error": str(exc)},
                )
                self._touch_error_logged = True


__all__ = ["DEFAULT_LIVENESS_FILE", "LIVENESS_FILE_ENV", "LivenessMiddleware"]
