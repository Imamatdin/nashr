"""Payment flow: provider selection + balance-path hand-off to generation.

Two payment paths land here via the ``pay_*`` callback prefix:

* **Balance pay** (``pay_balance``) — for users who already hold credit,
  we deduct via :class:`CreditLedger.deduct_for_generation` and hand
  straight off to :func:`packages.bot.handlers.article_flow.start_generation`
  so the article (or presentation, later) renders without a round trip
  to an external payment provider. This is the only end-to-end live
  path for now and closes Task 27's deliverable criterion #8.

* **External providers** (Payme / Click / Uzum) — still scaffolded:
  Task 31 wires real invoice creation and webhook verification.
  Until then, those buttons show a placeholder.
"""

from __future__ import annotations

import logging
from typing import Any

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from packages.bot.handlers.article_flow import start_generation
from packages.bot.labels import get_bot_labels
from packages.bot.states import ArticleStates
from packages.platform.credits import CreditLedger, InsufficientCreditsError
from packages.platform.database import DatabaseClient

logger = logging.getLogger("nashr.bot.payment")

router = Router()


def _flow_language(data: dict[str, Any]) -> str:
    lang = data.get("language")
    if isinstance(lang, str) and lang:
        return lang
    return "uz"


@router.callback_query(F.data.startswith("pay_"))
async def select_provider(
    callback: CallbackQuery,
    state: FSMContext,
    bot: Bot,
    db: DatabaseClient,
    credits: CreditLedger,
) -> None:
    """Route the provider choice to the right hand-off.

    Balance-pay deducts and runs the post-payment generation pipeline.
    Other providers are still scaffolded — Task 31 will replace those
    placeholder edits with real invoice creation.
    """

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
    else:
        await callback.message.edit_text(
            f"{labels.payment_pending}\n\nProvider: {provider} (Task 31)."
        )
    await callback.answer()


async def _handle_balance_payment(
    message: Message,
    state: FSMContext,
    data: dict[str, Any],
    bot: Bot,
    db: DatabaseClient,
    credits: CreditLedger,
) -> None:
    """Deduct credits and run the article generation pipeline.

    On insufficient balance we surface the deficit via the localised
    template so the user knows exactly how much more they need. The
    deduction is committed *before* generation starts; a generation
    failure is refunded by :func:`start_generation` itself.
    """

    lang = _flow_language(data)
    labels = get_bot_labels(lang)
    user_id = str(data.get("user_id") or "")
    project_id = str(data.get("project_id") or "")
    tier = str(data.get("tier") or "article_basic")
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
    if tier.startswith("article"):
        await state.set_state(ArticleStates.generating)
        await start_generation(message, state, bot, db, credits)
    else:
        # Presentation balance-path lands when its generation orchestrator does.
        await message.answer(labels.generation_failed)
        await state.clear()
