"""Behaviour tests for the persisted abuse caps (packages/platform/rate_limit.py)."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast

import pytest

from packages.platform.database import DatabaseClient
from packages.platform.rate_limit import ENQUEUE_ACTION, RateLimiter

pytestmark = pytest.mark.asyncio


class _FakeDb:
    """Counts consume_rate_limit calls per (scope, key) like the SQL fn would."""

    def __init__(self) -> None:
        self.counts: dict[tuple[str, str, str, str], int] = {}
        self.calls: list[dict[str, Any]] = []

    def rpc(self, fn: str, params: dict[str, Any]) -> Any:
        assert fn == "consume_rate_limit"
        self.calls.append(params)
        key = (params["p_scope"], params["p_action"], params["p_key"], params["p_window_start"])
        self.counts[key] = self.counts.get(key, 0) + 1
        return SimpleNamespace(data=self.counts[key])


def _limiter(limits: dict[tuple[str, str], int]) -> tuple[RateLimiter, _FakeDb]:
    fake = _FakeDb()
    return RateLimiter(cast(DatabaseClient, fake), limits=limits), fake


async def test_under_limit_allows_and_reports_count() -> None:
    limiter, _ = _limiter({("user", ENQUEUE_ACTION): 2, ("ip", ENQUEUE_ACTION): 10})
    decision = await limiter.check(action=ENQUEUE_ACTION, user_id="u1", ip="1.2.3.4")
    assert decision.allowed and decision.count == 1 and decision.limit == 2


async def test_user_cap_rejects_with_visible_state() -> None:
    limiter, _ = _limiter({("user", ENQUEUE_ACTION): 2, ("ip", ENQUEUE_ACTION): 10})
    await limiter.check(action=ENQUEUE_ACTION, user_id="u1", ip="1.2.3.4")
    await limiter.check(action=ENQUEUE_ACTION, user_id="u1", ip="1.2.3.4")
    decision = await limiter.check(action=ENQUEUE_ACTION, user_id="u1", ip="1.2.3.4")
    assert not decision.allowed
    assert decision.scope == "user" and decision.count == 3 and decision.limit == 2
    assert decision.resets_at > datetime.now(UTC)


async def test_ip_cap_rejects_across_users() -> None:
    limiter, _ = _limiter({("user", ENQUEUE_ACTION): 10, ("ip", ENQUEUE_ACTION): 2})
    await limiter.check(action=ENQUEUE_ACTION, user_id="u1", ip="9.9.9.9")
    await limiter.check(action=ENQUEUE_ACTION, user_id="u2", ip="9.9.9.9")
    decision = await limiter.check(action=ENQUEUE_ACTION, user_id="u3", ip="9.9.9.9")
    assert not decision.allowed and decision.scope == "ip"


async def test_both_scopes_are_always_counted() -> None:
    limiter, fake = _limiter({("user", ENQUEUE_ACTION): 5, ("ip", ENQUEUE_ACTION): 5})
    await limiter.check(action=ENQUEUE_ACTION, user_id="u1", ip="1.1.1.1")
    scopes = [c["p_scope"] for c in fake.calls]
    assert scopes == ["user", "ip"]


async def test_unknown_action_limit_zero_means_unlimited() -> None:
    limiter, _ = _limiter({})
    decision = await limiter.check(action="chat", user_id="u1", ip="1.1.1.1")
    assert decision.allowed and decision.limit == 0


async def test_window_start_is_utc_midnight() -> None:
    limiter, fake = _limiter({("user", ENQUEUE_ACTION): 5, ("ip", ENQUEUE_ACTION): 5})
    await limiter.check(action=ENQUEUE_ACTION, user_id="u1", ip="1.1.1.1")
    window = datetime.fromisoformat(fake.calls[0]["p_window_start"])
    assert window.tzinfo is not None
    assert (window.hour, window.minute, window.second) == (0, 0, 0)
