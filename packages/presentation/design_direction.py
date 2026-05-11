"""Design Direction Pass for the presentation pipeline.

The pass is the "creative director" of the pipeline. It maps an academic
content domain plus the user's interview preferences onto an aesthetic
specification (palette, fonts, image style prefix) that the rest of the
pipeline treats as immutable.

The mapping is intentionally deterministic — no LLM call is involved.
Domain detection (which is the only fuzzy step) is delegated to
:class:`packages.suggestions.domain_detector.DomainDetector`, a pure
keyword scanner. Encoding the design judgment as data lets the project
ship one-shot studio-quality decks without paying for an extra LLM call
per generation and without LLM jitter colouring the deck differently on
re-runs.

See :file:`packages/presentation/DESIGN-LANGUAGE.md` rules R12 (palette
selection), R23 (image style consistency), R15 (light/dark coexistence),
R50 (font glyph coverage).
"""

from __future__ import annotations

from typing import Final

from packages.core.enums import (
    BackgroundTreatment,
    PresentationMood,
)
from packages.core.models.presentation import (
    ColorPalette,
    DesignDirectionSpec,
    PresentationInterviewAnswers,
)
from packages.core.models.source import (
    SourceChunkCreate,
    SourceClaimCreate,
    SourceMetadataExtracted,
)
from packages.core.models.suggestion import AcademicDomain
from packages.suggestions.domain_detector import DomainDetector

_DEFAULT_PALETTES: Final[dict[PresentationMood, ColorPalette]] = {
    PresentationMood.WARM_HISTORICAL: ColorPalette(
        background="#F5F0E8",
        surface="#FFFFFF",
        text="#2A2A2A",
        accent="#8B6914",
        text_secondary="#6B5B3E",
    ),
    PresentationMood.BOLD_TECHNICAL: ColorPalette(
        background="#0D0D12",
        surface="#1A1A24",
        text="#E8E8EC",
        accent="#E8553A",
        text_secondary="#8888A0",
    ),
    PresentationMood.CLEAN_PROFESSIONAL: ColorPalette(
        background="#F8F8FA",
        surface="#FFFFFF",
        text="#2A2A2A",
        accent="#0A8A7A",
        text_secondary="#6A6A7A",
    ),
    PresentationMood.CALM_MEDICAL: ColorPalette(
        background="#FAFAFA",
        surface="#FFFFFF",
        text="#2A2A2A",
        accent="#2E8B8B",
        text_secondary="#6A7A7A",
    ),
    PresentationMood.NATURAL: ColorPalette(
        background="#F5F2E8",
        surface="#FFFFFF",
        text="#2A2A2A",
        accent="#2D6B4F",
        text_secondary="#5A6B5A",
    ),
    PresentationMood.INSTITUTIONAL: ColorPalette(
        background="#FAF8F5",
        surface="#FFFFFF",
        text="#2A2A2A",
        accent="#1A3A5C",
        text_secondary="#5A6A7A",
    ),
}

# Each pair: (heading_font, body_font). All fonts must support the
# Karakalpak / Uzbek diacritics demanded by R50 (ń, ǵ, ú, ó, á, ı, ş, ñ);
# Noto Sans / Noto Serif and Inter are the safe defaults.
_DEFAULT_FONTS: Final[dict[PresentationMood, tuple[str, str]]] = {
    PresentationMood.WARM_HISTORICAL: ("Noto Serif", "Noto Sans"),
    PresentationMood.BOLD_TECHNICAL: ("Inter", "Inter"),
    PresentationMood.CLEAN_PROFESSIONAL: ("Inter", "Inter"),
    PresentationMood.CALM_MEDICAL: ("Noto Sans", "Noto Sans"),
    PresentationMood.NATURAL: ("Noto Serif", "Noto Sans"),
    PresentationMood.INSTITUTIONAL: ("Noto Serif", "Noto Sans"),
}


# R23: every AI image in a deck shares the prefix so the deck does not
# mix an oil-painting slide with a stock-photo slide. Mood-specific
# prefixes preserve domain fit (R22).
_IMAGE_STYLE_PREFIXES: Final[dict[PresentationMood, str]] = {
    PresentationMood.WARM_HISTORICAL: (
        "18th-century oil painting style, warm earth tones, museum quality, "
        "period-appropriate, rich golden lighting"
    ),
    PresentationMood.BOLD_TECHNICAL: (
        "technical diagram, dark background, red-orange accent lines, clean vector style, "
        "high contrast, engineering blueprint aesthetic"
    ),
    PresentationMood.CLEAN_PROFESSIONAL: (
        "clean modern photography, soft natural lighting, neutral tones, professional, "
        "minimal composition"
    ),
    PresentationMood.CALM_MEDICAL: (
        "medical illustration, clean white background, precise linework, "
        "anatomical accuracy, clinical blue-green accents"
    ),
    PresentationMood.NATURAL: (
        "nature photography, warm golden hour lighting, organic textures, earth tones, "
        "ecological subject matter"
    ),
    PresentationMood.INSTITUTIONAL: (
        "architectural photography, institutional interiors, marble and wood textures, "
        "formal composition, warm neutral tones"
    ),
}


_MOOD_DEFAULT_TREATMENT: Final[dict[PresentationMood, BackgroundTreatment]] = {
    PresentationMood.WARM_HISTORICAL: BackgroundTreatment.LIGHT,
    PresentationMood.BOLD_TECHNICAL: BackgroundTreatment.DARK,
    PresentationMood.CLEAN_PROFESSIONAL: BackgroundTreatment.LIGHT,
    PresentationMood.CALM_MEDICAL: BackgroundTreatment.LIGHT,
    PresentationMood.NATURAL: BackgroundTreatment.LIGHT,
    PresentationMood.INSTITUTIONAL: BackgroundTreatment.LIGHT,
}


# Same domain → mood mapping the interview engine uses for defaults, kept
# in sync so the pass produces the same aesthetic the user previewed.
_DOMAIN_TO_MOOD: Final[dict[AcademicDomain, PresentationMood]] = {
    AcademicDomain.MEDICAL: PresentationMood.CALM_MEDICAL,
    AcademicDomain.ENGINEERING: PresentationMood.BOLD_TECHNICAL,
    AcademicDomain.COMPUTER_SCIENCE: PresentationMood.BOLD_TECHNICAL,
    AcademicDomain.ECONOMICS: PresentationMood.CLEAN_PROFESSIONAL,
    AcademicDomain.LEGAL: PresentationMood.INSTITUTIONAL,
    AcademicDomain.ENVIRONMENTAL: PresentationMood.NATURAL,
    AcademicDomain.EDUCATION: PresentationMood.WARM_HISTORICAL,
    AcademicDomain.AGRICULTURE: PresentationMood.NATURAL,
    AcademicDomain.SOCIAL_SCIENCES: PresentationMood.CLEAN_PROFESSIONAL,
    AcademicDomain.GENERAL: PresentationMood.CLEAN_PROFESSIONAL,
}


# Decorative (script/display) fonts are reserved for the warm-historical
# mood only — R02 permits a third font on at most two slides per deck.
_DECORATIVE_FONTS: Final[dict[PresentationMood, str | None]] = {
    PresentationMood.WARM_HISTORICAL: "Noto Serif Display",
    PresentationMood.BOLD_TECHNICAL: None,
    PresentationMood.CLEAN_PROFESSIONAL: None,
    PresentationMood.CALM_MEDICAL: None,
    PresentationMood.NATURAL: None,
    PresentationMood.INSTITUTIONAL: None,
}


class DesignDirectionPass:
    """Deterministic mapping from interview + content to a design spec.

    Stateless apart from the injected :class:`DomainDetector`. A single
    instance can be reused across projects.
    """

    def __init__(self, domain_detector: DomainDetector | None = None) -> None:
        self._domain_detector = domain_detector if domain_detector is not None else DomainDetector()

    def generate(
        self,
        interview: PresentationInterviewAnswers,
        claims: list[SourceClaimCreate],
        chunks: list[SourceChunkCreate],
        source_metadata: list[SourceMetadataExtracted],
    ) -> DesignDirectionSpec:
        """Return the design direction for one deck.

        The mood is taken from ``interview.mood_override`` when supplied;
        otherwise the domain detector runs over the content and the
        resulting :class:`AcademicDomain` is mapped onto a mood via
        :data:`_DOMAIN_TO_MOOD`. Palette, fonts, decorative font and
        image style prefix all follow from the mood deterministically.
        ``background_treatment`` honours the interview override and
        inverts the palette when the user picked the opposite polarity.
        """

        mood = self._resolve_mood(interview, claims, chunks, source_metadata)
        treatment = self._resolve_treatment(interview, mood)
        palette = self._resolve_palette(mood, treatment)
        heading_font, body_font = _DEFAULT_FONTS[mood]
        decorative_font = _DECORATIVE_FONTS[mood]
        image_style_prefix = _IMAGE_STYLE_PREFIXES[mood]

        return DesignDirectionSpec(
            mood=mood,
            palette=palette,
            heading_font=heading_font,
            body_font=body_font,
            decorative_font=decorative_font,
            image_style_prefix=image_style_prefix,
            background_treatment=treatment,
        )

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    def _resolve_mood(
        self,
        interview: PresentationInterviewAnswers,
        claims: list[SourceClaimCreate],
        chunks: list[SourceChunkCreate],
        source_metadata: list[SourceMetadataExtracted],
    ) -> PresentationMood:
        if interview.mood_override is not None:
            return interview.mood_override
        detection = self._domain_detector.detect_domains(
            claims=claims,
            chunks=chunks,
            outline=None,
            source_metadata=source_metadata,
        )
        return _DOMAIN_TO_MOOD.get(detection.primary_domain, PresentationMood.CLEAN_PROFESSIONAL)

    @staticmethod
    def _resolve_treatment(
        interview: PresentationInterviewAnswers,
        mood: PresentationMood,
    ) -> BackgroundTreatment:
        if interview.background_treatment is not None:
            return interview.background_treatment
        return _MOOD_DEFAULT_TREATMENT[mood]

    @staticmethod
    def _resolve_palette(
        mood: PresentationMood,
        treatment: BackgroundTreatment,
    ) -> ColorPalette:
        base = _DEFAULT_PALETTES[mood]
        if treatment is _MOOD_DEFAULT_TREATMENT[mood]:
            return base
        return _invert_palette(base)


def _invert_palette(palette: ColorPalette) -> ColorPalette:
    """Swap polarity-bearing fields while keeping the accent fixed.

    The renderer pairs ``background`` against ``text`` and ``surface``
    against ``text_secondary``; swapping each pair preserves the contrast
    ratio (since the same two colours just trade roles) while flipping
    the deck from dark to light or vice-versa. The accent does not move:
    it is meant to read as the same hue regardless of polarity (R12 +
    R13: ≤10% of surface area, semantic colour).
    """

    return ColorPalette(
        background=palette.text,
        surface=palette.text_secondary,
        text=palette.background,
        accent=palette.accent,
        text_secondary=palette.surface,
    )
