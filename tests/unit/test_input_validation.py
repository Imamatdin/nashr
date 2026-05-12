"""Behaviour tests for :class:`InputValidationMiddleware`.

The middleware drops three event shapes silently before they reach
handlers: messages from bots, channel posts (no ``from_user``), and
``CallbackQuery`` with no user. Tests assert the handler is not awaited
when the event is dropped, and that a normal user message still passes.
"""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from packages.bot.middleware.input_validation import InputValidationMiddleware


def _message(*, is_bot: bool = False, no_user: bool = False, text: str = "hello") -> Any:
    from aiogram.types import Message

    msg = MagicMock(spec=Message)
    if no_user:
        msg.from_user = None
    else:
        msg.from_user = MagicMock(id=42, is_bot=is_bot)
    msg.text = text
    return msg


async def test_skip_bot_messages() -> None:
    """Messages from bots return early — the handler is never awaited."""

    mw = InputValidationMiddleware()
    handler = AsyncMock(return_value="reached")
    result = await mw(handler, _message(is_bot=True), {})
    assert result is None
    handler.assert_not_awaited()


async def test_skip_channel_posts() -> None:
    """Messages without ``from_user`` (channel posts) return early."""

    mw = InputValidationMiddleware()
    handler = AsyncMock(return_value="reached")
    result = await mw(handler, _message(no_user=True), {})
    assert result is None
    handler.assert_not_awaited()


async def test_normal_message_passes() -> None:
    """Regular user messages reach the handler and propagate its return value."""

    mw = InputValidationMiddleware()
    handler = AsyncMock(return_value="handled")
    result = await mw(handler, _message(), {})
    assert result == "handled"
    handler.assert_awaited_once()


async def test_long_text_logged_but_passed(caplog: pytest.LogCaptureFixture) -> None:
    """A 5000-char text triggers a warning but still reaches the handler."""

    mw = InputValidationMiddleware()
    handler = AsyncMock(return_value="ok")
    caplog.set_level(logging.WARNING, logger="nashr.validation")
    result = await mw(handler, _message(text="x" * 5000), {})
    assert result == "ok"
    handler.assert_awaited_once()
    truncations = [
        r for r in caplog.records if r.message == "input_validation_truncating_long_message"
    ]
    assert len(truncations) == 1
