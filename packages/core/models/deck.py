"""Presentation (deck) models: design direction, slides, and interactive specs."""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from packages.core.constants import (
    MAX_BODY_ITEM_LENGTH,
    MAX_BODY_ITEMS,
    MAX_SLIDES,
    MAX_SUBTITLE_LENGTH,
    MAX_TITLE_LENGTH,
    MIN_SLIDES,
)
from packages.core.enums import (
    Audience,
    BackgroundType,
    Language,
    LayoutMode,
    SlideType,
)

HEX_COLOR_RE: re.Pattern[str] = re.compile(r"^#([0-9a-fA-F]{6})$")


class ColorEntry(BaseModel):
    """One color in the design palette."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    hex: str = Field(min_length=7, max_length=7)
    name: str = Field(min_length=1, max_length=80)
    usage: str = Field(min_length=1, max_length=200)

    @field_validator("hex")
    @classmethod
    def _validate_hex(cls, value: str) -> str:
        if not HEX_COLOR_RE.match(value):
            raise ValueError("hex must match the pattern #RRGGBB")
        return value.upper()


class ColorPalette(BaseModel):
    """The 60-30-10 palette plus text colors."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    dominant_60: ColorEntry
    secondary_30: ColorEntry
    accent_10: ColorEntry
    text_primary: str = Field(min_length=7, max_length=7)
    text_secondary: str = Field(min_length=7, max_length=7)

    @field_validator("text_primary", "text_secondary")
    @classmethod
    def _validate_text_hex(cls, value: str) -> str:
        if not HEX_COLOR_RE.match(value):
            raise ValueError("text color must match the pattern #RRGGBB")
        return value.upper()


class TypographySpec(BaseModel):
    """Exactly two paired fonts: a display face and a body face."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    display_font: str = Field(min_length=1, max_length=80)
    display_weight: str = Field(min_length=1, max_length=20)
    body_font: str = Field(min_length=1, max_length=80)
    body_weight: str = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def _fonts_must_differ(self) -> TypographySpec:
        if self.display_font.lower() == self.body_font.lower():
            raise ValueError("display_font and body_font must differ for visual contrast")
        return self


class VisualTheme(BaseModel):
    """Mood-aligned visual direction shared across every slide in the deck."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    background_treatment: str = Field(min_length=1, max_length=500)
    decorative_elements: list[str] = Field(default_factory=list, max_length=10)
    image_style: str = Field(min_length=1, max_length=300)
    image_prompt_prefix: str = Field(min_length=1, max_length=500)


class DesignDirection(BaseModel):
    """Output of the Design Direction Pass: the deck's full creative brief."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    topic_analysis: str = Field(min_length=1, max_length=1000)
    mood: list[str] = Field(min_length=3, max_length=3)
    color_palette: ColorPalette
    typography: TypographySpec
    visual_theme: VisualTheme

    @field_validator("mood")
    @classmethod
    def _strip_mood(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value if item.strip()]
        if len(cleaned) != 3:
            raise ValueError("mood must contain exactly 3 non-empty adjectives")
        return cleaned


class VisualSpec(BaseModel):
    """How a slide's visual zone is described to the image generator."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    zone: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=1, max_length=1000)
    style: str = Field(min_length=1, max_length=200)


class BackgroundSpec(BaseModel):
    """Per-slide background description."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    type: BackgroundType
    description: str = Field(min_length=1, max_length=500)


class QuizOption(BaseModel):
    """One option in a multiple-choice quiz slide."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: str = Field(min_length=1, max_length=8)
    text: str = Field(min_length=1, max_length=300)
    correct: bool


class QuizFeedback(BaseModel):
    """Feedback shown after answering a quiz question."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    slide_id: str = Field(min_length=1, max_length=40)
    message: str = Field(min_length=1, max_length=300)


class MatchingPair(BaseModel):
    """One left/right pairing in a matching exercise."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    left: str = Field(min_length=1, max_length=150)
    right: str = Field(min_length=1, max_length=150)


class CategoryItem(BaseModel):
    """One item to be sorted into a named category."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    text: str = Field(min_length=1, max_length=150)
    category: str = Field(min_length=1, max_length=100)


class FillBlankItem(BaseModel):
    """A fill-in-the-blank question with a single answer."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    text_with_blank: str = Field(min_length=1, max_length=300)
    answer: str = Field(min_length=1, max_length=100)


class TrueFalseItem(BaseModel):
    """A true/false statement with the correct verdict and an explanation."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    statement: str = Field(min_length=1, max_length=300)
    correct: bool
    explanation: str = Field(min_length=1, max_length=300)


class DebateOption(BaseModel):
    """One position the user can pick in a debate scenario."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    text: str = Field(min_length=1, max_length=300)
    explanation: str = Field(min_length=1, max_length=500)


class DebateScenario(BaseModel):
    """A debate / role-play prompt with branching positions."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    setting: str = Field(min_length=1, max_length=300)
    prompt: str = Field(min_length=1, max_length=500)
    options: list[DebateOption] = Field(min_length=2, max_length=4)


class InteractiveSpec(BaseModel):
    """Type-discriminated interactive payload for quiz / matching / debate slides.

    Which fields are populated depends on the parent slide's :class:`SlideType`:
    quiz_mcq uses ``question`` + ``options`` + ``feedback_*``; quiz_matching
    uses ``pairs``; quiz_categorize uses ``categories`` + ``category_items``;
    quiz_fill_blank uses ``fill_items``; quiz_true_false uses
    ``true_false_items``; debate_scenario uses ``debate``.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    question: str | None = Field(default=None, max_length=500)
    options: list[QuizOption] | None = None
    feedback_correct: QuizFeedback | None = None
    feedback_wrong: QuizFeedback | None = None
    pairs: list[MatchingPair] | None = None
    categories: list[str] | None = None
    category_items: list[CategoryItem] | None = None
    fill_items: list[FillBlankItem] | None = None
    true_false_items: list[TrueFalseItem] | None = None
    debate: DebateScenario | None = None

    @model_validator(mode="after")
    def _mcq_must_have_a_correct_option(self) -> InteractiveSpec:
        if self.options is not None and not any(opt.correct for opt in self.options):
            raise ValueError(
                "InteractiveSpec.options must contain at least one correct=True option"
            )
        return self

    @model_validator(mode="after")
    def _categorize_items_reference_known_categories(self) -> InteractiveSpec:
        if self.category_items is not None:
            if self.categories is None:
                raise ValueError("InteractiveSpec.category_items requires categories to be set")
            allowed = set(self.categories)
            unknown = sorted({item.category for item in self.category_items} - allowed)
            if unknown:
                raise ValueError(f"category_items reference unknown categories: {unknown}")
        return self


class NavigationSpec(BaseModel):
    """Slide-to-slide navigation links rendered in the HTML output."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    prev: str | None = Field(default=None, max_length=40)
    next: str | None = Field(default=None, max_length=40)


class Slide(BaseModel):
    """One slide produced by the Layout Pass."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: str = Field(min_length=1, max_length=40)
    type: SlideType
    layout_mode: LayoutMode
    title: str = Field(min_length=1, max_length=MAX_TITLE_LENGTH)
    subtitle: str | None = Field(default=None, max_length=MAX_SUBTITLE_LENGTH)
    body: list[str] | None = None
    visual: VisualSpec | None = None
    background: BackgroundSpec
    interactive: InteractiveSpec | None = None
    speaker_notes: str | None = Field(default=None, max_length=2000)
    navigation: NavigationSpec

    @field_validator("body")
    @classmethod
    def _validate_body(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        if len(value) > MAX_BODY_ITEMS:
            raise ValueError(f"body may contain at most {MAX_BODY_ITEMS} items")
        for index, item in enumerate(value):
            if len(item) > MAX_BODY_ITEM_LENGTH:
                raise ValueError(
                    f"body[{index}] is {len(item)} chars; max is {MAX_BODY_ITEM_LENGTH}"
                )
            if not item.strip():
                raise ValueError(f"body[{index}] must not be blank")
        return value


class Deck(BaseModel):
    """Top-level presentation object — the output of the full pipeline."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=200)
    language: Language
    audience: Audience
    design_direction: DesignDirection
    slides: list[Slide] = Field(min_length=MIN_SLIDES, max_length=MAX_SLIDES)
