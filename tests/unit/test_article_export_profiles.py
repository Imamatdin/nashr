"""Profile data integrity (I-B6-1): every rule is sourced, nothing mislabeled."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from packages.workers.article.export.profiles import (
    NASHR_DEFAULT,
    ArticleProfile,
    HeadingStyle,
    PageNumbering,
    SourceRef,
    TitlePageKind,
    all_profiles,
    get_profile,
    profile_ids,
)

_SOURCED_RULES = {
    "page_size",
    "margins",
    "body_font",
    "body_size",
    "line_spacing",
    "first_line_indent",
    "heading_1",
    "heading_2",
    "heading_3",
    "page_numbers",
    "title_page",
}


def test_every_profile_sources_every_rule() -> None:
    for profile in all_profiles():
        required = set(_SOURCED_RULES)
        if profile.abstract_min_words is not None:
            required.add("abstract_word_count")
        assert set(profile.sources) == required, profile.id


def test_oak_typography_rules_are_nashr_default_not_oak() -> None:
    # The OAK document states no typography; every typographic rule must be our
    # own default, never presented as an OAK requirement.
    oak = get_profile("oak_default")
    for rule in _SOURCED_RULES:
        assert oak.sources[rule] == NASHR_DEFAULT, rule
    # The one rule the OAK document does state carries a real source.
    abstract_source = oak.sources["abstract_word_count"]
    assert isinstance(abstract_source, SourceRef)
    assert "oak.uz" in abstract_source.url
    assert abstract_source.page is not None


def test_d7_default_values() -> None:
    oak = get_profile("oak_default")
    assert (oak.page_width_cm, oak.page_height_cm) == (21.0, 29.7)
    assert (oak.margin_top_cm, oak.margin_bottom_cm) == (2.0, 2.0)
    assert (oak.margin_left_cm, oak.margin_right_cm) == (3.0, 1.5)
    assert oak.body_font == "Times New Roman"
    assert oak.body_size_pt == 14
    assert oak.line_spacing == 1.5
    assert oak.first_line_indent_cm == 1.25


def test_ieee_is_marked_unverified() -> None:
    assert get_profile("ieee").verified is False


def test_apa_variants_differ_only_by_title_page() -> None:
    student = get_profile("apa_7")
    professional = get_profile("apa_7_professional")
    assert student.title_page is TitlePageKind.APA_STUDENT
    assert professional.title_page is TitlePageKind.APA_PROFESSIONAL
    assert student.margin_left_cm == professional.margin_left_cm
    assert student.body_size_pt == professional.body_size_pt


def test_profile_ids_cover_registry() -> None:
    assert set(profile_ids()) == {"oak_default", "apa_7", "apa_7_professional", "ieee"}
    for pid in profile_ids():
        assert get_profile(pid).id == pid


def test_unknown_profile_raises() -> None:
    with pytest.raises(KeyError):
        get_profile("mla_9")


def test_profile_rejects_unsourced_rule() -> None:
    with pytest.raises(ValidationError):
        ArticleProfile(
            id="oak_default",
            page_width_cm=21.0,
            page_height_cm=29.7,
            margin_top_cm=2.0,
            margin_bottom_cm=2.0,
            margin_left_cm=3.0,
            margin_right_cm=1.5,
            body_font="Times New Roman",
            body_size_pt=14,
            line_spacing=1.5,
            first_line_indent_cm=1.25,
            headings=(
                HeadingStyle(
                    level=1,
                    size_pt=14,
                    bold=True,
                    italic=False,
                    alignment="center",
                    uppercase=True,
                    space_before_pt=12,
                    space_after_pt=6,
                ),
                HeadingStyle(
                    level=2,
                    size_pt=14,
                    bold=True,
                    italic=False,
                    alignment="left",
                    uppercase=False,
                    space_before_pt=12,
                    space_after_pt=6,
                ),
                HeadingStyle(
                    level=3,
                    size_pt=14,
                    bold=True,
                    italic=True,
                    alignment="left",
                    uppercase=False,
                    space_before_pt=12,
                    space_after_pt=6,
                ),
            ),
            page_numbers=PageNumbering(
                enabled=True, suppress_on_first_page=False, alignment="center"
            ),
            title_page=TitlePageKind.STUDENT,
            verified=True,
            sources={"page_size": NASHR_DEFAULT},  # missing the rest
        )
