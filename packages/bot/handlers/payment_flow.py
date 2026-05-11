"""Payment flow scaffold: provider selection.

The full payment integration (invoice creation, deep-linking, webhook
verification, credit grant) is Task 31. This module handles the
``pay_*`` callback prefix so the article and presentation flows can
hand off cleanly without crashing.
"""

from __future__ import annotations

from typing import Any

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

router = Router()


def _flow_language(data: dict[str, Any]) -> str:
    lang = data.get("language")
    if isinstance(lang, str) and lang:
        return lang
    return "uz"


@router.callback_query(F.data.startswith("pay_"))
async def select_provider(callback: CallbackQuery, state: FSMContext) -> None:
    """Record the provider choice and show a placeholder receipt screen.

    Branching here documents the two paths the real handler in Task 31
    will take: balance-only payment goes through
    :class:`CreditLedger.deduct_for_generation`, every other provider
    goes through :class:`DatabaseClient.create_invoice` plus a
    deep-linked payment URL.
    """

    raw = callback.data or ""
    provider = raw.removeprefix("pay_")
    data = await state.get_data()
    _ = _flow_language(data)

    if isinstance(callback.message, Message):
        if provider == "balance":
            await callback.message.edit_text("Balance payment will be wired in Task 29.")
        else:
            await callback.message.edit_text(
                f"Payment via {provider}. Invoice system wired in Task 31."
            )

    await callback.answer()
