"""Article creation flow: upload → interview → outline → tier → payment.

Scaffold only. The state machine and validation rules are real (file
size cap, allowed extensions, FSM transitions) so the bot can already
walk a user from the menu all the way to the tier picker; the
generation calls (interview engine, outline generator, drafter, file
storage) land in Task 27, and payment activation lands in Task 31.
"""

from __future__ import annotations

from typing import Any

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from packages.bot.keyboards import tier_keyboard, upload_more_keyboard
from packages.bot.labels import get_bot_labels
from packages.bot.states import ArticleStates
from packages.platform.database import DatabaseClient

router = Router()

MAX_FILE_BYTES: int = 20 * 1024 * 1024
SUPPORTED_EXTENSIONS: frozenset[str] = frozenset(
    {"pdf", "docx", "doc", "txt", "xlsx", "xls", "pptx", "ppt", "jpg", "jpeg", "png"}
)


def _extract_extension(filename: str) -> str:
    """Lowercase extension, or empty string if the name has no dot."""

    if "." not in filename:
        return ""
    return filename.rsplit(".", 1)[-1].lower()


def _flow_language(data: dict[str, Any]) -> str:
    lang = data.get("language")
    if isinstance(lang, str) and lang:
        return lang
    return "uz"


@router.message(ArticleStates.uploading_sources, F.document)
async def receive_document(message: Message, state: FSMContext, db: DatabaseClient) -> None:
    """Validate and stash a document source. Real storage lands in Task 27."""

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
    await state.set_state(ArticleStates.waiting_for_more_sources)


@router.message(ArticleStates.uploading_sources, F.photo)
async def receive_photo(message: Message, state: FSMContext) -> None:
    """Photos arrive as a list of resolutions; we keep the largest."""

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
    await state.set_state(ArticleStates.waiting_for_more_sources)


@router.callback_query(ArticleStates.waiting_for_more_sources, F.data == "upload_more")
async def upload_more(callback: CallbackQuery, state: FSMContext) -> None:
    """Return to the upload stage so the user can attach another file."""

    data = await state.get_data()
    lang = _flow_language(data)
    labels = get_bot_labels(lang)
    if isinstance(callback.message, Message):
        await callback.message.edit_text(labels.upload_prompt)
    await state.set_state(ArticleStates.uploading_sources)
    await callback.answer()


@router.callback_query(ArticleStates.waiting_for_more_sources, F.data == "continue_flow")
async def continue_to_interview(callback: CallbackQuery, state: FSMContext) -> None:
    """Move from upload stage into the research interview.

    Refuses to advance with zero sources — Nashr requires uploaded
    evidence, not just a user-typed topic.
    """

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
            f"{labels.interview_start}\n\n"
            f"(Interview engine will be wired in Task 27. "
            f"{len(sources)} source(s) received.)"
        )
    await state.set_state(ArticleStates.answering_interview)
    await callback.answer()


@router.callback_query(F.data == "approve_outline")
async def approve_outline(callback: CallbackQuery, state: FSMContext) -> None:
    """User approved the outline; advance to tier selection."""

    data = await state.get_data()
    lang = _flow_language(data)
    labels = get_bot_labels(lang)

    if isinstance(callback.message, Message):
        await callback.message.edit_text(
            labels.choose_tier, reply_markup=tier_keyboard(lang, "article")
        )
    await state.set_state(ArticleStates.choosing_tier)
    await callback.answer()


@router.callback_query(ArticleStates.choosing_tier, F.data.startswith("tier_"))
async def choose_tier(callback: CallbackQuery, state: FSMContext) -> None:
    """Record the chosen tier and hand off to the payment flow (Task 31)."""

    raw = callback.data or ""
    tier = raw.removeprefix("tier_")
    await state.update_data(tier=tier)

    if isinstance(callback.message, Message):
        await callback.message.edit_text(
            f"Selected: {tier}. Payment flow will be wired in Task 31."
        )
    await state.set_state(ArticleStates.confirming_payment)
    await callback.answer()
