"""Behaviour tests for :class:`DesignDirectionPass`.

The pass is pure Python: deterministic mood → aesthetic mapping with no
LLM call. Tests build small claim fixtures and assert on the structured
``DesignDirectionSpec`` output.
"""

from __future__ import annotations

import re

from packages.core.enums import (
    BackgroundTreatment,
    ClaimStrength,
    ClaimType,
    PresentationMood,
)
from packages.core.models.presentation import (
    DesignDirectionSpec,
    PresentationInterviewAnswers,
)
from packages.core.models.source import SourceClaimCreate
from packages.presentation.design_direction import DesignDirectionPass

_HEX_RE = re.compile(r"^#[0-9A-F]{6}$")


def _claim(text: str) -> SourceClaimCreate:
    return SourceClaimCreate(
        claim_text=text,
        strength=ClaimStrength.MODERATE,
        claim_type=ClaimType.GENERAL_FACT,
    )


def _medical_claims() -> list[SourceClaimCreate]:
    return [
        _claim("Clinical trials show patient diagnosis improves with biomarker screening."),
        _claim("Hospital readmission rates dropped after pharmaceutical review protocols."),
        _claim("The vaccine cohort had reduced morbidity in oncology pathology metrics."),
        _claim("Therapy adherence in chronic disease cohorts varies with mental health."),
        _claim("Surgery complication rates fell in the treatment patient cohort study."),
    ]


def _engineering_claims() -> list[SourceClaimCreate]:
    return [
        _claim("Finite element simulation of structural stress identified failure modes."),
        _claim("Optimization of the algorithm and circuit signal reduced electrical loss."),
        _claim("The control system used sensor data for actuator feedback in robotics."),
        _claim("Computational simulation of thermal load validated the design and prototype."),
        _claim("Automation of manufacture cut prototype iteration time across the system."),
    ]


def _interview(
    *,
    mood_override: PresentationMood | None = None,
    background_treatment: BackgroundTreatment | None = None,
) -> PresentationInterviewAnswers:
    return PresentationInterviewAnswers(
        mood_override=mood_override,
        background_treatment=background_treatment,
    )


# ---------------------------------------------------------------------------
# Mood override paths
# ---------------------------------------------------------------------------


def test_generate_warm_historical() -> None:
    pass_ = DesignDirectionPass()
    result = pass_.generate(
        interview=_interview(mood_override=PresentationMood.WARM_HISTORICAL),
        claims=[],
        chunks=[],
        source_metadata=[],
    )
    assert isinstance(result, DesignDirectionSpec)
    assert result.mood is PresentationMood.WARM_HISTORICAL
    assert result.palette.background == "#F5F0E8"
    assert result.heading_font == "Noto Serif"
    assert result.background_treatment is BackgroundTreatment.LIGHT


def test_generate_bold_technical() -> None:
    pass_ = DesignDirectionPass()
    result = pass_.generate(
        interview=_interview(mood_override=PresentationMood.BOLD_TECHNICAL),
        claims=[],
        chunks=[],
        source_metadata=[],
    )
    assert result.mood is PresentationMood.BOLD_TECHNICAL
    assert result.palette.background == "#0D0D12"
    assert result.palette.accent == "#E8553A"
    assert result.background_treatment is BackgroundTreatment.DARK


def test_generate_all_moods_have_palettes() -> None:
    pass_ = DesignDirectionPass()
    for mood in PresentationMood:
        result = pass_.generate(
            interview=_interview(mood_override=mood),
            claims=[],
            chunks=[],
            source_metadata=[],
        )
        for color in (
            result.palette.background,
            result.palette.surface,
            result.palette.text,
            result.palette.accent,
            result.palette.text_secondary,
        ):
            assert _HEX_RE.match(color), f"{mood}: {color} is not a valid hex"
        assert result.heading_font
        assert result.body_font
        assert result.image_style_prefix


# ---------------------------------------------------------------------------
# Auto-detect mood
# ---------------------------------------------------------------------------


def test_auto_detect_mood_from_medical_claims() -> None:
    pass_ = DesignDirectionPass()
    result = pass_.generate(
        interview=_interview(),
        claims=_medical_claims(),
        chunks=[],
        source_metadata=[],
    )
    assert result.mood is PresentationMood.CALM_MEDICAL


def test_auto_detect_mood_from_engineering_claims() -> None:
    pass_ = DesignDirectionPass()
    result = pass_.generate(
        interview=_interview(),
        claims=_engineering_claims(),
        chunks=[],
        source_metadata=[],
    )
    assert result.mood is PresentationMood.BOLD_TECHNICAL


def test_auto_detect_falls_back_to_clean_professional_for_empty_content() -> None:
    pass_ = DesignDirectionPass()
    result = pass_.generate(
        interview=_interview(),
        claims=[],
        chunks=[],
        source_metadata=[],
    )
    assert result.mood is PresentationMood.CLEAN_PROFESSIONAL


# ---------------------------------------------------------------------------
# Background treatment override
# ---------------------------------------------------------------------------


def test_background_treatment_override_inverts_palette() -> None:
    pass_ = DesignDirectionPass()
    default = pass_.generate(
        interview=_interview(mood_override=PresentationMood.BOLD_TECHNICAL),
        claims=[],
        chunks=[],
        source_metadata=[],
    )
    overridden = pass_.generate(
        interview=_interview(
            mood_override=PresentationMood.BOLD_TECHNICAL,
            background_treatment=BackgroundTreatment.LIGHT,
        ),
        claims=[],
        chunks=[],
        source_metadata=[],
    )
    assert default.background_treatment is BackgroundTreatment.DARK
    assert overridden.background_treatment is BackgroundTreatment.LIGHT
    assert default.palette.background != overridden.palette.background
    # The text/background roles should have swapped.
    assert overridden.palette.background == default.palette.text
    assert overridden.palette.text == default.palette.background
    assert overridden.palette.accent == default.palette.accent


def test_background_treatment_matching_default_keeps_palette() -> None:
    pass_ = DesignDirectionPass()
    result = pass_.generate(
        interview=_interview(
            mood_override=PresentationMood.WARM_HISTORICAL,
            background_treatment=BackgroundTreatment.LIGHT,
        ),
        claims=[],
        chunks=[],
        source_metadata=[],
    )
    # LIGHT is already the default for WARM_HISTORICAL, so no inversion.
    assert result.palette.background == "#F5F0E8"
    assert result.palette.text == "#2A2A2A"


# ---------------------------------------------------------------------------
# Image style prefix + decorative font
# ---------------------------------------------------------------------------


def test_image_style_prefix_matches_mood() -> None:
    pass_ = DesignDirectionPass()
    expectations = {
        PresentationMood.WARM_HISTORICAL: "oil painting",
        PresentationMood.BOLD_TECHNICAL: "technical diagram",
        PresentationMood.CLEAN_PROFESSIONAL: "clean modern",
        PresentationMood.CALM_MEDICAL: "medical illustration",
        PresentationMood.NATURAL: "nature photography",
        PresentationMood.INSTITUTIONAL: "architectural photography",
    }
    for mood, keyword in expectations.items():
        result = pass_.generate(
            interview=_interview(mood_override=mood),
            claims=[],
            chunks=[],
            source_metadata=[],
        )
        assert keyword in result.image_style_prefix.lower()


def test_decorative_font_only_for_historical() -> None:
    pass_ = DesignDirectionPass()
    historical = pass_.generate(
        interview=_interview(mood_override=PresentationMood.WARM_HISTORICAL),
        claims=[],
        chunks=[],
        source_metadata=[],
    )
    technical = pass_.generate(
        interview=_interview(mood_override=PresentationMood.BOLD_TECHNICAL),
        claims=[],
        chunks=[],
        source_metadata=[],
    )
    assert historical.decorative_font is not None
    assert technical.decorative_font is None


# ---------------------------------------------------------------------------
# Contrast (WCAG AA)
# ---------------------------------------------------------------------------


def _relative_luminance(hex_color: str) -> float:
    """Compute the WCAG relative luminance for a #RRGGBB string."""

    r = int(hex_color[1:3], 16) / 255.0
    g = int(hex_color[3:5], 16) / 255.0
    b = int(hex_color[5:7], 16) / 255.0

    def channel(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def _contrast_ratio(fg: str, bg: str) -> float:
    l1 = _relative_luminance(fg)
    l2 = _relative_luminance(bg)
    lighter, darker = max(l1, l2), min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


def test_palette_contrast_ratio_meets_wcag_aa() -> None:
    pass_ = DesignDirectionPass()
    for mood in PresentationMood:
        spec = pass_.generate(
            interview=_interview(mood_override=mood),
            claims=[],
            chunks=[],
            source_metadata=[],
        )
        ratio = _contrast_ratio(spec.palette.text, spec.palette.background)
        assert ratio >= 4.5, f"{mood}: text/background contrast {ratio:.2f} < 4.5"
