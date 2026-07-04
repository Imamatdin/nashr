"""Session persistence orchestration (Build 2, Stage 4).

The bot-layer bridge between the typed :class:`BrainSession` and the JSON-valued
:class:`~packages.platform.database.DatabaseClient` brain-session methods. It owns
every (de)serialization the platform layer must not (history via the SDK channel,
sources via the split serializer) and assembles the session from its row plus the
deck. Persistence keys on ``project_id`` alone, so recovery after a restart is a
single lookup — no restart can orphan a session.

The wiring gap this module was built against is CLOSED (Stage 5a):
``run_full_pipeline`` returns its sources via ``PresentationPipelineResult`` and
the delivery handler seeds the session through ``_open_brain_session``
(``presentation_flow.start_generation``); :func:`create_session` still takes the
live sources from its caller by design.
"""

from __future__ import annotations

from packages.bot.orchestrators.article_orchestrator import SourceProcessingResult
from packages.bot.sessions.models import ApprovalState, BrainSession, PendingAction
from packages.bot.sessions.serialization import deserialize_sources, serialize_sources
from packages.core.enums import ExportFormat, GenerationPackage
from packages.core.gemini_tools import deserialize_history, serialize_history
from packages.core.models.presentation import DeckSpec
from packages.platform.database import DatabaseClient


async def create_session(
    db: DatabaseClient,
    *,
    project_id: str,
    sources: SourceProcessingResult,
    package: GenerationPackage,
    formats: list[ExportFormat],
) -> BrainSession:
    """Create and persist the project's brain session, returning the live object.

    The deck is read back from the decks table (``run_full_pipeline`` already
    persisted it), so the decks table stays the single source of truth for the
    deck. The figure bytes are written ONCE here; per-turn saves never touch them.

    INVARIANT — a ``brain_sessions`` row implies a persisted deck: the deck is
    loaded and verified BEFORE the row is written, so a deck-less session is never
    created (the pipeline's deck persist is itself best-effort). No deck ⇒ raise ⇒
    no row, so downstream can treat any session row as backed by a real deck.
    """

    deck = await _load_deck(db, project_id)
    if deck is None:
        raise ValueError(
            f"cannot create a brain session for project {project_id}: no persisted deck"
        )
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
    )
    return BrainSession(
        project_id=project_id,
        history=[],
        sources=sources,
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
    return BrainSession(
        project_id=project_id,
        history=deserialize_history(row["history_json"]),
        sources=deserialize_sources(row["sources_json"], None),
        deck=await _load_deck(db, project_id),
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
    )


async def _load_deck(db: DatabaseClient, project_id: str) -> DeckSpec | None:
    """Load the project's current deck as a typed spec, or ``None`` if unsaved."""

    deck_row = await db.get_deck(project_id)
    if deck_row is None:
        return None
    return DeckSpec.model_validate(deck_row["deck_json"])
