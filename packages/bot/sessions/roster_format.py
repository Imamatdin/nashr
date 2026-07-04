"""Human-facing deck roster formatting for the conversational brain.

``slide_index`` in :class:`~packages.core.models.presentation.DeckSpec` stays
0-based for storage and routing (``slide_id`` is authoritative). Bracket labels
shown to the model and in ``edit_slides`` function responses use **1-based**
display numbers so "slide 5" in user speech matches roster ``[5]``.
"""

from __future__ import annotations

from packages.core.models.presentation import DeckSpec, SlideSpec


def display_slide_number(slide_index: int) -> int:
    """Map stored ``slide_index`` (0-based) to a human slide number (1-based)."""

    return slide_index + 1


def format_roster_line(slide: SlideSpec) -> str:
    """One roster line for the injected DECK ROSTER text block."""

    number = display_slide_number(slide.slide_index)
    return (
        f"[{number}] slide_id={slide.slide_id} type={slide.slide_type.value} "
        f"— {slide.content.title}"
    )


def render_roster_text(deck: DeckSpec | None) -> str:
    """Multiline roster for the once-injected session context prefix."""

    if deck is None or not deck.slides:
        return "(no slides)"
    return "\n".join(format_roster_line(slide) for slide in deck.slides)


def render_roster_payload(deck: DeckSpec | None) -> list[dict[str, object]]:
    """Structured roster returned in ``edit_slides`` function responses."""

    if deck is None:
        return []
    return [
        {
            "slide_number": display_slide_number(slide.slide_index),
            "slide_id": slide.slide_id,
            "slide_type": slide.slide_type.value,
            "title": slide.content.title,
        }
        for slide in deck.slides
    ]


__all__ = [
    "display_slide_number",
    "format_roster_line",
    "render_roster_payload",
    "render_roster_text",
]
