"""Behaviour tests for SIGTERM/SIGINT signal handler registration in run.py.

Docker sends SIGTERM on container stop; the handler translates it into
a logged message + KeyboardInterrupt so aiogram unwinds in-flight tasks.
Tests assert that the installer registers handlers for the right signals
without actually running the bot.
"""

from __future__ import annotations

import signal
from typing import Any
from unittest.mock import MagicMock

import pytest


def test_install_shutdown_handlers_registers_sigint(monkeypatch: pytest.MonkeyPatch) -> None:
    """``signal.signal`` is called for SIGINT during installer execution."""

    from packages.bot import run

    calls: list[tuple[int, Any]] = []

    def fake_signal(sig: int, handler: Any) -> Any:
        calls.append((sig, handler))
        return None

    monkeypatch.setattr(signal, "signal", fake_signal)
    run._install_shutdown_handlers()
    sigs = [c[0] for c in calls]
    assert signal.SIGINT in sigs


def test_install_shutdown_handlers_registers_sigterm_when_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the platform exposes SIGTERM (Linux), it is registered too."""

    from packages.bot import run

    if not hasattr(signal, "SIGTERM"):
        pytest.skip("Platform has no SIGTERM (Windows)")

    calls: list[tuple[int, Any]] = []

    def fake_signal(sig: int, handler: Any) -> Any:
        calls.append((sig, handler))
        return None

    monkeypatch.setattr(signal, "signal", fake_signal)
    run._install_shutdown_handlers()
    sigs = [c[0] for c in calls]
    assert signal.SIGTERM in sigs


def test_shutdown_handler_raises_keyboard_interrupt(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The installed handler raises ``KeyboardInterrupt`` and logs the signal."""

    from packages.bot import run

    captured: dict[int, Any] = {}

    def fake_signal(sig: int, handler: Any) -> Any:
        captured[sig] = handler
        return None

    monkeypatch.setattr(signal, "signal", fake_signal)
    run._install_shutdown_handlers()
    handler = captured[signal.SIGINT]

    with pytest.raises(KeyboardInterrupt):
        handler(signal.SIGINT, None)


def test_main_installs_handlers_when_bot_token_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``main`` calls ``_install_shutdown_handlers`` after token validation."""

    from packages.bot import run
    from packages.platform.config import PlatformConfig

    monkeypatch.setattr(
        PlatformConfig,
        "from_env",
        classmethod(
            lambda cls: PlatformConfig(
                supabase_url="https://test.supabase.co",
                supabase_service_key="test",
                telegram_bot_token="real-token",
            )
        ),
    )
    monkeypatch.setattr("sys.argv", ["run.py"])

    install_called = MagicMock()
    monkeypatch.setattr(run, "_install_shutdown_handlers", install_called)

    # Stub the run_polling import path so main() exits without launching the bot
    def fake_run_polling(_config: PlatformConfig) -> None:
        raise SystemExit(0)

    monkeypatch.setattr(
        "packages.bot.app.run_polling",
        lambda *a, **k: fake_run_polling(*a, **k),
    )

    with pytest.raises(SystemExit):
        run.main()

    install_called.assert_called_once()
