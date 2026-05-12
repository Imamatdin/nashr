"""Payment flow: provider selection + balance-path hand-off to generation.

Two payment paths land here via the ``pay_*`` callback prefix:

* **Balance pay** (``pay_balance``) — for users who already hold credit
  (or in dev mode, where balance checks are bypassed), we deduct via
  :class:`CreditLedger.deduct_for_generation` and hand straight off to
  the right flow's ``start_generation`` so the article or presentation
  renders without a round trip to an external payment provider.

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

from packages.bot.handlers import article_flow, presentation_flow
from packages.bot.labels import get_bot_labels
from packages.bot.states import ArticleStates, PresentationStates
from packages.platform.credits import CreditLedger, InsufficientCreditsError
from packages.platform.database import DatabaseClient

logger = logging.getLogger("nashr.bot.payment")

router = Router()


def _flow_language(data: dict[str, Any]) -> str:
    lang = data.get("language")
    if isinstance(lang, str) and lang:
        return lang
    return "uz"


def _tier_default_for_state(current_state: str | None) -> str:
    """Choose a fall-back tier when FSM data is missing the chosen tier.

    Falls back to ``article_basic`` for article flows and
    ``presentation_basic`` otherwise; the bot always populates ``tier``
    in normal flow, so this only matters in the (very rare) case the
    FSM lost it.
    """

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
) -> None:
    """Route the provider choice to the right hand-off.

    Balance-pay deducts and runs the post-payment generation pipeline
    for whichever flow (article or presentation) the user is in. Other
    providers are still scaffolded.
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

    if tier.startswith("article"):
        await state.set_state(ArticleStates.generating)
        await article_flow.start_generation(message, state, bot, db, credits)
    elif tier.startswith("presentation"):
        await state.set_state(PresentationStates.generating)
        await presentation_flow.start_generation(message, state, bot, db, credits)
    else:
        logger.warning("payment_unknown_tier_prefix", extra={"tier": tier})
        await message.answer(labels.generation_failed)
        await state.clear()
