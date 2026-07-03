"""Behaviour tests for the catch-all fallback callback router.

The fallback router is registered LAST in :func:`packages.bot.app.create_bot`,
so its single handler only ever fires for callbacks no other router matched —
a button from a since-cleared conversation. It answers a short toast so the
Telegram client stops its loading spinner, and deliberately sends NO chat
message (a stale button must not spam the chat). The toast language comes from
FSM data when present, else the stored user profile, else Uzbek.
"""

from __future__ import annotations

from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, Message

from packages.bot.handlers.fallback import unmatched_callback
from packages.bot.labels import get_bot_labels


@pytest.fixture
def state() -> FSMContext:
    storage = MemoryStorage()
    key = StorageKey(bot_id=1, user_id=11, chat_id=22)
    return FSMContext(storage=storage, key=key)


def _make_callback() -> MagicMock:
    msg = MagicMock(spec=Message)
    msg.answer = AsyncMock()
    cb = MagicMock(spec=CallbackQuery)
    cb.data = "obsolete_button_data"
    cb.message = msg
    cb.answer = AsyncMock()
    cb.from_user = MagicMock()
    cb.from_user.id = 5555
    return cb


async def test_unmatched_callback_uses_fsm_language_without_db(state: FSMContext) -> None:
    await state.update_data(language="ru")
    cb = _make_callback()
    db = MagicMock()
    db.get_user_by_telegram_id = AsyncMock()

    await unmatched_callback(cast(Any, cb), state, cast(Any, db))

    cb.answer.assert_awaited_once_with(get_bot_labels("ru").stale_button)
    cb.message.answer.assert_not_awaited()
    db.get_user_by_telegram_id.assert_not_awaited()


async def test_unmatched_callback_falls_back_to_user_profile_language(
    state: FSMContext,
) -> None:
    """After ``state.clear()`` the FSM has no language; the stored profile wins."""

    cb = _make_callback()
    db = MagicMock()
    db.get_user_by_telegram_id = AsyncMock(return_value={"id": "u1", "language": "ru"})

    await unmatched_callback(cast(Any, cb), state, cast(Any, db))

    cb.answer.assert_awaited_once_with(get_bot_labels("ru").stale_button)
    db.get_user_by_telegram_id.assert_awaited_once_with(5555)


async def test_unmatched_callback_defaults_to_uz_for_unknown_user(state: FSMContext) -> None:
    cb = _make_callback()
    db = MagicMock()
    db.get_user_by_telegram_id = AsyncMock(return_value=None)

    await unmatched_callback(cast(Any, cb), state, cast(Any, db))

    cb.answer.assert_awaited_once_with(get_bot_labels("uz").stale_button)


async def test_unmatched_callback_db_error_still_answers_in_uz(state: FSMContext) -> None:
    cb = _make_callback()
    db = MagicMock()
    db.get_user_by_telegram_id = AsyncMock(side_effect=RuntimeError("db down"))

    await unmatched_callback(cast(Any, cb), state, cast(Any, db))

    cb.answer.assert_awaited_once_with(get_bot_labels("uz").stale_button)


async def test_create_bot_registers_fallback_router_last() -> None:
    """``create_bot`` must include the fallback router AFTER every other one, so it
    only ever sees callbacks no flow matched."""

    from packages.bot.app import create_bot
    from packages.platform.config import PlatformConfig

    config = PlatformConfig(
        supabase_url="https://test.supabase.co",
        supabase_service_key="test-service-key",
        telegram_bot_token="123456:AAHtest-token-value-goes-here-000000",
    )
    bot, dp = await create_bot(
        config,
        db=cast(Any, MagicMock()),
        credits=cast(Any, MagicMock()),
        storage=cast(Any, MagicMock()),
    )
    try:
        assert dp.sub_routers[-1].name == "fallback"
    finally:
        # aiogram routers are single-attach: detach the shared module-level
        # singletons so other tests can build their own dispatchers from them.
        for sub in dp.sub_routers:
            sub._parent_router = None
        await bot.session.close()
