"""Behavior tests for every model in :mod:`packages.core.models.presentation`.

Each test pins one specific contract: enum size, field validator, optional
field defaulting, round-trip serialization, or a computed property.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from packages.core.enums import (
    AudienceType,
    AuditSeverity,
    BackgroundTreatment,
    ChartType,
    DiagramStrategy,
    ExportFormat,
    ImageSubjectType,
    Language,
    NarrativeEmphasis,
    PresentationMood,
    SlideType,
    SpeakerNotesStyle,
    TitleStyle,
)
from packages.core.models.presentation import (
    AuditCheckResult,
    AuditReport,
    ChartSeriesPoint,
    ColorPalette,
    DeckSpec,
    DesignDirectionSpec,
    MatchingPair,
    PersonItem,
    PresentationInterviewAnswers,
    QuizOption,
    QuizQuestion,
    SlideContent,
    SlideSpec,
    StatItem,
    TableRow,
    TimelineNode,
    new_deck_id,
)


def _palette() -> ColorPalette:
    return ColorPalette(
        background="#F5F0E8",
        surface="#E0D6C4",
        text="#1A120B",
        accent="#C4923A",
        text_secondary="#5C4A39",
    )


def _design() -> DesignDirectionSpec:
    return DesignDirectionSpec(
        mood=PresentationMood.WARM_HISTORICAL,
        palette=_palette(),
        heading_font="Playfair Display",
        body_font="EB Garamond",
        image_style_prefix="18th century oil painting, ",
        background_treatment=BackgroundTreatment.LIGHT,
    )


def _slide(idx: int, slide_type: SlideType = SlideType.CONTENT_SPLIT) -> SlideSpec:
    return SlideSpec(
        slide_index=idx,
        slide_type=slide_type,
        content=SlideContent(title="Test slide"),
    )


# ---------------------------------------------------------------------------
# enums
# ---------------------------------------------------------------------------


def test_slide_type_enum_has_all_22_types() -> None:
    assert len(SlideType) == 22


def test_slide_type_includes_all_interactive_variants() -> None:
    interactive = {m for m in SlideType if m.value.startswith("interactive_")}
    assert len(interactive) == 6
    assert SlideType.INTERACTIVE_QUIZ_MCQ in interactive
    assert SlideType.INTERACTIVE_DEBATE in interactive


def test_presentation_mood_enum_has_six_values() -> None:
    assert {m.value for m in PresentationMood} == {
        "warm_historical",
        "bold_technical",
        "clean_professional",
        "calm_medical",
        "natural",
        "institutional",
    }


def test_background_treatment_only_dark_or_light() -> None:
    assert {m.value for m in BackgroundTreatment} == {"dark", "light"}


def test_export_format_includes_all_four_outputs() -> None:
    assert {m.value for m in ExportFormat} == {"html", "pptx_editable", "pptx_studio", "pdf"}


# ---------------------------------------------------------------------------
# ColorPalette / DesignDirectionSpec
# ---------------------------------------------------------------------------


def test_color_palette_validates_hex_format() -> None:
    ColorPalette(
        background="#abcdef",
        surface="#123456",
        text="#000000",
        accent="#FFFFFF",
        text_secondary="#888888",
    )
    with pytest.raises(ValidationError):
        ColorPalette(
            background="red",
            surface="#123456",
            text="#000000",
            accent="#FFFFFF",
            text_secondary="#888888",
        )
    with pytest.raises(ValidationError):
        ColorPalette(
            background="#GGGGGG",
            surface="#123456",
            text="#000000",
            accent="#FFFFFF",
            text_secondary="#888888",
        )


def test_color_palette_uppercases_hex() -> None:
    palette = ColorPalette(
        background="#abcdef",
        surface="#123abc",
        text="#000000",
        accent="#fffeee",
        text_secondary="#888888",
    )
    assert palette.background == "#ABCDEF"
    assert palette.accent == "#FFFEEE"


def test_design_direction_spec_round_trip() -> None:
    design = _design()
    again = DesignDirectionSpec.model_validate(design.model_dump(mode="json"))
    assert again == design
    assert again.mood is PresentationMood.WARM_HISTORICAL


# ---------------------------------------------------------------------------
# SlideContent / item primitives
# ---------------------------------------------------------------------------


def test_slide_content_minimal_only_title() -> None:
    content = SlideContent(title="Just a title")
    assert content.title == "Just a title"
    assert content.bullets is None
    assert content.stats is None
    assert content.quiz_questions is None
    assert content.speaker_notes is None


def test_slide_content_data_emphasis_holds_stats() -> None:
    content = SlideContent(
        title="Headline results",
        stats=[
            StatItem(value="94.4", unit="%", label="Water savings in Seattle", highlight=True),
            StatItem(value="516,120", unit="", label="Hourly records analysed"),
        ],
    )
    assert content.stats is not None
    assert content.stats[0].highlight is True
    assert content.stats[1].unit == ""


def test_stat_item_with_trend_and_comparison_round_trips() -> None:
    stat = StatItem(
        value="94.4",
        unit="%",
        label="Water saved",
        trend="↑",
        comparison="vs 67% in 2022",
    )
    again = StatItem.model_validate(stat.model_dump(mode="json"))
    assert again == stat
    assert again.trend == "↑"


def test_stat_item_unit_accepts_descriptive_real_units() -> None:
    # The 10-char cap rejected real units the editorial model naturally emits,
    # collapsing the whole deck. The cap is 32; these must validate verbatim.
    for unit in ("liters/year", "of facility energy", "of waste heat"):
        stat = StatItem(value="42", unit=unit, label="Recovered")
        assert stat.unit == unit


def test_stat_item_unit_accepts_full_32_chars_rejects_33() -> None:
    StatItem(value="1", unit="x" * 32, label="L")
    with pytest.raises(ValidationError):
        StatItem(value="1", unit="x" * 33, label="L")


def test_chart_series_point_unit_accepts_descriptive_real_units() -> None:
    for unit in ("liters/year", "of facility energy", "of waste heat"):
        point = ChartSeriesPoint(label="Recovered heat", value=42.0, unit=unit)
        assert point.unit == unit


def test_chart_series_point_unit_accepts_full_32_chars_rejects_33() -> None:
    ChartSeriesPoint(label="L", value=1.0, unit="x" * 32)
    with pytest.raises(ValidationError):
        ChartSeriesPoint(label="L", value=1.0, unit="x" * 33)


def test_quiz_question_rejects_single_option() -> None:
    with pytest.raises(ValidationError):
        QuizQuestion(
            question="What year?",
            options=[QuizOption(text="1750", is_correct=True)],
            explanation_correct="Right",
            explanation_wrong="Wrong",
        )


def test_quiz_question_accepts_two_to_four_options() -> None:
    q = QuizQuestion(
        question="Which century?",
        options=[
            QuizOption(text="XV-XVI"),
            QuizOption(text="XVII-XVIII", is_correct=True),
            QuizOption(text="XIX-XX"),
        ],
        explanation_correct="Yes — Enlightenment era.",
        explanation_wrong="Off by a couple of centuries.",
    )
    assert q.options[1].is_correct is True


def test_matching_pair_requires_both_sides_non_empty() -> None:
    MatchingPair(left="Monteske", right="Separation of powers")
    with pytest.raises(ValidationError):
        MatchingPair(left="", right="x")
    with pytest.raises(ValidationError):
        MatchingPair(left="x", right="")


def test_slide_content_quiz_round_trip() -> None:
    content = SlideContent(
        title="Quick check",
        quiz_questions=[
            QuizQuestion(
                question="When did the Enlightenment begin?",
                options=[
                    QuizOption(text="XVII-XVIII century", is_correct=True),
                    QuizOption(text="XIX century"),
                ],
                explanation_correct="Correct",
                explanation_wrong="Try again",
            )
        ],
    )
    again = SlideContent.model_validate(content.model_dump(mode="json"))
    assert again == content


def test_chart_series_point_round_trips() -> None:
    point = ChartSeriesPoint(label="sCO2 rack density", value=120.0, unit="kW/rack")
    again = ChartSeriesPoint.model_validate(point.model_dump(mode="json"))
    assert again == point
    assert again.value == 120.0
    assert again.unit == "kW/rack"


def test_chart_series_point_coerces_numeric_string_value() -> None:
    # The editorial LLM may emit the value as a JSON string; pydantic coerces
    # it to float so the renderer always receives a plottable magnitude.
    point = ChartSeriesPoint.model_validate({"label": "Air", "value": "8", "unit": None})
    assert point.value == 8.0
    assert point.unit is None


def test_slide_content_chart_series_round_trips() -> None:
    content = SlideContent(
        title="Rack density climbs 15x from air to sCO2",
        body_text="Heat capacity, not airflow, sets the ceiling.",
        chart_series=[
            ChartSeriesPoint(label="Air", value=8, unit="kW/rack"),
            ChartSeriesPoint(label="Liquid", value=40, unit="kW/rack"),
            ChartSeriesPoint(label="sCO2", value=120, unit="kW/rack"),
        ],
    )
    again = SlideContent.model_validate(content.model_dump(mode="json"))
    assert again == content
    assert again.chart_series is not None
    assert [p.value for p in again.chart_series] == [8.0, 40.0, 120.0]


def test_chart_series_point_with_values_round_trips() -> None:
    # Grouped/stacked charts carry per-group magnitudes in `values`; the scalar
    # `value` stays present for the flat-chart fallback.
    point = ChartSeriesPoint(label="sCO2", value=120.0, unit="kW", values=[90.0, 25.0, 5.0])
    again = ChartSeriesPoint.model_validate(point.model_dump(mode="json"))
    assert again == point
    assert again.values == [90.0, 25.0, 5.0]


def test_chart_series_point_without_values_defaults_none() -> None:
    point = ChartSeriesPoint(label="Air", value=8.0)
    assert point.values is None


def test_slide_content_grouped_chart_round_trips() -> None:
    content = SlideContent(
        title="Power split widens with density",
        chart_type=ChartType.GROUPED_BAR,
        chart_group_labels=["IT load", "Cooling", "Other"],
        chart_series=[
            ChartSeriesPoint(label="Air", value=8, values=[6.0, 1.5, 0.5]),
            ChartSeriesPoint(label="sCO2", value=120, values=[90.0, 25.0, 5.0]),
        ],
    )
    again = SlideContent.model_validate(content.model_dump(mode="json"))
    assert again == content
    assert again.chart_type is ChartType.GROUPED_BAR
    assert again.chart_group_labels == ["IT load", "Cooling", "Other"]


def test_slide_content_figure_slot_round_trips() -> None:
    # The object-figure slot (image engine PART 1): prompt + subject type are
    # authored by editorial, the url filled by the image stage. All three must
    # survive a json round-trip through the deck_json blob without loss.
    content = SlideContent(
        title="The cold plate moves the heat",
        figure_prompt="a liquid cold plate, copper microchannels, neutral background",
        figure_url="https://cdn.example.com/temp/p1/figure_03.png",
        figure_subject_type=ImageSubjectType.OBJECT,
    )
    again = SlideContent.model_validate(content.model_dump(mode="json"))
    assert again == content
    assert again.figure_subject_type is ImageSubjectType.OBJECT
    assert again.figure_url == "https://cdn.example.com/temp/p1/figure_03.png"


def test_slide_content_figure_fields_default_none() -> None:
    content = SlideContent(title="No figure here")
    assert content.figure_prompt is None
    assert content.figure_url is None
    assert content.figure_subject_type is None


def test_timeline_node_portrait_url_round_trips() -> None:
    # TimelineNode gains a portrait_url the image engine fills from Commons;
    # both portrait fields must round-trip so timeline portraits survive.
    node = TimelineNode(
        date="1687",
        label="Newton publishes the Principia",
        portrait_prompt="Isaac Newton, English physicist",
        portrait_url="https://cdn.example.com/temp/p1/newton.png",
    )
    again = TimelineNode.model_validate(node.model_dump(mode="json"))
    assert again == node
    assert again.portrait_url == "https://cdn.example.com/temp/p1/newton.png"


def test_person_item_portrait_fields_default_none() -> None:
    person = PersonItem(name="Voltaire")
    assert person.portrait_prompt is None
    assert person.portrait_url is None


def test_image_subject_type_enum_size() -> None:
    assert {s.value for s in ImageSubjectType} == {"person", "object", "concept", "scene"}


def test_slide_content_chart_type_defaults_none() -> None:
    # A chart_data slide that omits chart_type leaves the renderer to default
    # to "bar"; the model itself stores None.
    content = SlideContent(title="x", chart_series=[ChartSeriesPoint(label="A", value=1)])
    assert content.chart_type is None
    assert content.chart_group_labels is None


def test_chart_type_enum_size() -> None:
    assert {c.value for c in ChartType} == {
        "bar",
        "line",
        "single_value",
        "grouped_bar",
        "stacked_bar",
    }


def test_slide_content_table_round_trips() -> None:
    content = SlideContent(
        title="sCO2 wins on every dimension",
        table_headers=["Cooling", "Density", "PUE"],
        table_rows=[
            TableRow(cells=["Air", "8 kW/rack", "1.58"]),
            TableRow(cells=["Liquid", "40 kW/rack", "1.10"]),
            TableRow(cells=["sCO2", "120 kW/rack", "1.04"]),
        ],
    )
    again = SlideContent.model_validate(content.model_dump(mode="json"))
    assert again == content
    assert again.table_rows is not None
    assert again.table_rows[2].cells[0] == "sCO2"


def test_slide_content_table_emphasis_round_trips() -> None:
    content = SlideContent(
        title="sCO2 wins on every dimension",
        table_headers=["Cooling", "Density", "PUE"],
        table_rows=[TableRow(cells=["sCO2", "120 kW/rack", "1.04"])],
        table_preferred_column=2,
        table_hero_row=0,
    )
    again = SlideContent.model_validate(content.model_dump(mode="json"))
    assert again == content
    assert again.table_preferred_column == 2
    assert again.table_hero_row == 0


def test_slide_content_table_emphasis_defaults_none() -> None:
    content = SlideContent(title="Neutral reference", table_headers=["A", "B"])
    assert content.table_preferred_column is None
    assert content.table_hero_row is None


# ---------------------------------------------------------------------------
# SlideSpec
# ---------------------------------------------------------------------------


def test_slide_spec_construction() -> None:
    spec = SlideSpec(
        slide_index=0,
        slide_type=SlideType.TITLE_HERO,
        content=SlideContent(title="Hero"),
    )
    assert spec.slide_index == 0
    assert spec.slide_type is SlideType.TITLE_HERO
    assert spec.accent_override is None
    assert spec.section_thesis is None


def test_slide_spec_section_thesis_round_trips() -> None:
    spec = SlideSpec(
        slide_index=2,
        slide_type=SlideType.TABLE_COMPACT,
        content=SlideContent(title="Results"),
        section_name="Results",
        section_thesis="sCO2 cooling pays back its capital within a few years.",
    )
    again = SlideSpec.model_validate(spec.model_dump(mode="json"))
    assert again == spec
    assert again.section_thesis == "sCO2 cooling pays back its capital within a few years."


def test_slide_spec_accent_override_validates_hex() -> None:
    SlideSpec(
        slide_index=0,
        slide_type=SlideType.SECTION_BREAK,
        content=SlideContent(title="Section"),
        accent_override="#abcdef",
    )
    with pytest.raises(ValidationError):
        SlideSpec(
            slide_index=0,
            slide_type=SlideType.SECTION_BREAK,
            content=SlideContent(title="Section"),
            accent_override="orange",
        )


# ---------------------------------------------------------------------------
# DeckSpec
# ---------------------------------------------------------------------------


def test_deck_spec_construction_and_counts() -> None:
    slides = [
        _slide(0, SlideType.TITLE_HERO),
        _slide(1, SlideType.CONTENT_SPLIT),
        _slide(2, SlideType.SECTION_BREAK),
        _slide(3, SlideType.INTERACTIVE_QUIZ_MCQ),
        _slide(4, SlideType.INTERACTIVE_MATCHING),
    ]
    deck = DeckSpec(
        project_id="proj-1",
        title="A deck",
        design=_design(),
        interview=PresentationInterviewAnswers(),
        slides=slides,
    )
    assert deck.slide_count == 5
    assert deck.content_slide_count == 4
    assert deck.interactive_slide_count == 2


def test_deck_spec_rejects_zero_slides() -> None:
    with pytest.raises(ValidationError):
        DeckSpec(
            project_id="proj-1",
            title="A deck",
            design=_design(),
            interview=PresentationInterviewAnswers(),
            slides=[],
        )


def test_deck_spec_default_export_is_html_only() -> None:
    deck = DeckSpec(
        project_id="proj-1",
        title="A deck",
        design=_design(),
        interview=PresentationInterviewAnswers(),
        slides=[_slide(0)],
    )
    assert deck.export_formats == [ExportFormat.HTML]
    assert deck.language is Language.UZ


def test_deck_spec_round_trips() -> None:
    deck = DeckSpec(
        project_id="proj-1",
        title="A deck",
        design=_design(),
        interview=PresentationInterviewAnswers(language=Language.EN),
        slides=[_slide(0), _slide(1, SlideType.SECTION_BREAK)],
        export_formats=[ExportFormat.HTML, ExportFormat.PDF],
    )
    again = DeckSpec.model_validate(deck.model_dump(mode="json"))
    assert again.slide_count == 2
    assert again.interview.language is Language.EN
    assert again.export_formats[1] is ExportFormat.PDF


# ---------------------------------------------------------------------------
# PresentationInterviewAnswers
# ---------------------------------------------------------------------------


def test_presentation_interview_answers_defaults() -> None:
    answers = PresentationInterviewAnswers()
    assert answers.audience is AudienceType.UNDERGRADUATE
    assert answers.talk_duration_minutes == 15
    assert answers.title_style is TitleStyle.TAKEAWAY
    assert answers.narrative_emphasis is NarrativeEmphasis.BALANCED
    assert answers.diagram_strategy is DiagramStrategy.BUILD_SVG
    assert answers.speaker_notes_style is SpeakerNotesStyle.BRIEF_TALKING_POINTS
    assert answers.include_interactive is True
    assert answers.mood_override is None
    assert answers.headline_numbers == []


def test_interview_answers_duration_rejects_out_of_range() -> None:
    with pytest.raises(ValidationError):
        PresentationInterviewAnswers(talk_duration_minutes=2)
    with pytest.raises(ValidationError):
        PresentationInterviewAnswers(talk_duration_minutes=61)


def test_interview_answers_headline_numbers_capped() -> None:
    PresentationInterviewAnswers(headline_numbers=["a"] * 10)
    with pytest.raises(ValidationError):
        PresentationInterviewAnswers(headline_numbers=["a"] * 11)


# ---------------------------------------------------------------------------
# AuditReport
# ---------------------------------------------------------------------------


def test_audit_check_result_construction() -> None:
    result = AuditCheckResult(
        check_id="Q1",
        check_name="Word count per slide",
        passed=False,
        severity=AuditSeverity.FAIL,
        slide_index=3,
        rule_reference="R17",
        message="Slide 3 exceeds 60-word limit (88 words)",
    )
    assert result.severity is AuditSeverity.FAIL
    assert result.rule_reference == "R17"


def test_audit_report_exportable_flag() -> None:
    deck_id = new_deck_id()
    clean = AuditReport(
        deck_id=deck_id,
        total_checks=15,
        passed=15,
        failed=0,
        warnings=0,
        is_exportable=True,
    )
    dirty = AuditReport(
        deck_id=deck_id,
        total_checks=15,
        passed=13,
        failed=1,
        warnings=1,
        is_exportable=False,
        results=[
            AuditCheckResult(
                check_id="Q1",
                check_name="Word count",
                passed=False,
                severity=AuditSeverity.FAIL,
                slide_index=3,
            )
        ],
    )
    assert clean.is_exportable is True
    assert dirty.is_exportable is False
    assert dirty.results[0].severity is AuditSeverity.FAIL
