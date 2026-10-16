"""Queue an AI edit the way the chat route does: for a call parked on a real session.

Since B1-FIX4 migration 016 (and its emulator) admits a ``presentation_edit`` job,
and its commit, only for the session's currently parked call, and ``dispatch_fix``
refuses any other. Tests that queue an edit park one first, through the real
session store, and stamp the job with the identity this returns.
"""

from __future__ import annotations

from packages.bot.sessions.store import load_session, persist_session
from packages.platform.database import DatabaseClient


async def park_edit(db: DatabaseClient, project_id: str) -> dict[str, str]:
    """Park a call on the project's session; the job payload's ``session_id``/``operation_id``."""

    # Imported here: modules gated against older applications import this file.
    from packages.bot.sessions.parked import park_call

    session = await load_session(db, project_id)
    assert session is not None and session.session_id is not None, "the project has no session"
    operation_id = park_call(session)
    await persist_session(db, session)
    return {"session_id": session.session_id, "operation_id": operation_id}


__all__ = ["park_edit"]
