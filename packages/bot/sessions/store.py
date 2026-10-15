"""Session persistence orchestration (Build 2, Stage 4; B1-FIX3).

The bot-layer bridge between the typed :class:`BrainSession` and the JSON-valued
:class:`~packages.platform.database.DatabaseClient` brain-session methods. It owns
every (de)serialization the platform layer must not and assembles the session from
its row, the deck of the revision it is editing, and its edit_deliveries rows.
Persistence keys on ``project_id`` alone, so recovery after a restart is a single
lookup — no restart can orphan a session.

Since B1-FIX3:

* reading never writes (:func:`load_session` is pure; Codex A2);
* every write is a compare-and-swap on the row's version, and a write that loses
  it reloads the row and three-way merges instead of overwriting (Codex A2);
* the edit allowance's queued half is counted from edit_deliveries rows the
  database settles, and an answer a dead worker never wrote is recovered from its
  job's receipt (Codex A1);
* a corrupt row is a :class:`SessionDataInvalidError`, never a crash (Codex A3).

The session is created on the revision a generation just committed: both the
worker and the bot's ``start_generation`` pass the deck, its revision id and the
sources ``build_deck`` returned (ADR 0001).
"""

from __future__ import annotations

import json
import logging
from typing import Any, Final

from pydantic import ValidationError

from packages.bot.orchestrators.article_orchestrator import SourceProcessingResult
from packages.bot.sessions.delivery import apply_deliveries, fold_notes
from packages.bot.sessions.models import BrainSession
from packages.bot.sessions.receipts import answer_from_receipt, receipt_for, receipt_revision
from packages.bot.sessions.serialization import deserialize_sources, serialize_sources
from packages.bot.sessions.session_rows import (
    SessionConflictError,
    SessionDataInvalidError,
    columns_from_row,
    columns_of,
    merge,
    parse_row,
)
from packages.core.enums import ExportFormat, GenerationPackage
from packages.core.models.presentation import DeckSpec
from packages.platform.database import DatabaseClient, SessionVersionConflictError
from packages.platform.document_models import DocumentKind
from packages.platform.document_store import DocumentStore
from packages.platform.edit_deliveries import acknowledge_notices, session_deliveries

logger = logging.getLogger(__name__)

# A write that keeps losing its compare-and-swap gives up rather than spin.
_WRITE_ATTEMPTS: Final[int] = 5


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
    """Create (or replace) the project's brain session on a committed revision.

    A regeneration replaces the session: the old row is removed under its version
    (its edit deliveries stay, unattached) and the new one starts a new allowance.
    The figure bytes are written ONCE here; per-turn saves never touch them.
    ``fixes_used`` is not written: it is the bot's inline counter (B1-FIX3).
    """

    session = BrainSession(
        project_id=project_id,
        sources=sources,
        revision_id=revision_id,
        deck=deck,
        package=package,
        formats=formats,
        figures_loaded=True,
    )
    columns = columns_of(session)
    columns.pop("fixes_used")
    _light, figures = serialize_sources(sources)
    for _attempt in range(_WRITE_ATTEMPTS):
        existing = await db.get_brain_session(project_id)
        try:
            if existing is not None:
                await db.delete_brain_session(str(existing["id"]), int(existing["version"]))
            row = await db.insert_brain_session(project_id, {**columns, "figures_json": figures})
        except SessionVersionConflictError:
            continue
        session.session_id = str(row["id"])
        session.version = 0
        session._base = columns_from_row(row)  # pyright: ignore[reportPrivateUsage]
        return session
    raise SessionConflictError(project_id, "create_contended")


async def load_session(db: DatabaseClient, project_id: str) -> BrainSession | None:
    """Recover the session by project_id alone, or ``None`` if none exists.

    A pure read. The source figures are NOT loaded (``figures_loaded`` is False);
    the fix path calls :func:`hydrate_figures` first. The edit allowance and the
    chat notices come from the session's edit_deliveries rows, and an unanswered
    call whose job left a receipt is answered from it, in memory: the next write
    persists both. Raises :class:`SessionDataInvalidError` for a corrupt row.
    """

    row = await db.get_brain_session(project_id)
    if row is None:
        return None
    session = parse_row(project_id, row)
    job = await receipt_for(db, session)
    revision = receipt_revision(job) if job is not None else None
    session.revision_id, session.deck = await load_revision_deck(
        db, project_id, revision or session.revision_id
    )
    if job is not None:
        answer_from_receipt(session, job, session.deck if revision is not None else None)
    try:
        rows = await session_deliveries(db, str(session.session_id))
    except ValidationError as exc:
        raise SessionDataInvalidError(project_id, "edit_deliveries", str(exc)) from None
    apply_deliveries(session, rows)
    session._base = columns_from_row(row)  # pyright: ignore[reportPrivateUsage]
    return session


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
    """Write the session's changes back with a compare-and-swap; merge on conflict.

    Only columns that differ from what was read are written, so a writer never
    restates (and never overwrites) a column it did not change; in particular the
    web and worker paths never write ``fixes_used``. Unfolded delivery notices are
    folded in first and acknowledged once the write landed. A lost compare-and-swap
    reloads the row and merges (:func:`~packages.bot.sessions.session_rows.merge`).
    """

    folded = fold_notes(session)
    base = session._base  # pyright: ignore[reportPrivateUsage]
    ours = columns_of(session)
    if base is None or session.session_id is None:
        raise SessionConflictError(session.project_id, "session_not_loaded")
    # The row the session must end up mirroring once a merge was needed.
    latest: dict[str, Any] | None = None
    for _attempt in range(_WRITE_ATTEMPTS):
        changed = {column: value for column, value in ours.items() if base.get(column) != value}
        if not changed:
            break
        try:
            row = await db.update_brain_session(session.session_id, session.version, changed)
        except SessionVersionConflictError:
            fresh = await db.get_brain_session(session.project_id)
            if fresh is None or str(fresh.get("id")) != session.session_id:
                raise SessionConflictError(session.project_id, "session_replaced") from None
            theirs = columns_from_row(fresh)
            ours = merge(session.project_id, base, ours, theirs)
            base, session.version, latest = theirs, int(fresh["version"]), fresh
            logger.info(
                "session_write_merged %s",
                json.dumps({"project_id": session.project_id, "columns": sorted(changed)}),
            )
            continue
        session.version = int(row["version"])
        base = columns_from_row(row)
        if latest is not None:
            latest = row
        break
    else:
        raise SessionConflictError(session.project_id, "write_contended")
    if latest is not None:
        _adopt(session, latest)
    session._base = base  # pyright: ignore[reportPrivateUsage]
    if folded:
        await _acknowledge(db, session, folded)


def _adopt(session: BrainSession, row: dict[str, Any]) -> None:
    """Take the merged row's values, keeping what only memory holds (deck, figures)."""

    merged = parse_row(session.project_id, row)
    session.history = merged.history
    session.pending_action = merged.pending_action
    session.approval_state = merged.approval_state
    session.inline_fixes_used = merged.inline_fixes_used
    session.accumulated_cost_usd = merged.accumulated_cost_usd
    session.accumulated_image_count = merged.accumulated_image_count
    session.delivery_notes = merged.delivery_notes
    session.formats = merged.formats
    session.package = merged.package
    if merged.revision_id != session.revision_id:
        session.revision_id = merged.revision_id
        session.deck = None


async def _acknowledge(db: DatabaseClient, session: BrainSession, job_ids: list[str]) -> None:
    """Best-effort: an unacknowledged notice is shown once anyway (job ids dedupe it)."""

    try:
        await acknowledge_notices(db, str(session.session_id), job_ids)
    except Exception as exc:
        logger.warning(
            "session_notice_ack_failed %s",
            json.dumps({"project_id": session.project_id, "error_type": type(exc).__name__}),
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


__all__ = [
    "SessionConflictError",
    "SessionDataInvalidError",
    "create_session",
    "hydrate_figures",
    "load_revision_deck",
    "load_session",
    "move_session_to_head",
    "persist_session",
]
