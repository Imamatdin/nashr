"""The ``edit_slides`` tool responses a resolved fix batch answers the model with.

One definition, used both when the worker answers the call itself
(:mod:`packages.sessions_core.apply`) and when a session load recovers the answer
from the job's receipt because the worker never got to write it (B1-FIX3, Codex A1).
"""

from __future__ import annotations

from packages.bot.sessions.roster_format import render_roster_payload
from packages.core.models.presentation import DeckSpec


def committed_response(deck: DeckSpec, slides_changed: int) -> dict[str, object]:
    """Committed; the job's render is publishing the exports (not yet delivered)."""

    return {
        "committed": True,
        "delivery": "rendering",
        "slides_changed": slides_changed,
        "roster": render_roster_payload(deck),
    }


def delivered_response(deck: DeckSpec, slides_changed: int) -> dict[str, object]:
    """Committed, rendered and published."""

    return {
        "delivered": True,
        "slides_changed": slides_changed,
        "roster": render_roster_payload(deck),
    }


def proposed_response() -> dict[str, object]:
    """The deck moved while the edit ran; it was stored as a proposal."""

    return {
        "proposed": True,
        "detail": "the deck changed while this edit ran; it was saved for review",
    }


def unchanged_response() -> dict[str, object]:
    """The edit produced the deck that was already there."""

    return {"unchanged": True}


__all__ = [
    "committed_response",
    "delivered_response",
    "proposed_response",
    "unchanged_response",
]
