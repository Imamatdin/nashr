"""Behaviour tests for source-informed image generation.

The image client is injected with stub fns (no SDK, no network). The key
guarantees: a relevant source figure INFORMS the generation prompt (its
understanding appears in the prompt), but the output bytes are the GENERATED
image, never the source figure's pixels.
"""

from __future__ import annotations

import pytest

from packages.core.enums import (
    BackgroundTreatment,
    ImageSubjectType,
    PresentationMood,
)
from packages.core.gemini_image import GeminiImageClient, GeneratedImage
from packages.core.models.presentation import ColorPalette, DesignDirectionSpec
from packages.core.models.source import SourceFigure
from packages.presentation.image_generation import (
    GeneratedImageResolver,
    build_generation_prompt,
    find_relevant_figure,
)

_GENERATED = b"GENERATED-IMAGE-BYTES"
_SOURCE = b"SOURCE-FIGURE-PIXELS"


def _design() -> DesignDirectionSpec:
    return DesignDirectionSpec(
        mood=PresentationMood.BOLD_TECHNICAL,
        palette=ColorPalette(
            background="#0E1A1C",
            surface="#15262A",
            text="#F5F0E8",
            accent="#E8773A",
            text_secondary="#A89F91",
        ),
        heading_font="Space Grotesk",
        body_font="Inter",
        decorative_font=None,
        image_style_prefix="industrial photography, cool slate and teal tones, no text in image",
        background_treatment=BackgroundTreatment.DARK,
    )


def _figure(caption: str, context: str = "") -> SourceFigure:
    return SourceFigure(
        page_number=1,
        data=_SOURCE,
        content_type="image/png",
        width=600,
        height=400,
        caption=caption,
        context=context,
    )


# ---------------------------------------------------------------------------
# find_relevant_figure
# ---------------------------------------------------------------------------


def test_find_relevant_figure_matches_on_topic_overlap() -> None:
    figures = [
        _figure("Figure 1: supercritical CO2 cooling loop for a server rack"),
        _figure("Figure 2: mangrove carbon sequestration in tidal wetlands"),
    ]
    match = find_relevant_figure("a server rack with a cooling manifold", figures)
    assert match is figures[0]


def test_find_relevant_figure_returns_none_below_threshold() -> None:
    figures = [_figure("Figure 1: mangrove carbon sequestration in wetlands")]
    assert find_relevant_figure("a server rack", figures) is None


def test_find_relevant_figure_handles_empty() -> None:
    assert find_relevant_figure("anything", []) is None


# ---------------------------------------------------------------------------
# build_generation_prompt
# ---------------------------------------------------------------------------


def test_prompt_includes_style_prefix_and_no_text_clause() -> None:
    prompt = build_generation_prompt("a steam turbine rotor", ImageSubjectType.OBJECT, _design())
    assert "industrial photography" in prompt  # deck cohesion style
    assert "steam turbine rotor" in prompt
    assert "isolated" in prompt  # object framing, not full-bleed
    assert "no text" in prompt


def test_prompt_scene_uses_full_bleed_framing() -> None:
    prompt = build_generation_prompt("a datacenter hall", ImageSubjectType.SCENE, _design())
    assert "full-bleed" in prompt


def test_prompt_folds_in_source_understanding_when_present() -> None:
    prompt = build_generation_prompt(
        "a server rack",
        ImageSubjectType.OBJECT,
        _design(),
        source_understanding="a 42U rack with rear-door liquid cooling",
    )
    assert "42U rack with rear-door liquid cooling" in prompt
    assert "reference material" in prompt


# ---------------------------------------------------------------------------
# GeneratedImageResolver
# ---------------------------------------------------------------------------


def _client(
    *,
    caption: str | None = None,
    caption_raises: bool = False,
    generate_raises: bool = False,
    recorder: list[str] | None = None,
) -> GeminiImageClient:
    async def gen(*, model: str, prompt: str) -> GeneratedImage:
        if recorder is not None:
            recorder.append(prompt)
        if generate_raises:
            raise RuntimeError("model unavailable")
        return GeneratedImage(data=_GENERATED, content_type="image/png")

    async def cap(*, model: str, data: bytes, mime_type: str, instruction: str) -> str:
        if caption_raises:
            raise RuntimeError("vision unavailable")
        return caption or ""

    return GeminiImageClient(generate_image_fn=gen, caption_fn=cap)


@pytest.mark.asyncio
async def test_resolve_generates_styled_image_without_source() -> None:
    recorder: list[str] = []
    resolver = GeneratedImageResolver(image_client=_client(recorder=recorder))
    result = await resolver.resolve("a server rack", ImageSubjectType.OBJECT, _design(), figures=[])
    assert result is not None
    assert result.data == _GENERATED
    # No source → prompt is not source-informed.
    assert "reference material" not in recorder[0]


@pytest.mark.asyncio
async def test_resolve_is_informed_by_relevant_source_but_never_copies_pixels() -> None:
    recorder: list[str] = []
    figures = [_figure("Figure 1: a server rack with liquid cooling manifolds")]
    resolver = GeneratedImageResolver(
        image_client=_client(caption="a 42U server rack with liquid cooling", recorder=recorder)
    )
    result = await resolver.resolve(
        "a server rack", ImageSubjectType.OBJECT, _design(), figures=figures
    )
    assert result is not None
    # The generation prompt reflects the source understanding (informed)...
    assert "42U server rack with liquid cooling" in recorder[0]
    assert "reference material" in recorder[0]
    # ...but the output is the GENERATED image, never the source pixels.
    assert result.data == _GENERATED
    assert result.data != _SOURCE


@pytest.mark.asyncio
async def test_resolve_falls_back_to_extracted_caption_when_vision_fails() -> None:
    recorder: list[str] = []
    figures = [_figure("Figure 1: a centrifugal pump cross-section")]
    resolver = GeneratedImageResolver(image_client=_client(caption_raises=True, recorder=recorder))
    result = await resolver.resolve(
        "a centrifugal pump", ImageSubjectType.OBJECT, _design(), figures=figures
    )
    assert result is not None
    # Vision failed, but the figure's extracted caption still informs the prompt.
    assert "centrifugal pump cross-section" in recorder[0]


@pytest.mark.asyncio
async def test_resolve_abstains_when_generation_fails() -> None:
    resolver = GeneratedImageResolver(image_client=_client(generate_raises=True))
    result = await resolver.resolve("a server rack", ImageSubjectType.OBJECT, _design(), figures=[])
    assert result is None


@pytest.mark.asyncio
async def test_resolve_abstains_on_empty_prompt() -> None:
    resolver = GeneratedImageResolver(image_client=_client())
    result = await resolver.resolve("   ", ImageSubjectType.OBJECT, _design(), figures=[])
    assert result is None
