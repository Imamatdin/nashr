"""Behaviour tests for the money-reading routes (packages/api/routes/credits.py).

Three contracts: the balance is always the FULL-history figure even when the
ledger page is truncated, every row reaches the wire with its ``action`` intact
so the UI can name a refund a refund, and ``/pricing`` is a projection of the
single source of truth (the ledger's price table, the SPEC image budgets, the
session fix allowances) rather than a second copy of the numbers.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import uuid4

import httpx
import pytest

from packages.api.app import create_app
from packages.api.services.tokens import mint_app_jwt
from packages.bot.sessions.budget import session_fix_limit
from packages.core.constants import image_budget_for_package
from packages.core.enums import GenerationPackage
from packages.platform.config import PlatformConfig
from packages.platform.credits import CreditAction, CreditEntry, CreditLedger

pytestmark = pytest.mark.asyncio

_SECRET = "credits-route-secret"
_USER_ID = uuid4()
_PROJECT_ID = str(uuid4())
_JOB_ID = str(uuid4())

_WEB_TIERS = (
    GenerationPackage.PRESENTATION_BASIC,
    GenerationPackage.PRESENTATION_STANDARD,
    GenerationPackage.PRESENTATION_PREMIUM,
)


def _config() -> PlatformConfig:
    return PlatformConfig(
        supabase_url="https://example.supabase.co",
        supabase_service_key="service",
        telegram_bot_token="123:abc",
        supabase_jwt_secret=_SECRET,
    )


def _entry(
    *,
    action: CreditAction,
    amount: int,
    reason: str,
    created_at: datetime,
    project_id: str | None = _PROJECT_ID,
    generation_job_id: str | None = None,
) -> CreditEntry:
    return CreditEntry(
        id=str(uuid4()),
        user_id=str(_USER_ID),
        project_id=project_id,
        generation_job_id=generation_job_id,
        action=action,
        amount=amount,
        reason=reason,
        created_at=created_at,
    )


class _FakeCredits:
    """Scripted ledger: the page and the balance are set independently."""

    def __init__(self) -> None:
        self.balance = 0
        self.entries: list[CreditEntry] = []
        self.limits: list[int] = []

    async def get_balance(self, user_id: str) -> int:
        return self.balance

    async def get_ledger(self, user_id: str, limit: int = 50) -> list[CreditEntry]:
        self.limits.append(limit)
        return list(self.entries)


def _client() -> tuple[httpx.AsyncClient, _FakeCredits]:
    credits = _FakeCredits()
    app = create_app(
        config=_config(),
        db=cast(Any, object()),
        identity_service=cast(Any, object()),
        credits=cast(Any, credits),
    )
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test"), credits


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {mint_app_jwt(_SECRET, _USER_ID, 3600).access_token}"}


# ------------------------------------------------------------------ balance


async def test_get_credits_requires_auth_then_reports_balance_in_uzs() -> None:
    client, credits = _client()
    credits.balance = 42_500
    async with client:
        anonymous = await client.get("/credits")
        authed = await client.get("/credits", headers=_headers())
    assert anonymous.status_code == 401
    assert anonymous.json()["detail"] == "missing_bearer_token"
    assert authed.status_code == 200
    assert authed.json() == {"balance": 42_500, "currency": "UZS"}


# ------------------------------------------------------------------- ledger


async def test_ledger_passes_store_order_through_with_full_row_shape() -> None:
    # The route does NOT sort — newest-first is CreditLedger.get_ledger's
    # contract, proven against a real query in
    # tests/unit/test_credit_ledger.py::test_get_ledger_returns_typed_entries_newest_first.
    # What this pins is the pass-through: rows are handed over in the order the
    # ledger returned them, so a route that "helpfully" re-sorted would fail here.
    client, credits = _client()
    now = datetime.now(UTC)
    newest = _entry(
        action=CreditAction.DEDUCT_PRESENTATION,
        amount=-10_000,
        reason="generation:presentation_standard",
        created_at=now,
        generation_job_id=_JOB_ID,
    )
    older = _entry(
        action=CreditAction.GRANT_PAID,
        amount=50_000,
        reason="payment:pay-1",
        created_at=now - timedelta(hours=2),
        project_id=None,
    )
    credits.entries = [older, newest]  # deliberately NOT newest-first
    credits.balance = 40_000
    async with client:
        response = await client.get("/credits/ledger", headers=_headers())
    assert response.status_code == 200
    body = response.json()
    assert [e["id"] for e in body["entries"]] == [older.id, newest.id]
    assert body["entries"][1] == {
        "id": newest.id,
        "amount": -10_000,
        "action": "deduct_presentation",
        "reason": "generation:presentation_standard",
        "project_id": _PROJECT_ID,
        "generation_job_id": _JOB_ID,
        "created_at": body["entries"][1]["created_at"],
    }
    assert datetime.fromisoformat(body["entries"][1]["created_at"]) == now
    assert body["entries"][0]["project_id"] is None
    assert body["entries"][0]["generation_job_id"] is None


async def test_ledger_balance_is_full_history_not_the_returned_page() -> None:
    # A truncated page must never imply a smaller balance: the two rows below
    # net to zero, but the user's real history is 88 000. If the route summed
    # what it returned, a paginated view would tell the user they are broke.
    client, credits = _client()
    now = datetime.now(UTC)
    credits.entries = [
        _entry(
            action=CreditAction.GRANT_FREE,
            amount=5_000,
            reason="source_upload",
            created_at=now,
        ),
        _entry(
            action=CreditAction.DEDUCT_PRESENTATION,
            amount=-5_000,
            reason="generation:presentation_basic",
            created_at=now - timedelta(minutes=5),
        ),
    ]
    credits.balance = 88_000
    async with client:
        response = await client.get("/credits/ledger", headers=_headers())
    body = response.json()
    assert len(body["entries"]) == 2
    assert sum(e["amount"] for e in body["entries"]) == 0
    assert body["balance"] == 88_000


async def test_ledger_requires_auth() -> None:
    client, credits = _client()
    async with client:
        response = await client.get("/credits/ledger")
    assert response.status_code == 401
    assert credits.limits == []


async def test_ledger_limit_is_bounded() -> None:
    client, credits = _client()
    async with client:
        zero = await client.get("/credits/ledger?limit=0", headers=_headers())
        over = await client.get("/credits/ledger?limit=101", headers=_headers())
        maximum = await client.get("/credits/ledger?limit=100", headers=_headers())
    assert zero.status_code == 422
    assert over.status_code == 422
    assert maximum.status_code == 200
    assert credits.limits == [100]


async def test_refund_and_learning_reward_rows_keep_their_action_on_the_wire() -> None:
    client, credits = _client()
    now = datetime.now(UTC)
    credits.entries = [
        _entry(
            action=CreditAction.REFUND,
            amount=10_000,
            reason="job_failed",
            created_at=now,
            generation_job_id=_JOB_ID,
        ),
        _entry(
            action=CreditAction.GRANT_FREE,
            amount=CreditLedger.FREE_CREDIT_VALUE,
            reason="contradiction_explain",
            created_at=now - timedelta(days=1),
        ),
    ]
    credits.balance = 15_000
    async with client:
        response = await client.get("/credits/ledger", headers=_headers())
    entries = response.json()["entries"]
    assert [e["action"] for e in entries] == ["refund", "grant_free"]
    assert entries[0]["generation_job_id"] == _JOB_ID
    assert entries[1]["amount"] == CreditLedger.FREE_CREDIT_VALUE
    assert entries[1]["reason"] == "contradiction_explain"


# ------------------------------------------------------------------ pricing


async def test_pricing_is_public_and_projects_the_real_sources_of_truth() -> None:
    client, _ = _client()
    async with client:
        response = await client.get("/pricing")
    assert response.status_code == 200
    body = response.json()
    assert body["currency"] == "UZS"
    assert [entry["package"] for entry in body["packages"]] == [t.value for t in _WEB_TIERS]
    for entry, tier in zip(body["packages"], _WEB_TIERS, strict=True):
        assert entry == {
            "package": tier.value,
            "price": CreditLedger.PRICING[tier.value],
            "ai_images": image_budget_for_package(tier),
            "fix_allowance": session_fix_limit(tier),
        }


async def test_pricing_carries_the_free_credit_caps() -> None:
    client, _ = _client()
    async with client:
        body = (await client.get("/pricing")).json()
    assert body["free_credit_value"] == CreditLedger.FREE_CREDIT_VALUE
    assert body["free_daily_cap"] == CreditLedger.FREE_DAILY_CAP
    assert body["free_weekly_cap"] == CreditLedger.FREE_WEEKLY_CAP
    assert body["free_project_cap"] == CreditLedger.FREE_PROJECT_CAP
