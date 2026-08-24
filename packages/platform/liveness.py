"""Liveness file touching for long-running, non-HTTP processes.

The container health story used to have exactly one probe:
``scripts/healthcheck.py``, which reads the mtime of a liveness file the
Telegram bot's session middleware touches after every successful API call.
That probe is declared once in the Dockerfile, so ``api``, ``worker``,
``backup`` and ``caddy`` all INHERITED it — and none of them runs the Telegram
poller, so none of them could ever touch that file. All four reported
``unhealthy`` for their entire lifetime.

A health signal that is permanently red is worse than none: it trains everyone
to ignore the one indicator that would show a real outage, and it makes
"did killing the worker actually take it down?" unanswerable.

This module gives a non-HTTP process the same honest signal the bot has. The
file's mtime proves the process is CYCLING — claiming jobs, heartbeating — not
merely that a PID exists.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Final

logger = logging.getLogger("nashr.liveness")

LIVENESS_FILE_ENV: Final[str] = "NASHR_LIVENESS_FILE"
DEFAULT_WORKER_LIVENESS_FILE: Final[str] = "/tmp/nashr-worker-liveness"


class LivenessFile:
    """A best-effort liveness marker.

    Touch failures are logged ONCE and swallowed: a health-probe side effect
    must never be able to take down the work it is reporting on. A filesystem
    that stops accepting the touch makes the file go stale, which is exactly
    the signal a probe should read.
    """

    def __init__(self, path: str | os.PathLike[str] | None = None) -> None:
        """Resolve the path once (arg > ``NASHR_LIVENESS_FILE`` > default)."""

        resolved = (
            path
            if path is not None
            else os.environ.get(LIVENESS_FILE_ENV, DEFAULT_WORKER_LIVENESS_FILE)
        )
        self._path = Path(resolved)
        self._error_logged = False

    @property
    def path(self) -> Path:
        """The resolved liveness file path."""

        return self._path

    def touch(self) -> bool:
        """Update the file's mtime. Returns whether the touch landed."""

        try:
            self._path.touch()
        except OSError as exc:
            if not self._error_logged:
                logger.warning(
                    "liveness_touch_failed",
                    extra={"path": str(self._path), "error": str(exc)},
                )
                self._error_logged = True
            return False
        return True


__all__ = ["DEFAULT_WORKER_LIVENESS_FILE", "LIVENESS_FILE_ENV", "LivenessFile"]
