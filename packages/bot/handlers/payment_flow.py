"""Payment flow: balance pay + external invoice + provider deep links.

Two payment paths land here via the ``pay_*`` callback prefix:

* **Balance pay** (``pay_balance``) — for users who already hold credit
  (or in dev mode, where balance checks are bypassed), we deduct via
  :class:`CreditLedger.deduct_for_generation` and hand straight off to
  the right flow's ``start_generation`` so the article or presentation
  renders without a round trip to an external payment provider.

* **External providers** (``pay_payme`` / ``pay_click`` / ``pay_uzum``)
  — create a pending invoice via :class:`InvoiceService`, render an
  inline deep-link to the chosen app, and wait for the provider's
  webhook to finalise the payment. In dev mode the same path
  auto-confirms after a short delay so the rest of the flow can be
  exercised end-to-end without merchant credentials.

The matching ``cancel_payment`` callback expires the pending invoice
and drops the user back to the main menu.

CLAUDE.md's 300-line cap is intentionally exceeded: the balance and
external paths share enough state (FSM data, tier inference, hand-off
to ``article_flow.start_generation`` / ``presentation_flow.start_generation``)
that splitting them across files would scatter the conversation.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from packages.bot.handlers import article_flow, presentation_flow
from packages.bot.keyboards import main_menu_keyboard
from packages.bot.labels import get_bot_labels
from packages.bot.states import ArticleStates, PresentationStates
from packages.platform.config import PlatformConfig
from packages.platform.credits import CreditLedger, InsufficientCreditsError
from packages.platform.database import DatabaseClient
from packages.platform.invoices import InvoiceService

logger = logging.getLogger("nashr.bot.payment")

router = Router()

EXTERNAL_PROVIDERS: frozenset[str] = frozenset({"payme", "click", "uzum"})
PROVIDER_DISPLAY_NAMES: dict[str, str] = {"payme": "Payme", "click": "Click", "uzum": "Uzum"}

# Seconds the dev-mode auto-confirm waits before simulating a paid webhook.
DEV_MODE_AUTOCONFIRM_DELAY: float = 2.0

# Strong refs to in-flight dev-mode auto-confirm tasks so the asyncio
# garbage collector does not drop them mid-sleep.
_DEV_AUTOCONFIRM_TASKS: set[asyncio.Task[None]] = set()


def _flow_language(data: dict[str, Any]) -> str:
    lang = data.get("language")
    if isinstance(lang, str) and lang:
        return lang
    return "uz"


def _tier_default_for_state(current_state: str | None) -> str:
    """Choose a fall-back tier when FSM data is missing the chosen tier."""

    if current_state and "article" in current_state.lower():
        return "article_basic"
    return "presentation_basic"


@router.callback_query(F.data.startswith("pay_"))
async def select_provider(
    callback: CallbackQuery,
    state: FSMContext,
    bot: Bot,
    db: DatabaseClient,
    credits: CreditLedger,
    config: PlatformConfig,
) -> None:
    """Route the provider choice: balance hand-off or external invoice."""

    raw = callback.data or ""
    provider = raw.removeprefix("pay_")
    data = await state.get_data()
    lang = _flow_language(data)
    labels = get_bot_labels(lang)

    if not isinstance(callback.message, Message):
        await callback.answer()
        return

    if provider == "balance":
        await _handle_balance_payment(callback.message, state, data, bot, db, credits)
        await callback.answer()
        return

    if provider in EXTERNAL_PROVIDERS:
        await _handle_external_payment(
            callback.message,
            state,
            data,
            provider,
            bot,
            db,
            credits,
            config,
        )
        await callback.answer()
        return

    await callback.message.edit_text(f"{labels.payment_pending}\n\nProvider: {provider}")
    await callback.answer()


@router.callback_query(F.data == "cancel_payment")
async def cancel_payment(
    callback: CallbackQuery,
    state: FSMContext,
    db: DatabaseClient,
) -> None:
    """Cancel the pending invoice and return to the main menu."""

    data = await state.get_data()
    lang = _flow_language(data)
    labels = get_bot_labels(lang)
    invoice_number = data.get("invoice_number")
    if isinstance(invoice_number, str) and invoice_number:
        invoice = await db.get_invoice_by_number(invoice_number)
        if invoice is not None and invoice.get("status") == "pending":
            invoice_id = invoice.get("id")
            if isinstance(invoice_id, str):
                await db.mark_invoice_expired(invoice_id)

    if isinstance(callback.message, Message):
        await callback.message.edit_text(labels.main_menu, reply_markup=main_menu_keyboard(lang))
    await state.clear()
    await callback.answer()


# ---------------------------------------------------------------------------
# Balance-pay path
# ---------------------------------------------------------------------------


async def _handle_balance_payment(
    message: Message,
    state: FSMContext,
    data: dict[str, Any],
    bot: Bot,
    db: DatabaseClient,
    credits: CreditLedger,
) -> None:
    """Deduct credits and hand off to the appropriate generation pipeline."""

    lang = _flow_language(data)
    labels = get_bot_labels(lang)
    user_id = str(data.get("user_id") or "")
    project_id = str(data.get("project_id") or "")
    current_state = await state.get_state()
    tier = str(data.get("tier") or _tier_default_for_state(current_state))

    if not user_id or not project_id:
        await message.edit_text(labels.generation_failed)
        await state.clear()
        return

    try:
        await credits.deduct_for_generation(
            user_id=user_id, project_id=project_id, product_type=tier
        )
    except InsufficientCreditsError as exc:
        await message.edit_text(
            labels.insufficient_balance.format(balance=exc.balance, required=exc.required)
        )
        return
    except KeyError:
        logger.warning("payment_unknown_tier", extra={"tier": tier})
        await message.edit_text(labels.generation_failed)
        await state.clear()
        return

    await message.edit_text(labels.payment_confirmed)
    await _trigger_generation(message, state, tier, bot, db, credits)


# ---------------------------------------------------------------------------
# External-provider path
# ---------------------------------------------------------------------------


async def _handle_external_payment(
    message: Message,
    state: FSMContext,
    data: dict[str, Any],
    provider: str,
    bot: Bot,
    db: DatabaseClient,
    credits: CreditLedger,
    config: PlatformConfig,
) -> None:
    """Create an invoice, show the deep link, kick off dev auto-confirm."""

    lang = _flow_language(data)
    labels = get_bot_labels(lang)
    user_id = str(data.get("user_id") or "")
    project_id = str(data.get("project_id") or "")
    current_state = await state.get_state()
    tier = str(data.get("tier") or _tier_default_for_state(current_state))

    if not user_id or not project_id:
        await message.edit_text(labels.generation_failed)
        await state.clear()
        return

    invoice_service = InvoiceService(db, credits)
    try:
        invoice = await invoice_service.create_invoice(
            user_id=user_id, project_id=project_id, product_type=tier
        )
    except ValueError as exc:
        await message.edit_text(f"{labels.generation_failed}\n\n{exc}")
        return

    invoice_number = str(invoice.get("invoice_number", ""))
    amount = int(invoice.get("amount_uzs", 0))
    deep_link = invoice_service.generate_deep_link(
        provider=provider, invoice_number=invoice_number, amount_uzs=amount
    )

    keyboard_rows: list[list[InlineKeyboardButton]] = []
    if deep_link:
        keyboard_rows.append(
            [
                InlineKeyboardButton(
                    text=f"💳 {PROVIDER_DISPLAY_NAMES.get(provider, provider)}",
                    url=deep_link,
                )
            ]
        )
    keyboard_rows.append([InlineKeyboardButton(text=labels.cancel, callback_data="cancel_payment")])

    await message.edit_text(
        labels.invoice_created.format(invoice_number=invoice_number, amount=f"{amount:,}"),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard_rows),
    )
    await state.update_data(invoice_number=invoice_number, payment_provider=provider)

    if config.dev_mode:
        task = asyncio.create_task(
            _dev_mode_auto_confirm(
                message=message,
                state=state,
                invoice_service=invoice_service,
                invoice_number=invoice_number,
                provider=provider,
                amount_uzs=amount,
                tier=tier,
                bot=bot,
                db=db,
                credits=credits,
            )
        )
        _DEV_AUTOCONFIRM_TASKS.add(task)
        task.add_done_callback(_DEV_AUTOCONFIRM_TASKS.discard)


async def _dev_mode_auto_confirm(
    message: Message,
    state: FSMContext,
    invoice_service: InvoiceService,
    invoice_number: str,
    provider: str,
    amount_uzs: int,
    tier: str,
    bot: Bot,
    db: DatabaseClient,
    credits: CreditLedger,
) -> None:
    """Simulate a successful provider webhook after a short delay."""

    await asyncio.sleep(DEV_MODE_AUTOCONFIRM_DELAY)
    data = await state.get_data()
    lang = _flow_language(data)
    labels = get_bot_labels(lang)
    try:
        await invoice_service.process_payment(
            invoice_number=invoice_number,
            payment_provider=provider,
            payment_reference=f"dev_auto_{invoice_number}",
            amount_uzs=amount_uzs,
        )
    except Exception as exc:
        logger.error(
            "dev_autoconfirm_failed",
            extra={"invoice_number": invoice_number, "error_type": type(exc).__name__},
        )
        return

    user_id = str(data.get("user_id") or "")
    project_id = str(data.get("project_id") or "")
    if user_id and project_id:
        try:
            await credits.deduct_for_generation(
                user_id=user_id, project_id=project_id, product_type=tier
            )
        except Exception as exc:
            logger.warning(
                "dev_autoconfirm_deduct_failed",
                extra={"error_type": type(exc).__name__},
            )

    await message.answer(labels.payment_confirmed)
    await _trigger_generation(message, state, tier, bot, db, credits)


# ---------------------------------------------------------------------------
# Shared post-payment hand-off
# ---------------------------------------------------------------------------


async def _trigger_generation(
    message: Message,
    state: FSMContext,
    tier: str,
    bot: Bot,
    db: DatabaseClient,
    credits: CreditLedger,
) -> None:
    """Route the post-payment hand-off to the right generation pipeline."""

    data = await state.get_data()
    lang = _flow_language(data)
    labels = get_bot_labels(lang)

    if tier.startswith("article"):
        await state.set_state(ArticleStates.generating)
        await article_flow.start_generation(message, state, bot, db, credits)
        return
    if tier.startswith("presentation"):
        await state.set_state(PresentationStates.generating)
        await presentation_flow.start_generation(message, state, bot, db, credits)
        return

    logger.warning("payment_unknown_tier_prefix", extra={"tier": tier})
    await message.answer(labels.generation_failed)
    await state.clear()
