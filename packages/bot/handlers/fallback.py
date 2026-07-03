"""Catch-all callback answerer for stale inline buttons.

This router is registered LAST in :func:`packages.bot.app.create_bot` (after
every flow and payment router), so its single handler only ever sees callback
queries that NO other router matched — a button from a conversation that has
since been cleared or moved on. Telegram keeps showing a loading spinner on the
button until the callback is answered; answering it here stops that spinner and
shows a short toast. It deliberately sends no chat message: a stale button must
not push a new line into the chat.
"""

from __future__ import annotations

import contextlib

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from packages.bot.labels import get_bot_labels
from packages.platform.database import DatabaseClient

router = Router(name="fallback")


@router.callback_query()
async def unmatched_callback(
    callback: CallbackQuery, state: FSMContext, db: DatabaseClient
) -> None:
    """Answer any unmatched callback with a short 'expired' toast.

    Resolves the user's language from FSM data first; a stale button usually
    arrives AFTER ``state.clear()`` wiped that, so the stored user profile is
    the second source. Falls back to Uzbek (the bot-wide default) when both
    are unavailable — including on a DB error, which must never break the
    toast.
    """

    data = await state.get_data()
    lang = data.get("language")
    if not isinstance(lang, str):
        with contextlib.suppress(Exception):
            user = await db.get_user_by_telegram_id(callback.from_user.id)
            if user is not None:
                lang = user.get("language")
    labels = get_bot_labels(lang if isinstance(lang, str) else "uz")
    await callback.answer(labels.stale_button)
