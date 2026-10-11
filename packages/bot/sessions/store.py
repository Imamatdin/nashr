"""Session persistence orchestration (Build 2, Stage 4).

The bot-layer bridge between the typed :class:`BrainSession` and the JSON-valued
:class:`~packages.platform.database.DatabaseClient` brain-session methods. It owns
every (de)serialization the platform layer must not (history via the SDK channel,
sources via the split serializer) and assembles the session from its row plus the
deck of the revision it is editing. Persistence keys on ``project_id`` alone, so
recovery after a restart is a single lookup — no restart can orphan a session.

The session is created on the revision a generation just committed: both the
worker and the bot's ``start_generation`` pass the deck, its revision id and the
sources ``build_deck`` returned (ADR 0001); :func:`create_session` takes them from
its caller by design.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import ValidationError

from packages.bot.orchestrators.article_orchestrator import SourceProcessingResult
from packages.bot.sessions.models import ApprovalState, BrainSession, PendingAction
from packages.bot.sessions.serialization import deserialize_sources, serialize_sources
from packages.core.enums import ExportFormat, GenerationPackage
from packages.core.gemini_tools import deserialize_history, serialize_history
from packages.core.models.presentation import DeckSpec
from packages.platform.database import DatabaseClient
from packages.platform.document_models import DocumentKind
from packages.platform.document_store import DocumentStore

logger = logging.getLogger(__name__)


async def create_session(
    db: DatabaseClient,
    *,
    project_id: str,
    sources: SourceProcessingResult,
    package: GenerationPackage,
    formats: list[ExportFormat],
    revision_id: str,
    deck: DeckSpec,
) -> BrainSession:
    """Create and persist the project's brain session on a committed revision.

    The caller has just committed ``deck`` as ``revision_id`` (ADR 0001), so the
    session starts on exactly that revision. The figure bytes are written ONCE
    here; per-turn saves never touch them.
    """

    light, figures = serialize_sources(sources)
    await db.save_brain_session(
        project_id,
        history_json=[],
        sources_json=light,
        figures_json=figures,
        package=package.value,
        formats_json=[fmt.value for fmt in formats],
        approval_state=ApprovalState.IDLE.value,
        pending_action_json=None,
        fixes_used=0,
        accumulated_cost_usd=0.0,
        accumulated_image_count=0,
        revision_id=revision_id,
    )
    return BrainSession(
        project_id=project_id,
        history=[],
        sources=sources,
        revision_id=revision_id,
        deck=deck,
        package=package,
        formats=formats,
        approval_state=ApprovalState.IDLE,
        pending_action=None,
        fixes_used=0,
        accumulated_cost_usd=0.0,
        accumulated_image_count=0,
        figures_loaded=True,
    )


async def load_session(db: DatabaseClient, project_id: str) -> BrainSession | None:
    """Recover the session by project_id alone, or ``None`` if none exists.

    The light per-turn / restart-recovery read: the source figures are NOT
    loaded (``sources.figures`` is empty, ``figures_loaded`` is False) so a
    text-only turn never deserializes the raster bytes. The fix path calls
    :func:`hydrate_figures` first.
    """

    row = await db.get_brain_session(project_id)
    if row is None:
        return None
    pending_raw = row["pending_action_json"]
    stored_revision = row.get("revision_id")
    revision_id, deck = await load_revision_deck(
        db, project_id, str(stored_revision) if stored_revision else None
    )
    return BrainSession(
        project_id=project_id,
        history=deserialize_history(row["history_json"]),
        sources=deserialize_sources(row["sources_json"], None),
        revision_id=revision_id,
        deck=deck,
        package=GenerationPackage(row["package"]),
        formats=[ExportFormat(fmt) for fmt in row["formats_json"]],
        approval_state=ApprovalState(row["approval_state"]),
        pending_action=PendingAction.model_validate(pending_raw) if pending_raw else None,
        fixes_used=int(row["fixes_used"]),
        accumulated_cost_usd=float(row["accumulated_cost_usd"]),
        accumulated_image_count=int(row["accumulated_image_count"]),
        figures_loaded=False,
    )


async def hydrate_figures(db: DatabaseClient, session: BrainSession) -> BrainSession:
    """Load the heavy source figures into ``session`` before a fix grounds on them.

    Idempotent: a session whose figures are already loaded is returned unchanged.
    Otherwise the figure bytes are fetched and reattached to ``sources`` so the
    regen re-grounds against the same figure roster first-gen used.
    """

    if session.figures_loaded:
        return session
    figures_json = await db.get_brain_session_figures(session.project_id)
    light = session.sources.model_dump(mode="json", exclude={"figures"})
    session.sources = deserialize_sources(light, figures_json)
    session.figures_loaded = True
    return session


async def persist_session(db: DatabaseClient, session: BrainSession) -> None:
    """Write the session's mutated state back, preserving the write-once figures.

    Serializes the conversation through the SDK channel and the light source half
    only; ``figures_json`` is omitted so the upsert keeps the stored figures.
    """

    light, _figures = serialize_sources(session.sources)
    pending_json = (
        session.pending_action.model_dump(mode="json") if session.pending_action else None
    )
    await db.save_brain_session(
        session.project_id,
        history_json=serialize_history(session.history),
        sources_json=light,
        package=session.package.value,
        formats_json=[fmt.value for fmt in session.formats],
        approval_state=session.approval_state.value,
        pending_action_json=pending_json,
        fixes_used=session.fixes_used,
        accumulated_cost_usd=session.accumulated_cost_usd,
        accumulated_image_count=session.accumulated_image_count,
        revision_id=session.revision_id,
    )


async def load_revision_deck(
    db: DatabaseClient, project_id: str, revision_id: str | None
) -> tuple[str | None, DeckSpec | None]:
    """The session's revision and its deck; the head when no revision is recorded.

    A session written before migration 016 has no revision: it adopts the head.
    Content that does not validate as a deck (a legacy import) yields no deck, so
    the session cannot be edited until a valid revision is the head.
    """

    store = DocumentStore(db)
    content: dict[str, Any] | None = None
    if revision_id is not None:
        found = await store.revision_in_project(project_id, revision_id)
        if found is not None:
            content = found[1].content
    if content is None:
        head = await store.head(project_id, DocumentKind.PRESENTATION)
        if head is None:
            return None, None
        revision_id, content = head.revision_id, head.content
    try:
        return revision_id, DeckSpec.model_validate(content)
    except ValidationError:
        logger.warning(
            "session_revision_not_a_deck project=%s revision=%s", project_id, revision_id
        )
        return revision_id, None


async def move_session_to_head(db: DatabaseClient, session: BrainSession) -> bool:
    """Point the session at the current head; True when it moved.

    The bot's Reload button and the web chat (which always edits what the web
    shows) use this. A parked approval is left alone: its call is answered first.
    """

    if session.pending_action is not None:
        return False
    head = await DocumentStore(db).head(session.project_id, DocumentKind.PRESENTATION)
    if head is None or head.revision_id == session.revision_id:
        return False
    revision_id, deck = await load_revision_deck(db, session.project_id, head.revision_id)
    session.revision_id = revision_id
    session.deck = deck
    await persist_session(db, session)
    return True
