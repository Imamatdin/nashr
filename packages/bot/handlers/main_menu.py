"""Main-menu router: dispatches the top-level menu callbacks.

Each menu item either starts a flow (article, presentation) or shows
a read-only view (projects, balance). Flow starts always create a
fresh project row so the FSM can hang every subsequent decision off
its UUID; this keeps draft state in the database, not just in memory.
"""

from __future__ import annotations

from typing import Any

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State
from aiogram.types import CallbackQuery, Message

from packages.bot.labels import get_bot_labels
from packages.bot.states import ArticleStates, PresentationStates
from packages.platform.database import DatabaseClient

router = Router()

_STATUS_EMOJI: dict[str, str] = {
    "draft": "📝",
    "generating": "⏳",
    "completed": "✅",
    "failed": "❌",
}


def _user_language(user: dict[str, Any] | None) -> str:
    if user is None:
        return "uz"
    lang = user.get("language")
    if isinstance(lang, str) and lang:
        return lang
    return "uz"


async def _start_flow(
    callback: CallbackQuery,
    state: FSMContext,
    db: DatabaseClient,
    *,
    project_type: str,
    first_state: State,
    default_title: str,
) -> None:
    user = await db.get_user_by_telegram_id(callback.from_user.id)
    if user is None:
        await callback.answer(get_bot_labels("uz").please_start_first)
        return

    lang = _user_language(user)
    labels = get_bot_labels(lang)

    project = await db.create_project(
        user_id=str(user["id"]),
        title=default_title,
        project_type=project_type,
        language=lang,
    )

    await state.update_data(
        project_id=str(project["id"]),
        user_id=str(user["id"]),
        language=lang,
        sources=[],
    )

    if isinstance(callback.message, Message):
        await callback.message.edit_text(labels.upload_prompt)
    await state.set_state(first_state)
    await callback.answer()


@router.callback_query(F.data == "create_article")
async def start_article(callback: CallbackQuery, state: FSMContext, db: DatabaseClient) -> None:
    """Create a draft article project and enter the upload stage."""

    await _start_flow(
        callback,
        state,
        db,
        project_type="article",
        first_state=ArticleStates.uploading_sources,
        default_title="New Article",
    )


@router.callback_query(F.data == "create_presentation")
async def start_presentation(
    callback: CallbackQuery, state: FSMContext, db: DatabaseClient
) -> None:
    """Create a draft presentation project and enter the upload stage."""

    await _start_flow(
        callback,
        state,
        db,
        project_type="presentation",
        first_state=PresentationStates.uploading_sources,
        default_title="New Presentation",
    )


@router.callback_query(F.data == "my_projects")
async def show_projects(callback: CallbackQuery, db: DatabaseClient) -> None:
    """Render the user's 10 most recent projects with status emoji."""

    user = await db.get_user_by_telegram_id(callback.from_user.id)
    if user is None:
        await callback.answer()
        return

    projects = await db.get_user_projects(str(user["id"]))

    if not projects:
        lang = _user_language(user)
        labels = get_bot_labels(lang)
        if isinstance(callback.message, Message):
            await callback.message.edit_text(labels.no_projects_yet)
        await callback.answer()
        return

    lines: list[str] = []
    for p in projects[:10]:
        emoji = _STATUS_EMOJI.get(str(p.get("status", "draft")), "📝")
        title = str(p.get("title", "Untitled"))
        ptype = str(p.get("type", p.get("project_type", "")))
        lines.append(f"{emoji} {title} ({ptype})")

    if isinstance(callback.message, Message):
        await callback.message.edit_text("\n".join(lines))
    await callback.answer()


@router.callback_query(F.data == "my_balance")
async def show_balance(callback: CallbackQuery, db: DatabaseClient) -> None:
    """Show the user's credit balance (full wiring lands in Task 29)."""

    user = await db.get_user_by_telegram_id(callback.from_user.id)
    if user is None:
        await callback.answer()
        return

    lang = _user_language(user)
    labels = get_bot_labels(lang)
    if isinstance(callback.message, Message):
        await callback.message.edit_text(labels.balance_info.format(balance="—", free_today="—"))
    await callback.answer()
