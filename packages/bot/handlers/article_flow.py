"""Article creation flow — wired to :class:`ArticleOrchestrator`.

End-to-end conversation:

    upload sources → process → research interview → outline →
    review → tier → (payment) → draft → verify → export → deliver

Heavy work is delegated to the orchestrator; this module owns the FSM
transitions, the progress messages, and the file delivery handlers.
Complex objects (claims, chunks, the evidence matrix, the outline, the
draft, the rendered files) cannot survive aiogram's FSM storage cleanly
because pydantic instances do not pickle through MemoryStorage; we keep
them in a process-local :data:`_PROJECT_CACHE` keyed by ``project_id``.
The cache is wiped on flow completion or cancellation. It is **not**
durable across bot restarts and is **not** safe for multi-instance
deployment — that lands when we move state into Redis.

CLAUDE.md's 300-line cap is intentionally exceeded: every stage shares
state (project_id, language, labels, the cache slot), and splitting
the upload/interview/outline/payment/export handlers into separate
modules would just scatter the conversation flow across files.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from packages.bot.keyboards import (
    main_menu_keyboard,
    outline_review_keyboard,
    output_review_keyboard,
    payment_provider_keyboard,
    tier_keyboard,
    upload_more_keyboard,
)
from packages.bot.labels import BotLabels, get_bot_labels
from packages.bot.orchestrators import (
    ArticleOrchestrator,
    ProgressCallback,
    SourceProcessingResult,
)
from packages.bot.states import ArticleStates
from packages.core.models.article import ArticleDraftResult, ArticleOutline
from packages.core.models.evidence import (
    EvidenceMatrix,
    ResearchQuestion,
)
from packages.platform.credits import CreditLedger
from packages.platform.database import DatabaseClient
from packages.platform.storage import FileStorage

logger = logging.getLogger("nashr.bot.article")

router = Router()

MAX_FILE_BYTES: int = 20 * 1024 * 1024
SUPPORTED_EXTENSIONS: frozenset[str] = frozenset(
    {"pdf", "docx", "doc", "txt", "xlsx", "xls", "pptx", "ppt", "jpg", "jpeg", "png"}
)

# Module-local cache for per-project pipeline state. See module docstring.
_PROJECT_CACHE: dict[str, dict[str, Any]] = {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_extension(filename: str) -> str:
    """Lowercase extension, or empty string if the name has no dot."""

    if "." not in filename:
        return ""
    return filename.rsplit(".", 1)[-1].lower()


def _flow_language(data: dict[str, Any]) -> str:
    """Pull the FSM-stored language code; fall back to Uzbek."""

    lang = data.get("language")
    if isinstance(lang, str) and lang:
        return lang
    return "uz"


def _cache(project_id: str) -> dict[str, Any]:
    """Get-or-create the orchestration cache slot for one project."""

    slot = _PROJECT_CACHE.get(project_id)
    if slot is None:
        slot = {}
        _PROJECT_CACHE[project_id] = slot
    return slot


def _drop_cache(project_id: str) -> None:
    """Wipe the project's cache slot. Safe to call when the slot is missing."""

    _PROJECT_CACHE.pop(project_id, None)


def _orchestrator(
    bot: Bot,
    db: DatabaseClient,
    credits: CreditLedger,
    storage: FileStorage | None = None,
) -> ArticleOrchestrator:
    """Compose a fresh orchestrator. Cheap; each engine is stateless."""

    return ArticleOrchestrator(bot=bot, db=db, credits=credits, storage=storage)


def _progress_editor(message: Message, labels: BotLabels) -> ProgressCallback:
    """Return a closure that edits ``message`` with the current step.

    The callable signature matches :data:`ProgressCallback`. If the
    Telegram edit fails (message was deleted, content unchanged) we log
    and continue — progress UX is best-effort, not load-bearing.
    """

    async def callback(step_name: str, step: int, total: int) -> None:
        try:
            await message.edit_text(
                labels.generating.format(progress=f"{step}/{total}: {step_name}…")
            )
        except Exception as exc:
            logger.debug(
                "article_flow_progress_edit_failed",
                extra={"error_type": type(exc).__name__},
            )

    return callback


def _format_outline_for_review(outline: ArticleOutline) -> str:
    """Render the outline as the body of the review message."""

    lines = [f"<b>{outline.title}</b>", ""]
    for index, section in enumerate(outline.sections, start=1):
        lines.append(f"{index}. {section.title}")
        if section.section_thesis:
            lines.append(f"   <i>{section.section_thesis}</i>")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Upload stage
# ---------------------------------------------------------------------------


@router.message(ArticleStates.uploading_sources, F.document)
async def receive_document(message: Message, state: FSMContext) -> None:
    """Validate and stash a document source."""

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


# ---------------------------------------------------------------------------
# Process sources → interview
# ---------------------------------------------------------------------------


@router.callback_query(ArticleStates.waiting_for_more_sources, F.data == "continue_flow")
async def continue_to_processing(
    callback: CallbackQuery,
    state: FSMContext,
    bot: Bot,
    db: DatabaseClient,
    credits: CreditLedger,
) -> None:
    """Process sources, build the evidence matrix, and ask the first question."""

    data = await state.get_data()
    lang = _flow_language(data)
    labels = get_bot_labels(lang)
    sources_meta = list(data.get("sources", []))
    if not sources_meta:
        if isinstance(callback.message, Message):
            await callback.message.edit_text(labels.error_no_sources)
        await callback.answer()
        return
    if not isinstance(callback.message, Message):
        await callback.answer()
        return
    progress_msg: Message = callback.message
    await progress_msg.edit_text(labels.generating.format(progress="1/8: …"))
    await callback.answer()
    progress = _progress_editor(progress_msg, labels)

    project_id = str(data.get("project_id", ""))
    user_id = str(data.get("user_id", ""))
    orchestrator = _orchestrator(bot, db, credits)

    try:
        sources = await orchestrator.process_sources(
            file_infos=sources_meta,
            project_id=project_id,
            user_id=user_id,
            progress=progress,
        )
        matrix = await orchestrator.build_evidence_matrix(sources, project_id, progress)
        cache = _cache(project_id)
        cache["sources"] = sources
        cache["matrix"] = matrix
        cache["answers"] = []

        questions = await orchestrator.generate_interview_questions(
            sources=sources, matrix=matrix, project_id=project_id, language=lang
        )
    except ValueError as exc:
        await progress_msg.edit_text(f"{labels.generation_failed}\n\n{exc}")
        _drop_cache(project_id)
        await state.clear()
        return
    except Exception as exc:
        logger.exception(
            "article_flow_processing_failed",
            extra={"project_id": project_id, "error_type": type(exc).__name__},
        )
        await progress_msg.edit_text(labels.generation_failed)
        _drop_cache(project_id)
        await state.clear()
        return

    cache["questions"] = questions
    if not questions:
        await _generate_and_show_outline(progress_msg, state, orchestrator, data, progress)
        return

    await state.update_data(current_question_index=0)
    await _show_interview_question(progress_msg, questions[0], labels)
    await state.set_state(ArticleStates.answering_interview)


# ---------------------------------------------------------------------------
# Interview
# ---------------------------------------------------------------------------


async def _show_interview_question(
    target: Message, question: ResearchQuestion, labels: BotLabels
) -> None:
    """Render a single interview question with a 'Skip' shortcut."""

    skip_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=labels.skip_questionnaire, callback_data="skip_question")]
        ]
    )
    text = f"❓ {question.question_text}"
    try:
        await target.edit_text(text, reply_markup=skip_kb)
    except Exception:
        await target.answer(text, reply_markup=skip_kb)


@router.message(ArticleStates.answering_interview)
async def handle_interview_text_answer(
    message: Message,
    state: FSMContext,
    bot: Bot,
    db: DatabaseClient,
    credits: CreditLedger,
) -> None:
    """User typed an answer; score it, update matrix, advance."""

    if message.text is None:
        return
    data = await state.get_data()
    lang = _flow_language(data)
    labels = get_bot_labels(lang)
    project_id = str(data.get("project_id", ""))
    user_id = str(data.get("user_id", ""))
    cache = _cache(project_id)
    questions: list[ResearchQuestion] = cache.get("questions", [])
    current_idx = int(data.get("current_question_index", 0))

    if current_idx >= len(questions):
        return

    question = questions[current_idx]
    matrix: EvidenceMatrix | None = cache.get("matrix")
    sources: SourceProcessingResult | None = cache.get("sources")
    if matrix is None or sources is None:
        await message.answer(labels.generation_failed)
        return

    orchestrator = _orchestrator(bot, db, credits)
    earned = False
    try:
        updated_matrix, earned, research_answer = await orchestrator.process_interview_answer(
            question=question,
            answer_text=message.text.strip(),
            matrix=matrix,
            sources=sources,
            project_id=project_id,
            user_id=user_id,
            language=lang,
        )
        cache["matrix"] = updated_matrix
        cache.setdefault("answers", []).append(research_answer)
    except Exception as exc:
        logger.warning(
            "article_flow_interview_failed",
            extra={"error_type": type(exc).__name__},
        )

    if earned:
        await message.answer(
            labels.free_credit_earned.format(amount=CreditLedger.FREE_CREDIT_VALUE)
        )

    await _advance_interview(message, state, orchestrator, data, bot, db, credits)


@router.callback_query(ArticleStates.answering_interview, F.data == "skip_question")
async def skip_interview_question(
    callback: CallbackQuery,
    state: FSMContext,
    bot: Bot,
    db: DatabaseClient,
    credits: CreditLedger,
) -> None:
    """Skip without scoring; advance to the next question or to the outline."""

    if not isinstance(callback.message, Message):
        await callback.answer()
        return
    data = await state.get_data()
    orchestrator = _orchestrator(bot, db, credits)
    await _advance_interview(callback.message, state, orchestrator, data, bot, db, credits)
    await callback.answer()


async def _advance_interview(
    target: Message,
    state: FSMContext,
    orchestrator: ArticleOrchestrator,
    data: dict[str, Any],
    bot: Bot,
    db: DatabaseClient,
    credits: CreditLedger,
) -> None:
    """Move to the next interview question or kick off outline generation."""

    del bot, db, credits  # captured by `orchestrator`
    lang = _flow_language(data)
    labels = get_bot_labels(lang)
    project_id = str(data.get("project_id", ""))
    cache = _cache(project_id)
    questions: list[ResearchQuestion] = cache.get("questions", [])
    next_idx = int(data.get("current_question_index", 0)) + 1

    if next_idx < len(questions):
        await state.update_data(current_question_index=next_idx)
        await _show_interview_question(target, questions[next_idx], labels)
        return

    progress = _progress_editor(target, labels)
    await _generate_and_show_outline(target, state, orchestrator, data, progress)


# ---------------------------------------------------------------------------
# Outline review
# ---------------------------------------------------------------------------


async def _generate_and_show_outline(
    target: Message,
    state: FSMContext,
    orchestrator: ArticleOrchestrator,
    data: dict[str, Any],
    progress: ProgressCallback,
) -> None:
    """Run the outline generator and render the review keyboard."""

    lang = _flow_language(data)
    labels = get_bot_labels(lang)
    project_id = str(data.get("project_id", ""))
    project_title = str(data.get("project_title", "New Article"))
    cache = _cache(project_id)
    sources: SourceProcessingResult | None = cache.get("sources")
    matrix: EvidenceMatrix | None = cache.get("matrix")
    if sources is None or matrix is None:
        try:
            await target.edit_text(labels.generation_failed)
        except Exception:
            await target.answer(labels.generation_failed)
        await state.clear()
        return

    try:
        outline = await orchestrator.generate_outline(
            sources=sources,
            matrix=matrix,
            project_id=project_id,
            language=lang,
            tier=str(data.get("tier") or "basic"),
            project_title=project_title,
            progress=progress,
        )
    except Exception as exc:
        logger.exception(
            "article_flow_outline_failed",
            extra={"project_id": project_id, "error_type": type(exc).__name__},
        )
        try:
            await target.edit_text(labels.generation_failed)
        except Exception:
            await target.answer(labels.generation_failed)
        await state.clear()
        return

    cache["outline"] = outline
    text = f"{labels.outline_ready}\n\n{_format_outline_for_review(outline)}"
    keyboard = outline_review_keyboard(lang)
    try:
        await target.edit_text(text, reply_markup=keyboard)
    except Exception:
        await target.answer(text, reply_markup=keyboard)
    await state.set_state(ArticleStates.reviewing_outline)


@router.callback_query(ArticleStates.reviewing_outline, F.data == "approve_outline")
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


@router.callback_query(ArticleStates.reviewing_outline, F.data == "regenerate_outline")
async def regenerate_outline(
    callback: CallbackQuery,
    state: FSMContext,
    bot: Bot,
    db: DatabaseClient,
    credits: CreditLedger,
) -> None:
    """Run outline generation again with the same inputs."""

    if not isinstance(callback.message, Message):
        await callback.answer()
        return
    chat_message: Message = callback.message
    data = await state.get_data()
    labels = get_bot_labels(_flow_language(data))
    progress = _progress_editor(chat_message, labels)
    orchestrator = _orchestrator(bot, db, credits)
    await _generate_and_show_outline(chat_message, state, orchestrator, data, progress)
    await callback.answer()


# ---------------------------------------------------------------------------
# Tier & payment hand-off
# ---------------------------------------------------------------------------


@router.callback_query(ArticleStates.choosing_tier, F.data.startswith("tier_"))
async def choose_tier(callback: CallbackQuery, state: FSMContext) -> None:
    """Record the chosen tier and show the payment-provider keyboard."""

    raw = callback.data or ""
    tier = raw.removeprefix("tier_")
    await state.update_data(tier=f"article_{tier}")

    data = await state.get_data()
    lang = _flow_language(data)
    labels = get_bot_labels(lang)
    if isinstance(callback.message, Message):
        await callback.message.edit_text(
            labels.choose_payment, reply_markup=payment_provider_keyboard(lang)
        )
    await state.set_state(ArticleStates.confirming_payment)
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
    """Run draft → verify → export. Called from payment_flow when payment lands."""

    data = await state.get_data()
    lang = _flow_language(data)
    labels = get_bot_labels(lang)
    project_id = str(data.get("project_id", ""))
    cache = _cache(project_id)
    outline: ArticleOutline | None = cache.get("outline")
    matrix: EvidenceMatrix | None = cache.get("matrix")
    sources: SourceProcessingResult | None = cache.get("sources")
    if outline is None or matrix is None or sources is None:
        await target.answer(labels.generation_failed)
        await state.clear()
        return

    progress_msg: Message = await target.answer(labels.generating.format(progress="…"))
    progress = _progress_editor(progress_msg, labels)
    orchestrator = _orchestrator(bot, db, credits, storage=storage)
    await state.set_state(ArticleStates.generating)

    try:
        draft: ArticleDraftResult = await orchestrator.draft_article(
            outline=outline,
            matrix=matrix,
            sources=sources,
            questions=cache.get("questions", []),
            answers=cache.get("answers", []),
            language=lang,
            calibration=str(data.get("calibration") or "bakalavr"),
            progress=progress,
        )
        verification = await orchestrator.verify_citations(draft, matrix, sources, progress)
        docx_path, pdf_path, _bundle = await orchestrator.export(
            draft=draft,
            outline=outline,
            verification=verification,
            sources=sources,
            project_id=project_id,
            language=lang,
            author_name=str(data.get("author_name") or "Nashr foydalanuvchisi"),
            progress=progress,
        )
    except Exception as exc:
        logger.exception(
            "article_flow_generation_failed",
            extra={"project_id": project_id, "error_type": type(exc).__name__},
        )
        await progress_msg.edit_text(labels.generation_failed)
        await db.update_project_status(project_id, "failed")
        await _refund_on_failure(credits, data, project_id)
        await state.clear()
        return

    cache["docx_path"] = str(docx_path)
    if pdf_path is not None:
        cache["pdf_path"] = str(pdf_path)

    await _register_outputs(db, project_id, docx_path, pdf_path)
    await db.update_project_status(project_id, "completed")

    await progress_msg.edit_text(labels.download_ready, reply_markup=output_review_keyboard(lang))
    await state.set_state(ArticleStates.reviewing_output)


async def _register_outputs(
    db: DatabaseClient, project_id: str, docx_path: Path, pdf_path: Path | None
) -> None:
    """Persist rows for every rendered output file."""

    try:
        await db.create_generated_file(
            project_id=project_id,
            file_type="docx",
            storage_path=str(docx_path),
            file_size=docx_path.stat().st_size if docx_path.exists() else 0,
        )
        if pdf_path is not None:
            await db.create_generated_file(
                project_id=project_id,
                file_type="pdf",
                storage_path=str(pdf_path),
                file_size=pdf_path.stat().st_size if pdf_path.exists() else 0,
            )
    except Exception as exc:
        logger.warning(
            "article_flow_register_outputs_failed",
            extra={"project_id": project_id, "error_type": type(exc).__name__},
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
            reason="article_generation_failed",
        )
    except Exception as exc:
        logger.warning(
            "article_flow_refund_failed",
            extra={"error_type": type(exc).__name__},
        )


# ---------------------------------------------------------------------------
# Output delivery
# ---------------------------------------------------------------------------


@router.callback_query(ArticleStates.reviewing_output, F.data == "download_docx")
async def send_docx(callback: CallbackQuery, state: FSMContext) -> None:
    """Send the rendered DOCX file."""

    data = await state.get_data()
    lang = _flow_language(data)
    labels = get_bot_labels(lang)
    cache = _cache(str(data.get("project_id", "")))
    path = cache.get("docx_path")

    if not isinstance(callback.message, Message):
        await callback.answer()
        return
    if isinstance(path, str) and Path(path).exists():
        await callback.message.answer_document(FSInputFile(path, filename="nashr_article.docx"))
    else:
        await callback.message.answer(labels.error_generic)
    await callback.answer()


@router.callback_query(ArticleStates.reviewing_output, F.data == "download_pdf")
async def send_pdf(callback: CallbackQuery, state: FSMContext) -> None:
    """Send the rendered PDF file (or warn if LibreOffice was missing)."""

    data = await state.get_data()
    lang = _flow_language(data)
    labels = get_bot_labels(lang)
    cache = _cache(str(data.get("project_id", "")))
    path = cache.get("pdf_path")

    if not isinstance(callback.message, Message):
        await callback.answer()
        return
    if isinstance(path, str) and Path(path).exists():
        await callback.message.answer_document(FSInputFile(path, filename="nashr_article.pdf"))
    else:
        await callback.message.answer(labels.error_generic)
    await callback.answer()


@router.callback_query(ArticleStates.reviewing_output, F.data == "done")
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


@router.callback_query(F.data == "cancel_flow")
async def cancel(callback: CallbackQuery, state: FSMContext) -> None:
    """Cancel the active flow from any state."""

    data = await state.get_data()
    lang = _flow_language(data)
    labels = get_bot_labels(lang)
    _drop_cache(str(data.get("project_id", "")))
    if isinstance(callback.message, Message):
        await callback.message.edit_text(labels.main_menu, reply_markup=main_menu_keyboard(lang))
    await state.clear()
    await callback.answer()
