"""Behaviour tests for :class:`EditorialPass`.

All LLM calls are mocked via stub clients (per ``.claude/rules/testing.md``
only external LLM APIs may be mocked). Pure-Python helpers — content
analysis, narrative arc selection, slide-count estimation, post-processing —
are tested without any stubs.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from itertools import pairwise
from typing import Any
from uuid import uuid4

import pytest

from packages.core.enums import (
    AudienceType,
    BackgroundTreatment,
    ClaimStrength,
    ClaimType,
    ExportFormat,
    ImageSubjectType,
    Language,
    NarrativeEmphasis,
    NarrativePhase,
    PresentationMood,
    SlideType,
)
from packages.core.gemini import GEMINI_FLASH_MODEL
from packages.core.llm import LLMResponse
from packages.core.models.evidence import EvidenceMatrix
from packages.core.models.presentation import (
    ColorPalette,
    ContentAnalysis,
    DeckSpec,
    DesignDirectionSpec,
    PresentationInterviewAnswers,
    SlideContent,
    SlideSpec,
    StatItem,
)
from packages.core.models.source import SourceClaimCreate
from packages.presentation.editorial import (
    SONNET_MODEL,
    WORD_LIMITS,
    EditorialPass,
    _insert_breathing_after_data,
    _materialise_slides,
    _parse_sequence,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class _StubLLM:
    """Stand-in returning scripted text responses in order."""

    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, str]] = []

    async def complete(
        self,
        system: str,
        user: str,
        model: str = SONNET_MODEL,
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


def _claim(
    text: str,
    *,
    claim_type: ClaimType = ClaimType.GENERAL_FACT,
    strength: ClaimStrength = ClaimStrength.MODERATE,
    quote: str | None = None,
) -> SourceClaimCreate:
    if len(text) < 10:
        text = text.ljust(10, ".")
    return SourceClaimCreate(
        claim_text=text,
        strength=strength,
        claim_type=claim_type,
        quote=quote,
    )


def _interview(**kwargs: Any) -> PresentationInterviewAnswers:
    defaults: dict[str, Any] = {
        "audience": AudienceType.UNDERGRADUATE,
        "talk_duration_minutes": 15,
        "language": Language.UZ,
        "narrative_emphasis": NarrativeEmphasis.BALANCED,
        "include_interactive": False,
        "mood_override": PresentationMood.CLEAN_PROFESSIONAL,
        "background_treatment": BackgroundTreatment.LIGHT,
    }
    defaults.update(kwargs)
    return PresentationInterviewAnswers(**defaults)


def _design() -> DesignDirectionSpec:
    return DesignDirectionSpec(
        mood=PresentationMood.CLEAN_PROFESSIONAL,
        palette=ColorPalette(
            background="#F8F8FA",
            surface="#FFFFFF",
            text="#2A2A2A",
            accent="#0A8A7A",
            text_secondary="#6A6A7A",
        ),
        heading_font="Inter",
        body_font="Inter",
        decorative_font=None,
        image_style_prefix="clean modern",
        background_treatment=BackgroundTreatment.LIGHT,
    )


def _evidence_matrix() -> EvidenceMatrix:
    return EvidenceMatrix(project_id=uuid4(), created_at=datetime.now(UTC))


def _slide(
    slide_type: SlideType,
    title: str = "Slide",
    *,
    body_text: str | None = None,
    bullets: list[str] | None = None,
    speaker_notes: str | None = None,
) -> SlideSpec:
    return SlideSpec(
        slide_index=0,
        slide_type=slide_type,
        content=SlideContent(
            title=title,
            body_text=body_text,
            bullets=bullets,
            speaker_notes=speaker_notes,
        ),
    )


def _llm_slides_payload(slides: list[dict[str, Any]]) -> str:
    return json.dumps({"slides": slides})


# ---------------------------------------------------------------------------
# Structured field parsing (tables / comparison / chart series)
#
# These lock the prompt<->parser contract. _LLMSlide uses extra="ignore", so it
# SILENTLY DROPS any field it does not declare. The editorial prompt instructs
# the model to emit table_headers/table_rows, left_column/right_column, and
# chart_series; if the schema ever stops declaring one of those, the data is
# dropped and the slide renders blank. These tests fail loudly if that drift
# returns.
# ---------------------------------------------------------------------------


def _materialise_one(slide_payload: dict[str, Any]) -> SlideContent:
    """Parse a single LLM slide payload and return its materialised content."""

    parsed = _parse_sequence(_llm_slides_payload([slide_payload]))
    assert parsed is not None and len(parsed) == 1
    slides = _materialise_slides(parsed)
    assert len(slides) == 1
    return slides[0].content


def test_table_fields_parse_and_materialise() -> None:
    content = _materialise_one(
        {
            "slide_index": 0,
            "slide_type": "table_compact",
            "title": "sCO2 wins on every dimension",
            "table_headers": ["Cooling", "Density", "PUE"],
            "table_rows": [
                {"cells": ["Air", "8 kW/rack", "1.58"]},
                {"cells": ["Liquid", "40 kW/rack", "1.10"]},
                {"cells": ["sCO2", "120 kW/rack", "1.04"]},
            ],
        }
    )
    assert content.table_headers == ["Cooling", "Density", "PUE"]
    assert content.table_rows is not None
    assert len(content.table_rows) == 3
    assert content.table_rows[0].cells == ["Air", "8 kW/rack", "1.58"]


def test_comparison_columns_parse_from_top_level_keys() -> None:
    # The prompt now emits left_column/right_column at the TOP level (not a
    # nested "comparison" object). These are the keys _LLMSlide declares, so
    # they survive parsing and reach SlideContent.
    content = _materialise_one(
        {
            "slide_index": 0,
            "slide_type": "comparison",
            "title": "Air cooling vs liquid cooling",
            "left_column": {"heading": "Air", "points": ["Cheap", "Low density"]},
            "right_column": {"heading": "Liquid", "points": ["Dense", "Higher capex"]},
        }
    )
    assert content.left_column is not None
    assert content.left_column.heading == "Air"
    assert content.left_column.points == ["Cheap", "Low density"]
    assert content.right_column is not None
    assert content.right_column.heading == "Liquid"
    assert content.right_column.points == ["Dense", "Higher capex"]


def test_nested_comparison_key_is_dropped() -> None:
    # Regression guard documenting the bug the prompt fix removes: the OLD
    # prompt told the model to emit {"comparison": {"left": ..., "right": ...}}.
    # _LLMSlide does not declare "comparison", so extra="ignore" silently drops
    # it and both columns stay null — which is exactly why comparison slides
    # rendered as blank scaffolding.
    content = _materialise_one(
        {
            "slide_index": 0,
            "slide_type": "comparison",
            "title": "Air vs liquid",
            "comparison": {
                "left": {"heading": "Air", "points": ["Cheap"]},
                "right": {"heading": "Liquid", "points": ["Dense"]},
            },
        }
    )
    assert content.left_column is None
    assert content.right_column is None


def test_chart_series_parses_and_materialises() -> None:
    content = _materialise_one(
        {
            "slide_index": 0,
            "slide_type": "chart_data",
            "title": "Rack density climbs 15x from air to sCO2",
            "body_text": "Heat capacity sets the ceiling.",
            "chart_series": [
                {"label": "Air", "value": 8, "unit": "kW/rack"},
                {"label": "Liquid", "value": 40, "unit": "kW/rack"},
                {"label": "sCO2", "value": 120, "unit": "kW/rack"},
            ],
        }
    )
    assert content.chart_series is not None
    assert [p.label for p in content.chart_series] == ["Air", "Liquid", "sCO2"]
    assert [p.value for p in content.chart_series] == [8.0, 40.0, 120.0]
    # The data lives in chart_series, not buried in prose.
    assert content.body_text == "Heat capacity sets the ceiling."


def test_chart_type_and_grouped_fields_parse_and_materialise() -> None:
    # Regression guard: _LLMSlide must DECLARE chart_type / chart_group_labels
    # and ChartSeriesPoint must declare `values`, or extra="ignore"/extra=
    # "forbid" drops them and the worker silently falls back to a flat bar.
    content = _materialise_one(
        {
            "slide_index": 0,
            "slide_type": "chart_data",
            "title": "Power split widens with rack density",
            "chart_type": "grouped_bar",
            "chart_group_labels": ["IT load", "Cooling", "Other"],
            "chart_series": [
                {"label": "Air", "value": 8, "values": [6, 1.5, 0.5]},
                {"label": "sCO2", "value": 120, "values": [90, 25, 5]},
            ],
        }
    )
    assert content.chart_type is not None
    assert content.chart_type.value == "grouped_bar"
    assert content.chart_group_labels == ["IT load", "Cooling", "Other"]
    assert content.chart_series is not None
    assert content.chart_series[1].values == [90.0, 25.0, 5.0]


# ---------------------------------------------------------------------------
# Object-figure slot parsing (image engine, PART 1)
#
# Same contract guard as the chart/table tests: _LLMSlide must DECLARE
# figure_prompt/figure_subject_type and _materialise_slides must copy them,
# or extra="ignore" drops the figure the editorial prompt asks for and the
# image engine never has a figure to resolve. _normalise_figure additionally
# clamps a figure away from PERSON/SCENE so it never mis-routes into person
# sourcing. figure_url is never emitted by editorial — the image stage writes
# it later — so it must materialise as None here.
# ---------------------------------------------------------------------------


def test_figure_prompt_parses_and_materialises() -> None:
    content = _materialise_one(
        {
            "slide_index": 0,
            "slide_type": "concept_definition",
            "title": "The cold plate is where the heat leaves the chip",
            "subtitle": "A liquid-cooled heat exchanger bolted to the die.",
            "figure_prompt": "a liquid cold plate heat exchanger, copper "
            "microchannels, isolated on a neutral background",
            "figure_subject_type": "object",
        }
    )
    assert (
        content.figure_prompt == "a liquid cold plate heat exchanger, copper microchannels, "
        "isolated on a neutral background"
    )
    assert content.figure_subject_type is ImageSubjectType.OBJECT
    # The image stage fills figure_url later; editorial never emits it.
    assert content.figure_url is None


def test_figure_subject_type_concept_survives() -> None:
    content = _materialise_one(
        {
            "slide_index": 0,
            "slide_type": "content_split",
            "title": "Entropy always increases in a closed loop",
            "figure_prompt": "an abstract visualisation of rising entropy",
            "figure_subject_type": "concept",
        }
    )
    assert content.figure_subject_type is ImageSubjectType.CONCEPT


def test_figure_without_subject_type_defaults_to_object() -> None:
    # The model may emit a figure_prompt and forget the subject type; the
    # materialiser must default it to OBJECT, never leave a figure unrouted.
    content = _materialise_one(
        {
            "slide_index": 0,
            "slide_type": "content_split",
            "title": "A turbine spins the generator",
            "figure_prompt": "a steam turbine rotor, isolated on neutral grey",
        }
    )
    assert content.figure_prompt is not None
    assert content.figure_subject_type is ImageSubjectType.OBJECT


def test_figure_tagged_person_is_coerced_to_object() -> None:
    # A figure is a contained object/concept, never a real person (people go
    # through the people slot and resolve to gated Commons portraits). A
    # figure mistakenly tagged "person" must NOT route into person sourcing.
    content = _materialise_one(
        {
            "slide_index": 0,
            "slide_type": "content_split",
            "title": "The reactor core",
            "figure_prompt": "a nuclear reactor pressure vessel cutaway",
            "figure_subject_type": "person",
        }
    )
    assert content.figure_subject_type is ImageSubjectType.OBJECT


def test_no_figure_prompt_leaves_both_fields_null() -> None:
    # No prompt means no figure: a stray subject type is dropped too, so the
    # image stage sees a clean "no figure here" signal.
    content = _materialise_one(
        {
            "slide_index": 0,
            "slide_type": "content_split",
            "title": "A slide with no figure",
            "figure_subject_type": "object",
        }
    )
    assert content.figure_prompt is None
    assert content.figure_subject_type is None


# ---------------------------------------------------------------------------
# Editorial validation coercion (the resilience net)
#
# The editorial schema is intentionally tighter than the model's natural
# output, so a SINGLE bad field on a SINGLE slide used to fail _LLMSequence
# validation and collapse the whole deck to the 2-slide "Insufficient source
# material" fallback. _parse_sequence now salvages the two recurring failure
# modes — an over-long string and a slide missing its title — and re-validates
# once, falling back only when the output is genuinely unusable. These tests
# lock that behaviour: a fixable field must never throw away the deck, and a
# real defect must still fall back (coercion must not mask it).
# ---------------------------------------------------------------------------


def test_overlong_unit_is_truncated_not_whole_deck_rejected() -> None:
    parsed = _parse_sequence(
        _llm_slides_payload(
            [
                {
                    "slide_index": 0,
                    "slide_type": "data_emphasis",
                    "title": "Recovered heat pays for the retrofit",
                    "stats": [
                        {
                            "value": "1.04",
                            "unit": "M USD of facility energy recovered annually",
                            "label": "Annual saving",
                        }
                    ],
                }
            ]
        )
    )
    assert parsed is not None and len(parsed) == 1
    assert parsed[0].stats is not None
    # 43-char unit clamped at the nearest word boundary inside the 32 cap.
    assert parsed[0].stats[0].unit == "M USD of facility energy"


def test_null_title_repaired_from_body_keeps_slide() -> None:
    parsed = _parse_sequence(
        _llm_slides_payload(
            [
                {"slide_index": 0, "slide_type": "title_hero", "title": "Cooling that pays"},
                {
                    "slide_index": 1,
                    "slide_type": "content_split",
                    "title": None,
                    "body_text": "A dry cooler rejects rack heat without evaporating water.",
                },
            ]
        )
    )
    assert parsed is not None and len(parsed) == 2
    assert parsed[1].title == "A dry cooler rejects rack heat without evaporating water."


def test_empty_string_title_repaired_from_stat_label() -> None:
    parsed = _parse_sequence(
        _llm_slides_payload(
            [
                {"slide_index": 0, "slide_type": "title_hero", "title": "Real title"},
                {
                    "slide_index": 1,
                    "slide_type": "data_emphasis",
                    "title": "   ",
                    "stats": [{"value": "94.4", "unit": "%", "label": "Water saved"}],
                },
            ]
        )
    )
    assert parsed is not None and len(parsed) == 2
    assert parsed[1].title == "Water saved"


def test_missing_title_key_repaired_from_body() -> None:
    parsed = _parse_sequence(
        _llm_slides_payload(
            [
                {"slide_index": 0, "slide_type": "title_hero", "title": "Real title"},
                {
                    "slide_index": 1,
                    "slide_type": "content_split",
                    "body_text": "Liquid cooling moves five times the heat of air.",
                },
            ]
        )
    )
    assert parsed is not None and len(parsed) == 2
    assert parsed[1].title == "Liquid cooling moves five times the heat of air."


def test_untitled_slide_with_no_text_is_dropped_not_whole_deck() -> None:
    parsed = _parse_sequence(
        _llm_slides_payload(
            [
                {"slide_index": 0, "slide_type": "title_hero", "title": "Cooling that pays"},
                {"slide_index": 1, "slide_type": "content_split", "title": None},
            ]
        )
    )
    assert parsed is not None and len(parsed) == 1
    assert parsed[0].title == "Cooling that pays"


def test_genuinely_invalid_output_is_not_coerced() -> None:
    # An unknown slide_type is a real defect, not a fixable field. Coercion must
    # not mask it: parsing fails so the pipeline can fall back as before.
    parsed = _parse_sequence(
        _llm_slides_payload(
            [{"slide_index": 0, "slide_type": "not_a_real_slide_type", "title": "x"}]
        )
    )
    assert parsed is None


def _coercible_payload() -> str:
    """A realistic editorial response carrying both salvageable violations:
    one slide with an over-long stat unit and one slide with a null title."""

    slides = [
        _minimal_slide_payload("title_hero", "Water savings reach 94.4% in mild climates"),
        _minimal_slide_payload("concept_definition", "Direct evaporative cooling defined"),
        {
            "slide_index": 2,
            "slide_type": "data_emphasis",
            "title": "Recovered heat pays for the retrofit",
            "stats": [
                {
                    "value": "1.04",
                    "unit": "M USD of facility energy recovered annually",
                    "label": "Annual saving",
                }
            ],
            "narrative_role": "evidence",
        },
        _minimal_slide_payload("section_break", "Method"),
        {
            "slide_index": 4,
            "slide_type": "content_split",
            "title": None,
            "body_text": "A three-stage pipeline moves heat off the rack into a dry cooler.",
            "narrative_role": "core",
        },
        _minimal_slide_payload("summary_takeaway", "Three lessons from the pilot"),
    ]
    return _llm_slides_payload(slides)


@pytest.mark.asyncio
async def test_coercible_violations_yield_full_deck_not_fallback() -> None:
    # The regression that proves the CLASS is fixed, not just the instance: a
    # response with an over-long unit AND a null title must coerce to a FULL
    # multi-slide deck, never the 2-slide "insufficient source" fallback.
    llm = _StubLLM([_coercible_payload()])
    pass_ = EditorialPass(llm=llm)  # type: ignore[arg-type]
    claims = [
        _claim(
            f"Empirical finding {i} from the cooling pilot.",
            claim_type=ClaimType.EMPIRICAL_FINDING,
            strength=ClaimStrength.STRONG,
        )
        for i in range(20)
    ]
    deck = await pass_.generate_deck_spec(
        interview=_interview(include_interactive=False),
        design=_design(),
        evidence_matrix=_evidence_matrix(),
        claims=claims,
        chunks=[],
        source_metadata=[],
    )
    titles = [s.content.title for s in deck.slides]
    assert "Insufficient source material" not in titles
    assert len(deck.slides) > 2
    units = [st.unit for s in deck.slides if s.content.stats for st in s.content.stats]
    assert "M USD of facility energy" in units


@pytest.mark.asyncio
async def test_uncoercible_output_falls_back_to_minimal_deck() -> None:
    # Garbage that coercion can't fix (unknown slide_type on every slide) must
    # still produce the emergency deck — the safety net must not hide real
    # failure. Two responses: the first call plus its one retry.
    bad = _llm_slides_payload([{"slide_index": 0, "slide_type": "bogus", "title": "x"}])
    llm = _StubLLM([bad, bad])
    pass_ = EditorialPass(llm=llm)  # type: ignore[arg-type]
    deck = await pass_.generate_deck_spec(
        interview=_interview(include_interactive=False),
        design=_design(),
        evidence_matrix=_evidence_matrix(),
        claims=[_claim("A finding that matters.")],
        chunks=[],
        source_metadata=[],
    )
    titles = [s.content.title for s in deck.slides]
    assert "Insufficient source material" in titles


# ---------------------------------------------------------------------------
# Content analysis (no LLM)
# ---------------------------------------------------------------------------


def test_analyze_content_counts_claim_types() -> None:
    claims = (
        [_claim(f"Stat claim {i}", claim_type=ClaimType.STATISTICAL_RESULT) for i in range(3)]
        + [_claim(f"Empirical claim {i}", claim_type=ClaimType.EMPIRICAL_FINDING) for i in range(4)]
        + [_claim(f"Theory claim {i}", claim_type=ClaimType.THEORETICAL_ARGUMENT) for i in range(3)]
    )
    analysis = EditorialPass._analyze_content(claims)
    assert analysis.total_claims == 10
    assert len(analysis.statistical_claims) == 3
    assert len(analysis.empirical_findings) == 4
    assert len(analysis.theoretical_arguments) == 3


def test_analyze_content_detects_people() -> None:
    claims = [
        _claim("Newton's laws of motion underpin classical mechanics."),
        _claim("Leibniz independently developed calculus and proposed notation."),
        _claim("Euler unified analysis with his celebrated identity."),
        _claim("The committee endorsed the report after revisions."),
    ]
    analysis = EditorialPass._analyze_content(claims)
    lowered = {p.lower() for p in analysis.people_mentioned}
    assert "newton" in lowered
    assert "leibniz" in lowered
    assert "euler" in lowered


def test_analyze_content_detects_comparisons() -> None:
    claims = [
        _claim("Solar adoption grew faster compared to wind generation in the same region."),
        _claim("Hospital A reported higher recovery rates versus Hospital B over five years."),
    ]
    analysis = EditorialPass._analyze_content(claims)
    assert analysis.has_comparison_content is True


def test_analyze_content_extracts_key_numbers() -> None:
    claims = [
        _claim("Water savings reached 94.4% across mild climate facilities."),
        _claim("The pilot cost the operator $1.04M in the first year of deployment."),
        _claim("Researchers analysed 516,120 records to build the predictive model."),
    ]
    analysis = EditorialPass._analyze_content(claims)
    joined = " ".join(analysis.key_numbers)
    assert "94.4%" in joined
    assert "1.04" in joined  # captured as $1.04M
    assert "516,120" in joined


def test_analyze_content_ranks_strongest() -> None:
    claims = [
        _claim("Weak claim about adoption.", strength=ClaimStrength.WEAK),
        _claim(
            "Strong claim demonstrating direct benefit.",
            strength=ClaimStrength.STRONG,
            claim_type=ClaimType.EMPIRICAL_FINDING,
        ),
        _claim(
            "Moderate claim suggesting improvement.",
            strength=ClaimStrength.MODERATE,
            claim_type=ClaimType.EMPIRICAL_FINDING,
        ),
    ]
    analysis = EditorialPass._analyze_content(claims)
    assert "Strong claim demonstrating direct benefit." in analysis.strongest_claims
    assert all("Weak claim" not in c for c in analysis.strongest_claims)
    assert analysis.strongest_claims[0] == "Strong claim demonstrating direct benefit."


# ---------------------------------------------------------------------------
# Narrative arc selection
# ---------------------------------------------------------------------------


def test_narrative_arc_balanced() -> None:
    arc = EditorialPass._determine_narrative_arc(
        _interview(narrative_emphasis=NarrativeEmphasis.BALANCED),
        EditorialPass._analyze_content([]),
    )
    assert arc.emphasis_phase is NarrativePhase.CORE
    assert NarrativePhase.HOOK in arc.phases
    assert NarrativePhase.CLOSE in arc.phases


def test_narrative_arc_problem_framing() -> None:
    arc = EditorialPass._determine_narrative_arc(
        _interview(narrative_emphasis=NarrativeEmphasis.PROBLEM_FRAMING),
        EditorialPass._analyze_content([]),
    )
    assert arc.emphasis_phase is NarrativePhase.CONTEXT


def test_narrative_arc_results() -> None:
    arc = EditorialPass._determine_narrative_arc(
        _interview(narrative_emphasis=NarrativeEmphasis.RESULTS_NUMBERS),
        EditorialPass._analyze_content([]),
    )
    assert arc.emphasis_phase is NarrativePhase.EVIDENCE


# ---------------------------------------------------------------------------
# Deck sizing (content-driven, not duration-driven)
# ---------------------------------------------------------------------------


def _analysis_with_claims(n: int) -> ContentAnalysis:
    """Build a ContentAnalysis whose total_claims is exactly ``n``."""

    return EditorialPass._analyze_content(
        [_claim(f"Substantive claim number {i} that carries an idea.") for i in range(n)]
    )


def _size(interview: PresentationInterviewAnswers, n_claims: int) -> int:
    return EditorialPass()._size_deck(interview, _analysis_with_claims(n_claims))


def test_size_deck_thin_content_clamps_to_floor() -> None:
    # 5 claims -> content base floors at 6 (not 30). 6 + max(1, 6//5)=1 break.
    count = _size(_interview(include_interactive=False), n_claims=5)
    assert count == 7


def test_size_deck_rich_content_clamps_to_ceiling() -> None:
    # 60 claims -> content base caps at 15 (not 60). 15 + 15//5=3 breaks.
    count = _size(_interview(include_interactive=False), n_claims=60)
    assert count == 18


def test_size_deck_mid_content_lands_between_floor_and_ceiling() -> None:
    # 10 claims -> content base 10, between floor and ceiling. 10 + 10//5=2.
    count = _size(_interview(include_interactive=False), n_claims=10)
    assert count == 12


def test_size_deck_scales_with_claim_volume() -> None:
    # More substantive claims -> a larger deck, within the clamp band.
    fewer = _size(_interview(include_interactive=False), n_claims=8)
    more = _size(_interview(include_interactive=False), n_claims=12)
    assert fewer < more


def test_size_deck_long_duration_thin_content_still_clamps_low() -> None:
    # Proves talk_duration no longer drives the count: a 60-minute slot with
    # only 5 claims still produces a tight deck, not 60+ slides.
    count = _size(
        _interview(talk_duration_minutes=60, include_interactive=False),
        n_claims=5,
    )
    assert count == 7


def test_size_deck_short_duration_rich_content_still_gets_real_deck() -> None:
    # Proves talk_duration no longer starves the count: a 3-minute slot with
    # 40 claims still earns a full deck up to the ceiling.
    count = _size(
        _interview(talk_duration_minutes=3, include_interactive=False),
        n_claims=40,
    )
    assert count == 18


def test_size_deck_interactive_adds_on_top_of_content_base() -> None:
    with_int = _size(_interview(include_interactive=True), n_claims=10)
    without_int = _size(_interview(include_interactive=False), n_claims=10)
    assert with_int > without_int


# ---------------------------------------------------------------------------
# Content summary
# ---------------------------------------------------------------------------


def test_build_content_summary_includes_headline_numbers() -> None:
    interview = _interview(headline_numbers=["94.4% water savings"])
    analysis = EditorialPass._analyze_content([])
    arc = EditorialPass._determine_narrative_arc(interview, analysis)
    summary = EditorialPass._build_content_summary(analysis, interview, arc)
    assert "94.4% water savings" in summary


def test_build_content_summary_includes_closing_ask() -> None:
    interview = _interview(closing_ask="pilot site at hyperscaler X")
    analysis = EditorialPass._analyze_content([])
    arc = EditorialPass._determine_narrative_arc(interview, analysis)
    summary = EditorialPass._build_content_summary(analysis, interview, arc)
    assert "pilot site at hyperscaler X" in summary


def test_build_content_summary_limits_claims() -> None:
    many_claims = [
        _claim(
            f"Statistical finding number {i} establishes a measurable result.",
            claim_type=ClaimType.STATISTICAL_RESULT,
            strength=ClaimStrength.STRONG,
        )
        for i in range(100)
    ]
    interview = _interview()
    analysis = EditorialPass._analyze_content(many_claims)
    arc = EditorialPass._determine_narrative_arc(interview, analysis)
    summary = EditorialPass._build_content_summary(analysis, interview, arc)
    # We curate at most ~30-40 claim-text bullet lines (strongest + stats + others).
    bullet_lines = [line for line in summary.split("\n") if line.lstrip().startswith("-")]
    assert len(bullet_lines) <= 40
    assert len(bullet_lines) >= 5


# ---------------------------------------------------------------------------
# Post-processing
# ---------------------------------------------------------------------------


def test_post_process_does_not_inject_hollow_dividers_between_repeats() -> None:
    """Invariant I2: the post-process no longer hides R01 (consecutive same-
    type slides) behind a hollow SECTION_BREAK. The old auto-divider had
    title='•' and no thesis — pure slop. Consecutive same-types now flow
    through unchanged (the model is steered by EDITORIAL_SYSTEM rule 7 not
    to emit them; layout variety is the layout pass's job).
    """

    slides = [
        _slide(SlideType.TITLE_HERO, "Title"),
        _slide(SlideType.CONTENT_SPLIT, "A"),
        _slide(SlideType.CONTENT_SPLIT, "B"),
        _slide(SlideType.DATA_EMPHASIS, "Stat"),
    ]
    out = EditorialPass._post_process(slides, _interview())
    # The two CONTENT_SPLIT slides remain adjacent — no hollow break wedged in.
    types = [s.slide_type for s in out]
    assert types.count(SlideType.CONTENT_SPLIT) == 2
    # No SECTION_BREAK appears at all because the input had none and post-
    # process never invents one.
    assert SlideType.SECTION_BREAK not in types


def test_post_process_does_not_auto_insert_section_breaks_in_long_runs() -> None:
    """Invariant I2: R03 (section cadence) is now a model-prompt concern; the
    post-process no longer injects hollow section breaks every 5 slides.
    A long run of content slides survives unchanged — section structure is
    earned by a thesis-bearing SECTION_BREAK from the LLM, not synthesized.
    """

    slides = [_slide(SlideType.TITLE_HERO, "Title")] + [
        _slide(
            SlideType.CONTENT_SPLIT if i % 2 == 0 else SlideType.DATA_EMPHASIS,
            f"Slide {i}",
        )
        for i in range(12)
    ]
    out = EditorialPass._post_process(slides, _interview())
    # No SECTION_BREAK should be auto-inserted: input had none, output has none.
    assert all(s.slide_type is not SlideType.SECTION_BREAK for s in out)


def test_drop_hollow_dividers_keeps_thesis_breaks_and_drops_bare_ones() -> None:
    """The hard backstop for invariant I2 — a bare SECTION_BREAK is dropped,
    a thesis-bearing one (non-empty subtitle) survives. The prompt steers the
    model away from bare breaks, but this filter is the guarantee.
    """

    from packages.presentation.editorial import _drop_hollow_dividers

    bare = SlideSpec(
        slide_index=0,
        slide_type=SlideType.SECTION_BREAK,
        content=SlideContent(title="Method"),
        section_name="Method",
    )
    thesis = SlideSpec(
        slide_index=1,
        slide_type=SlideType.SECTION_BREAK,
        content=SlideContent(
            title="Method",
            subtitle="Three pilots, one protocol, identical instrumentation.",
        ),
        section_name="Method",
    )
    body_only = SlideSpec(
        slide_index=2,
        slide_type=SlideType.SECTION_BREAK,
        content=SlideContent(title="Results", body_text="The pilots converged within 6%."),
        section_name="Results",
    )
    content_slide = _slide(SlideType.CONTENT_SPLIT, "Pilot A")

    out = _drop_hollow_dividers([bare, thesis, body_only, content_slide])

    assert [s.slide_type for s in out] == [
        SlideType.SECTION_BREAK,  # thesis (kept)
        SlideType.SECTION_BREAK,  # body_only (kept)
        SlideType.CONTENT_SPLIT,
    ]
    assert out[0].content.subtitle is not None  # the thesis-bearing one
    assert out[1].content.body_text is not None  # the body-only one


def test_post_process_enforces_word_limits() -> None:
    # CONTENT_SPLIT limit is 60. Build a slide with 90 words of body text.
    big_body = " ".join(["paragraph"] * 90)
    slides = [
        _slide(SlideType.TITLE_HERO, "Title"),
        _slide(SlideType.CONTENT_SPLIT, "Topic", body_text=big_body, speaker_notes="brief"),
    ]
    out = EditorialPass._post_process(slides, _interview())
    target = next(s for s in out if s.slide_type is SlideType.CONTENT_SPLIT)
    body_words = len((target.content.body_text or "").split())
    notes = target.content.speaker_notes or ""
    assert body_words < 90
    assert "paragraph" in notes
    # Total visible word count should fit within the slide-type limit.
    from packages.presentation.editorial import _count_words_in_content

    assert _count_words_in_content(target.content) <= WORD_LIMITS[SlideType.CONTENT_SPLIT]


def _data_slide_with_stat(
    title: str,
    *,
    value: str,
    label: str,
    unit: str = "",
    highlight: bool = False,
) -> SlideSpec:
    return SlideSpec(
        slide_index=0,
        slide_type=SlideType.DATA_EMPHASIS,
        content=SlideContent(
            title=title,
            stats=[StatItem(value=value, unit=unit, label=label, highlight=highlight)],
        ),
    )


def _only_bullet(slide: SlideSpec) -> str:
    """The single bullet of a breather slide, narrowed for the type checker."""

    bullets = slide.content.bullets
    assert bullets is not None and len(bullets) == 1
    return bullets[0]


def test_post_process_does_not_auto_insert_breather_by_default() -> None:
    """Invariant I2: the breather device defaults OFF. The stat-echo seed it
    ships with today ('Key takeaway: 1.58 PUE — Power Usage Effectiveness')
    is exactly the 'echoes an adjacent stat' filler invariant I2 forbids.
    The device is retained for plan item 2 (model-authored breathers) but is
    NOT invoked from _post_process by default — consecutive data slides flow
    through unchanged.
    """

    slides = [
        _slide(SlideType.TITLE_HERO, "Title"),
        _data_slide_with_stat("Stat", value="1.58", unit="PUE", label="Power Usage Effectiveness"),
        _slide(SlideType.CHART_DATA, "Chart"),
    ]
    out = EditorialPass._post_process(slides, _interview())
    types = [s.slide_type for s in out]
    # The two data-heavy slides remain adjacent (no auto breather wedged in).
    assert SlideType.DATA_EMPHASIS in types
    assert SlideType.CHART_DATA in types
    assert all(s.slide_type is not SlideType.SUMMARY_TAKEAWAY for s in out)


def test_breathing_device_off_by_default_is_a_no_op() -> None:
    """The device is OFF by default — calling without enabled=True yields the
    input unchanged regardless of what data slides precede what."""

    slides = [
        _data_slide_with_stat(
            "Energy", value="1.58", unit="PUE", label="Power Usage Effectiveness", highlight=True
        ),
        _slide(SlideType.CHART_DATA, "Chart"),
    ]
    out = _insert_breathing_after_data(slides, _interview())
    assert [s.slide_type for s in out] == [SlideType.DATA_EMPHASIS, SlideType.CHART_DATA]


def test_breathing_device_when_enabled_seeds_from_real_stat() -> None:
    """The scaffold still works when explicitly enabled — the digit + label
    pair is carried through (kept so plan item 2 can flip enabled=True once a
    thesis-bearing seed replaces the stat echo)."""

    slides = [
        _data_slide_with_stat(
            "Energy", value="1.58", unit="PUE", label="Power Usage Effectiveness", highlight=True
        ),
        _slide(SlideType.CHART_DATA, "Chart"),
    ]
    out = _insert_breathing_after_data(slides, _interview(), enabled=True)
    assert [s.slide_type for s in out] == [
        SlideType.DATA_EMPHASIS,
        SlideType.SUMMARY_TAKEAWAY,
        SlideType.CHART_DATA,
    ]
    bullet = _only_bullet(out[1])
    assert any(ch.isdigit() for ch in bullet)
    assert "Power Usage Effectiveness" in bullet
    assert "1.58 PUE" in bullet  # word unit spaced off the value


def test_breathing_device_when_enabled_prefers_highlighted_stat_and_keeps_symbol_unit() -> None:
    multi = SlideSpec(
        slide_index=0,
        slide_type=SlideType.DATA_EMPHASIS,
        content=SlideContent(
            title="Numbers",
            stats=[
                StatItem(value="10", unit="%", label="first stat"),
                StatItem(value="35", unit="%", label="highlighted stat", highlight=True),
            ],
        ),
    )
    out = _insert_breathing_after_data(
        [multi, _slide(SlideType.TABLE_COMPACT, "Table")], _interview(), enabled=True
    )
    bullet = _only_bullet(out[1])
    assert "highlighted stat" in bullet
    assert "35%" in bullet  # symbol unit stays attached


def test_breathing_device_when_enabled_does_not_seed_without_a_stat() -> None:
    """CHART_DATA / TABLE_COMPACT carry numbers in prose/rows, not stats. The
    device, even when enabled, still abstains rather than inventing a hollow
    breather — absent beats hollow."""

    slides = [
        _slide(SlideType.CHART_DATA, "Chart with prose numbers"),
        _slide(SlideType.TABLE_COMPACT, "Table"),
    ]
    out = _insert_breathing_after_data(slides, _interview(), enabled=True)
    assert [s.slide_type for s in out] == [SlideType.CHART_DATA, SlideType.TABLE_COMPACT]
    assert all(s.slide_type is not SlideType.SUMMARY_TAKEAWAY for s in out)


def test_post_process_keeps_first_three_sparse() -> None:
    # R26: the LLM put a dense TABLE_COMPACT into the opening trio. The
    # post-processor must swap it later so the audience eases in.
    slides = [
        _slide(SlideType.TITLE_HERO, "Title"),
        _slide(SlideType.TABLE_COMPACT, "Dense early table"),
        _slide(SlideType.CONTENT_SPLIT, "Body 1"),
        _slide(SlideType.CONTENT_SPLIT, "Body 2"),
        _slide(SlideType.DATA_EMPHASIS, "Stat"),
        _slide(SlideType.SUMMARY_TAKEAWAY, "Wrap"),
    ]
    out = EditorialPass._post_process(slides, _interview())
    opening_types = [s.slide_type for s in out[:3]]
    assert SlideType.TABLE_COMPACT not in opening_types
    # The dense slide must still appear somewhere in the deck.
    assert any(s.slide_type is SlideType.TABLE_COMPACT for s in out)


def test_post_process_first_slide_is_title() -> None:
    slides = [
        _slide(SlideType.CONTENT_SPLIT, "Not a title slide"),
        _slide(SlideType.DATA_EMPHASIS, "Stat"),
    ]
    out = EditorialPass._post_process(slides, _interview())
    assert out[0].slide_type is SlideType.TITLE_HERO


def test_post_process_reindexes_sequentially() -> None:
    slides = [
        _slide(SlideType.CONTENT_SPLIT, "A"),
        _slide(SlideType.CONTENT_SPLIT, "B"),
        _slide(SlideType.DATA_EMPHASIS, "C"),
    ]
    out = EditorialPass._post_process(slides, _interview())
    assert [s.slide_index for s in out] == list(range(len(out)))


# ---------------------------------------------------------------------------
# Interactive slide generation (LLM mocked)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_interactive_quiz_from_claims() -> None:
    payload = {
        "quiz_questions": [
            {
                "question": "Qachon paydo boldi?",
                "options": [
                    {"text": "1700", "is_correct": False},
                    {"text": "1800", "is_correct": True},
                ],
                "explanation_correct": "Dúrıs — XVIII ásirde.",
                "explanation_wrong": "Qáte — biraz keyinroq.",
            }
        ]
    }
    gemini = _StubLLM([json.dumps(payload)])
    pass_ = EditorialPass(gemini=gemini)  # type: ignore[arg-type]
    content_slides = [
        _slide(SlideType.CONTENT_SPLIT, "Background", body_text="History overview."),
    ]
    interactive = await pass_._generate_interactive_slides(
        content_slides=content_slides,
        analysis=EditorialPass._analyze_content([]),
        language=Language.UZ,
    )
    assert any(s.slide_type is SlideType.INTERACTIVE_QUIZ_MCQ for s in interactive)
    quiz_slide = next(s for s in interactive if s.slide_type is SlideType.INTERACTIVE_QUIZ_MCQ)
    assert quiz_slide.content.quiz_questions is not None
    assert any(opt.is_correct for opt in quiz_slide.content.quiz_questions[0].options)


@pytest.mark.asyncio
async def test_generate_interactive_matching_from_people() -> None:
    payload = {
        "quiz_questions": [
            {
                "question": "Q?",
                "options": [
                    {"text": "yes", "is_correct": True},
                    {"text": "no", "is_correct": False},
                ],
                "explanation_correct": "ok",
                "explanation_wrong": "no",
            }
        ],
        "matching_pairs": [
            {"left": "Newton", "right": "Laws of motion"},
            {"left": "Leibniz", "right": "Calculus notation"},
            {"left": "Euler", "right": "Euler's identity"},
        ],
    }
    gemini = _StubLLM([json.dumps(payload)])
    pass_ = EditorialPass(gemini=gemini)  # type: ignore[arg-type]
    analysis = EditorialPass._analyze_content(
        [
            _claim("Newton's laws explain classical motion."),
            _claim("Leibniz proposed the notation for calculus."),
            _claim("Euler unified analysis with his identity."),
        ]
    )
    interactive = await pass_._generate_interactive_slides(
        content_slides=[_slide(SlideType.GALLERY_PEOPLE, "Thinkers")],
        analysis=analysis,
        language=Language.EN,
    )
    matching = next(s for s in interactive if s.slide_type is SlideType.INTERACTIVE_MATCHING)
    assert matching.content.matching_pairs is not None
    assert len(matching.content.matching_pairs) >= 2


@pytest.mark.asyncio
async def test_generate_interactive_skipped_when_disabled() -> None:
    gemini = _StubLLM([])  # if called, would raise
    pass_ = EditorialPass(
        llm=_StubLLM([_llm_slides_payload([_minimal_slide_payload("title_hero")])]),  # type: ignore[arg-type]
        gemini=gemini,  # type: ignore[arg-type]
    )
    interview = _interview(include_interactive=False)
    deck = await pass_.generate_deck_spec(
        interview=interview,
        design=_design(),
        evidence_matrix=_evidence_matrix(),
        claims=[],
        chunks=[],
        source_metadata=[],
    )
    assert all(s.slide_type not in {SlideType.INTERACTIVE_QUIZ_MCQ} for s in deck.slides)
    assert gemini.calls == []


# ---------------------------------------------------------------------------
# Merge
# ---------------------------------------------------------------------------


def _minimal_slide_payload(
    slide_type: str, title: str = "Headline", *, subtitle: str | None = None
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "slide_index": 0,
        "slide_type": slide_type,
        "title": title,
        "narrative_role": "hook",
    }
    if subtitle is not None:
        payload["subtitle"] = subtitle
    return payload


def test_merge_inserts_before_section_breaks() -> None:
    content = [
        _slide(SlideType.TITLE_HERO, "Title"),
        _slide(SlideType.CONTENT_SPLIT, "A"),
        _slide(SlideType.SECTION_BREAK, "•"),
        _slide(SlideType.CONTENT_SPLIT, "B"),
        _slide(SlideType.SECTION_BREAK, "•"),
    ]
    interactive = [
        _slide(SlideType.INTERACTIVE_QUIZ_MCQ, "Quiz 1"),
        _slide(SlideType.INTERACTIVE_MATCHING, "Match 1"),
    ]
    merged = EditorialPass._merge_slides(content, interactive)
    types = [s.slide_type for s in merged]
    # Each interactive slide should appear immediately before a section break.
    quiz_idx = types.index(SlideType.INTERACTIVE_QUIZ_MCQ)
    match_idx = types.index(SlideType.INTERACTIVE_MATCHING)
    assert types[quiz_idx + 1] is SlideType.SECTION_BREAK
    assert types[match_idx + 1] is SlideType.SECTION_BREAK


def test_merge_reindexes_correctly() -> None:
    content = [
        _slide(SlideType.TITLE_HERO, "Title"),
        _slide(SlideType.SECTION_BREAK, "•"),
        _slide(SlideType.CONTENT_SPLIT, "Body"),
    ]
    interactive = [_slide(SlideType.INTERACTIVE_QUIZ_MCQ, "Quiz")]
    merged = EditorialPass._merge_slides(content, interactive)
    assert [s.slide_index for s in merged] == list(range(len(merged)))


# ---------------------------------------------------------------------------
# Full pipeline (LLM mocked)
# ---------------------------------------------------------------------------


def _full_pipeline_payload() -> str:
    slides = [
        _minimal_slide_payload("title_hero", "Water savings reach 94.4% in mild climates"),
        _minimal_slide_payload("concept_definition", "Direct evaporative cooling defined"),
        _minimal_slide_payload("data_emphasis", "94.4% water savings demonstrated"),
        # Thesis-bearing section break: under invariant I2 a bare "Method" is
        # dropped; the subtitle states the section's argument so it earns its
        # place and survives _drop_hollow_dividers in _post_process.
        _minimal_slide_payload(
            "section_break",
            "Method",
            subtitle="Three pilots, one protocol, identical instrumentation.",
        ),
        _minimal_slide_payload("flow_process", "Three-stage cooling pipeline"),
        _minimal_slide_payload("content_split", "Pilot results across climates"),
        _minimal_slide_payload("summary_takeaway", "Three lessons from the pilot"),
    ]
    return _llm_slides_payload(slides)


@pytest.mark.asyncio
async def test_generate_deck_spec_full_pipeline() -> None:
    llm = _StubLLM([_full_pipeline_payload()])
    gemini = _StubLLM([])  # interactive disabled
    pass_ = EditorialPass(llm=llm, gemini=gemini)  # type: ignore[arg-type]
    claims = [
        _claim(
            f"Empirical finding {i} established in pilot studies.",
            claim_type=ClaimType.EMPIRICAL_FINDING,
            strength=ClaimStrength.STRONG,
        )
        for i in range(20)
    ]
    deck = await pass_.generate_deck_spec(
        interview=_interview(include_interactive=False, talk_duration_minutes=10),
        design=_design(),
        evidence_matrix=_evidence_matrix(),
        claims=claims,
        chunks=[],
        source_metadata=[],
    )
    assert isinstance(deck, DeckSpec)
    assert deck.slides[0].slide_type is SlideType.TITLE_HERO
    section_breaks = [s for s in deck.slides if s.slide_type is SlideType.SECTION_BREAK]
    assert len(section_breaks) >= 1
    for prev, curr in pairwise(deck.slides):
        if prev.slide_type is not SlideType.SECTION_BREAK:
            assert (
                prev.slide_type is not curr.slide_type or curr.slide_type is SlideType.SECTION_BREAK
            )


@pytest.mark.asyncio
async def test_generate_deck_spec_no_outline() -> None:
    llm = _StubLLM([_full_pipeline_payload()])
    pass_ = EditorialPass(llm=llm)  # type: ignore[arg-type]
    deck = await pass_.generate_deck_spec(
        interview=_interview(include_interactive=False),
        design=_design(),
        evidence_matrix=_evidence_matrix(),
        claims=[_claim("A finding that matters.")],
        chunks=[],
        source_metadata=[],
        outline=None,
    )
    assert len(deck.slides) >= 1


@pytest.mark.asyncio
async def test_generate_deck_spec_empty_claims_returns_minimal_deck() -> None:
    llm = _StubLLM(["not json"] * 2)
    pass_ = EditorialPass(llm=llm)  # type: ignore[arg-type]
    deck = await pass_.generate_deck_spec(
        interview=_interview(include_interactive=False),
        design=_design(),
        evidence_matrix=_evidence_matrix(),
        claims=[],
        chunks=[],
        source_metadata=[],
    )
    assert deck.slides[0].slide_type is SlideType.TITLE_HERO
    assert len(deck.slides) >= 1


@pytest.mark.asyncio
async def test_generate_deck_spec_language_preserved() -> None:
    llm = _StubLLM([_full_pipeline_payload()])
    pass_ = EditorialPass(llm=llm)  # type: ignore[arg-type]
    deck = await pass_.generate_deck_spec(
        interview=_interview(language=Language.RU, include_interactive=False),
        design=_design(),
        evidence_matrix=_evidence_matrix(),
        claims=[_claim("Empirical claim.")],
        chunks=[],
        source_metadata=[],
    )
    assert deck.language is Language.RU


@pytest.mark.asyncio
async def test_generate_deck_spec_export_formats() -> None:
    llm = _StubLLM([_full_pipeline_payload()])
    pass_ = EditorialPass(llm=llm)  # type: ignore[arg-type]
    deck = await pass_.generate_deck_spec(
        interview=_interview(include_interactive=False),
        design=_design(),
        evidence_matrix=_evidence_matrix(),
        claims=[_claim("Empirical claim.")],
        chunks=[],
        source_metadata=[],
    )
    assert ExportFormat.HTML in deck.export_formats


# ---------------------------------------------------------------------------
# Model routing (Sonnet for editorial, Gemini for interactive)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_editorial_uses_sonnet_model() -> None:
    llm = _StubLLM([_full_pipeline_payload()])

    captured: dict[str, str] = {}

    original = llm.complete

    async def capture_complete(
        system: str,
        user: str,
        model: str = SONNET_MODEL,
        max_tokens: int = 2000,
        temperature: float = 0.0,
    ) -> LLMResponse:
        captured["model"] = model
        return await original(system, user, model, max_tokens, temperature)

    # Manually patch the bound method
    cast: Callable[..., Awaitable[LLMResponse]] = capture_complete
    llm.complete = cast  # type: ignore[assignment]

    pass_ = EditorialPass(llm=llm)  # type: ignore[arg-type]
    await pass_.generate_deck_spec(
        interview=_interview(include_interactive=False),
        design=_design(),
        evidence_matrix=_evidence_matrix(),
        claims=[_claim("Empirical claim.")],
        chunks=[],
        source_metadata=[],
    )
    assert captured.get("model") == SONNET_MODEL


@pytest.mark.asyncio
async def test_interactive_uses_gemini_flash_model() -> None:
    llm = _StubLLM([_full_pipeline_payload()])
    payload = {
        "quiz_questions": [
            {
                "question": "Q?",
                "options": [
                    {"text": "a", "is_correct": True},
                    {"text": "b", "is_correct": False},
                ],
                "explanation_correct": "ok",
                "explanation_wrong": "no",
            }
        ]
    }
    gemini = _StubLLM([json.dumps(payload)])

    captured: dict[str, str] = {}
    original = gemini.complete

    async def capture_complete(
        system: str,
        user: str,
        model: str = GEMINI_FLASH_MODEL,
        max_tokens: int = 2000,
        temperature: float = 0.0,
    ) -> LLMResponse:
        captured["model"] = model
        return await original(system, user, model, max_tokens, temperature)

    cast: Callable[..., Awaitable[LLMResponse]] = capture_complete
    gemini.complete = cast  # type: ignore[assignment]

    pass_ = EditorialPass(llm=llm, gemini=gemini)  # type: ignore[arg-type]
    await pass_.generate_deck_spec(
        interview=_interview(include_interactive=True),
        design=_design(),
        evidence_matrix=_evidence_matrix(),
        claims=[_claim("Empirical claim that matters.")],
        chunks=[],
        source_metadata=[],
    )
    assert captured.get("model") == GEMINI_FLASH_MODEL
