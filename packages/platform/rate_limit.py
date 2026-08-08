"""Persisted abuse caps: per-user AND per-IP fixed-window counters (plan P2).

Every publicly reachable credit-burning surface calls :meth:`RateLimiter.check`
BEFORE any model token is spent. Counters live in the migration-006
``rate_limit_counters`` table and are bumped through the atomic
``consume_rate_limit`` SQL function, so caps survive restarts and apply across
processes (the in-memory 3-gen/hour soft limit the bot carries is log-only —
this is the enforced layer).

Windows are fixed UTC days: coarse on purpose — the cap is an abuse backstop,
not a traffic shaper. ``action`` separates surfaces; ``enqueue`` is live now
and ``chat`` is pre-wired for the P4 chat route.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import cast

from pydantic import BaseModel, ConfigDict

from packages.platform.database import DatabaseClient

ENQUEUE_ACTION: str = "enqueue"
CHAT_ACTION: str = "chat"
UPLOAD_ACTION: str = "upload"
SHARE_VIEW_ACTION: str = "share_view"

# Defaults sized off SPEC §9 ("max 10 generation jobs per user per day") with
# per-IP headroom for NAT'd campus networks sharing one address. Upload caps
# assume max 10 sources per job × the 10-job user cap, minus slack for retried
# uploads. share_view is IP-only: the public route has no authenticated user.
DEFAULT_LIMITS: dict[tuple[str, str], int] = {
    ("user", ENQUEUE_ACTION): 10,
    ("ip", ENQUEUE_ACTION): 40,
    ("user", CHAT_ACTION): 200,
    ("ip", CHAT_ACTION): 800,
    ("user", UPLOAD_ACTION): 60,
    ("ip", UPLOAD_ACTION): 240,
    ("ip", SHARE_VIEW_ACTION): 600,
}


class RateDecision(BaseModel):
    """The visible state a rejected caller gets back."""

    model_config = ConfigDict(extra="forbid")

    allowed: bool
    scope: str
    action: str
    count: int
    limit: int
    resets_at: datetime


class RateLimiter:
    """Fixed-window request limiter over the persisted counter table."""

    def __init__(
        self,
        db: DatabaseClient,
        limits: dict[tuple[str, str], int] | None = None,
    ) -> None:
        self._db = db
        self._limits = limits if limits is not None else dict(DEFAULT_LIMITS)

    @staticmethod
    def _window_start(now: datetime) -> datetime:
        return now.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)

    async def _consume(self, scope: str, action: str, key: str) -> RateDecision:
        now = datetime.now(UTC)
        window_start = self._window_start(now)
        limit = self._limits.get((scope, action), 0)
        result = await asyncio.to_thread(
            lambda: self._db.rpc(
                "consume_rate_limit",
                {
                    "p_scope": scope,
                    "p_action": action,
                    "p_key": key,
                    "p_window_start": window_start.isoformat(),
                },
            )
        )
        count = int(cast(int, result.data))
        return RateDecision(
            allowed=limit <= 0 or count <= limit,
            scope=scope,
            action=action,
            count=count,
            limit=limit,
            resets_at=window_start + timedelta(days=1),
        )

    async def check(self, *, action: str, user_id: str, ip: str) -> RateDecision:
        """Count this request against BOTH scopes; return the first violation.

        Both counters are always bumped (an attempt is an attempt), then the
        user decision wins the rejection message when both are over — the user
        cap is the one the caller can actually reason about.
        """

        user_decision = await self._consume("user", action, user_id)
        ip_decision = await self._consume("ip", action, ip)
        if not user_decision.allowed:
            return user_decision
        if not ip_decision.allowed:
            return ip_decision
        return user_decision

    async def check_ip(self, *, action: str, ip: str) -> RateDecision:
        """IP-scope-only counter for unauthenticated surfaces (public share views)."""

        return await self._consume("ip", action, ip)


__all__ = [
    "CHAT_ACTION",
    "DEFAULT_LIMITS",
    "ENQUEUE_ACTION",
    "SHARE_VIEW_ACTION",
    "UPLOAD_ACTION",
    "RateDecision",
    "RateLimiter",
]
