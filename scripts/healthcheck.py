"""Docker HEALTHCHECK probe for the polling-mode Telegram bot.

The bot runs in polling mode (see ``docker-compose.yml``), so there is
no HTTP ``/health`` endpoint to curl — nothing binds the webhook port.
Instead, :class:`packages.bot.middleware.liveness.LivenessMiddleware`
touches a liveness file after every successful Telegram API call
(``getUpdates`` fires every long-poll cycle, so the file stays fresh even
when the bot is idle).

This script exits ``0`` when that file exists and was touched within the
freshness window, and ``1`` otherwise (missing, stale, or unreadable) —
the contract Docker's ``HEALTHCHECK ... CMD`` expects. It imports only
the standard library so it stays fast and dependency-free.

Configuration (env vars, matching the middleware defaults):
  * ``NASHR_LIVENESS_FILE``    — liveness file path
                                 (default ``/tmp/nashr-bot-liveness``).
  * ``NASHR_LIVENESS_MAX_AGE`` — freshness window, seconds (default ``120``).
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

LIVENESS_FILE_ENV = "NASHR_LIVENESS_FILE"
MAX_AGE_ENV = "NASHR_LIVENESS_MAX_AGE"
DEFAULT_LIVENESS_FILE = "/tmp/nashr-bot-liveness"
DEFAULT_MAX_AGE_SECONDS = 120.0


def is_fresh(path: Path, max_age_seconds: float, *, now: float | None = None) -> bool:
    """Return whether ``path`` exists and was modified within the window.

    :param path: Liveness file to inspect.
    :param max_age_seconds: Maximum allowed age — the current time minus
        the file's mtime. Non-positive values make the check always fail.
    :param now: Reference timestamp (epoch seconds); defaults to
        :func:`time.time`. Injectable so tests stay deterministic.
    :returns: ``True`` when the file is present and fresh, else ``False``.
    """

    reference = time.time() if now is None else now
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return False
    age = reference - mtime
    # A FUTURE mtime (negative age) is anomalous — a backward clock jump — and
    # must not read as fresh: a dead bot would look healthy until wall time
    # caught up. A live bot self-corrects on its next touch, which rewrites the
    # mtime under the corrected clock, so the two-sided bound only fails dead
    # processes (and a live one for at most one probe window).
    return 0 <= age < max_age_seconds


def _resolve_max_age() -> float:
    """Read ``NASHR_LIVENESS_MAX_AGE`` (seconds); fall back to the default."""

    raw = os.environ.get(MAX_AGE_ENV)
    if raw is None:
        return DEFAULT_MAX_AGE_SECONDS
    try:
        return float(raw)
    except ValueError:
        return DEFAULT_MAX_AGE_SECONDS


def main() -> int:
    """Return ``0`` if the liveness file is fresh, else ``1`` (Docker probe)."""

    path = Path(os.environ.get(LIVENESS_FILE_ENV, DEFAULT_LIVENESS_FILE))
    max_age = _resolve_max_age()
    return 0 if is_fresh(path, max_age) else 1


if __name__ == "__main__":
    sys.exit(main())
