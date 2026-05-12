"""Behaviour tests for :mod:`packages.bot.handlers.payment_flow`.

The balance-pay path is covered indirectly by the article-flow and
presentation-flow handler suites; this file focuses on the new
invoice-based external-provider path (Payme / Click / Uzum), the
``cancel_payment`` callback, and the dev-mode auto-confirm scheduling.

We drive handlers directly with :class:`MagicMock` spies for messages
and callbacks (the same shape as :mod:`test_article_flow_handlers`).
The FSM context is real — a :class:`MemoryStorage`-backed
:class:`FSMContext` so state transitions are asserted against actual
storage rather than method spies.
"""

from __future__ import annotations

from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from packages.bot.handlers.payment_flow import (
    _dev_mode_auto_confirm,
    cancel_payment,
    select_provider,
)
from packages.bot.states import ArticleStates
from packages.platform.config import PlatformConfig


def _make_message_spy() -> MagicMock:
    msg = MagicMock(spec=Message)
    msg.answer = AsyncMock(return_value=msg)
    msg.edit_text = AsyncMock(return_value=msg)
    return msg


def _make_callback_spy(*, data: str, message: MagicMock) -> MagicMock:
    cb = MagicMock(spec=CallbackQuery)
    cb.data = data
    cb.message = message
    cb.answer = AsyncMock(return_value=True)
    return cb


def _config(dev_mode: bool = False) -> PlatformConfig:
    return PlatformConfig(
        supabase_url="https://test.supabase.co",
        supabase_service_key="test-service-key",
        telegram_bot_token="test-token",
        dev_mode=dev_mode,
    )


@pytest.fixture
def state() -> FSMContext:
    storage = MemoryStorage()
    key = StorageKey(bot_id=1, user_id=11, chat_id=22)
    return FSMContext(storage=storage, key=key)


# ---------------------------------------------------------------------------
# External provider selection
# ---------------------------------------------------------------------------


async def test_select_payme_creates_invoice_and_shows_deep_link(state: FSMContext) -> None:
    await state.set_state(ArticleStates.confirming_payment)
    await state.update_data(language="uz", user_id="u1", project_id="p1", tier="article_basic")
    msg = _make_message_spy()
    callback = _make_callback_spy(data="pay_payme", message=msg)
    db = MagicMock()
    db.get_pending_invoice = AsyncMock(return_value=None)
    db.create_invoice = AsyncMock(
        return_value={
            "id": "inv1",
            "invoice_number": "847291-1001",
            "amount_uzs": 60_000,
            "status": "pending",
        }
    )
    credits = MagicMock()
    bot = MagicMock()
    config = _config(dev_mode=False)

    await select_provider(
        cast(Any, callback),
        state,
        cast(Any, bot),
        cast(Any, db),
        cast(Any, credits),
        config,
    )

    db.create_invoice.assert_awaited_once()
    msg.edit_text.assert_awaited_once()
    sent_text = msg.edit_text.await_args.args[0]
    assert "847291-1001" in sent_text
    assert "60,000" in sent_text

    markup = msg.edit_text.await_args.kwargs.get("reply_markup")
    assert isinstance(markup, InlineKeyboardMarkup)
    flat = [btn for row in markup.inline_keyboard for btn in row]
    assert any(getattr(b, "url", None) and "payme.uz" in (b.url or "") for b in flat)
    assert any(b.callback_data == "cancel_payment" for b in flat)

    data = await state.get_data()
    assert data["invoice_number"] == "847291-1001"
    assert data["payment_provider"] == "payme"


async def test_select_click_creates_invoice_and_uses_click_url(state: FSMContext) -> None:
    await state.set_state(ArticleStates.confirming_payment)
    await state.update_data(
        language="uz", user_id="u1", project_id="p1", tier="presentation_standard"
    )
    msg = _make_message_spy()
    callback = _make_callback_spy(data="pay_click", message=msg)
    db = MagicMock()
    db.get_pending_invoice = AsyncMock(return_value=None)
    db.create_invoice = AsyncMock(
        return_value={
            "id": "inv2",
            "invoice_number": "100000-2222",
            "amount_uzs": 10_000,
            "status": "pending",
        }
    )
    credits = MagicMock()
    config = _config(dev_mode=False)

    await select_provider(
        cast(Any, callback),
        state,
        cast(Any, MagicMock()),
        cast(Any, db),
        cast(Any, credits),
        config,
    )

    markup = msg.edit_text.await_args.kwargs.get("reply_markup")
    assert isinstance(markup, InlineKeyboardMarkup)
    flat = [btn for row in markup.inline_keyboard for btn in row]
    click_buttons = [b for b in flat if getattr(b, "url", None) and "click.uz" in (b.url or "")]
    assert click_buttons, "Expected Click deep-link button"


async def test_select_uzum_creates_invoice_and_uses_uzum_url(state: FSMContext) -> None:
    await state.set_state(ArticleStates.confirming_payment)
    await state.update_data(
        language="uz", user_id="u1", project_id="p1", tier="presentation_premium"
    )
    msg = _make_message_spy()
    callback = _make_callback_spy(data="pay_uzum", message=msg)
    db = MagicMock()
    db.get_pending_invoice = AsyncMock(return_value=None)
    db.create_invoice = AsyncMock(
        return_value={
            "id": "inv3",
            "invoice_number": "100000-3333",
            "amount_uzs": 15_000,
            "status": "pending",
        }
    )
    credits = MagicMock()
    config = _config(dev_mode=False)

    await select_provider(
        cast(Any, callback),
        state,
        cast(Any, MagicMock()),
        cast(Any, db),
        cast(Any, credits),
        config,
    )

    markup = msg.edit_text.await_args.kwargs.get("reply_markup")
    assert isinstance(markup, InlineKeyboardMarkup)
    flat = [btn for row in markup.inline_keyboard for btn in row]
    assert any(getattr(b, "url", None) and "uzumbank.uz" in (b.url or "") for b in flat)


async def test_select_provider_missing_ids_shows_failed(state: FSMContext) -> None:
    await state.set_state(ArticleStates.confirming_payment)
    await state.update_data(language="uz")
    msg = _make_message_spy()
    callback = _make_callback_spy(data="pay_payme", message=msg)
    db = MagicMock()
    db.create_invoice = AsyncMock()
    credits = MagicMock()
    config = _config(dev_mode=False)

    await select_provider(
        cast(Any, callback),
        state,
        cast(Any, MagicMock()),
        cast(Any, db),
        cast(Any, credits),
        config,
    )

    db.create_invoice.assert_not_called()
    msg.edit_text.assert_awaited_once()
    assert (await state.get_state()) is None


async def test_select_provider_invoice_creation_fails_shows_error(state: FSMContext) -> None:
    await state.set_state(ArticleStates.confirming_payment)
    await state.update_data(language="uz", user_id="u1", project_id="p1", tier="article_basic")
    msg = _make_message_spy()
    callback = _make_callback_spy(data="pay_payme", message=msg)
    db = MagicMock()
    db.get_pending_invoice = AsyncMock(return_value=None)
    db.create_invoice = AsyncMock(side_effect=ValueError("user has no subscriber_id"))
    credits = MagicMock()
    config = _config(dev_mode=False)

    await select_provider(
        cast(Any, callback),
        state,
        cast(Any, MagicMock()),
        cast(Any, db),
        cast(Any, credits),
        config,
    )

    msg.edit_text.assert_awaited_once()
    text = msg.edit_text.await_args.args[0]
    assert "subscriber_id" in text or "Xato" in text or "xato" in text.lower()


# ---------------------------------------------------------------------------
# cancel_payment
# ---------------------------------------------------------------------------


async def test_cancel_payment_marks_invoice_expired(state: FSMContext) -> None:
    await state.set_state(ArticleStates.confirming_payment)
    await state.update_data(
        language="uz",
        user_id="u1",
        project_id="p1",
        invoice_number="847291-1001",
    )
    msg = _make_message_spy()
    callback = _make_callback_spy(data="cancel_payment", message=msg)
    db = MagicMock()
    db.get_invoice_by_number = AsyncMock(return_value={"id": "inv1", "status": "pending"})
    db.mark_invoice_expired = AsyncMock(return_value=None)

    await cancel_payment(cast(Any, callback), state, cast(Any, db))

    db.mark_invoice_expired.assert_awaited_once_with("inv1")
    msg.edit_text.assert_awaited_once()
    assert (await state.get_state()) is None


async def test_cancel_payment_skips_when_invoice_already_paid(state: FSMContext) -> None:
    await state.set_state(ArticleStates.confirming_payment)
    await state.update_data(
        language="uz", invoice_number="847291-1001", user_id="u1", project_id="p1"
    )
    msg = _make_message_spy()
    callback = _make_callback_spy(data="cancel_payment", message=msg)
    db = MagicMock()
    db.get_invoice_by_number = AsyncMock(return_value={"id": "inv1", "status": "paid"})
    db.mark_invoice_expired = AsyncMock()

    await cancel_payment(cast(Any, callback), state, cast(Any, db))

    db.mark_invoice_expired.assert_not_called()
    assert (await state.get_state()) is None


async def test_cancel_payment_with_no_invoice_in_state_still_clears(state: FSMContext) -> None:
    await state.set_state(ArticleStates.confirming_payment)
    await state.update_data(language="uz")
    msg = _make_message_spy()
    callback = _make_callback_spy(data="cancel_payment", message=msg)
    db = MagicMock()
    db.get_invoice_by_number = AsyncMock(return_value=None)
    db.mark_invoice_expired = AsyncMock()

    await cancel_payment(cast(Any, callback), state, cast(Any, db))

    db.mark_invoice_expired.assert_not_called()
    msg.edit_text.assert_awaited_once()
    assert (await state.get_state()) is None


# ---------------------------------------------------------------------------
# Dev mode auto-confirm
# ---------------------------------------------------------------------------


async def test_dev_mode_schedules_auto_confirm_task(state: FSMContext) -> None:
    """In dev mode, selecting an external provider schedules an auto-confirm task."""

    await state.set_state(ArticleStates.confirming_payment)
    await state.update_data(language="uz", user_id="u1", project_id="p1", tier="article_basic")
    msg = _make_message_spy()
    callback = _make_callback_spy(data="pay_payme", message=msg)
    db = MagicMock()
    db.get_pending_invoice = AsyncMock(return_value=None)
    db.create_invoice = AsyncMock(
        return_value={
            "id": "inv1",
            "invoice_number": "847291-1001",
            "amount_uzs": 60_000,
            "status": "pending",
        }
    )
    credits = MagicMock()
    config = _config(dev_mode=True)

    with patch("packages.bot.handlers.payment_flow.asyncio.create_task") as create_task:
        await select_provider(
            cast(Any, callback),
            state,
            cast(Any, MagicMock()),
            cast(Any, db),
            cast(Any, credits),
            config,
        )
        coro = create_task.call_args.args[0]
        # Close the unscheduled coroutine so pytest doesn't warn.
        coro.close()
        create_task.assert_called_once()


async def test_non_dev_mode_does_not_schedule_auto_confirm(state: FSMContext) -> None:
    await state.set_state(ArticleStates.confirming_payment)
    await state.update_data(language="uz", user_id="u1", project_id="p1", tier="article_basic")
    msg = _make_message_spy()
    callback = _make_callback_spy(data="pay_payme", message=msg)
    db = MagicMock()
    db.get_pending_invoice = AsyncMock(return_value=None)
    db.create_invoice = AsyncMock(
        return_value={
            "id": "inv1",
            "invoice_number": "847291-1001",
            "amount_uzs": 60_000,
            "status": "pending",
        }
    )
    credits = MagicMock()
    config = _config(dev_mode=False)

    with patch("packages.bot.handlers.payment_flow.asyncio.create_task") as create_task:
        await select_provider(
            cast(Any, callback),
            state,
            cast(Any, MagicMock()),
            cast(Any, db),
            cast(Any, credits),
            config,
        )
        create_task.assert_not_called()


# ---------------------------------------------------------------------------
# Dev mode auto-confirm body
# ---------------------------------------------------------------------------


async def test_dev_mode_auto_confirm_processes_payment_and_triggers_article_flow(
    state: FSMContext,
) -> None:
    """The body of the auto-confirm task: credits the user and starts article gen."""

    await state.set_state(ArticleStates.confirming_payment)
    await state.update_data(language="uz", user_id="u1", project_id="p1", tier="article_basic")
    msg = _make_message_spy()
    invoice_service = MagicMock()
    invoice_service.process_payment = AsyncMock(return_value=None)
    credits = MagicMock()
    credits.deduct_for_generation = AsyncMock(return_value=None)
    db = MagicMock()
    bot = MagicMock()

    with (
        patch(
            "packages.bot.handlers.payment_flow.asyncio.sleep",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "packages.bot.handlers.payment_flow.article_flow.start_generation",
            new=AsyncMock(return_value=None),
        ) as article_start,
        patch(
            "packages.bot.handlers.payment_flow.presentation_flow.start_generation",
            new=AsyncMock(return_value=None),
        ) as presentation_start,
    ):
        await _dev_mode_auto_confirm(
            message=cast(Any, msg),
            state=state,
            invoice_service=cast(Any, invoice_service),
            invoice_number="847291-1001",
            provider="payme",
            amount_uzs=60_000,
            tier="article_basic",
            bot=cast(Any, bot),
            db=cast(Any, db),
            credits=cast(Any, credits),
        )

    invoice_service.process_payment.assert_awaited_once_with(
        invoice_number="847291-1001",
        payment_provider="payme",
        payment_reference="dev_auto_847291-1001",
        amount_uzs=60_000,
    )
    credits.deduct_for_generation.assert_awaited_once_with(
        user_id="u1", project_id="p1", product_type="article_basic"
    )
    msg.answer.assert_awaited()
    article_start.assert_awaited_once()
    presentation_start.assert_not_called()


async def test_dev_mode_auto_confirm_routes_presentation_tier_to_presentation_flow(
    state: FSMContext,
) -> None:
    await state.set_state(ArticleStates.confirming_payment)
    await state.update_data(
        language="uz", user_id="u1", project_id="p1", tier="presentation_premium"
    )
    msg = _make_message_spy()
    invoice_service = MagicMock()
    invoice_service.process_payment = AsyncMock(return_value=None)
    credits = MagicMock()
    credits.deduct_for_generation = AsyncMock(return_value=None)

    with (
        patch(
            "packages.bot.handlers.payment_flow.asyncio.sleep",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "packages.bot.handlers.payment_flow.article_flow.start_generation",
            new=AsyncMock(return_value=None),
        ) as article_start,
        patch(
            "packages.bot.handlers.payment_flow.presentation_flow.start_generation",
            new=AsyncMock(return_value=None),
        ) as presentation_start,
    ):
        await _dev_mode_auto_confirm(
            message=cast(Any, msg),
            state=state,
            invoice_service=cast(Any, invoice_service),
            invoice_number="847291-2002",
            provider="click",
            amount_uzs=15_000,
            tier="presentation_premium",
            bot=cast(Any, MagicMock()),
            db=cast(Any, MagicMock()),
            credits=cast(Any, credits),
        )

    presentation_start.assert_awaited_once()
    article_start.assert_not_called()


async def test_dev_mode_auto_confirm_aborts_when_process_payment_fails(
    state: FSMContext,
) -> None:
    """If the simulated webhook fails, no deduction or generation happens."""

    await state.set_state(ArticleStates.confirming_payment)
    await state.update_data(language="uz", user_id="u1", project_id="p1", tier="article_basic")
    msg = _make_message_spy()
    invoice_service = MagicMock()
    invoice_service.process_payment = AsyncMock(side_effect=ValueError("amount mismatch"))
    credits = MagicMock()
    credits.deduct_for_generation = AsyncMock(return_value=None)

    with (
        patch(
            "packages.bot.handlers.payment_flow.asyncio.sleep",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "packages.bot.handlers.payment_flow.article_flow.start_generation",
            new=AsyncMock(return_value=None),
        ) as article_start,
    ):
        await _dev_mode_auto_confirm(
            message=cast(Any, msg),
            state=state,
            invoice_service=cast(Any, invoice_service),
            invoice_number="847291-1001",
            provider="payme",
            amount_uzs=60_000,
            tier="article_basic",
            bot=cast(Any, MagicMock()),
            db=cast(Any, MagicMock()),
            credits=cast(Any, credits),
        )

    credits.deduct_for_generation.assert_not_called()
    article_start.assert_not_called()
