"""Behaviour tests for :class:`ImagePass` — the parallel image-resolution stage.

Resolvers and storage are injected fakes (no network, no SDK, no filesystem
side effects). The guarantees pinned here: fillable slots get urls, unfillable
slots abstain (stay null) and never fail the deck, resolution runs in PARALLEL,
the generated-image budget is respected, and CC-BY attribution lands in the
slide's speaker notes (no credits slide).
"""

from __future__ import annotations

import time
from pathlib import Path

import httpx
import pytest

from packages.core.enums import (
    AudienceType,
    BackgroundTreatment,
    ImageSubjectType,
    Language,
    PresentationMood,
    SlideType,
)
from packages.core.models.presentation import (
    ColorPalette,
    DeckSpec,
    DesignDirectionSpec,
    PersonItem,
    PresentationInterviewAnswers,
    SlideContent,
    SlideSpec,
    TimelineNode,
)
from packages.core.models.source import SourceFigure
from packages.presentation.image_pass import ImagePass
from packages.presentation.image_types import ImageAttribution, ResolvedImage

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeStorage:
    """Records uploads and hands back a short, stable url."""

    def __init__(self) -> None:
        self.uploaded: dict[str, tuple[bytes, str | None]] = {}

    async def upload(
        self, local_path: Path, remote_key: str, content_type: str | None = None
    ) -> str:
        self.uploaded[remote_key] = (Path(local_path).read_bytes(), content_type)
        return remote_key

    async def signed_url(self, remote_key: str, expires_in: int = 3600) -> str:
        return f"https://cdn.test/{remote_key}"


class _FakePortraits:
    def __init__(self, *, result: ResolvedImage | None, delay: float = 0.0) -> None:
        self._result = result
        self._delay = delay
        self.calls: list[str] = []

    async def resolve(
        self,
        client: httpx.AsyncClient,
        name: str,
        *,
        years: str | None = None,
        role: str | None = None,
        description: str | None = None,
    ) -> ResolvedImage | None:
        self.calls.append(name)
        if self._delay:
            import asyncio

            await asyncio.sleep(self._delay)
        return self._result


class _FakeGenerated:
    def __init__(self, *, result: ResolvedImage | None, delay: float = 0.0) -> None:
        self._result = result
        self._delay = delay
        self.calls: list[tuple[str, ImageSubjectType]] = []

    async def resolve(
        self,
        subject_prompt: str,
        subject_type: ImageSubjectType,
        design: DesignDirectionSpec,
        figures: list[SourceFigure],
    ) -> ResolvedImage | None:
        self.calls.append((subject_prompt, subject_type))
        if self._delay:
            import asyncio

            await asyncio.sleep(self._delay)
        return self._result


def _img(data: bytes = b"IMGDATA", attribution: ImageAttribution | None = None) -> ResolvedImage:
    return ResolvedImage(data=data, content_type="image/png", attribution=attribution)


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
        image_style_prefix="industrial photography, no text",
        background_treatment=BackgroundTreatment.DARK,
    )


def _deck(slides: list[SlideSpec]) -> DeckSpec:
    return DeckSpec(
        project_id="p-test",
        title="Supercritical CO2 cooling",
        subtitle="A datacenter story",
        language=Language.EN,
        design=_design(),
        interview=PresentationInterviewAnswers(audience=AudienceType.GRADUATE),
        slides=slides,
    )


def _slide(index: int, slide_type: SlideType, content: SlideContent) -> SlideSpec:
    return SlideSpec(slide_index=index, slide_type=slide_type, content=content)


def _no_http() -> httpx.AsyncClient:
    # A client the portrait fake never actually uses; constructed/closed only.
    return httpx.AsyncClient(transport=httpx.MockTransport(lambda _r: httpx.Response(204)))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fills_person_figure_and_background_slots() -> None:
    deck = _deck(
        [
            _slide(0, SlideType.TITLE_HERO, SlideContent(title="Supercritical CO2 cooling")),
            _slide(
                1,
                SlideType.GALLERY_PEOPLE,
                SlideContent(
                    title="Pioneers", people=[PersonItem(name="Carnot", years="1796-1832")]
                ),
            ),
            _slide(
                2,
                SlideType.CONTENT_SPLIT,
                SlideContent(
                    title="The cold plate",
                    figure_prompt="a copper cold plate",
                    figure_subject_type=ImageSubjectType.OBJECT,
                ),
            ),
        ]
    )
    storage = _FakeStorage()
    image_pass = ImagePass(
        portrait_resolver=_FakePortraits(result=_img(b"PORTRAIT")),
        generated_resolver=_FakeGenerated(result=_img(b"GENERATED")),
        max_generated_images=5,
        http_client_factory=_no_http,
    )

    result = await image_pass.resolve_deck(deck, storage=storage, project_id="p1", figures=[])

    assert result.slides[1].content.people is not None
    assert result.slides[1].content.people[0].portrait_url == "https://cdn.test/" + next(
        k for k in storage.uploaded if storage.uploaded[k][0] == b"PORTRAIT"
    )
    assert result.slides[2].content.figure_url is not None
    assert result.slides[0].content.background_url is not None  # title-hero scene
    # Three images were uploaded under the project's temp namespace.
    assert len(storage.uploaded) == 3
    assert all(key.startswith("temp/p1/") for key in storage.uploaded)


@pytest.mark.asyncio
async def test_abstains_leave_urls_null_and_never_fail() -> None:
    deck = _deck(
        [
            _slide(
                0,
                SlideType.GALLERY_PEOPLE,
                SlideContent(title="People", people=[PersonItem(name="Nobody Specific")]),
            ),
            _slide(
                1,
                SlideType.CONTENT_SPLIT,
                SlideContent(title="X", figure_prompt="an obscure widget"),
            ),
        ]
    )
    storage = _FakeStorage()
    image_pass = ImagePass(
        portrait_resolver=_FakePortraits(result=None),  # abstains
        generated_resolver=_FakeGenerated(result=None),  # abstains
        http_client_factory=_no_http,
    )

    result = await image_pass.resolve_deck(deck, storage=storage, project_id="p1", figures=[])

    assert result.slides[0].content.people is not None
    assert result.slides[0].content.people[0].portrait_url is None
    assert result.slides[1].content.figure_url is None
    assert storage.uploaded == {}  # nothing uploaded when everything abstains


@pytest.mark.asyncio
async def test_resolution_runs_in_parallel() -> None:
    # Six portrait slots, each resolver sleeps 200ms. Serial would be ~1.2s;
    # if the gather truly overlaps them the resolution phase is ~200ms, so even
    # with upload overhead the whole stage finishes far below the serial bound.
    delay = 0.2
    count = 6
    people = [PersonItem(name=f"Person {i}") for i in range(count)]
    deck = _deck([_slide(0, SlideType.GALLERY_PEOPLE, SlideContent(title="Many", people=people))])
    image_pass = ImagePass(
        portrait_resolver=_FakePortraits(result=_img(), delay=delay),
        generated_resolver=_FakeGenerated(result=None),
        http_client_factory=_no_http,
    )

    start = time.perf_counter()
    await image_pass.resolve_deck(deck, storage=_FakeStorage(), project_id="p1", figures=[])
    elapsed = time.perf_counter() - start

    # Serial would be count*delay = 1.2s. Half of that (0.6s) is unreachable
    # unless the six resolutions genuinely overlap.
    assert elapsed < count * delay * 0.5


@pytest.mark.asyncio
async def test_generated_budget_caps_figures_and_prefers_them_over_background() -> None:
    # Budget of 1: one figure should win the budget; the title-hero background
    # (lower priority) abstains.
    deck = _deck(
        [
            _slide(0, SlideType.TITLE_HERO, SlideContent(title="Deck")),
            _slide(
                1,
                SlideType.CONTENT_SPLIT,
                SlideContent(title="Fig A", figure_prompt="widget A"),
            ),
        ]
    )
    generated = _FakeGenerated(result=_img(b"GEN"))
    image_pass = ImagePass(
        portrait_resolver=_FakePortraits(result=None),
        generated_resolver=generated,
        max_generated_images=1,
        http_client_factory=_no_http,
    )

    result = await image_pass.resolve_deck(
        deck, storage=_FakeStorage(), project_id="p1", figures=[]
    )

    assert result.slides[1].content.figure_url is not None  # figure won the budget
    assert result.slides[0].content.background_url is None  # background dropped
    assert len(generated.calls) == 1
    assert generated.calls[0][1] is ImageSubjectType.OBJECT  # the figure, not the scene


@pytest.mark.asyncio
async def test_cc_by_attribution_is_folded_into_speaker_notes() -> None:
    attribution = ImageAttribution(
        creator="Jane Photographer",
        source_url="https://commons.wikimedia.org/wiki/File:X.jpg",
        license_name="CC BY 4.0",
        subject="Carnot",
    )
    deck = _deck(
        [
            _slide(
                0,
                SlideType.GALLERY_PEOPLE,
                SlideContent(
                    title="People",
                    people=[PersonItem(name="Carnot")],
                    speaker_notes="Original notes.",
                ),
            )
        ]
    )
    image_pass = ImagePass(
        portrait_resolver=_FakePortraits(result=_img(attribution=attribution)),
        generated_resolver=_FakeGenerated(result=None),
        http_client_factory=_no_http,
    )

    result = await image_pass.resolve_deck(
        deck, storage=_FakeStorage(), project_id="p1", figures=[]
    )

    notes = result.slides[0].content.speaker_notes or ""
    assert "Original notes." in notes  # existing notes preserved
    assert "Jane Photographer" in notes  # attribution appended
    assert "CC BY 4.0" in notes


@pytest.mark.asyncio
async def test_timeline_portrait_resolved_from_prompt() -> None:
    deck = _deck(
        [
            _slide(
                0,
                SlideType.TIMELINE,
                SlideContent(
                    title="Key dates",
                    timeline_nodes=[
                        TimelineNode(
                            date="1824", label="Carnot cycle", portrait_prompt="Sadi Carnot"
                        ),
                        TimelineNode(date="1850", label="Second law"),  # no person → skipped
                    ],
                ),
            )
        ]
    )
    portraits = _FakePortraits(result=_img(b"FACE"))
    image_pass = ImagePass(
        portrait_resolver=portraits,
        generated_resolver=_FakeGenerated(result=None),
        http_client_factory=_no_http,
    )

    result = await image_pass.resolve_deck(
        deck, storage=_FakeStorage(), project_id="p1", figures=[]
    )

    nodes = result.slides[0].content.timeline_nodes
    assert nodes is not None
    assert nodes[0].portrait_url is not None
    assert nodes[1].portrait_url is None
    assert portraits.calls == ["Sadi Carnot"]  # only the person node was queried


@pytest.mark.asyncio
async def test_no_slots_returns_deck_unchanged() -> None:
    deck = _deck([_slide(0, SlideType.SUMMARY_TAKEAWAY, SlideContent(title="Just text"))])
    storage = _FakeStorage()
    image_pass = ImagePass(
        portrait_resolver=_FakePortraits(result=_img()),
        generated_resolver=_FakeGenerated(result=_img()),
        http_client_factory=_no_http,
    )
    result = await image_pass.resolve_deck(deck, storage=storage, project_id="p1", figures=[])
    assert storage.uploaded == {}
    assert result.slides[0].content.background_url is None
