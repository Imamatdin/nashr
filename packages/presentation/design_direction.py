"""Design Direction Pass for the presentation pipeline.

The pass is the "creative director" of the pipeline. It maps a deck's
specific topic onto an aesthetic specification (palette, fonts, image
style prefix) that the rest of the pipeline treats as immutable.

The palette is produced by a single Sonnet call so every deck gets a
*bespoke* colour scheme derived from its subject matter rather than a
hardcoded table entry (DESIGN-LANGUAGE.md R43: "if the output looks like
it came from a theme picker, it fails"). The deterministic six-mood table
is retained as a typed fallback — :meth:`DesignDirectionPass.generate`
returns it whenever the LLM call fails, returns unparseable JSON, or
returns output that violates the safe-font set (R50) or WCAG AA contrast
(R12). Determinism on re-runs is bounded by a low temperature plus that
fallback, not by avoiding the LLM.

The 300-line CLAUDE.md cap is intentionally exceeded: the generative pass
and its deterministic fallback produce the SAME output contract
(:class:`DesignDirectionSpec`) and share the mood/treatment resolution
helpers; splitting them would fragment one coherent operation.

See :file:`packages/presentation/DESIGN-LANGUAGE.md` rules R12 (palette
selection), R13 (60-30-10), R15 (light/dark coexistence), R23 (image
style consistency), R43 (bespoke palette), R50 (font glyph coverage).
"""

from __future__ import annotations

import json
import logging
from typing import Any, Final

from pydantic import BaseModel, ConfigDict, ValidationError

from packages.core.enums import (
    BackgroundTreatment,
    PresentationMood,
)
from packages.core.llm import LLMClient
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
from packages.core.prompts import (
    DESIGN_DIRECTION_RETRY_SUFFIX,
    DESIGN_DIRECTION_SYSTEM,
    DESIGN_DIRECTION_USER,
)
from packages.suggestions.domain_detector import DomainDetector

logger = logging.getLogger(__name__)

SONNET_MODEL: Final[str] = "claude-sonnet-4-6"

# Low enough that re-runs of the same deck stay close, high enough that
# the model can derive a topic-specific palette instead of collapsing to
# one canonical answer per domain. The deterministic fallback handles the
# residual jitter risk.
DESIGN_TEMPERATURE: Final[float] = 0.4
DESIGN_MAX_TOKENS: Final[int] = 1_500

# WCAG AA minimum contrast ratio for normal-size text.
WCAG_AA_CONTRAST: Final[float] = 4.5

# Fonts the LLM may choose from. Every entry covers Latin Extended-A/-B,
# i.e. the Karakalpak / Uzbek diacritics R50 demands (ń ǵ ú ó á ı ş ñ).
# Any font outside this set is rejected and the pass falls back.
_SAFE_FONT_LIST: Final[tuple[str, ...]] = (
    "Noto Serif",
    "Noto Sans",
    "Noto Serif Display",
    "Inter",
    "Source Serif 4",
    "IBM Plex Sans",
    "IBM Plex Serif",
    "Lora",
    "EB Garamond",
)
_SAFE_FONTS: Final[frozenset[str]] = frozenset(_SAFE_FONT_LIST)

# R12 starting-point moods per domain, embedded in the system prompt. The
# LLM treats these as a starting point, not the answer (R43).
_PALETTE_DECISION_TREE: Final[str] = (
    "  - History / education -> warm_historical: warm off-white background, brown/gold accent\n"
    "  - Engineering / technical -> bold_technical: dark background, red-orange accent\n"
    "  - Professional / business -> clean_professional: light-grey background, teal accent\n"
    "  - Medical / health -> calm_medical: white background, blue-green accent\n"
    "  - Environmental -> natural: cream background, forest-green accent\n"
    "  - Legal / policy -> institutional: warm-white background, navy accent"
)

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


# ---------------------------------------------------------------------------
# Parsing schema for the LLM response
# ---------------------------------------------------------------------------


class _LLMPalette(BaseModel):
    """Permissive shape of the palette object in the design LLM response."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    background: str = ""
    surface: str = ""
    text: str = ""
    accent: str = ""
    text_secondary: str = ""


class _LLMDesignDirection(BaseModel):
    """Permissive shape of the whole design-direction LLM response."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    mood: PresentationMood | None = None
    palette: _LLMPalette | None = None
    heading_font: str = ""
    body_font: str = ""
    decorative_font: str | None = None
    image_style_prefix: str = ""


class DesignDirectionPass:
    """Generate a bespoke :class:`DesignDirectionSpec` for one deck.

    The primary path is one Sonnet call that derives a topic-specific
    palette and typography. When that call fails or yields invalid
    output, the pass falls back to the deterministic six-mood table via
    :meth:`_generate_deterministic`. Stateless apart from the injected
    :class:`DomainDetector` and lazily-constructed :class:`LLMClient`; a
    single instance can be reused across projects.
    """

    def __init__(
        self,
        domain_detector: DomainDetector | None = None,
        llm: LLMClient | None = None,
    ) -> None:
        self._domain_detector = domain_detector if domain_detector is not None else DomainDetector()
        self._llm = llm

    def _get_llm(self) -> LLMClient:
        if self._llm is None:
            self._llm = LLMClient()
        return self._llm

    async def generate(
        self,
        interview: PresentationInterviewAnswers,
        claims: list[SourceClaimCreate],
        chunks: list[SourceChunkCreate],
        source_metadata: list[SourceMetadataExtracted],
    ) -> DesignDirectionSpec:
        """Return the design direction for one deck.

        Detects the domain (which seeds both the LLM hint and the fallback
        mood), resolves the dominant background treatment, then asks Sonnet
        for a bespoke palette + typography. The LLM output is validated for
        safe-set fonts (R50) and WCAG AA contrast (R12); any failure — bad
        JSON, a font outside the safe set, or a low-contrast palette — falls
        back to :meth:`_generate_deterministic`, which is byte-for-byte the
        old deterministic mapping.
        """

        domain = self._detect_domain(claims, chunks, source_metadata)
        fallback_mood = self._resolve_mood(interview, domain)
        treatment = self._resolve_treatment(interview, fallback_mood)

        system = DESIGN_DIRECTION_SYSTEM.format(
            palette_decision_tree=_PALETTE_DECISION_TREE,
            safe_fonts=_format_safe_fonts(),
            mood_values=", ".join(m.value for m in PresentationMood),
        )
        user = DESIGN_DIRECTION_USER.format(
            domain=domain.value,
            fallback_mood=fallback_mood.value,
            treatment=treatment.value,
            audience=interview.audience.value,
            language=interview.language.value,
            topic_summary=_build_topic_summary(claims, chunks, source_metadata),
        )

        spec: DesignDirectionSpec | None = None
        try:
            spec = await self._call_design_with_retry(system, user, treatment)
        except Exception as exc:  # any LLM failure falls back to the deterministic table
            logger.warning(
                "design_direction_llm_failed",
                extra={"error_type": type(exc).__name__, "error": str(exc)[:200]},
            )

        if spec is not None:
            return spec

        logger.warning("design_direction_fallback_to_deterministic")
        return self._generate_deterministic(interview, claims, chunks, source_metadata)

    async def _call_design_with_retry(
        self,
        system: str,
        user: str,
        treatment: BackgroundTreatment,
    ) -> DesignDirectionSpec | None:
        """One Sonnet call; on bad/invalid output, retry once with a stricter suffix."""

        first = await self._get_llm().complete(
            system=system,
            user=user,
            model=SONNET_MODEL,
            max_tokens=DESIGN_MAX_TOKENS,
            temperature=DESIGN_TEMPERATURE,
        )
        spec = _parse_and_validate(first.content, treatment)
        if spec is not None:
            return spec
        retry = await self._get_llm().complete(
            system=system,
            user=user + DESIGN_DIRECTION_RETRY_SUFFIX,
            model=SONNET_MODEL,
            max_tokens=DESIGN_MAX_TOKENS,
            temperature=DESIGN_TEMPERATURE,
        )
        return _parse_and_validate(retry.content, treatment)

    # ------------------------------------------------------------------
    # Deterministic fallback (the former generate() body, unchanged)
    # ------------------------------------------------------------------

    def _generate_deterministic(
        self,
        interview: PresentationInterviewAnswers,
        claims: list[SourceClaimCreate],
        chunks: list[SourceChunkCreate],
        source_metadata: list[SourceMetadataExtracted],
    ) -> DesignDirectionSpec:
        """Deterministic six-mood mapping used when the LLM path is unusable.

        The mood is taken from ``interview.mood_override`` when supplied;
        otherwise the domain detector runs over the content and the
        resulting :class:`AcademicDomain` is mapped onto a mood via
        :data:`_DOMAIN_TO_MOOD`. Palette, fonts, decorative font and
        image style prefix all follow from the mood deterministically.
        ``background_treatment`` honours the interview override and
        inverts the palette when the user picked the opposite polarity.
        """

        domain = self._detect_domain(claims, chunks, source_metadata)
        mood = self._resolve_mood(interview, domain)
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

    def _detect_domain(
        self,
        claims: list[SourceClaimCreate],
        chunks: list[SourceChunkCreate],
        source_metadata: list[SourceMetadataExtracted],
    ) -> AcademicDomain:
        detection = self._domain_detector.detect_domains(
            claims=claims,
            chunks=chunks,
            outline=None,
            source_metadata=source_metadata,
        )
        return detection.primary_domain

    @staticmethod
    def _resolve_mood(
        interview: PresentationInterviewAnswers,
        domain: AcademicDomain,
    ) -> PresentationMood:
        if interview.mood_override is not None:
            return interview.mood_override
        return _DOMAIN_TO_MOOD.get(domain, PresentationMood.CLEAN_PROFESSIONAL)

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


# ---------------------------------------------------------------------------
# Palette inversion (deterministic fallback)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Contrast helpers (WCAG relative luminance + ratio)
# ---------------------------------------------------------------------------


def _relative_luminance(hex_color: str) -> float:
    """Return the WCAG relative luminance of a ``#RRGGBB`` colour."""

    r = int(hex_color[1:3], 16) / 255.0
    g = int(hex_color[3:5], 16) / 255.0
    b = int(hex_color[5:7], 16) / 255.0

    def _channel(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    return 0.2126 * _channel(r) + 0.7152 * _channel(g) + 0.0722 * _channel(b)


def _contrast_ratio(fg: str, bg: str) -> float:
    """Return the WCAG contrast ratio between two ``#RRGGBB`` colours."""

    l1 = _relative_luminance(fg)
    l2 = _relative_luminance(bg)
    lighter, darker = max(l1, l2), min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


# ---------------------------------------------------------------------------
# LLM output parsing + validation
# ---------------------------------------------------------------------------


def _parse_and_validate(text: str, treatment: BackgroundTreatment) -> DesignDirectionSpec | None:
    """Parse a design-direction LLM response and validate it into a spec.

    Returns ``None`` (so the caller falls back) when the JSON is
    unparseable, the palette is missing/malformed, a font lies outside
    the R50 safe set, or the palette fails WCAG AA contrast.
    """

    parsed = _parse_design(text)
    if parsed is None:
        return None
    return _build_validated_spec(parsed, treatment)


def _parse_design(text: str) -> _LLMDesignDirection | None:
    """Decode a design-direction LLM response into a typed object."""

    obj = _try_parse_object(text)
    if obj is None:
        return None
    try:
        return _LLMDesignDirection.model_validate(obj)
    except ValidationError as exc:
        logger.warning("design_direction_invalid_schema", extra={"error": str(exc)[:200]})
        return None


def _build_validated_spec(
    parsed: _LLMDesignDirection,
    treatment: BackgroundTreatment,
) -> DesignDirectionSpec | None:
    """Validate parsed fields (palette, fonts, contrast) into a spec or ``None``."""

    if parsed.mood is None or parsed.palette is None:
        logger.warning("design_direction_missing_fields")
        return None

    p = parsed.palette
    if not all((p.background, p.surface, p.text, p.accent, p.text_secondary)):
        logger.warning("design_direction_incomplete_palette")
        return None
    try:
        palette = ColorPalette(
            background=p.background,
            surface=p.surface,
            text=p.text,
            accent=p.accent,
            text_secondary=p.text_secondary,
        )
    except ValidationError as exc:
        logger.warning("design_direction_bad_hex", extra={"error": str(exc)[:200]})
        return None

    heading_font = parsed.heading_font
    body_font = parsed.body_font
    decorative_font = (parsed.decorative_font or "").strip() or None
    if heading_font not in _SAFE_FONTS or body_font not in _SAFE_FONTS:
        logger.warning(
            "design_direction_unsafe_font",
            extra={"heading_font": heading_font, "body_font": body_font},
        )
        return None
    if decorative_font is not None and decorative_font not in _SAFE_FONTS:
        logger.warning("design_direction_unsafe_decorative_font", extra={"font": decorative_font})
        return None
    if not parsed.image_style_prefix:
        logger.warning("design_direction_missing_image_style")
        return None

    text_bg = _contrast_ratio(palette.text, palette.background)
    text_surface = _contrast_ratio(palette.text, palette.surface)
    if text_bg < WCAG_AA_CONTRAST or text_surface < WCAG_AA_CONTRAST:
        logger.warning(
            "design_direction_low_contrast",
            extra={
                "text_background": round(text_bg, 2),
                "text_surface": round(text_surface, 2),
            },
        )
        return None

    try:
        return DesignDirectionSpec(
            mood=parsed.mood,
            palette=palette,
            heading_font=heading_font,
            body_font=body_font,
            decorative_font=decorative_font,
            image_style_prefix=parsed.image_style_prefix,
            background_treatment=treatment,
        )
    except ValidationError as exc:
        logger.warning("design_direction_invalid_spec", extra={"error": str(exc)[:200]})
        return None


def _try_parse_object(text: str) -> dict[str, Any] | None:
    """Parse a JSON object from an LLM response that may include code fences."""

    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.lower().startswith("json"):
            stripped = stripped[4:].lstrip()
    try:
        loaded: Any = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    if isinstance(loaded, dict):
        result: dict[str, Any] = {str(k): v for k, v in loaded.items()}  # type: ignore[misc]
        return result
    return None


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------


def _format_safe_fonts() -> str:
    return "\n".join(f"  - {name}" for name in _SAFE_FONT_LIST)


def _build_topic_summary(
    claims: list[SourceClaimCreate],
    chunks: list[SourceChunkCreate],
    source_metadata: list[SourceMetadataExtracted],
) -> str:
    """Curate a compact topic brief for the design LLM call.

    Source titles and claim texts carry the topic signal the LLM needs to
    derive a bespoke palette; chunk excerpts are a last resort when no
    titles or claims exist so empty decks still get a topic-relevant brief.
    """

    lines: list[str] = []

    titles = [m.title.strip() for m in source_metadata if m.title and m.title.strip()]
    if titles:
        lines.append("SOURCE TITLES:")
        lines.extend(f"  - {t}" for t in titles[:5])
        lines.append("")

    claim_texts = [c.claim_text.strip() for c in claims if c.claim_text.strip()][:12]
    if claim_texts:
        lines.append("KEY CLAIMS:")
        lines.extend(f"  - {t}" for t in claim_texts)
        lines.append("")

    if not titles and not claim_texts:
        excerpts = [c.text.strip()[:200] for c in chunks if c.text.strip()][:3]
        if excerpts:
            lines.append("SOURCE EXCERPTS:")
            lines.extend(f"  - {e}" for e in excerpts)

    summary = "\n".join(lines).strip()
    return (
        summary or "(no specific source material; design for the detected domain in the abstract)"
    )
