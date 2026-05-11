"""Presentation engine: design direction, editorial, layout, render.

This package owns everything that turns evidence-matrix-backed content into
a renderable :class:`DeckSpec`. The first piece — the pre-generation
interview — lives in :mod:`packages.presentation.interview`.
"""

from packages.presentation.design_direction import DesignDirectionPass
from packages.presentation.editorial import EditorialPass
from packages.presentation.interview import PresentationInterviewEngine

__all__ = ["DesignDirectionPass", "EditorialPass", "PresentationInterviewEngine"]
