"""Behaviour tests for :mod:`packages.bot.handlers.article_flow`.

We test handler logic by passing message / callback spies into the
async handlers directly. The spies use :class:`unittest.mock.MagicMock`
with ``spec=Message`` / ``spec=CallbackQuery`` so the handlers'
``isinstance`` type guards pass; method calls are tracked via
:class:`unittest.mock.AsyncMock` for assertions.

The FSM context is real: a :class:`MemoryStorage`-backed
:class:`FSMContext` is attached so state transitions and
``update_data`` calls are asserted against actual storage rather than
method spies.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, Document, Message, PhotoSize

from packages.bot.handlers import article_flow
from packages.bot.handlers.article_flow import (
    _PROJECT_CACHE,
    approve_outline,
    cancel,
    choose_tier,
    finish,
    receive_document,
    receive_photo,
    send_docx,
    upload_more,
)
from packages.bot.states import ArticleStates

# ---------------------------------------------------------------------------
# Spy helpers
# ---------------------------------------------------------------------------


def _make_message_spy() -> MagicMock:
    """Build a :class:`Message` spy with async method tracking."""

    msg = MagicMock(spec=Message)
    msg.answer = AsyncMock(return_value=msg)
    msg.edit_text = AsyncMock(return_value=msg)
    msg.answer_document = AsyncMock(return_value=msg)
    return msg


def _make_callback_spy(*, data: str, message: MagicMock) -> MagicMock:
    cb = MagicMock(spec=CallbackQuery)
    cb.data = data
    cb.message = message
    cb.answer = AsyncMock(return_value=True)
    return cb


def _make_doc(
    *, file_id: str = "f1", file_name: str = "paper.pdf", file_size: int | None = 1234
) -> MagicMock:
    doc = MagicMock(spec=Document)
    doc.file_id = file_id
    doc.file_name = file_name
    doc.file_size = file_size
    return doc


def _make_photo(*, file_id: str, file_unique_id: str, file_size: int = 500) -> MagicMock:
    photo = MagicMock(spec=PhotoSize)
    photo.file_id = file_id
    photo.file_unique_id = file_unique_id
    photo.file_size = file_size
    return photo


@pytest.fixture
def state() -> FSMContext:
    storage = MemoryStorage()
    key = StorageKey(bot_id=1, user_id=11, chat_id=22)
    return FSMContext(storage=storage, key=key)


@pytest.fixture(autouse=True)
def _clear_project_cache():
    _PROJECT_CACHE.clear()
    yield
    _PROJECT_CACHE.clear()


# ---------------------------------------------------------------------------
# receive_document
# ---------------------------------------------------------------------------


async def test_receive_document_tracks_source_and_sets_state(state: FSMContext) -> None:
    await state.set_state(ArticleStates.uploading_sources)
    await state.update_data(language="uz", sources=[])
    msg = _make_message_spy()
    msg.document = _make_doc(file_name="paper.pdf", file_size=200)

    await receive_document(cast(Any, msg), state)

    data = await state.get_data()
    assert len(data["sources"]) == 1
    assert data["sources"][0]["file_id"] == "f1"
    assert data["sources"][0]["filename"] == "paper.pdf"
    assert data["sources"][0]["file_type"] == "pdf"
    assert (await state.get_state()) == ArticleStates.waiting_for_more_sources.state
    msg.answer.assert_awaited()


async def test_receive_document_rejects_oversized_file(state: FSMContext) -> None:
    await state.set_state(ArticleStates.uploading_sources)
    await state.update_data(language="uz", sources=[])
    msg = _make_message_spy()
    msg.document = _make_doc(file_size=article_flow.MAX_FILE_BYTES + 1)

    await receive_document(cast(Any, msg), state)

    msg.answer.assert_awaited_once()
    sent_text = msg.answer.await_args.args[0]
    assert "20" in sent_text or "MB" in sent_text
    data = await state.get_data()
    assert data.get("sources", []) == []


async def test_receive_document_rejects_unsupported_extension(state: FSMContext) -> None:
    await state.set_state(ArticleStates.uploading_sources)
    await state.update_data(language="uz", sources=[])
    msg = _make_message_spy()
    msg.document = _make_doc(file_name="malware.exe", file_size=200)

    await receive_document(cast(Any, msg), state)

    msg.answer.assert_awaited_once()
    sent_text = msg.answer.await_args.args[0]
    assert "format" in sent_text.lower() or "qo'llab" in sent_text
    data = await state.get_data()
    assert data.get("sources", []) == []


# ---------------------------------------------------------------------------
# receive_photo
# ---------------------------------------------------------------------------


async def test_receive_photo_tracks_largest_size(state: FSMContext) -> None:
    await state.set_state(ArticleStates.uploading_sources)
    await state.update_data(language="uz", sources=[])
    small = _make_photo(file_id="small", file_unique_id="u_small", file_size=100)
    large = _make_photo(file_id="large", file_unique_id="u_large", file_size=900)
    msg = _make_message_spy()
    msg.photo = [small, large]

    await receive_photo(cast(Any, msg), state)

    data = await state.get_data()
    assert len(data["sources"]) == 1
    assert data["sources"][0]["file_id"] == "large"
    assert data["sources"][0]["file_type"] == "jpg"


# ---------------------------------------------------------------------------
# continue_to_processing — empty sources
# ---------------------------------------------------------------------------


async def test_continue_with_no_sources_shows_error(state: FSMContext) -> None:
    await state.set_state(ArticleStates.waiting_for_more_sources)
    await state.update_data(language="uz", sources=[], project_id="p1", user_id="u1")
    msg = _make_message_spy()
    callback = _make_callback_spy(data="continue_flow", message=msg)

    await article_flow.continue_to_processing(
        cast(Any, callback),
        state,
        cast(Any, object()),
        cast(Any, object()),
        cast(Any, object()),
    )

    msg.edit_text.assert_awaited()
    edited_text = msg.edit_text.await_args.args[0]
    assert "manba" in edited_text.lower() or "source" in edited_text.lower()


# ---------------------------------------------------------------------------
# upload_more
# ---------------------------------------------------------------------------


async def test_upload_more_returns_to_uploading_state(state: FSMContext) -> None:
    await state.set_state(ArticleStates.waiting_for_more_sources)
    await state.update_data(language="uz")
    msg = _make_message_spy()
    callback = _make_callback_spy(data="upload_more", message=msg)

    await upload_more(cast(Any, callback), state)

    assert (await state.get_state()) == ArticleStates.uploading_sources.state
    msg.edit_text.assert_awaited()
    callback.answer.assert_awaited_once()


# ---------------------------------------------------------------------------
# approve_outline / regenerate_outline / choose_tier
# ---------------------------------------------------------------------------


async def test_approve_outline_moves_to_choosing_tier(state: FSMContext) -> None:
    await state.set_state(ArticleStates.reviewing_outline)
    await state.update_data(language="uz")
    msg = _make_message_spy()
    callback = _make_callback_spy(data="approve_outline", message=msg)

    await approve_outline(cast(Any, callback), state)

    assert (await state.get_state()) == ArticleStates.choosing_tier.state
    msg.edit_text.assert_awaited_once()
    assert msg.edit_text.await_args.kwargs.get("reply_markup") is not None


async def test_choose_tier_stores_tier_and_advances(state: FSMContext) -> None:
    await state.set_state(ArticleStates.choosing_tier)
    await state.update_data(language="uz")
    msg = _make_message_spy()
    callback = _make_callback_spy(data="tier_standard", message=msg)

    await choose_tier(cast(Any, callback), state)

    data = await state.get_data()
    assert data["tier"] == "article_standard"
    assert (await state.get_state()) == ArticleStates.confirming_payment.state
    msg.edit_text.assert_awaited_once()
    assert msg.edit_text.await_args.kwargs.get("reply_markup") is not None


# ---------------------------------------------------------------------------
# send_docx — file delivery
# ---------------------------------------------------------------------------


async def test_send_docx_sends_file_when_path_exists(state: FSMContext, tmp_path: Path) -> None:
    await state.set_state(ArticleStates.reviewing_output)
    await state.update_data(language="uz", project_id="proj_x")
    docx_path = tmp_path / "out.docx"
    docx_path.write_bytes(b"PK\x03\x04docx-bytes")
    _PROJECT_CACHE["proj_x"] = {"docx_path": str(docx_path)}

    msg = _make_message_spy()
    callback = _make_callback_spy(data="download_docx", message=msg)

    await send_docx(cast(Any, callback), state)

    msg.answer_document.assert_awaited_once()
    sent = msg.answer_document.await_args.args[0]
    assert getattr(sent, "filename", None) == "nashr_article.docx"


async def test_send_docx_reports_error_when_path_missing(state: FSMContext) -> None:
    await state.set_state(ArticleStates.reviewing_output)
    await state.update_data(language="uz", project_id="proj_missing")
    _PROJECT_CACHE["proj_missing"] = {"docx_path": "/nonexistent/path/x.docx"}

    msg = _make_message_spy()
    callback = _make_callback_spy(data="download_docx", message=msg)

    await send_docx(cast(Any, callback), state)

    msg.answer_document.assert_not_awaited()
    msg.answer.assert_awaited()


# ---------------------------------------------------------------------------
# finish / cancel — cleanup
# ---------------------------------------------------------------------------


async def test_finish_clears_state_and_cache(state: FSMContext) -> None:
    await state.set_state(ArticleStates.reviewing_output)
    await state.update_data(language="uz", project_id="proj_done")
    _PROJECT_CACHE["proj_done"] = {"docx_path": "x"}
    msg = _make_message_spy()
    callback = _make_callback_spy(data="done", message=msg)

    await finish(cast(Any, callback), state)

    assert (await state.get_state()) is None
    assert "proj_done" not in _PROJECT_CACHE
    msg.edit_text.assert_awaited()


async def test_cancel_clears_state_and_cache(state: FSMContext) -> None:
    await state.set_state(ArticleStates.choosing_tier)
    await state.update_data(language="uz", project_id="proj_cancel")
    _PROJECT_CACHE["proj_cancel"] = {"matrix": "stale"}
    msg = _make_message_spy()
    callback = _make_callback_spy(data="cancel_flow", message=msg)

    await cancel(cast(Any, callback), state)

    assert (await state.get_state()) is None
    assert "proj_cancel" not in _PROJECT_CACHE
