"""Presentation models for Design Language v2.

These types are the contract between the four passes of the presentation
pipeline (Design Direction → Editorial → Layout → Render) and between the
Python backend and the Node.js renderer. Every aesthetic decision, every
piece of slide content, and every audit finding flows through one of the
models defined here.

The module is intentionally a single file: the models are tightly coupled,
they exist solely to describe one cohesive wire format, and splitting them
across files would fragment the contract that callers import as a unit.
This is the exemption permitted in CLAUDE.md for coherent pipeline data
models.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from packages.core.enums import (
    AudienceType,
    AuditSeverity,
    BackgroundTreatment,
    DiagramStrategy,
    ExportFormat,
    Language,
    NarrativeEmphasis,
    NarrativePhase,
    PresentationMood,
    SlideType,
    SpeakerNotesStyle,
    TitleStyle,
)

HEX_COLOR_RE: re.Pattern[str] = re.compile(r"^#[0-9a-fA-F]{6}$")


# ---------------------------------------------------------------------------
# Design Direction Pass output
# ---------------------------------------------------------------------------


class ColorPalette(BaseModel):
    """Five-colour palette mapped to the renderer's CSS custom properties.

    Each field is a ``#RRGGBB`` literal validated at construction time. The
    field names map 1:1 to the CSS variables emitted into the rendered
    slide HTML: ``--slide-bg`` / ``--slide-surface`` / ``--slide-text``
    / ``--slide-accent`` / ``--slide-text-secondary``.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    background: str = Field(max_length=7)
    surface: str = Field(max_length=7)
    text: str = Field(max_length=7)
    accent: str = Field(max_length=7)
    text_secondary: str = Field(max_length=7)

    @field_validator("background", "surface", "text", "accent", "text_secondary")
    @classmethod
    def _validate_hex(cls, value: str) -> str:
        if not HEX_COLOR_RE.match(value):
            raise ValueError("colour must match the pattern #RRGGBB")
        return value.upper()


class DesignDirectionSpec(BaseModel):
    """Output of the Design Direction Pass. Frozen for the rest of the deck."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    mood: PresentationMood
    palette: ColorPalette
    heading_font: str = Field(min_length=1, max_length=100)
    body_font: str = Field(min_length=1, max_length=100)
    decorative_font: str | None = Field(default=None, max_length=100)
    image_style_prefix: str = Field(min_length=1, max_length=500)
    background_treatment: BackgroundTreatment


# ---------------------------------------------------------------------------
# Per-slide content primitives
# ---------------------------------------------------------------------------


class StatItem(BaseModel):
    """One statistic shown on a DATA_EMPHASIS slide."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    value: str = Field(min_length=1, max_length=20)
    unit: str = Field(default="", max_length=10)
    label: str = Field(min_length=1, max_length=100)
    highlight: bool = False
    trend: str | None = Field(default=None, max_length=4)
    comparison: str | None = Field(default=None, max_length=100)


class PersonItem(BaseModel):
    """One person rendered on a GALLERY_PEOPLE or TEAM_CREDITS slide."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=100)
    years: str | None = Field(default=None, max_length=30)
    role: str | None = Field(default=None, max_length=100)
    description: str | None = Field(default=None, max_length=200)
    portrait_prompt: str | None = Field(default=None, max_length=300)
    portrait_url: str | None = Field(default=None, max_length=1000)


class KeywordItem(BaseModel):
    """One keyword rendered on a TYPOGRAPHIC_KEYWORDS slide."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    term: str = Field(min_length=1, max_length=50)
    explanation: str = Field(min_length=1, max_length=200)


class ComparisonColumn(BaseModel):
    """One half of a COMPARISON slide."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    heading: str = Field(min_length=1, max_length=100)
    points: list[str] = Field(default_factory=list[str], max_length=6)
    is_preferred: bool = False


class TimelineNode(BaseModel):
    """One node on a TIMELINE slide."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    date: str = Field(min_length=1, max_length=30)
    label: str = Field(min_length=1, max_length=150)
    portrait_prompt: str | None = Field(default=None, max_length=300)


class FlowStep(BaseModel):
    """One step on a FLOW_PROCESS slide."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    label: str = Field(min_length=1, max_length=50)
    description: str = Field(min_length=1, max_length=100)
    icon: str | None = Field(default=None, max_length=30)


class TableRow(BaseModel):
    """One row in a TABLE_COMPACT slide."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    cells: list[str] = Field(default_factory=list[str], max_length=6)


class ChartSeriesPoint(BaseModel):
    """One data point in a CHART_DATA series: a label, a numeric value, and an
    optional unit.

    The value is a float (not a display string like :class:`StatItem.value`)
    because it is plotted, not typeset — the renderer needs the magnitude to
    size a bar or place a point. Formatting (thousands separators, decimals) is
    the renderer's job, so this model stays the raw datum.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    label: str = Field(min_length=1, max_length=60)
    value: float
    unit: str | None = Field(default=None, max_length=10)


class QuizOption(BaseModel):
    """One option for an INTERACTIVE_QUIZ_MCQ question."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    text: str = Field(min_length=1, max_length=200)
    is_correct: bool = False


class QuizQuestion(BaseModel):
    """One multiple-choice question."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    question: str = Field(min_length=1, max_length=300)
    options: list[QuizOption] = Field(min_length=2, max_length=4)
    explanation_correct: str = Field(min_length=1, max_length=300)
    explanation_wrong: str = Field(min_length=1, max_length=300)


class MatchingPair(BaseModel):
    """One pair for an INTERACTIVE_MATCHING slide."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    left: str = Field(min_length=1, max_length=100)
    right: str = Field(min_length=1, max_length=200)


class CategoryItem(BaseModel):
    """One item to sort on an INTERACTIVE_CATEGORIZE slide."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    term: str = Field(min_length=1, max_length=100)
    category: str = Field(min_length=1, max_length=50)


class FillBlankItem(BaseModel):
    """One fill-in-the-blank statement."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    statement: str = Field(min_length=1, max_length=300)
    answer: str = Field(min_length=1, max_length=100)


class TrueFalseItem(BaseModel):
    """One true/false statement."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    statement: str = Field(min_length=1, max_length=300)
    is_true: bool
    explanation: str = Field(min_length=1, max_length=300)


class DebateOption(BaseModel):
    """One position the user can pick in an INTERACTIVE_DEBATE slide."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    position: str = Field(min_length=1, max_length=200)
    framework_label: str = Field(min_length=1, max_length=200)


class ResourceLink(BaseModel):
    """One entry on a RESOURCES_LINKS slide."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=300)
    url: str = Field(min_length=1, max_length=1000)


# ---------------------------------------------------------------------------
# Slide content + slide spec + deck spec
# ---------------------------------------------------------------------------


class SlideContent(BaseModel):
    """Content for a single slide.

    Which subset of the optional fields is populated is determined by the
    parent :class:`SlideSpec.slide_type`; the Layout Pass is responsible
    for choosing the right combination. ``title`` is the only mandatory
    field — every slide in Design Language v2 carries a title.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=300)
    subtitle: str | None = Field(default=None, max_length=300)

    body_text: str | None = Field(default=None, max_length=1000)
    bullets: list[str] | None = Field(default=None, max_length=8)

    caption: str | None = Field(default=None, max_length=300)
    source_citation: str | None = Field(default=None, max_length=300)

    stats: list[StatItem] | None = Field(default=None, max_length=4)

    people: list[PersonItem] | None = Field(default=None, max_length=6)

    keywords: list[KeywordItem] | None = Field(default=None, max_length=6)

    left_column: ComparisonColumn | None = None
    right_column: ComparisonColumn | None = None

    timeline_nodes: list[TimelineNode] | None = Field(default=None, max_length=8)

    steps: list[FlowStep] | None = Field(default=None, max_length=6)

    quote_text: str | None = Field(default=None, max_length=300)
    quote_attribution: str | None = Field(default=None, max_length=100)

    table_headers: list[str] | None = Field(default=None, max_length=6)
    table_rows: list[TableRow] | None = Field(default=None, max_length=7)

    chart_series: list[ChartSeriesPoint] | None = Field(default=None, max_length=8)

    quiz_questions: list[QuizQuestion] | None = Field(default=None, max_length=5)

    matching_pairs: list[MatchingPair] | None = Field(default=None, max_length=6)

    category_labels: list[str] | None = Field(default=None, max_length=5)
    category_items: list[CategoryItem] | None = Field(default=None, max_length=12)

    fill_blanks: list[FillBlankItem] | None = Field(default=None, max_length=5)

    true_false_items: list[TrueFalseItem] | None = Field(default=None, max_length=5)

    debate_prompt: str | None = Field(default=None, max_length=500)
    debate_options: list[DebateOption] | None = Field(default=None, max_length=3)

    resources: list[ResourceLink] | None = Field(default=None, max_length=6)

    background_prompt: str | None = Field(default=None, max_length=500)
    background_url: str | None = Field(default=None, max_length=1000)

    speaker_notes: str | None = Field(default=None, max_length=2000)


class SlideSpec(BaseModel):
    """Complete specification for one slide; the Editorial Pass emits a list of these."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    slide_index: int = Field(ge=0)
    slide_type: SlideType
    content: SlideContent

    background_override: BackgroundTreatment | None = None
    accent_override: str | None = Field(default=None, max_length=7)

    source_claim_ids: list[str] = Field(default_factory=list[str], max_length=50)

    section_name: str | None = Field(default=None, max_length=100)
    narrative_role: str | None = Field(default=None, max_length=50)

    @field_validator("accent_override")
    @classmethod
    def _validate_accent_override(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not HEX_COLOR_RE.match(value):
            raise ValueError("accent_override must match the pattern #RRGGBB")
        return value.upper()


# ---------------------------------------------------------------------------
# Interview models (input to Design/Editorial passes)
# ---------------------------------------------------------------------------


class PresentationInterviewAnswers(BaseModel):
    """Resolved user preferences after the pre-generation interview."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    audience: AudienceType = AudienceType.UNDERGRADUATE
    talk_duration_minutes: int = Field(default=15, ge=3, le=60)
    language: Language = Language.UZ

    narrative_emphasis: NarrativeEmphasis = NarrativeEmphasis.BALANCED
    title_style: TitleStyle = TitleStyle.TAKEAWAY
    include_interactive: bool = True

    mood_override: PresentationMood | None = None
    background_treatment: BackgroundTreatment | None = None
    diagram_strategy: DiagramStrategy = DiagramStrategy.BUILD_SVG

    speaker_notes_style: SpeakerNotesStyle = SpeakerNotesStyle.BRIEF_TALKING_POINTS

    closing_ask: str | None = Field(default=None, max_length=500)

    headline_numbers: list[str] = Field(default_factory=list[str], max_length=10)

    anchor_source_id: str | None = Field(default=None, max_length=64)


class InterviewQuestionOption(BaseModel):
    """One selectable option on a single-select or multi-select question."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    value: str = Field(min_length=1, max_length=100)
    label: str = Field(min_length=1, max_length=300)
    is_default: bool = False


class InterviewQuestion(BaseModel):
    """One question shown to the user during the pre-generation interview."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    question_id: str = Field(min_length=1, max_length=50)
    question_text: str = Field(min_length=1, max_length=500)
    question_type: str = Field(min_length=1, max_length=20)
    options: list[InterviewQuestionOption] | None = Field(default=None, max_length=10)
    min_value: int | None = None
    max_value: int | None = None
    default_value: str | int | None = None
    placeholder: str | None = Field(default=None, max_length=200)
    help_text: str | None = Field(default=None, max_length=300)


class PresentationInterviewQuestions(BaseModel):
    """Complete interview script returned to the bot/UI layer."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    questions: list[InterviewQuestion] = Field(min_length=1, max_length=15)
    detected_domain: str = Field(min_length=1, max_length=32)
    estimated_slide_count: int = Field(ge=1, le=80)
    available_stats_count: int = Field(ge=0, le=1000)
    available_people_count: int = Field(ge=0, le=1000)


# ---------------------------------------------------------------------------
# Deck spec + audit
# ---------------------------------------------------------------------------


class DeckSpec(BaseModel):
    """Top-level deck specification — the contract handed to the renderer."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    project_id: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=300)
    subtitle: str | None = Field(default=None, max_length=300)
    language: Language = Language.UZ
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    design: DesignDirectionSpec

    interview: PresentationInterviewAnswers

    slides: list[SlideSpec] = Field(min_length=1, max_length=50)

    export_formats: list[ExportFormat] = Field(
        default_factory=lambda: [ExportFormat.HTML],
        max_length=4,
    )

    @property
    def slide_count(self) -> int:
        return len(self.slides)

    @property
    def content_slide_count(self) -> int:
        """Slides that are not section breaks."""
        return len([s for s in self.slides if s.slide_type is not SlideType.SECTION_BREAK])

    @property
    def interactive_slide_count(self) -> int:
        interactive_types: frozenset[SlideType] = frozenset(
            {
                SlideType.INTERACTIVE_QUIZ_MCQ,
                SlideType.INTERACTIVE_MATCHING,
                SlideType.INTERACTIVE_CATEGORIZE,
                SlideType.INTERACTIVE_FILL_BLANK,
                SlideType.INTERACTIVE_TRUE_FALSE,
                SlideType.INTERACTIVE_DEBATE,
            }
        )
        return len([s for s in self.slides if s.slide_type in interactive_types])


class AuditCheckResult(BaseModel):
    """Result of a single Q1..Q15 audit check on one deck."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    check_id: str = Field(min_length=1, max_length=10)
    check_name: str = Field(min_length=1, max_length=100)
    passed: bool
    severity: AuditSeverity
    slide_index: int | None = Field(default=None, ge=0)
    rule_reference: str | None = Field(default=None, max_length=10)
    message: str | None = Field(default=None, max_length=500)


class AuditReport(BaseModel):
    """Roll-up of every audit check for a deck.

    ``is_exportable`` mirrors "zero ``FAIL`` findings"; warnings never block
    export but are surfaced to the user for review. Maintained as a stored
    field rather than a property so callers can serialise the report and
    later reconstruct it without recomputing.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    deck_id: str = Field(min_length=1, max_length=64)
    total_checks: int = Field(ge=0)
    passed: int = Field(ge=0)
    failed: int = Field(ge=0)
    warnings: int = Field(ge=0)
    is_exportable: bool
    results: list[AuditCheckResult] = Field(default_factory=list[AuditCheckResult], max_length=200)


def new_deck_id() -> str:
    """Return a fresh deck identifier for use in audit reports and DeckSpec."""
    return str(uuid4())


# ---------------------------------------------------------------------------
# Editorial Pass intermediate models
# ---------------------------------------------------------------------------


class ContentAnalysis(BaseModel):
    """Curated view of the source material handed to the Editorial Pass.

    The Editorial Pass cannot feed every claim into the LLM call. This
    analysis pre-groups claims by rhetorical role, surfaces the strongest
    candidates for emphasis slides, and records detected entities (people,
    statistics) so the LLM is asked to *select* rather than to *discover*.

    All list-of-claim fields carry the claim text only — full
    :class:`SourceClaimCreate` objects are intentionally not embedded so
    the analysis serialises cheaply and the LLM prompt size stays bounded.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    total_claims: int = Field(default=0, ge=0)

    statistical_claims: list[str] = Field(default_factory=list[str], max_length=200)
    empirical_findings: list[str] = Field(default_factory=list[str], max_length=200)
    theoretical_arguments: list[str] = Field(default_factory=list[str], max_length=200)
    definitions: list[str] = Field(default_factory=list[str], max_length=100)
    comparisons: list[str] = Field(default_factory=list[str], max_length=100)

    people_mentioned: list[str] = Field(default_factory=list[str], max_length=50)
    key_numbers: list[str] = Field(default_factory=list[str], max_length=100)

    has_timeline_content: bool = False
    has_comparison_content: bool = False
    has_process_content: bool = False

    strongest_claims: list[str] = Field(default_factory=list[str], max_length=10)


class NarrativeArc(BaseModel):
    """Ordered list of narrative phases plus the emphasised phase.

    ``phases`` is the canonical phase order (HOOK → CLOSE); ``emphasis_phase``
    indicates which phase should receive the largest fraction of the slide
    budget. The Editorial Pass uses both to allocate slides across the deck.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    phases: list[NarrativePhase] = Field(min_length=1, max_length=10)
    emphasis_phase: NarrativePhase
