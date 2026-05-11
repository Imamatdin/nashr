"""Common command handlers: ``/start``, ``/help``, ``/balance``.

These handlers do not belong to any FSM flow; they short-circuit
whatever conversation the user is in, look up the user record in the
database, and either start the registration funnel or show the main
menu. ``db: DatabaseClient`` is injected by the dispatcher's workflow
data (see :func:`packages.bot.app.create_bot`).
"""

from __future__ import annotations

from typing import Any

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from packages.bot.keyboards import language_keyboard, main_menu_keyboard
from packages.bot.labels import get_bot_labels
from packages.bot.states import RegistrationStates
from packages.platform.database import DatabaseClient

router = Router()


def _user_language(user: dict[str, Any] | None) -> str:
    """Return ``user.language`` or fall back to Uzbek."""

    if user is None:
        return "uz"
    lang = user.get("language")
    if isinstance(lang, str) and lang:
        return lang
    return "uz"


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, db: DatabaseClient) -> None:
    """Route ``/start``: existing users see the menu, new users register."""

    if message.from_user is None:
        return
    user = await db.get_user_by_telegram_id(message.from_user.id)

    if user is not None:
        lang = _user_language(user)
        labels = get_bot_labels(lang)
        await message.answer(labels.main_menu, reply_markup=main_menu_keyboard(lang))
        return

    await message.answer(
        "🇺🇿 O'zbekcha / 🇷🇺 Русский / Qaraqalpaqsha / 🇬🇧 English",
        reply_markup=language_keyboard(),
    )
    await state.set_state(RegistrationStates.choosing_language)


@router.message(Command("help"))
async def cmd_help(message: Message, db: DatabaseClient) -> None:
    """Short help message listing the main menu items + commands."""

    if message.from_user is None:
        return
    user = await db.get_user_by_telegram_id(message.from_user.id)
    lang = _user_language(user)
    labels = get_bot_labels(lang)

    help_text = (
        f"{labels.create_article}\n"
        f"{labels.create_presentation}\n"
        f"{labels.my_projects}\n"
        f"{labels.my_balance}\n\n"
        f"/start — {labels.main_menu}\n"
        "/help — ?\n"
        "/balance"
    )
    await message.answer(help_text)


@router.message(Command("balance"))
async def cmd_balance(message: Message, db: DatabaseClient) -> None:
    """Show the user's credit balance.

    The actual balance read against :class:`CreditLedger` is wired in
    Task 29; this handler resolves the user record and renders the
    template so the formatting work is already done.
    """

    if message.from_user is None:
        return
    user = await db.get_user_by_telegram_id(message.from_user.id)
    if user is None:
        await message.answer(get_bot_labels("uz").please_start_first)
        return

    lang = _user_language(user)
    labels = get_bot_labels(lang)
    await message.answer(labels.balance_info.format(balance="—", free_today="—"))
