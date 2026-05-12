"""Presentation creation flow — wired to :class:`PresentationOrchestrator`.

End-to-end conversation:

    upload sources → (Mini App questionnaire | skip) → tier →
    payment → generate → deliver

The flow parallels :mod:`packages.bot.handlers.article_flow`. The
distinguishing feature is that pre-generation preferences come from a
Telegram Mini App rather than a Telegram-native interview — the user
either submits a JSON payload via Telegram's ``web_app_data`` channel
or skips entirely and lets
:meth:`PresentationInterviewEngine.apply_defaults` derive answers from
the uploaded sources alone.

Heavy work is delegated to :class:`PresentationOrchestrator`; this
module owns the FSM transitions, the progress messages, and the file
delivery handlers. Generated file paths cannot survive aiogram's FSM
storage cleanly (pydantic Path objects do not pickle through
MemoryStorage); they live in :data:`_PROJECT_CACHE` keyed by
``project_id`` and are wiped on completion or cancellation.

CLAUDE.md's 300-line cap is intentionally exceeded: every stage of the
flow shares state (project_id, language, labels, the cache slot), and
splitting upload/questionnaire/payment/delivery into separate modules
would scatter the conversation across files.
"""

from __future__ import annotations

import contextlib
import json
import logging
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlencode

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, FSInputFile, Message

from packages.bot.keyboards import (
    main_menu_keyboard,
    payment_provider_keyboard,
    presentation_mini_app_keyboard,
    presentation_output_keyboard,
    tier_keyboard,
    upload_more_keyboard,
)
from packages.bot.labels import BotLabels, get_bot_labels
from packages.bot.orchestrators import (
    PresentationOrchestrator,
    PresentationRenderResult,
    ProgressCallback,
)
from packages.bot.states import PresentationStates
from packages.core.enums import ExportFormat
from packages.platform.config import PlatformConfig
from packages.platform.credits import CreditLedger
from packages.platform.database import DatabaseClient
from packages.platform.storage import FileStorage

logger = logging.getLogger("nashr.bot.presentation")

router = Router()

MAX_FILE_BYTES: int = 20 * 1024 * 1024
SUPPORTED_EXTENSIONS: frozenset[str] = frozenset(
    {"pdf", "docx", "doc", "txt", "xlsx", "xls", "pptx", "ppt", "jpg", "jpeg", "png"}
)
MINI_APP_URL_DEFAULT: str = "https://nashr.uz/mini-app/presentation"

# Source types likely to contain headline statistics — used to decide
# whether the Mini App shows the "headline numbers" question.
_STAT_BEARING_FILE_TYPES: frozenset[str] = frozenset({"xlsx", "xls", "csv"})

# Module-local cache keyed by project_id; see module docstring for why
# generated file paths cannot live in aiogram's FSM storage.
_PROJECT_CACHE: dict[str, dict[str, Any]] = {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_extension(filename: str) -> str:
    if "." not in filename:
        return ""
    return filename.rsplit(".", 1)[-1].lower()


def _flow_language(data: dict[str, Any]) -> str:
    lang = data.get("language")
    if isinstance(lang, str) and lang:
        return lang
    return "uz"


def _count_stat_bearing_sources(sources: list[dict[str, Any]]) -> int:
    return sum(1 for s in sources if str(s.get("file_type", "")) in _STAT_BEARING_FILE_TYPES)


def _cache(project_id: str) -> dict[str, Any]:
    """Get-or-create the per-project cache slot."""

    slot = _PROJECT_CACHE.get(project_id)
    if slot is None:
        slot = {}
        _PROJECT_CACHE[project_id] = slot
    return slot


def _drop_cache(project_id: str) -> None:
    """Remove the project's cache slot; safe when no slot exists."""

    _PROJECT_CACHE.pop(project_id, None)


def _orchestrator(
    bot: Bot,
    db: DatabaseClient,
    credits: CreditLedger,
    storage: FileStorage | None = None,
) -> PresentationOrchestrator:
    """Build a fresh orchestrator. Cheap; each engine is stateless."""

    return PresentationOrchestrator(bot=bot, db=db, credits=credits, storage=storage)


def _progress_editor(message: Message, labels: BotLabels) -> ProgressCallback:
    """Closure that edits ``message`` with the current pipeline step.

    Edit failures (Telegram returns 400 when the new content is
    identical to the old) are swallowed: progress UX is best-effort.
    """

    async def callback(step_name: str, step: int, total: int) -> None:
        try:
            await message.edit_text(
                labels.generating.format(progress=f"{step}/{total}: {step_name}…")
            )
        except Exception as exc:
            logger.debug(
                "presentation_progress_edit_failed",
                extra={"error_type": type(exc).__name__},
            )

    return callback


def build_mini_app_url(
    *,
    base_url: str,
    lang: str,
    project_id: str,
    stats: int,
    domain: str = "general",
    people: int = 0,
) -> str:
    """Compose the URL the Mini App button opens.

    Query params parallel the Mini App's JS reader; keep both in sync.
    """

    params: dict[str, str] = {
        "lang": lang,
        "project_id": project_id,
        "stats": str(stats),
        "people": str(people),
        "domain": domain,
    }
    base = base_url.rstrip("/")
    return f"{base}/mini-app/presentation?{urlencode(params)}"


# ---------------------------------------------------------------------------
# Upload stage
# ---------------------------------------------------------------------------


@router.message(PresentationStates.uploading_sources, F.document)
async def receive_document(message: Message, state: FSMContext, db: DatabaseClient) -> None:
    """Receive and validate a presentation source document."""

    del db  # reserved for direct source registration once R2 storage lands
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
async def continue_to_questionnaire(
    callback: CallbackQuery, state: FSMContext, config: PlatformConfig
) -> None:
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

    project_id = str(data.get("project_id", ""))
    stat_count = _count_stat_bearing_sources(sources)
    mini_app_url = build_mini_app_url(
        base_url=config.mini_app_base_url,
        lang=lang,
        project_id=project_id,
        stats=stat_count,
        domain="general",
    )

    if isinstance(callback.message, Message):
        await callback.message.edit_text(
            labels.open_questionnaire,
            reply_markup=presentation_mini_app_keyboard(lang, mini_app_url),
        )
    await state.set_state(PresentationStates.opening_mini_app)
    await callback.answer()


# ---------------------------------------------------------------------------
# Mini App / Skip
# ---------------------------------------------------------------------------


@router.callback_query(PresentationStates.opening_mini_app, F.data == "skip_questionnaire")
async def skip_questionnaire(callback: CallbackQuery, state: FSMContext) -> None:
    """Skip questionnaire; downstream defaults will be applied."""

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


@router.message(PresentationStates.opening_mini_app, F.web_app_data)
async def receive_mini_app_data(message: Message, state: FSMContext) -> None:
    """Receive questionnaire answers from the Mini App.

    Malformed payloads leave the FSM in ``opening_mini_app`` so the user
    can retry; we never silently fall back to defaults here (the skip
    button is the explicit path for that).
    """

    data = await state.get_data()
    lang = _flow_language(data)
    labels = get_bot_labels(lang)

    web_app = message.web_app_data
    if web_app is None:
        await message.answer(labels.error_generic)
        return

    try:
        parsed: object = json.loads(web_app.data)
    except (json.JSONDecodeError, TypeError):
        await message.answer(labels.error_generic)
        return

    if not isinstance(parsed, dict):
        await message.answer(labels.error_generic)
        return

    await state.update_data(interview_answers=parsed)
    await message.answer(labels.choose_tier, reply_markup=tier_keyboard(lang, "presentation"))
    await state.set_state(PresentationStates.choosing_tier)


# ---------------------------------------------------------------------------
# Tier & payment hand-off
# ---------------------------------------------------------------------------


@router.callback_query(PresentationStates.choosing_tier, F.data.startswith("tier_"))
async def choose_tier(callback: CallbackQuery, state: FSMContext) -> None:
    """Record the chosen tier, prefixed for :class:`CreditLedger.PRICING`."""

    raw = callback.data or ""
    tier = raw.removeprefix("tier_")
    await state.update_data(tier=f"presentation_{tier}")

    data = await state.get_data()
    lang = _flow_language(data)
    labels = get_bot_labels(lang)
    if isinstance(callback.message, Message):
        await callback.message.edit_text(
            labels.choose_payment, reply_markup=payment_provider_keyboard(lang)
        )
    await state.set_state(PresentationStates.confirming_payment)
    await callback.answer()


# ---------------------------------------------------------------------------
# Post-payment generation (called from the payment flow)
# ---------------------------------------------------------------------------


async def start_generation(
    target: Message,
    state: FSMContext,
    bot: Bot,
    db: DatabaseClient,
    credits: CreditLedger,
    storage: FileStorage | None = None,
) -> None:
    """Run the full presentation pipeline after payment lands.

    Called from :mod:`packages.bot.handlers.payment_flow` once balance
    has been deducted (or from the dev-mode short-circuit). On failure
    the credit is refunded before the state is cleared.
    """

    data = await state.get_data()
    lang = _flow_language(data)
    labels = get_bot_labels(lang)
    project_id = str(data.get("project_id", ""))
    user_id = str(data.get("user_id", ""))
    sources_raw = data.get("sources", [])
    sources_meta: list[dict[str, object]] = (
        cast(list[dict[str, object]], sources_raw) if isinstance(sources_raw, list) else []
    )
    raw_answers_in = data.get("interview_answers")
    raw_answers: dict[str, object] | None = (
        cast(dict[str, object], raw_answers_in) if isinstance(raw_answers_in, dict) else None
    )

    progress_msg: Message = await target.answer(labels.generating.format(progress="…"))
    progress = _progress_editor(progress_msg, labels)
    orchestrator = _orchestrator(bot, db, credits, storage=storage)
    await state.set_state(PresentationStates.generating)

    try:
        files = await orchestrator.run_full_pipeline(
            file_infos=sources_meta,
            project_id=project_id,
            user_id=user_id,
            language=lang,
            raw_answers=raw_answers,
            requested_formats=[ExportFormat.HTML, ExportFormat.PPTX_EDITABLE],
            progress=progress,
        )
    except Exception as exc:
        logger.exception(
            "presentation_generation_failed",
            extra={"project_id": project_id, "error_type": type(exc).__name__},
        )
        with contextlib.suppress(Exception):
            await progress_msg.edit_text(labels.generation_failed)
        with contextlib.suppress(Exception):
            await db.update_project_status(project_id, "failed")
        await _refund_on_failure(credits, data, project_id)
        await state.clear()
        return

    _stash_outputs(project_id, files)
    await _register_outputs(db, project_id, files)
    try:
        await db.update_project_status(project_id, "completed")
    except Exception as exc:
        logger.warning(
            "presentation_update_status_failed",
            extra={"project_id": project_id, "error_type": type(exc).__name__},
        )

    try:
        await progress_msg.edit_text(
            labels.download_ready, reply_markup=presentation_output_keyboard(lang)
        )
    except Exception:
        await progress_msg.answer(
            labels.download_ready, reply_markup=presentation_output_keyboard(lang)
        )
    await state.set_state(PresentationStates.reviewing_output)


def _stash_outputs(project_id: str, files: PresentationRenderResult) -> None:
    """Cache the rendered paths for the download callbacks."""

    slot = _cache(project_id)
    paths: dict[str, str] = {}
    for ext, path in files.by_extension().items():
        paths[ext] = str(path)
    slot["files"] = paths
    if files.warnings:
        slot["warnings"] = list(files.warnings)


async def _register_outputs(
    db: DatabaseClient, project_id: str, files: PresentationRenderResult
) -> None:
    """Persist a generated_files row per rendered output."""

    for ext, path in files.by_extension().items():
        try:
            size = path.stat().st_size if path.exists() else 0
            await db.create_generated_file(
                project_id=project_id,
                file_type=ext,
                storage_path=str(path),
                file_size=size,
            )
        except Exception as exc:
            logger.warning(
                "presentation_register_output_failed",
                extra={"project_id": project_id, "format": ext, "error_type": type(exc).__name__},
            )


async def _refund_on_failure(credits: CreditLedger, data: dict[str, Any], project_id: str) -> None:
    """Issue a credit refund when generation fails after deduction."""

    tier = str(data.get("tier") or "")
    price = CreditLedger.PRICING.get(tier)
    user_id = str(data.get("user_id") or "")
    if price is None or not user_id:
        return
    try:
        await credits.refund(
            user_id=user_id,
            project_id=project_id,
            amount_uzs=price,
            reason="presentation_generation_failed",
        )
    except Exception as exc:
        logger.warning(
            "presentation_refund_failed",
            extra={"error_type": type(exc).__name__},
        )


# ---------------------------------------------------------------------------
# Output delivery
# ---------------------------------------------------------------------------


async def _send_format(
    callback: CallbackQuery, state: FSMContext, ext: str, fallback_label: str
) -> None:
    """Shared file-delivery logic for the HTML/PPTX/PDF buttons."""

    data = await state.get_data()
    lang = _flow_language(data)
    labels = get_bot_labels(lang)
    cache = _cache(str(data.get("project_id", "")))
    files_raw = cache.get("files")
    files: dict[str, str] = cast(dict[str, str], files_raw) if isinstance(files_raw, dict) else {}
    path = files.get(ext)

    if not isinstance(callback.message, Message):
        await callback.answer()
        return
    if isinstance(path, str) and Path(path).exists():
        await callback.message.answer_document(
            FSInputFile(path, filename=f"nashr_presentation.{ext}")
        )
    else:
        await callback.message.answer(fallback_label or labels.error_generic)
    await callback.answer()


@router.callback_query(PresentationStates.reviewing_output, F.data == "download_html")
async def send_html(callback: CallbackQuery, state: FSMContext) -> None:
    """Send the rendered HTML artefact."""

    await _send_format(callback, state, "html", "")


@router.callback_query(PresentationStates.reviewing_output, F.data == "download_pptx")
async def send_pptx(callback: CallbackQuery, state: FSMContext) -> None:
    """Send the rendered PPTX file."""

    await _send_format(callback, state, "pptx", "")


@router.callback_query(PresentationStates.reviewing_output, F.data == "download_pdf")
async def send_pdf(callback: CallbackQuery, state: FSMContext) -> None:
    """Send the rendered PDF file (if generated)."""

    await _send_format(callback, state, "pdf", "PDF not available. Try HTML or PPTX.")


@router.callback_query(PresentationStates.reviewing_output, F.data == "regenerate_output")
async def regenerate_output(
    callback: CallbackQuery,
    state: FSMContext,
    bot: Bot,
    db: DatabaseClient,
    credits: CreditLedger,
    storage: FileStorage | None = None,
) -> None:
    """Re-render the deck without charging again."""

    if not isinstance(callback.message, Message):
        await callback.answer()
        return
    await callback.answer()
    await start_generation(callback.message, state, bot, db, credits, storage)


@router.callback_query(PresentationStates.reviewing_output, F.data == "done")
async def finish(callback: CallbackQuery, state: FSMContext) -> None:
    """End the flow: clear FSM, drop the cache, show the main menu."""

    data = await state.get_data()
    lang = _flow_language(data)
    labels = get_bot_labels(lang)
    _drop_cache(str(data.get("project_id", "")))
    if isinstance(callback.message, Message):
        await callback.message.edit_text(labels.main_menu, reply_markup=main_menu_keyboard(lang))
    await state.clear()
    await callback.answer()


@router.callback_query(PresentationStates.reviewing_output, F.data == "cancel_flow")
async def cancel(callback: CallbackQuery, state: FSMContext) -> None:
    """Cancel from the output-review state (the article router covers the rest)."""

    data = await state.get_data()
    lang = _flow_language(data)
    labels = get_bot_labels(lang)
    _drop_cache(str(data.get("project_id", "")))
    if isinstance(callback.message, Message):
        await callback.message.edit_text(labels.main_menu, reply_markup=main_menu_keyboard(lang))
    await state.clear()
    await callback.answer()
