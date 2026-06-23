"""Behaviour tests for :class:`DesignDirectionPass`.

The pass now has two paths: a generative Sonnet call that derives a
bespoke palette per deck, and the deterministic six-mood table retained
as a typed fallback. The deterministic tests exercise
``_generate_deterministic`` directly; the generative tests drive
``generate`` with a stubbed LLM and assert it returns the bespoke output
when valid and falls back to the table when the LLM output is unusable.
"""

from __future__ import annotations

import json
import re

import pytest

from packages.core.enums import (
    BackgroundTreatment,
    ClaimStrength,
    ClaimType,
    PresentationMood,
)
from packages.core.gemini import GEMINI_FLASH_3_5_MODEL
from packages.core.llm import LLMResponse
from packages.core.models.presentation import (
    DesignDirectionSpec,
    PresentationInterviewAnswers,
)
from packages.core.models.source import SourceClaimCreate
from packages.presentation.design_direction import (
    _DEFAULT_PALETTES,
    DesignDirectionPass,
)

_HEX_RE = re.compile(r"^#[0-9A-F]{6}$")


# ---------------------------------------------------------------------------
# Stub LLM (mirrors tests/unit/test_editorial_pass.py)
# ---------------------------------------------------------------------------


class _StubGemini:
    """Stand-in returning scripted text responses in order."""

    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, str]] = []

    async def complete(
        self,
        system: str,
        user: str,
        model: str = GEMINI_FLASH_3_5_MODEL,
        max_tokens: int = 2000,
        temperature: float = 0.0,
    ) -> LLMResponse:
        self.calls.append((system, user))
        if not self.responses:
            raise RuntimeError("LLM stub ran out of scripted responses")
        return LLMResponse(
            content=self.responses.pop(0),
            model=model,
            input_tokens=100,
            output_tokens=80,
            latency_ms=5,
            estimated_cost_usd=0.0001,
        )


def _design_json(
    *,
    mood: str = "bold_technical",
    background: str = "#0E1A1C",
    surface: str = "#16292B",
    text: str = "#EAF2F1",
    accent: str = "#FF6A3D",
    text_secondary: str = "#8FA8A6",
    heading_font: str = "IBM Plex Sans",
    body_font: str = "IBM Plex Sans",
    decorative_font: str | None = None,
    image_style_prefix: str = "industrial photography, cool slate tones, no text in image",
) -> str:
    """Build a design-direction JSON payload as the LLM would emit it."""

    return json.dumps(
        {
            "mood": mood,
            "palette": {
                "background": background,
                "surface": surface,
                "text": text,
                "accent": accent,
                "text_secondary": text_secondary,
            },
            "heading_font": heading_font,
            "body_font": body_font,
            "decorative_font": decorative_font,
            "image_style_prefix": image_style_prefix,
        }
    )


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


def _engineering_claims_alt() -> list[SourceClaimCreate]:
    """A second, distinct engineering topic — same domain, different subject."""

    return [
        _claim("Supercritical CO2 cycles improved datacenter cooling efficiency markedly."),
        _claim("Heat-exchanger geometry optimization reduced thermal resistance in the loop."),
        _claim("Turbine and compressor design governed the power system's overall efficiency."),
        _claim("Sensor-driven control of the coolant circuit stabilised the thermal load."),
        _claim("Computational fluid simulation validated the radiator prototype performance."),
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


# ---------------------------------------------------------------------------
# Deterministic fallback: mood override paths
# ---------------------------------------------------------------------------


def test_deterministic_warm_historical() -> None:
    pass_ = DesignDirectionPass()
    result = pass_._generate_deterministic(
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


def test_deterministic_bold_technical() -> None:
    pass_ = DesignDirectionPass()
    result = pass_._generate_deterministic(
        interview=_interview(mood_override=PresentationMood.BOLD_TECHNICAL),
        claims=[],
        chunks=[],
        source_metadata=[],
    )
    assert result.mood is PresentationMood.BOLD_TECHNICAL
    assert result.palette.background == "#0D0D12"
    assert result.palette.accent == "#E8553A"
    assert result.background_treatment is BackgroundTreatment.DARK


def test_deterministic_all_moods_have_palettes() -> None:
    pass_ = DesignDirectionPass()
    for mood in PresentationMood:
        result = pass_._generate_deterministic(
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
# Deterministic fallback: auto-detect mood
# ---------------------------------------------------------------------------


def test_deterministic_auto_detect_mood_from_medical_claims() -> None:
    pass_ = DesignDirectionPass()
    result = pass_._generate_deterministic(
        interview=_interview(),
        claims=_medical_claims(),
        chunks=[],
        source_metadata=[],
    )
    assert result.mood is PresentationMood.CALM_MEDICAL


def test_deterministic_auto_detect_mood_from_engineering_claims() -> None:
    pass_ = DesignDirectionPass()
    result = pass_._generate_deterministic(
        interview=_interview(),
        claims=_engineering_claims(),
        chunks=[],
        source_metadata=[],
    )
    assert result.mood is PresentationMood.BOLD_TECHNICAL


def test_deterministic_auto_detect_falls_back_to_clean_professional_for_empty_content() -> None:
    pass_ = DesignDirectionPass()
    result = pass_._generate_deterministic(
        interview=_interview(),
        claims=[],
        chunks=[],
        source_metadata=[],
    )
    assert result.mood is PresentationMood.CLEAN_PROFESSIONAL


# ---------------------------------------------------------------------------
# Deterministic fallback: background treatment override
# ---------------------------------------------------------------------------


def test_deterministic_background_treatment_override_inverts_palette() -> None:
    pass_ = DesignDirectionPass()
    default = pass_._generate_deterministic(
        interview=_interview(mood_override=PresentationMood.BOLD_TECHNICAL),
        claims=[],
        chunks=[],
        source_metadata=[],
    )
    overridden = pass_._generate_deterministic(
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


def test_deterministic_background_treatment_matching_default_keeps_palette() -> None:
    pass_ = DesignDirectionPass()
    result = pass_._generate_deterministic(
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
# Deterministic fallback: image style prefix + decorative font
# ---------------------------------------------------------------------------


def test_deterministic_image_style_prefix_matches_mood() -> None:
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
        result = pass_._generate_deterministic(
            interview=_interview(mood_override=mood),
            claims=[],
            chunks=[],
            source_metadata=[],
        )
        assert keyword in result.image_style_prefix.lower()


def test_deterministic_decorative_font_only_for_historical() -> None:
    pass_ = DesignDirectionPass()
    historical = pass_._generate_deterministic(
        interview=_interview(mood_override=PresentationMood.WARM_HISTORICAL),
        claims=[],
        chunks=[],
        source_metadata=[],
    )
    technical = pass_._generate_deterministic(
        interview=_interview(mood_override=PresentationMood.BOLD_TECHNICAL),
        claims=[],
        chunks=[],
        source_metadata=[],
    )
    assert historical.decorative_font is not None
    assert technical.decorative_font is None


def test_deterministic_palette_contrast_ratio_meets_wcag_aa() -> None:
    pass_ = DesignDirectionPass()
    for mood in PresentationMood:
        spec = pass_._generate_deterministic(
            interview=_interview(mood_override=mood),
            claims=[],
            chunks=[],
            source_metadata=[],
        )
        ratio = _contrast_ratio(spec.palette.text, spec.palette.background)
        assert ratio >= 4.5, f"{mood}: text/background contrast {ratio:.2f} < 4.5"


# ---------------------------------------------------------------------------
# Generative path: bespoke palette
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_uses_bespoke_llm_palette() -> None:
    bespoke_bg = "#0E1A1C"
    stub = _StubGemini([_design_json(background=bespoke_bg, accent="#FF6A3D")])
    pass_ = DesignDirectionPass(gemini=stub)  # type: ignore[arg-type]

    result = await pass_.generate(
        interview=_interview(),
        claims=_engineering_claims(),
        chunks=[],
        source_metadata=[],
    )

    # The bespoke palette must win over the deterministic table entry.
    assert result.palette.background == bespoke_bg
    assert (
        result.palette.background != _DEFAULT_PALETTES[PresentationMood.BOLD_TECHNICAL].background
    )
    assert result.palette.accent == "#FF6A3D"
    assert result.mood is PresentationMood.BOLD_TECHNICAL
    assert result.background_treatment is BackgroundTreatment.DARK
    assert len(stub.calls) == 1  # one call, no retry needed


@pytest.mark.asyncio
async def test_generate_two_topics_same_domain_differ() -> None:
    # Both topics are engineering, so the deterministic table would hand
    # them an IDENTICAL palette. The generative pass must produce different
    # palettes, proving it is no longer a lookup table.
    stub_a = _StubGemini([_design_json(background="#0E1A1C", accent="#FF6A3D")])
    stub_b = _StubGemini([_design_json(background="#241026", accent="#C77DFF")])

    result_a = await DesignDirectionPass(gemini=stub_a).generate(  # type: ignore[arg-type]
        interview=_interview(),
        claims=_engineering_claims(),
        chunks=[],
        source_metadata=[],
    )
    result_b = await DesignDirectionPass(gemini=stub_b).generate(  # type: ignore[arg-type]
        interview=_interview(),
        claims=_engineering_claims_alt(),
        chunks=[],
        source_metadata=[],
    )

    assert result_a.palette.background != result_b.palette.background
    assert result_a.palette.accent != result_b.palette.accent


@pytest.mark.asyncio
async def test_generate_retries_then_succeeds() -> None:
    good = _design_json(background="#0E1A1C")
    stub = _StubGemini(["not json at all", good])
    pass_ = DesignDirectionPass(gemini=stub)  # type: ignore[arg-type]

    result = await pass_.generate(
        interview=_interview(),
        claims=_engineering_claims(),
        chunks=[],
        source_metadata=[],
    )

    assert result.palette.background == "#0E1A1C"
    assert len(stub.calls) == 2  # first failed, retry succeeded


# ---------------------------------------------------------------------------
# Generative path: fallback to deterministic on bad output
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_falls_back_on_invalid_json() -> None:
    stub = _StubGemini(["this is not json", "still not json"])
    pass_ = DesignDirectionPass(gemini=stub)  # type: ignore[arg-type]

    result = await pass_.generate(
        interview=_interview(mood_override=PresentationMood.WARM_HISTORICAL),
        claims=[],
        chunks=[],
        source_metadata=[],
    )

    # Falls back to the deterministic table entry, still a valid spec.
    assert isinstance(result, DesignDirectionSpec)
    assert result.mood is PresentationMood.WARM_HISTORICAL
    assert result.palette.background == "#F5F0E8"
    assert len(stub.calls) == 2  # tried once, retried once, then fell back


@pytest.mark.asyncio
async def test_generate_falls_back_on_low_contrast() -> None:
    # text #888888 on background #999999 is ~1.2:1 — well below WCAG AA.
    low_contrast = _design_json(
        background="#999999",
        surface="#AAAAAA",
        text="#888888",
        accent="#777777",
        text_secondary="#808080",
    )
    stub = _StubGemini([low_contrast, low_contrast])
    pass_ = DesignDirectionPass(gemini=stub)  # type: ignore[arg-type]

    result = await pass_.generate(
        interview=_interview(mood_override=PresentationMood.WARM_HISTORICAL),
        claims=[],
        chunks=[],
        source_metadata=[],
    )

    # Low-contrast palette rejected; deterministic fallback used instead.
    assert result.palette.background == "#F5F0E8"
    assert result.palette.text == "#2A2A2A"
    assert _contrast_ratio(result.palette.text, result.palette.background) >= 4.5


@pytest.mark.asyncio
async def test_generate_falls_back_on_unsafe_font() -> None:
    unsafe = _design_json(heading_font="Comic Sans", body_font="Comic Sans")
    stub = _StubGemini([unsafe, unsafe])
    pass_ = DesignDirectionPass(gemini=stub)  # type: ignore[arg-type]

    result = await pass_.generate(
        interview=_interview(mood_override=PresentationMood.BOLD_TECHNICAL),
        claims=[],
        chunks=[],
        source_metadata=[],
    )

    # Unsafe font rejected; deterministic fallback (Inter) used instead.
    assert result.heading_font == "Inter"
    assert result.palette.background == "#0D0D12"


@pytest.mark.asyncio
async def test_generate_falls_back_when_llm_raises() -> None:
    stub = _StubGemini([])  # empty → complete() raises RuntimeError
    pass_ = DesignDirectionPass(gemini=stub)  # type: ignore[arg-type]

    result = await pass_.generate(
        interview=_interview(mood_override=PresentationMood.NATURAL),
        claims=[],
        chunks=[],
        source_metadata=[],
    )

    assert isinstance(result, DesignDirectionSpec)
    assert result.mood is PresentationMood.NATURAL
    assert result.palette.background == "#F5F2E8"
