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
from typing import Any, Final, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from packages.core.enums import (
    PEOPLE_RENDERING_SLIDE_TYPES,
    AudienceType,
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
from packages.core.gemini import GEMINI_FLASH_MODEL, GeminiClient
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
    SlideSpec,
    StatItem,
    TableRow,
    TimelineNode,
    TrueFalseItem,
)
from packages.core.models.source import (
    SourceChunkCreate,
    SourceClaimCreate,
    SourceMetadataExtracted,
)
from packages.core.prompts import (
    EDITORIAL_REPAIR_USER,
    EDITORIAL_RETRY_SUFFIX,
    EDITORIAL_SYSTEM,
    EDITORIAL_USER,
    INTERACTIVE_RETRY_SUFFIX,
    INTERACTIVE_SYSTEM,
    INTERACTIVE_USER,
)
from packages.presentation.plan_validator import (
    failing_section_indices,
    validate_deck_against_plan,
    validate_plan_async,
)
from packages.presentation.planner import PlannerPass
from packages.presentation.thesis_classifier import ThesisClassifier

logger = logging.getLogger(__name__)


SONNET_MODEL: Final[str] = "claude-sonnet-4-6"
DEFAULT_PROJECT_ID: Final[str] = "presentation"

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

# Title carried by the SUMMARY_TAKEAWAY slide in the emergency-minimal deck.
# Used both to build that deck and to detect it: the deck-vs-plan gate is
# skipped for the emergency deck (the executor returned nothing usable — an
# infrastructure failure, not a plan mismatch).
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

    def _get_llm(self) -> LLMClient:
        if self._llm is None:
            self._llm = LLMClient()
        return self._llm

    def _get_gemini(self) -> GeminiClient:
        if self._gemini is None:
            self._gemini = GeminiClient()
        return self._gemini

    def _get_planner(self) -> PlannerPass:
        # Reuse the configured Sonnet client so planner calls share editorial's
        # client (and its cost accounting) instead of building a second one.
        if self._planner is None:
            self._planner = PlannerPass(llm=self._get_llm())
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
        content_slides = self._post_process(raw_slides, interview)
        content_slides = await self._enforce_plan_adherence(interview, arc, plan, content_slides)

        interactive_slides: list[SlideSpec] = []
        if interview.include_interactive:
            interactive_slides = await self._generate_interactive_slides(
                content_slides=content_slides,
                analysis=analysis,
                language=interview.language,
            )

        merged = self._merge_slides(content_slides, interactive_slides)
        return self._assemble_deck(merged, interview, design, project_id)

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
    ) -> list[SlideSpec]:
        """Validate the deck against the plan; repair the failing sections ONCE.

        Skipped for the emergency-minimal deck: that path means the executor
        returned nothing usable (an infra failure), not a plan mismatch, and
        validating it would spuriously fail section coverage.
        """

        if _is_emergency_deck(content_slides):
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
    ) -> list[_LLMSlide]:
        """One Sonnet call; on bad JSON, retry once with a stricter suffix.

        Both the initial call and the retry use EDITORIAL_LLM_TIMEOUT_SECONDS
        (longer than the shared default) because a 16k-token plan-bound
        generation legitimately runs for minutes. The section-repair path
        (_repair_failing_sections) routes through here too, so it inherits the
        same timeout.
        """

        first = await self._get_llm().complete(
            system=system,
            user=user,
            model=SONNET_MODEL,
            max_tokens=16_000,
            timeout=EDITORIAL_LLM_TIMEOUT_SECONDS,
        )
        parsed = _parse_sequence(first.content)
        if parsed is not None:
            return parsed
        retry = await self._get_llm().complete(
            system=system,
            user=user + EDITORIAL_RETRY_SUFFIX,
            model=SONNET_MODEL,
            max_tokens=16_000,
            timeout=EDITORIAL_LLM_TIMEOUT_SECONDS,
        )
        parsed = _parse_sequence(retry.content)
        return parsed if parsed is not None else []

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
        """One Gemini Flash call; on bad JSON, retry once."""

        first = await self._get_gemini().complete(
            system=system, user=user, model=GEMINI_FLASH_MODEL, max_tokens=3_000
        )
        parsed = _parse_interactive(first.content)
        if parsed is not None:
            return parsed
        retry = await self._get_gemini().complete(
            system=system,
            user=user + INTERACTIVE_RETRY_SUFFIX,
            model=GEMINI_FLASH_MODEL,
            max_tokens=3_000,
        )
        return _parse_interactive(retry.content)

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
    ) -> DeckSpec:
        """Wrap the validated slides plus metadata into the final DeckSpec."""

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


def _parse_sequence(text: str) -> list[_LLMSlide] | None:
    """Decode an editorial LLM response into typed slide objects.

    On a validation failure the response is not thrown away outright: a single
    fixable field — an over-long unit/label, a slide that forgot its title —
    must not collapse the whole deck into the emergency fallback. We attempt
    targeted field-level salvage (see :func:`_coerce_llm_object`) and
    re-validate once; only output that is still invalid after coercion (i.e.
    genuinely unusable) is rejected.
    """

    obj = _try_parse_object(text)
    if obj is None:
        logger.warning("editorial_parse_failed_not_json len=%d head=%s", len(text), text[:300])
        return None
    try:
        wrapper = _LLMSequence.model_validate(obj)
    except ValidationError as exc:
        coerced = _coerce_llm_object(obj, exc)
        if coerced is None:
            logger.warning("editorial_invalid_schema: %s", str(exc)[:3000])
            return None
        try:
            wrapper = _LLMSequence.model_validate(coerced)
        except ValidationError as exc2:
            logger.warning("editorial_invalid_after_coercion: %s", str(exc2)[:3000])
            return None
        logger.info("editorial_coerced_and_recovered slides=%d", len(wrapper.slides))
    return wrapper.slides


def _coerce_llm_object(obj: dict[str, Any], exc: ValidationError) -> dict[str, Any] | None:
    """Salvage the two recurring LLM failure modes that nuke a whole deck.

    The editorial schema is intentionally tighter than the model's natural
    output, so a single field on a single slide can fail validation and drop
    the entire deck to the "insufficient source material" fallback. This reacts
    to exactly two pydantic error classes and leaves everything else to that
    fallback (so genuinely garbage output is not masked):

    * ``string_too_long`` on any field → clamp the offending string to the
      field's declared ``max_length`` (cut at a word boundary). A unit truncated
      to 32 chars is vastly better than a lost deck.
    * a slide ``title`` that is null / empty / missing → synthesise a terse
      title from that slide's own text, or drop that one slide.

    Mutates ``obj`` in place and returns it for one re-validation, or ``None``
    when nothing was coercible (the caller then falls back unchanged).
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


def _parse_interactive(text: str) -> _LLMInteractive | None:
    """Decode the interactive LLM response into typed interactive content."""

    obj = _try_parse_object(text)
    if obj is None:
        return None
    try:
        return _LLMInteractive.model_validate(obj)
    except ValidationError as exc:
        logger.warning("interactive_invalid_schema", extra={"error": str(exc)[:200]})
        return None


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


def _is_emergency_deck(slides: list[SlideSpec]) -> bool:
    """True when post-process produced the 2-slide emergency fallback.

    The emergency deck means the executor returned nothing usable (an infra
    failure), not a plan mismatch — so the deck-vs-plan gate is skipped for it.
    """

    return any(s.content.title == _EMERGENCY_TAKEAWAY_TITLE for s in slides)


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
