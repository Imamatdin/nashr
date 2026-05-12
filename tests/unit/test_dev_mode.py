"""Tests for the dev-mode escape hatch and the ``/devgrant`` admin command.

Dev mode (``NASHR_ENV=development``) bypasses balance checks in
:class:`CreditLedger.deduct_for_generation` and prepends a banner to
the main menu. ``/devgrant`` is an admin-only command that grants a
paid-credit row directly; both pieces gate on
``PlatformConfig.admin_telegram_ids`` to avoid leaking the command's
existence to ordinary users.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, User

from packages.bot.handlers.common import cmd_devgrant
from packages.platform.config import PlatformConfig
from packages.platform.credits import CreditLedger, InsufficientCreditsError
from packages.platform.database import DatabaseClient
from tests.unit.test_database_client import FakeSupabaseClient


@pytest.fixture
def env_isolation(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Remove NASHR_* env vars so :meth:`from_env` reads a clean slate."""

    for var in ("NASHR_ENV", "NASHR_ADMIN_IDS"):
        monkeypatch.delenv(var, raising=False)
    yield


# ---------------------------------------------------------------------------
# PlatformConfig.from_env
# ---------------------------------------------------------------------------


def test_dev_mode_enabled_when_env_is_development(
    env_isolation: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NASHR_ENV", "development")
    config = PlatformConfig.from_env()
    assert config.dev_mode is True


def test_dev_mode_disabled_in_production_by_default(env_isolation: None) -> None:
    config = PlatformConfig.from_env()
    assert config.dev_mode is False


def test_dev_mode_disabled_for_arbitrary_other_values(
    env_isolation: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NASHR_ENV", "staging")
    config = PlatformConfig.from_env()
    assert config.dev_mode is False


def test_admin_ids_parsed_from_csv_env(
    env_isolation: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NASHR_ADMIN_IDS", "12345,67890,  111  ")
    config = PlatformConfig.from_env()
    assert config.admin_telegram_ids == (12345, 67890, 111)


def test_admin_ids_empty_by_default(env_isolation: None) -> None:
    config = PlatformConfig.from_env()
    assert config.admin_telegram_ids == ()


def test_admin_ids_skips_non_numeric_entries(
    env_isolation: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NASHR_ADMIN_IDS", "12345,not-a-number,67890")
    config = PlatformConfig.from_env()
    assert config.admin_telegram_ids == (12345, 67890)


# ---------------------------------------------------------------------------
# CreditLedger dev-mode behaviour
# ---------------------------------------------------------------------------


def _make_db() -> tuple[DatabaseClient, FakeSupabaseClient]:
    cfg = PlatformConfig(
        supabase_url="https://test.supabase.co",
        supabase_service_key="test",
        telegram_bot_token="test",
    )
    fake = FakeSupabaseClient()
    db = DatabaseClient(cfg, client=cast(Any, fake))
    return db, fake


async def test_dev_mode_skips_balance_check_but_still_records_entry() -> None:
    db, fake = _make_db()
    ledger = CreditLedger(db, dev_mode=True)

    # Zero balance — production would raise InsufficientCreditsError.
    entry = await ledger.deduct_for_generation(
        user_id="user_x",
        project_id="proj_x",
        product_type="presentation_basic",
    )

    assert entry.amount == -5_000
    assert entry.action.value == "deduct_presentation"
    rows = fake.tables.get("credit_ledger", [])
    assert len(rows) == 1
    assert rows[0]["amount"] == -5_000


async def test_production_mode_still_raises_on_insufficient_balance() -> None:
    db, _fake = _make_db()
    ledger = CreditLedger(db, dev_mode=False)

    with pytest.raises(InsufficientCreditsError) as exc_info:
        await ledger.deduct_for_generation(
            user_id="user_x", project_id="proj_x", product_type="presentation_basic"
        )

    assert exc_info.value.required == 5_000
    assert exc_info.value.balance == 0


async def test_dev_mode_has_sufficient_credits_always_true() -> None:
    db, _ = _make_db()
    ledger = CreditLedger(db, dev_mode=True)

    assert await ledger.has_sufficient_credits("user_x", "presentation_premium") is True


async def test_production_mode_has_sufficient_credits_checks_balance() -> None:
    db, _ = _make_db()
    ledger = CreditLedger(db, dev_mode=False)

    assert await ledger.has_sufficient_credits("user_x", "presentation_premium") is False


# ---------------------------------------------------------------------------
# /devgrant command
# ---------------------------------------------------------------------------


@pytest.fixture
def state() -> FSMContext:
    storage = MemoryStorage()
    key = StorageKey(bot_id=1, user_id=11, chat_id=22)
    return FSMContext(storage=storage, key=key)


def _message_with(text: str, from_id: int) -> MagicMock:
    msg = MagicMock(spec=Message)
    msg.text = text
    user = MagicMock(spec=User)
    user.id = from_id
    msg.from_user = user
    msg.answer = AsyncMock(return_value=msg)
    return msg


async def test_devgrant_ignores_non_admin_caller() -> None:
    db = MagicMock()
    db.get_user_by_telegram_id = AsyncMock(return_value={"id": "u1"})
    credits = MagicMock()
    credits.grant_paid_credit = AsyncMock()
    credits.get_balance = AsyncMock(return_value=0)
    config = PlatformConfig(
        supabase_url="",
        supabase_service_key="",
        telegram_bot_token="t",
        admin_telegram_ids=(999,),
    )

    msg = _message_with("/devgrant 100000", from_id=42)
    await cmd_devgrant(
        cast(Any, msg),
        cast(Any, db),
        cast(Any, credits),
        config,
    )

    msg.answer.assert_not_awaited()
    credits.grant_paid_credit.assert_not_awaited()


async def test_devgrant_admin_grants_credit_and_reports_balance() -> None:
    db = MagicMock()
    db.get_user_by_telegram_id = AsyncMock(return_value={"id": "u_admin"})
    credits = MagicMock()
    credits.grant_paid_credit = AsyncMock()
    credits.get_balance = AsyncMock(return_value=100_000)
    config = PlatformConfig(
        supabase_url="",
        supabase_service_key="",
        telegram_bot_token="t",
        admin_telegram_ids=(42,),
    )

    msg = _message_with("/devgrant 100000", from_id=42)
    await cmd_devgrant(
        cast(Any, msg),
        cast(Any, db),
        cast(Any, credits),
        config,
    )

    credits.grant_paid_credit.assert_awaited_once()
    grant_kwargs = credits.grant_paid_credit.await_args.kwargs
    assert grant_kwargs["amount_uzs"] == 100_000
    assert grant_kwargs["user_id"] == "u_admin"
    msg.answer.assert_awaited_once()
    sent = msg.answer.await_args.args[0]
    assert "100,000" in sent
    assert "100,000 UZS" in sent  # new balance line


async def test_devgrant_with_bad_argument_shows_usage() -> None:
    db = MagicMock()
    credits = MagicMock()
    credits.grant_paid_credit = AsyncMock()
    config = PlatformConfig(
        supabase_url="",
        supabase_service_key="",
        telegram_bot_token="t",
        admin_telegram_ids=(42,),
    )

    msg = _message_with("/devgrant abc", from_id=42)
    await cmd_devgrant(
        cast(Any, msg),
        cast(Any, db),
        cast(Any, credits),
        config,
    )

    msg.answer.assert_awaited_once()
    assert "Usage" in msg.answer.await_args.args[0]
    credits.grant_paid_credit.assert_not_awaited()


async def test_devgrant_unregistered_admin_is_told_to_start() -> None:
    db = MagicMock()
    db.get_user_by_telegram_id = AsyncMock(return_value=None)
    credits = MagicMock()
    credits.grant_paid_credit = AsyncMock()
    config = PlatformConfig(
        supabase_url="",
        supabase_service_key="",
        telegram_bot_token="t",
        admin_telegram_ids=(42,),
    )

    msg = _message_with("/devgrant 100000", from_id=42)
    await cmd_devgrant(
        cast(Any, msg),
        cast(Any, db),
        cast(Any, credits),
        config,
    )

    credits.grant_paid_credit.assert_not_awaited()
    msg.answer.assert_awaited_once()
    sent = msg.answer.await_args.args[0]
    assert "/start" in sent


# ---------------------------------------------------------------------------
# Reference: env_isolation hides the var the conftest leaves behind
# ---------------------------------------------------------------------------


def test_env_isolation_actually_unsets(env_isolation: None) -> None:
    """Smoke test: the fixture removes the variables before the test runs."""

    assert os.environ.get("NASHR_ENV") is None
    assert os.environ.get("NASHR_ADMIN_IDS") is None
