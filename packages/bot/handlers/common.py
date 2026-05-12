"""Common command handlers: ``/start``, ``/help``, ``/balance``, ``/devgrant``.

These handlers do not belong to any FSM flow; they short-circuit
whatever conversation the user is in, look up the user record in the
database, and either start the registration funnel or show the main
menu. ``db: DatabaseClient`` is injected by the dispatcher's workflow
data (see :func:`packages.bot.app.create_bot`).

``/devgrant`` is an admin-only escape hatch: it credits the caller's
account with a fixed amount so test users can run paid flows without
touching Payme/Click. The handler silently ignores invocations from
non-admin Telegram IDs (configured via ``NASHR_ADMIN_IDS``) so it does
not advertise its existence to ordinary users.
"""

from __future__ import annotations

import logging
from typing import Any

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from packages.bot.keyboards import language_keyboard, main_menu_keyboard
from packages.bot.labels import get_bot_labels
from packages.bot.states import RegistrationStates
from packages.platform.config import PlatformConfig
from packages.platform.credits import CreditLedger
from packages.platform.database import DatabaseClient

logger = logging.getLogger("nashr.bot.common")

router = Router()

DEV_MODE_BANNER: str = "🔧 DEV MODE"


def _user_language(user: dict[str, Any] | None) -> str:
    """Return ``user.language`` or fall back to Uzbek."""

    if user is None:
        return "uz"
    lang = user.get("language")
    if isinstance(lang, str) and lang:
        return lang
    return "uz"


def _decorate_main_menu(menu_text: str, config: PlatformConfig | None) -> str:
    """Prepend the dev-mode banner when the platform is running in dev."""

    if config is not None and config.dev_mode:
        return f"{DEV_MODE_BANNER}\n\n{menu_text}"
    return menu_text


@router.message(CommandStart())
async def cmd_start(
    message: Message,
    state: FSMContext,
    db: DatabaseClient,
    config: PlatformConfig | None = None,
) -> None:
    """Route ``/start``: existing users see the menu, new users register."""

    if message.from_user is None:
        return
    user = await db.get_user_by_telegram_id(message.from_user.id)

    if user is not None:
        lang = _user_language(user)
        labels = get_bot_labels(lang)
        await message.answer(
            _decorate_main_menu(labels.main_menu, config),
            reply_markup=main_menu_keyboard(lang),
        )
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
async def cmd_balance(
    message: Message, db: DatabaseClient, credits: CreditLedger | None = None
) -> None:
    """Show the user's current credit balance."""

    if message.from_user is None:
        return
    user = await db.get_user_by_telegram_id(message.from_user.id)
    if user is None:
        await message.answer(get_bot_labels("uz").please_start_first)
        return

    lang = _user_language(user)
    labels = get_bot_labels(lang)
    if credits is None:
        await message.answer(labels.balance_info.format(balance="—", free_today="—"))
        return
    user_id = str(user["id"])
    balance = await credits.get_balance(user_id)
    free_today = await credits.get_free_credits_today(user_id)
    await message.answer(labels.balance_info.format(balance=f"{balance:,}", free_today=free_today))


@router.message(Command("devgrant"))
async def cmd_devgrant(
    message: Message,
    db: DatabaseClient,
    credits: CreditLedger,
    config: PlatformConfig,
) -> None:
    """Grant the caller a paid-credit row for development testing.

    Restricted to Telegram IDs listed in ``NASHR_ADMIN_IDS``; calls from
    non-admin users are silently ignored so the command does not leak
    its existence. Usage: ``/devgrant 100000``.
    """

    if message.from_user is None or message.text is None:
        return
    if message.from_user.id not in config.admin_telegram_ids:
        return

    parts = message.text.strip().split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Usage: /devgrant <amount_uzs>")
        return

    amount = int(parts[1])
    user = await db.get_user_by_telegram_id(message.from_user.id)
    if user is None:
        await message.answer("Register first with /start")
        return

    user_id = str(user["id"])
    await credits.grant_paid_credit(
        user_id=user_id,
        amount_uzs=amount,
        payment_reference=f"admin_grant_{message.from_user.id}",
    )
    balance = await credits.get_balance(user_id)
    await message.answer(f"Granted {amount:,} UZS. New balance: {balance:,} UZS")
