"""Seed and edit gate decks through the canonical write path (ADR 0001).

The live Build 2 gates used to write the ``decks`` table directly. Since
migration 016 a deck is the head revision of the project's presentation
document, written only through ``commit_revision``; these helpers do that.
"""

from __future__ import annotations

from uuid import uuid4

from packages.core.models.presentation import DeckSpec
from packages.platform.database import DatabaseClient
from packages.platform.document_models import (
    DocumentKind,
    RevisionKind,
    bot_actor,
    user_actor,
)
from packages.platform.document_store import DocumentStore


async def _owner(db: DatabaseClient, project_id: str) -> dict[str, object]:
    project = await db.get_project(project_id)
    if project is None:
        raise SystemExit(f"gate project {project_id} not found")
    user = await db.get_user_by_id(str(project["user_id"]))
    if user is None:
        raise SystemExit(f"gate project {project_id} has no owner")
    return user


async def owner_telegram_id(db: DatabaseClient, project_id: str) -> int:
    """The Telegram id of the gate project's throwaway owner."""

    telegram_id = (await _owner(db, project_id)).get("telegram_id")
    if not isinstance(telegram_id, int):
        raise SystemExit("gate owner has no Telegram id")
    return telegram_id


async def seed_deck_revision(db: DatabaseClient, project_id: str, deck: DeckSpec) -> str:
    """Commit ``deck`` as the presentation head (a manual revision by the owner)."""

    actor = user_actor(str((await _owner(db, project_id))["id"]))
    store = DocumentStore(db)
    document_id = await store.ensure_document(project_id, DocumentKind.PRESENTATION, actor)
    head = await store.head(project_id, DocumentKind.PRESENTATION)
    outcome = await store.commit(
        document_id,
        head.revision_id if head is not None else None,
        deck.model_dump(mode="json"),
        kind=RevisionKind.MANUAL,
        actor=actor,
        idempotency_key=f"gate-seed:{uuid4()}",
    )
    if outcome.revision_id is None:
        raise SystemExit(f"seeding the gate deck did not commit: {outcome.status}")
    return outcome.revision_id


async def commit_bot_edit(
    db: DatabaseClient, project_id: str, base_revision_id: str, deck: DeckSpec
) -> str:
    """Commit an edited deck the way the bot does; returns the new head revision."""

    store = DocumentStore(db)
    document_id = await store.document_id(project_id, DocumentKind.PRESENTATION)
    if document_id is None:
        raise SystemExit("gate project has no presentation document")
    outcome = await store.commit(
        document_id,
        base_revision_id,
        deck.model_dump(mode="json"),
        kind=RevisionKind.BOT_EDIT,
        actor=bot_actor(await owner_telegram_id(db, project_id)),
        idempotency_key=f"gate-edit:{uuid4()}",
    )
    if outcome.revision_id is None:
        raise SystemExit(f"gate edit did not commit: {outcome.status}")
    return outcome.revision_id
