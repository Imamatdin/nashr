"""Behaviour tests for :class:`EditorialPass`.

All LLM calls are mocked via stub clients (per ``.claude/rules/testing.md``
only external LLM APIs may be mocked). Pure-Python helpers — content
analysis, narrative arc selection, slide-count estimation, post-processing —
are tested without any stubs.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from itertools import pairwise
from typing import Any
from uuid import uuid4

import pytest

from packages.core.enums import (
    AudienceType,
    AuditSeverity,
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
from packages.core.gemini import GEMINI_FLASH_3_5_MODEL
from packages.core.gemini_tools import ToolTurnResult
from packages.core.llm import LLMResponse
from packages.core.models.evidence import EvidenceMatrix
from packages.core.models.presentation import (
    AuditCheckResult,
    ColorPalette,
    DeckPlan,
    DeckSpec,
    DesignDirectionSpec,
    NarrativeArc,
    PlannedFigure,
    PlannedSection,
    PresentationInterviewAnswers,
    SlideContent,
    SlideSpec,
    StatItem,
    ThesisVerdict,
)
from packages.core.models.source import (
    SourceChunkCreate,
    SourceClaimCreate,
    SourceMetadataExtracted,
)
from packages.core.prompts import CONTENT_CRITIC_SYSTEM, EDITORIAL_SYSTEM
from packages.presentation.editorial import (
    SONNET_MODEL,
    WORD_LIMITS,
    EditorialContentCriticError,
    EditorialDeckPlanMismatchError,
    EditorialPass,
    EditorialSlideRegenError,
    _count_words_in_content,
    _critic_finding_union_key,
    _critique_unioned,
    _insert_breathing_after_data,
    _LLMSlide,
    _materialise_slides,
    _parse_editorial_response,
    _parse_interactive,
    _reindex,
    _splice_sections,
    _splice_single_slide,
    _union_critic_findings,
)
from packages.presentation.thesis_classifier import ThesisClassifier
from tests.unit.test_brain_loop import _fix_turn, _reply_turn

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
        timeout: int | None = None,
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


class _StubGemini:
    """Routes editorial's Gemini calls by prompt so one stub serves both passes.

    The content-critic call shares editorial's Gemini client; it is identified by
    its system prompt and answered with scripted critic findings — EMPTY by
    default, so the critic is a no-op unless a test scripts otherwise via the
    ``critic`` factory arg. Every other call (the interactive pass) is delegated
    to the scripted interactive stub, preserving the historical ``gemini=``
    semantics.
    """

    def __init__(
        self,
        *,
        critic: list[str] | None = None,
        interactive: _StubLLM | None = None,
        brain: list[ToolTurnResult] | None = None,
    ) -> None:
        self._critic = list(critic) if critic is not None else None
        self._interactive = interactive if interactive is not None else _StubLLM([])
        self._brain = list(brain) if brain is not None else None
        self.critic_calls = 0
        self.brain_calls = 0

    async def complete(
        self,
        system: str,
        user: str,
        model: str = GEMINI_FLASH_3_5_MODEL,
        max_tokens: int = 2000,
        temperature: float = 0.0,
    ) -> LLMResponse:
        if system == CONTENT_CRITIC_SYSTEM:
            self.critic_calls += 1
            text = self._critic.pop(0) if self._critic else '{"findings": []}'
            return LLMResponse(
                content=text,
                model=model,
                input_tokens=10,
                output_tokens=5,
                latency_ms=1,
                estimated_cost_usd=0.0,
            )
        return await self._interactive.complete(
            system, user, model=model, max_tokens=max_tokens, temperature=temperature
        )

    async def generate_with_tools(
        self,
        contents: list[Any],
        tools: list[Any],
        *,
        system: str | None = None,
        max_tokens: int = 8192,
        tool_mode: Any = None,
        allowed_function_names: list[str] | None = None,
        **_: Any,
    ) -> ToolTurnResult:
        # The Way 1 brain fix pass shares editorial's Gemini client. Default: a
        # terminal reply with NO fixes, so the escalation is a no-op and the
        # existing hard stop fires unchanged unless a test scripts brain fixes.
        del contents, tools, system, max_tokens, tool_mode, allowed_function_names
        self.brain_calls += 1
        if self._brain:
            return self._brain.pop(0)
        return _reply_turn("")


class _StubPlanner:
    """Returns canned DeckPlan(s) without an LLM call; records re-plan feedback.

    A single plan is reused for every call; a list replays in order with the
    last entry repeating, so the plan-reject retry test can hand back a first
    (rejected) plan then a second (accepted) one.
    """

    def __init__(self, plans: DeckPlan | list[DeckPlan]) -> None:
        self._plans = [plans] if isinstance(plans, DeckPlan) else list(plans)
        self.calls = 0
        self.last_feedback: list[AuditCheckResult] | None = None

    async def plan_deck(
        self,
        interview: PresentationInterviewAnswers,
        claims: list[SourceClaimCreate],
        chunks: list[SourceChunkCreate],
        source_metadata: list[SourceMetadataExtracted],
        feedback: list[AuditCheckResult] | None = None,
    ) -> DeckPlan:
        del interview, claims, chunks, source_metadata
        self.calls += 1
        self.last_feedback = feedback
        if len(self._plans) > 1:
            return self._plans.pop(0)
        return self._plans[0]


class _StubClassifier(ThesisClassifier):
    """Replays verdict lists without a Gemini call. Defaults to all-pass."""

    def __init__(self, scripts: list[list[ThesisVerdict]] | None = None) -> None:
        super().__init__(gemini=None)
        self._scripts = scripts
        self.call_count = 0

    async def classify(  # type: ignore[override]
        self,
        items: list[tuple[str, str]],
        language: Language,
    ) -> list[ThesisVerdict]:
        del language
        self.call_count += 1
        if self._scripts is None:
            return [ThesisVerdict(is_thesis=True, reason="ok") for _ in items]
        return self._scripts.pop(0)


def _section_phases(n: int) -> list[NarrativePhase]:
    """HOOK ... CLOSE with CORE between, so a stub plan reads as a real arc."""

    if n <= 1:
        return [NarrativePhase.CORE]
    return [
        NarrativePhase.HOOK
        if i == 0
        else NarrativePhase.CLOSE
        if i == n - 1
        else NarrativePhase.CORE
        for i in range(n)
    ]


def _stub_plan(n_sections: int = 2) -> DeckPlan:
    """A minimal, valid DeckPlan: ``n_sections`` figure-free sections that pass
    the plan validator (distinct theses, an opener and a closer)."""

    phases = _section_phases(n_sections)
    sections = [
        PlannedSection(
            section_name=f"Section {index}",
            thesis=f"Section {index} argues one specific, concrete point about the topic.",
            phase=phases[index],
            figure_names=[],
            planned_slide_types=[],
        )
        for index in range(n_sections)
    ]
    return DeckPlan(
        thesis="The deck makes one specific, concrete argument grounded in the source material.",
        audience_takeaway="The audience leaves able to state the core argument and its support.",
        sections=sections,
        figures=[],
        image_cohesion_note="A single coherent visual treatment shared across every slide.",
    )


def _editorial(
    llm: _StubLLM | None = None,
    *,
    gemini: _StubLLM | None = None,
    critic: list[str] | None = None,
    brain: list[ToolTurnResult] | None = None,
    plan: DeckPlan | list[DeckPlan] | None = None,
    planner: _StubPlanner | None = None,
    classifier: ThesisClassifier | None = None,
) -> EditorialPass:
    """EditorialPass wired with stub planner + classifier so generate_deck_spec
    never reaches a real planner/classifier LLM. The default plan is a valid
    2-section, figure-free plan; pass ``plan`` to override.

    The content critic shares editorial's Gemini client; it is stubbed to return
    NO findings by default (pass ``critic`` to script critic response bodies),
    while ``gemini`` continues to script the interactive pass."""

    if planner is None:
        planner = _StubPlanner(plan if plan is not None else _stub_plan())
    return EditorialPass(
        llm=llm,  # type: ignore[arg-type]
        gemini=_StubGemini(critic=critic, interactive=gemini, brain=brain),  # type: ignore[arg-type]
        planner=planner,  # type: ignore[arg-type]
        classifier=classifier if classifier is not None else _StubClassifier(),
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


def _parse_slides(text: str) -> list[_LLMSlide] | None:
    """Slides-only view of a parsed editorial response, for tests that do not
    assert on the retry feedback (the production parser is _parse_editorial_response)."""

    return _parse_editorial_response(text).slides


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

    parsed = _parse_slides(_llm_slides_payload([slide_payload]))
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


def test_table_emphasis_fields_parse_and_materialise() -> None:
    # _LLMSlide uses extra="ignore"; if it stops declaring these the executor's
    # authored emphasis is silently dropped and the gate's executor count is 0.
    content = _materialise_one(
        {
            "slide_index": 0,
            "slide_type": "table_compact",
            "title": "sCO2 wins on every dimension",
            "table_headers": ["Metric", "Air", "sCO2"],
            "table_rows": [{"cells": ["PUE", "1.55", "1.08"]}],
            "table_preferred_column": 2,
            "table_hero_row": 0,
        }
    )
    assert content.table_preferred_column == 2
    assert content.table_hero_row == 0


def test_stat_highlight_parses_and_materialises() -> None:
    content = _materialise_one(
        {
            "slide_index": 0,
            "slide_type": "data_emphasis",
            "title": "The headline number",
            "stats": [
                {"value": "1.08", "unit": "PUE", "label": "efficiency", "highlight": True},
                {"value": "1.55", "unit": "PUE", "label": "baseline"},
            ],
        }
    )
    assert content.stats is not None
    assert content.stats[0].highlight is True
    assert content.stats[1].highlight is False


def test_section_thesis_carried_from_plan() -> None:
    plan = _stub_plan(2)
    parsed = _parse_slides(
        _llm_slides_payload(
            [
                {
                    "slide_index": 0,
                    "section_index": 1,
                    "slide_type": "table_compact",
                    "title": "A results table",
                    "table_headers": ["Metric", "Air", "sCO2"],
                    "table_rows": [{"cells": ["PUE", "1.55", "1.08"]}],
                }
            ]
        )
    )
    assert parsed is not None
    slides = _materialise_slides(parsed, plan)
    assert slides[0].section_name == plan.sections[1].section_name
    assert slides[0].section_thesis == plan.sections[1].thesis


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
# Chart-selection rules (the editorial prompt's DATA-SHAPE → ENCODING block)
#
# The model picked zero-based bars by default for ratios and zero-laden series,
# producing misleading charts on the sCO2 deck. These tests pin the rules that
# replaced that behaviour:
#   (a) the EDITORIAL_SYSTEM prompt carries decision criteria for each of the
#       five recognised data shapes — failing if the rule text drifts;
#   (b) the materialise path round-trips the model's chart_type intact for
#       each shape, so a correctly-chosen encoding actually reaches the
#       renderer.
# A separate renderer-side guard (chart-guard.ts) is the backstop when the
# model still mis-picks — these tests assert the SOURCE-side fix.
# ---------------------------------------------------------------------------


def test_editorial_prompt_carries_chart_selection_decision_rules() -> None:
    # The prompt must instruct the model on encoding for each of the five
    # recognised data shapes. Assertions pin the actual decision criteria
    # (max/min ratio, "clustered well above zero", literal zeros, "single
    # dominant number", "ordered progression", "multi-series per category")
    # so a future change that deletes a rule is forced to update this test.
    prompt = EDITORIAL_SYSTEM
    # The decision block is named, so the contract is greppable.
    assert "DATA-SHAPE" in prompt and "ENCODING" in prompt
    # Rule 15 explicitly forbids defaulting to bar.
    assert "NEVER default to a zero-based bar" in prompt
    # Shape 1 — large spread (the only correct default for bar).
    assert "LARGE SPREAD FROM ZERO" in prompt
    assert "max/min" in prompt
    # Shape 2 — clustered ratios/indices, the PUE-near-1 case.
    assert "RATIO" in prompt and "CLUSTERED" in prompt
    assert "PUE 1.08" in prompt
    assert "compress these into near-equal columns" in prompt
    # Shape 3 — literal zeros, the heat-recovery case.
    assert "SERIES CONTAINING LITERAL ZEROES" in prompt
    assert "draws as no bar at all" in prompt
    # Shape 4 — single dominant number.
    assert "SINGLE DOMINANT NUMBER" in prompt
    assert "single_value" in prompt
    # Shape 5 — ordered progression: tightened to require THREE OR MORE
    # ordered points, with two-point comparisons routed away from line
    # (the bug that drew a payback "line" between two discrete categories).
    assert "ORDERED PROGRESSION" in prompt
    assert "THREE OR MORE points" in prompt
    assert "NEVER use line for two discrete categories" in prompt
    # Shape 6 — multi-series-per-category (grouped/stacked) is the ONLY
    # remaining bar-default case.
    assert "MULTI-SERIES PER CATEGORY" in prompt


def test_editorial_prompt_carries_subject_pick_guidance() -> None:
    # The renderer's chart-guard picks the slide's subject by matching a
    # series label inside the title; if the title names no subject the
    # picker falls back to a metric-polarity lexicon (PUE → min, efficiency
    # → max). The prompt must instruct the model to put the subject in the
    # title so (a) wins on the common case — without this, a slide titled
    # "Cooling efficiency compared" leaves the renderer guessing.
    prompt = EDITORIAL_SYSTEM
    assert "TITLE-SUBJECT ALIGNMENT" in prompt
    assert "the title MUST name that subject" in prompt
    # The PUE/efficiency lexicon is the deterministic fallback the prompt
    # explicitly names so the model knows what the renderer will do if the
    # title is generic.
    assert "lower-is-better" in prompt and "higher-is-better" in prompt
    assert "sCO₂ Achieves PUE 1.08" in prompt


def test_editorial_prompt_carries_people_field_placement_rule() -> None:
    # Rule 16 (Phase-2 run-2 fix): the people array is ONLY for gallery_people /
    # team_credits; the executor must not attach it elsewhere (the sCO2 leak put
    # a citation on a typographic_keywords slide). The strip is the hard layer,
    # this prompt rule is the soft one — pin its text so a future edit that drops
    # the rule is forced through this test, matching the DATA-SHAPE rule pins.
    prompt = EDITORIAL_SYSTEM
    assert "gallery_people and team_credits slides" in prompt
    assert 'NEVER attach "people" to any other slide type' in prompt
    assert "bibliographic citation" in prompt


def _chart_payload(chart_type: str, series: list[dict[str, Any]]) -> dict[str, Any]:
    """Return a minimal chart_data slide payload for the parser."""

    return {
        "slide_index": 0,
        "slide_type": "chart_data",
        "title": "Encoding round-trip",
        "chart_type": chart_type,
        "chart_series": series,
    }


@pytest.mark.parametrize(
    "shape_name, chart_type, series",
    [
        # Big spread from zero — bar is correct.
        (
            "big_spread_bar",
            "bar",
            [
                {"label": "Air", "value": 8, "unit": "kW/rack"},
                {"label": "Liquid", "value": 40, "unit": "kW/rack"},
                {"label": "sCO2", "value": 120, "unit": "kW/rack"},
            ],
        ),
        # Clustered ratios — model should emit single_value (or a non-chart
        # slide_type). Test pins that, if the model DOES emit single_value,
        # the type round-trips intact.
        (
            "pue_near_1_single_value",
            "single_value",
            [{"label": "Best PUE", "value": 1.08, "unit": "PUE"}],
        ),
        # Series with literal zeros — the editorial layer routes these away
        # from chart_data; but if the model picks single_value with one
        # headline (e.g. "current recovery: 0"), the round-trip must hold.
        (
            "zeros_single_value",
            "single_value",
            [
                {"label": "Current recovery", "value": 0, "unit": "%"},
                {"label": "Target", "value": 20, "unit": "%"},
            ],
        ),
        # Single dominant number.
        (
            "single_number",
            "single_value",
            [{"label": "Water saved", "value": 94.4, "unit": "%"}],
        ),
        # Two-point progression — line is the correct encoding.
        (
            "two_point_progression",
            "line",
            [
                {"label": "2020", "value": 12, "unit": "GW"},
                {"label": "2023", "value": 44, "unit": "GW"},
            ],
        ),
    ],
)
def test_materialise_preserves_chart_type_for_each_data_shape(
    shape_name: str,
    chart_type: str,
    series: list[dict[str, Any]],
) -> None:
    # When the LLM picks the right chart_type for a data shape, the
    # materialise path must NOT silently drop or rewrite it. This is the
    # same contract the existing chart_type_and_grouped_fields test pins,
    # extended across the five recognised data shapes so the wire is proven
    # end-to-end. The five shapes mirror the editorial prompt's decision
    # tree (DATA-SHAPE → ENCODING).
    del shape_name
    content = _materialise_one(_chart_payload(chart_type, series))
    assert content.chart_type is not None
    assert content.chart_type.value == chart_type
    assert content.chart_series is not None
    assert [p.value for p in content.chart_series] == [s["value"] for s in series]


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
# Misplaced-people strip (the Phase-2 run-2 sCO2 leak fix)
#
# Sibling of the object-figure clamp above. content.people is rendered ONLY by
# gallery_people and team_credits (PEOPLE_RENDERING_SLIDE_TYPES); the executor
# leaked a bibliographic citation into `people` on a typographic_keywords slide.
# _materialise_slides clamps the field off any slide type that does not render
# it — covering BOTH the main path and the section-repair path, which both
# funnel through _materialise_slides — and LOGS the drop so a still-leaking
# executor stays visible (no silent data loss).
# ---------------------------------------------------------------------------


def test_materialise_strips_people_from_non_people_slide_and_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING, logger="packages.presentation.editorial"):
        content = _materialise_one(
            {
                "slide_index": 0,
                "slide_type": "typographic_keywords",
                "title": "sCO2 thermodynamic advantages",
                "keywords": [{"term": "Brayton cycle", "explanation": "a supercritical CO2 loop"}],
                "people": [{"name": "Ahn, Y. et al."}],
            }
        )
    assert content.people is None  # stripped: keywords slides never render people
    assert content.keywords is not None  # the legitimate field is untouched
    stripped = [
        r for r in caplog.records if r.getMessage() == "editorial_stripped_misplaced_people"
    ]
    assert len(stripped) == 1
    assert stripped[0].dropped == ["Ahn, Y. et al."]
    assert stripped[0].slide_type == "typographic_keywords"


def test_materialise_preserves_people_on_gallery_and_team(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING, logger="packages.presentation.editorial"):
        gallery = _materialise_one(
            {
                "slide_index": 0,
                "slide_type": "gallery_people",
                "title": "Enlightenment thinkers",
                "people": [{"name": "Voltaire"}, {"name": "Montesquieu"}],
            }
        )
        team = _materialise_one(
            {
                "slide_index": 0,
                "slide_type": "team_credits",
                "title": "Credits",
                "people": [{"name": "A Student Author"}],
            }
        )
    assert gallery.people is not None
    assert [p.name for p in gallery.people] == ["Voltaire", "Montesquieu"]
    assert team.people is not None
    assert [p.name for p in team.people] == ["A Student Author"]
    assert "editorial_stripped_misplaced_people" not in caplog.text


async def test_generate_deck_spec_strips_misplaced_person_before_plan_gate() -> None:
    """End-to-end ordering proof: the executor leaks a non-rostered person onto a
    typographic_keywords slide, but the materialise-time strip removes it BEFORE
    the deck-vs-plan gate runs, so the deck passes with NO repair.

    The stub LLM has exactly ONE scripted response; a repair would request a
    second and raise "ran out of scripted responses". Generation succeeding on
    one call therefore proves the strip pre-empted the gate (no D-X1/D-X2 fired),
    which is the live-path ordering the fix depends on. The plan is figure-free,
    so an un-stripped 'Ahn' would be both non-rostered (D-X1) and misplaced
    (D-X2)."""

    payload = _llm_slides_payload(
        [
            {"slide_index": 0, "section_index": 0, "slide_type": "title_hero", "title": "Cooling"},
            {
                "slide_index": 1,
                "section_index": 0,
                "slide_type": "typographic_keywords",
                "title": "Key terms",
                "keywords": [{"term": "PUE", "explanation": "power usage effectiveness"}],
                "people": [{"name": "Ahn, Y. et al."}],
            },
            {
                "slide_index": 2,
                "section_index": 1,
                "slide_type": "summary_takeaway",
                "title": "Takeaways",
                "bullets": ["sCO2 cooling raises achievable rack density."],
            },
        ]
    )
    editorial = _editorial(_StubLLM([payload]), plan=_stub_plan(2))
    deck = await editorial.generate_deck_spec(
        interview=_interview(),
        design=_design(),
        evidence_matrix=_evidence_matrix(),
        claims=[_claim("sCO2 cooling reaches 120 kW per rack.")],
        chunks=[],
        source_metadata=[],
    )
    # The misplaced citation is gone deck-wide — no person survives on any slide.
    for slide in deck.slides:
        assert slide.content.people is None


# ---------------------------------------------------------------------------
# Stable slide identity through the pipeline (generation, reindex, merge, splice)
#
# slide_id is the durable address a single-slide regeneration will splice on; these
# pin that it is unique on a generated deck, that the persisted plan rides along,
# and that the identity survives the order-mutating steps — except a SECTION repair,
# which mints fresh ids (the reason per-slide regen must thread the id explicitly).
# ---------------------------------------------------------------------------


def _id_slide(section_name: str, title: str, slide_id: str | None = None) -> SlideSpec:
    fields: dict[str, Any] = {
        "slide_index": 0,
        "slide_type": SlideType.CONTENT_SPLIT,
        "content": SlideContent(title=title),
        "section_name": section_name,
    }
    if slide_id is not None:
        fields["slide_id"] = slide_id
    return SlideSpec(**fields)


async def test_generated_deck_assigns_unique_slide_ids() -> None:
    payload = _llm_slides_payload(
        [
            {"slide_index": 0, "section_index": 0, "slide_type": "title_hero", "title": "Cooling"},
            {
                "slide_index": 1,
                "section_index": 0,
                "slide_type": "concept_definition",
                "title": "Direct cooling defined",
                "body_text": "A definition grounded in the source.",
            },
            {
                "slide_index": 2,
                "section_index": 1,
                "slide_type": "summary_takeaway",
                "title": "Takeaways",
                "bullets": ["sCO2 cooling raises achievable rack density."],
            },
        ]
    )
    editorial = _editorial(_StubLLM([payload]), plan=_stub_plan(2))
    deck = await editorial.generate_deck_spec(
        interview=_interview(),
        design=_design(),
        evidence_matrix=_evidence_matrix(),
        claims=[_claim("sCO2 cooling reaches 120 kW per rack.")],
        chunks=[],
        source_metadata=[],
    )
    ids = [s.slide_id for s in deck.slides]
    assert all(ids)
    assert len(set(ids)) == len(ids)


async def test_generated_deck_persists_plan() -> None:
    plan = _stub_plan(2)
    payload = _llm_slides_payload(
        [
            {"slide_index": 0, "section_index": 0, "slide_type": "title_hero", "title": "Cooling"},
            {
                "slide_index": 1,
                "section_index": 1,
                "slide_type": "summary_takeaway",
                "title": "Takeaways",
                "bullets": ["sCO2 cooling raises achievable rack density."],
            },
        ]
    )
    editorial = _editorial(_StubLLM([payload]), plan=plan)
    deck = await editorial.generate_deck_spec(
        interview=_interview(),
        design=_design(),
        evidence_matrix=_evidence_matrix(),
        claims=[_claim("sCO2 cooling reaches 120 kW per rack.")],
        chunks=[],
        source_metadata=[],
    )
    assert deck.plan is not None
    assert deck.plan.thesis == plan.thesis
    assert [s.section_name for s in deck.plan.sections] == [s.section_name for s in plan.sections]


def test_reindex_preserves_slide_id_and_rewrites_index() -> None:
    slides = [
        _id_slide("Section 0", "A", slide_id="id-a"),
        _id_slide("Section 1", "B", slide_id="id-b"),
    ]  # both built with slide_index=0
    out = _reindex(slides)
    assert [s.slide_id for s in out] == ["id-a", "id-b"]
    assert [s.slide_index for s in out] == [0, 1]


def test_merge_slides_preserves_slide_ids() -> None:
    content = [
        _id_slide("Section 0", "A", slide_id="id-a"),
        SlideSpec(
            slide_id="id-break",
            slide_index=1,
            slide_type=SlideType.SECTION_BREAK,
            content=SlideContent(title="Break", subtitle="A real section thesis here."),
        ),
    ]
    interactive = [
        SlideSpec(
            slide_id="id-quiz",
            slide_index=0,
            slide_type=SlideType.INTERACTIVE_QUIZ_MCQ,
            content=SlideContent(title="Quiz"),
        ),
    ]
    merged = EditorialPass._merge_slides(content, interactive)
    assert {"id-a", "id-break", "id-quiz"} <= {s.slide_id for s in merged}


def test_splice_sections_preserves_nonfailing_ids_and_replaces_failing() -> None:
    plan = _stub_plan(2)  # canonical section names "Section 0", "Section 1"
    content = [
        _id_slide("Section 0", "Old A", slide_id="old-a"),
        _id_slide("Section 1", "Keep B", slide_id="keep-b"),
    ]
    replacements = [_id_slide("Section 0", "New A", slide_id="new-a")]
    spliced = _splice_sections(content, replacements, {0}, plan)
    ids = [s.slide_id for s in spliced]
    assert "keep-b" in ids  # non-failing section survives untouched
    assert "new-a" in ids  # failing section replaced by the regenerated slide
    assert "old-a" not in ids  # the old failing slide's id is gone (fresh id minted)


# ---------------------------------------------------------------------------
# Editorial validation coercion (the resilience net)
#
# The editorial schema is intentionally tighter than the model's natural
# output, so a SINGLE bad field on a SINGLE slide used to fail _LLMSequence
# validation and collapse the whole deck to the 2-slide "Insufficient source
# material" fallback. _parse_editorial_response now salvages the recurring failure
# modes — an over-long string and a slide missing its title — and re-validates
# once, falling back only when the output is genuinely unusable. These tests
# lock that behaviour: a fixable field must never throw away the deck, and a
# real defect must still fall back (coercion must not mask it).
# ---------------------------------------------------------------------------


def test_overlong_unit_is_truncated_not_whole_deck_rejected() -> None:
    parsed = _parse_slides(
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
    parsed = _parse_slides(
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
    parsed = _parse_slides(
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
    parsed = _parse_slides(
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
    parsed = _parse_slides(
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
    parsed = _parse_slides(
        _llm_slides_payload(
            [{"slide_index": 0, "slide_type": "not_a_real_slide_type", "title": "x"}]
        )
    )
    assert parsed is None


def _coercible_payload() -> str:
    """A realistic editorial response carrying both salvageable violations:
    one slide with an over-long stat unit and one slide with a null title."""

    slides = [
        _minimal_slide_payload(
            "title_hero", "Water savings reach 94.4% in mild climates", section_index=0
        ),
        _minimal_slide_payload(
            "concept_definition", "Direct evaporative cooling defined", section_index=0
        ),
        {
            "slide_index": 2,
            "section_index": 0,
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
        _minimal_slide_payload("section_break", "Method", section_index=1),
        {
            "slide_index": 4,
            "section_index": 1,
            "slide_type": "content_split",
            "title": None,
            "body_text": "A three-stage pipeline moves heat off the rack into a dry cooler.",
            "narrative_role": "core",
        },
        _minimal_slide_payload("summary_takeaway", "Three lessons from the pilot", section_index=1),
    ]
    return _llm_slides_payload(slides)


@pytest.mark.asyncio
async def test_coercible_violations_yield_full_deck_not_fallback() -> None:
    # The regression that proves the CLASS is fixed, not just the instance: a
    # response with an over-long unit AND a null title must coerce to a FULL
    # multi-slide deck, never the 2-slide "insufficient source" fallback.
    llm = _StubLLM([_coercible_payload()])
    pass_ = _editorial(llm)
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
    pass_ = _editorial(llm)
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
# Schema-failure resilience: salvage an improvised field + informed retry
#
# _LLMSlide is extra="ignore", but its nested domain items (KeywordItem, ...)
# are extra="forbid", so a stray field on a NESTED item used to nuke the whole
# deck. The executor now (1) strips an extra_forbidden field in place — no
# retry, so a one-field trip cannot trigger a whole-deck resample that drops a
# different section's planned people (the run-4 Enlightenment cascade); and
# (2) on a NON-salvageable schema error, retries with the exact field errors
# translated into instructions, not a blind resample.
# ---------------------------------------------------------------------------


def test_extra_field_on_nested_item_is_stripped_not_whole_deck_rejected() -> None:
    # KeywordItem forbids extras; the model improvised `explanation_note`. Salvage
    # strips just that key and keeps the slide and its real fields intact.
    parsed = _parse_slides(
        _llm_slides_payload(
            [
                {"slide_index": 0, "slide_type": "title_hero", "title": "Cooling that pays"},
                {
                    "slide_index": 1,
                    "slide_type": "typographic_keywords",
                    "title": "Key terms",
                    "keywords": [
                        {
                            "term": "PUE",
                            "explanation": "power usage effectiveness",
                            "explanation_note": "a field the slide schema does not define",
                        }
                    ],
                },
            ]
        )
    )
    assert parsed is not None and len(parsed) == 2
    assert parsed[1].keywords is not None
    keyword = parsed[1].keywords[0]
    assert keyword.term == "PUE"
    assert keyword.explanation == "power usage effectiveness"


@pytest.mark.asyncio
async def test_extra_field_is_salvaged_in_place_without_a_retry() -> None:
    # The cascade-preventer: a stray nested field is stripped locally in ONE LLM
    # call. No retry means no whole-deck resample — the run-4 failure was a
    # blind retry re-rolling the deck and dropping a different section's people.
    payload = _llm_slides_payload(
        [
            {"slide_index": 0, "slide_type": "title_hero", "title": "Cooling"},
            {
                "slide_index": 1,
                "slide_type": "typographic_keywords",
                "title": "Terms",
                "keywords": [
                    {
                        "term": "PUE",
                        "explanation": "power usage effectiveness",
                        "explanation_note": "x",
                    }
                ],
            },
        ]
    )
    stub = _StubLLM([payload])  # exactly ONE scripted response — a retry would exhaust it
    editorial = _editorial(stub)
    slides = await editorial._call_editorial_with_retry("sys", "user")
    assert len(stub.calls) == 1
    assert len(slides) == 2


@pytest.mark.asyncio
async def test_schema_failure_drives_informed_retry_naming_the_field() -> None:
    # An unknown slide_type is NOT salvageable (no right value to guess), so the
    # retry fires; it must NAME the offending field, not blindly resample. The
    # pre-existing blind suffix carried nothing about what failed.
    bad = _llm_slides_payload([{"slide_index": 0, "slide_type": "not_a_real_type", "title": "x"}])
    good = _llm_slides_payload(
        [{"slide_index": 0, "slide_type": "title_hero", "title": "Cooling that pays"}]
    )
    stub = _StubLLM([bad, good])
    editorial = _editorial(stub)
    slides = await editorial._call_editorial_with_retry("sys", "USERPROMPT")
    assert slides is not None and len(slides) == 1
    assert len(stub.calls) == 2
    retry_prompt = stub.calls[1][1]
    assert "slide_type" in retry_prompt
    # The schema-failure header, not the malformed-JSON suffix.
    assert "FAILED schema validation" in retry_prompt


def test_post_coercion_feedback_names_remaining_error_not_stripped_field() -> None:
    # Both a salvageable stray field AND a non-salvageable enum on one slide: the
    # retry feedback must name what is STILL wrong (slide_type) after coercion,
    # never the field coercion already removed (explanation_note).
    result = _parse_editorial_response(
        _llm_slides_payload(
            [
                {
                    "slide_index": 0,
                    "slide_type": "not_a_real_type",
                    "title": "x",
                    "keywords": [{"term": "PUE", "explanation": "ok", "explanation_note": "stray"}],
                }
            ]
        )
    )
    assert result.slides is None
    assert result.schema_feedback is not None
    assert "slide_type" in result.schema_feedback
    assert "explanation_note" not in result.schema_feedback


def test_interactive_extra_field_on_nested_item_is_stripped() -> None:
    # Same disease as the slide path: MatchingPair is extra="forbid", so an
    # improvised field on a pair used to nuke the interactive response. Salvage
    # strips just that key and keeps the pair (so the INTERACTIVE_MATCHING bar
    # survives a stray field).
    result = _parse_interactive(
        json.dumps(
            {
                "matching_pairs": [
                    {"left": "PUE", "right": "power usage effectiveness", "note": "improvised"}
                ]
            }
        )
    )
    assert result.content is not None
    assert result.schema_feedback is None
    assert result.content.matching_pairs is not None
    assert result.content.matching_pairs[0].left == "PUE"
    assert result.content.matching_pairs[0].right == "power usage effectiveness"


@pytest.mark.asyncio
async def test_interactive_schema_failure_drives_informed_retry() -> None:
    # A non-salvageable interactive schema error (a quiz question missing required
    # fields) must drive a retry whose prompt names the offending field — the same
    # informed retry the slide executor got, so the interactive pass is no longer
    # the un-inoculated component on the INTERACTIVE_MATCHING bar.
    bad = json.dumps({"quiz_questions": [{"question": "Q?", "explanation_correct": "x"}]})
    good = json.dumps({"matching_pairs": [{"left": "A", "right": "B"}]})
    stub = _StubLLM([bad, good])
    editorial = _editorial(gemini=stub)
    content = await editorial._call_interactive_with_retry("sys", "USERPROMPT")
    assert content is not None
    assert len(stub.calls) == 2
    retry_prompt = stub.calls[1][1]
    assert "options" in retry_prompt
    assert "FAILED schema validation" in retry_prompt


# ---------------------------------------------------------------------------
# Section repair: keep the planned figures (defense-in-depth + the backstop)
# ---------------------------------------------------------------------------


def _figure_plan() -> DeckPlan:
    """A plan whose first section MUST portray a real figure, second is a closer."""

    return DeckPlan(
        thesis="The deck makes one specific, concrete argument grounded in the source.",
        audience_takeaway="The audience leaves able to state the core argument and its support.",
        sections=[
            PlannedSection(
                section_name="Thinkers",
                thesis="These named figures concretely reshaped the period's debate.",
                phase=NarrativePhase.CORE,
                figure_names=["Adam Smit"],
                planned_slide_types=[SlideType.GALLERY_PEOPLE],
            ),
            PlannedSection(
                section_name="Close",
                thesis="The argument lands on one concrete, actionable takeaway.",
                phase=NarrativePhase.CLOSE,
                figure_names=[],
                planned_slide_types=[SlideType.SUMMARY_TAKEAWAY],
            ),
        ],
        figures=[
            PlannedFigure(
                name="Adam Smit",
                years="1723-1790",
                why_in_source="The source names Smith as a central figure of the section.",
            )
        ],
        image_cohesion_note="A single coherent visual treatment shared across every slide.",
    )


def _arc() -> NarrativeArc:
    return NarrativeArc(
        phases=[NarrativePhase.HOOK, NarrativePhase.CORE, NarrativePhase.CLOSE],
        emphasis_phase=NarrativePhase.CORE,
    )


@pytest.mark.asyncio
async def test_repair_prompt_makes_required_figures_a_hard_constraint() -> None:
    # Defense-in-depth: a repair regenerating a section with planned figures must
    # be TOLD, as a hard requirement, to portray those exact people on a
    # gallery/timeline slide — listing them is not enough.
    plan = _figure_plan()
    stub = _StubLLM(['{"slides": []}'])  # content is irrelevant; we assert the PROMPT
    editorial = _editorial(stub, plan=plan)
    failing = [
        AuditCheckResult(
            check_id="D-F1",
            check_name="deck.figure_adherence",
            passed=False,
            severity=AuditSeverity.FAIL,
            slide_index=0,
            rule_reference="D-F1",
            message="Section 'Thinkers' planned figure 'Adam Smit' but no slide portrays them.",
        )
    ]
    content = [
        SlideSpec(
            slide_index=0,
            slide_type=SlideType.GALLERY_PEOPLE,
            section_name="Thinkers",
            content=SlideContent(title="Thinkers"),
        )
    ]
    await editorial._repair_failing_sections(_interview(), _arc(), plan, content, failing)
    repair_prompt = stub.calls[0][1]
    assert "Adam Smit" in repair_prompt
    assert "MUST appear on a gallery_people or timeline slide" in repair_prompt


@pytest.mark.asyncio
async def test_repair_that_still_drops_a_planned_figure_raises_not_ships() -> None:
    # The backstop: if the repair comes back STILL missing the section's planned
    # figure, re-validation must fail and the pass must RAISE — never ship a deck
    # that contradicts its plan. (This is the guarantee that held on run-4.)
    plan = _figure_plan()
    # The repair regenerates section 0 but again portrays nobody.
    repair_payload = _llm_slides_payload(
        [
            {
                "slide_index": 0,
                "section_index": 0,
                "slide_type": "gallery_people",
                "title": "Thinkers",
            }
        ]
    )
    editorial = _editorial(_StubLLM([repair_payload]), plan=plan)
    content = [
        SlideSpec(
            slide_index=0,
            slide_type=SlideType.GALLERY_PEOPLE,
            section_name="Thinkers",
            content=SlideContent(title="Thinkers"),
        ),
        SlideSpec(
            slide_index=1,
            slide_type=SlideType.SUMMARY_TAKEAWAY,
            section_name="Close",
            content=SlideContent(title="Close", bullets=["One concrete takeaway."]),
        ),
    ]
    with pytest.raises(EditorialDeckPlanMismatchError):
        await editorial._enforce_plan_adherence(
            _interview(), _arc(), plan, content, is_emergency=False
        )


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


def test_analyze_content_no_longer_derives_people_from_text() -> None:
    # Phase 2 deleted the hardcoded _PERSON_KEYWORDS roster. _analyze_content no
    # longer detects people from claim text; the figure roster now comes from
    # the source-grounded DeckPlan (generate_deck_spec regrounds
    # people_mentioned from plan.figures). This locks the keyword path dead.
    claims = [
        _claim("Newton's laws of motion underpin classical mechanics."),
        _claim("Leibniz independently developed calculus and proposed notation."),
        _claim("Euler unified analysis with his celebrated identity."),
    ]
    analysis = EditorialPass._analyze_content(claims)
    assert analysis.people_mentioned == []


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


def _plan_with_slide_types(n: int) -> DeckPlan:
    """A DeckPlan whose sections' planned_slide_types sum to exactly ``n``.

    Phase 2 sizes the deck from the plan, not the claim count, so the size
    tests feed a plan whose planned-slide-type total equals what the old
    claim count was. Types are distributed round-robin (each section capped at
    the field's max of 10) with every section getting at least one, so the
    plan-driven content base ``sum(max(1, len(types)))`` equals ``n``.
    """

    n_sections = max(2, min(8, -(-n // 10)))  # ceil(n / 10), clamped to [2, 8]
    per = [0] * n_sections
    placed = 0
    i = 0
    while placed < n and not all(count >= 10 for count in per):
        if per[i] < 10:
            per[i] += 1
            placed += 1
        i = (i + 1) % n_sections
    phases = _section_phases(n_sections)
    sections = [
        PlannedSection(
            section_name=f"Section {index}",
            thesis=f"Section {index} argues one specific, concrete point about the topic.",
            phase=phases[index],
            figure_names=[],
            planned_slide_types=[SlideType.CONTENT_SPLIT] * count,
        )
        for index, count in enumerate(per)
    ]
    return DeckPlan(
        thesis="The deck makes one specific, concrete argument grounded in the source material.",
        audience_takeaway="The audience leaves able to state the core argument and its support.",
        sections=sections,
        figures=[],
        image_cohesion_note="A single coherent visual treatment shared across every slide.",
    )


def _size(interview: PresentationInterviewAnswers, n_claims: int) -> int:
    return EditorialPass()._size_deck(interview, _plan_with_slide_types(n_claims))


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
    # people_mentioned now comes from the source-grounded DeckPlan roster, not a
    # keyword scan; simulate that reground so the matching selector (>= 3 people)
    # still fires. This is the second consumer of people_mentioned the Phase-2
    # review flagged — it must keep working when the field is plan-populated.
    analysis = EditorialPass._analyze_content(
        [
            _claim("Newton's laws explain classical motion."),
            _claim("Leibniz proposed the notation for calculus."),
            _claim("Euler unified analysis with his identity."),
        ]
    ).model_copy(update={"people_mentioned": ["Newton", "Leibniz", "Euler"]})
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
    gemini = _StubLLM([])  # if called, would raise — interactive disabled, and
    # the stub classifier never touches gemini, so it must stay untouched.
    pass_ = _editorial(_StubLLM([_full_pipeline_payload()]), gemini=gemini)
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
    slide_type: str, title: str = "Headline", *, subtitle: str | None = None, section_index: int = 0
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "slide_index": 0,
        "section_index": section_index,
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
    # section_index 0/1 fill the default _stub_plan's two sections so the
    # deck-vs-plan gate (D-S1 coverage) passes without a repair.
    slides = [
        _minimal_slide_payload(
            "title_hero", "Water savings reach 94.4% in mild climates", section_index=0
        ),
        _minimal_slide_payload(
            "concept_definition", "Direct evaporative cooling defined", section_index=0
        ),
        _minimal_slide_payload(
            "data_emphasis", "94.4% water savings demonstrated", section_index=0
        ),
        # Thesis-bearing section break: under invariant I2 a bare "Method" is
        # dropped; the subtitle states the section's argument so it earns its
        # place and survives _drop_hollow_dividers in _post_process.
        _minimal_slide_payload(
            "section_break",
            "Method",
            subtitle="Three pilots, one protocol, identical instrumentation.",
            section_index=1,
        ),
        _minimal_slide_payload("flow_process", "Three-stage cooling pipeline", section_index=1),
        _minimal_slide_payload("content_split", "Pilot results across climates", section_index=1),
        _minimal_slide_payload("summary_takeaway", "Three lessons from the pilot", section_index=1),
    ]
    return _llm_slides_payload(slides)


@pytest.mark.asyncio
async def test_generate_deck_spec_full_pipeline() -> None:
    llm = _StubLLM([_full_pipeline_payload()])
    gemini = _StubLLM([])  # interactive disabled
    pass_ = _editorial(llm, gemini=gemini)
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
    pass_ = _editorial(llm)
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
    pass_ = _editorial(llm)
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
    pass_ = _editorial(llm)
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
    pass_ = _editorial(llm)
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
        timeout: int | None = None,
    ) -> LLMResponse:
        captured["model"] = model
        return await original(system, user, model, max_tokens, temperature, timeout)

    # Manually patch the bound method
    cast: Callable[..., Awaitable[LLMResponse]] = capture_complete
    llm.complete = cast  # type: ignore[assignment]

    pass_ = _editorial(llm)
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
        model: str = GEMINI_FLASH_3_5_MODEL,
        max_tokens: int = 2000,
        temperature: float = 0.0,
    ) -> LLMResponse:
        captured["model"] = model
        return await original(system, user, model, max_tokens, temperature)

    cast: Callable[..., Awaitable[LLMResponse]] = capture_complete
    gemini.complete = cast  # type: ignore[assignment]

    pass_ = _editorial(llm, gemini=gemini)
    await pass_.generate_deck_spec(
        interview=_interview(include_interactive=True),
        design=_design(),
        evidence_matrix=_evidence_matrix(),
        claims=[_claim("Empirical claim that matters.")],
        chunks=[],
        source_metadata=[],
    )
    assert captured.get("model") == GEMINI_FLASH_3_5_MODEL


# ---------------------------------------------------------------------------
# Plan-adherence retry policy (Phase 2)
# ---------------------------------------------------------------------------


def _reject_then_accept(n: int) -> _StubClassifier:
    return _StubClassifier(
        scripts=[
            [ThesisVerdict(is_thesis=False, reason="label") for _ in range(n)],
            [ThesisVerdict(is_thesis=True, reason="ok") for _ in range(n)],
        ]
    )


@pytest.mark.asyncio
async def test_plan_rejected_triggers_one_replan_with_feedback() -> None:
    # First validation fails (classifier rejects every thesis), second passes.
    # The planner must be called twice, the second time WITH the findings fed
    # back; then generation proceeds normally.
    plan = _stub_plan()
    planner = _StubPlanner([plan, plan])
    pass_ = _editorial(
        _StubLLM([_full_pipeline_payload()]),
        planner=planner,
        classifier=_reject_then_accept(len(plan.sections)),
    )
    deck = await pass_.generate_deck_spec(
        interview=_interview(include_interactive=False),
        design=_design(),
        evidence_matrix=_evidence_matrix(),
        claims=[_claim("A finding that matters.")],
        chunks=[],
        source_metadata=[],
    )
    assert isinstance(deck, DeckSpec)
    assert planner.calls == 2
    assert planner.last_feedback is not None and len(planner.last_feedback) >= 1


@pytest.mark.asyncio
async def test_plan_rejected_twice_raises() -> None:
    from packages.presentation.editorial import EditorialPlanRejectedError

    plan = _stub_plan()
    n = len(plan.sections)
    classifier = _StubClassifier(
        scripts=[
            [ThesisVerdict(is_thesis=False, reason="label") for _ in range(n)],
            [ThesisVerdict(is_thesis=False, reason="label") for _ in range(n)],
        ]
    )
    pass_ = _editorial(
        _StubLLM([_full_pipeline_payload()]),
        planner=_StubPlanner([plan, plan]),
        classifier=classifier,
    )
    with pytest.raises(EditorialPlanRejectedError):
        await pass_.generate_deck_spec(
            interview=_interview(include_interactive=False),
            design=_design(),
            evidence_matrix=_evidence_matrix(),
            claims=[_claim("A finding that matters.")],
            chunks=[],
            source_metadata=[],
        )


@pytest.mark.asyncio
async def test_deck_mismatch_triggers_one_section_repair() -> None:
    # Initial executor output covers only section 0 (deck-vs-plan D-S1 fails for
    # section 1); the ONE repair call returns section 1's slide; the spliced
    # deck then passes. Two LLM responses: initial generation + the repair.
    initial = _llm_slides_payload(
        [
            _minimal_slide_payload("title_hero", "Opening", section_index=0),
            _minimal_slide_payload("content_split", "Section zero body", section_index=0),
        ]
    )
    repair = _llm_slides_payload(
        [_minimal_slide_payload("content_split", "Section one body", section_index=1)]
    )
    pass_ = _editorial(_StubLLM([initial, repair]), plan=_stub_plan())
    deck = await pass_.generate_deck_spec(
        interview=_interview(include_interactive=False),
        design=_design(),
        evidence_matrix=_evidence_matrix(),
        claims=[_claim("A finding that matters.")],
        chunks=[],
        source_metadata=[],
    )
    section_names = {s.section_name for s in deck.slides if s.section_name}
    assert "Section 0" in section_names
    assert "Section 1" in section_names  # the dropped section was repaired in


# ---------------------------------------------------------------------------
# Single-slide regeneration (regenerate_slide_content)
#
# The keystone of the engine arc: a type-preserving regen of ONE slide that the
# quality judge and the conversational edit layer drive. These pin the contract —
# identity/section/overrides/claim-ids inherited from the target, findings
# surfaced (not silently fixed), and the hard-stop errors — without a real LLM.
# ---------------------------------------------------------------------------


def _deck_with_plan(
    slides: list[SlideSpec] | None = None,
    plan: DeckPlan | None = None,
) -> DeckSpec:
    """A finished DeckSpec carrying a persisted plan, for single-slide regen tests."""

    plan = plan if plan is not None else _stub_plan(2)
    if slides is None:
        slides = [
            SlideSpec(
                slide_index=0,
                slide_type=SlideType.TITLE_HERO,
                content=SlideContent(title="Cooling that scales"),
                section_name="Section 0",
                section_thesis=plan.sections[0].thesis,
            ),
            SlideSpec(
                slide_index=1,
                slide_type=SlideType.CONTENT_SPLIT,
                content=SlideContent(title="Direct cooling", body_text="A first point."),
                section_name="Section 0",
                section_thesis=plan.sections[0].thesis,
            ),
            SlideSpec(
                slide_index=2,
                slide_type=SlideType.SUMMARY_TAKEAWAY,
                content=SlideContent(title="Takeaways", bullets=["One concrete lesson."]),
                section_name="Section 1",
                section_thesis=plan.sections[1].thesis,
            ),
        ]
    return DeckSpec(
        project_id="proj-1",
        title="Cooling that scales",
        design=_design(),
        interview=_interview(),
        plan=plan,
        slides=slides,
    )


async def test_regenerate_slide_preserves_type_id_and_section() -> None:
    deck = _deck_with_plan()
    target = deck.slides[1]
    payload = _llm_slides_payload(
        [
            {
                "slide_type": "content_split",
                "title": "Liquid cooling lifts achievable rack density",
                "body_text": "Direct-to-chip cooling clears far more heat per rack.",
            }
        ]
    )
    editorial = _editorial(_StubLLM([payload]))
    result = await editorial.regenerate_slide_content(
        deck, target.slide_id, claims=[_claim("Liquid cooling lifts rack density.")]
    )
    assert result.passed
    assert result.slide.slide_id == target.slide_id
    assert result.slide.slide_type is SlideType.CONTENT_SPLIT
    assert result.slide.section_name == target.section_name
    assert result.slide.section_thesis == target.section_thesis
    assert result.slide.content.title == "Liquid cooling lifts achievable rack density"


async def test_regenerate_slide_inherits_source_claim_ids_when_model_omits_them() -> None:
    # Traceability floor: a regen must not silently strip the target's provenance.
    deck = _deck_with_plan()
    target = deck.slides[1].model_copy(update={"source_claim_ids": ["claim-1", "claim-2"]})
    deck = deck.model_copy(update={"slides": [deck.slides[0], target, deck.slides[2]]})
    payload = _llm_slides_payload(
        [{"slide_type": "content_split", "title": "New", "body_text": "x.", "source_claim_ids": []}]
    )
    editorial = _editorial(_StubLLM([payload]))
    result = await editorial.regenerate_slide_content(
        deck, target.slide_id, claims=[_claim("a grounding claim.")]
    )
    assert result.slide.source_claim_ids == ["claim-1", "claim-2"]


async def test_regenerate_slide_inherits_per_slide_overrides() -> None:
    deck = _deck_with_plan()
    target = deck.slides[1].model_copy(
        update={"background_override": BackgroundTreatment.DARK, "accent_override": "#FF0000"}
    )
    deck = deck.model_copy(update={"slides": [deck.slides[0], target, deck.slides[2]]})
    payload = _llm_slides_payload(
        [{"slide_type": "content_split", "title": "New", "body_text": "x."}]
    )
    editorial = _editorial(_StubLLM([payload]))
    result = await editorial.regenerate_slide_content(deck, target.slide_id, claims=[])
    assert result.slide.background_override is BackgroundTreatment.DARK
    assert result.slide.accent_override == "#FF0000"


async def test_regenerate_slide_flags_off_roster_person() -> None:
    plan = _stub_plan(2)  # empty figure roster — any named person is off-roster
    gallery = SlideSpec(
        slide_index=1,
        slide_type=SlideType.GALLERY_PEOPLE,
        content=SlideContent(title="Thinkers"),
        section_name="Section 0",
        section_thesis=plan.sections[0].thesis,
    )
    deck = _deck_with_plan(
        slides=[
            SlideSpec(
                slide_index=0,
                slide_type=SlideType.TITLE_HERO,
                content=SlideContent(title="T"),
                section_name="Section 0",
                section_thesis=plan.sections[0].thesis,
            ),
            gallery,
            SlideSpec(
                slide_index=2,
                slide_type=SlideType.SUMMARY_TAKEAWAY,
                content=SlideContent(title="End", bullets=["x."]),
                section_name="Section 1",
                section_thesis=plan.sections[1].thesis,
            ),
        ],
        plan=plan,
    )
    payload = _llm_slides_payload(
        [{"slide_type": "gallery_people", "title": "Thinkers", "people": [{"name": "Beethoven"}]}]
    )
    editorial = _editorial(_StubLLM([payload]))
    result = await editorial.regenerate_slide_content(deck, gallery.slide_id, claims=[])
    assert not result.passed
    assert any(f.check_id == "D-X1" for f in result.findings)


async def test_regenerate_slide_flags_type_change_without_forcing() -> None:
    deck = _deck_with_plan()
    target = deck.slides[1]  # content_split
    payload = _llm_slides_payload(
        [
            {
                "slide_type": "data_emphasis",
                "title": "Now a stat",
                "stats": [{"value": "94", "unit": "%", "label": "saved", "highlight": True}],
            }
        ]
    )
    editorial = _editorial(_StubLLM([payload]))
    result = await editorial.regenerate_slide_content(deck, target.slide_id, claims=[])
    assert not result.passed
    assert any(f.check_id == "R-T1" for f in result.findings)
    assert result.slide.slide_id == target.slide_id  # identity inherited even on a reject


async def test_regenerate_slide_enforces_word_limits() -> None:
    deck = _deck_with_plan()
    target = deck.slides[1]
    long_body = " ".join(["word"] * 300)
    payload = _llm_slides_payload(
        [{"slide_type": "content_split", "title": "Trim me", "body_text": long_body}]
    )
    editorial = _editorial(_StubLLM([payload]))
    result = await editorial.regenerate_slide_content(deck, target.slide_id, claims=[])
    limit = WORD_LIMITS.get(SlideType.CONTENT_SPLIT, 60)
    assert _count_words_in_content(result.slide.content) <= limit


async def test_regenerate_slide_brief_carries_cohesion_neighbors_claims_instruction() -> None:
    plan = _stub_plan(2)
    deck = _deck_with_plan(plan=plan)
    target = deck.slides[1]
    stub = _StubLLM(
        [_llm_slides_payload([{"slide_type": "content_split", "title": "x", "body_text": "y."}])]
    )
    editorial = _editorial(stub)
    await editorial.regenerate_slide_content(
        deck,
        target.slide_id,
        instruction="Make it punchier",
        claims=[_claim("Liquid cooling lifts rack density to 120 kW per rack.")],
    )
    system, user = stub.calls[-1]
    assert "content_split" in system  # the fixed type is pinned in the system prompt
    assert plan.thesis in user
    assert plan.image_cohesion_note in user
    assert "Make it punchier" in user
    assert "Liquid cooling lifts rack density" in user
    assert deck.slides[0].content.title in user  # previous-slide title
    assert deck.slides[2].content.title in user  # next-slide title


async def test_regenerate_slide_without_plan_raises() -> None:
    deck = _deck_with_plan().model_copy(update={"plan": None})
    editorial = _editorial(_StubLLM([]))
    with pytest.raises(EditorialSlideRegenError):
        await editorial.regenerate_slide_content(deck, deck.slides[0].slide_id, claims=[])


async def test_regenerate_slide_unknown_id_raises() -> None:
    deck = _deck_with_plan()
    editorial = _editorial(_StubLLM([]))
    with pytest.raises(EditorialSlideRegenError):
        await editorial.regenerate_slide_content(deck, "no-such-id", claims=[])


async def test_regenerate_slide_empty_llm_output_raises() -> None:
    deck = _deck_with_plan()
    target = deck.slides[1]
    editorial = _editorial(_StubLLM(["not json at all", "still not json"]))
    with pytest.raises(EditorialSlideRegenError):
        await editorial.regenerate_slide_content(deck, target.slide_id, claims=[])


async def test_regenerate_title_hero_keeps_type() -> None:
    deck = _deck_with_plan()
    target = deck.slides[0]  # title_hero
    payload = _llm_slides_payload(
        [{"slide_type": "title_hero", "title": "A sharper title", "subtitle": "A subtitle"}]
    )
    editorial = _editorial(_StubLLM([payload]))
    result = await editorial.regenerate_slide_content(deck, target.slide_id, claims=[])
    assert result.passed
    assert result.slide.slide_type is SlideType.TITLE_HERO
    assert result.slide.slide_id == target.slide_id


# ---------------------------------------------------------------------------
# Single-slide splice back into the deck (id-keyed) + title propagation
# ---------------------------------------------------------------------------


def test_splice_single_slide_replaces_by_id_preserves_order_and_reindexes() -> None:
    a = _id_slide("Section 0", "A", slide_id="id-a")
    b = _id_slide("Section 1", "B", slide_id="id-b")
    c = _id_slide("Section 1", "C", slide_id="id-c")
    new_b = _id_slide("Section 1", "B-revised", slide_id="id-b")
    out = _splice_single_slide([a, b, c], new_b)
    assert [s.slide_id for s in out] == ["id-a", "id-b", "id-c"]  # order preserved
    assert out[1].content.title == "B-revised"  # replaced by id
    assert out[0].content.title == "A" and out[2].content.title == "C"  # neighbours untouched
    assert [s.slide_index for s in out] == [0, 1, 2]  # reindexed


def test_splice_regenerated_title_hero_propagates_title_to_deck() -> None:
    deck = _deck_with_plan()
    title_slide = deck.slides[0]  # TITLE_HERO at position 0
    new_title = title_slide.model_copy(
        update={"content": SlideContent(title="A much sharper title", subtitle="And a subtitle")}
    )
    editorial = _editorial(_StubLLM([]))
    new_deck = editorial.splice_regenerated_slide(deck, new_title)
    assert new_deck.title == "A much sharper title"
    assert new_deck.subtitle == "And a subtitle"
    assert new_deck.slides[0].content.title == "A much sharper title"
    assert new_deck.plan is deck.plan  # plan rides along untouched


def test_splice_regenerated_non_title_slide_leaves_deck_title() -> None:
    deck = _deck_with_plan()
    content_slide = deck.slides[1]  # CONTENT_SPLIT, not the hero
    new_content = content_slide.model_copy(
        update={"content": SlideContent(title="A revised body slide")}
    )
    editorial = _editorial(_StubLLM([]))
    new_deck = editorial.splice_regenerated_slide(deck, new_content)
    assert new_deck.title == deck.title  # unchanged — only the hero drives the deck title
    assert new_deck.slides[1].content.title == "A revised body slide"


async def test_regenerate_slide_produces_null_image_urls_for_re_resolution() -> None:
    # The regenerated slide must carry NULL image URLs (only HINTS) so the scoped
    # downstream image re-run resolves exactly its slots — the precondition the
    # orchestrator's only_slide_ids scoping relies on. A target that ALREADY had
    # resolved URLs must not carry them forward onto the fresh slide.
    deck = _deck_with_plan()
    target = deck.slides[1].model_copy(
        update={
            "content": SlideContent(
                title="Has images",
                figure_url="https://cdn.example/f.png",
                background_url="https://cdn.example/b.png",
            )
        }
    )
    deck = deck.model_copy(update={"slides": [deck.slides[0], target, deck.slides[2]]})
    payload = _llm_slides_payload(
        [
            {
                "slide_type": "content_split",
                "title": "A revised, grounded point",
                "body_text": "Direct cooling clears more heat per rack.",
                "figure_prompt": "a liquid cold plate on a clean background",
            }
        ]
    )
    editorial = _editorial(_StubLLM([payload]))
    result = await editorial.regenerate_slide_content(deck, target.slide_id, claims=[])
    assert result.slide.content.figure_url is None  # no stale URL carried forward
    assert result.slide.content.background_url is None
    assert result.slide.content.figure_prompt is not None  # but the image HINT is present


# ---------------------------------------------------------------------------
# Content critic orchestration: routing, one-round re-judge, residual hard-stop
# ---------------------------------------------------------------------------


def _critic_response(findings: list[dict[str, Any]]) -> str:
    return json.dumps({"findings": findings})


def _fab_finding(handle: int, quote: str, token: str) -> dict[str, Any]:
    return {
        "slide_handle": handle,
        "category": "fabrication",
        "message": f"{token} is not supported by the source.",
        "evidence": {"slide_quote": quote, "unsupported_token": token, "second_quote": None},
    }


def _critic_content_slide(title: str, body: str, section_name: str, thesis: str) -> SlideSpec:
    return SlideSpec(
        slide_index=0,
        slide_type=SlideType.CONCEPT_DEFINITION,
        content=SlideContent(title=title, body_text=body),
        section_name=section_name,
        section_thesis=thesis,
    )


def _mixed_claims() -> list[SourceClaimCreate]:
    """A claim pool that supports NEITHER fabricated token in :func:`_mixed_fab_deck`."""

    return [_claim("The system reduced water and energy consumption during evaluation.")]


def _mixed_fab_deck(plan: DeckPlan) -> tuple[list[SlideSpec], _StubLLM, list[dict[str, Any]]]:
    """Two fabricating slides plus the regens for a MIXED round.

    Slide A is fixable — its regen keeps the type (CONCEPT_DEFINITION) and drops the
    fabricated figure, so it splices. Slide B is not — its regen changes the type
    (CONTENT_SPLIT), an R-T1 FAIL that is rejected, so the original is kept. Returns
    the two slides, a Sonnet stub scripting both regens in iteration order
    (A then B), and the two first-pass fabrication findings (handles 1 and 2).
    """

    slide_a = SlideSpec(
        slide_index=0,
        slide_type=SlideType.CONCEPT_DEFINITION,
        content=SlideContent(
            title="Water", body_text="Water savings reached 94.4 percent in field trials."
        ),
        section_name=plan.sections[0].section_name,
        section_thesis=plan.sections[0].thesis,
    )
    slide_b = SlideSpec(
        slide_index=1,
        slide_type=SlideType.CONCEPT_DEFINITION,
        content=SlideContent(
            title="Energy", body_text="Energy use dropped by 87.3 percent across all zones."
        ),
        section_name=plan.sections[1].section_name,
        section_thesis=plan.sections[1].thesis,
    )
    regen_a = _llm_slides_payload(
        [
            {
                "slide_index": 0,
                "section_index": 0,
                "slide_type": "concept_definition",
                "title": "Water",
                "body_text": "Water savings improved notably in field trials.",
                "narrative_role": "core",
            }
        ]
    )
    regen_b = _llm_slides_payload(
        [
            {
                "slide_index": 1,
                "section_index": 1,
                "slide_type": "content_split",
                "title": "Energy",
                "body_text": "Energy use improved across the evaluated zones.",
                "narrative_role": "core",
            }
        ]
    )
    fab_a = _fab_finding(1, "Water savings reached 94.4 percent in field trials.", "94.4 percent")
    fab_b = _fab_finding(2, "Energy use dropped by 87.3 percent across all zones.", "87.3 percent")
    return [slide_a, slide_b], _StubLLM([regen_a, regen_b]), [fab_a, fab_b]


async def test_content_critic_routes_fixes_and_preserves_slide_id() -> None:
    plan = _stub_plan()
    section = plan.sections[0]
    slide = _critic_content_slide(
        "Findings",
        "Water savings reached 94.4 percent in field trials.",
        section.section_name,
        section.thesis,
    )
    claims = [_claim("The system reduced water consumption during the evaluation period.")]
    regen = _llm_slides_payload(
        [
            {
                "slide_index": 0,
                "section_index": 0,
                "slide_type": "concept_definition",
                "title": "Findings",
                "body_text": "Water savings improved notably in field trials.",
                "narrative_role": "core",
            }
        ]
    )
    pass_ = _editorial(
        _StubLLM([regen]),
        critic=[
            _critic_response(
                [
                    _fab_finding(
                        1, "Water savings reached 94.4 percent in field trials.", "94.4 percent"
                    )
                ]
            ),
            _critic_response([]),  # union re-judge, pass 1: clean
            _critic_response([]),  # union re-judge, pass 2: clean
        ],
        plan=plan,
    )

    out = await pass_._enforce_content_critic(
        _interview(), _design(), plan, [slide], claims, "proj", is_emergency=False
    )

    assert len(out) == 1
    assert out[0].slide_id == slide.slide_id  # durable id preserved across regen + splice
    assert "94.4" not in (out[0].content.body_text or "")  # the fabricated fact is gone
    # first discovery critique + a two-pass UNION re-judge (a clean deck requires BOTH clean).
    assert pass_._gemini.critic_calls == 3


async def test_content_critic_residual_fabrication_raises() -> None:
    plan = _stub_plan()
    section = plan.sections[0]
    slide = _critic_content_slide(
        "Findings",
        "Water savings reached 94.4 percent in field trials.",
        section.section_name,
        section.thesis,
    )
    claims = [_claim("The system reduced water consumption during the evaluation period.")]
    # The regen "fails to fix" — it still asserts the fabricated figure.
    regen = _llm_slides_payload(
        [
            {
                "slide_index": 0,
                "section_index": 0,
                "slide_type": "concept_definition",
                "title": "Findings",
                "body_text": "Water savings reached 94.4 percent in field trials.",
                "narrative_role": "core",
            }
        ]
    )
    fab = _fab_finding(1, "Water savings reached 94.4 percent in field trials.", "94.4 percent")
    pass_ = _editorial(
        _StubLLM([regen]),
        # first discovery + a two-pass union re-judge (both re-flag) + the escalation-
        # entry extra pass — the fabrication survives every pass, so the hard stop fires.
        critic=[
            _critic_response([fab]),
            _critic_response([fab]),
            _critic_response([fab]),
            _critic_response([fab]),
        ],
        plan=plan,
    )

    with pytest.raises(EditorialContentCriticError) as exc:
        await pass_._enforce_content_critic(
            _interview(), _design(), plan, [slide], claims, "proj", is_emergency=False
        )
    assert any(f.check_id == "C-FB" for f in exc.value.findings)
    assert pass_._gemini.critic_calls == 4  # first + union re-judge (2) + escalation-entry extra


async def test_content_critic_warn_only_does_not_route() -> None:
    plan = _stub_plan()
    section = plan.sections[0]
    slide = _critic_content_slide(
        "Findings",
        "The programme has a long documented history of careful testing.",
        section.section_name,
        section.thesis,
    )
    claims = [_claim("The programme is documented across many years of careful testing work.")]
    pass_ = _editorial(
        _StubLLM([]),  # no regen scripted — must not be called
        critic=[
            _critic_response(
                [
                    {
                        "slide_handle": 1,
                        "category": "weak_craft",
                        "message": "Generic phrasing.",
                        "evidence": {
                            "slide_quote": "The programme has a long documented history of careful testing.",
                            "unsupported_token": None,
                            "second_quote": None,
                        },
                    }
                ]
            )
        ],
        plan=plan,
    )

    out = await pass_._enforce_content_critic(
        _interview(), _design(), plan, [slide], claims, "proj", is_emergency=False
    )

    assert out[0].slide_id == slide.slide_id  # unchanged
    assert pass_._gemini.critic_calls == 1  # no regen, no re-judge


async def test_content_critic_all_regens_rejected_short_circuits_to_hard_stop() -> None:
    plan = _stub_plan()
    section = plan.sections[0]
    slide = _critic_content_slide(
        "Findings",
        "Water savings reached 94.4 percent in field trials.",
        section.section_name,
        section.thesis,
    )
    claims = [_claim("The system reduced water consumption during the evaluation period.")]
    # The regen comes back with a DIFFERENT slide type -> R-T1 type-change FAIL ->
    # regen.passed is False -> the failing regen is NOT spliced and the original
    # (still-fabricated) slide is kept. With NO regen accepted, the re-judge could
    # only re-examine an unchanged slide, so it is SKIPPED entirely: the first-pass
    # code-confirmed hard-stop carries forward and fires on its own.
    regen = _llm_slides_payload(
        [
            {
                "slide_index": 0,
                "section_index": 0,
                "slide_type": "content_split",
                "title": "Findings",
                "body_text": "Water savings improved notably in field trials.",
                "narrative_role": "core",
            }
        ]
    )
    fab = _fab_finding(1, "Water savings reached 94.4 percent in field trials.", "94.4 percent")
    pass_ = _editorial(
        _StubLLM([regen]),
        # First discovery pass, then the escalation-entry extra pass — the union-of-two
        # for this unchanged state. No site-3 re-judge (no regen accepted) and no
        # re-critique loop (the brain has no fixes), so the standing hard stop fires.
        critic=[_critic_response([fab]), _critic_response([fab])],
        plan=plan,
    )

    with pytest.raises(EditorialContentCriticError) as exc:
        await pass_._enforce_content_critic(
            _interview(), _design(), plan, [slide], claims, "proj", is_emergency=False
        )
    assert any(f.check_id == "C-FB" for f in exc.value.findings)
    assert pass_._gemini.critic_calls == 2  # first discovery + escalation-entry extra


async def test_content_critic_skips_emergency_deck() -> None:
    plan = _stub_plan()
    emergency = [
        SlideSpec(
            slide_index=0,
            slide_type=SlideType.TITLE_HERO,
            content=SlideContent(title="A deck"),
        ),
        SlideSpec(
            slide_index=1,
            slide_type=SlideType.SUMMARY_TAKEAWAY,
            content=SlideContent(
                title="Insufficient source material",
                bullets=["Add more source material to generate a full deck."],
            ),
        ),
    ]
    claims = [_claim("Real claims exist, but the executor produced nothing usable.")]
    pass_ = _editorial(_StubLLM([]), plan=plan)

    out = await pass_._enforce_content_critic(
        _interview(), _design(), plan, emergency, claims, "proj", is_emergency=True
    )

    assert out is emergency  # returned unchanged
    assert pass_._gemini.critic_calls == 0  # the explicit emergency flag short-circuits


async def test_content_critic_runs_on_real_deck_matching_emergency_shape() -> None:
    """The RISK Codex flagged: a REAL deck whose shape matches the emergency
    fallback (a synthesized TITLE_HERO + a SUMMARY_TAKEAWAY titled exactly the
    sentinel, no section metadata) must STILL be critiqued. Emergency status is the
    explicit origin flag, never inferred from shape — so ``is_emergency=False`` here
    means every gate runs even though the shape is identical to the fallback's."""
    plan = _stub_plan()
    shaped_like_emergency = [
        SlideSpec(
            slide_index=0,
            slide_type=SlideType.TITLE_HERO,
            content=SlideContent(title="A deck"),
        ),
        SlideSpec(
            slide_index=1,
            slide_type=SlideType.SUMMARY_TAKEAWAY,
            content=SlideContent(
                title="Insufficient source material",
                bullets=["Add more source material to generate a full deck."],
            ),
        ),
    ]
    claims = [_claim("The deck has real source claims and a genuine summary slide.")]
    pass_ = _editorial(_StubLLM([]), plan=plan)  # critic defaults to clean findings

    out = await pass_._enforce_content_critic(
        _interview(), _design(), plan, shaped_like_emergency, claims, "proj", is_emergency=False
    )

    # The critic RAN (shape did not skip it); it found nothing -> deck returned as-is.
    assert pass_._gemini.critic_calls == 1
    assert out is shaped_like_emergency


async def test_content_critic_uncorrected_hard_stop_stands_when_rejudge_clean() -> None:
    """Divergence from a naive 'trust the re-judge' fix: a first-pass hard-stop on
    a slide whose regen was REJECTED stands even when the re-judge RAN successfully
    and returned NO findings. The unchanged slide's deterministic, code-confirmed
    verdict is not clearable by a stochastic re-judge that merely failed to
    re-propose it — clearing it would ship the known fabrication."""
    plan = _stub_plan()
    slides, llm, (fab_a, fab_b) = _mixed_fab_deck(plan)
    pass_ = _editorial(
        llm,
        # First pass flags both; the two-pass UNION re-judge is clean (it does not
        # re-flag corrected A), and the escalation-entry extra pass is clean too — so
        # only the UNCORRECTED slide B's standing hard stop survives.
        critic=[
            _critic_response([fab_a, fab_b]),
            _critic_response([]),
            _critic_response([]),
            _critic_response([]),
        ],
        plan=plan,
    )

    with pytest.raises(EditorialContentCriticError) as exc:
        await pass_._enforce_content_critic(
            _interview(),
            _design(),
            plan,
            slides,
            _mixed_claims(),
            "proj",
            is_emergency=False,
        )
    # Only the UNCORRECTED slide B stands; A was corrected and the clean union re-judge
    # legitimately cleared it.
    assert [f.slide_id for f in exc.value.findings] == [slides[1].slide_id]
    assert all(f.check_id == "C-FB" for f in exc.value.findings)
    assert pass_._gemini.critic_calls == 4  # first + union re-judge (2) + escalation-entry extra


async def test_content_critic_degraded_rejudge_keeps_all_first_pass_hard_stops() -> None:
    """The originally reported bug: after a mixed regen round, if the re-judge
    DEGRADES (unparseable after retry, ``llm_verified`` False), absence of a verdict
    must not clear a known fabrication — EVERY first-pass hard-stop stands, including
    the one on the corrected slide whose fix could not be re-verified."""
    plan = _stub_plan()
    slides, llm, (fab_a, fab_b) = _mixed_fab_deck(plan)
    pass_ = _editorial(
        llm,
        # First pass flags both. The two-pass UNION re-judge DEGRADES: its first pass
        # is unparseable after a retry (2 calls), its second pass is clean (1 call), so
        # the union is unverified — absence of a verdict must not clear a known
        # fabrication, so EVERY first-pass hard stop stands. The escalation-entry extra
        # pass is clean and adds nothing (the incoming set is already established).
        critic=[
            _critic_response([fab_a, fab_b]),
            "not valid json",
            "still not valid json",
            _critic_response([]),
            _critic_response([]),
        ],
        plan=plan,
    )

    with pytest.raises(EditorialContentCriticError) as exc:
        await pass_._enforce_content_critic(
            _interview(),
            _design(),
            plan,
            slides,
            _mixed_claims(),
            "proj",
            is_emergency=False,
        )
    # Both stand: B (uncorrected) AND A (corrected but the union re-judge could not confirm).
    assert {f.slide_id for f in exc.value.findings} == {slides[0].slide_id, slides[1].slide_id}
    assert all(f.check_id == "C-FB" for f in exc.value.findings)
    # first + union re-judge (one degraded pass = attempt+retry, one clean pass) + entry extra.
    assert pass_._gemini.critic_calls == 5


async def test_content_critic_brain_escalation_grounds_and_delivers() -> None:
    """Way 1: the Sonnet regen fails (type change), so nothing splices and the deck
    would refund. The brain escalation authors a grounding fix, the Sonnet regen this
    time grounds it, and the re-critique is clean — so the deck delivers, no refund."""
    plan = _stub_plan()
    section = plan.sections[0]
    slide = _critic_content_slide(
        "Findings",
        "Water savings reached 94.4 percent in field trials.",
        section.section_name,
        section.thesis,
    )
    claims = [_claim("The system reduced water consumption during the evaluation period.")]
    # The existing repair's regen changes type -> FAIL -> not spliced (site 1). The
    # brain's regen keeps the type and drops the fabricated figure -> passes -> splices.
    regen_fail = _llm_slides_payload(
        [
            {
                "slide_index": 0,
                "section_index": 0,
                "slide_type": "content_split",
                "title": "Findings",
                "body_text": "Water savings improved notably in field trials.",
                "narrative_role": "core",
            }
        ]
    )
    regen_grounded = _llm_slides_payload(
        [
            {
                "slide_index": 0,
                "section_index": 0,
                "slide_type": "concept_definition",
                "title": "Findings",
                "body_text": "Water savings improved notably in field trials.",
                "narrative_role": "core",
            }
        ]
    )
    fab = _fab_finding(1, "Water savings reached 94.4 percent in field trials.", "94.4 percent")
    pass_ = _editorial(
        _StubLLM([regen_fail, regen_grounded]),
        # first discovery flags; the escalation-entry extra re-flags the still-unchanged
        # slide; then the two-pass union re-critique on the brain-grounded deck is clean.
        critic=[
            _critic_response([fab]),
            _critic_response([fab]),
            _critic_response([]),
            _critic_response([]),
        ],
        brain=[
            _fix_turn(
                [
                    {
                        "slide_id": slide.slide_id,
                        "instruction": "Remove the unsupported 94.4 percent figure; state only grounded facts.",
                    }
                ]
            )
        ],
        plan=plan,
    )

    out = await pass_._enforce_content_critic(
        _interview(), _design(), plan, [slide], claims, "proj", is_emergency=False
    )

    assert len(out) == 1
    assert out[0].slide_id == slide.slide_id  # durable id preserved across the brain regen + splice
    assert "94.4" not in (out[0].content.body_text or "")  # the fabrication was grounded away
    assert pass_._gemini.brain_calls == 1  # the brain escalation engaged
    # first discovery + escalation-entry extra + a two-pass union re-critique.
    assert pass_._gemini.critic_calls == 4


async def test_content_critic_brain_escalation_fails_still_hard_stops() -> None:
    """Way 1 invariant: when the brain's fix ALSO fails to ground the fabrication, the
    re-critique still flags it and the UNCHANGED hard stop fires. Unfixable fabrication
    refunds, never ships — the brain strictly reduces refunds, never weakens the gate."""
    plan = _stub_plan()
    section = plan.sections[0]
    slide = _critic_content_slide(
        "Findings",
        "Water savings reached 94.4 percent in field trials.",
        section.section_name,
        section.thesis,
    )
    claims = [_claim("The system reduced water consumption during the evaluation period.")]
    regen_fail = _llm_slides_payload(
        [
            {
                "slide_index": 0,
                "section_index": 0,
                "slide_type": "content_split",
                "title": "Findings",
                "body_text": "Water savings improved notably in field trials.",
                "narrative_role": "core",
            }
        ]
    )
    # The brain's regen keeps the type (so it splices) but STILL asserts the fabrication,
    # so the re-critique re-flags it — the grounding never happened.
    regen_still_fab = _llm_slides_payload(
        [
            {
                "slide_index": 0,
                "section_index": 0,
                "slide_type": "concept_definition",
                "title": "Findings",
                "body_text": "Water savings reached 94.4 percent in field trials.",
                "narrative_role": "core",
            }
        ]
    )
    fab = _fab_finding(1, "Water savings reached 94.4 percent in field trials.", "94.4 percent")
    pass_ = _editorial(
        _StubLLM([regen_fail, regen_still_fab, regen_still_fab]),
        critic=[
            _critic_response([fab]),  # first discovery pass
            _critic_response([fab]),  # escalation-entry extra pass
            _critic_response([fab]),  # escalation loop 1: union re-critique, pass 1
            _critic_response([fab]),  # escalation loop 1: union re-critique, pass 2
            _critic_response([fab]),  # escalation loop 2: union re-critique, pass 1
            _critic_response([fab]),  # escalation loop 2: union re-critique, pass 2
        ],
        brain=[
            _fix_turn(
                [
                    {
                        "slide_id": slide.slide_id,
                        "instruction": "Ground the 94.4 percent claim in the source.",
                    }
                ]
            ),
            _fix_turn(
                [
                    {
                        "slide_id": slide.slide_id,
                        "instruction": "Drop the 94.4 percent figure; replace with: Water savings improved during field trials.",
                    }
                ]
            ),
        ],
        plan=plan,
    )

    with pytest.raises(EditorialContentCriticError) as exc:
        await pass_._enforce_content_critic(
            _interview(), _design(), plan, [slide], claims, "proj", is_emergency=False
        )

    assert any(f.check_id == "C-FB" for f in exc.value.findings)  # the hard stop still fires
    assert pass_._gemini.brain_calls == 3  # three escalation attempts (cap raised to 3)
    # first + escalation-entry extra + two union re-critiques inside the loop (2 passes each).
    assert pass_._gemini.critic_calls == 6


# ---------------------------------------------------------------------------
# Union-of-two verification critique (helpers + the four wired sites)
#
# Every VERIFICATION critique is a union of two independent passes on the SAME
# deck state, because the adversarial critic samples defects per pass. These pin
# the pure union helpers and the four sites (main re-judge, escalation entry +
# re-critique) so a single clean sample can never be mistaken for a clean deck.
# ---------------------------------------------------------------------------


def _audit_finding(
    check_id: str,
    *,
    slide_id: str | None = None,
    message: str | None = None,
    severity: AuditSeverity = AuditSeverity.FAIL,
) -> AuditCheckResult:
    return AuditCheckResult(
        check_id=check_id,
        check_name=f"content_critic.{check_id}",
        passed=False,
        severity=severity,
        slide_id=slide_id,
        message=message,
    )


def test_critic_finding_union_key_folds_case_and_whitespace() -> None:
    f1 = _audit_finding("C-FB", slide_id="s1", message="94.4  Not  Supported")
    f2 = _audit_finding("C-FB", slide_id="s1", message="94.4 not supported")
    # Case and collapsed whitespace fold to the same identity.
    assert _critic_finding_union_key(f1) == _critic_finding_union_key(f2)
    # A DIFFERENT message on the same (slide_id, check_id) is a distinct key — two
    # fabricated numbers on one slide must both be able to survive the union.
    f3 = _audit_finding("C-FB", slide_id="s1", message="1987 not supported")
    assert _critic_finding_union_key(f1) != _critic_finding_union_key(f3)
    # Severity is IN the key: code derives it from the evidence, so the SAME
    # (check_id, slide_id, message) can arrive WARN in one pass and FAIL in another.
    # Keying without severity would let the pass-1 WARN shadow the pass-2 FAIL.
    warn = _audit_finding(
        "C-FB", slide_id="s1", message="94.4 not supported", severity=AuditSeverity.WARN
    )
    fail = _audit_finding(
        "C-FB", slide_id="s1", message="94.4 not supported", severity=AuditSeverity.FAIL
    )
    assert _critic_finding_union_key(warn) != _critic_finding_union_key(fail)
    # A None message normalizes to "" and never raises; the key carries the severity.
    f4 = _audit_finding("C-FB", slide_id="s1", message=None)
    assert _critic_finding_union_key(f4) == ("C-FB", "s1", "", AuditSeverity.FAIL)


def test_union_critic_findings_dedupes_and_preserves_order() -> None:
    a = _audit_finding("C-FB", slide_id="s1", message="94.4 is not supported by the source.")
    b = _audit_finding("C-US", slide_id="s2", message="Second finding.")
    first = [a, b]
    # dup_a differs from a ONLY by case + whitespace -> collapses (dropped).
    dup_a = _audit_finding("C-FB", slide_id="s1", message="94.4   IS not supported by the SOURCE.")
    # diff_msg shares (slide_id, check_id) with a but a DIFFERENT message -> survives.
    diff_msg = _audit_finding("C-FB", slide_id="s1", message="1987 is not supported by the source.")
    novel = _audit_finding("C-FB", slide_id="s3", message="Third finding.")

    out = _union_critic_findings(first, [dup_a, diff_msg, novel])

    # All of first in order, then second's not-already-seen in order.
    assert out == [a, b, diff_msg, novel]
    assert dup_a not in out  # the case/whitespace duplicate was folded away


async def test_critique_unioned_unions_a_finding_only_the_second_pass_saw() -> None:
    plan = _stub_plan()
    section = plan.sections[0]
    slide = _critic_content_slide(
        "Findings",
        "Water savings reached 94.4 percent in field trials.",
        section.section_name,
        section.thesis,
    )
    claims = [_claim("The system reduced water consumption during the evaluation period.")]
    fab = _fab_finding(1, "Water savings reached 94.4 percent in field trials.", "94.4 percent")
    # Pass 1 clean, pass 2 flags the fabrication. A single clean sample would ship it.
    gemini = _StubGemini(critic=[_critic_response([]), _critic_response([fab])])

    outcome = await _critique_unioned(
        [slide], plan, claims=claims, gemini=gemini, language=Language.UZ, project_id="proj"
    )

    assert gemini.critic_calls == 2  # two independent passes, one Gemini call each
    assert outcome.llm_verified is True  # both passes produced a verdict
    assert [f.check_id for f in outcome.result.failures] == ["C-FB"]
    assert outcome.result.passed is False  # a defect only ONE pass saw still blocks


@pytest.mark.parametrize("degrade_first", [True, False])
async def test_critique_unioned_is_unverified_when_either_pass_degrades(
    degrade_first: bool,
) -> None:
    plan = _stub_plan()
    section = plan.sections[0]
    slide = _critic_content_slide(
        "Findings",
        "Water savings reached 94.4 percent in field trials.",
        section.section_name,
        section.thesis,
    )
    claims = [_claim("The system reduced water consumption during the evaluation period.")]
    # A degraded pass is unparseable across both the initial call and its retry.
    degraded = ["not valid json", "still not valid json"]
    clean = _critic_response([])
    critic = [*degraded, clean] if degrade_first else [clean, *degraded]
    gemini = _StubGemini(critic=critic)

    outcome = await _critique_unioned(
        [slide], plan, claims=claims, gemini=gemini, language=Language.UZ, project_id="proj"
    )

    # llm_verified requires BOTH passes to verify; one degrade -> the union is unverified,
    # so the caller must not read empty failures as clean.
    assert outcome.llm_verified is False
    assert gemini.critic_calls == 3  # degraded pass consumed 2 (initial + retry), clean pass 1


async def test_content_critic_rejudge_union_one_pass_flags_still_escalates() -> None:
    """Site 3: the union re-judge blocks when EITHER pass re-flags the corrected slide.
    A defect only one sampled pass caught still triggers escalation and, with no brain
    fix available, the hard stop — a single clean re-judge sample is not 'clean'."""
    plan = _stub_plan()
    section = plan.sections[0]
    slide = _critic_content_slide(
        "Findings",
        "Water savings reached 94.4 percent in field trials.",
        section.section_name,
        section.thesis,
    )
    claims = [_claim("The system reduced water consumption during the evaluation period.")]
    # The regen splices (keeps type) but still asserts the fabrication.
    regen = _llm_slides_payload(
        [
            {
                "slide_index": 0,
                "section_index": 0,
                "slide_type": "concept_definition",
                "title": "Findings",
                "body_text": "Water savings reached 94.4 percent in field trials.",
                "narrative_role": "core",
            }
        ]
    )
    fab = _fab_finding(1, "Water savings reached 94.4 percent in field trials.", "94.4 percent")
    pass_ = _editorial(
        _StubLLM([regen]),
        # discovery flags; the union re-judge is ONE clean pass + ONE flagging pass ->
        # union NOT clean; the escalation-entry extra is clean (incoming already has fab).
        critic=[
            _critic_response([fab]),
            _critic_response([]),
            _critic_response([fab]),
            _critic_response([]),
        ],
        plan=plan,
    )

    with pytest.raises(EditorialContentCriticError) as exc:
        await pass_._enforce_content_critic(
            _interview(), _design(), plan, [slide], claims, "proj", is_emergency=False
        )
    assert any(f.check_id == "C-FB" for f in exc.value.findings)
    assert pass_._gemini.brain_calls == 1  # escalation was entered (not shipped)
    assert pass_._gemini.critic_calls == 4  # first + union re-judge (2) + escalation-entry extra


@pytest.mark.parametrize("degrade_first", [True, False])
async def test_content_critic_rejudge_union_unverified_keeps_first_pass_hard_stop(
    degrade_first: bool,
) -> None:
    """Site 3: if EITHER union re-judge pass degrades, the union is unverified and the
    first-pass hard stop on the corrected slide stands — absence of a verdict never
    clears a known fabrication, whichever pass could not be established."""
    plan = _stub_plan()
    section = plan.sections[0]
    slide = _critic_content_slide(
        "Findings",
        "Water savings reached 94.4 percent in field trials.",
        section.section_name,
        section.thesis,
    )
    claims = [_claim("The system reduced water consumption during the evaluation period.")]
    # The regen GROUNDS the slide (drops 94.4) and splices; only an unverified re-judge
    # keeps the first-pass hard stop alive on the corrected slide.
    regen = _llm_slides_payload(
        [
            {
                "slide_index": 0,
                "section_index": 0,
                "slide_type": "concept_definition",
                "title": "Findings",
                "body_text": "Water savings improved notably in field trials.",
                "narrative_role": "core",
            }
        ]
    )
    fab = _fab_finding(1, "Water savings reached 94.4 percent in field trials.", "94.4 percent")
    clean = _critic_response([])
    degraded = ["not valid json", "still not valid json"]
    union = [*degraded, clean] if degrade_first else [clean, *degraded]
    pass_ = _editorial(
        _StubLLM([regen]),
        critic=[_critic_response([fab]), *union, clean],
        plan=plan,
    )

    with pytest.raises(EditorialContentCriticError) as exc:
        await pass_._enforce_content_critic(
            _interview(), _design(), plan, [slide], claims, "proj", is_emergency=False
        )
    assert [f.slide_id for f in exc.value.findings] == [slide.slide_id]
    assert exc.value.findings[0].check_id == "C-FB"
    assert pass_._gemini.critic_calls == 5  # first + union (degrade 2 + clean 1) + entry extra


async def test_escalation_site2_union_one_pass_flags_does_not_ground() -> None:
    """Site 2: a brain fix is applied, then the union re-critique has ONE clean pass and
    ONE that still flags — surviving is non-empty, so the loop does NOT terminate as
    grounded. Grounding requires a clean UNION, not a single clean sample."""
    plan = _stub_plan()
    section = plan.sections[0]
    slide = _critic_content_slide(
        "Findings",
        "Water savings reached 94.4 percent in field trials.",
        section.section_name,
        section.thesis,
    )
    claims = [_claim("The system reduced water consumption during the evaluation period.")]
    regen_fail = _llm_slides_payload(  # site-3 Sonnet repair changes type -> rejected
        [
            {
                "slide_index": 0,
                "section_index": 0,
                "slide_type": "content_split",
                "title": "Findings",
                "body_text": "Water savings improved notably in field trials.",
                "narrative_role": "core",
            }
        ]
    )
    regen_still_fab = _llm_slides_payload(  # brain regen keeps type but still fabricates
        [
            {
                "slide_index": 0,
                "section_index": 0,
                "slide_type": "concept_definition",
                "title": "Findings",
                "body_text": "Water savings reached 94.4 percent in field trials.",
                "narrative_role": "core",
            }
        ]
    )
    fab = _fab_finding(1, "Water savings reached 94.4 percent in field trials.", "94.4 percent")
    pass_ = _editorial(
        _StubLLM([regen_fail, regen_still_fab]),
        critic=[
            _critic_response([fab]),  # first discovery
            _critic_response([fab]),  # escalation-entry extra
            _critic_response([]),  # loop 1 union re-critique, pass 1: CLEAN
            _critic_response([fab]),  # loop 1 union re-critique, pass 2: still flags
        ],
        brain=[
            _fix_turn([{"slide_id": slide.slide_id, "instruction": "Ground the 94.4 figure."}]),
        ],
        plan=plan,
    )

    with pytest.raises(EditorialContentCriticError) as exc:
        await pass_._enforce_content_critic(
            _interview(), _design(), plan, [slide], claims, "proj", is_emergency=False
        )
    assert any(f.check_id == "C-FB" for f in exc.value.findings)
    # One clean sample did not ground it; loop 2 has no brain fix -> break -> hard stop.
    assert pass_._gemini.brain_calls == 2  # loop 1 (fix) + loop 2 (no fix -> break)
    assert pass_._gemini.critic_calls == 4  # first + entry extra + one union re-critique (2)


async def test_escalation_entry_extra_pass_adds_missed_finding_to_brief() -> None:
    """Site 1: the escalation-entry extra pass catches a hard stop the discovery pass
    SAMPLED past (on a different slide) and unions it into the set the brain must fix,
    so the hard stop carries BOTH findings — the incoming one and the newly caught one."""
    plan = _stub_plan()
    slide_a = _critic_content_slide(
        "Water",
        "Water savings reached 94.4 percent in field trials.",
        plan.sections[0].section_name,
        plan.sections[0].thesis,
    )
    slide_b = SlideSpec(
        slide_index=1,
        slide_type=SlideType.CONCEPT_DEFINITION,
        content=SlideContent(
            title="Energy", body_text="Energy use dropped by 87.3 percent across all zones."
        ),
        section_name=plan.sections[1].section_name,
        section_thesis=plan.sections[1].thesis,
    )
    claims = [_claim("The system reduced water and energy consumption during evaluation.")]
    # A's site-3 repair changes type -> rejected -> no regen accepted -> escalation.
    regen_a_fail = _llm_slides_payload(
        [
            {
                "slide_index": 0,
                "section_index": 0,
                "slide_type": "content_split",
                "title": "Water",
                "body_text": "Water savings improved notably in field trials.",
                "narrative_role": "core",
            }
        ]
    )
    fab_a = _fab_finding(1, "Water savings reached 94.4 percent in field trials.", "94.4 percent")
    fab_b = _fab_finding(2, "Energy use dropped by 87.3 percent across all zones.", "87.3 percent")
    pass_ = _editorial(
        _StubLLM([regen_a_fail]),
        # discovery flags ONLY A (samples past B); the entry extra catches BOTH.
        critic=[_critic_response([fab_a]), _critic_response([fab_a, fab_b])],
        plan=plan,
    )

    with pytest.raises(EditorialContentCriticError) as exc:
        await pass_._enforce_content_critic(
            _interview(), _design(), plan, [slide_a, slide_b], claims, "proj", is_emergency=False
        )
    # Both A (incoming) and B (added by the entry extra) reach the hard stop / brain brief.
    assert {f.slide_id for f in exc.value.findings} == {slide_a.slide_id, slide_b.slide_id}
    assert all(f.check_id == "C-FB" for f in exc.value.findings)
    assert pass_._gemini.critic_calls == 2  # discovery + one escalation-entry extra


async def test_escalation_entry_extra_pass_unverified_keeps_incoming_unchanged() -> None:
    """Site 1: an UNVERIFIED entry extra pass must not block escalation nor alter the
    incoming set — those findings are already code-confirmed. It adds nothing and the
    hard stop carries exactly the incoming finding."""
    plan = _stub_plan()
    section = plan.sections[0]
    slide = _critic_content_slide(
        "Findings",
        "Water savings reached 94.4 percent in field trials.",
        section.section_name,
        section.thesis,
    )
    claims = [_claim("The system reduced water consumption during the evaluation period.")]
    regen_fail = _llm_slides_payload(
        [
            {
                "slide_index": 0,
                "section_index": 0,
                "slide_type": "content_split",
                "title": "Findings",
                "body_text": "Water savings improved notably in field trials.",
                "narrative_role": "core",
            }
        ]
    )
    fab = _fab_finding(1, "Water savings reached 94.4 percent in field trials.", "94.4 percent")
    pass_ = _editorial(
        _StubLLM([regen_fail]),
        # discovery flags fab; the entry extra is unparseable after retry (unverified).
        critic=[_critic_response([fab]), "not valid json", "still not valid json"],
        plan=plan,
    )

    with pytest.raises(EditorialContentCriticError) as exc:
        await pass_._enforce_content_critic(
            _interview(), _design(), plan, [slide], claims, "proj", is_emergency=False
        )
    assert [f.slide_id for f in exc.value.findings] == [slide.slide_id]
    assert exc.value.findings[0].check_id == "C-FB"
    assert pass_._gemini.critic_calls == 3  # discovery + entry extra (unparseable + retry)


# ---------------------------------------------------------------------------
# Hard-stop-path fixes (adversarial review): severity in the union key, and the
# site-3 residual as an add-only union in BOTH the verified and unverified branch.
# ---------------------------------------------------------------------------


async def test_critique_unioned_warn_pass_does_not_shadow_fail_pass() -> None:
    """BUG-1: severity is CODE-derived from the evidence, so two independent passes can
    emit the SAME (check_id, slide_id, message) at different severities. The union key
    carries severity, so a pass-1 WARN never shadows a pass-2 FAIL — the union's
    ``.failures`` keeps the FAIL that routing / the hard stop must see."""
    plan = _stub_plan()
    section = plan.sections[0]
    slide = _critic_content_slide(
        "Findings",
        "Water savings reached 94.4 percent and energy fell 87.3 percent in field trials.",
        section.section_name,
        section.thesis,
    )
    # 94.4 IS grounded in a claim (its finding degrades to WARN); 87.3 is NOT (stays FAIL).
    claims = [_claim("Independent trials confirmed water savings of 94.4 percent.")]
    quote = "Water savings reached 94.4 percent and energy fell 87.3 percent in field trials."
    message = "The reported percentage is not grounded in the cited source."
    warn_side = {
        "slide_handle": 1,
        "category": "fabrication",
        "message": message,
        "evidence": {
            "slide_quote": quote,
            "unsupported_token": "94.4 percent",
            "second_quote": None,
        },
    }
    fail_side = {
        "slide_handle": 1,
        "category": "fabrication",
        "message": message,  # SAME message, so the union key differs ONLY by severity
        "evidence": {
            "slide_quote": quote,
            "unsupported_token": "87.3 percent",
            "second_quote": None,
        },
    }
    gemini = _StubGemini(critic=[_critic_response([warn_side]), _critic_response([fail_side])])

    outcome = await _critique_unioned(
        [slide], plan, claims=claims, gemini=gemini, language=Language.UZ, project_id="proj"
    )

    assert gemini.critic_calls == 2
    assert outcome.llm_verified is True
    # The FAIL survives — the pass-1 WARN sharing (check_id, slide_id, message) did not
    # shadow it, so the deck does NOT read as clean.
    assert [f.severity for f in outcome.result.failures] == [AuditSeverity.FAIL]
    assert outcome.result.passed is False
    # Both copies are retained: proof the WARN was not collapsed onto the FAIL.
    fb = [f for f in outcome.result.findings if f.check_id == "C-FB"]
    assert {f.severity for f in fb} == {AuditSeverity.WARN, AuditSeverity.FAIL}


async def test_content_critic_rejudge_union_two_same_slide_fabrications_both_survive() -> None:
    """BUG-2 (site 3): the re-judge UNION returns two DIFFERENT-message C-FB findings on
    ONE corrected slide (each pass sampled a different fabrication). The residual must be
    an add-only union, not a (slide_id, check_id) dedupe — BOTH must reach the escalation
    brief / hard-stop payload."""
    plan = _stub_plan()
    section = plan.sections[0]
    slide = _critic_content_slide(
        "Findings",
        "Water savings reached 94.4 percent in field trials.",
        section.section_name,
        section.thesis,
    )
    claims = [_claim("The system reduced water consumption during the evaluation period.")]
    # The Sonnet repair splices (keeps type) but the new body carries TWO fabricated
    # numbers, so the two adversarial re-judge passes each catch a different one.
    two_fab_body = (
        "Water savings reached 94.4 percent and energy fell 87.3 percent in field trials."
    )
    regen = _llm_slides_payload(
        [
            {
                "slide_index": 0,
                "section_index": 0,
                "slide_type": "concept_definition",
                "title": "Findings",
                "body_text": two_fab_body,
                "narrative_role": "core",
            }
        ]
    )
    disc = _fab_finding(1, "Water savings reached 94.4 percent in field trials.", "94.4 percent")
    rejudge_94 = _fab_finding(1, two_fab_body, "94.4 percent")
    rejudge_87 = _fab_finding(1, two_fab_body, "87.3 percent")
    pass_ = _editorial(
        _StubLLM([regen]),
        # discovery flags 94.4; the union re-judge pass 1 catches 94.4, pass 2 catches
        # 87.3 (different messages, same slide); the escalation-entry extra is clean.
        critic=[
            _critic_response([disc]),
            _critic_response([rejudge_94]),
            _critic_response([rejudge_87]),
            _critic_response([]),
        ],
        plan=plan,
    )

    with pytest.raises(EditorialContentCriticError) as exc:
        await pass_._enforce_content_critic(
            _interview(), _design(), plan, [slide], claims, "proj", is_emergency=False
        )
    same_slide = [f for f in exc.value.findings if f.slide_id == slide.slide_id]
    assert len(same_slide) == 2  # add-only union kept BOTH; a dedupe would collapse to 1
    assert {f.check_id for f in same_slide} == {"C-FB"}
    messages = {" ".join((f.message or "").split()).lower() for f in same_slide}
    assert len(messages) == 2
    # Each message carries its own token verbatim (the unconditional suffix that
    # makes the message a valid union discriminator).
    assert any('[unsupported: "94.4 percent"]' in m for m in messages)
    assert any('[unsupported: "87.3 percent"]' in m for m in messages)
    assert pass_._gemini.critic_calls == 4  # discovery + union re-judge (2) + entry extra


async def test_content_critic_rejudge_union_unverified_keeps_verified_half_discovery() -> None:
    """BUG-3 (site 3): when the re-judge UNION is unverified (one pass degraded), the
    else-branch must still carry the VERIFIED half's discoveries. A NEW hard stop B the
    verified pass found on the corrected deck must not be discarded alongside the standing
    first-pass hard stop A."""
    plan = _stub_plan()
    slide_a = _critic_content_slide(
        "Water",
        "Water savings reached 94.4 percent in field trials.",
        plan.sections[0].section_name,
        plan.sections[0].thesis,
    )
    slide_b = SlideSpec(
        slide_index=1,
        slide_type=SlideType.CONCEPT_DEFINITION,
        content=SlideContent(
            title="Energy", body_text="Energy use dropped by 87.3 percent across all zones."
        ),
        section_name=plan.sections[1].section_name,
        section_thesis=plan.sections[1].thesis,
    )
    claims = [_claim("The system reduced water and energy consumption during evaluation.")]
    # A is flagged by discovery and its regen GROUNDS it (drops 94.4) -> A is corrected.
    regen_a = _llm_slides_payload(
        [
            {
                "slide_index": 0,
                "section_index": 0,
                "slide_type": "concept_definition",
                "title": "Water",
                "body_text": "Water savings improved notably in field trials.",
                "narrative_role": "core",
            }
        ]
    )
    fab_a = _fab_finding(1, "Water savings reached 94.4 percent in field trials.", "94.4 percent")
    fab_b = _fab_finding(2, "Energy use dropped by 87.3 percent across all zones.", "87.3 percent")
    pass_ = _editorial(
        _StubLLM([regen_a]),
        # discovery flags ONLY A. The union re-judge: pass 1 DEGRADES (unparseable + retry),
        # pass 2 VERIFIES and catches a NEW hard stop B on the still-fabricating slide. The
        # union is unverified -> A stands (absence never clears) AND B is carried in. The
        # escalation-entry extra is clean (the incoming set is already established).
        critic=[
            _critic_response([fab_a]),
            "not valid json",
            "still not valid json",
            _critic_response([fab_b]),
            _critic_response([]),
        ],
        plan=plan,
    )

    with pytest.raises(EditorialContentCriticError) as exc:
        await pass_._enforce_content_critic(
            _interview(), _design(), plan, [slide_a, slide_b], claims, "proj", is_emergency=False
        )
    # BOTH: A (first-pass stop that the unverified re-judge could not clear) AND B (the
    # verified half's new discovery). The old else-branch dropped B.
    assert {f.slide_id for f in exc.value.findings} == {slide_a.slide_id, slide_b.slide_id}
    assert all(f.check_id == "C-FB" for f in exc.value.findings)
    assert (
        pass_._gemini.critic_calls == 5
    )  # discovery + union (degrade 2 + verified 1) + entry extra
