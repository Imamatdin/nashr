"""Behaviour tests for :class:`RateLimitMiddleware`.

The middleware is soft in v1: it logs warnings when a per-user window
exceeds the cap but still passes the event through. Tests assert on the
log record (count + extras) plus the event-classification logic, which
together pin the user-facing behaviour: every event reaches the handler
regardless of cap, and we know which limit fired.
"""

from __future__ import annotations

import logging
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from packages.bot.middleware.rate_limit import RateLimitMiddleware


def _make_message(user_id: int = 1, has_document: bool = False, has_photo: bool = False) -> Any:
    """Build a minimal ``Message`` stand-in for middleware classification."""

    from aiogram.types import Message

    msg = MagicMock(spec=Message)
    msg.from_user = MagicMock(id=user_id, is_bot=False)
    msg.document = MagicMock() if has_document else None
    msg.photo = [MagicMock()] if has_photo else []
    msg.text = "hi"
    return msg


def _make_callback(user_id: int = 1, data: str = "noop") -> Any:
    from aiogram.types import CallbackQuery

    cb = MagicMock(spec=CallbackQuery)
    cb.from_user = MagicMock(id=user_id, is_bot=False)
    cb.data = data
    return cb


async def _run(middleware: RateLimitMiddleware, event: Any) -> Any:
    """Invoke the middleware once with a stub passthrough handler."""

    handler = AsyncMock(return_value="ok")
    return await middleware(handler, event, {})


async def test_rate_limit_allows_normal_usage(caplog: pytest.LogCaptureFixture) -> None:
    """Ten messages in 60s pass through with no warnings."""

    mw = RateLimitMiddleware()
    caplog.set_level(logging.WARNING, logger="nashr.ratelimit")
    for _ in range(10):
        result = await _run(mw, _make_message(user_id=42))
        assert result == "ok"
    excess = [r for r in caplog.records if r.message == "rate_limit_exceeded"]
    assert excess == []


async def test_rate_limit_logs_on_excess(caplog: pytest.LogCaptureFixture) -> None:
    """The 31st message inside one minute logs a warning but still passes."""

    mw = RateLimitMiddleware()
    caplog.set_level(logging.WARNING, logger="nashr.ratelimit")
    for _ in range(31):
        result = await _run(mw, _make_message(user_id=42))
        assert result == "ok"
    warnings = [r for r in caplog.records if r.message == "rate_limit_exceeded"]
    assert len(warnings) == 1
    assert warnings[0].action == "message"
    assert warnings[0].user_id == "42"


async def test_rate_limit_upload_limit(caplog: pytest.LogCaptureFixture) -> None:
    """The 6th upload in a minute triggers an upload-action warning."""

    mw = RateLimitMiddleware()
    caplog.set_level(logging.WARNING, logger="nashr.ratelimit")
    for _ in range(6):
        await _run(mw, _make_message(user_id=7, has_document=True))
    warnings = [r for r in caplog.records if r.message == "rate_limit_exceeded"]
    assert len(warnings) == 1
    assert warnings[0].action == "upload"


async def test_rate_limit_separate_per_user(caplog: pytest.LogCaptureFixture) -> None:
    """User A and user B each get a full window; no warnings cross."""

    mw = RateLimitMiddleware()
    caplog.set_level(logging.WARNING, logger="nashr.ratelimit")
    for _ in range(30):
        await _run(mw, _make_message(user_id=1))
    for _ in range(30):
        await _run(mw, _make_message(user_id=2))
    excess = [r for r in caplog.records if r.message == "rate_limit_exceeded"]
    assert excess == []


async def test_rate_limit_window_expiry(caplog: pytest.LogCaptureFixture) -> None:
    """Entries outside the window age out — second burst is clean."""

    mw = RateLimitMiddleware()
    caplog.set_level(logging.WARNING, logger="nashr.ratelimit")
    user = "55"

    # Seed 30 entries 120 seconds in the past — they should fall out of the window.
    mw._counters[f"{user}:message"] = [time.time() - 120] * 30

    for _ in range(30):
        await _run(mw, _make_message(user_id=55))

    excess = [r for r in caplog.records if r.message == "rate_limit_exceeded"]
    assert excess == []


async def test_rate_limit_generate_classification(caplog: pytest.LogCaptureFixture) -> None:
    """Callback queries with ``tier_`` data classify as generate."""

    mw = RateLimitMiddleware()
    caplog.set_level(logging.WARNING, logger="nashr.ratelimit")
    for _ in range(4):
        await _run(mw, _make_callback(user_id=9, data="tier_basic"))
    warnings = [r for r in caplog.records if r.message == "rate_limit_exceeded"]
    assert len(warnings) == 1
    assert warnings[0].action == "generate"


async def test_rate_limit_anonymous_event_passthrough() -> None:
    """An event without ``from_user`` (channel post) still calls the handler."""

    mw = RateLimitMiddleware()
    handler = AsyncMock(return_value="ok")
    event = MagicMock()
    event.from_user = None
    result = await mw(handler, event, {})
    assert result == "ok"
    handler.assert_awaited_once()
