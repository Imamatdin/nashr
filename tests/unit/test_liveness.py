"""Tests for the polling-mode liveness healthcheck.

Covers both halves of the mechanism:

  * :class:`packages.bot.middleware.liveness.LivenessMiddleware` — the Bot
    session middleware that touches a liveness file after each *successful*
    Telegram API call, leaves it untouched (and re-raises) on failure, and
    never lets a touch error break a request.
  * ``scripts/healthcheck.py`` — the stdlib-only Docker probe mapping the
    liveness file's freshness to exit code 0 (fresh) or 1 (stale/missing).
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from packages.bot.middleware.liveness import (
    DEFAULT_LIVENESS_FILE,
    LIVENESS_FILE_ENV,
    LivenessMiddleware,
)
from scripts.healthcheck import DEFAULT_MAX_AGE_SECONDS, is_fresh, main

_HEALTHCHECK_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "healthcheck.py"

_SENTINEL = object()


class _BoomError(RuntimeError):
    """Distinct error type raised by the failing ``make_request`` stub."""


async def _ok_request(_bot: object, _method: object) -> object:
    """Stand-in for aiogram's ``make_request`` that succeeds."""

    return _SENTINEL


async def _boom_request(_bot: object, _method: object) -> object:
    """Stand-in for ``make_request`` that fails like a dropped API call."""

    raise _BoomError("telegram unreachable")


# ---------------------------------------------------------------------------
# LivenessMiddleware
# ---------------------------------------------------------------------------


async def test_touches_file_and_returns_response_on_success(tmp_path: Path) -> None:
    """A successful request touches the file and forwards the response as-is."""

    liveness = tmp_path / "liveness"
    middleware = LivenessMiddleware(liveness_file=liveness)

    result = await middleware(_ok_request, object(), object())

    assert result is _SENTINEL
    assert liveness.exists()


async def test_refreshes_mtime_of_existing_file(tmp_path: Path) -> None:
    """Touching an existing file advances its mtime (proves freshness)."""

    liveness = tmp_path / "liveness"
    liveness.touch()
    stale = time.time() - 10_000
    os.utime(liveness, (stale, stale))

    middleware = LivenessMiddleware(liveness_file=liveness)
    await middleware(_ok_request, object(), object())

    assert liveness.stat().st_mtime > stale


async def test_does_not_touch_and_reraises_on_failure(tmp_path: Path) -> None:
    """A failing request re-raises unchanged and leaves the file untouched."""

    liveness = tmp_path / "liveness"
    middleware = LivenessMiddleware(liveness_file=liveness)

    with pytest.raises(_BoomError, match="telegram unreachable"):
        await middleware(_boom_request, object(), object())

    assert not liveness.exists()


async def test_touch_failure_is_swallowed(tmp_path: Path) -> None:
    """A filesystem error during the touch never breaks the request."""

    # Parent directory is absent and ``Path.touch`` does not create it, so
    # the touch raises ``FileNotFoundError`` — the middleware must swallow it.
    unwritable = tmp_path / "missing_dir" / "liveness"
    middleware = LivenessMiddleware(liveness_file=unwritable)

    result = await middleware(_ok_request, object(), object())

    assert result is _SENTINEL
    assert not unwritable.exists()


async def test_env_var_selects_liveness_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With no explicit path, the env var chooses the file that gets touched."""

    liveness = tmp_path / "from_env"
    monkeypatch.setenv(LIVENESS_FILE_ENV, str(liveness))
    middleware = LivenessMiddleware()

    await middleware(_ok_request, object(), object())

    assert liveness.exists()


def test_public_liveness_contract() -> None:
    """The default path and env-var name are the cross-component contract.

    ``scripts/healthcheck.py`` and ``docker-compose.yml`` rely on these
    exact values, so pin them here rather than in an internal-state probe.
    """

    assert LIVENESS_FILE_ENV == "NASHR_LIVENESS_FILE"
    assert DEFAULT_LIVENESS_FILE == "/tmp/nashr-bot-liveness"


# ---------------------------------------------------------------------------
# scripts/healthcheck.py — is_fresh
# ---------------------------------------------------------------------------


def test_is_fresh_true_for_recent_file(tmp_path: Path) -> None:
    liveness = tmp_path / "liveness"
    liveness.touch()

    assert is_fresh(liveness, 120.0) is True


def test_is_fresh_false_for_stale_file(tmp_path: Path) -> None:
    liveness = tmp_path / "liveness"
    liveness.touch()
    old = time.time() - 500
    os.utime(liveness, (old, old))

    assert is_fresh(liveness, 120.0) is False


def test_is_fresh_false_for_missing_file(tmp_path: Path) -> None:
    assert is_fresh(tmp_path / "nope", 120.0) is False


def test_is_fresh_uses_injected_now(tmp_path: Path) -> None:
    """The ``now`` parameter drives the age comparison deterministically."""

    liveness = tmp_path / "liveness"
    liveness.touch()
    mtime = liveness.stat().st_mtime

    assert is_fresh(liveness, 120.0, now=mtime + 50) is True
    assert is_fresh(liveness, 120.0, now=mtime + 200) is False


def test_is_fresh_false_for_future_mtime(tmp_path: Path) -> None:
    """A FUTURE mtime (backward clock jump) must not read as fresh — a dead
    bot would otherwise look healthy until wall time caught up."""

    liveness = tmp_path / "liveness"
    liveness.touch()
    mtime = liveness.stat().st_mtime

    assert is_fresh(liveness, 120.0, now=mtime - 30) is False
    assert is_fresh(liveness, 120.0, now=mtime) is True


# ---------------------------------------------------------------------------
# scripts/healthcheck.py — main() exit codes
# ---------------------------------------------------------------------------


def test_main_returns_0_for_fresh_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    liveness = tmp_path / "liveness"
    liveness.touch()
    monkeypatch.setenv(LIVENESS_FILE_ENV, str(liveness))
    monkeypatch.delenv("NASHR_LIVENESS_MAX_AGE", raising=False)

    assert main() == 0


def test_main_returns_1_for_stale_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    liveness = tmp_path / "liveness"
    liveness.touch()
    old = time.time() - 500
    os.utime(liveness, (old, old))
    monkeypatch.setenv(LIVENESS_FILE_ENV, str(liveness))
    monkeypatch.setenv("NASHR_LIVENESS_MAX_AGE", "120")

    assert main() == 1


def test_main_returns_1_for_missing_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(LIVENESS_FILE_ENV, str(tmp_path / "nope"))

    assert main() == 1


def test_main_honours_max_age_env_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A file older than the default window passes with a widened override."""

    liveness = tmp_path / "liveness"
    liveness.touch()
    old = time.time() - 200
    os.utime(liveness, (old, old))
    monkeypatch.setenv(LIVENESS_FILE_ENV, str(liveness))

    monkeypatch.delenv("NASHR_LIVENESS_MAX_AGE", raising=False)
    assert main() == 1  # 200s old > default 120s window

    monkeypatch.setenv("NASHR_LIVENESS_MAX_AGE", "300")
    assert main() == 0  # 200s old < 300s window


def test_default_max_age_constant() -> None:
    assert DEFAULT_MAX_AGE_SECONDS == 120.0


# ---------------------------------------------------------------------------
# scripts/healthcheck.py — end-to-end via subprocess (proves sys.exit wiring
# and stdlib-only execution outside the test interpreter)
# ---------------------------------------------------------------------------


def test_script_exits_0_for_fresh_file(tmp_path: Path) -> None:
    liveness = tmp_path / "liveness"
    liveness.touch()
    env = {**os.environ, LIVENESS_FILE_ENV: str(liveness)}

    result = subprocess.run(
        [sys.executable, str(_HEALTHCHECK_SCRIPT)],
        env=env,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0


def test_script_exits_1_for_stale_file(tmp_path: Path) -> None:
    liveness = tmp_path / "liveness"
    liveness.touch()
    old = time.time() - 500
    os.utime(liveness, (old, old))
    env = {**os.environ, LIVENESS_FILE_ENV: str(liveness)}

    result = subprocess.run(
        [sys.executable, str(_HEALTHCHECK_SCRIPT)],
        env=env,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1


# ---------------------------------------------------------------- worker file


class TestWorkerLivenessFile:
    """The marker a non-HTTP service uses to prove it is still cycling.

    Every service except the bot inherited the bot's liveness probe from the
    Dockerfile and could never touch its file, so api/worker/backup/caddy
    reported unhealthy for their whole lifetime. A permanently-red signal is
    worse than none — it is the signal step 2c of a live verification reads to
    tell "I killed the worker" from "the worker is fine".
    """

    def test_touch_creates_the_file(self, tmp_path: Path) -> None:
        from packages.platform.liveness import LivenessFile

        marker = tmp_path / "worker-liveness"
        assert LivenessFile(marker).touch() is True
        assert marker.exists()

    def test_touch_refreshes_an_existing_file(self, tmp_path: Path) -> None:
        from packages.platform.liveness import LivenessFile

        marker = tmp_path / "worker-liveness"
        marker.touch()
        os.utime(marker, (1_000_000, 1_000_000))
        stale = marker.stat().st_mtime

        LivenessFile(marker).touch()

        assert marker.stat().st_mtime > stale

    def test_env_var_selects_the_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # This is the whole mechanism by which the worker's inherited probe is
        # pointed at the worker's own marker instead of the bot's.
        from packages.platform.liveness import LIVENESS_FILE_ENV, LivenessFile

        chosen = tmp_path / "from-env"
        monkeypatch.setenv(LIVENESS_FILE_ENV, str(chosen))
        assert LivenessFile().path == chosen

    def test_default_is_not_the_bot_file(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Sharing the bot's path would let a dead worker look alive because the
        # BOT was still touching it.
        from packages.bot.middleware.liveness import DEFAULT_LIVENESS_FILE as BOT_FILE
        from packages.platform.liveness import (
            DEFAULT_WORKER_LIVENESS_FILE,
            LIVENESS_FILE_ENV,
            LivenessFile,
        )

        monkeypatch.delenv(LIVENESS_FILE_ENV, raising=False)
        assert DEFAULT_WORKER_LIVENESS_FILE != BOT_FILE
        # Compared as Paths, not strings: the constants are POSIX container
        # paths and this suite also runs on Windows.
        assert LivenessFile().path == Path(DEFAULT_WORKER_LIVENESS_FILE)

    def test_touch_failure_is_swallowed_and_reported(self, tmp_path: Path) -> None:
        # A health-probe side effect must never take down the work it reports
        # on; an unwritable marker goes stale, which is the correct signal.
        from packages.platform.liveness import LivenessFile

        unwritable = tmp_path / "no-such-dir" / "marker"
        live = LivenessFile(unwritable)
        assert live.touch() is False
        assert live.touch() is False  # log-once, still no raise
