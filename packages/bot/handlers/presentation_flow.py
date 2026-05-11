"""Presentation creation flow: upload → Mini App → tier → payment.

Differs from the article flow in that research collection is a Mini
App questionnaire rather than a Telegram-native interview. A 'skip'
button hands off to :class:`PresentationInterviewEngine.apply_defaults`
which produces sensible defaults from the uploaded sources alone.
"""

from __future__ import annotations

from typing import Any

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from packages.bot.keyboards import (
    presentation_mini_app_keyboard,
    tier_keyboard,
    upload_more_keyboard,
)
from packages.bot.labels import get_bot_labels
from packages.bot.states import PresentationStates
from packages.platform.database import DatabaseClient

router = Router()

MAX_FILE_BYTES: int = 20 * 1024 * 1024
SUPPORTED_EXTENSIONS: frozenset[str] = frozenset(
    {"pdf", "docx", "doc", "txt", "xlsx", "xls", "pptx", "ppt", "jpg", "jpeg", "png"}
)
MINI_APP_URL_DEFAULT: str = "https://nashr.uz/mini-app/presentation"


def _extract_extension(filename: str) -> str:
    if "." not in filename:
        return ""
    return filename.rsplit(".", 1)[-1].lower()


def _flow_language(data: dict[str, Any]) -> str:
    lang = data.get("language")
    if isinstance(lang, str) and lang:
        return lang
    return "uz"


@router.message(PresentationStates.uploading_sources, F.document)
async def receive_document(message: Message, state: FSMContext, db: DatabaseClient) -> None:
    """Receive and validate a presentation source document."""

    doc = message.document
    if doc is None:
        return
    data = await state.get_data()
    lang = _flow_language(data)
    labels = get_bot_labels(lang)

    if doc.file_size is not None and doc.file_size > MAX_FILE_BYTES:
        await message.answer(labels.error_file_too_large)
        return

    filename = doc.file_name or "unknown"
    ext = _extract_extension(filename)
    if ext not in SUPPORTED_EXTENSIONS:
        await message.answer(labels.error_unsupported_format)
        return

    sources = list(data.get("sources", []))
    sources.append(
        {
            "file_id": doc.file_id,
            "filename": filename,
            "file_size": doc.file_size,
            "file_type": ext,
        }
    )
    await state.update_data(sources=sources)

    await message.answer(labels.upload_received, reply_markup=upload_more_keyboard(lang))
    await state.set_state(PresentationStates.waiting_for_more_sources)


@router.message(PresentationStates.uploading_sources, F.photo)
async def receive_photo(message: Message, state: FSMContext) -> None:
    """Photo sources for presentations: keep largest resolution."""

    if not message.photo:
        return
    photo = message.photo[-1]
    data = await state.get_data()
    lang = _flow_language(data)
    labels = get_bot_labels(lang)

    sources = list(data.get("sources", []))
    sources.append(
        {
            "file_id": photo.file_id,
            "filename": f"photo_{photo.file_unique_id}.jpg",
            "file_size": photo.file_size,
            "file_type": "jpg",
        }
    )
    await state.update_data(sources=sources)

    await message.answer(labels.upload_received, reply_markup=upload_more_keyboard(lang))
    await state.set_state(PresentationStates.waiting_for_more_sources)


@router.callback_query(PresentationStates.waiting_for_more_sources, F.data == "upload_more")
async def upload_more(callback: CallbackQuery, state: FSMContext) -> None:
    """Re-enter upload stage."""

    data = await state.get_data()
    lang = _flow_language(data)
    labels = get_bot_labels(lang)
    if isinstance(callback.message, Message):
        await callback.message.edit_text(labels.upload_prompt)
    await state.set_state(PresentationStates.uploading_sources)
    await callback.answer()


@router.callback_query(PresentationStates.waiting_for_more_sources, F.data == "continue_flow")
async def continue_to_questionnaire(callback: CallbackQuery, state: FSMContext) -> None:
    """Show the Mini App opener (or refuse if no sources)."""

    data = await state.get_data()
    lang = _flow_language(data)
    labels = get_bot_labels(lang)
    sources = list(data.get("sources", []))

    if not sources:
        if isinstance(callback.message, Message):
            await callback.message.edit_text(labels.error_no_sources)
        await callback.answer()
        return

    if isinstance(callback.message, Message):
        await callback.message.edit_text(
            labels.open_questionnaire,
            reply_markup=presentation_mini_app_keyboard(lang, MINI_APP_URL_DEFAULT),
        )
    await state.set_state(PresentationStates.opening_mini_app)
    await callback.answer()


@router.callback_query(PresentationStates.opening_mini_app, F.data == "skip_questionnaire")
async def skip_questionnaire(callback: CallbackQuery, state: FSMContext) -> None:
    """Skip the questionnaire; downstream code will fall back to defaults.

    Setting ``interview_answers`` to ``None`` signals
    ``PresentationInterviewEngine.apply_defaults`` should be used.
    """

    data = await state.get_data()
    lang = _flow_language(data)
    labels = get_bot_labels(lang)

    await state.update_data(interview_answers=None)

    if isinstance(callback.message, Message):
        await callback.message.edit_text(
            labels.choose_tier, reply_markup=tier_keyboard(lang, "presentation")
        )
    await state.set_state(PresentationStates.choosing_tier)
    await callback.answer()


@router.callback_query(PresentationStates.choosing_tier, F.data.startswith("tier_"))
async def choose_tier(callback: CallbackQuery, state: FSMContext) -> None:
    """Record tier; hand off to the payment flow (Task 31)."""

    raw = callback.data or ""
    tier = raw.removeprefix("tier_")
    await state.update_data(tier=tier)

    if isinstance(callback.message, Message):
        await callback.message.edit_text(f"Selected: {tier}. Payment flow wired in Task 31.")
    await state.set_state(PresentationStates.confirming_payment)
    await callback.answer()
