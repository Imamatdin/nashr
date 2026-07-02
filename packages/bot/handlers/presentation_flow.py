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

import asyncio
import contextlib
import json
import logging
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlencode

from aiogram import Bot, F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, FSInputFile, Message

from packages.bot.keyboards import (
    main_menu_keyboard,
    payment_provider_keyboard,
    presentation_approval_keyboard,
    presentation_chat_keyboard,
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
    SourceProcessingResult,
)
from packages.bot.orchestrators.article_orchestrator import _OrchestratorError
from packages.bot.sessions import (
    ApprovalState,
    BrainDriver,
    BrainSession,
    GeminiBrainDriver,
    PendingAction,
    create_session,
    hydrate_figures,
    load_session,
    persist_session,
    requires_approval,
)
from packages.bot.sessions.budget import has_fixes_remaining, session_fix_limit
from packages.bot.states import PresentationStates
from packages.core.brain_loop import EDIT_SLIDES_TOOL_NAME
from packages.core.enums import ExportFormat, GenerationPackage
from packages.core.gemini import GeminiClient
from packages.core.gemini_tools import FunctionResult, build_function_responses_content
from packages.core.models.presentation import DeckSpec, SlideFix
from packages.platform.config import PlatformConfig
from packages.platform.credits import CreditLedger
from packages.platform.database import DatabaseClient
from packages.platform.storage import FileStorage
from packages.presentation.editorial import EditorialContentCriticError

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
    package = _package_for_generation(data)
    await state.set_state(PresentationStates.generating)

    try:
        result = await orchestrator.run_full_pipeline(
            file_infos=sources_meta,
            project_id=project_id,
            user_id=user_id,
            language=lang,
            raw_answers=raw_answers,
            requested_formats=[ExportFormat.HTML, ExportFormat.PPTX_EDITABLE],
            progress=progress,
            package=package,
        )
    except _OrchestratorError as exc:
        if _is_content_grounding_failure(exc):
            logger.warning(
                "presentation_content_ungrounded",
                extra={"project_id": project_id},
            )
            failure_text = labels.generation_ungrounded_refunded
        else:
            logger.exception(
                "presentation_generation_failed_step",
                extra={"project_id": project_id, "step": exc.step},
            )
            failure_text = labels.generation_failed_at_step.format(step=exc.step)
        with contextlib.suppress(Exception):
            await progress_msg.edit_text(failure_text)
        with contextlib.suppress(Exception):
            await db.update_project_status(project_id, "failed")
        await _refund_on_failure(credits, data, project_id)
        await state.clear()
        return
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

    _stash_outputs(project_id, result.render)
    await _register_outputs(db, project_id, result.render)
    try:
        await db.update_project_status(project_id, "ready")
    except Exception as exc:
        logger.warning(
            "presentation_update_status_failed",
            extra={"project_id": project_id, "error_type": type(exc).__name__},
        )

    # Seed the brain editing session eagerly (sources in hand) but keep the user in
    # reviewing_output; the "Edit with AI" button opens the chat loop on demand, so
    # the download / regenerate affordances are preserved and editing is opt-in.
    can_edit = await _open_brain_session(db, project_id, result.sources, package)
    keyboard = presentation_output_keyboard(lang, can_edit=can_edit)
    try:
        await progress_msg.edit_text(labels.download_ready, reply_markup=keyboard)
    except Exception:
        await progress_msg.answer(labels.download_ready, reply_markup=keyboard)
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


async def _open_brain_session(
    db: DatabaseClient,
    project_id: str,
    sources: SourceProcessingResult,
    package: GenerationPackage,
) -> bool:
    """Create the brain editing session; report whether conversational editing is on.

    Best-effort: a create failure — including a deck that never persisted, which
    ``create_session`` refuses (no deck ⇒ raise ⇒ no row) — simply means delivery
    proceeds WITHOUT the "Edit with AI" affordance. Downloads still work; the user
    just cannot chat-edit, the honest state when there is no deck to edit.
    """

    try:
        await create_session(
            db,
            project_id=project_id,
            sources=sources,
            package=package,
            formats=[ExportFormat.HTML, ExportFormat.PPTX_EDITABLE],
        )
    except Exception as exc:
        logger.warning(
            "presentation_brain_session_create_failed",
            extra={"project_id": project_id, "error_type": type(exc).__name__},
        )
        return False
    return True


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


def _is_content_grounding_failure(exc: _OrchestratorError) -> bool:
    """True when an orchestration failure is the content critic's hard stop.

    The orchestrator wraps editorial errors as ``_OrchestratorError("editorial",
    original)``; the critic's hard stop is an :class:`EditorialContentCriticError`.
    We inspect ``original`` and walk a bounded ``__cause__`` chain so the detection
    survives an extra wrap layer, then surface an honest "couldn't ground some
    claims; you've been refunded" message instead of the generic step error.
    """

    candidates: list[BaseException | None] = [exc.original]
    cursor: BaseException | None = exc
    for _ in range(5):
        cursor = cursor.__cause__ if cursor is not None else None
        candidates.append(cursor)
    return any(isinstance(candidate, EditorialContentCriticError) for candidate in candidates)


def _package_for_generation(data: dict[str, Any]) -> GenerationPackage:
    """Resolve the FSM-recorded tier string to a :class:`GenerationPackage`.

    The ``choose_tier`` callback writes ``presentation_{basic,standard,premium}``
    into FSM data — exactly the :class:`GenerationPackage` enum values for the
    three presentation tiers. Missing/malformed values fall back to
    ``PRESENTATION_STANDARD`` with a logged warning so a flow bug never starves
    a paying user to zero images; tier is required at the orchestrator (no
    silent default there — invariant I1), so the handler is the one place that
    owns the str→enum boundary.
    """

    raw = str(data.get("tier") or "")
    try:
        package = GenerationPackage(raw)
    except ValueError:
        logger.warning("presentation_unknown_tier_in_fsm", extra={"tier": raw})
        return GenerationPackage.PRESENTATION_STANDARD
    if not raw.startswith("presentation_"):
        # The presentation flow should never land here with an article/bundle
        # tier (the choose_tier callback prefixes presentation_); if it does,
        # something upstream is wrong — fall back rather than ship a deck
        # without images, and log so the upstream bug is visible.
        logger.warning("presentation_non_presentation_tier_in_fsm", extra={"tier": package.value})
        return GenerationPackage.PRESENTATION_STANDARD
    return package


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


# Downloads are served not only at first delivery (reviewing_output) but
# throughout the editing conversation: a fix re-stashes the new files, so the
# same buttons must keep working in talking_to_brain (and while a change is
# parked at awaiting_approval, where the current files are still downloadable).
_DOWNLOAD_STATES = StateFilter(
    PresentationStates.reviewing_output,
    PresentationStates.talking_to_brain,
    PresentationStates.awaiting_approval,
)


@router.callback_query(_DOWNLOAD_STATES, F.data == "download_html")
async def send_html(callback: CallbackQuery, state: FSMContext) -> None:
    """Send the rendered HTML artefact."""

    await _send_format(callback, state, "html", "")


@router.callback_query(_DOWNLOAD_STATES, F.data == "download_pptx")
async def send_pptx(callback: CallbackQuery, state: FSMContext) -> None:
    """Send the rendered PPTX file."""

    await _send_format(callback, state, "pptx", "")


@router.callback_query(_DOWNLOAD_STATES, F.data == "download_pdf")
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


@router.callback_query(
    StateFilter(PresentationStates.reviewing_output, PresentationStates.talking_to_brain),
    F.data == "done",
)
async def finish(callback: CallbackQuery, state: FSMContext) -> None:
    """End the flow (delivery review OR editing chat): clear FSM, drop cache, menu."""

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


@router.callback_query(PresentationStates.reviewing_output, F.data == "edit_with_ai")
async def edit_with_ai(callback: CallbackQuery, state: FSMContext, db: DatabaseClient) -> None:
    """Open the conversational editor: reviewing_output → talking_to_brain.

    The editing session was created at delivery (deck + sources already loaded), so
    this only enters the chat loop and shows the chat keyboard. If the session is
    gone (evicted, or never created), fall back to the not-found notice and stay put.
    """

    data = await state.get_data()
    project_id = str(data.get("project_id", ""))
    lang = _flow_language(data)
    labels = get_bot_labels(lang)
    session = await load_session(db, project_id) if project_id else None
    if session is None:
        if isinstance(callback.message, Message):
            await callback.message.answer(labels.edit_session_not_found)
        await callback.answer()
        return
    if session.pending_action is not None:
        # A change is parked behind the approval gate (e.g. recovered mid-park after a
        # restart). Re-present the decision — never enter chat with an unanswered call.
        await state.set_state(PresentationStates.awaiting_approval)
        if isinstance(callback.message, Message):
            await callback.message.answer(
                labels.approval_prompt.format(reason=session.pending_action.reason),
                reply_markup=presentation_approval_keyboard(lang),
            )
        await callback.answer()
        return
    await state.set_state(PresentationStates.talking_to_brain)
    if isinstance(callback.message, Message):
        await callback.message.answer(
            labels.edit_invite, reply_markup=presentation_chat_keyboard(lang)
        )
    await callback.answer()


# ---------------------------------------------------------------------------
# Conversational editing loop + approval gate (Build 2, Stage 4)
# ---------------------------------------------------------------------------
#
# After delivery the user edits the deck by talking to the brain (Stage 5). This
# is the MACHINERY: load the DB-backed session by project_id, run ONE turn (a
# scripted stub stands in for the brain), dispatch the brain's fix tool to the
# orchestrator ABOVE the pipeline (apply_fixes_and_render — no run_full_pipeline
# refactor), gate significant re-deliveries behind a user button, cap cumulative
# spend, and persist. A per-project lock serializes concurrent turns. The core
# functions below take no aiogram types so they are unit-testable directly.

# Per-project async locks serialize a session's turns within this process. Like
# _PROJECT_CACHE they are module-local and restart-wiped — correct for a single
# instance (an in-flight turn is lost on restart anyway); a multi-instance
# deployment needs a DB-level lock (SELECT ... FOR UPDATE), the documented
# follow-on.
_SESSION_LOCKS: dict[str, asyncio.Lock] = {}


def _session_lock(project_id: str) -> asyncio.Lock:
    """Get-or-create the per-project turn lock."""

    lock = _SESSION_LOCKS.get(project_id)
    if lock is None:
        lock = asyncio.Lock()
        _SESSION_LOCKS[project_id] = lock
    return lock


def _brain_driver() -> BrainDriver:
    """The driver for one chat turn: the real Gemini tool-calling brain (Stage 5a).

    Constructed per turn like :func:`_orchestrator`, holding a fresh
    ``GeminiClient`` (Vertex-routed, as the editorial passes are) and NO
    orchestrator — so a requested fix can only leave the turn as
    ``TurnOutcome.fixes`` and route through the guarded ``_dispatch_fix``, never be
    applied inside the turn. ``ScriptedStubDriver`` stays for the Stage-4 tests and
    the gate; only this factory's body swaps to the live brain.
    """

    return GeminiBrainDriver(gemini=GeminiClient())


async def _noop_progress(step_name: str, step: int, total: int) -> None:
    """Progress sink for the editing fix-chain; the re-delivery is brief."""

    del step_name, step, total


class _ChatOutcome(StrEnum):
    """What the chat machinery resolved a turn / callback to, for rendering."""

    REPLY = "reply"
    REDELIVERED = "redelivered"
    RENDER_FAILED = "render_failed"
    AWAITING_APPROVAL = "awaiting_approval"
    FIXES_EXHAUSTED = "fixes_exhausted"
    DISCARDED = "discarded"
    NO_SESSION = "no_session"


@dataclass
class _ChatResult:
    """The machinery's verdict; the handler maps it to FSM state + a reply."""

    outcome: _ChatOutcome
    reply_text: str | None = None
    reason: str | None = None
    slides_changed: int = 0
    fix_limit: int = 0  # the tier's edit allowance, for the FIXES_EXHAUSTED message
    warnings: list[str] = field(default_factory=list[str])


async def _run_chat_turn(
    *,
    driver: BrainDriver,
    orchestrator: PresentationOrchestrator,
    db: DatabaseClient,
    project_id: str,
    user_text: str,
    user_initiated: bool,
) -> _ChatResult:
    """Run ONE brain turn: load → turn → (reply | gate | fix).

    The session loads light (no figures). A turn ALWAYS runs — even with the fix
    allowance spent, the user can still chat — so the only cap is the pre-fix
    counter in :func:`_dispatch_fix`. The turn's cost and updated history are
    recorded, then the result routes on whether it re-delivers
    (``bool(outcome.fixes)`` — never the model's label): a plain reply persists
    and returns; a re-delivery is either gated (:func:`requires_approval`, keyed
    on ``user_initiated`` provenance) or, when the user's own message authorized
    it, applied directly.
    """

    session = await load_session(db, project_id)
    if session is None:
        return _ChatResult(_ChatOutcome.NO_SESSION)

    if session.pending_action is not None:
        # A change is parked behind the approval gate: its edit_slides call is still
        # UNANSWERED in history. No brain turn may run against this session — doing so
        # would resend a dangling function_call and 400 (the sharp case: a restart
        # dropped the FSM pointer, the user re-enters chat, and sends a message). Route
        # back to the pending decision; _apply_pending / _reject_pending answer the call.
        return _ChatResult(_ChatOutcome.AWAITING_APPROVAL, reason=session.pending_action.reason)

    outcome = await driver.run_turn(session, user_text)
    session.history = outcome.history
    session.accumulated_cost_usd += outcome.estimated_cost_usd

    if not outcome.fixes:
        await persist_session(db, session)
        return _ChatResult(_ChatOutcome.REPLY, reply_text=outcome.reply_text)

    if requires_approval(outcome, user_initiated=user_initiated):
        session.pending_action = PendingAction(
            fixes=list(outcome.fixes),
            reason=outcome.reason or "",
            call_count=max(1, outcome.fix_call_count),
        )
        session.approval_state = ApprovalState.AWAITING_APPROVAL
        await persist_session(db, session)
        return _ChatResult(_ChatOutcome.AWAITING_APPROVAL, reason=outcome.reason or "")

    return await _dispatch_fix(
        orchestrator=orchestrator,
        db=db,
        session=session,
        fixes=list(outcome.fixes),
        call_count=outcome.fix_call_count,
    )


def _deck_roster(deck: DeckSpec | None) -> list[dict[str, object]]:
    """A compact roster the brain reads to see the deck AFTER a delivered fix."""

    if deck is None:
        return []
    return [
        {"slide_id": s.slide_id, "slide_type": s.slide_type.value, "title": s.content.title}
        for s in deck.slides
    ]


def _append_fix_result(session: BrainSession, response: dict[str, object], *, count: int) -> None:
    """Answer the brain's ``edit_slides`` call(s) with the fix's real outcome.

    Gemini requires EVERY tool call part that ended the previous turn to be answered
    by its own function_response part before the next user turn (else HTTP 400). A
    turn may carry several edit_slides calls (their fixes are merged into one batch),
    so ``count`` (the number of call parts) response parts are appended — never fewer.
    This records delivered / exhausted / failed so the brain's NEXT turn sees a
    coherent call → result history and can react (e.g. not re-issue an exhausted fix).
    """

    parts = [
        FunctionResult(name=EDIT_SLIDES_TOOL_NAME, response=response) for _ in range(max(1, count))
    ]
    session.history = [*session.history, build_function_responses_content(parts)]


async def _dispatch_fix(
    *,
    orchestrator: PresentationOrchestrator,
    db: DatabaseClient,
    session: BrainSession,
    fixes: list[SlideFix],
    call_count: int,
) -> _ChatResult:
    """Fire the orchestrator fix-chain, re-deliver, accumulate spend, persist.

    ``call_count`` is the number of edit_slides call parts in the brain turn (or the
    parked turn) being resolved; every exit path answers each call part with its own
    function_response so the next turn's history stays coherent.

    The single place a fix actually runs — reached by the auto-apply path and the
    approve callback alike. The pre-fix gate is the fix COUNTER: refuse BEFORE the
    expensive call if the session's tier allowance is spent. The count is consumed
    and success reported IFF the fix produced at least one DELIVERABLE rendered
    file — the delivery boundary. ``apply_fixes_and_render`` can RETURN (no
    exception) with zero output files because ``render`` records per-format
    failures as warnings rather than raising; that is a failed fix, not a delivered
    one, so it must not consume the allowance, must not overwrite the prior good
    downloads with an empty map, and must not claim success. An exception from the
    fix chain likewise never reaches the increment. Figures are hydrated here
    (lazy-loaded only now), the edited deck refreshed from the result (apply
    persisted it internally, so a held copy would be stale), and the new files
    re-stashed so the download buttons serve them.
    """

    if not has_fixes_remaining(session.fixes_used, session.package):
        session.pending_action = None
        session.approval_state = ApprovalState.IDLE
        _append_fix_result(
            session,
            {"error": "fixes_exhausted", "fix_limit": session_fix_limit(session.package)},
            count=call_count,
        )
        await persist_session(db, session)
        return _ChatResult(
            _ChatOutcome.FIXES_EXHAUSTED, fix_limit=session_fix_limit(session.package)
        )
    if session.deck is None:
        return _ChatResult(_ChatOutcome.NO_SESSION)

    try:
        await hydrate_figures(db, session)
        result = await orchestrator.apply_fixes_and_render(
            session.deck,
            fixes,
            session.sources,
            session.project_id,
            session.formats,
            _noop_progress,
            package=session.package,
        )
    except Exception as exc:
        # The fix chain can RAISE (a brain-hallucinated/typo'd slide_id, or an empty
        # editorial regen after retry). Degrade gracefully — the way start_generation
        # guards first-gen — instead of crashing the turn: answer the brain's call so
        # the next turn's history stays coherent, persist the conversation, and DO NOT
        # consume the allowance or touch the prior good downloads. apply_fixes_and_render
        # is atomic (it raises before persist/render), so session.deck is still intact.
        logger.warning(
            "presentation_fix_chain_failed",
            extra={"project_id": session.project_id, "error_type": type(exc).__name__},
        )
        session.pending_action = None
        session.approval_state = ApprovalState.IDLE
        _append_fix_result(
            session, {"error": "fix_failed", "detail": type(exc).__name__}, count=call_count
        )
        await persist_session(db, session)
        return _ChatResult(
            _ChatOutcome.RENDER_FAILED,
            warnings=[f"edit could not be applied: {type(exc).__name__}"],
        )
    # The edited deck was persisted INSIDE apply_fixes_and_render (so the next fix
    # builds on it); keep the in-memory copy in sync regardless of render outcome.
    session.deck = result.deck
    session.pending_action = None
    session.approval_state = ApprovalState.IDLE

    if not result.render.by_extension():
        # DELIVERY BOUNDARY: every render format failed — nothing downloadable.
        # The fix was NOT delivered: do not consume the allowance, do not stash an
        # empty map over the prior good paths (the old download buttons keep
        # working), and do not claim success. The conversation IS persisted so the
        # next turn sees this attempt. (Note: the deck advanced in the DB while the
        # user saw a failure — acceptable here because the next fix grounds on the
        # advanced deck and the allowance is intact; surfacing it is the contract.)
        _append_fix_result(
            session,
            {"error": "render_failed", "warnings": list(result.render.warnings)},
            count=call_count,
        )
        await persist_session(db, session)
        return _ChatResult(_ChatOutcome.RENDER_FAILED, warnings=list(result.render.warnings))

    session.fixes_used += 1  # consume one edit — only on a DELIVERED fix
    session.accumulated_cost_usd += result.estimated_cost_usd  # analytics, not the cap
    session.accumulated_image_count += result.image_count
    _stash_outputs(session.project_id, result.render)
    await _register_outputs(db, session.project_id, result.render)
    _append_fix_result(
        session,
        {
            "delivered": True,
            "slides_changed": len(fixes),
            "roster": _deck_roster(session.deck),
        },
        count=call_count,
    )
    await persist_session(db, session)
    return _ChatResult(
        _ChatOutcome.REDELIVERED,
        slides_changed=len(fixes),
        warnings=list(result.render.warnings),
    )


async def _apply_pending(
    *,
    orchestrator: PresentationOrchestrator,
    db: DatabaseClient,
    project_id: str,
) -> _ChatResult:
    """Approve path: fire the parked change. A button — not the model — got here."""

    session = await load_session(db, project_id)
    if session is None or session.pending_action is None:
        return _ChatResult(_ChatOutcome.NO_SESSION)
    return await _dispatch_fix(
        orchestrator=orchestrator,
        db=db,
        session=session,
        fixes=list(session.pending_action.fixes),
        call_count=session.pending_action.call_count,
    )


async def _reject_pending(*, db: DatabaseClient, project_id: str) -> _ChatResult:
    """Reject path: discard the parked change and clear the gate."""

    session = await load_session(db, project_id)
    if session is None:
        return _ChatResult(_ChatOutcome.NO_SESSION)
    if session.pending_action is not None:
        # Answer EACH parked edit_slides call so the next turn's history stays coherent
        # (a dangling/under-answered function_call before a user turn is a Gemini 400).
        _append_fix_result(session, {"discarded": True}, count=session.pending_action.call_count)
    session.pending_action = None
    session.approval_state = ApprovalState.IDLE
    await persist_session(db, session)
    return _ChatResult(_ChatOutcome.DISCARDED)


async def _render_chat_result(
    target: Message, lang: str, labels: BotLabels, result: _ChatResult
) -> None:
    """Send the user-facing message for a chat result; FSM state is the caller's."""

    if result.outcome is _ChatOutcome.REPLY:
        await target.answer(result.reply_text or labels.error_generic)
    elif result.outcome is _ChatOutcome.REDELIVERED:
        text = labels.edit_applied.format(count=result.slides_changed)
        await target.answer(text, reply_markup=presentation_chat_keyboard(lang))
    elif result.outcome is _ChatOutcome.RENDER_FAILED:
        await target.answer(labels.edit_render_failed)
    elif result.outcome is _ChatOutcome.AWAITING_APPROVAL:
        prompt = labels.approval_prompt.format(reason=result.reason or "")
        await target.answer(prompt, reply_markup=presentation_approval_keyboard(lang))
    elif result.outcome is _ChatOutcome.FIXES_EXHAUSTED:
        await target.answer(labels.edit_fixes_exhausted.format(limit=result.fix_limit))
    elif result.outcome is _ChatOutcome.DISCARDED:
        await target.answer(labels.change_discarded)
    else:
        await target.answer(labels.edit_session_not_found)


@router.message(PresentationStates.talking_to_brain, F.text)
async def chat_turn(
    message: Message,
    state: FSMContext,
    bot: Bot,
    db: DatabaseClient,
    credits: CreditLedger,
    storage: FileStorage | None = None,
) -> None:
    """One inbound editing message: load → turn → dispatch/gate → persist → reply."""

    data = await state.get_data()
    project_id = str(data.get("project_id", ""))
    lang = _flow_language(data)
    labels = get_bot_labels(lang)
    if not project_id:
        await message.answer(labels.edit_session_not_found)
        return
    orchestrator = _orchestrator(bot, db, credits, storage)
    async with _session_lock(project_id):
        # A turn in talking_to_brain is triggered by the user's OWN message, so a
        # re-delivery it asks for is user-authorized (no button). The day the
        # brain (Stage 5) re-delivers on its own initiative — outside a user edit
        # request, or proactively — that path must pass user_initiated=False so
        # requires_approval() gates it; the provenance is set HERE, never by the
        # model's turn outcome.
        result = await _run_chat_turn(
            driver=_brain_driver(),
            orchestrator=orchestrator,
            db=db,
            project_id=project_id,
            user_text=message.text or "",
            user_initiated=True,
        )
    await _render_chat_result(message, lang, labels, result)
    if result.outcome is _ChatOutcome.AWAITING_APPROVAL:
        await state.set_state(PresentationStates.awaiting_approval)


@router.message(PresentationStates.awaiting_approval, F.text)
async def blocked_during_approval(message: Message, state: FSMContext) -> None:
    """While a change awaits approval, text does NOT run a turn — resolve first."""

    data = await state.get_data()
    labels = get_bot_labels(_flow_language(data))
    await message.answer(labels.approval_required_first)


@router.callback_query(PresentationStates.awaiting_approval, F.data == "approve_redeliver")
async def approve_redeliver(
    callback: CallbackQuery,
    state: FSMContext,
    bot: Bot,
    db: DatabaseClient,
    credits: CreditLedger,
    storage: FileStorage | None = None,
) -> None:
    """The user authorized the parked change: fire it, re-deliver, resume chatting."""

    data = await state.get_data()
    project_id = str(data.get("project_id", ""))
    lang = _flow_language(data)
    labels = get_bot_labels(lang)
    if not isinstance(callback.message, Message):
        await callback.answer()
        return
    orchestrator = _orchestrator(bot, db, credits, storage)
    async with _session_lock(project_id):
        result = await _apply_pending(orchestrator=orchestrator, db=db, project_id=project_id)
    await _render_chat_result(callback.message, lang, labels, result)
    await state.set_state(PresentationStates.talking_to_brain)
    await callback.answer()


@router.callback_query(PresentationStates.awaiting_approval, F.data == "reject_redeliver")
async def reject_redeliver(callback: CallbackQuery, state: FSMContext, db: DatabaseClient) -> None:
    """The user declined the parked change: discard it, resume chatting."""

    data = await state.get_data()
    project_id = str(data.get("project_id", ""))
    lang = _flow_language(data)
    labels = get_bot_labels(lang)
    if not isinstance(callback.message, Message):
        await callback.answer()
        return
    async with _session_lock(project_id):
        result = await _reject_pending(db=db, project_id=project_id)
    await _render_chat_result(callback.message, lang, labels, result)
    await state.set_state(PresentationStates.talking_to_brain)
    await callback.answer()
