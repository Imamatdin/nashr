"""Bot-side orchestrators that wire engine pipelines to Telegram flows.

Orchestrators sit between the handler layer (thin, FSM-driven) and the
worker engines (Telegram-agnostic). Each orchestrator owns the
sequencing of engine calls for one product flow and exposes a
``ProgressCallback`` seam so handlers can edit Telegram messages as the
pipeline advances.
"""

from __future__ import annotations

from packages.bot.orchestrators.article_orchestrator import (
    ArticleOrchestrator,
    ProgressCallback,
    SourceProcessingResult,
    map_calibration,
    map_language,
)

__all__ = [
    "ArticleOrchestrator",
    "ProgressCallback",
    "SourceProcessingResult",
    "map_calibration",
    "map_language",
]
