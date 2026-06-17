"""Unit tests for the emphasis fallback + provenance module.

The executor authors emphasis in production (proven live by the GATE A script);
these tests pin the LAST-RESORT FALLBACK and its provenance recording — the
guarantee that a DATA_EMPHASIS slide never ships flat and that the gate can tell
an executor mark from a fallback fill.
"""

from __future__ import annotations

from packages.core.enums import (
    BackgroundTreatment,
    Language,
    PresentationMood,
    SlideType,
)
from packages.core.models.presentation import (
    ColorPalette,
    DeckSpec,
    DesignDirectionSpec,
    PresentationInterviewAnswers,
    SlideContent,
    SlideSpec,
    StatItem,
    TableRow,
)
from packages.presentation.emphasis import (
    EmphasisSignals,
    EmphasisSource,
    apply_emphasis_fallback,
    fallback_hero_row,
    fallback_hero_stat,
    fallback_preferred_column,
)

# ---------------------------------------------------------------------------
# Fixtures — the two real sCO2 comparison tables (winning column = sCO₂)
# ---------------------------------------------------------------------------

_SCO2_SUBTITLE = "How supercritical CO₂ transforms data centers into thermodynamic systems"

_HEADERS_4 = ["Metric", "Air Cooling", "Liquid Cooling", "sCO₂ Cooling"]
_ROWS_4 = [
    TableRow(cells=["Max rack density", "25–30 kW", "~100 kW", "300 kW"]),
    TableRow(cells=["PUE", "1.55–1.80", "1.20–1.30", "1.08"]),
    TableRow(cells=["Cooling energy reduction", "Baseline", "66%", "85%"]),
]

_HEADERS_13 = ["Outcome", "Air Cooling", "sCO₂ Cooling", "Improvement"]
_ROWS_13 = [
    TableRow(cells=["Annual energy savings (10 MW)", "Baseline", "$4.1M/yr", "+$4.1M/yr"]),
    TableRow(cells=["Payback period", "N/A", "3.2 years", "Strong ROI"]),
]


def _design() -> DesignDirectionSpec:
    return DesignDirectionSpec(
        mood=PresentationMood.CLEAN_PROFESSIONAL,
        palette=ColorPalette(
            background="#0A1520",
            surface="#112030",
            text="#E8F0F5",
            accent="#FF6B2B",
            text_secondary="#7AAFC4",
        ),
        heading_font="Inter",
        body_font="Inter",
        decorative_font=None,
        image_style_prefix="clean",
        background_treatment=BackgroundTreatment.LIGHT,
    )


def _deck(
    slides: list[SlideSpec],
    *,
    title: str = "Untitled deck",
    subtitle: str | None = None,
    headline_numbers: tuple[str, ...] = (),
) -> DeckSpec:
    return DeckSpec(
        project_id="test",
        title=title,
        subtitle=subtitle,
        design=_design(),
        interview=PresentationInterviewAnswers(
            language=Language.EN, headline_numbers=list(headline_numbers)
        ),
        slides=slides,
    )


def _table_slide(
    headers: list[str],
    rows: list[TableRow],
    *,
    index: int = 0,
    table_preferred_column: int | None = None,
    table_hero_row: int | None = None,
) -> SlideSpec:
    return SlideSpec(
        slide_index=index,
        slide_type=SlideType.TABLE_COMPACT,
        content=SlideContent(
            title="A table",
            table_headers=headers,
            table_rows=rows,
            table_preferred_column=table_preferred_column,
            table_hero_row=table_hero_row,
        ),
    )


def _data_slide(stats: list[StatItem], *, index: int = 0) -> SlideSpec:
    return SlideSpec(
        slide_index=index,
        slide_type=SlideType.DATA_EMPHASIS,
        content=SlideContent(title="Some numbers", stats=stats),
    )


# ---------------------------------------------------------------------------
# fallback_preferred_column
# ---------------------------------------------------------------------------


def test_preferred_column_picks_subject_column_from_slide_title() -> None:
    signals = EmphasisSignals(
        deck_subtitle=_SCO2_SUBTITLE,
        slide_title="sCO₂ Outperforms on Every Dimension That Matters",
    )
    assert fallback_preferred_column(_HEADERS_4, _ROWS_4, signals) == 3


def test_preferred_column_uses_subtitle_when_slide_title_omits_subject() -> None:
    # idx 13's own title never says "sCO₂"; the subject must come from the deck
    # subtitle. This is the case that proves reasoning beyond the slide's title.
    signals = EmphasisSignals(
        deck_subtitle=_SCO2_SUBTITLE,
        slide_title="A 10 MW Facility Saves $4.1M Annually and Eliminates 56 Million Liters",
    )
    assert fallback_preferred_column(_HEADERS_13, _ROWS_13, signals) == 2


def test_preferred_column_none_without_subject_signal() -> None:
    assert fallback_preferred_column(_HEADERS_4, _ROWS_4, EmphasisSignals()) is None


def test_preferred_column_none_on_tie() -> None:
    headers = ["Metric", "Alpha", "Beta"]
    rows = [TableRow(cells=["x", "1", "2"])]
    signals = EmphasisSignals(slide_title="Alpha versus Beta head to head")
    assert fallback_preferred_column(headers, rows, signals) is None


def test_preferred_column_ignores_label_column() -> None:
    # The subject word lives in the row-label column header; it must NOT win.
    headers = ["sCO₂ metric", "Air", "Liquid"]
    rows = [TableRow(cells=["density", "8", "40"])]
    signals = EmphasisSignals(slide_title="sCO₂ wins")
    assert fallback_preferred_column(headers, rows, signals) is None


# ---------------------------------------------------------------------------
# fallback_hero_stat
# ---------------------------------------------------------------------------


def test_hero_stat_matches_headline_number() -> None:
    stats = [
        StatItem(value="85", unit="%", label="cooling energy cut"),
        StatItem(value="1.08", unit="PUE", label="efficiency"),
    ]
    signals = EmphasisSignals(headline_numbers=("PUE 1.08 vs 1.55",))
    assert fallback_hero_stat(stats, signals) == 1


def test_hero_stat_defaults_to_lead_when_nothing_matches() -> None:
    stats = [
        StatItem(value="100+", unit="kW", label="demand"),
        StatItem(value="25", unit="kW", label="limit"),
    ]
    assert fallback_hero_stat(stats, EmphasisSignals()) == 0


# ---------------------------------------------------------------------------
# fallback_hero_row
# ---------------------------------------------------------------------------


def test_hero_row_matches_headline_number() -> None:
    signals = EmphasisSignals(headline_numbers=("3.2-year payback",))
    assert fallback_hero_row(_ROWS_13, signals) == 1


def test_hero_row_none_without_any_signal() -> None:
    rows = [TableRow(cells=["A", "1"]), TableRow(cells=["B", "2"])]
    assert fallback_hero_row(rows, EmphasisSignals()) is None


# ---------------------------------------------------------------------------
# apply_emphasis_fallback — provenance + primary-path-wins
# ---------------------------------------------------------------------------


def test_apply_leaves_executor_marked_table_untouched() -> None:
    slide = _table_slide(_HEADERS_4, _ROWS_4, table_preferred_column=1, table_hero_row=0)
    deck = _deck([slide], subtitle=_SCO2_SUBTITLE)

    provenance = apply_emphasis_fallback(deck)

    assert deck.slides[0].content.table_preferred_column == 1
    assert deck.slides[0].content.table_hero_row == 0
    assert provenance.slides[0].table_preferred_column is EmphasisSource.EXECUTOR
    assert provenance.slides[0].table_hero_row is EmphasisSource.EXECUTOR


def test_apply_fills_unmarked_data_emphasis_with_exactly_one_highlight() -> None:
    slide = _data_slide(
        [
            StatItem(value="100+", unit="kW", label="demand"),
            StatItem(value="25", unit="kW", label="limit"),
        ]
    )
    deck = _deck([slide])

    provenance = apply_emphasis_fallback(deck)

    highlighted = [s for s in (deck.slides[0].content.stats or []) if s.highlight]
    assert len(highlighted) == 1
    assert provenance.slides[0].hero_stat is EmphasisSource.FALLBACK


def test_apply_records_executor_when_a_stat_is_prehighlighted() -> None:
    slide = _data_slide(
        [
            StatItem(value="1.08", unit="PUE", label="efficiency", highlight=True),
            StatItem(value="25", unit="kW", label="limit"),
        ]
    )
    deck = _deck([slide])

    provenance = apply_emphasis_fallback(deck)

    assert provenance.slides[0].hero_stat is EmphasisSource.EXECUTOR


def test_section_thesis_provenance_is_plan_or_absent() -> None:
    with_thesis = SlideSpec(
        slide_index=0,
        slide_type=SlideType.CONTENT_SPLIT,
        content=SlideContent(title="With"),
        section_thesis="The section argues one concrete point.",
    )
    without_thesis = SlideSpec(
        slide_index=1,
        slide_type=SlideType.CONTENT_SPLIT,
        content=SlideContent(title="Without"),
    )
    provenance = apply_emphasis_fallback(_deck([with_thesis, without_thesis]))

    assert provenance.slides[0].section_thesis is EmphasisSource.PLAN
    assert provenance.slides[1].section_thesis is EmphasisSource.ABSENT


def test_out_of_range_executor_index_is_flagged_invalid() -> None:
    slide = _table_slide(["A", "B"], [TableRow(cells=["x", "y"])], table_preferred_column=9)
    deck = _deck([slide])  # no subject signal -> fallback finds no winner

    provenance = apply_emphasis_fallback(deck)

    # The bad index is discarded (not rendered) AND flagged as an executor error,
    # not as clean abstention — so the gate counts it against the executor.
    assert deck.slides[0].content.table_preferred_column is None
    assert provenance.slides[0].table_preferred_column is EmphasisSource.EXECUTOR_INVALID
    assert provenance.invalid_count == 1
    assert provenance.executor_count == 0


def test_executor_and_fallback_counts() -> None:
    executor_table = _table_slide(
        _HEADERS_4, _ROWS_4, index=0, table_preferred_column=3, table_hero_row=1
    )
    unmarked_data = _data_slide(
        [StatItem(value="1", unit="", label="a"), StatItem(value="2", unit="", label="b")], index=1
    )
    provenance = apply_emphasis_fallback(_deck([executor_table, unmarked_data]))

    assert provenance.executor_count == 2  # preferred_column + hero_row, both executor
    assert provenance.fallback_count == 1  # the data slide's hero stat
