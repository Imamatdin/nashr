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
    ChartType,
    DiagramStrategy,
    ExportFormat,
    ImageSubjectType,
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
    unit: str = Field(default="", max_length=32)
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
    """One node on a TIMELINE slide.

    ``portrait_prompt`` carries the editorial hint (a name + context) and
    ``portrait_url`` the resolved Commons image the renderer draws. Both
    optional: a timeline node without a person renders as a plain dated
    label, exactly as before.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    date: str = Field(min_length=1, max_length=30)
    label: str = Field(min_length=1, max_length=150)
    portrait_prompt: str | None = Field(default=None, max_length=300)
    portrait_url: str | None = Field(default=None, max_length=1000)


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

    ``values`` carries the per-group magnitudes for GROUPED_BAR / STACKED_BAR
    charts, aligned 1:1 to :attr:`SlideContent.chart_group_labels`. It is
    additive: the flat ``value`` stays the source of truth for bar/line/
    single_value, and a point that omits ``values`` validates unchanged. When
    a grouped/stacked chart sees a point with ``values``, it plots those; a
    point without falls back to the scalar ``value`` as a single group.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    label: str = Field(min_length=1, max_length=60)
    value: float
    unit: str | None = Field(default=None, max_length=32)
    values: list[float] | None = Field(default=None, max_length=6)


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
    chart_type: ChartType | None = None
    chart_group_labels: list[str] | None = Field(default=None, max_length=6)

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

    figure_prompt: str | None = Field(default=None, max_length=300)
    figure_url: str | None = Field(default=None, max_length=1000)
    figure_subject_type: ImageSubjectType | None = None

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


# ---------------------------------------------------------------------------
# Planner Pass models (Phase 1 of the editorial re-architecture)
# ---------------------------------------------------------------------------
#
# The Planner Pass runs BEFORE the Editorial Pass and produces a binding
# authorship plan: a thesis, a sequence of section theses, and a roster of
# real figures named by the source. Phase 1 (these models + the planner +
# the plan validator) is additive — editorial's control flow is not yet
# rewired. Phase 2 binds editorial to the plan and removes the curated
# claim-string author path that lets the model substitute facts the source
# never contained (the Bach/Mozart → Beethoven failure).


class PlannedFigure(BaseModel):
    """A real person the source names, eligible to appear as a portrait.

    Extracted by the Planner Pass directly from source TEXT (chunks), never
    from a hardcoded keyword roster — that is the editorial bug the planner
    exists to remove. ``name`` and ``years`` are the disambiguation signal
    :class:`packages.presentation.commons_portraits.CommonsPortraitResolver`
    matches against Wikidata P569/P570; both should be populated when the
    source gives them, but ``years`` stays optional because some sources
    legitimately omit dates. ``why_in_source`` is the grounding anchor — a
    one-line paraphrase of what the source actually says about this figure;
    the plan validator's source-fidelity gate requires it to be non-empty,
    and Phase 2's deck-vs-plan validator will use it to verify that any
    slide claim about the figure is consistent with the source.

    ``source_claim_ids`` is the optional join key from the figure back into
    the project's extracted :class:`SourceClaimCreate` list. Phase 1 leaves
    it as a forward-looking field; Phase 2's deck-vs-plan validator can
    enforce that a figure-bearing slide cites a claim from this list.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=100)
    years: str | None = Field(default=None, max_length=30)
    why_in_source: str = Field(min_length=1, max_length=300)
    source_claim_ids: list[str] = Field(default_factory=list[str], max_length=50)


class PlannedSection(BaseModel):
    """One movement of the deck's argument.

    ``thesis`` is a CLAIM the section argues, not a label. "Introduction" is
    not a thesis; "Science breaks the authority of inherited dogma" is. The
    plan validator's arc non-genericness gate enforces this STRUCTURALLY (no
    banned-word lists, no per-language stopword tables): it requires the
    thesis to differ from the section name, to be a multi-token predication
    rather than a noun phrase, and to introduce real content beyond the
    label. See :mod:`packages.presentation.plan_validator` for the exact
    heuristic and the rationale.

    ``figure_names`` is the subset of the deck-level :attr:`DeckPlan.figures`
    roster that this section portrays. The validator enforces it is a
    subset; any name a section claims to portray that is not in the roster
    means the planner LLM either hallucinated a figure or named one the
    source did not contain — that is the gate that would have caught the
    Beethoven substitution.

    ``planned_slide_types`` is advisory in Phase 1: the section's hint to
    Phase 2's executor for how to render this movement. Each entry is a
    real :class:`SlideType` enum value.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    section_name: str = Field(min_length=1, max_length=100)
    thesis: str = Field(min_length=12, max_length=300)
    phase: NarrativePhase
    figure_names: list[str] = Field(default_factory=list[str], max_length=12)
    planned_slide_types: list[SlideType] = Field(default_factory=list[SlideType], max_length=10)


class DeckPlan(BaseModel):
    """Binding authorship plan produced before slide generation.

    The thesis and sections are the deck's spine; in Phase 2 the executor
    fills this plan section by section instead of inventing the deck, and
    the validator rejects slides that contradict it. In Phase 1 the plan is
    produced and validated in isolation by the proof harness.

    ``figures`` is the complete roster of real people the source names that
    the deck may portray. The 30-entry ceiling mirrors the deck-level scale
    of :attr:`DeckSpec.slides` (max 50) so a roster cannot dwarf the deck
    it provisions: a source naming more than 30 distinct figures is
    vanishingly rare in practice, and the planner is asked to pick the
    load-bearing ones rather than list everyone.

    ``image_cohesion_note`` is the one-line aesthetic anchor every
    generated image in the deck shares so the deck reads as authored
    (a single voice, not a magazine). Wiring it into
    :attr:`DesignDirectionSpec.image_style_prefix` is deferred to the
    visual-system work, NOT Phase 2: the planner runs inside the editorial
    pass, which the orchestrator invokes AFTER the design pass, so feeding
    cohesion back to design needs a pipeline reorder that belongs with that
    phase. Phase 2 binds editorial to the plan but leaves design untouched.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    thesis: str = Field(min_length=20, max_length=400)
    audience_takeaway: str = Field(min_length=12, max_length=300)
    sections: list[PlannedSection] = Field(min_length=2, max_length=8)
    figures: list[PlannedFigure] = Field(default_factory=list[PlannedFigure], max_length=30)
    image_cohesion_note: str = Field(min_length=12, max_length=500)


class PlanValidationResult(BaseModel):
    """Result of running :func:`plan_validator.validate_plan` over a DeckPlan.

    Thin wrapper around the existing :class:`AuditCheckResult` /
    :class:`AuditSeverity` vocabulary so plan-time and deck-time audit
    findings are presented and rendered identically. We do NOT reuse
    :class:`AuditReport` because that type carries a deck_id, which a plan
    does not have until the executor runs.

    ``passed`` is a derived flag: True iff there are zero ``FAIL`` findings.
    Warnings never block — they are informational signals the planner gave
    a structurally weak plan (e.g. a roster of named figures but no section
    portrays any of them — the original Beethoven bug's signature).
    """

    model_config = ConfigDict(extra="forbid")

    findings: list[AuditCheckResult] = Field(default_factory=list[AuditCheckResult], max_length=200)

    @property
    def passed(self) -> bool:
        return not any(f.severity is AuditSeverity.FAIL for f in self.findings)

    @property
    def failures(self) -> list[AuditCheckResult]:
        return [f for f in self.findings if f.severity is AuditSeverity.FAIL]

    @property
    def warnings(self) -> list[AuditCheckResult]:
        return [f for f in self.findings if f.severity is AuditSeverity.WARN]


class ThesisVerdict(BaseModel):
    """One classifier verdict on whether a section's thesis is a real predication.

    Phase 1.5 of the planner re-architecture replaces the token-count
    structural checks (which were biased against agglutinative languages
    like Karakalpak / Uzbek / Turkish, where a 3-token clause is a real
    predication) with a multilingual LLM judgement. The classifier
    returns one of these verdicts per section in the plan; the validator's
    async path appends a ``P-A3`` failing finding for every verdict where
    :attr:`is_thesis` is ``False``.

    ``reason`` is written in English regardless of the input language so
    debug logs and validator messages stay readable when the source is in
    Karakalpak / Uzbek / Russian. The classifier prompt enforces this.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    is_thesis: bool
    reason: str = Field(min_length=1, max_length=200)
