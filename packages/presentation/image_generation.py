"""Source-informed generation of object/concept/scene images, styled to the deck.

This resolves the slots the Commons path does not: contained object-figures,
abstract concept visuals, and full-bleed scene backgrounds. Generation is
*grounded* in the user's own sources — when an uploaded figure is topically
relevant, the engine captions it (vision) and folds that understanding into the
prompt as art direction. It never copies the source pixels and never uses the
source image directly; the output is always a freshly generated image, styled to
the deck's cohesion family via ``design.image_style_prefix``.

Generated images depict objects/concepts/scenes only, never a real identifiable
person — those are sourced from Commons (:mod:`packages.presentation.commons_portraits`).
"""

from __future__ import annotations

import logging
import re
from typing import Final

from packages.core.enums import ImageSubjectType
from packages.core.gemini_image import GeminiImageClient
from packages.core.models.presentation import DesignDirectionSpec
from packages.core.models.source import SourceFigure
from packages.presentation.image_types import ResolvedImage

logger = logging.getLogger(__name__)

# Minimum shared content tokens before a source figure is considered relevant to
# a slide's subject. Two avoids matching on a single incidental word.
GROUNDING_MIN_OVERLAP: Final[int] = 2
_UNDERSTANDING_MAX_CHARS: Final[int] = 300

_VISION_INSTRUCTION: Final[str] = (
    "Describe ONLY the technical subject shown in this figure in one short "
    "phrase, for use as art direction (e.g. 'a 42U server rack with liquid "
    "cooling manifolds'). Do not mention text, labels, axes, or chart type."
)

_STOPWORDS: Final[frozenset[str]] = frozenset(
    {
        "the",
        "and",
        "for",
        "with",
        "from",
        "this",
        "that",
        "into",
        "over",
        "under",
        "isolated",
        "background",
        "neutral",
        "figure",
        "image",
        "diagram",
        "showing",
        "shows",
        "view",
    }
)


def _tokens(text: str) -> set[str]:
    """Content tokens (len >= 4, stopwords removed) for topic matching."""

    return {
        t for t in re.findall(r"[a-z0-9]+", text.lower()) if len(t) >= 4 and t not in _STOPWORDS
    }


def find_relevant_figure(subject_prompt: str, figures: list[SourceFigure]) -> SourceFigure | None:
    """Return the source figure most topically relevant to ``subject_prompt``.

    Relevance is content-token overlap between the subject and each figure's
    caption + context, requiring at least :data:`GROUNDING_MIN_OVERLAP` shared
    tokens. The richest match wins; nothing clearing the bar returns ``None`` so
    the caller generates from the subject alone.
    """

    subject_tokens = _tokens(subject_prompt)
    if not subject_tokens or not figures:
        return None

    best: SourceFigure | None = None
    best_overlap = GROUNDING_MIN_OVERLAP - 1
    for figure in figures:
        haystack = f"{figure.caption or ''} {figure.context}"
        overlap = len(subject_tokens & _tokens(haystack))
        if overlap > best_overlap:
            best_overlap = overlap
            best = figure
    return best


def build_generation_prompt(
    subject_prompt: str,
    subject_type: ImageSubjectType,
    design: DesignDirectionSpec,
    source_understanding: str | None = None,
) -> str:
    """Compose the final, deck-styled generation prompt.

    Order: the deck's shared style prefix (cohesion), the slot's subject, the
    source-derived understanding when present (direction only), a framing clause
    keyed to the subject type, and a hard no-text constraint. A scene fills the
    frame; an object/concept is isolated on a clean background.
    """

    parts: list[str] = [
        design.image_style_prefix.strip().rstrip(",").strip(),
        subject_prompt.strip(),
    ]
    if source_understanding:
        parts.append(f"faithful to reference material depicting {source_understanding.strip()}")
    if subject_type is ImageSubjectType.SCENE:
        parts.append("full-bleed atmospheric scene, 16:9 composition")
    else:
        parts.append("a single subject isolated on a clean, uncluttered background")
    parts.append("no text, no words, no labels, no watermarks, no logos")
    return ", ".join(part for part in parts if part)


class GeneratedImageResolver:
    """Generate one styled, source-informed image for a slot, or abstain."""

    def __init__(self, image_client: GeminiImageClient | None = None) -> None:
        self._client = image_client

    def _get_client(self) -> GeminiImageClient:
        if self._client is None:
            self._client = GeminiImageClient()
        return self._client

    async def resolve(
        self,
        subject_prompt: str,
        subject_type: ImageSubjectType,
        design: DesignDirectionSpec,
        figures: list[SourceFigure],
    ) -> ResolvedImage | None:
        """Resolve a generated image for one slot; ``None`` on any failure.

        Steps: topic-match a source figure → understand it (vision, falling back
        to its extracted caption) → build a deck-styled, source-informed prompt
        → generate. The returned bytes are always the GENERATED image, never the
        source figure's pixels.
        """

        cleaned = subject_prompt.strip()
        if not cleaned:
            return None

        understanding = await self._understand(find_relevant_figure(cleaned, figures))
        prompt = build_generation_prompt(cleaned, subject_type, design, understanding)

        try:
            generated = await self._get_client().generate_image(prompt)
        except Exception as exc:
            logger.warning(
                "image_generation_failed",
                extra={"subject_type": subject_type.value, "error_type": type(exc).__name__},
            )
            return None

        return ResolvedImage(data=generated.data, content_type=generated.content_type)

    async def _understand(self, figure: SourceFigure | None) -> str | None:
        """Caption a relevant source figure for art direction; abstain to None.

        Prefers a fresh vision caption; if that fails it falls back to the
        figure's already-extracted caption text, so grounding still works even
        when the vision call errors. Returns ``None`` when there is no figure or
        no usable text — generation then proceeds from the subject alone.
        """

        if figure is None:
            return None
        caption = ""
        try:
            caption = await self._get_client().caption_image(
                figure.data, figure.content_type, _VISION_INSTRUCTION
            )
        except Exception as exc:
            logger.warning("figure_caption_failed", extra={"error_type": type(exc).__name__})
        text = (caption or "").strip() or (figure.caption or "").strip()
        return text[:_UNDERSTANDING_MAX_CHARS] or None


__all__ = [
    "GROUNDING_MIN_OVERLAP",
    "GeneratedImageResolver",
    "build_generation_prompt",
    "find_relevant_figure",
]
