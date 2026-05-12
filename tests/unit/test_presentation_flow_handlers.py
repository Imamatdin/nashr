"""Behaviour tests for :mod:`packages.bot.handlers.presentation_flow`.

Exercises the handlers that landed in Task 29: tier selection (with
the ``presentation_`` prefix the credit ledger expects), file delivery
from the per-project cache, the regenerate shortcut, and the cancel /
finish cleanup. Mini-App URL / payload parsing is covered separately
by ``test_presentation_flow_mini_app.py`` — we don't repeat that here.

The orchestrator is replaced with a fake at the
:func:`packages.bot.handlers.presentation_flow._orchestrator` seam so
no Telegram, LLM or subprocess calls happen.
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

from packages.bot.handlers import presentation_flow
from packages.bot.handlers.presentation_flow import (
    _PROJECT_CACHE,
    cancel,
    choose_tier,
    finish,
    receive_document,
    receive_photo,
    send_html,
    send_pdf,
    send_pptx,
    start_generation,
    upload_more,
)
from packages.bot.orchestrators.presentation_orchestrator import PresentationRenderResult
from packages.bot.states import PresentationStates

# ---------------------------------------------------------------------------
# Spy helpers
# ---------------------------------------------------------------------------


def _make_message_spy() -> MagicMock:
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
    *, file_id: str = "f1", file_name: str = "deck.pdf", file_size: int | None = 1234
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
# Upload handlers
# ---------------------------------------------------------------------------


async def test_receive_document_tracks_source_and_sets_state(state: FSMContext) -> None:
    await state.set_state(PresentationStates.uploading_sources)
    await state.update_data(language="uz", sources=[])
    msg = _make_message_spy()
    msg.document = _make_doc(file_name="deck.pdf", file_size=200)

    db_spy = MagicMock()
    await receive_document(cast(Any, msg), state, cast(Any, db_spy))

    data = await state.get_data()
    assert len(data["sources"]) == 1
    assert data["sources"][0]["file_id"] == "f1"
    assert data["sources"][0]["file_type"] == "pdf"
    assert (await state.get_state()) == PresentationStates.waiting_for_more_sources.state


async def test_receive_document_rejects_oversized_file(state: FSMContext) -> None:
    await state.set_state(PresentationStates.uploading_sources)
    await state.update_data(language="uz", sources=[])
    msg = _make_message_spy()
    msg.document = _make_doc(file_size=presentation_flow.MAX_FILE_BYTES + 1)

    await receive_document(cast(Any, msg), state, cast(Any, MagicMock()))

    data = await state.get_data()
    assert data.get("sources", []) == []


async def test_receive_photo_uses_largest_resolution(state: FSMContext) -> None:
    await state.set_state(PresentationStates.uploading_sources)
    await state.update_data(language="uz", sources=[])
    small = _make_photo(file_id="small", file_unique_id="us", file_size=100)
    large = _make_photo(file_id="large", file_unique_id="ul", file_size=900)
    msg = _make_message_spy()
    msg.photo = [small, large]

    await receive_photo(cast(Any, msg), state)

    data = await state.get_data()
    assert len(data["sources"]) == 1
    assert data["sources"][0]["file_id"] == "large"


async def test_upload_more_returns_to_uploading_state(state: FSMContext) -> None:
    await state.set_state(PresentationStates.waiting_for_more_sources)
    await state.update_data(language="uz")
    msg = _make_message_spy()
    cb = _make_callback_spy(data="upload_more", message=msg)

    await upload_more(cast(Any, cb), state)

    assert (await state.get_state()) == PresentationStates.uploading_sources.state


# ---------------------------------------------------------------------------
# choose_tier — must prefix with "presentation_"
# ---------------------------------------------------------------------------


async def test_choose_tier_stores_presentation_prefixed_tier(state: FSMContext) -> None:
    await state.set_state(PresentationStates.choosing_tier)
    await state.update_data(language="uz")
    msg = _make_message_spy()
    cb = _make_callback_spy(data="tier_standard", message=msg)

    await choose_tier(cast(Any, cb), state)

    data = await state.get_data()
    assert data["tier"] == "presentation_standard"
    assert (await state.get_state()) == PresentationStates.confirming_payment.state
    assert msg.edit_text.await_args.kwargs.get("reply_markup") is not None


async def test_choose_tier_basic_and_premium(state: FSMContext) -> None:
    await state.set_state(PresentationStates.choosing_tier)
    await state.update_data(language="uz")
    msg = _make_message_spy()

    cb_basic = _make_callback_spy(data="tier_basic", message=msg)
    await choose_tier(cast(Any, cb_basic), state)
    assert (await state.get_data())["tier"] == "presentation_basic"

    await state.set_state(PresentationStates.choosing_tier)
    cb_prem = _make_callback_spy(data="tier_premium", message=msg)
    await choose_tier(cast(Any, cb_prem), state)
    assert (await state.get_data())["tier"] == "presentation_premium"


# ---------------------------------------------------------------------------
# start_generation — happy path
# ---------------------------------------------------------------------------


class _FakeOrchestrator:
    """Records calls and returns canned render results."""

    def __init__(self, files: PresentationRenderResult, raises: Exception | None = None) -> None:
        self._files = files
        self._raises = raises
        self.run_calls: list[dict[str, Any]] = []

    async def run_full_pipeline(self, **kwargs: Any) -> PresentationRenderResult:
        self.run_calls.append(kwargs)
        if self._raises is not None:
            raise self._raises
        return self._files


async def test_start_generation_caches_outputs_and_advances_state(
    state: FSMContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    await state.set_state(PresentationStates.confirming_payment)
    await state.update_data(
        language="uz",
        project_id="proj_x",
        user_id="user_x",
        sources=[{"file_id": "f1", "filename": "a.pdf", "file_type": "pdf"}],
        tier="presentation_basic",
        interview_answers=None,
    )

    html = tmp_path / "deck.html"
    html.write_bytes(b"html")
    pptx = tmp_path / "deck.pptx"
    pptx.write_bytes(b"pptx")
    fake = _FakeOrchestrator(PresentationRenderResult(html_path=html, pptx_path=pptx))

    def _factory(_bot: Any, _db: Any, _credits: Any) -> Any:
        return fake

    monkeypatch.setattr(presentation_flow, "_orchestrator", _factory)

    db_spy = MagicMock()
    db_spy.create_generated_file = AsyncMock()
    db_spy.update_project_status = AsyncMock()
    credits_spy = MagicMock()

    target = _make_message_spy()
    await start_generation(
        cast(Any, target),
        state,
        cast(Any, MagicMock()),
        cast(Any, db_spy),
        cast(Any, credits_spy),
    )

    assert (await state.get_state()) == PresentationStates.reviewing_output.state
    cache = _PROJECT_CACHE.get("proj_x") or {}
    assert cache["files"]["html"] == str(html)
    assert cache["files"]["pptx"] == str(pptx)
    # Two generated_files rows: html + pptx.
    assert db_spy.create_generated_file.await_count == 2
    db_spy.update_project_status.assert_awaited_with("proj_x", "completed")


async def test_start_generation_refunds_on_failure(
    state: FSMContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    await state.set_state(PresentationStates.confirming_payment)
    await state.update_data(
        language="uz",
        project_id="proj_fail",
        user_id="user_x",
        sources=[{"file_id": "f1", "filename": "a.pdf", "file_type": "pdf"}],
        tier="presentation_basic",
    )

    fake = _FakeOrchestrator(PresentationRenderResult(), raises=RuntimeError("LLM down"))

    def _factory(_bot: Any, _db: Any, _credits: Any) -> Any:
        return fake

    monkeypatch.setattr(presentation_flow, "_orchestrator", _factory)

    db_spy = MagicMock()
    db_spy.update_project_status = AsyncMock()
    credits_spy = MagicMock()
    credits_spy.refund = AsyncMock()

    target = _make_message_spy()
    await start_generation(
        cast(Any, target),
        state,
        cast(Any, MagicMock()),
        cast(Any, db_spy),
        cast(Any, credits_spy),
    )

    db_spy.update_project_status.assert_awaited_with("proj_fail", "failed")
    credits_spy.refund.assert_awaited_once()
    call_kwargs = credits_spy.refund.await_args.kwargs
    assert call_kwargs["amount_uzs"] == 5_000  # presentation_basic price
    assert (await state.get_state()) is None


# ---------------------------------------------------------------------------
# File delivery — HTML / PPTX / PDF
# ---------------------------------------------------------------------------


async def test_send_html_delivers_cached_file(state: FSMContext, tmp_path: Path) -> None:
    await state.set_state(PresentationStates.reviewing_output)
    await state.update_data(language="uz", project_id="proj_html")
    html = tmp_path / "deck.html"
    html.write_bytes(b"<html>")
    _PROJECT_CACHE["proj_html"] = {"files": {"html": str(html)}}

    msg = _make_message_spy()
    cb = _make_callback_spy(data="download_html", message=msg)
    await send_html(cast(Any, cb), state)

    msg.answer_document.assert_awaited_once()
    sent = msg.answer_document.await_args.args[0]
    assert getattr(sent, "filename", "") == "nashr_presentation.html"


async def test_send_pptx_delivers_cached_file(state: FSMContext, tmp_path: Path) -> None:
    await state.set_state(PresentationStates.reviewing_output)
    await state.update_data(language="uz", project_id="proj_pptx")
    pptx = tmp_path / "deck.pptx"
    pptx.write_bytes(b"PK\x03\x04")
    _PROJECT_CACHE["proj_pptx"] = {"files": {"pptx": str(pptx)}}

    msg = _make_message_spy()
    cb = _make_callback_spy(data="download_pptx", message=msg)
    await send_pptx(cast(Any, cb), state)

    msg.answer_document.assert_awaited_once()


async def test_send_pdf_warns_when_missing(state: FSMContext) -> None:
    await state.set_state(PresentationStates.reviewing_output)
    await state.update_data(language="uz", project_id="proj_no_pdf")
    _PROJECT_CACHE["proj_no_pdf"] = {"files": {"html": "/tmp/x.html"}}

    msg = _make_message_spy()
    cb = _make_callback_spy(data="download_pdf", message=msg)
    await send_pdf(cast(Any, cb), state)

    msg.answer_document.assert_not_awaited()
    msg.answer.assert_awaited_once()


# ---------------------------------------------------------------------------
# finish / cancel — cleanup
# ---------------------------------------------------------------------------


async def test_finish_clears_state_and_cache(state: FSMContext) -> None:
    await state.set_state(PresentationStates.reviewing_output)
    await state.update_data(language="uz", project_id="proj_done")
    _PROJECT_CACHE["proj_done"] = {"files": {"html": "/x.html"}}

    msg = _make_message_spy()
    cb = _make_callback_spy(data="done", message=msg)
    await finish(cast(Any, cb), state)

    assert (await state.get_state()) is None
    assert "proj_done" not in _PROJECT_CACHE


async def test_cancel_clears_state_and_cache(state: FSMContext) -> None:
    await state.set_state(PresentationStates.reviewing_output)
    await state.update_data(language="uz", project_id="proj_canc")
    _PROJECT_CACHE["proj_canc"] = {"files": {"html": "/x.html"}}

    msg = _make_message_spy()
    cb = _make_callback_spy(data="cancel_flow", message=msg)
    await cancel(cast(Any, cb), state)

    assert (await state.get_state()) is None
    assert "proj_canc" not in _PROJECT_CACHE
