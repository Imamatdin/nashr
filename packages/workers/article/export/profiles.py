"""Article export profiles as validated data, each rule carrying its source.

A profile is the complete, machine-checkable description of how one article
document is laid out: page geometry, margins, body font and size, line spacing,
first-line indent, heading styles, page numbering, and title-page style. The
compliance checker (``checker.py``) reads a produced DOCX back and verifies it
rule by rule against the profile, so every rule here must be expressible both as
a build instruction and as a read-back assertion.

Provenance (D8): every validated rule has an entry in :attr:`ArticleProfile.sources`
that is either :data:`NASHR_DEFAULT` (our own default, honestly labelled) or a
:class:`SourceRef` (a URL plus optional page we actually retrieved and checked).
Nothing without a source is ever presented as an external requirement.

The OAK document at oak.uz (``Ilmiy etiket va umumiy texnik talablar``) is a
scientific-ethics and journal-metadata standard; it contains no typographic
specification. The ``oak_default`` page geometry, fonts and spacing are therefore
the de-facto Uzbek university student-work convention, labelled ``NASHR_DEFAULT``.
The one rule that document does state (abstract length 100-250 words, section 20)
carries a real :class:`SourceRef` to it.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# The OAK standard we actually retrieved and read (ethics/metadata only).
_OAK_URL = "https://oak.uz/userfiles/files/Ilmiy_etiket_va_umumiy_texnik_talablar.pdf"

NASHR_DEFAULT = "nashr_default"

ArticleProfileId = Literal["oak_default", "apa_7", "apa_7_professional", "ieee"]

Alignment = Literal["left", "center", "right", "justify"]


class SourceRef(BaseModel):
    """A retrieved external source for a profile rule: a URL and optional page."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    url: str = Field(min_length=1, max_length=500)
    page: int | None = Field(default=None, ge=1)


# Either our honest default, or a source we actually checked. A rule can never be
# silently unsourced: the profile validator requires an entry for every rule key.
RuleSource = Literal["nashr_default"] | SourceRef


class TitlePageKind(StrEnum):
    """Which title-page layout the profile prescribes (none means no title page)."""

    NONE = "none"
    STUDENT = "student"  # Uzbek university referat / kurs ishi cover page
    APA_STUDENT = "apa_student"
    APA_PROFESSIONAL = "apa_professional"


class HeadingStyle(BaseModel):
    """One heading level's typography, both built and checked."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    level: int = Field(ge=1, le=3)
    size_pt: float = Field(gt=0, le=72)
    bold: bool
    italic: bool
    alignment: Alignment
    uppercase: bool
    space_before_pt: float = Field(ge=0, le=72)
    space_after_pt: float = Field(ge=0, le=72)


class PageNumbering(BaseModel):
    """Page-number rule: whether numbers appear and how the first page behaves."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    enabled: bool
    suppress_on_first_page: bool
    alignment: Literal["left", "center", "right"]


# Every validated rule must have a source entry. Keys that are always present:
_ALWAYS_SOURCED: frozenset[str] = frozenset(
    {
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
)


class ArticleProfile(BaseModel):
    """A complete, sourced, machine-checkable article layout profile."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: ArticleProfileId
    # Page geometry (cm).
    page_width_cm: float = Field(gt=0, le=100)
    page_height_cm: float = Field(gt=0, le=100)
    margin_top_cm: float = Field(ge=0, le=10)
    margin_bottom_cm: float = Field(ge=0, le=10)
    margin_left_cm: float = Field(ge=0, le=10)
    margin_right_cm: float = Field(ge=0, le=10)
    # Body text.
    body_font: str = Field(min_length=1, max_length=100)
    body_size_pt: float = Field(gt=0, le=72)
    line_spacing: float = Field(gt=0, le=4)
    first_line_indent_cm: float = Field(ge=0, le=10)
    # Headings L1..L3 in order.
    headings: tuple[HeadingStyle, HeadingStyle, HeadingStyle]
    page_numbers: PageNumbering
    title_page: TitlePageKind
    # Abstract length rule (only where a standard states one). Both or neither.
    abstract_min_words: int | None = Field(default=None, ge=1, le=100_000)
    abstract_max_words: int | None = Field(default=None, ge=1, le=100_000)
    # False when the profile is a best-effort approximation of a standard whose
    # official template we could not recover (e.g. IEEE two-column).
    verified: bool
    sources: dict[str, RuleSource]

    @model_validator(mode="after")
    def _rules_are_sourced_and_coherent(self) -> ArticleProfile:
        required = set(_ALWAYS_SOURCED)
        if (self.abstract_min_words is None) != (self.abstract_max_words is None):
            raise ValueError("abstract_min_words and abstract_max_words must be set together")
        if self.abstract_min_words is not None:
            required.add("abstract_word_count")
            if (
                self.abstract_max_words is not None
                and self.abstract_max_words < self.abstract_min_words
            ):
                raise ValueError("abstract_max_words must be >= abstract_min_words")
        missing = sorted(required - set(self.sources))
        if missing:
            raise ValueError(f"profile {self.id} is missing sources for rules: {missing}")
        extra = sorted(set(self.sources) - required)
        if extra:
            raise ValueError(f"profile {self.id} has sources for unknown rules: {extra}")
        levels = tuple(h.level for h in self.headings)
        if levels != (1, 2, 3):
            raise ValueError(
                f"profile {self.id} headings must be levels 1,2,3 in order, got {levels}"
            )
        return self

    def heading(self, level: int) -> HeadingStyle:
        """The heading style for ``level`` (1..3); levels past 3 clamp to 3."""

        index = min(max(level, 1), 3) - 1
        return self.headings[index]


def _student_headings() -> tuple[HeadingStyle, HeadingStyle, HeadingStyle]:
    return (
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
    )


# ---------------------------------------------------------------------------
# oak_default (D7): the Uzbek university student-work typographic convention.
# Every typographic rule is NASHR_DEFAULT: the OAK document states none of them.
# The abstract-length rule is the one genuine OAK citation.
# ---------------------------------------------------------------------------
_OAK_DEFAULT = ArticleProfile(
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
    headings=_student_headings(),
    page_numbers=PageNumbering(enabled=True, suppress_on_first_page=False, alignment="center"),
    title_page=TitlePageKind.STUDENT,
    abstract_min_words=100,
    abstract_max_words=250,
    verified=True,
    sources={
        "page_size": NASHR_DEFAULT,
        "margins": NASHR_DEFAULT,
        "body_font": NASHR_DEFAULT,
        "body_size": NASHR_DEFAULT,
        "line_spacing": NASHR_DEFAULT,
        "first_line_indent": NASHR_DEFAULT,
        "heading_1": NASHR_DEFAULT,
        "heading_2": NASHR_DEFAULT,
        "heading_3": NASHR_DEFAULT,
        "page_numbers": NASHR_DEFAULT,
        "title_page": NASHR_DEFAULT,
        "abstract_word_count": SourceRef(url=_OAK_URL, page=12),
    },
)


def _apa_headings() -> tuple[HeadingStyle, HeadingStyle, HeadingStyle]:
    # APA 7 heading levels 1-3: L1 centered bold; L2 flush-left bold;
    # L3 flush-left bold italic. All in the body font and size.
    return (
        HeadingStyle(
            level=1,
            size_pt=12,
            bold=True,
            italic=False,
            alignment="center",
            uppercase=False,
            space_before_pt=0,
            space_after_pt=0,
        ),
        HeadingStyle(
            level=2,
            size_pt=12,
            bold=True,
            italic=False,
            alignment="left",
            uppercase=False,
            space_before_pt=0,
            space_after_pt=0,
        ),
        HeadingStyle(
            level=3,
            size_pt=12,
            bold=True,
            italic=True,
            alignment="left",
            uppercase=False,
            space_before_pt=0,
            space_after_pt=0,
        ),
    )


# ---------------------------------------------------------------------------
# apa_7: our APA-7-aligned student-paper implementation. Sourced NASHR_DEFAULT
# because apastyle.apa.org could not be retrieved for verification (bot wall);
# values follow the published APA 7 student-paper conventions.
# ---------------------------------------------------------------------------
_APA_7 = ArticleProfile(
    id="apa_7",
    page_width_cm=21.59,  # US Letter 8.5 in
    page_height_cm=27.94,  # US Letter 11 in
    margin_top_cm=2.54,
    margin_bottom_cm=2.54,
    margin_left_cm=2.54,
    margin_right_cm=2.54,
    body_font="Times New Roman",
    body_size_pt=12,
    line_spacing=2.0,
    first_line_indent_cm=1.27,  # 0.5 in
    headings=_apa_headings(),
    page_numbers=PageNumbering(enabled=True, suppress_on_first_page=False, alignment="right"),
    title_page=TitlePageKind.APA_STUDENT,
    abstract_min_words=None,
    abstract_max_words=None,
    verified=True,
    sources={
        "page_size": NASHR_DEFAULT,
        "margins": NASHR_DEFAULT,
        "body_font": NASHR_DEFAULT,
        "body_size": NASHR_DEFAULT,
        "line_spacing": NASHR_DEFAULT,
        "first_line_indent": NASHR_DEFAULT,
        "heading_1": NASHR_DEFAULT,
        "heading_2": NASHR_DEFAULT,
        "heading_3": NASHR_DEFAULT,
        "page_numbers": NASHR_DEFAULT,
        "title_page": NASHR_DEFAULT,
    },
)

# APA 7 professional variant: same typography, professional title page.
_APA_7_PROFESSIONAL = _APA_7.model_copy(
    update={"id": "apa_7_professional", "title_page": TitlePageKind.APA_PROFESSIONAL}
)


def _ieee_headings() -> tuple[HeadingStyle, HeadingStyle, HeadingStyle]:
    return (
        HeadingStyle(
            level=1,
            size_pt=10,
            bold=False,
            italic=False,
            alignment="center",
            uppercase=True,
            space_before_pt=12,
            space_after_pt=6,
        ),
        HeadingStyle(
            level=2,
            size_pt=10,
            bold=False,
            italic=True,
            alignment="left",
            uppercase=False,
            space_before_pt=10,
            space_after_pt=4,
        ),
        HeadingStyle(
            level=3,
            size_pt=10,
            bold=False,
            italic=True,
            alignment="left",
            uppercase=False,
            space_before_pt=8,
            space_after_pt=4,
        ),
    )


# ---------------------------------------------------------------------------
# ieee: best-effort single-column approximation. verified=False because the
# official IEEE two-column conference template was not recovered. Honestly
# flagged so the UI can warn; sources NASHR_DEFAULT throughout.
# ---------------------------------------------------------------------------
_IEEE = ArticleProfile(
    id="ieee",
    page_width_cm=21.59,
    page_height_cm=27.94,
    margin_top_cm=1.9,
    margin_bottom_cm=2.54,
    margin_left_cm=1.59,
    margin_right_cm=1.59,
    body_font="Times New Roman",
    body_size_pt=10,
    line_spacing=1.0,
    first_line_indent_cm=0.46,
    headings=_ieee_headings(),
    page_numbers=PageNumbering(enabled=False, suppress_on_first_page=False, alignment="center"),
    title_page=TitlePageKind.NONE,
    abstract_min_words=None,
    abstract_max_words=None,
    verified=False,
    sources={
        "page_size": NASHR_DEFAULT,
        "margins": NASHR_DEFAULT,
        "body_font": NASHR_DEFAULT,
        "body_size": NASHR_DEFAULT,
        "line_spacing": NASHR_DEFAULT,
        "first_line_indent": NASHR_DEFAULT,
        "heading_1": NASHR_DEFAULT,
        "heading_2": NASHR_DEFAULT,
        "heading_3": NASHR_DEFAULT,
        "page_numbers": NASHR_DEFAULT,
        "title_page": NASHR_DEFAULT,
    },
)


_PROFILES: dict[str, ArticleProfile] = {
    "oak_default": _OAK_DEFAULT,
    "apa_7": _APA_7,
    "apa_7_professional": _APA_7_PROFESSIONAL,
    "ieee": _IEEE,
}


def profile_ids() -> tuple[str, ...]:
    """Every selectable profile id, including the apa_7 professional variant."""

    return tuple(_PROFILES)


def get_profile(profile_id: str) -> ArticleProfile:
    """Return the profile for ``profile_id`` or raise ``KeyError`` with the id."""

    try:
        return _PROFILES[profile_id]
    except KeyError as exc:
        raise KeyError(f"unknown article profile: {profile_id!r}") from exc


def all_profiles() -> tuple[ArticleProfile, ...]:
    """Every profile, for validation and the renderer-version hash."""

    return tuple(_PROFILES.values())


__all__ = [
    "NASHR_DEFAULT",
    "Alignment",
    "ArticleProfile",
    "ArticleProfileId",
    "HeadingStyle",
    "PageNumbering",
    "RuleSource",
    "SourceRef",
    "TitlePageKind",
    "all_profiles",
    "get_profile",
    "profile_ids",
]
