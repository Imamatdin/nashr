"""Presentation creation flow — wired to :class:`PresentationOrchestrator`.

End-to-end conversation:

    upload sources → tier → payment → generate → deliver

The flow parallels :mod:`packages.bot.handlers.article_flow`. It is
entirely in-bot: there is no Mini App questionnaire. Pre-generation
preferences are never collected from the user — every path leaves
``interview_answers`` as ``None`` and
:meth:`PresentationInterviewEngine.apply_defaults` derives answers from
the uploaded sources alone.

The Mini App handlers below (``skip_questionnaire``,
``receive_mini_app_data``) and :func:`build_mini_app_url` are DEPRECATED
dead code since the in-bot flow decision; they stay registered so stale
messages carrying old buttons still resolve.

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
from uuid import uuid4

from aiogram import Bot, F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, FSInputFile, Message
from aiogram.utils.chat_action import ChatActionSender

from packages.bot.keyboards import (
    APPROVE_PREFIX,
    REJECT_PREFIX,
    deck_changed_keyboard,
    main_menu_keyboard,
    parse_approval_callback,
    payment_provider_keyboard,
    presentation_approval_keyboard,
    presentation_chat_keyboard,
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
from packages.bot.orchestrators.deck_revisions import commit_generated_deck, renderable
from packages.bot.orchestrators.inline_publish import fetch_exports, owner_bot_actor, publish_inline
from packages.bot.sessions import (
    ApprovalState,
    BrainDriver,
    BrainSession,
    GeminiBrainDriver,
    PendingAction,
    create_session,
    load_session,
    persist_session,
    requires_approval,
)
from packages.bot.sessions.budget import session_fix_limit
from packages.bot.sessions.parked import is_parked, park_call
from packages.bot.sessions.store import move_session_to_head
from packages.bot.states import PresentationStates
from packages.core.enums import ExportFormat, GenerationPackage
from packages.core.gemini import GeminiClient
from packages.core.models.presentation import DeckSpec, SlideFix
from packages.platform.credits import CreditLedger
from packages.platform.database import DatabaseClient
from packages.platform.document_models import (
    CommitOutcome,
    CommitStatus,
    DocumentKind,
    DocumentStoreError,
    RevisionKind,
    bot_actor,
)
from packages.platform.document_store import DocumentStore
from packages.platform.storage import FileStorage
from packages.presentation.editorial import EditorialContentCriticError
from packages.sessions_core.apply import FixStatus, answer_fix_calls, apply_fix_batch

logger = logging.getLogger("nashr.bot.presentation")

# Telegram delivery formats; renders are all-or-nothing (ADR 0001).
_BOT_FORMATS: list[ExportFormat] = [ExportFormat.HTML, ExportFormat.PPTX_EDITABLE]

router = Router()

MAX_FILE_BYTES: int = 20 * 1024 * 1024
SUPPORTED_EXTENSIONS: frozenset[str] = frozenset(
    {"pdf", "docx", "doc", "txt", "xlsx", "xls", "pptx", "ppt", "jpg", "jpeg", "png"}
)
# DEPRECATED: dead since the in-bot flow decision; no live caller. Do not delete.
MINI_APP_URL_DEFAULT: str = "https://nashr.uz/mini-app/presentation"

# DEPRECATED: dead since the in-bot flow decision; only fed the deprecated
# build_mini_app_url "stats" param. Do not delete.
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


def _count_stat_bearing_sources(  # pyright: ignore[reportUnusedFunction]
    sources: list[dict[str, Any]],
) -> int:
    """DEPRECATED: dead since the in-bot flow decision (fed the Mini App URL)."""

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

    DEPRECATED: dead since the in-bot flow decision; no live caller (only
    its own unit tests). Kept, not deleted, this run.
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
async def continue_to_questionnaire(callback: CallbackQuery, state: FSMContext) -> None:
    """Advance to tier selection in-bot (or refuse if no sources).

    Preferences are no longer collected here: ``interview_answers`` is
    set to ``None`` and :meth:`PresentationInterviewEngine.apply_defaults`
    derives them from the uploaded sources.
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

    await state.update_data(interview_answers=None)

    if isinstance(callback.message, Message):
        await callback.message.edit_text(
            labels.choose_tier, reply_markup=tier_keyboard(lang, "presentation")
        )
    await state.set_state(PresentationStates.choosing_tier)
    await callback.answer()


# ---------------------------------------------------------------------------
# Mini App / Skip — DEPRECATED, dead since the in-bot flow decision
# ---------------------------------------------------------------------------


# DEPRECATED: dead since the in-bot flow decision; kept registered only so a
# stale message carrying the old skip button still resolves. Do not delete.
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


# DEPRECATED: dead since the in-bot flow decision; kept registered only so a
# stale message carrying an old Mini App button still resolves. Do not delete.
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

    store = DocumentStore(db)
    render: PresentationRenderResult | None = None
    try:
        # The head as generation starts: a regeneration commits against it, so a
        # deck changed elsewhere meanwhile is never overwritten (ADR 0001).
        head = await store.head(project_id, DocumentKind.PRESENTATION)
        built = await orchestrator.build_deck(
            file_infos=sources_meta,
            project_id=project_id,
            user_id=user_id,
            language=lang,
            raw_answers=raw_answers,
            progress=progress,
            package=package,
        )
        outcome = await commit_generated_deck(
            store,
            project_id=project_id,
            deck=built.deck,
            actor=await owner_bot_actor(db, user_id),
            base_revision_id=head.revision_id if head is not None else None,
            idempotency_key=f"bot-generation:{uuid4()}",
        )
        revision_id = renderable(outcome) or (
            outcome.revision_id if outcome.status is CommitStatus.UNCHANGED else None
        )
        if revision_id is not None:
            render = await orchestrator.render(built.deck, _BOT_FORMATS, progress)
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

    if revision_id is None or render is None:
        # The deck changed elsewhere while this one was generated: it was kept as
        # a proposal for the owner to review on the web, not written over theirs.
        with contextlib.suppress(Exception):
            await progress_msg.edit_text(labels.deck_regeneration_proposed)
        await state.set_state(PresentationStates.reviewing_output)
        return

    await publish_inline(
        db=db,
        storage=storage,
        project_id=project_id,
        user_id=user_id,
        document_id=outcome.document_id,
        revision_id=revision_id,
        render=render,
        formats=_BOT_FORMATS,
    )
    _stash_outputs(project_id, render)
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
    can_edit = await _open_brain_session(
        db, project_id, built.sources, package, revision_id=revision_id, deck=built.deck
    )
    await state.update_data(can_edit=can_edit)
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


# NOTE (G40): this module used to carry _register_outputs, which INSERTed a
# generated_files row per format carrying the LOCAL rendered path. It was both
# redundant and wrong:
#
#   * redundant — the bot publishes every render as revision exports under an
#     inline job claim (inline_publish.publish_inline, ADR 0001);
#   * wrong — a local /tmp path is not something GET /projects/{id}/deck can
#     sign, so any row that did land made a deck unopenable from the web.
#
# Post-007 the INSERT could not even succeed: it violated the unique constraint
# the orchestrator's upsert targets, raised, and was swallowed into a warning on
# every single delivery. Registration belongs to whoever holds the render job's
# claim. _stash_outputs is untouched — Telegram delivery genuinely does serve the
# local files.


async def _open_brain_session(
    db: DatabaseClient,
    project_id: str,
    sources: SourceProcessingResult,
    package: GenerationPackage,
    *,
    revision_id: str,
    deck: DeckSpec,
) -> bool:
    """Create the brain editing session on the committed revision.

    Best-effort: a create failure simply means delivery proceeds WITHOUT the
    "Edit with AI" affordance. Downloads still work; the user just cannot
    chat-edit.
    """

    try:
        await create_session(
            db,
            project_id=project_id,
            sources=sources,
            package=package,
            formats=_BOT_FORMATS,
            revision_id=revision_id,
            deck=deck,
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
    """Cancel from the output-review state.

    ``cancel_flow`` buttons live only on article keyboards; this catches a stale
    one pressed here at presentation output review. Any other stale cancel (a
    different state, or none) is answered by the fallback router.
    """

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
            assert session.session_id is not None
            await callback.message.answer(
                labels.approval_prompt.format(reason=session.pending_action.reason),
                reply_markup=presentation_approval_keyboard(
                    lang,
                    session_id=session.session_id,
                    operation_id=session.parked_operation_id,
                ),
            )
        await callback.answer()
        return
    await state.set_state(PresentationStates.talking_to_brain)
    if isinstance(callback.message, Message):
        await callback.message.answer(
            labels.edit_invite, reply_markup=presentation_chat_keyboard(lang)
        )
    await callback.answer()


@router.message(PresentationStates.reviewing_output)
async def reviewing_output_nudge(message: Message, state: FSMContext) -> None:
    """A message typed at output review: editing is a button, not free text.

    No ``F.text`` filter — any message type lands here. When the deck has an
    editing session, point the user at the "Edit with AI" button; when it does
    not (session creation failed at delivery), say editing is unavailable rather
    than telling them to tap a button the keyboard omits. Zero model calls.
    """

    data = await state.get_data()
    lang = _flow_language(data)
    labels = get_bot_labels(lang)
    can_edit = bool(data.get("can_edit", False))
    keyboard = presentation_output_keyboard(lang, can_edit=can_edit)
    text = labels.edit_nudge if can_edit else labels.edit_nudge_unavailable
    await message.answer(text, reply_markup=keyboard)


# ---------------------------------------------------------------------------
# Conversational editing loop + approval gate (Build 2, Stage 4)
# ---------------------------------------------------------------------------
#
# After delivery the user edits the deck by talking to the brain (Stage 5). This
# is the MACHINERY: load the DB-backed session by project_id, run ONE turn (a
# scripted stub stands in for the brain), dispatch the brain's fix tool through
# the shared fix path (sessions_core.apply: apply → commit against the session's
# revision → render/publish), gate significant re-deliveries behind a user button,
# cap cumulative spend, and persist. A per-project lock serializes concurrent turns. The core
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
    DECK_CHANGED = "deck_changed"
    UNCHANGED = "unchanged"
    # The button's decision was answered or replaced since it was shown (B1-FIX5).
    DECISION_STALE = "decision_stale"


@dataclass
class _ChatResult:
    """The machinery's verdict; the handler maps it to FSM state + a reply."""

    outcome: _ChatOutcome
    reply_text: str | None = None
    reason: str | None = None
    slides_changed: int = 0
    fix_limit: int = 0  # the tier's edit allowance, for the FIXES_EXHAUSTED message
    warnings: list[str] = field(default_factory=list[str])
    # AWAITING_APPROVAL: the parked decision the buttons name (B1-FIX5).
    session_id: str | None = None
    operation_id: str | None = None


async def _run_chat_turn(
    *,
    driver: BrainDriver,
    orchestrator: PresentationOrchestrator,
    db: DatabaseClient,
    project_id: str,
    user_text: str,
    user_initiated: bool,
    telegram_id: int,
    storage: FileStorage | None = None,
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
        return _ChatResult(
            _ChatOutcome.AWAITING_APPROVAL,
            reason=session.pending_action.reason,
            session_id=session.session_id,
            operation_id=session.parked_operation_id,
        )

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
        # The web may approve this decision, queuing an edit for this exact call.
        park_call(session)
        await persist_session(db, session)
        return _ChatResult(
            _ChatOutcome.AWAITING_APPROVAL,
            reason=outcome.reason or "",
            session_id=session.session_id,
            operation_id=session.parked_operation_id,
        )

    return await _dispatch_fix(
        orchestrator=orchestrator,
        db=db,
        session=session,
        fixes=list(outcome.fixes),
        call_count=outcome.fix_call_count,
        telegram_id=telegram_id,
        storage=storage,
        reply_text=outcome.reply_text,
    )


def _append_fix_result(session: BrainSession, response: dict[str, object], *, count: int) -> None:
    """Answer the brain's ``edit_slides`` call(s) with the fix's real outcome."""

    answer_fix_calls(session, response, count=count)


_FIX_OUTCOMES: dict[FixStatus, _ChatOutcome] = {
    FixStatus.DELIVERED: _ChatOutcome.REDELIVERED,
    FixStatus.CONFLICT: _ChatOutcome.DECK_CHANGED,
    # A bot edit never proposes (bot_edit conflicts instead); mapped for completeness.
    FixStatus.PROPOSED: _ChatOutcome.DECK_CHANGED,
    FixStatus.UNCHANGED: _ChatOutcome.UNCHANGED,
    FixStatus.FAILED: _ChatOutcome.RENDER_FAILED,
    FixStatus.RENDER_FAILED: _ChatOutcome.RENDER_FAILED,
    FixStatus.EXHAUSTED: _ChatOutcome.FIXES_EXHAUSTED,
    FixStatus.NO_SESSION: _ChatOutcome.NO_SESSION,
}


async def _dispatch_fix(
    *,
    orchestrator: PresentationOrchestrator,
    db: DatabaseClient,
    session: BrainSession,
    fixes: list[SlideFix],
    call_count: int,
    telegram_id: int,
    storage: FileStorage | None = None,
    reply_text: str | None = None,
) -> _ChatResult:
    """Apply a fix batch through the shared path, commit it as the user's bot edit, re-deliver.

    The edit commits against the revision this session is editing
    (``session.revision_id``), so a deck changed on the web meanwhile is never
    overwritten: the commit conflicts and the user is offered a reload (ADR 0001).
    Allowance, call answering and persistence follow
    :func:`packages.sessions_core.apply.apply_fix_batch`.
    """

    store = DocumentStore(db)
    actor = bot_actor(telegram_id)
    rendered: list[PresentationRenderResult] = []

    async def commit(deck: DeckSpec, base: str | None) -> CommitOutcome:
        document_id = await store.document_id(session.project_id, DocumentKind.PRESENTATION)
        if document_id is None:
            raise DocumentStoreError("document_not_found")
        return await store.commit(
            document_id,
            base,
            deck.model_dump(mode="json"),
            kind=RevisionKind.BOT_EDIT,
            actor=actor,
            idempotency_key=f"bot-edit:{uuid4()}",
        )

    async def deliver(deck: DeckSpec, revision_id: str, formats: list[ExportFormat]) -> list[str]:
        render = await orchestrator.render(deck, formats, _noop_progress)
        rendered.append(render)
        project = await db.get_project(session.project_id)
        document_id = await store.document_id(session.project_id, DocumentKind.PRESENTATION)
        if project is not None and document_id is not None:
            await publish_inline(
                db=db,
                storage=storage,
                project_id=session.project_id,
                user_id=str(project["user_id"]),
                document_id=document_id,
                revision_id=revision_id,
                render=render,
                formats=formats,
            )
        return list(render.warnings)

    result = await apply_fix_batch(
        runner=orchestrator,
        db=db,
        session=session,
        fixes=fixes,
        call_count=call_count,
        progress=_noop_progress,
        commit=commit,
        deliver=deliver,
    )
    if result.status is FixStatus.DELIVERED and rendered:
        _stash_outputs(session.project_id, rendered[-1])
    return _ChatResult(
        _FIX_OUTCOMES[result.status],
        slides_changed=result.slides_changed,
        warnings=list(result.warnings),
        reply_text=reply_text,
        fix_limit=session_fix_limit(session.package),
    )


async def _apply_pending(  # pyright: ignore[reportUnusedFunction]  (kept for B8 item 1)
    *,
    orchestrator: PresentationOrchestrator,
    db: DatabaseClient,
    project_id: str,
    telegram_id: int,
    session_id: str,
    operation_id: str | None,
    storage: FileStorage | None = None,
) -> _ChatResult:
    """Approve path: fire the parked change. A button — not the model — got here.

    UNREACHABLE until B8 item 1: the Approve button no longer calls this (it applies
    inline through ``commit_revision`` without operation fencing); bot approvals
    will go through the same operation-bound queued job as web approvals.

    Only the decision the button was shown for (B1-FIX5): one answered or replaced
    since is DECISION_STALE and nothing is applied or written.
    """

    session = await load_session(db, project_id)
    if session is None or session.pending_action is None:
        return _ChatResult(_ChatOutcome.NO_SESSION)
    if not is_parked(session, session_id, operation_id):
        return _ChatResult(_ChatOutcome.DECISION_STALE)
    return await _dispatch_fix(
        orchestrator=orchestrator,
        db=db,
        session=session,
        fixes=list(session.pending_action.fixes),
        call_count=session.pending_action.call_count,
        telegram_id=telegram_id,
        storage=storage,
    )


async def _reject_pending(
    *, db: DatabaseClient, project_id: str, session_id: str, operation_id: str | None
) -> _ChatResult:
    """Reject path: discard the parked change and clear the gate.

    Only the decision the button was shown for (B1-FIX5): one answered or replaced
    since is DECISION_STALE and nothing is written.
    """

    session = await load_session(db, project_id)
    if session is None:
        return _ChatResult(_ChatOutcome.NO_SESSION)
    if session.pending_action is not None and not is_parked(session, session_id, operation_id):
        return _ChatResult(_ChatOutcome.DECISION_STALE)
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
        label = labels.edit_applied.format(count=result.slides_changed)
        text = f"{result.reply_text}\n\n{label}" if result.reply_text else label
        await target.answer(text, reply_markup=presentation_chat_keyboard(lang))
    elif result.outcome is _ChatOutcome.RENDER_FAILED:
        await target.answer(labels.edit_render_failed)
    elif result.outcome is _ChatOutcome.AWAITING_APPROVAL:
        prompt = labels.approval_prompt.format(reason=result.reason or "")
        assert result.session_id is not None
        keyboard = presentation_approval_keyboard(
            lang, session_id=result.session_id, operation_id=result.operation_id
        )
        await target.answer(prompt, reply_markup=keyboard)
    elif result.outcome is _ChatOutcome.FIXES_EXHAUSTED:
        await target.answer(labels.edit_fixes_exhausted.format(limit=result.fix_limit))
    elif result.outcome is _ChatOutcome.DISCARDED:
        await target.answer(labels.change_discarded)
    elif result.outcome is _ChatOutcome.DECK_CHANGED:
        await target.answer(labels.deck_changed_elsewhere, reply_markup=deck_changed_keyboard(lang))
    elif result.outcome is _ChatOutcome.UNCHANGED:
        await target.answer(labels.edit_unchanged, reply_markup=presentation_chat_keyboard(lang))
    elif result.outcome is _ChatOutcome.DECISION_STALE:
        await target.answer(labels.approval_stale)
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
    if _session_lock(project_id).locked():
        # A turn is already running for this project. DROP this message with a
        # notice rather than queue it behind the lock — queued, it would run
        # minutes later as a stale edit the user has moved on from. They resend.
        # Accepted edge: a released lock with queued waiters reads locked()==False,
        # so a message could still queue — but a waiter requires chat_turn and
        # approve_redeliver to contend, and their FSM states (talking_to_brain vs
        # awaiting_approval) are mutually exclusive; a turn racing a freshly parked
        # action is stopped by the pending_action guard in _run_chat_turn.
        await message.answer(labels.brain_busy)
        return
    orchestrator = _orchestrator(bot, db, credits, storage)
    async with (
        _session_lock(project_id),
        ChatActionSender.typing(bot=bot, chat_id=message.chat.id),
    ):
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
            telegram_id=message.from_user.id if message.from_user else message.chat.id,
            storage=storage,
        )
    await _render_chat_result(message, lang, labels, result)
    if result.outcome is _ChatOutcome.AWAITING_APPROVAL:
        await state.set_state(PresentationStates.awaiting_approval)


@router.message(PresentationStates.talking_to_brain)
async def talking_to_brain_non_text(message: Message, state: FSMContext) -> None:
    """Non-text message while editing: the brain edits from words only.

    Registered AFTER :func:`chat_turn` (which carries ``F.text``), so source order
    lets text win and this catches everything else — photos, documents, stickers,
    voice — with a nudge to describe the change in words. Zero model calls.
    """

    data = await state.get_data()
    labels = get_bot_labels(_flow_language(data))
    await message.answer(labels.brain_text_only)


@router.message(PresentationStates.awaiting_approval, F.text)
async def blocked_during_approval(message: Message, state: FSMContext) -> None:
    """While a change awaits approval, text does NOT run a turn — resolve first."""

    data = await state.get_data()
    labels = get_bot_labels(_flow_language(data))
    await message.answer(labels.approval_required_first)


@router.callback_query(F.data.in_({"approve_redeliver", "reject_redeliver"}))
async def legacy_approval_button(callback: CallbackQuery, state: FSMContext) -> None:
    """A button sent before decisions were named (B1-FIX5): it can name none, so it does nothing."""

    labels = get_bot_labels(_flow_language(await state.get_data()))
    if isinstance(callback.message, Message):
        await callback.message.answer(labels.approval_stale)
    await callback.answer()


@router.callback_query(
    PresentationStates.awaiting_approval, F.data.startswith(f"{APPROVE_PREFIX}:")
)
async def approve_redeliver(
    callback: CallbackQuery,
    state: FSMContext,
    bot: Bot,
    db: DatabaseClient,
    credits: CreditLedger,
    storage: FileStorage | None = None,
) -> None:
    """The user pressed Approve: for now, the change is applied from the web.

    B8 item 1: the bot's inline apply (:func:`_apply_pending`) commits through
    ``commit_revision`` with no operation fencing, unlike a web approval's
    operation-bound queued job. Until bot approvals go through that same job, the
    button applies nothing: it says so in the user's language, and the decision
    stays parked, so it can be approved on the web or rejected here. Nothing is
    committed, delivered or counted. The dependencies stay injected for B8.
    """

    del bot, db, credits, storage
    labels = get_bot_labels(_flow_language(await state.get_data()))
    if isinstance(callback.message, Message):
        await callback.message.answer(labels.approval_web_only)
    await callback.answer()


@router.callback_query(
    PresentationStates.awaiting_approval, F.data.startswith(f"{REJECT_PREFIX}:")
)
async def reject_redeliver(callback: CallbackQuery, state: FSMContext, db: DatabaseClient) -> None:
    """The user declined the parked change: discard it, resume chatting."""

    data = await state.get_data()
    project_id = str(data.get("project_id", ""))
    lang = _flow_language(data)
    labels = get_bot_labels(lang)
    named = parse_approval_callback(callback.data or "")
    if not isinstance(callback.message, Message) or named is None:
        await callback.answer()
        return
    _prefix, session_id, operation_id = named
    async with _session_lock(project_id):
        result = await _reject_pending(
            db=db, project_id=project_id, session_id=session_id, operation_id=operation_id
        )
    await _render_chat_result(callback.message, lang, labels, result)
    if result.outcome is not _ChatOutcome.DECISION_STALE:
        await state.set_state(PresentationStates.talking_to_brain)
    await callback.answer()


@router.callback_query(
    StateFilter(PresentationStates.talking_to_brain, PresentationStates.reviewing_output),
    F.data == "reload_deck",
)
async def reload_deck(
    callback: CallbackQuery,
    state: FSMContext,
    db: DatabaseClient,
    storage: FileStorage | None = None,
) -> None:
    """Move the editing session to the latest version after a conflict (ADR 0001).

    The download buttons serve cached local files; they belonged to the old
    revision, so they are replaced by the new head's published exports, or
    dropped when that revision has none yet.
    """

    data = await state.get_data()
    project_id = str(data.get("project_id", ""))
    lang = _flow_language(data)
    labels = get_bot_labels(lang)
    if not isinstance(callback.message, Message):
        await callback.answer()
        return
    async with _session_lock(project_id):
        session = await load_session(db, project_id) if project_id else None
        if session is None:
            await callback.message.answer(labels.edit_session_not_found)
            await callback.answer()
            return
        await move_session_to_head(db, session)
        slot = _cache(project_id)
        slot.pop("files", None)
        if session.revision_id is not None:
            files = await fetch_exports(db, storage, session.revision_id)
            if files:
                slot["files"] = {ext: str(path) for ext, path in files.items()}
    await state.set_state(PresentationStates.talking_to_brain)
    await callback.message.answer(
        labels.deck_reloaded, reply_markup=presentation_chat_keyboard(lang)
    )
    await callback.answer()
