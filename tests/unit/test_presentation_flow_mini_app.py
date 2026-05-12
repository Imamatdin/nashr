"""Tests for the presentation flow's Mini App wiring.

Three handlers are exercised here:

1. :func:`continue_to_questionnaire` — builds the Mini App URL with
   query params drawn from FSM state and platform config.
2. :func:`receive_mini_app_data` — receives the ``sendData`` payload
   Telegram delivers when the user submits the questionnaire, parses
   it, and advances to tier selection.
3. :func:`skip_questionnaire` — short-circuits the Mini App and goes
   straight to tier selection with ``interview_answers=None``.

We also test the URL builder and the helper that serves the Mini App
HTML from the aiohttp webhook app.
"""

from __future__ import annotations

import json
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, Message, WebAppData

from packages.bot.handlers.presentation_flow import (
    build_mini_app_url,
    continue_to_questionnaire,
    receive_mini_app_data,
    skip_questionnaire,
)
from packages.bot.states import PresentationStates
from packages.platform.config import PlatformConfig


def _make_config(base_url: str = "https://nashr.uz") -> PlatformConfig:
    return PlatformConfig(
        supabase_url="",
        supabase_service_key="",
        telegram_bot_token="dummy",
        mini_app_base_url=base_url,
    )


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


@pytest.fixture
def state() -> FSMContext:
    storage = MemoryStorage()
    key = StorageKey(bot_id=1, user_id=11, chat_id=22)
    return FSMContext(storage=storage, key=key)


# ---------------------------------------------------------------------------
# build_mini_app_url
# ---------------------------------------------------------------------------


def test_build_mini_app_url_includes_all_required_params() -> None:
    url = build_mini_app_url(
        base_url="https://nashr.uz",
        lang="uz",
        project_id="proj_42",
        stats=3,
        domain="engineering",
        people=5,
    )
    assert url.startswith("https://nashr.uz/mini-app/presentation?")
    assert "lang=uz" in url
    assert "project_id=proj_42" in url
    assert "stats=3" in url
    assert "domain=engineering" in url
    assert "people=5" in url


def test_build_mini_app_url_handles_trailing_slash_base() -> None:
    url = build_mini_app_url(
        base_url="https://nashr.uz/",
        lang="ru",
        project_id="p1",
        stats=0,
    )
    assert "//mini-app" not in url
    assert url.startswith("https://nashr.uz/mini-app/presentation?")


def test_build_mini_app_url_escapes_special_chars_in_values() -> None:
    url = build_mini_app_url(
        base_url="https://x.test",
        lang="en",
        project_id="a b&c",
        stats=0,
    )
    # urlencode quotes spaces and ampersands so the URL parses correctly.
    assert "project_id=a+b%26c" in url


# ---------------------------------------------------------------------------
# continue_to_questionnaire
# ---------------------------------------------------------------------------


async def test_continue_to_questionnaire_blocks_when_no_sources(
    state: FSMContext,
) -> None:
    await state.set_state(PresentationStates.waiting_for_more_sources)
    await state.update_data(language="uz", sources=[], project_id="p1")
    msg = _make_message_spy()
    cb = _make_callback_spy(data="continue_flow", message=msg)

    await continue_to_questionnaire(cast(Any, cb), state, _make_config())

    msg.edit_text.assert_awaited_once()
    text = msg.edit_text.await_args.args[0]
    assert "manba" in text.lower() or "source" in text.lower()
    # Mini App keyboard must NOT have been attached.
    assert msg.edit_text.await_args.kwargs.get("reply_markup") is None
    assert (await state.get_state()) == PresentationStates.waiting_for_more_sources.state


async def test_continue_to_questionnaire_shows_mini_app_button_with_url(
    state: FSMContext,
) -> None:
    await state.set_state(PresentationStates.waiting_for_more_sources)
    await state.update_data(
        language="uz",
        project_id="proj_abc",
        sources=[{"file_type": "pdf"}, {"file_type": "xlsx"}],
    )
    msg = _make_message_spy()
    cb = _make_callback_spy(data="continue_flow", message=msg)

    await continue_to_questionnaire(cast(Any, cb), state, _make_config("https://test.example"))

    msg.edit_text.assert_awaited_once()
    markup = msg.edit_text.await_args.kwargs.get("reply_markup")
    assert markup is not None
    buttons = [btn for row in markup.inline_keyboard for btn in row]
    web_app_buttons = [b for b in buttons if b.web_app is not None]
    assert len(web_app_buttons) == 1
    url = web_app_buttons[0].web_app.url
    assert "https://test.example/mini-app/presentation?" in url
    assert "lang=uz" in url
    assert "project_id=proj_abc" in url
    # One xlsx source → stats=1.
    assert "stats=1" in url
    assert (await state.get_state()) == PresentationStates.opening_mini_app.state


async def test_continue_to_questionnaire_counts_no_stat_sources_as_zero(
    state: FSMContext,
) -> None:
    await state.set_state(PresentationStates.waiting_for_more_sources)
    await state.update_data(
        language="ru",
        project_id="p_text_only",
        sources=[{"file_type": "pdf"}, {"file_type": "docx"}],
    )
    msg = _make_message_spy()
    cb = _make_callback_spy(data="continue_flow", message=msg)

    await continue_to_questionnaire(cast(Any, cb), state, _make_config())

    markup = msg.edit_text.await_args.kwargs["reply_markup"]
    web_app_btn = next(
        btn for row in markup.inline_keyboard for btn in row if btn.web_app is not None
    )
    assert "stats=0" in web_app_btn.web_app.url
    assert "lang=ru" in web_app_btn.web_app.url


# ---------------------------------------------------------------------------
# receive_mini_app_data
# ---------------------------------------------------------------------------


def _make_web_app_message(payload: str) -> MagicMock:
    msg = _make_message_spy()
    msg.web_app_data = WebAppData(data=payload, button_text="open")
    return msg


async def test_receive_mini_app_data_stores_answers_and_advances(
    state: FSMContext,
) -> None:
    await state.set_state(PresentationStates.opening_mini_app)
    await state.update_data(language="uz")
    payload = json.dumps(
        {
            "project_id": "p1",
            "audience": "undergraduate",
            "talk_duration_minutes": 25,
            "narrative_emphasis": ["results_numbers"],
            "title_style": "takeaway",
            "include_interactive": "yes",
            "theme": "light",
            "speaker_notes": "brief_talking_points",
            "headline_numbers": "94.4% water saved",
            "closing_ask": "",
            "diagrams": "decide_for_me",
        }
    )
    msg = _make_web_app_message(payload)

    await receive_mini_app_data(cast(Any, msg), state)

    data = await state.get_data()
    answers = data.get("interview_answers")
    assert isinstance(answers, dict)
    assert answers["audience"] == "undergraduate"
    assert answers["talk_duration_minutes"] == 25
    assert answers["narrative_emphasis"] == ["results_numbers"]
    assert (await state.get_state()) == PresentationStates.choosing_tier.state
    msg.answer.assert_awaited_once()
    # Tier keyboard should be attached.
    assert msg.answer.await_args.kwargs.get("reply_markup") is not None


async def test_receive_mini_app_data_handles_invalid_json(state: FSMContext) -> None:
    await state.set_state(PresentationStates.opening_mini_app)
    await state.update_data(language="uz")
    msg = _make_web_app_message("not-valid-json{{{")

    await receive_mini_app_data(cast(Any, msg), state)

    data = await state.get_data()
    assert "interview_answers" not in data
    assert (await state.get_state()) == PresentationStates.opening_mini_app.state
    msg.answer.assert_awaited_once()


async def test_receive_mini_app_data_rejects_non_object_payload(state: FSMContext) -> None:
    await state.set_state(PresentationStates.opening_mini_app)
    await state.update_data(language="uz")
    msg = _make_web_app_message(json.dumps(["not", "a", "dict"]))

    await receive_mini_app_data(cast(Any, msg), state)

    data = await state.get_data()
    assert "interview_answers" not in data
    assert (await state.get_state()) == PresentationStates.opening_mini_app.state


# ---------------------------------------------------------------------------
# skip_questionnaire
# ---------------------------------------------------------------------------


async def test_skip_questionnaire_uses_defaults(state: FSMContext) -> None:
    await state.set_state(PresentationStates.opening_mini_app)
    await state.update_data(language="uz")
    msg = _make_message_spy()
    cb = _make_callback_spy(data="skip_questionnaire", message=msg)

    await skip_questionnaire(cast(Any, cb), state)

    data = await state.get_data()
    assert data.get("interview_answers") is None
    assert (await state.get_state()) == PresentationStates.choosing_tier.state
    msg.edit_text.assert_awaited_once()
    assert msg.edit_text.await_args.kwargs.get("reply_markup") is not None


# ---------------------------------------------------------------------------
# webhook app — serves the Mini App HTML
# ---------------------------------------------------------------------------


async def test_webhook_app_registers_payment_routes_when_dependencies_present() -> None:
    """``build_aiohttp_app`` mounts payment webhooks when db/credits/config are present."""

    from aiogram import Dispatcher
    from aiogram.fsm.storage.memory import MemoryStorage

    from packages.bot.app import build_aiohttp_app
    from packages.platform.config import PlatformConfig
    from packages.platform.credits import CreditLedger
    from packages.platform.database import DatabaseClient

    config = PlatformConfig(
        supabase_url="https://test.supabase.co",
        supabase_service_key="test-service-key",
        telegram_bot_token="test-token",
    )
    fake_supabase = MagicMock()
    fake_supabase.table = MagicMock()
    db = DatabaseClient(config, client=cast(Any, fake_supabase))
    credits = CreditLedger(db)

    bot = MagicMock()
    bot.session = MagicMock()
    bot.session.close = AsyncMock(return_value=None)
    dp = Dispatcher(storage=MemoryStorage())
    dp["db"] = db
    dp["credits"] = credits
    dp["config"] = config

    app = build_aiohttp_app(bot, dp)
    paths = {route.resource.canonical for route in app.router.routes() if route.resource}
    assert "/webhooks/payme" in paths
    assert "/webhooks/click" in paths
    assert "/webhooks/uzum" in paths
    assert any("/api/invoices/" in p for p in paths)


async def test_webhook_app_skips_payment_routes_when_dependencies_absent() -> None:
    """Without db/credits/config in the dispatcher, payment routes are not mounted."""

    from aiogram import Dispatcher
    from aiogram.fsm.storage.memory import MemoryStorage

    from packages.bot.app import build_aiohttp_app

    bot = MagicMock()
    bot.session = MagicMock()
    bot.session.close = AsyncMock(return_value=None)
    dp = Dispatcher(storage=MemoryStorage())

    app = build_aiohttp_app(bot, dp)
    paths = {route.resource.canonical for route in app.router.routes() if route.resource}
    assert "/webhooks/payme" not in paths


async def test_webhook_app_serves_mini_app_html() -> None:
    """The aiohttp app built by ``build_aiohttp_app`` serves the HTML.

    Uses a real :class:`aiogram.Dispatcher` so the webhook plumbing
    (startup hooks, middleware) initialises correctly; only the
    :class:`aiogram.Bot` is a spy because instantiating it requires a
    token.
    """

    from aiogram import Dispatcher
    from aiogram.fsm.storage.memory import MemoryStorage
    from aiohttp.test_utils import TestClient, TestServer

    from packages.bot.app import MINI_APP_HTML_PATH, build_aiohttp_app

    bot = MagicMock()
    bot.session = MagicMock()
    bot.session.close = AsyncMock(return_value=None)
    dp = Dispatcher(storage=MemoryStorage())

    app = build_aiohttp_app(bot, dp)

    async with TestClient(TestServer(app)) as client:
        resp = await client.get("/mini-app/presentation")
        assert resp.status == 200
        assert resp.content_type == "text/html"
        body = await resp.text()
        assert "<!DOCTYPE html>" in body
        assert "telegram-web-app.js" in body
        # The local file we just served should match what the test reads.
        assert body == MINI_APP_HTML_PATH.read_text(encoding="utf-8")
