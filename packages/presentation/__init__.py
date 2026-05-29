"""Presentation engine: design direction, editorial, layout, render.

This package owns everything that turns evidence-matrix-backed content into
a renderable :class:`DeckSpec`. The first piece — the pre-generation
interview — lives in :mod:`packages.presentation.interview`.
"""

from packages.presentation.design_direction import DesignDirectionPass
from packages.presentation.editorial import EditorialPass
from packages.presentation.interview import PresentationInterviewEngine
from packages.presentation.plan_validator import (
    validate_deck_against_plan,
    validate_plan,
    validate_plan_async,
)
from packages.presentation.planner import PlannerError, PlannerPass
from packages.presentation.thesis_classifier import (
    ThesisClassifier,
    ThesisClassifierError,
)

__all__ = [
    "DesignDirectionPass",
    "EditorialPass",
    "PlannerError",
    "PlannerPass",
    "PresentationInterviewEngine",
    "ThesisClassifier",
    "ThesisClassifierError",
    "validate_deck_against_plan",
    "validate_plan",
    "validate_plan_async",
]
