"""Editorial Pass for the presentation pipeline.

The pass turns evidence-backed source material plus a frozen
:class:`DesignDirectionSpec` into a complete :class:`DeckSpec`. It is
the highest-leverage LLM call in the pipeline: bad editorial judgment
cannot be rescued by colors or layout.

Pipeline:

1. Size the deck from content volume (extracted claim count) plus
   optional interactive slides.
2. Analyse content (pure Python) — group claims by rhetorical type,
   detect people/numbers/comparisons, surface the strongest claims.
3. Select a narrative arc from the user's emphasis choice.
4. LLM call (Sonnet) — generate the slide sequence with takeaway titles,
   typed content, and narrative roles.
5. Post-process — drop hollow SECTION_BREAK dividers that carry no thesis
   (invariant I2, ``docs/INVARIANTS.md``); ensure first-slide is TITLE_HERO;
   enforce R17 (word-count limits) and R26 (density arc); re-index. The
   breather device (R27) is retained but defaults OFF — see
   :func:`_insert_breathing_after_data`. R01/R03 are now model-prompt
   concerns (EDITORIAL_SYSTEM rules 7-8), not post-process invariants:
   the old auto-injected hollow dividers that satisfied them are slop.
6. Optional LLM call (Gemini Flash) — generate quiz / matching /
   fill-blank / true-false / debate / categorise content for interactive
   slides.
7. Merge interactive slides into the content sequence at section
   boundaries (R28).
8. Assemble the :class:`DeckSpec` with deck-level metadata.

The 300-line CLAUDE.md budget is intentionally exceeded here: every
stage shares state (interview, design, claim list, current slide
sequence) and splitting them across modules would just fan-out a single
coherent operation. Module-level helpers live at module scope so the
class body stays readable.
"""

from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from typing import Any, Final, NamedTuple, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from packages.core.enums import (
    PEOPLE_RENDERING_SLIDE_TYPES,
    AudienceType,
    AuditSeverity,
    ChartType,
    ClaimStrength,
    ClaimType,
    ExportFormat,
    ImageSubjectType,
    Language,
    NarrativeEmphasis,
    NarrativePhase,
    SlideType,
)
from packages.core.gemini import GEMINI_FLASH_3_5_MODEL, GeminiClient
from packages.core.llm import LLMClient
from packages.core.models.article import ArticleOutline
from packages.core.models.evidence import EvidenceMatrix
from packages.core.models.presentation import (
    AuditCheckResult,
    CategoryItem,
    ChartSeriesPoint,
    ComparisonColumn,
    ContentAnalysis,
    DebateOption,
    DeckPlan,
    DeckSpec,
    DesignDirectionSpec,
    FillBlankItem,
    FlowStep,
    KeywordItem,
    MatchingPair,
    NarrativeArc,
    PersonItem,
    PresentationInterviewAnswers,
    QuizQuestion,
    SlideContent,
    SlideRegenResult,
    SlideSpec,
    StatItem,
    TableRow,
    TimelineNode,
    TrueFalseItem,
    find_slide_by_id,
)
from packages.core.models.source import (
    SourceChunkCreate,
    SourceClaimCreate,
    SourceMetadataExtracted,
)
from packages.core.prompts import (
    EDITORIAL_REPAIR_USER,
    EDITORIAL_RETRY_SUFFIX,
    EDITORIAL_SCHEMA_RETRY_HEADER,
    EDITORIAL_SLIDE_REGEN_SYSTEM,
    EDITORIAL_SLIDE_REGEN_USER,
    EDITORIAL_SYSTEM,
    EDITORIAL_USER,
    INTERACTIVE_RETRY_SUFFIX,
    INTERACTIVE_SCHEMA_RETRY_HEADER,
    INTERACTIVE_SYSTEM,
    INTERACTIVE_USER,
)
from packages.presentation._schema_feedback import (
    format_schema_feedback,
    loc_path,
    summarise_errors,
)
from packages.presentation.content_critic import (
    HARD_STOP_CHECK_IDS,
    ROUTABLE_CHECK_IDS,
    critique_deck_adversarially,
)
from packages.presentation.emphasis import EmphasisProvenance, apply_emphasis_fallback
from packages.presentation.plan_validator import (
    failing_section_indices,
    validate_deck_against_plan,
    validate_plan_async,
    validate_slide_against_plan,
)
from packages.presentation.planner import PlannerPass
from packages.presentation.thesis_classifier import ThesisClassifier

logger = logging.getLogger(__name__)


SONNET_MODEL: Final[str] = "claude-sonnet-4-6"
DEFAULT_PROJECT_ID: Final[str] = "presentation"

# Interactive content runs on Gemini 3.5 Flash, which spends "thoughts" tokens
# before visible output; the budget must clear the thinking phase plus the
# quiz/matching JSON or the response truncates and no interactive slides ship.
# (The pass ran at 3k on 2.5 Flash, which had no thinking tokens.)
INTERACTIVE_MAX_TOKENS: Final[int] = 8_000

# Per-call timeout for the editorial executor's Sonnet call (and the section
# repair, which reuses the same helper). The executor runs at 16k max_tokens
# and now carries the full plan spine, so a complete plan-bound deck
# legitimately takes minutes — longer than the shared DEFAULT_LLM_TIMEOUT_SECONDS
# (180s) that suits the small planner/classifier calls. 300s is a CEILING that
# comfortably covers a ~16k-token generation (~200-270s at Sonnet rates); a
# typical deck returns well under it, so this never slows a normal call. If real
# generations routinely approach 300s, the proper fix is streaming the
# completion (or a lower max_tokens), not a higher ceiling.
EDITORIAL_LLM_TIMEOUT_SECONDS: Final[int] = 300

# Deck sizing is driven by content volume, not talk duration. Floor 6:
# anything thinner is not a deck. Ceiling 15: anything fatter is a
# document, not a presentation (a human making a real 5-minute pitch deck
# tops out around 15 content slides).
MIN_CONTENT_SLIDES: Final[int] = 6
MAX_CONTENT_SLIDES: Final[int] = 15

# Upper bound for a title synthesised during coercion; mirrors
# SlideContent.title / _LLMSlide.title so the salvaged value re-validates.
_TITLE_MAX: Final[int] = 300

# R17 word-count limits keyed by slide type. The post-processor enforces
# these by truncating body text and moving the excess to speaker notes.
WORD_LIMITS: Final[dict[SlideType, int]] = {
    SlideType.TITLE_HERO: 15,
    SlideType.DATA_EMPHASIS: 30,
    SlideType.QUOTE_PULLQUOTE: 35,
    SlideType.SECTION_BREAK: 6,
    SlideType.CONCEPT_DEFINITION: 50,
    SlideType.CONTENT_SPLIT: 60,
    SlideType.GALLERY_PEOPLE: 60,
    SlideType.COMPARISON: 70,
    SlideType.TYPOGRAPHIC_KEYWORDS: 55,
    SlideType.TIMELINE: 50,
    SlideType.FLOW_PROCESS: 50,
    SlideType.CHART_DATA: 20,
    SlideType.TABLE_COMPACT: 80,
    SlideType.SUMMARY_TAKEAWAY: 60,
    SlideType.RESOURCES_LINKS: 60,
    SlideType.TEAM_CREDITS: 40,
    SlideType.INTERACTIVE_QUIZ_MCQ: 50,
    SlideType.INTERACTIVE_MATCHING: 50,
    SlideType.INTERACTIVE_CATEGORIZE: 50,
    SlideType.INTERACTIVE_FILL_BLANK: 50,
    SlideType.INTERACTIVE_TRUE_FALSE: 50,
    SlideType.INTERACTIVE_DEBATE: 70,
}

SLIDE_TYPE_DESCRIPTIONS: Final[dict[SlideType, str]] = {
    SlideType.TITLE_HERO: "Opening slide. Large title + subtitle. Full-bleed background. Max 15 words.",
    SlideType.CONCEPT_DEFINITION: (
        "Introduce a concept. 1-sentence definition + 3-5 short bullets. Max 50 words."
    ),
    SlideType.GALLERY_PEOPLE: (
        "Show 3-5 key people. Name + dates + one-line description each. Max 60 words."
    ),
    SlideType.TYPOGRAPHIC_KEYWORDS: "3-6 key terms with short explanations. Max 55 words.",
    SlideType.CONTENT_SPLIT: "Body text + image. Title + 4-5 lines text. Max 60 words.",
    SlideType.DATA_EMPHASIS: "1-4 big numbers with labels. Stats are the visual focus. Max 30 words.",
    SlideType.COMPARISON: (
        "Side-by-side comparison. 2 columns with heading + points. Max 70 words."
    ),
    SlideType.TIMELINE: "3-6 chronological events. Date + one-line per event. Max 50 words.",
    SlideType.FLOW_PROCESS: (
        "3-5 sequential steps. Label + short description per step. Max 50 words."
    ),
    SlideType.QUOTE_PULLQUOTE: "One powerful quote or finding. The quote IS the slide. Max 35 words.",
    SlideType.CHART_DATA: "One chart/graph. Title states the insight. Max 20 words of text.",
    SlideType.TABLE_COMPACT: "Structured data. Max 5 columns x 6 rows.",
    SlideType.SECTION_BREAK: (
        "Section transition. Put the section LABEL in section_name, and put a"
        " ONE-LINE THESIS for the section in subtitle (the section's argument,"
        " not its name). A SECTION_BREAK with no subtitle is dropped — invariant"
        " I2: a slide that only names a section carries no weight. Most decks"
        " flow content→content; emit a SECTION_BREAK only when a thesis earns it."
        " Title max 6 words; subtitle max 130 chars."
    ),
    SlideType.SUMMARY_TAKEAWAY: "3-5 numbered takeaways from preceding section. Max 60 words.",
    SlideType.RESOURCES_LINKS: "3-6 resource links with descriptions. Max 60 words.",
    SlideType.TEAM_CREDITS: "Team members with names + roles. Max 40 words.",
}

_DATA_HEAVY_TYPES: Final[frozenset[SlideType]] = frozenset(
    {SlideType.DATA_EMPHASIS, SlideType.CHART_DATA, SlideType.TABLE_COMPACT}
)

_BREATHING_TYPES: Final[frozenset[SlideType]] = frozenset(
    {SlideType.QUOTE_PULLQUOTE, SlideType.SUMMARY_TAKEAWAY, SlideType.SECTION_BREAK}
)

_INTERACTIVE_TYPES: Final[frozenset[SlideType]] = frozenset(
    {
        SlideType.INTERACTIVE_QUIZ_MCQ,
        SlideType.INTERACTIVE_MATCHING,
        SlideType.INTERACTIVE_CATEGORIZE,
        SlideType.INTERACTIVE_FILL_BLANK,
        SlideType.INTERACTIVE_TRUE_FALSE,
        SlideType.INTERACTIVE_DEBATE,
    }
)

# R26: dense slide types (tables, full-column comparisons) belong in the
# middle/late deck. The opening (first 3 slides) must be sparse so the
# audience eases into the material.
_DENSE_TYPES: Final[frozenset[SlideType]] = frozenset(
    {SlideType.TABLE_COMPACT, SlideType.COMPARISON, SlideType.TIMELINE}
)

_SPARSE_OPENING_TYPES: Final[frozenset[SlideType]] = frozenset(
    {
        SlideType.TITLE_HERO,
        SlideType.CONCEPT_DEFINITION,
        SlideType.CONTENT_SPLIT,
        SlideType.QUOTE_PULLQUOTE,
        SlideType.DATA_EMPHASIS,
        SlideType.SECTION_BREAK,
        SlideType.TYPOGRAPHIC_KEYWORDS,
    }
)


_COMPARISON_MARKERS: Final[tuple[str, ...]] = (
    "compared to",
    "compared with",
    "versus",
    " vs ",
    " vs.",
    "in contrast",
    "contrasted",
    "rather than",
    "outperform",
    "more than",
    "less than",
)

_PROCESS_MARKERS: Final[tuple[str, ...]] = (
    "first,",
    "second,",
    "third,",
    "step 1",
    "step one",
    "next,",
    "finally,",
    "process",
    "procedure",
    "pipeline",
    "workflow",
)

_TIMELINE_MARKERS: Final[tuple[str, ...]] = (
    "in 18",
    "in 19",
    "in 20",
    "century",
    "decade",
    "era",
    "before christ",
    " bce",
    " ce ",
    "founded in",
    "established in",
)

# Pulls statistical magnitudes from claim text: percentages, dollar
# amounts, numbers with units (kg, km, MW), large numbers with commas
# (516,120), and shorthand magnitudes ($1.04M, 2.5B).
_NUMBER_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"\$\s*\d+(?:[.,]\d+)*\s*[KMB]?", re.IGNORECASE),
    re.compile(r"\d+(?:\.\d+)?\s*%"),
    re.compile(r"\d{1,3}(?:,\d{3})+(?:\s+\w+)?"),
    re.compile(
        r"\d+(?:\.\d+)?\s*(?:kg|km|m|mw|gw|kw|kWh|MW|GW|°C|°F|hz|MHz|GHz|"
        r"tonnes?|metres?|meters?|miles?|hectares?|years?|months?|days?)",
        re.IGNORECASE,
    ),
)

_CLAIM_STRENGTH_RANK: Final[dict[ClaimStrength, int]] = {
    ClaimStrength.STRONG: 3,
    ClaimStrength.MODERATE: 2,
    ClaimStrength.WEAK: 1,
}

# Title carried by the SUMMARY_TAKEAWAY slide in the emergency-minimal deck. This
# is the user-facing message ONLY; whether a deck IS the emergency fallback is
# tracked by an explicit flag set at its origin (see ``generate_deck_spec``), never
# inferred from this title or the deck's shape — so a real deck that happens to use
# this title is still gated normally.
_EMERGENCY_TAKEAWAY_TITLE: Final[str] = "Insufficient source material"


# ---------------------------------------------------------------------------
# Typed editorial failures (Phase 2)
# ---------------------------------------------------------------------------
#
# Editorial historically degraded to the emergency-minimal deck on bad LLM
# output. Phase 2 keeps that ONLY for "the executor returned nothing usable".
# A plan that fails validation, or a deck that contradicts its plan, is a
# QUALITY failure the user should see (and that should refund) — so it raises.
# The orchestrator's existing ``except Exception -> _OrchestratorError(
# "editorial", ...)`` surfaces these unchanged.


class EditorialError(RuntimeError):
    """Base class for editorial-pass failures that must not silently degrade."""


class EditorialPlanRejectedError(EditorialError):
    """The planner's plan failed validation twice (initial + one re-plan).

    Carries the failing :class:`AuditCheckResult` findings so the orchestrator
    and logs can show exactly which sections or figures were rejected.
    """

    def __init__(self, findings: list[AuditCheckResult]) -> None:
        self.findings = findings
        detail = "; ".join(f"[{f.check_id}] {f.message or ''}" for f in findings) or "(no detail)"
        super().__init__(f"Plan rejected after one re-plan: {detail}")


class EditorialDeckPlanMismatchError(EditorialError):
    """The generated deck contradicted its plan even after one repair.

    Carries the residual failing findings (a section dropped, a planned figure
    missing, or a person invented) that survived the targeted section repair.
    """

    def __init__(self, findings: list[AuditCheckResult]) -> None:
        self.findings = findings
        detail = "; ".join(f"[{f.check_id}] {f.message or ''}" for f in findings) or "(no detail)"
        super().__init__(f"Deck contradicts its plan after one repair: {detail}")


class EditorialSlideRegenError(EditorialError):
    """Single-slide regeneration could not produce a result at all.

    Distinct from a regen that PRODUCED a slide with quality findings (that is a
    :class:`SlideRegenResult` with FAIL findings, not an exception). This is
    raised only when there is nothing to return: the deck has no persisted plan
    (so the figure-roster grounding guard would be disabled — the exact
    fabrication risk the system exists to stop), the target ``slide_id`` is not
    in the deck, or the LLM returned nothing usable after its informed retry.
    """


class EditorialContentCriticError(EditorialError):
    """The content critic confirmed a source-grounding defect that survived repair.

    Raised when, after one round of single-slide regeneration, the adversarial
    content critic still reports a code-confirmed FABRICATION or CLAIM_UNSUPPORTED
    finding (a verbatim fact-token on a slide that is absent from the full source
    claims). Shipping a known, logged fabrication is exactly what the
    source-grounding contract forbids, so this is a hard stop that propagates to
    the orchestrator and refunds the user. Carries the residual hard-stop findings
    so the handler can surface an honest "couldn't ground some claims" message.
    Cosmetic, structural, chart, and title findings never raise this — they are
    WARN and ship.
    """

    def __init__(self, findings: list[AuditCheckResult]) -> None:
        self.findings = findings
        detail = "; ".join(f"[{f.check_id}] {f.message or ''}" for f in findings) or "(no detail)"
        super().__init__(f"Deck makes claims the source does not support: {detail}")


# ---------------------------------------------------------------------------
# Parsing schemas for LLM output
# ---------------------------------------------------------------------------


class _LLMComparison(BaseModel):
    """A side of a comparison as emitted by the editorial LLM call."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    heading: str = Field(default="", max_length=100)
    points: list[str] = Field(default_factory=list[str], max_length=6)


class _LLMSlide(BaseModel):
    """Permissive shape of a single slide in the editorial LLM response."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    slide_index: int = Field(default=0, ge=0)
    # 0-based index into DeckPlan.sections — the binding tag the executor sets
    # so deck-vs-plan membership is a deterministic join, not a fuzzy name
    # match. Optional so a single missing tag salvages (falls back to
    # section_name) rather than dropping the whole deck.
    section_index: int | None = Field(default=None, ge=0)
    slide_type: SlideType
    title: str = Field(min_length=1, max_length=300)
    subtitle: str | None = Field(default=None, max_length=300)
    body_text: str | None = Field(default=None, max_length=1000)
    bullets: list[str] | None = Field(default=None, max_length=8)
    stats: list[StatItem] | None = Field(default=None, max_length=4)
    people: list[PersonItem] | None = Field(default=None, max_length=6)
    keywords: list[KeywordItem] | None = Field(default=None, max_length=6)
    left_column: _LLMComparison | None = None
    right_column: _LLMComparison | None = None
    table_headers: list[str] | None = Field(default=None, max_length=6)
    table_rows: list[TableRow] | None = Field(default=None, max_length=7)
    table_preferred_column: int | None = Field(default=None, ge=0)
    table_hero_row: int | None = Field(default=None, ge=0)
    chart_series: list[ChartSeriesPoint] | None = Field(default=None, max_length=8)
    chart_type: ChartType | None = None
    chart_group_labels: list[str] | None = Field(default=None, max_length=6)
    timeline_nodes: list[TimelineNode] | None = Field(default=None, max_length=8)
    steps: list[FlowStep] | None = Field(default=None, max_length=6)
    quote_text: str | None = Field(default=None, max_length=300)
    quote_attribution: str | None = Field(default=None, max_length=100)
    figure_prompt: str | None = Field(default=None, max_length=300)
    figure_subject_type: ImageSubjectType | None = None
    speaker_notes: str | None = Field(default=None, max_length=2000)
    narrative_role: NarrativePhase | None = None
    section_name: str | None = Field(default=None, max_length=100)
    source_claim_ids: list[str] = Field(default_factory=list[str], max_length=50)


class _LLMSequence(BaseModel):
    """Wrapper around the editorial LLM response's ``slides`` array."""

    model_config = ConfigDict(extra="ignore")

    slides: list[_LLMSlide] = Field(default_factory=list[_LLMSlide], max_length=80)


class _LLMInteractive(BaseModel):
    """Permissive shape of the interactive-content LLM response."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    quiz_questions: list[QuizQuestion] | None = Field(default=None, max_length=5)
    matching_pairs: list[MatchingPair] | None = Field(default=None, max_length=6)
    fill_blanks: list[FillBlankItem] | None = Field(default=None, max_length=5)
    true_false_items: list[TrueFalseItem] | None = Field(default=None, max_length=5)
    category_labels: list[str] | None = Field(default=None, max_length=5)
    category_items: list[CategoryItem] | None = Field(default=None, max_length=12)
    debate_prompt: str | None = Field(default=None, max_length=500)
    debate_options: list[DebateOption] | None = Field(default=None, max_length=3)


# ---------------------------------------------------------------------------
# EditorialPass
# ---------------------------------------------------------------------------


class EditorialPass:
    """Generate a full :class:`DeckSpec` from source material and design spec."""

    def __init__(
        self,
        llm: LLMClient | None = None,
        gemini: GeminiClient | None = None,
        planner: PlannerPass | None = None,
        classifier: ThesisClassifier | None = None,
    ) -> None:
        self._llm = llm
        self._gemini = gemini
        self._planner = planner
        self._classifier = classifier
        # Provenance of the last deck's emphasis fields (executor vs fallback),
        # captured by the post-assembly fallback. Ship ignores it; the GATE A
        # script reads it to prove the executor — not the fallback — authored
        # the table/stat emphasis. Reset on each generate_deck_spec call.
        self.last_emphasis_provenance: EmphasisProvenance | None = None

    def _get_llm(self) -> LLMClient:
        if self._llm is None:
            self._llm = LLMClient()
        return self._llm

    def _get_gemini(self) -> GeminiClient:
        if self._gemini is None:
            self._gemini = GeminiClient()
        return self._gemini

    def _get_planner(self) -> PlannerPass:
        # The planner runs on Gemini 3.1 Pro; reuse editorial's configured Gemini
        # client so planner calls share the same (Vertex) routing and cost
        # accounting as the classifier and critic instead of building a second one.
        # Editorial's own executor keeps its separate Sonnet LLMClient (_get_llm).
        if self._planner is None:
            self._planner = PlannerPass(gemini=self._get_gemini())
        return self._planner

    def _get_classifier(self) -> ThesisClassifier:
        # Reuse the configured Gemini client so the classifier inherits the
        # same (Vertex) routing as the rest of the pipeline rather than
        # default-building a fresh client.
        if self._classifier is None:
            self._classifier = ThesisClassifier(gemini=self._get_gemini())
        return self._classifier

    async def generate_deck_spec(
        self,
        interview: PresentationInterviewAnswers,
        design: DesignDirectionSpec,
        evidence_matrix: EvidenceMatrix,
        claims: list[SourceClaimCreate],
        chunks: list[SourceChunkCreate],
        source_metadata: list[SourceMetadataExtracted],
        outline: ArticleOutline | None = None,
        project_id: str = DEFAULT_PROJECT_ID,
    ) -> DeckSpec:
        """Run the full editorial pipeline end-to-end.

        The deck is FILLED from a source-grounded :class:`DeckPlan`, not
        invented: the planner reads the source chunks and commits to an
        argument plus a figure roster; editorial fills each section; the
        deck-vs-plan gate rejects a deck that drops a section, omits a planned
        figure, or invents a person. ``evidence_matrix`` and ``outline`` are
        consumed by neither the planner nor editorial in Phase 2.
        """

        del evidence_matrix, outline

        plan = await self._plan_and_validate(interview, claims, chunks, source_metadata)

        analysis = self._analyze_content(claims)
        # The figure roster now comes from the source-grounded plan, never a
        # keyword scan. Both consumers — the executor's people brief and the
        # interactive-matching selector — read people_mentioned from here.
        analysis = analysis.model_copy(
            update={"people_mentioned": [fig.name for fig in plan.figures]}
        )
        arc = self._determine_narrative_arc(interview, analysis)
        target_count = self._size_deck(interview, plan)

        raw_slides = await self._generate_slide_sequence(
            interview=interview,
            design=design,
            analysis=analysis,
            arc=arc,
            plan=plan,
            target_slide_count=target_count,
            language=interview.language,
        )
        # The emergency-minimal deck is produced ONLY when the executor returned
        # nothing usable (``raw_slides`` empty). Capture that HERE at its origin and
        # thread it to every gate, rather than re-inferring it downstream from slide
        # shape — a real 2-slide deck that happens to match the fallback's shape
        # must still pass through the plan gate, content critic, and interactive pass.
        deck_is_emergency = not raw_slides
        content_slides = self._post_process(raw_slides, interview)
        content_slides = await self._enforce_plan_adherence(
            interview, arc, plan, content_slides, is_emergency=deck_is_emergency
        )
        content_slides = await self._enforce_content_critic(
            interview,
            design,
            plan,
            content_slides,
            claims,
            project_id,
            is_emergency=deck_is_emergency,
        )

        interactive_slides: list[SlideSpec] = []
        if interview.include_interactive and not deck_is_emergency:
            interactive_slides = await self._generate_interactive_slides(
                content_slides=content_slides,
                analysis=analysis,
                language=interview.language,
            )

        merged = self._merge_slides(content_slides, interactive_slides)
        deck = self._assemble_deck(merged, interview, design, project_id, plan)
        # Last-resort guarantee: fill any emphasis field the executor left unmarked
        # (so a DATA_EMPHASIS slide never ships flat) and record where each field
        # came from. Ship discards the provenance; the gate reads it off the instance.
        self.last_emphasis_provenance = apply_emphasis_fallback(deck)
        return deck

    # ------------------------------------------------------------------
    # Plan: produce + validate (with one re-plan), then enforce on the deck
    # ------------------------------------------------------------------

    async def _plan_and_validate(
        self,
        interview: PresentationInterviewAnswers,
        claims: list[SourceClaimCreate],
        chunks: list[SourceChunkCreate],
        source_metadata: list[SourceMetadataExtracted],
    ) -> DeckPlan:
        """Produce a source-grounded plan and validate it; re-plan ONCE on reject.

        :class:`PlannerError` / :class:`ThesisClassifierError` propagate
        unchanged to the orchestrator — a planner or classifier that cannot do
        its job is a hard stop, not a silent degrade. A plan that PARSES but
        FAILS validation is recoverable by re-planning with the findings fed
        back, but only once; a second failure raises
        :class:`EditorialPlanRejectedError`.
        """

        planner = self._get_planner()
        classifier = self._get_classifier()
        plan = await planner.plan_deck(
            interview=interview, claims=claims, chunks=chunks, source_metadata=source_metadata
        )
        result = await validate_plan_async(
            plan, classifier=classifier, language=interview.language, claims=claims
        )
        if result.passed:
            return plan

        logger.warning(
            "editorial_plan_rejected_replanning",
            extra={"failures": [f.check_id for f in result.failures]},
        )
        plan = await planner.plan_deck(
            interview=interview,
            claims=claims,
            chunks=chunks,
            source_metadata=source_metadata,
            feedback=result.failures,
        )
        result = await validate_plan_async(
            plan, classifier=classifier, language=interview.language, claims=claims
        )
        if not result.passed:
            raise EditorialPlanRejectedError(result.failures)
        return plan

    async def _enforce_plan_adherence(
        self,
        interview: PresentationInterviewAnswers,
        arc: NarrativeArc,
        plan: DeckPlan,
        content_slides: list[SlideSpec],
        *,
        is_emergency: bool,
    ) -> list[SlideSpec]:
        """Validate the deck against the plan; repair the failing sections ONCE.

        Skipped for the emergency-minimal deck (``is_emergency``): that path means
        the executor returned nothing usable (an infra failure), not a plan
        mismatch, and validating it would spuriously fail section coverage. The
        flag is set once at the deck's origin in :meth:`generate_deck_spec`, never
        inferred from slide shape.
        """

        if is_emergency:
            return content_slides
        result = validate_deck_against_plan(content_slides, plan)
        if result.passed:
            return content_slides

        logger.warning(
            "editorial_deck_plan_mismatch_repairing",
            extra={"failures": [f.check_id for f in result.failures]},
        )
        content_slides = await self._repair_failing_sections(
            interview, arc, plan, content_slides, result.failures
        )
        result = validate_deck_against_plan(content_slides, plan)
        if not result.passed:
            raise EditorialDeckPlanMismatchError(result.failures)
        return content_slides

    async def _repair_failing_sections(
        self,
        interview: PresentationInterviewAnswers,
        arc: NarrativeArc,
        plan: DeckPlan,
        content_slides: list[SlideSpec],
        failures: list[AuditCheckResult],
    ) -> list[SlideSpec]:
        """Regenerate ONLY the failing sections' slides and splice them in place.

        DECISION 2 (path a): a scoped repair, not a whole-deck re-prompt. The
        replacement slides replace the failing section's slides in place; a
        section that produced none has its slides inserted at the plan-order
        position. Afterwards only the order-preserving post-steps run
        (:func:`_post_process_repaired`) — NOT ``_enforce_density_arc``, which
        reorders across section boundaries and would re-break the coverage the
        repair just fixed.
        """

        failing = failing_section_indices(failures, content_slides, plan)
        if not failing:
            return content_slides
        target = sum(max(1, len(plan.sections[i].planned_slide_types)) for i in failing)
        system = EDITORIAL_SYSTEM.format(
            slide_type_descriptions=_format_slide_type_descriptions(),
            word_limits=_format_word_limits(),
            arc_description=" → ".join(p.value for p in arc.phases),
            emphasis_phase=arc.emphasis_phase.value,
            target_count=target,
            title_style=interview.title_style.value,
            language=interview.language.value,
        )
        user = EDITORIAL_REPAIR_USER.format(
            audience=interview.audience.value,
            language=interview.language.value,
            plan_spine=_format_plan_spine(plan),
            current_deck=_format_current_deck(content_slides),
            failing_sections=_format_failing_sections(plan, failing),
            findings=_format_findings(failures),
        )
        parsed = await self._call_editorial_with_retry(system, user)
        replacements = _materialise_slides(parsed, plan)
        spliced = _splice_sections(content_slides, replacements, failing, plan)
        return _post_process_repaired(spliced)

    async def _enforce_content_critic(
        self,
        interview: PresentationInterviewAnswers,
        design: DesignDirectionSpec,
        plan: DeckPlan,
        content_slides: list[SlideSpec],
        claims: list[SourceClaimCreate],
        project_id: str,
        *,
        is_emergency: bool,
    ) -> list[SlideSpec]:
        """Audit the post-adherence content against the source; route + re-judge once.

        Runs the adversarial content critic (one Gemini 3.1 Pro call) on the content
        slides BEFORE the interactive pass, so corrected content flows into
        interactive generation. Routable FAIL findings (fabrication, unsupported,
        chart/title) are grouped by durable ``slide_id`` and regenerated one slide
        each via :meth:`regenerate_slide_content` (which preserves the id), spliced
        back, then re-judged ONCE.

        The hard stop is per-slide, keyed on what actually changed:

        * a first-pass hard-stop (C-FB / C-US) on a slide whose regen was REJECTED
          stands unconditionally — that slide is unchanged (word limits are
          idempotent and already applied before the first pass, so its visible text
          is identical at re-judge time), so its deterministic, code-confirmed
          grounding verdict still holds and a fresh, stochastic re-judge is not
          entitled to clear it. When NO regen was accepted, the re-judge can only
          re-examine unchanged slides, so it is skipped and the standing findings
          hard-stop directly (the reproduced all-regens-fail case);
        * a first-pass hard-stop on a slide that WAS corrected is cleared only if
          the re-judge SUCCESSFULLY RAN and did not re-flag it. If the re-judge
          could not produce a verdict (``llm_verified`` is False — degraded /
          unparseable), every first-pass hard-stop stands: absence of a verdict
          must never clear a known fabrication.

        A surviving hard-stop raises :class:`EditorialContentCriticError` (a hard
        stop that refunds); every other residual finding is WARN and ships (I5
        degrade-and-ship). When the FIRST critique cannot be established, no defect
        was found to clear, so the deck ships unaudited per I5 (logged).

        Skipped for the emergency-minimal deck (``is_emergency``, an infra fallback
        rather than a content defect) and when there are no claims to ground against.
        """

        if is_emergency or not claims:
            return content_slides

        gemini = self._get_gemini()
        critique = await critique_deck_adversarially(
            content_slides, plan, claims=claims, gemini=gemini, language=interview.language
        )
        if not critique.llm_verified:
            # The first critique could not be established (unparseable after retry).
            # Nothing was FOUND, so there is no known defect to clear — ship per I5.
            logger.warning("editorial_content_critic_first_pass_unverified")
            return content_slides

        result = critique.result
        routable = [f for f in result.failures if _is_routable_critic_finding(f)]
        if not routable:
            return content_slides

        first_hard = [f for f in result.failures if f.check_id in HARD_STOP_CHECK_IDS]
        logger.warning(
            "editorial_content_critic_routing",
            extra={"routable": [f.check_id for f in routable]},
        )
        # The regen path operates on a DeckSpec; assemble a throwaway content-only
        # deck (no interactives yet) to drive the slide_id-preserving regen, then
        # take its corrected slides back. _assemble_deck is a pure constructor.
        deck = self._assemble_deck(content_slides, interview, design, project_id, plan)
        corrected_ids: set[str] = set()
        for slide_id, findings in _group_critic_findings_by_slide_id(routable).items():
            regen = await self.regenerate_slide_content(
                deck, slide_id, instruction=_critic_instruction(findings), claims=claims
            )
            if not regen.passed:
                # The regen produced its OWN FAIL (off-roster person, type change,
                # hollow divider) — shipping it would trade one defect for another,
                # and SlideRegenResult's contract says a FAIL slide must not ship.
                # Keep the original, unchanged slide; its first-pass hard-stop is
                # carried forward below — the verdict still holds because the slide
                # did not change.
                logger.warning(
                    "editorial_content_critic_regen_rejected",
                    extra={
                        "slide_id": slide_id,
                        "regen_failures": [
                            f.check_id for f in regen.findings if f.severity is AuditSeverity.FAIL
                        ],
                    },
                )
                continue
            deck = self.splice_regenerated_slide(deck, regen.slide)
            corrected_ids.add(slide_id)
        corrected = _post_process_repaired(deck.slides)

        # A first-pass hard-stop on a slide we could NOT correct stands no matter
        # what the re-judge later says: the slide is unchanged and was already
        # code-confirmed to assert a fact the source does not support.
        uncorrected_hard = [f for f in first_hard if f.slide_id not in corrected_ids]

        if not corrected_ids:
            # Nothing was spliced, so the re-judge would only re-examine unchanged
            # slides — skip it entirely and hard-stop on the standing findings.
            if uncorrected_hard:
                raise self._content_critic_hard_stop(uncorrected_hard, reason="no_regen_accepted")
            return corrected

        rejudged = await critique_deck_adversarially(
            corrected, plan, claims=claims, gemini=gemini, language=interview.language
        )
        if rejudged.llm_verified:
            rejudge_hard = [
                f for f in rejudged.result.failures if f.check_id in HARD_STOP_CHECK_IDS
            ]
            residual = _dedupe_hard_stops(uncorrected_hard + rejudge_hard)
        else:
            # The re-judge produced no verdict; absence of a verdict must not clear
            # a known fabrication, so every first-pass hard-stop stands.
            residual = first_hard

        if residual:
            raise self._content_critic_hard_stop(residual, reason="residual_after_rejudge")
        return corrected

    @staticmethod
    def _content_critic_hard_stop(
        residual: list[AuditCheckResult], *, reason: str
    ) -> EditorialContentCriticError:
        """Log and build the content-critic hard stop; the caller ``raise``s it."""

        logger.warning(
            "editorial_content_critic_hard_stop",
            extra={"residual": [f.check_id for f in residual], "reason": reason},
        )
        return EditorialContentCriticError(residual)

    # ------------------------------------------------------------------
    # Single-slide regeneration (judge + conversational edit layer)
    # ------------------------------------------------------------------

    async def regenerate_slide_content(
        self,
        deck: DeckSpec,
        slide_id: str,
        *,
        instruction: str | None = None,
        claims: list[SourceClaimCreate],
    ) -> SlideRegenResult:
        """Regenerate ONE content slide of an existing deck, preserving its type.

        The single-slide sibling of :meth:`_repair_failing_sections`: it produces
        a stronger replacement for ``slide_id`` while KEEPING the slide's type,
        stable id, and section membership, grounded in the persisted plan's figure
        roster plus the ``claims`` pool. ``instruction`` is the optional
        edit-layer request, honoured only within the grounding rules (the system
        prompt ranks the roster/source above it).

        Returns a :class:`SlideRegenResult` — the new slide plus per-slide
        findings — so the caller (the quality judge or the edit layer) decides
        whether to accept, retry, or reject. A FAIL finding (a fabricated figure,
        a changed type, or a hollow divider) means do not ship without a retry;
        word-limit overflow is auto-trimmed, as in whole-deck generation.

        Raises :class:`EditorialSlideRegenError` only when no result is possible:
        the deck has no persisted plan (the roster grounding guard would be off),
        ``slide_id`` is absent, or the LLM returned nothing after its retry.

        Image URLs are intentionally NOT resolved here: the fresh slide carries
        image HINTS with null URLs, and the orchestrator re-runs the image stage
        after the splice (a separate downstream step, by design).
        """

        plan = deck.plan
        if plan is None:
            raise EditorialSlideRegenError(
                "cannot regenerate a slide on a deck with no persisted plan: the "
                "figure-roster grounding guard would be disabled"
            )
        located = find_slide_by_id(deck, slide_id)
        if located is None:
            raise EditorialSlideRegenError(f"no slide with id {slide_id!r} in the deck")
        position, target = located
        prev_slide = deck.slides[position - 1] if position > 0 else None
        next_slide = deck.slides[position + 1] if position + 1 < len(deck.slides) else None

        system = EDITORIAL_SLIDE_REGEN_SYSTEM.format(
            slide_type=target.slide_type.value,
            title_style=deck.interview.title_style.value,
            slide_type_descriptions=_format_slide_type_descriptions(),
            word_limits=_format_word_limits(),
            language=deck.interview.language.value,
        )
        user = _format_slide_regen_brief(
            deck, plan, target, prev_slide, next_slide, instruction, claims
        )
        regen_costs: list[float] = []
        parsed = await self._call_editorial_with_retry(system, user, cost_sink=regen_costs)
        if not parsed:
            raise EditorialSlideRegenError(
                f"slide regeneration for id {slide_id!r} returned no usable slide"
            )
        materialised = _materialise_slides([parsed[0]], plan)[0]

        # Inherit identity + deliberate per-slide design from the TARGET: the LLM
        # is not trusted to echo the stable id or section, and _materialise_slides
        # carries forward neither the background/accent overrides nor the source
        # claim ids. Keeping source_claim_ids is the traceability floor — a regen
        # must not silently strip the provenance the slide already carried.
        slide = materialised.model_copy(
            update={
                "slide_id": target.slide_id,
                "slide_index": target.slide_index,
                "section_name": target.section_name,
                "section_thesis": target.section_thesis,
                "background_override": target.background_override,
                "accent_override": target.accent_override,
                "source_claim_ids": list(target.source_claim_ids),
            }
        )
        slide = _enforce_word_limits([slide])[0]
        findings = _collect_slide_regen_findings(slide, target, plan)
        return SlideRegenResult(slide=slide, findings=findings, estimated_cost_usd=sum(regen_costs))

    def splice_regenerated_slide(self, deck: DeckSpec, new_slide: SlideSpec) -> DeckSpec:
        """Splice a regenerated slide back into the deck by its stable id.

        Id-keyed replacement in place (order preserved, reindexed). When the
        regenerated slide is the title hero at position 0, its new title/subtitle
        propagate to ``deck.title``/``deck.subtitle`` — both because the deck title
        is derived from the first slide and because the title-hero background image
        is generated downstream from the deck title/subtitle, not a slide field.

        Image URLs are deliberately NOT touched: the regenerated slide already
        carries null URLs (the editorial pass authored hints, not URLs), so a
        downstream image re-run resolves exactly its slots and leaves every other
        slide's resolved image untouched.
        """

        del self
        spliced = _splice_single_slide(deck.slides, new_slide)
        update: dict[str, Any] = {"slides": spliced}
        if (
            spliced
            and spliced[0].slide_id == new_slide.slide_id
            and new_slide.slide_type is SlideType.TITLE_HERO
        ):
            update["title"] = new_slide.content.title[:300]
            subtitle = new_slide.content.subtitle
            update["subtitle"] = subtitle[:300] if subtitle else None
        return deck.model_copy(update=update)

    # ------------------------------------------------------------------
    # Step 1 - deck sizing
    # ------------------------------------------------------------------

    def _size_deck(
        self,
        interview: PresentationInterviewAnswers,
        plan: DeckPlan,
    ) -> int:
        """Size the deck from the PLAN, not the claim count.

        The plan is the binding spine, so the content base is what the plan
        commits to render: the sum of each section's ``planned_slide_types``,
        floored at one slide per section (a section that listed no types still
        produces at least one slide). This replaces the old claim-count proxy
        so the executor no longer sees two contradictory size signals (a
        claim-derived target AND a plan implying a different count).

        Clamped to the EXISTING ``MIN_CONTENT_SLIDES`` / ``MAX_CONTENT_SLIDES``
        bounds — the same clamp the claim-count heuristic used, not a new cap.
        Section breaks and (optional) interactive slides layer on top of the
        clamped content base, preserving the meaning of the returned total
        (content + breaks + interactive).
        """

        content_supported = sum(
            max(1, len(section.planned_slide_types)) for section in plan.sections
        )
        content_slides = max(MIN_CONTENT_SLIDES, min(MAX_CONTENT_SLIDES, content_supported))
        section_breaks = max(1, content_slides // 5)
        interactive_slides = 0
        if interview.include_interactive:
            interactive_slides = min(6, max(2, content_slides // 4))
        return content_slides + section_breaks + interactive_slides

    # ------------------------------------------------------------------
    # Step 2 - content analysis
    # ------------------------------------------------------------------

    @staticmethod
    def _analyze_content(claims: list[SourceClaimCreate]) -> ContentAnalysis:
        """Group claims by type, detect entities, rank by strength."""

        grouped: dict[ClaimType, list[str]] = defaultdict(list)
        for claim in claims:
            grouped[claim.claim_type].append(claim.claim_text)

        blob = (
            " ".join(c.claim_text for c in claims)
            + " "
            + " ".join(c.quote for c in claims if c.quote)
        )
        blob_lower = blob.lower()

        numbers: list[str] = []
        for pattern in _NUMBER_PATTERNS:
            for match in pattern.finditer(blob):
                token = match.group(0).strip()
                if token and token not in numbers:
                    numbers.append(token)
        numbers = numbers[:100]

        has_comparison = any(marker in blob_lower for marker in _COMPARISON_MARKERS)
        has_process = any(marker in blob_lower for marker in _PROCESS_MARKERS)
        has_timeline = any(marker in blob_lower for marker in _TIMELINE_MARKERS)

        sorted_claims = sorted(
            claims,
            key=lambda c: _CLAIM_STRENGTH_RANK.get(c.strength, 0),
            reverse=True,
        )
        strongest_texts = [
            c.claim_text for c in sorted_claims if c.strength is not ClaimStrength.WEAK
        ][:10]

        return ContentAnalysis(
            total_claims=len(claims),
            statistical_claims=grouped[ClaimType.STATISTICAL_RESULT][:200],
            empirical_findings=grouped[ClaimType.EMPIRICAL_FINDING][:200],
            theoretical_arguments=grouped[ClaimType.THEORETICAL_ARGUMENT][:200],
            definitions=grouped[ClaimType.DEFINITION][:100],
            comparisons=grouped[ClaimType.COMPARISON][:100],
            # Roster comes from the source-grounded DeckPlan downstream
            # (generate_deck_spec), never a keyword scan — Phase 2 deleted
            # _PERSON_KEYWORDS. Both consumers (the executor's people brief and
            # the interactive-matching selector) read it from the plan.
            people_mentioned=[],
            key_numbers=numbers,
            has_timeline_content=has_timeline,
            has_comparison_content=has_comparison or len(grouped[ClaimType.COMPARISON]) > 0,
            has_process_content=has_process or len(grouped[ClaimType.METHODOLOGICAL]) > 0,
            strongest_claims=strongest_texts,
        )

    # ------------------------------------------------------------------
    # Step 3 - narrative arc
    # ------------------------------------------------------------------

    @staticmethod
    def _determine_narrative_arc(
        interview: PresentationInterviewAnswers,
        analysis: ContentAnalysis,
    ) -> NarrativeArc:
        """Pick a narrative arc based on the user's emphasis choice."""

        del analysis
        phases = [
            NarrativePhase.HOOK,
            NarrativePhase.CONTEXT,
            NarrativePhase.CORE,
            NarrativePhase.EVIDENCE,
            NarrativePhase.IMPLICATIONS,
            NarrativePhase.CLOSE,
        ]
        emphasis_map: dict[NarrativeEmphasis, NarrativePhase] = {
            NarrativeEmphasis.PROBLEM_FRAMING: NarrativePhase.CONTEXT,
            NarrativeEmphasis.TECHNICAL_MECHANISM: NarrativePhase.CORE,
            NarrativeEmphasis.METHODOLOGY: NarrativePhase.CORE,
            NarrativeEmphasis.RESULTS_NUMBERS: NarrativePhase.EVIDENCE,
            NarrativeEmphasis.ROADMAP_SCALABILITY: NarrativePhase.IMPLICATIONS,
            NarrativeEmphasis.BALANCED: NarrativePhase.CORE,
        }
        emphasis_phase = emphasis_map.get(interview.narrative_emphasis, NarrativePhase.CORE)
        return NarrativeArc(phases=phases, emphasis_phase=emphasis_phase)

    # ------------------------------------------------------------------
    # Step 4 - LLM slide sequence
    # ------------------------------------------------------------------

    async def _generate_slide_sequence(
        self,
        interview: PresentationInterviewAnswers,
        design: DesignDirectionSpec,
        analysis: ContentAnalysis,
        arc: NarrativeArc,
        plan: DeckPlan,
        target_slide_count: int,
        language: Language,
    ) -> list[SlideSpec]:
        """One LLM call (Sonnet) returning the editorial slide sequence.

        The plan is rendered into the user prompt as the binding spine; the
        executor fills each section and tags every slide with its
        ``section_index``, which :func:`_materialise_slides` resolves to the
        plan's canonical section name.
        """

        del design  # palette is for the renderer, not the editor
        system = EDITORIAL_SYSTEM.format(
            slide_type_descriptions=_format_slide_type_descriptions(),
            word_limits=_format_word_limits(),
            arc_description=" → ".join(p.value for p in arc.phases),
            emphasis_phase=arc.emphasis_phase.value,
            target_count=target_slide_count,
            title_style=interview.title_style.value,
            language=language.value,
        )
        user = EDITORIAL_USER.format(
            audience=interview.audience.value,
            language=language.value,
            headline_numbers=_format_headline_numbers(interview.headline_numbers),
            closing_ask=interview.closing_ask or "(none)",
            plan_spine=_format_plan_spine(plan),
            content_summary=self._build_content_summary(analysis, interview, arc),
        )
        parsed = await self._call_editorial_with_retry(system, user)
        return _materialise_slides(parsed, plan)

    async def _call_editorial_with_retry(
        self,
        system: str,
        user: str,
        *,
        cost_sink: list[float] | None = None,
    ) -> list[_LLMSlide]:
        """One Sonnet call; on failure, retry ONCE with a failure-specific nudge.

        The retry is INFORMED, not blind — the two failure modes need different
        corrections. Malformed JSON takes :data:`EDITORIAL_RETRY_SUFFIX` ("return
        ONLY a JSON object"); valid JSON that FAILS slide-schema validation
        (after coercion) takes the EXACT field errors translated into
        instructions (see :func:`packages.presentation._schema_feedback.format_schema_feedback`).
        At temperature 0 a blind resample re-rolls the whole deck — which is how
        a single stray field on one slide could drop a different section's
        planned people on the prior gate run; telling the model the one field to
        fix anchors it to its previous output.

        Both calls use EDITORIAL_LLM_TIMEOUT_SECONDS (longer than the shared
        default) because a 16k-token plan-bound generation legitimately runs for
        minutes. The section-repair path (_repair_failing_sections) routes
        through here too, so it inherits both the timeout and the informed retry.
        Returns ``[]`` after two failures (the emergency-deck path); we do NOT
        add a second blind retry — at temperature 0 more rolls do not help.

        ``cost_sink`` is an opt-in spend probe: when a list is passed, each
        underlying ``complete`` call's ``estimated_cost_usd`` is appended, so the
        single-slide regen path can record the EXACT editorial cost it already
        computed for the brain session's billing/analytics. Default ``None``
        leaves the first-gen and section-repair callers untouched.
        """

        first = await self._get_llm().complete(
            system=system,
            user=user,
            model=SONNET_MODEL,
            max_tokens=16_000,
            timeout=EDITORIAL_LLM_TIMEOUT_SECONDS,
        )
        if cost_sink is not None:
            cost_sink.append(first.estimated_cost_usd)
        parsed = _parse_editorial_response(first.content)
        if parsed.slides is not None:
            return parsed.slides
        retry_user = user + (parsed.schema_feedback or EDITORIAL_RETRY_SUFFIX)
        retry = await self._get_llm().complete(
            system=system,
            user=retry_user,
            model=SONNET_MODEL,
            max_tokens=16_000,
            timeout=EDITORIAL_LLM_TIMEOUT_SECONDS,
        )
        if cost_sink is not None:
            cost_sink.append(retry.estimated_cost_usd)
        parsed = _parse_editorial_response(retry.content)
        return parsed.slides if parsed.slides is not None else []

    # ------------------------------------------------------------------
    # Content summary builder
    # ------------------------------------------------------------------

    @staticmethod
    def _build_content_summary(
        analysis: ContentAnalysis,
        interview: PresentationInterviewAnswers,
        arc: NarrativeArc,
    ) -> str:
        """Curate a focused content brief for the editorial LLM call."""

        del arc
        lines: list[str] = []
        if interview.headline_numbers:
            lines.append("HEADLINE NUMBERS (each MUST become a hero slide):")
            lines.extend(f"  - {n}" for n in interview.headline_numbers)
            lines.append("")
        if interview.closing_ask:
            lines.append(f"CLOSING ASK (final slide focus): {interview.closing_ask}")
            lines.append("")
        if analysis.strongest_claims:
            lines.append("STRONGEST CLAIMS (candidates for emphasis):")
            lines.extend(f"  - {c}" for c in analysis.strongest_claims[:10])
            lines.append("")
        if analysis.statistical_claims:
            lines.append("STATISTICS (route to DATA_EMPHASIS or CHART_DATA):")
            lines.extend(f"  - {c}" for c in analysis.statistical_claims[:8])
            lines.append("")
        # People are carried authoritatively by the DECK PLAN's figure roster
        # in the user prompt (see _format_plan_spine), so the content summary
        # no longer lists them — double-listing would just add noise.
        if analysis.key_numbers:
            lines.append("KEY NUMBERS DETECTED: " + ", ".join(analysis.key_numbers[:15]))
            lines.append("")
        if analysis.comparisons:
            lines.append("COMPARISONS (use COMPARISON or CHART_DATA):")
            lines.extend(f"  - {c}" for c in analysis.comparisons[:5])
            lines.append("")
        if analysis.definitions:
            lines.append("DEFINITIONS (route to CONCEPT_DEFINITION):")
            lines.extend(f"  - {c}" for c in analysis.definitions[:5])
            lines.append("")
        remaining = analysis.empirical_findings + analysis.theoretical_arguments
        if remaining:
            lines.append("OTHER CLAIMS:")
            lines.extend(f"  - {c}" for c in remaining[:10])
        return "\n".join(lines) if lines else "(no content material available)"

    # ------------------------------------------------------------------
    # Step 5 - post-process
    # ------------------------------------------------------------------

    @staticmethod
    def _post_process(
        slides: list[SlideSpec],
        interview: PresentationInterviewAnswers,
    ) -> list[SlideSpec]:
        """De-slop the LLM-emitted sequence and enforce content invariants.

        Order matters: hollow dividers are dropped FIRST so a stray bare
        ``slides[0]`` SECTION_BREAK never gets promoted to a title-hero by
        :func:`_ensure_first_is_title`. The breather call is retained for the
        scaffold of plan item 2 (model-authored breathers) but defaults OFF —
        an invariant-I2 violation if enabled with the current stat-echo seed.
        """

        if not slides:
            return _emergency_minimal_deck(interview)
        slides = _drop_hollow_dividers(slides)
        slides = _ensure_first_is_title(slides, interview)
        slides = _enforce_word_limits(slides)
        slides = _enforce_density_arc(slides)
        slides = _insert_breathing_after_data(slides, interview)  # no-op by default
        slides = _reindex(slides)
        return slides

    # ------------------------------------------------------------------
    # Step 6 - interactive slide generation
    # ------------------------------------------------------------------

    async def _generate_interactive_slides(
        self,
        content_slides: list[SlideSpec],
        analysis: ContentAnalysis,
        language: Language,
    ) -> list[SlideSpec]:
        """One Gemini Flash call to fabricate interactive content from slides."""

        requested = _pick_interactive_types(analysis)
        if not requested:
            return []
        slide_summaries = _summarise_slides_for_interactive(content_slides)
        system = INTERACTIVE_SYSTEM
        user = INTERACTIVE_USER.format(
            language=language.value,
            requested=", ".join(t.value for t in requested),
            num_quiz=2,
            slide_summaries=slide_summaries,
        )
        parsed = await self._call_interactive_with_retry(system, user)
        if parsed is None:
            return []
        return _materialise_interactive_slides(parsed, requested, language)

    async def _call_interactive_with_retry(
        self,
        system: str,
        user: str,
    ) -> _LLMInteractive | None:
        """One Gemini Flash call; on failure, retry ONCE with a failure-specific nudge.

        The interactive content models (MatchingPair, QuizQuestion, ...) are
        extra="forbid", so an improvised field on a nested item fails validation
        the same way it does in the slide executor. The retry is INFORMED:
        malformed JSON takes the generic suffix; valid JSON that fails schema
        (after the stray-field strip) takes the EXACT field errors. Returns None
        after two failures (the caller then produces no interactive slides).
        """

        first = await self._get_gemini().complete(
            system=system,
            user=user,
            model=GEMINI_FLASH_3_5_MODEL,
            max_tokens=INTERACTIVE_MAX_TOKENS,
        )
        parsed = _parse_interactive(first.content)
        if parsed.content is not None:
            return parsed.content
        retry_user = user + (parsed.schema_feedback or INTERACTIVE_RETRY_SUFFIX)
        retry = await self._get_gemini().complete(
            system=system,
            user=retry_user,
            model=GEMINI_FLASH_3_5_MODEL,
            max_tokens=INTERACTIVE_MAX_TOKENS,
        )
        return _parse_interactive(retry.content).content

    # ------------------------------------------------------------------
    # Step 7 - merge interactive slides
    # ------------------------------------------------------------------

    @staticmethod
    def _merge_slides(
        content_slides: list[SlideSpec],
        interactive_slides: list[SlideSpec],
    ) -> list[SlideSpec]:
        """Insert each interactive slide just before a section break (R28)."""

        if not interactive_slides:
            return _reindex(content_slides)

        break_positions = [
            i for i, s in enumerate(content_slides) if s.slide_type is SlideType.SECTION_BREAK
        ]
        merged = list(content_slides)
        if not break_positions:
            merged.extend(interactive_slides)
            return _reindex(merged)

        for inserted_offset, (idx, interactive) in enumerate(enumerate(interactive_slides)):
            target_break = break_positions[idx % len(break_positions)]
            insert_at = target_break + inserted_offset
            merged.insert(insert_at, interactive)
        return _reindex(merged)

    # ------------------------------------------------------------------
    # Step 8 - assemble the deck
    # ------------------------------------------------------------------

    @staticmethod
    def _assemble_deck(
        slides: list[SlideSpec],
        interview: PresentationInterviewAnswers,
        design: DesignDirectionSpec,
        project_id: str,
        plan: DeckPlan | None = None,
    ) -> DeckSpec:
        """Wrap the validated slides plus metadata into the final DeckSpec.

        ``plan`` is persisted on the deck so a single slide can later be
        regenerated with the deck-wide authorship context (thesis, figure
        roster, section theses) that is otherwise lost when this method
        returns. ``None`` only on the emergency path, where there is no plan.
        """

        if not slides:
            slides = _emergency_minimal_deck(interview)
            slides = _reindex(slides)
        title_slide = slides[0]
        title = title_slide.content.title
        subtitle = title_slide.content.subtitle
        return DeckSpec(
            project_id=project_id or DEFAULT_PROJECT_ID,
            title=title[:300],
            subtitle=subtitle[:300] if subtitle else None,
            language=interview.language,
            design=design,
            interview=interview,
            plan=plan,
            slides=slides,
            export_formats=[ExportFormat.HTML],
        )


# ---------------------------------------------------------------------------
# Module helpers
# ---------------------------------------------------------------------------


def _format_slide_type_descriptions() -> str:
    return "\n".join(f"- {t.value}: {d}" for t, d in SLIDE_TYPE_DESCRIPTIONS.items())


def _format_word_limits() -> str:
    return "\n".join(f"- {t.value}: {limit} words max" for t, limit in WORD_LIMITS.items())


def _format_headline_numbers(numbers: list[str]) -> str:
    if not numbers:
        return "(none specified)"
    return "\n".join(f"  - {n}" for n in numbers)


class _SequenceParse(NamedTuple):
    """Outcome of parsing one editorial executor response.

    ``slides`` is the typed slide list, or None on any failure. ``schema_feedback``
    is the model-facing correction text — populated ONLY when the response parsed
    as a JSON object but failed slide-schema validation that coercion could not
    salvage, so :meth:`EditorialPass._call_editorial_with_retry` can make the
    retry INFORMED. It stays None on malformed JSON (which takes the generic
    suffix) and on success (including coerced recovery).
    """

    slides: list[_LLMSlide] | None
    schema_feedback: str | None


def _parse_editorial_response(text: str) -> _SequenceParse:
    """Decode an editorial LLM response, carrying retry feedback on schema failure.

    On a validation failure the response is not thrown away outright: a single
    fixable field — an over-long unit/label, a slide that forgot its title, a
    stray field the model improvised — must not collapse the whole deck into the
    emergency fallback. We attempt targeted field-level salvage (see
    :func:`_coerce_llm_object`) and re-validate once. Output still invalid after
    coercion is rejected, but its EXACT remaining field errors are translated
    into ``schema_feedback`` so the caller's retry is informed, not blind. The
    feedback is built from the POST-coercion error (``exc2``) when coercion ran —
    so it names what is STILL wrong, not the field already stripped.
    """

    obj = _try_parse_object(text)
    if obj is None:
        logger.warning("editorial_parse_failed_not_json len=%d head=%s", len(text), text[:300])
        return _SequenceParse(slides=None, schema_feedback=None)
    try:
        return _SequenceParse(slides=_LLMSequence.model_validate(obj).slides, schema_feedback=None)
    except ValidationError as exc:
        coerced = _coerce_llm_object(obj, exc)
        if coerced is None:
            errors = exc.errors(include_input=False)
            logger.warning("editorial_invalid_schema: %s", summarise_errors(errors))
            feedback = format_schema_feedback(errors, header=EDITORIAL_SCHEMA_RETRY_HEADER)
            return _SequenceParse(slides=None, schema_feedback=feedback)
        try:
            wrapper = _LLMSequence.model_validate(coerced)
        except ValidationError as exc2:
            errors2 = exc2.errors(include_input=False)
            logger.warning("editorial_invalid_after_coercion: %s", summarise_errors(errors2))
            feedback = format_schema_feedback(errors2, header=EDITORIAL_SCHEMA_RETRY_HEADER)
            return _SequenceParse(slides=None, schema_feedback=feedback)
        logger.info("editorial_coerced_and_recovered slides=%d", len(wrapper.slides))
        return _SequenceParse(slides=wrapper.slides, schema_feedback=None)


def _coerce_llm_object(obj: dict[str, Any], exc: ValidationError) -> dict[str, Any] | None:
    """Salvage the recurring LLM failure modes that nuke a whole deck.

    The editorial schema is intentionally tighter than the model's natural
    output, so a single field on a single slide can fail validation and drop
    the entire deck to the "insufficient source material" fallback. This reacts
    to exactly three pydantic error classes and leaves everything else to that
    fallback (so genuinely garbage output is not masked):

    * ``string_too_long`` on any field → clamp the offending string to the
      field's declared ``max_length`` (cut at a word boundary). A unit truncated
      to 32 chars is vastly better than a lost deck.
    * a slide ``title`` that is null / empty / missing → synthesise a terse
      title from that slide's own text, or drop that one slide.
    * ``extra_forbidden`` on a nested item → delete the stray key. The model
      improvised a field a strict domain model (e.g. KeywordItem) does not
      define; that field carries no schema meaning the renderer reads, so
      dropping it is information-preserving AND keeps the rest of the deck (and
      its already-correct people) intact — far better than a blind whole-deck
      retry, which re-rolls every section. ``_LLMSlide`` itself is
      ``extra="ignore"``, so this only ever fires on the nested domain items.

    Each branch touches ONLY the loc Pydantic flagged. Re-validation by the
    caller catches anything stripping left invalid (so coercion never masks a
    genuine defect — a stripped field that exposed a missing required field
    still fails, and routes to the informed retry). Mutates ``obj`` in place and
    returns it for one re-validation, or ``None`` when nothing was coercible
    (the caller then falls back / retries unchanged).
    """

    raw_slides = obj.get("slides")
    if not isinstance(raw_slides, list):
        return None
    slides = cast("list[Any]", raw_slides)

    drop_indices: set[int] = set()
    changed = False
    for error in exc.errors():
        loc = error["loc"]
        etype = error["type"]
        if etype == "string_too_long":
            ctx = error.get("ctx")
            limit = ctx.get("max_length") if isinstance(ctx, dict) else None
            if isinstance(limit, int) and _truncate_field(obj, loc, limit):
                changed = True
        elif etype == "extra_forbidden":
            if _delete_field(obj, loc):
                logger.warning("editorial_stripped_extra_field path=%s", loc_path(loc))
                changed = True
        elif _is_missing_title(loc, etype):
            slide_index = loc[1]
            if not isinstance(slide_index, int) or not 0 <= slide_index < len(slides):
                continue
            raw_slide = slides[slide_index]
            if not isinstance(raw_slide, dict):
                continue
            slide = cast("dict[str, Any]", raw_slide)
            synthesised = _synthesise_title(slide)
            if synthesised is not None:
                slide["title"] = synthesised
            else:
                drop_indices.add(slide_index)
            changed = True

    if drop_indices:
        obj["slides"] = [s for i, s in enumerate(slides) if i not in drop_indices]
    return obj if changed else None


def _is_missing_title(loc: tuple[int | str, ...], etype: str) -> bool:
    """True when ``loc``/``etype`` describe a slide whose title is absent.

    A too-long title is handled by the generic truncation branch, so only the
    "no usable title" error classes route here.
    """

    return (
        len(loc) == 3
        and loc[0] == "slides"
        and loc[2] == "title"
        and etype in ("string_type", "string_too_short", "missing")
    )


def _truncate_field(obj: dict[str, Any], loc: tuple[int | str, ...], limit: int) -> bool:
    """Walk ``loc`` into ``obj`` and clamp the terminal string to ``limit``.

    Returns ``True`` when a string was actually shortened. Any structural
    mismatch along the path (wrong container type, out-of-range index, terminal
    value not an over-long string) is treated as not-coercible and returns
    ``False`` — coercion only ever touches what the schema itself rejected.
    """

    if not loc:
        return False
    node: Any = obj
    for step in loc[:-1]:
        node = _index_raw(node, step)
        if node is None:
            return False
    last = loc[-1]
    if isinstance(node, dict) and isinstance(last, str):
        container = cast("dict[str, Any]", node)
        value = container.get(last)
        if isinstance(value, str) and len(value) > limit:
            container[last] = _truncate_at_word(value, limit)
            return True
    elif isinstance(node, list) and isinstance(last, int):
        seq = cast("list[Any]", node)
        if 0 <= last < len(seq):
            value = seq[last]
            if isinstance(value, str) and len(value) > limit:
                seq[last] = _truncate_at_word(value, limit)
                return True
    return False


def _delete_field(obj: dict[str, Any], loc: tuple[int | str, ...]) -> bool:
    """Walk ``loc`` into ``obj`` and delete the terminal dict key.

    The salvage for an ``extra_forbidden`` error: ``loc`` ends in the stray key
    a strict nested model rejected, so we navigate to its parent container and
    remove exactly that key. Returns ``True`` when a key was removed. Mirrors
    :func:`_truncate_field`'s navigation and the same invariant — coercion only
    ever touches what the schema itself rejected, never a sibling field. An
    ``extra_forbidden`` loc always ends in a str key (the field name); any
    structural mismatch along the path returns ``False``.
    """

    if not loc:
        return False
    node: Any = obj
    for step in loc[:-1]:
        node = _index_raw(node, step)
        if node is None:
            return False
    last = loc[-1]
    if isinstance(node, dict) and isinstance(last, str):
        container = cast("dict[str, Any]", node)
        if last in container:
            del container[last]
            return True
    return False


def _index_raw(node: Any, step: int | str) -> Any:
    """Take one navigation step into a raw JSON node.

    Returns the child at ``step`` (a dict key or list index), or ``None`` when
    the step does not fit the node's shape — the caller treats that as
    not-coercible.
    """

    if isinstance(step, str) and isinstance(node, dict):
        return cast("dict[str, Any]", node).get(step)
    if isinstance(step, int) and isinstance(node, list):
        seq = cast("list[Any]", node)
        if 0 <= step < len(seq):
            return seq[step]
    return None


def _truncate_at_word(value: str, limit: int) -> str:
    """Clamp ``value`` to ``limit`` chars, preferring a nearby word boundary."""

    if len(value) <= limit:
        return value
    hard = value[:limit].rstrip()
    space = hard.rfind(" ")
    if space >= limit // 2:
        return hard[:space].rstrip()
    return hard


def _synthesise_title(slide: dict[str, Any]) -> str | None:
    """Derive a terse title from a slide that emitted none.

    Falls through the slide's own visible text (subtitle, body, first bullet,
    first stat label, quote) and returns ``None`` when nothing usable remains —
    the caller then drops that one slide instead of the whole deck.
    """

    candidates: list[Any] = [slide.get("subtitle"), slide.get("body_text")]
    bullets = slide.get("bullets")
    if isinstance(bullets, list) and bullets:
        candidates.append(cast("list[Any]", bullets)[0])
    stats = slide.get("stats")
    if isinstance(stats, list) and stats:
        first_stat = cast("list[Any]", stats)[0]
        if isinstance(first_stat, dict):
            candidates.append(cast("dict[str, Any]", first_stat).get("label"))
    candidates.append(slide.get("quote_text"))
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return _truncate_at_word(candidate.strip(), _TITLE_MAX)
    return None


class _InteractiveParse(NamedTuple):
    """Outcome of parsing one interactive-pass response.

    ``content`` is the typed interactive content, or None on any failure.
    ``schema_feedback`` is the model-facing correction text, populated ONLY when
    the response parsed as a JSON object but failed validation that the
    stray-field strip could not salvage — so the retry is INFORMED, not blind.
    None on malformed JSON and on success (including a strip-recovery).
    """

    content: _LLMInteractive | None
    schema_feedback: str | None


def _parse_interactive(text: str) -> _InteractiveParse:
    """Decode the interactive LLM response, carrying retry feedback on schema failure.

    Same disease as the slide executor: the nested interactive items
    (MatchingPair, QuizQuestion, ...) are extra="forbid", so an improvised field
    nukes the response. We strip the stray key(s) in place and re-validate; if
    still invalid, the EXACT remaining field errors are translated into
    ``schema_feedback`` so the caller's retry is informed. Feedback is built from
    the post-strip error when a strip ran (names what is STILL wrong).
    """

    obj = _try_parse_object(text)
    if obj is None:
        return _InteractiveParse(content=None, schema_feedback=None)
    try:
        return _InteractiveParse(content=_LLMInteractive.model_validate(obj), schema_feedback=None)
    except ValidationError as exc:
        stripped = [
            loc_path(error["loc"])
            for error in exc.errors()
            if error["type"] == "extra_forbidden" and _delete_field(obj, error["loc"])
        ]
        if stripped:
            logger.warning("interactive_stripped_extra_field paths=%s", ", ".join(stripped))
            try:
                content = _LLMInteractive.model_validate(obj)
            except ValidationError as exc2:
                errors2 = exc2.errors(include_input=False)
                logger.warning("interactive_invalid_after_coercion: %s", summarise_errors(errors2))
                feedback = format_schema_feedback(errors2, header=INTERACTIVE_SCHEMA_RETRY_HEADER)
                return _InteractiveParse(content=None, schema_feedback=feedback)
            return _InteractiveParse(content=content, schema_feedback=None)
        errors = exc.errors(include_input=False)
        logger.warning("interactive_invalid_schema: %s", summarise_errors(errors))
        feedback = format_schema_feedback(errors, header=INTERACTIVE_SCHEMA_RETRY_HEADER)
        return _InteractiveParse(content=None, schema_feedback=feedback)


def _try_parse_object(text: str) -> dict[str, Any] | None:
    """Parse a JSON object from an LLM response that may include code fences."""

    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.lower().startswith("json"):
            stripped = stripped[4:].lstrip()
    try:
        loaded: Any = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    if isinstance(loaded, dict):
        result: dict[str, Any] = {str(k): v for k, v in loaded.items()}  # type: ignore[misc]
        return result
    return None


def _normalise_figure(
    prompt: str | None,
    subject_type: ImageSubjectType | None,
) -> tuple[str | None, ImageSubjectType | None]:
    """Clamp a figure slot to its legal shape.

    A figure depicts a contained object or concept, never a real person —
    real people flow through the ``people`` slot and resolve to gated
    Commons portraits. So if the LLM emits a figure with no subject type,
    or mistakenly tags it ``PERSON``/``SCENE``, coerce it to ``OBJECT`` so
    the image engine never routes a figure into person sourcing. With no
    prompt there is no figure: drop a stray subject type too.
    """

    if not prompt:
        return None, None
    if subject_type in (None, ImageSubjectType.PERSON, ImageSubjectType.SCENE):
        return prompt, ImageSubjectType.OBJECT
    return prompt, subject_type


def _clamp_people_to_legal_types(
    slide_type: SlideType,
    people: list[PersonItem] | None,
) -> list[PersonItem] | None:
    """Drop ``content.people`` from slide types whose renderer never paints it.

    Sibling of :func:`_normalise_figure`: a per-field legality clamp applied as
    each slide is materialised. ``content.people`` is rendered only by
    GALLERY_PEOPLE and TEAM_CREDITS (:data:`PEOPLE_RENDERING_SLIDE_TYPES`);
    attached to any other slide type it is dead data the executor mis-emitted —
    the sCO2 leak put a bibliographic citation ("Ahn, Y. et al.") on a
    ``typographic_keywords`` slide. Unlike :func:`_normalise_figure` this LOGS
    when it fires: the strip backstops a KNOWN, actively-tracked executor leak,
    and a silent drop would hide whether the EDITORIAL_SYSTEM placement rule
    actually stopped it at the source.

    Runs inside :func:`_materialise_slides`, which BOTH the main generation path
    and the section-repair path funnel through, so a person re-attached during a
    repair is cleaned by the same clamp.
    """

    if not people or slide_type in PEOPLE_RENDERING_SLIDE_TYPES:
        return people
    logger.warning(
        "editorial_stripped_misplaced_people",
        extra={
            "slide_type": slide_type.value,
            "dropped": [person.name for person in people],
        },
    )
    return None


# ---------------------------------------------------------------------------
# Plan binding + deck-vs-plan repair helpers (Phase 2)
# ---------------------------------------------------------------------------


def _resolve_section_name(raw: _LLMSlide, plan: DeckPlan | None) -> str | None:
    """Resolve a slide's section to the plan's CANONICAL section name.

    A valid ``section_index`` wins over any free-form ``section_name`` the model
    also emitted, so deck-vs-plan membership is a deterministic join. When the
    index is missing or out of range, fall back to the model's ``section_name``
    — the validator then surfaces any real coverage gap rather than masking it.
    """

    if (
        plan is not None
        and raw.section_index is not None
        and 0 <= raw.section_index < len(plan.sections)
    ):
        return plan.sections[raw.section_index].section_name
    return raw.section_name


def _resolve_section_thesis(raw: _LLMSlide, plan: DeckPlan | None) -> str | None:
    """Carry the plan's section THESIS (the section's argument) onto the slide.

    Mirrors :func:`_resolve_section_name`'s section_index join, but pulls the
    section's ``thesis`` rather than its label. The planner already commits to
    this thesis; here it becomes a slide-level signal. ``None`` when the slide
    has no resolvable plan section (the executor's free-form section_name carries
    no thesis of its own).
    """

    if (
        plan is not None
        and raw.section_index is not None
        and 0 <= raw.section_index < len(plan.sections)
    ):
        return plan.sections[raw.section_index].thesis
    return None


def _format_plan_spine(plan: DeckPlan) -> str:
    """Render the DeckPlan as the binding spine for the executor prompt."""

    lines = [
        "DECK PLAN (the binding spine — FILL it, do not re-author):",
        f"DECK THESIS: {plan.thesis}",
        f"AUDIENCE TAKEAWAY: {plan.audience_takeaway}",
        "",
        "SECTIONS (produce slides for each, IN ORDER; tag every slide with its section_index):",
    ]
    for index, section in enumerate(plan.sections):
        figures = ", ".join(section.figure_names) if section.figure_names else "(none)"
        types = (
            ", ".join(t.value for t in section.planned_slide_types)
            if section.planned_slide_types
            else "(your discretion)"
        )
        lines.append(
            f"  [section_index {index}] {section.section_name}  (phase: {section.phase.value})"
        )
        lines.append(f"      thesis: {section.thesis}")
        lines.append(f"      required figures: {figures}")
        lines.append(f"      planned slide types: {types}")
    lines.append("")
    if plan.figures:
        lines.append("FIGURE ROSTER (the ONLY real people you may name; use these exact names):")
        for fig in plan.figures:
            years = f" ({fig.years})" if fig.years else ""
            lines.append(f"  - {fig.name}{years}: {fig.why_in_source}")
    else:
        lines.append(
            "FIGURE ROSTER: (empty — this source names no people. Do NOT add a people "
            "slide and do NOT name anyone.)"
        )
    return "\n".join(lines)


def _format_current_deck(slides: list[SlideSpec]) -> str:
    """Compact, section-tagged summary of the current deck for the repair prompt."""

    lines: list[str] = []
    for slide in slides:
        section = slide.section_name or "(unassigned)"
        people = ", ".join(p.name for p in (slide.content.people or []))
        extra = f" [people: {people}]" if people else ""
        lines.append(f"  - [{section}] {slide.slide_type.value}: {slide.content.title}{extra}")
    return "\n".join(lines) if lines else "(empty)"


def _format_failing_sections(plan: DeckPlan, indices: set[int]) -> str:
    """Render the sections to regenerate, with their theses + required figures."""

    lines: list[str] = []
    for index in sorted(indices):
        section = plan.sections[index]
        figures = ", ".join(section.figure_names) if section.figure_names else "(none)"
        types = (
            ", ".join(t.value for t in section.planned_slide_types)
            if section.planned_slide_types
            else "(your discretion)"
        )
        lines.append(f"  [section_index {index}] {section.section_name}")
        lines.append(f"      thesis: {section.thesis}")
        lines.append(f"      required figures: {figures}")
        lines.append(f"      planned slide types: {types}")
    return "\n".join(lines)


def _format_findings(failures: list[AuditCheckResult]) -> str:
    return "\n".join(f"  - [{f.check_id}] {f.message or ''}" for f in failures)


# ---------------------------------------------------------------------------
# Single-slide regeneration: brief builder + per-slide re-validation
# ---------------------------------------------------------------------------

_REGEN_CLAIM_POOL_LIMIT: Final[int] = 40


def _format_slide_regen_brief(
    deck: DeckSpec,
    plan: DeckPlan,
    target: SlideSpec,
    prev_slide: SlideSpec | None,
    next_slide: SlideSpec | None,
    instruction: str | None,
    claims: list[SourceClaimCreate],
) -> str:
    """Assemble the single-slide regeneration user prompt.

    Carries the three things a slide-in-isolation regen needs that the section
    repair one-liner (:func:`_format_current_deck`) cannot: deck COHESION (thesis,
    cohesion note, palette, roster), the slide's OWN full current content plus its
    section argument, and the immediate NEIGHBOURS for continuity — plus the
    grounding claim pool and the optional edit instruction.
    """

    instruction_text = instruction.strip() if instruction and instruction.strip() else "(none)"
    return EDITORIAL_SLIDE_REGEN_USER.format(
        slide_type=target.slide_type.value,
        audience=deck.interview.audience.value,
        language=deck.interview.language.value,
        cohesion=_format_regen_cohesion(plan, deck.design),
        section=_format_regen_section(target),
        current_slide=_format_regen_current_slide(target),
        neighbors=_format_regen_neighbors(prev_slide, next_slide),
        instruction=instruction_text,
        claim_pool=_format_regen_claim_pool(claims),
    )


def _format_regen_cohesion(plan: DeckPlan, design: DesignDirectionSpec) -> str:
    """Deck-wide voice for a regen: thesis, cohesion note, palette, figure roster."""

    palette = design.palette
    lines = [
        f"DECK THESIS: {plan.thesis}",
        f"AUDIENCE TAKEAWAY: {plan.audience_takeaway}",
        f"VISUAL COHESION NOTE (the one voice every slide shares): {plan.image_cohesion_note}",
        (
            f"PALETTE: background {palette.background}, surface {palette.surface}, "
            f"text {palette.text}, accent {palette.accent}"
        ),
        f"TYPOGRAPHY: headings {design.heading_font}, body {design.body_font}",
    ]
    if plan.figures:
        lines.append("FIGURE ROSTER (the ONLY real people you may name — use these exact names):")
        for fig in plan.figures:
            years = f" ({fig.years})" if fig.years else ""
            lines.append(f"  - {fig.name}{years}: {fig.why_in_source}")
    else:
        lines.append(
            "FIGURE ROSTER: (empty — this source names no people. Do NOT name anyone "
            "and do NOT add a people slide.)"
        )
    return "\n".join(lines)


def _format_regen_section(target: SlideSpec) -> str:
    """The slide's plan section and the section argument it must serve."""

    name = target.section_name or "(unassigned)"
    thesis = target.section_thesis or "(no section thesis recorded)"
    return f"SECTION: {name}\nSECTION ARGUMENT (this slide must serve it): {thesis}"


def _format_regen_current_slide(target: SlideSpec) -> str:
    """The target's current content as JSON, minus resolved image URLs.

    The model sees exactly what it is replacing. Image URLs are stripped: they
    are noise for an editorial rewrite (the fresh slide re-resolves its own images
    downstream) and a stale URL must never read as content to preserve.
    """

    # Exclude resolved image URLs (top-level and nested) declaratively, so the
    # dump stays strongly typed — no Any-typed post-hoc mutation of the dict.
    data = target.content.model_dump(
        exclude_none=True,
        exclude={
            "figure_url": True,
            "background_url": True,
            "people": {"__all__": {"portrait_url"}},
            "timeline_nodes": {"__all__": {"portrait_url"}},
        },
    )
    return json.dumps(data, ensure_ascii=False, indent=2)


def _format_regen_neighbors(prev_slide: SlideSpec | None, next_slide: SlideSpec | None) -> str:
    """Prev/next slide type + title so the regen flows without seeing the whole deck."""

    def line(label: str, slide: SlideSpec | None, edge: str) -> str:
        if slide is None:
            return f"{label}: (none — this is the {edge} slide)"
        return f'{label}: {slide.slide_type.value} — "{slide.content.title}"'

    return "\n".join([line("PREVIOUS", prev_slide, "first"), line("NEXT", next_slide, "last")])


def _format_regen_claim_pool(claims: list[SourceClaimCreate]) -> str:
    """Bounded list of source claim texts to ground the regenerated content."""

    if not claims:
        return (
            "(no source claims available — keep the slide to what the deck already "
            "establishes; invent nothing)"
        )
    lines: list[str] = []
    for claim in claims[:_REGEN_CLAIM_POOL_LIMIT]:
        text = claim.claim_text.strip()
        if claim.quote:
            text += f"  [quote: {claim.quote.strip()}]"
        lines.append(f"  - {text}")
    extra = len(claims) - _REGEN_CLAIM_POOL_LIMIT
    if extra > 0:
        lines.append(f"  - … (+{extra} more claims in the source)")
    return "\n".join(lines)


def _collect_slide_regen_findings(
    slide: SlideSpec, target: SlideSpec, plan: DeckPlan
) -> list[AuditCheckResult]:
    """Per-slide re-validation for a regenerated slide (the safe-in-isolation set).

    Surfaces — never silently fixes — the failures the caller must act on: a type
    change (PR2 is type-preserving; a mismatch is a FAIL the caller retries on,
    not a silent force that could blank the slide), a fabricated/misplaced person
    (D-X1/D-X2 via :func:`validate_slide_against_plan`), and a hollow SECTION_BREAK
    (invariant I2). Word-limit overflow is already auto-trimmed upstream, so it is
    not a finding.
    """

    findings: list[AuditCheckResult] = []
    if slide.slide_type is not target.slide_type:
        findings.append(
            AuditCheckResult(
                check_id="R-T1",
                check_name="regen.type_changed",
                passed=False,
                severity=AuditSeverity.FAIL,
                slide_index=slide.slide_index,
                message=(
                    f"Regenerated slide changed type from {target.slide_type.value} to "
                    f"{slide.slide_type.value}; single-slide regeneration preserves the type."
                ),
            )
        )
    findings.extend(validate_slide_against_plan(slide, plan))
    if slide.slide_type is SlideType.SECTION_BREAK and not _section_break_has_thesis(slide):
        findings.append(
            AuditCheckResult(
                check_id="R-H1",
                check_name="regen.hollow_divider",
                passed=False,
                severity=AuditSeverity.FAIL,
                slide_index=slide.slide_index,
                message=(
                    "Regenerated SECTION_BREAK carries no thesis in subtitle or body "
                    "(invariant I2): a divider that only names the section is hollow."
                ),
            )
        )
    return findings


def _section_index_for(slide: SlideSpec, plan: DeckPlan) -> int | None:
    """Plan-section index for a slide by EXACT canonical-name match, or None.

    Both content slides and repair replacements carry section names resolved
    from ``plan.sections[i].section_name`` (see :func:`_resolve_section_name`),
    so an exact match is correct here; a slide that fell back to a free-form
    label maps to None and is treated as non-failing / unassigned.
    """

    name = slide.section_name
    if not name:
        return None
    for index, section in enumerate(plan.sections):
        if section.section_name == name:
            return index
    return None


def _splice_sections(
    content_slides: list[SlideSpec],
    replacements: list[SlideSpec],
    failing: set[int],
    plan: DeckPlan,
) -> list[SlideSpec]:
    """Replace each failing section's slides with its regenerated slides.

    A failing section that had slides is replaced in place (replacements land
    where its first slide was); a failing section that produced NO slides has
    its replacements inserted before the first later section. Non-failing slides
    are preserved untouched.
    """

    by_section: dict[int, list[SlideSpec]] = {}
    for slide in replacements:
        section = _section_index_for(slide, plan)
        if section is not None and section in failing:
            by_section.setdefault(section, []).append(slide)

    out: list[SlideSpec] = []
    inserted: set[int] = set()
    for slide in content_slides:
        section = _section_index_for(slide, plan)
        if section is not None and section in failing:
            if section not in inserted:
                out.extend(by_section.get(section, []))
                inserted.add(section)
            continue  # drop the old failing-section slide (it was replaced)
        out.append(slide)

    for section in sorted(failing - inserted):
        reps = by_section.get(section, [])
        if not reps:
            continue  # nothing came back for a section the executor still skipped
        position = _insertion_point_for_section(out, section, plan)
        out[position:position] = reps
    return out


def _insertion_point_for_section(out: list[SlideSpec], section: int, plan: DeckPlan) -> int:
    """Index at which to insert a missing section's slides: before the first
    later section, else at the end."""

    for position, slide in enumerate(out):
        other = _section_index_for(slide, plan)
        if other is not None and other > section:
            return position
    return len(out)


def _post_process_repaired(slides: list[SlideSpec]) -> list[SlideSpec]:
    """Order-preserving reprocess after a section splice (DECISION 2).

    Runs only the per-slide / order-preserving steps. Deliberately OMITS
    ``_enforce_density_arc`` (it reorders across section boundaries and would
    re-break the coverage the repair just fixed) and ``_ensure_first_is_title``
    (the title slide is never part of a repair).
    """

    if not slides:
        return slides
    slides = _drop_hollow_dividers(slides)
    slides = _enforce_word_limits(slides)
    slides = _reindex(slides)
    return slides


def _is_routable_critic_finding(finding: AuditCheckResult) -> bool:
    """A critic finding enters single-slide regen only if it pins a slide and FAILs.

    The structural/cosmetic categories are WARN and never in ``ROUTABLE_CHECK_IDS``,
    so they can never satisfy this and can never trigger a regen.
    """

    return (
        finding.check_id in ROUTABLE_CHECK_IDS
        and finding.slide_id is not None
        and finding.severity is AuditSeverity.FAIL
    )


def _group_critic_findings_by_slide_id(
    findings: list[AuditCheckResult],
) -> dict[str, list[AuditCheckResult]]:
    """Group routable findings by durable slide_id — one regen per slide."""

    grouped: dict[str, list[AuditCheckResult]] = defaultdict(list)
    for finding in findings:
        if finding.slide_id is not None:
            grouped[finding.slide_id].append(finding)
    return dict(grouped)


def _dedupe_hard_stops(findings: list[AuditCheckResult]) -> list[AuditCheckResult]:
    """Drop duplicate hard-stop findings, keyed by ``(slide_id, check_id)``.

    The residual set unions the first-pass findings on UNCORRECTED slides with the
    re-judge's findings on the corrected deck; an unchanged slide that the re-judge
    also re-flags would otherwise appear twice.
    """

    seen: set[tuple[str | None, str]] = set()
    out: list[AuditCheckResult] = []
    for finding in findings:
        key = (finding.slide_id, finding.check_id)
        if key in seen:
            continue
        seen.add(key)
        out.append(finding)
    return out


def _critic_instruction(findings: list[AuditCheckResult]) -> str:
    """Build a single-slide regen instruction from one slide's critic findings."""

    defects = "; ".join(f.message for f in findings if f.message) or "a source-grounding defect"
    return (
        f"A content critic flagged this slide: {defects}. Fix every flagged defect. "
        "State only facts grounded in the provided source claims; remove or correct "
        "anything the source does not support."
    )


def _materialise_slides(parsed: list[_LLMSlide], plan: DeckPlan | None = None) -> list[SlideSpec]:
    """Convert parsed LLM slides into validated :class:`SlideSpec` objects.

    When ``plan`` is supplied, each slide's ``section_index`` is resolved to the
    plan's canonical section name (see :func:`_resolve_section_name`) so
    deck-vs-plan membership is a deterministic join rather than a fuzzy match on
    a model-paraphrased section label.
    """

    out: list[SlideSpec] = []
    for raw in parsed:
        left_col: ComparisonColumn | None = None
        right_col: ComparisonColumn | None = None
        if raw.left_column is not None:
            left_col = ComparisonColumn(
                heading=raw.left_column.heading or "—",
                points=list(raw.left_column.points),
            )
        if raw.right_column is not None:
            right_col = ComparisonColumn(
                heading=raw.right_column.heading or "—",
                points=list(raw.right_column.points),
            )
        figure_prompt, figure_subject_type = _normalise_figure(
            raw.figure_prompt, raw.figure_subject_type
        )
        content = SlideContent(
            title=raw.title,
            subtitle=raw.subtitle,
            body_text=raw.body_text,
            bullets=raw.bullets,
            stats=raw.stats,
            people=_clamp_people_to_legal_types(raw.slide_type, raw.people),
            keywords=raw.keywords,
            left_column=left_col,
            right_column=right_col,
            table_headers=raw.table_headers,
            table_rows=raw.table_rows,
            table_preferred_column=raw.table_preferred_column,
            table_hero_row=raw.table_hero_row,
            chart_series=raw.chart_series,
            chart_type=raw.chart_type,
            chart_group_labels=raw.chart_group_labels,
            timeline_nodes=raw.timeline_nodes,
            steps=raw.steps,
            quote_text=raw.quote_text,
            quote_attribution=raw.quote_attribution,
            figure_prompt=figure_prompt,
            figure_subject_type=figure_subject_type,
            speaker_notes=raw.speaker_notes,
        )
        out.append(
            SlideSpec(
                slide_index=raw.slide_index,
                slide_type=raw.slide_type,
                content=content,
                source_claim_ids=raw.source_claim_ids,
                section_name=_resolve_section_name(raw, plan),
                section_thesis=_resolve_section_thesis(raw, plan),
                narrative_role=raw.narrative_role.value if raw.narrative_role else None,
            )
        )
    return out


def _count_words_in_content(content: SlideContent) -> int:
    """Approximate the visible word count of one slide for R17 enforcement."""

    parts: list[str] = []
    if content.title:
        parts.append(content.title)
    if content.subtitle:
        parts.append(content.subtitle)
    if content.body_text:
        parts.append(content.body_text)
    if content.bullets:
        parts.extend(content.bullets)
    if content.caption:
        parts.append(content.caption)
    if content.keywords:
        parts.extend(f"{k.term} {k.explanation}" for k in content.keywords)
    if content.people:
        parts.extend(
            f"{p.name} {p.years or ''} {p.description or ''}".strip() for p in content.people
        )
    if content.stats:
        parts.extend(f"{s.value}{s.unit} {s.label}" for s in content.stats)
    if content.left_column:
        parts.append(content.left_column.heading)
        parts.extend(content.left_column.points)
    if content.right_column:
        parts.append(content.right_column.heading)
        parts.extend(content.right_column.points)
    if content.timeline_nodes:
        parts.extend(f"{n.date} {n.label}" for n in content.timeline_nodes)
    if content.steps:
        parts.extend(f"{s.label} {s.description}" for s in content.steps)
    if content.quote_text:
        parts.append(content.quote_text)
    return sum(len(p.split()) for p in parts if p)


def _enforce_word_limits(slides: list[SlideSpec]) -> list[SlideSpec]:
    """Truncate body text on slides that overflow R17 limits."""

    out: list[SlideSpec] = []
    for slide in slides:
        limit = WORD_LIMITS.get(slide.slide_type, 60)
        count = _count_words_in_content(slide.content)
        if count <= limit:
            out.append(slide)
            continue
        trimmed_content, moved = _trim_to_limit(slide.content, limit, count)
        notes = (slide.content.speaker_notes or "").strip()
        notes_combined = (notes + "\n\n" + moved).strip() if moved else notes
        if len(notes_combined) > 2000:
            notes_combined = notes_combined[:2000]
        content_update = trimmed_content.model_copy(
            update={"speaker_notes": notes_combined or None}
        )
        out.append(slide.model_copy(update={"content": content_update}))
    return out


def _trim_to_limit(
    content: SlideContent,
    limit: int,
    current: int,
) -> tuple[SlideContent, str]:
    """Cut body text and bullets until the slide fits R17. Return moved text."""

    overflow = current - limit
    moved_parts: list[str] = []
    updates: dict[str, Any] = {}

    if content.body_text and overflow > 0:
        words = content.body_text.split()
        if len(words) <= overflow:
            moved_parts.append(content.body_text)
            updates["body_text"] = None
            overflow -= len(words)
        else:
            keep = max(1, len(words) - overflow)
            updates["body_text"] = " ".join(words[:keep])
            moved_parts.append(" ".join(words[keep:]))
            overflow = 0

    if overflow > 0 and content.bullets:
        kept: list[str] = []
        remaining = overflow
        for bullet in content.bullets:
            bw = len(bullet.split())
            if remaining >= bw:
                moved_parts.append(bullet)
                remaining -= bw
            else:
                kept.append(bullet)
        updates["bullets"] = kept or None
        overflow = remaining

    trimmed = content.model_copy(update=updates)
    return trimmed, " ".join(moved_parts).strip()


def _ensure_first_is_title(
    slides: list[SlideSpec],
    interview: PresentationInterviewAnswers,
) -> list[SlideSpec]:
    """Make sure slide 0 is a TITLE_HERO; synthesise one if the LLM didn't."""

    if slides and slides[0].slide_type is SlideType.TITLE_HERO:
        return slides
    title_text = slides[0].content.title if slides else _default_title(interview)
    title_slide = SlideSpec(
        slide_index=0,
        slide_type=SlideType.TITLE_HERO,
        content=SlideContent(title=title_text[:300]),
        narrative_role=NarrativePhase.HOOK.value,
    )
    return [title_slide, *slides]


def _drop_hollow_dividers(slides: list[SlideSpec]) -> list[SlideSpec]:
    """Invariant I2: drop SECTION_BREAK slides that carry no thesis.

    A SECTION_BREAK earns its place only by stating a one-line argument for
    the section — its title is the LABEL (the section name), its ``subtitle``
    (or ``body_text``) is the THESIS. A break that has neither is a bare
    label; per invariant I2 ("a slide that only names a section is NOT
    emitted") it does not survive post-process.

    The prompt is steered to put the thesis in ``subtitle``
    (:data:`SLIDE_TYPE_DESCRIPTIONS`, EDITORIAL_SYSTEM rule 8) so a
    well-behaved model never emits a hollow break; this filter is the hard
    backstop that keeps the invariant true regardless of model adherence.
    """

    return [
        s
        for s in slides
        if s.slide_type is not SlideType.SECTION_BREAK or _section_break_has_thesis(s)
    ]


def _section_break_has_thesis(slide: SlideSpec) -> bool:
    """True when a SECTION_BREAK carries a one-line thesis in subtitle/body."""

    content = slide.content
    subtitle = (content.subtitle or "").strip()
    body = (content.body_text or "").strip()
    return bool(subtitle) or bool(body)


def _insert_breathing_after_data(
    slides: list[SlideSpec],
    interview: PresentationInterviewAnswers,
    *,
    enabled: bool = False,
) -> list[SlideSpec]:
    """R27 scaffold: insert a breather between two cross-type data-heavy slides.

    DEFAULT OFF (invariant I2 + the master prompt: "do not delete the device,
    default it OFF"). The stat-echo seed below — "Key takeaway: {value} {unit}
    — {label}" — only echoes the preceding stat, which invariant I2 explicitly
    bans as filler. The mechanism is retained for the model-authored breathing
    content that lands in BUILD_STATE plan item 2; flip ``enabled=True`` only
    when a thesis-bearing seed replaces the stat echo.

    When enabled: only fires on a *cross-type* data-heavy run (e.g.
    DATA_EMPHASIS → CHART_DATA). The breather is seeded from the preceding
    data slide's highlighted (else first) stat; if that slide exposes no
    usable stat (CHART_DATA / TABLE_COMPACT carry numbers in prose/rows, not
    ``stats``) no breather is injected — absent beats hollow.
    """

    del interview
    if not enabled:
        return slides
    out: list[SlideSpec] = []
    prev_slide: SlideSpec | None = None
    for slide in slides:
        is_data = slide.slide_type in _DATA_HEAVY_TYPES
        is_breath = slide.slide_type in _BREATHING_TYPES
        prev_data = prev_slide is not None and prev_slide.slide_type in _DATA_HEAVY_TYPES
        if prev_data and is_data and not is_breath:
            assert prev_slide is not None  # implied by prev_data
            breather = _build_breathing_slide(prev_slide)
            if breather is not None:
                out.append(breather)
        out.append(slide)
        prev_slide = slide
    return out


def _build_breathing_slide(data_slide: SlideSpec) -> SlideSpec | None:
    """Seed a SUMMARY_TAKEAWAY breather from a real stat, or None if there is none."""

    stat = _pick_breathing_stat(data_slide.content.stats)
    if stat is None:
        return None
    # Space a word unit off the value ("1.58 PUE"), but keep a symbol unit
    # attached ("94.4%", "35°C") — the same value/unit split FIX A renders.
    if stat.unit and stat.unit[:1].isalpha():
        measure = f"{stat.value} {stat.unit}"
    else:
        measure = f"{stat.value}{stat.unit}"
    return SlideSpec(
        slide_index=0,
        slide_type=SlideType.SUMMARY_TAKEAWAY,
        content=SlideContent(title="Key takeaway", bullets=[f"{measure} — {stat.label}"]),
        narrative_role=NarrativePhase.EVIDENCE.value,
    )


def _pick_breathing_stat(stats: list[StatItem] | None) -> StatItem | None:
    """The highlighted stat if any, else the first; None when there are none."""

    if not stats:
        return None
    for stat in stats:
        if stat.highlight:
            return stat
    return stats[0]


def _enforce_density_arc(slides: list[SlideSpec]) -> list[SlideSpec]:
    """R26: keep dense slide types out of the first 3 positions.

    If a dense slide (TABLE_COMPACT / COMPARISON / TIMELINE) lands in
    positions 1 or 2 (slot 0 is always TITLE_HERO), it is swapped with
    the first eligible mid-deck slide whose type belongs to the sparse
    opening set. When no swap candidate exists the order stays as-is
    rather than dropping the dense slide outright.
    """

    if len(slides) < 4:
        return slides
    out = list(slides)
    opening_slots = (1, 2)
    for slot in opening_slots:
        if out[slot].slide_type not in _DENSE_TYPES:
            continue
        swap_target: int | None = None
        for j in range(3, len(out)):
            if (
                out[j].slide_type in _SPARSE_OPENING_TYPES
                and out[j].slide_type is not SlideType.TITLE_HERO
            ):
                swap_target = j
                break
        if swap_target is None:
            continue
        out[slot], out[swap_target] = out[swap_target], out[slot]
    return out


def _splice_single_slide(slides: list[SlideSpec], new_slide: SlideSpec) -> list[SlideSpec]:
    """Replace the slide whose stable id matches ``new_slide``, then reindex.

    Id-keyed (distinct from the section-keyed :func:`_splice_sections`): order is
    preserved, every other slide is untouched, and :func:`_reindex` rewrites the
    positional ``slide_index`` afterwards. Keeps the order-preserving discipline
    of :func:`_post_process_repaired` — deliberately no ``_enforce_density_arc``,
    whose full-deck reorder would move the slide out of place. If no id matches
    the slides are returned reindexed but unchanged; the caller locates the slide
    first, so a miss is an upstream programming error, never a silent drop here.
    """

    out = [new_slide if slide.slide_id == new_slide.slide_id else slide for slide in slides]
    return _reindex(out)


def _reindex(slides: list[SlideSpec]) -> list[SlideSpec]:
    return [slide.model_copy(update={"slide_index": i}) for i, slide in enumerate(slides)]


def _default_title(interview: PresentationInterviewAnswers) -> str:
    audience_label = {
        AudienceType.SCHOOL: "School audience",
        AudienceType.UNDERGRADUATE: "Undergraduate audience",
        AudienceType.GRADUATE: "Graduate audience",
        AudienceType.ACADEMIC_CONFERENCE: "Conference audience",
        AudienceType.MIXED_ACADEMIC_INDUSTRY: "Mixed audience",
        AudienceType.PROFESSIONAL: "Professional audience",
        AudienceType.GENERAL_PUBLIC: "General audience",
    }.get(interview.audience, "Audience")
    return f"Presentation for {audience_label}"


def _emergency_minimal_deck(interview: PresentationInterviewAnswers) -> list[SlideSpec]:
    """Fallback when the LLM returned nothing usable. Guarantees a valid DeckSpec."""

    return [
        SlideSpec(
            slide_index=0,
            slide_type=SlideType.TITLE_HERO,
            content=SlideContent(title=_default_title(interview)),
            narrative_role=NarrativePhase.HOOK.value,
        ),
        SlideSpec(
            slide_index=1,
            slide_type=SlideType.SUMMARY_TAKEAWAY,
            content=SlideContent(
                title=_EMERGENCY_TAKEAWAY_TITLE,
                bullets=["Add more source material to generate a full deck."],
            ),
            narrative_role=NarrativePhase.CLOSE.value,
        ),
    ]


def _pick_interactive_types(analysis: ContentAnalysis) -> list[SlideType]:
    """Decide which interactive slide types to generate based on content."""

    picked: list[SlideType] = [SlideType.INTERACTIVE_QUIZ_MCQ]
    if len(analysis.people_mentioned) >= 3:
        picked.append(SlideType.INTERACTIVE_MATCHING)
    if len(analysis.statistical_claims) >= 3:
        picked.append(SlideType.INTERACTIVE_FILL_BLANK)
    if analysis.has_comparison_content:
        picked.append(SlideType.INTERACTIVE_DEBATE)
    if analysis.total_claims >= 12:
        picked.append(SlideType.INTERACTIVE_TRUE_FALSE)
    return picked[:6]


def _summarise_slides_for_interactive(slides: list[SlideSpec]) -> str:
    """Compact slide summary fed to the interactive LLM call."""

    lines: list[str] = []
    for slide in slides[:20]:
        body = slide.content.body_text or ""
        bullets = " | ".join(slide.content.bullets or [])
        people = " ".join(p.name for p in (slide.content.people or []))
        stats = " ".join(f"{s.value}{s.unit} {s.label}" for s in (slide.content.stats or []))
        meat = " ".join(part for part in (body, bullets, people, stats) if part)
        lines.append(f"- {slide.content.title}: {meat}")
    return "\n".join(lines) if lines else "(no slides)"


def _materialise_interactive_slides(
    parsed: _LLMInteractive,
    requested: list[SlideType],
    language: Language,
) -> list[SlideSpec]:
    """Convert parsed interactive payload into SlideSpec entries (per type)."""

    del language
    out: list[SlideSpec] = []
    for slide_type in requested:
        slide = _build_interactive_slide(slide_type, parsed)
        if slide is not None:
            out.append(slide)
    return out


def _build_interactive_slide(
    slide_type: SlideType,
    parsed: _LLMInteractive,
) -> SlideSpec | None:
    """Pick the right interactive payload and wrap it as a SlideSpec."""

    if slide_type is SlideType.INTERACTIVE_QUIZ_MCQ and parsed.quiz_questions:
        return _wrap_interactive(slide_type, "Quiz", quiz_questions=parsed.quiz_questions[:5])
    if slide_type is SlideType.INTERACTIVE_MATCHING and parsed.matching_pairs:
        return _wrap_interactive(slide_type, "Matching", matching_pairs=parsed.matching_pairs[:6])
    if slide_type is SlideType.INTERACTIVE_FILL_BLANK and parsed.fill_blanks:
        return _wrap_interactive(slide_type, "Fill the blanks", fill_blanks=parsed.fill_blanks[:5])
    if slide_type is SlideType.INTERACTIVE_TRUE_FALSE and parsed.true_false_items:
        return _wrap_interactive(
            slide_type, "True or false", true_false_items=parsed.true_false_items[:5]
        )
    if (
        slide_type is SlideType.INTERACTIVE_CATEGORIZE
        and parsed.category_labels
        and parsed.category_items
    ):
        return _wrap_interactive(
            slide_type,
            "Categorise",
            category_labels=parsed.category_labels[:5],
            category_items=parsed.category_items[:12],
        )
    if (
        slide_type is SlideType.INTERACTIVE_DEBATE
        and parsed.debate_prompt
        and parsed.debate_options
    ):
        return _wrap_interactive(
            slide_type,
            "Debate",
            debate_prompt=parsed.debate_prompt,
            debate_options=parsed.debate_options[:3],
        )
    return None


def _wrap_interactive(slide_type: SlideType, title: str, **fields: Any) -> SlideSpec:
    """Build a SlideSpec for an interactive slide with the supplied fields."""

    content = SlideContent(title=title, **fields)
    return SlideSpec(
        slide_index=0,
        slide_type=slide_type,
        content=content,
        narrative_role=NarrativePhase.EVIDENCE.value,
    )


# Re-export the structured primitives the editorial pass now materialises from
# the LLM response (tables and chart series), so tests can construct them
# without reaching into the models module directly.
__all__ = [
    "SLIDE_TYPE_DESCRIPTIONS",
    "WORD_LIMITS",
    "ChartSeriesPoint",
    "EditorialDeckPlanMismatchError",
    "EditorialError",
    "EditorialPass",
    "EditorialPlanRejectedError",
    "TableRow",
]
