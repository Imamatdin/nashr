"""Behaviour tests for :class:`CreditLedger`.

We reuse the in-memory fake Supabase client from
``test_database_client`` to give the ledger a real persistence target
without any network calls. Every test asserts a single property of the
ledger contract: balance arithmetic, the free-credit cap policy, the
pricing schedule, the insufficient-credits guard, or how reads project
the table back into typed :class:`CreditEntry` rows.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest

from packages.platform.config import PlatformConfig
from packages.platform.credits import (
    CreditAction,
    CreditEntry,
    CreditLedger,
    FreeCreditsReason,
    InsufficientCreditsError,
)
from packages.platform.database import DatabaseClient
from tests.unit.test_database_client import FakeSupabaseClient


def _make_ledger() -> tuple[CreditLedger, FakeSupabaseClient]:
    cfg = PlatformConfig(
        supabase_url="https://test.supabase.co",
        supabase_service_key="test",
        telegram_bot_token="test",
    )
    fake = FakeSupabaseClient()
    db = DatabaseClient(cfg, client=cast(Any, fake))
    ledger = CreditLedger(db)
    return ledger, fake


def _seed_entry(
    fake: FakeSupabaseClient,
    *,
    user_id: str,
    action: CreditAction,
    amount: int,
    project_id: str | None = None,
    created_at: datetime | None = None,
) -> None:
    rows = fake.tables.setdefault("credit_ledger", [])
    rows.append(
        {
            "id": str(uuid.uuid4()),
            "user_id": user_id,
            "project_id": project_id,
            "action": action.value,
            "amount": amount,
            "reason": "test seed",
            "created_at": (created_at or datetime.now(UTC)).isoformat(),
        }
    )


# ------------------------------------------------------------- balance


async def test_get_balance_empty_is_zero() -> None:
    ledger, _ = _make_ledger()
    assert await ledger.get_balance("u1") == 0


async def test_get_balance_sums_positive_grants() -> None:
    ledger, fake = _make_ledger()
    _seed_entry(fake, user_id="u1", action=CreditAction.GRANT_PAID, amount=60_000)
    _seed_entry(fake, user_id="u1", action=CreditAction.GRANT_FREE, amount=5_000)
    _seed_entry(fake, user_id="u1", action=CreditAction.GRANT_FREE, amount=5_000)
    assert await ledger.get_balance("u1") == 70_000


async def test_get_balance_subtracts_deductions() -> None:
    ledger, fake = _make_ledger()
    _seed_entry(fake, user_id="u1", action=CreditAction.GRANT_PAID, amount=100_000)
    _seed_entry(fake, user_id="u1", action=CreditAction.DEDUCT_ARTICLE, amount=-60_000)
    assert await ledger.get_balance("u1") == 40_000


async def test_get_balance_is_per_user() -> None:
    ledger, fake = _make_ledger()
    _seed_entry(fake, user_id="u1", action=CreditAction.GRANT_PAID, amount=10_000)
    _seed_entry(fake, user_id="u2", action=CreditAction.GRANT_PAID, amount=99_000)
    assert await ledger.get_balance("u1") == 10_000
    assert await ledger.get_balance("u2") == 99_000


# --------------------------------------------------- sufficient_credits


async def test_has_sufficient_true_when_balance_covers_price() -> None:
    ledger, fake = _make_ledger()
    _seed_entry(fake, user_id="u1", action=CreditAction.GRANT_PAID, amount=100_000)
    assert await ledger.has_sufficient_credits("u1", "article_basic") is True


async def test_has_sufficient_false_when_balance_short() -> None:
    ledger, fake = _make_ledger()
    _seed_entry(fake, user_id="u1", action=CreditAction.GRANT_PAID, amount=10_000)
    assert await ledger.has_sufficient_credits("u1", "article_basic") is False


# ----------------------------------------------------------- grants


async def test_grant_free_credit_writes_entry_with_default_value() -> None:
    ledger, fake = _make_ledger()
    entry = await ledger.grant_free_credit(
        user_id="u1", project_id="p1", reason=FreeCreditsReason.SOURCE_UPLOAD
    )
    assert entry is not None
    assert entry.action == CreditAction.GRANT_FREE
    assert entry.amount == CreditLedger.FREE_CREDIT_VALUE
    assert entry.project_id == "p1"
    assert entry.reason == FreeCreditsReason.SOURCE_UPLOAD.value
    inserted = [t for t, _ in fake.inserts]
    assert inserted == ["credit_ledger"]


async def test_grant_free_credit_blocked_by_daily_cap() -> None:
    ledger, fake = _make_ledger()
    today = datetime.now(UTC).replace(hour=12, minute=0, second=0, microsecond=0)
    for _ in range(CreditLedger.FREE_DAILY_CAP):
        _seed_entry(
            fake,
            user_id="u1",
            action=CreditAction.GRANT_FREE,
            amount=CreditLedger.FREE_CREDIT_VALUE,
            project_id="p1",
            created_at=today,
        )

    entry = await ledger.grant_free_credit(
        user_id="u1", project_id="p1", reason=FreeCreditsReason.SOURCE_UPLOAD
    )
    assert entry is None


async def test_grant_free_credit_blocked_by_weekly_cap() -> None:
    ledger, fake = _make_ledger()
    now = datetime.now(UTC)
    start_of_week = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(
        days=now.weekday()
    )
    # Spread WEEKLY_CAP entries across distinct projects so the per-project
    # cap does not fire first.
    for i in range(CreditLedger.FREE_WEEKLY_CAP):
        _seed_entry(
            fake,
            user_id="u1",
            action=CreditAction.GRANT_FREE,
            amount=CreditLedger.FREE_CREDIT_VALUE,
            project_id=f"p{i}",
            created_at=start_of_week + timedelta(hours=i * 6),
        )

    entry = await ledger.grant_free_credit(
        user_id="u1",
        project_id="p-new",
        reason=FreeCreditsReason.INTERVIEW_ANSWER,
    )
    assert entry is None


async def test_grant_free_credit_blocked_by_project_cap() -> None:
    ledger, fake = _make_ledger()
    # Spread across previous days so daily cap does not fire first.
    base = datetime.now(UTC) - timedelta(days=30)
    for i in range(CreditLedger.FREE_PROJECT_CAP):
        _seed_entry(
            fake,
            user_id="u1",
            action=CreditAction.GRANT_FREE,
            amount=CreditLedger.FREE_CREDIT_VALUE,
            project_id="p1",
            created_at=base + timedelta(days=i),
        )

    entry = await ledger.grant_free_credit(
        user_id="u1", project_id="p1", reason=FreeCreditsReason.SOURCE_UPLOAD
    )
    assert entry is None


async def test_grant_paid_credit_has_no_cap() -> None:
    ledger, _ = _make_ledger()
    entry = await ledger.grant_paid_credit(
        user_id="u1", amount_uzs=90_000, payment_reference="payme:txn-1"
    )
    assert entry.action == CreditAction.GRANT_PAID
    assert entry.amount == 90_000
    assert "payme:txn-1" in entry.reason


# --------------------------------------------------------- deduction


async def test_deduct_for_generation_records_negative_amount() -> None:
    ledger, fake = _make_ledger()
    _seed_entry(fake, user_id="u1", action=CreditAction.GRANT_PAID, amount=100_000)

    entry = await ledger.deduct_for_generation(
        user_id="u1", project_id="p1", product_type="article_basic"
    )
    assert entry.action == CreditAction.DEDUCT_ARTICLE
    assert entry.amount == -60_000
    assert await ledger.get_balance("u1") == 40_000


async def test_deduct_for_generation_picks_presentation_action_for_presentation_products() -> None:
    ledger, fake = _make_ledger()
    _seed_entry(fake, user_id="u1", action=CreditAction.GRANT_PAID, amount=100_000)

    entry = await ledger.deduct_for_generation(
        user_id="u1", project_id="p1", product_type="presentation_basic"
    )
    assert entry.action == CreditAction.DEDUCT_PRESENTATION
    assert entry.amount == -5_000


async def test_deduct_raises_insufficient_credits_with_balance_and_required() -> None:
    ledger, fake = _make_ledger()
    _seed_entry(fake, user_id="u1", action=CreditAction.GRANT_FREE, amount=10_000)

    with pytest.raises(InsufficientCreditsError) as excinfo:
        await ledger.deduct_for_generation(
            user_id="u1", project_id="p1", product_type="article_basic"
        )
    err = excinfo.value
    assert err.balance == 10_000
    assert err.required == 60_000


# --------------------------------------------------------------- refund


async def test_refund_restores_balance() -> None:
    ledger, fake = _make_ledger()
    _seed_entry(fake, user_id="u1", action=CreditAction.GRANT_PAID, amount=100_000)
    await ledger.deduct_for_generation(user_id="u1", project_id="p1", product_type="article_basic")
    assert await ledger.get_balance("u1") == 40_000

    await ledger.refund(
        user_id="u1", project_id="p1", amount_uzs=60_000, reason="generation failed"
    )
    assert await ledger.get_balance("u1") == 100_000


# -------------------------------------------------------------- pricing


def test_pricing_article_tiers() -> None:
    assert CreditLedger.PRICING["article_basic"] == 60_000
    assert CreditLedger.PRICING["article_standard"] == 90_000
    assert CreditLedger.PRICING["article_premium"] == 150_000


def test_pricing_presentation_tiers() -> None:
    assert CreditLedger.PRICING["presentation_basic"] == 5_000
    assert CreditLedger.PRICING["presentation_standard"] == 10_000
    assert CreditLedger.PRICING["presentation_premium"] == 15_000


def test_free_credit_value_matches_basic_presentation_price() -> None:
    assert CreditLedger.PRICING["presentation_basic"] == CreditLedger.FREE_CREDIT_VALUE


# --------------------------------------------------------- cap counting


async def test_free_credits_today_counts_only_today() -> None:
    ledger, fake = _make_ledger()
    today = datetime.now(UTC).replace(hour=12, minute=0, second=0, microsecond=0)
    yesterday = today - timedelta(days=1)
    _seed_entry(
        fake,
        user_id="u1",
        action=CreditAction.GRANT_FREE,
        amount=5_000,
        project_id="p",
        created_at=today,
    )
    _seed_entry(
        fake,
        user_id="u1",
        action=CreditAction.GRANT_FREE,
        amount=5_000,
        project_id="p",
        created_at=today,
    )
    _seed_entry(
        fake,
        user_id="u1",
        action=CreditAction.GRANT_FREE,
        amount=5_000,
        project_id="p",
        created_at=yesterday,
    )
    _seed_entry(
        fake,
        user_id="u1",
        action=CreditAction.GRANT_FREE,
        amount=5_000,
        project_id="p",
        created_at=yesterday,
    )
    _seed_entry(
        fake,
        user_id="u1",
        action=CreditAction.GRANT_FREE,
        amount=5_000,
        project_id="p",
        created_at=yesterday,
    )
    assert await ledger.get_free_credits_today("u1") == 2


async def test_free_credits_this_week_excludes_last_sunday() -> None:
    ledger, fake = _make_ledger()
    now = datetime.now(UTC)
    monday = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=now.weekday())
    last_sunday = monday - timedelta(seconds=1)

    _seed_entry(
        fake,
        user_id="u1",
        action=CreditAction.GRANT_FREE,
        amount=5_000,
        project_id="p",
        created_at=monday + timedelta(hours=3),
    )
    _seed_entry(
        fake,
        user_id="u1",
        action=CreditAction.GRANT_FREE,
        amount=5_000,
        project_id="p",
        created_at=monday + timedelta(days=2),
    )
    _seed_entry(
        fake,
        user_id="u1",
        action=CreditAction.GRANT_FREE,
        amount=5_000,
        project_id="p",
        created_at=last_sunday,
    )

    assert await ledger.get_free_credits_this_week("u1") == 2


async def test_free_credits_for_project_filters_by_project() -> None:
    ledger, fake = _make_ledger()
    for _ in range(3):
        _seed_entry(
            fake,
            user_id="u1",
            action=CreditAction.GRANT_FREE,
            amount=5_000,
            project_id="p1",
        )
    for _ in range(2):
        _seed_entry(
            fake,
            user_id="u1",
            action=CreditAction.GRANT_FREE,
            amount=5_000,
            project_id="p2",
        )
    assert await ledger.get_free_credits_for_project("u1", "p1") == 3
    assert await ledger.get_free_credits_for_project("u1", "p2") == 2


# ----------------------------------------------------------- read API


async def test_get_ledger_returns_typed_entries_newest_first() -> None:
    ledger, fake = _make_ledger()
    base = datetime(2026, 5, 1, tzinfo=UTC)
    _seed_entry(
        fake,
        user_id="u1",
        action=CreditAction.GRANT_PAID,
        amount=60_000,
        created_at=base,
    )
    _seed_entry(
        fake,
        user_id="u1",
        action=CreditAction.DEDUCT_ARTICLE,
        amount=-60_000,
        created_at=base + timedelta(days=1),
    )

    entries = await ledger.get_ledger("u1", limit=10)
    assert len(entries) == 2
    assert all(isinstance(e, CreditEntry) for e in entries)
    assert entries[0].action == CreditAction.DEDUCT_ARTICLE
    assert entries[1].action == CreditAction.GRANT_PAID
