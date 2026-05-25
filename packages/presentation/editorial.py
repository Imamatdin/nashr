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
5. Post-process — enforce R01 (no consecutive layout repeats), R03
   (section breaks every 4-5 slides), R17 (word-count limits), R27
   (breathing after data-heavy), R26 (density arc), first-slide is
   TITLE_HERO, and re-index.
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
from typing import Any, Final

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from packages.core.enums import (
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
    CategoryItem,
    ChartSeriesPoint,
    ComparisonColumn,
    ContentAnalysis,
    DebateOption,
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
    EDITORIAL_RETRY_SUFFIX,
    EDITORIAL_SYSTEM,
    EDITORIAL_USER,
    INTERACTIVE_RETRY_SUFFIX,
    INTERACTIVE_SYSTEM,
    INTERACTIVE_USER,
)

logger = logging.getLogger(__name__)


SONNET_MODEL: Final[str] = "claude-sonnet-4-6"
DEFAULT_PROJECT_ID: Final[str] = "presentation"

# Deck sizing is driven by content volume, not talk duration. Floor 6:
# anything thinner is not a deck. Ceiling 15: anything fatter is a
# document, not a presentation (a human making a real 5-minute pitch deck
# tops out around 15 content slides).
MIN_CONTENT_SLIDES: Final[int] = 6
MAX_CONTENT_SLIDES: Final[int] = 15

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
    SlideType.SECTION_BREAK: "Section transition. Just the section name. Max 6 words.",
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

# A small fixed list of known people names. The same approach as in the
# interview engine — enough to power detection without a real NER call.
_PERSON_KEYWORDS: Final[frozenset[str]] = frozenset(
    {
        "newton",
        "leibniz",
        "euler",
        "darwin",
        "einstein",
        "tesla",
        "edison",
        "curie",
        "voltaire",
        "monteske",
        "montesquieu",
        "rousseau",
        "kant",
        "hegel",
        "marx",
        "smith",
        "keynes",
        "fisher",
        "pasteur",
        "koch",
        "fleming",
        "freud",
        "jung",
        "skinner",
        "piaget",
        "vygotsky",
        "navoiy",
        "beruniy",
        "ibn sino",
        "ulug'bek",
        "al-xorazmiy",
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
    ) -> None:
        self._llm = llm
        self._gemini = gemini

    def _get_llm(self) -> LLMClient:
        if self._llm is None:
            self._llm = LLMClient()
        return self._llm

    def _get_gemini(self) -> GeminiClient:
        if self._gemini is None:
            self._gemini = GeminiClient()
        return self._gemini

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
        """Run the full editorial pipeline end-to-end."""

        del evidence_matrix, chunks, source_metadata, outline
        analysis = self._analyze_content(claims)
        arc = self._determine_narrative_arc(interview, analysis)
        target_count = self._size_deck(interview, analysis)

        raw_slides = await self._generate_slide_sequence(
            interview=interview,
            design=design,
            analysis=analysis,
            arc=arc,
            target_slide_count=target_count,
            language=interview.language,
        )
        content_slides = self._post_process(raw_slides, interview)

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
    # Step 1 - deck sizing
    # ------------------------------------------------------------------

    def _size_deck(
        self,
        interview: PresentationInterviewAnswers,
        analysis: ContentAnalysis,
    ) -> int:
        """Size the deck from content volume, not talk duration.

        Heuristic: each substantive claim seeds roughly one content slide
        (SPEC: "one main idea per slide"), so ``analysis.total_claims`` is a
        direct proxy for how many content slides the source material can
        actually fill. This is the only uncapped volume signal the analysis
        exposes — ``strongest_claims`` is capped at 10 and the grouped
        claim lists at 100-200 — so it is what scales with real content.
        Thin material now yields a tight deck instead of being padded out
        to match a requested running time.

        Section breaks and (optional) interactive slides are layered on top
        of the clamped content base, preserving the prior meaning of the
        returned total (content + breaks + interactive).
        """

        content_supported = analysis.total_claims
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

        people = sorted({kw.title() for kw in _PERSON_KEYWORDS if kw in blob_lower})

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
            people_mentioned=people[:50],
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
        target_slide_count: int,
        language: Language,
    ) -> list[SlideSpec]:
        """One LLM call (Sonnet) returning the editorial slide sequence."""

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
            content_summary=self._build_content_summary(analysis, interview, arc),
        )
        parsed = await self._call_editorial_with_retry(system, user)
        return _materialise_slides(parsed)

    async def _call_editorial_with_retry(
        self,
        system: str,
        user: str,
    ) -> list[_LLMSlide]:
        """One Sonnet call; on bad JSON, retry once with a stricter suffix."""

        first = await self._get_llm().complete(
            system=system, user=user, model=SONNET_MODEL, max_tokens=16_000
        )
        parsed = _parse_sequence(first.content)
        if parsed is not None:
            return parsed
        retry = await self._get_llm().complete(
            system=system,
            user=user + EDITORIAL_RETRY_SUFFIX,
            model=SONNET_MODEL,
            max_tokens=16_000,
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
        if analysis.people_mentioned:
            lines.append(
                "PEOPLE (use GALLERY_PEOPLE when 3+): " + ", ".join(analysis.people_mentioned[:15])
            )
            lines.append("")
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
        """Enforce R01, R03, R17, R27, R26 on the LLM-emitted sequence."""

        if not slides:
            return _emergency_minimal_deck(interview)
        slides = _ensure_first_is_title(slides, interview)
        slides = _enforce_word_limits(slides)
        slides = _enforce_density_arc(slides)
        slides = _fix_consecutive_repeats(slides)
        slides = _insert_section_breaks(slides, interview)
        slides = _insert_breathing_after_data(slides, interview)
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
    """Decode an editorial LLM response into typed slide objects."""

    obj = _try_parse_object(text)
    if obj is None:
        logger.warning("editorial_parse_failed_not_json len=%d head=%s", len(text), text[:300])
        return None
    try:
        wrapper = _LLMSequence.model_validate(obj)
    except ValidationError as exc:
        logger.warning("editorial_invalid_schema: %s", str(exc)[:3000])
        return None
    return wrapper.slides


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


def _materialise_slides(parsed: list[_LLMSlide]) -> list[SlideSpec]:
    """Convert parsed LLM slides into validated :class:`SlideSpec` objects."""

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
            people=raw.people,
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
                section_name=raw.section_name,
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


def _fix_consecutive_repeats(slides: list[SlideSpec]) -> list[SlideSpec]:
    """Break a run of identical slide_types by inserting a SECTION_BREAK."""

    out: list[SlideSpec] = []
    prev_type: SlideType | None = None
    for slide in slides:
        if (
            prev_type is not None
            and slide.slide_type is prev_type
            and slide.slide_type is not SlideType.SECTION_BREAK
        ):
            out.append(_make_section_break("•"))
        out.append(slide)
        prev_type = slide.slide_type
    return out


def _insert_section_breaks(
    slides: list[SlideSpec],
    interview: PresentationInterviewAnswers,
) -> list[SlideSpec]:
    """Make sure a SECTION_BREAK appears at least every 5 content slides."""

    del interview
    out: list[SlideSpec] = []
    since_break = 0
    for slide in slides:
        if slide.slide_type is SlideType.SECTION_BREAK:
            out.append(slide)
            since_break = 0
            continue
        if since_break >= 5:
            out.append(_make_section_break("•"))
            since_break = 0
        out.append(slide)
        since_break += 1
    return out


def _insert_breathing_after_data(
    slides: list[SlideSpec],
    interview: PresentationInterviewAnswers,
) -> list[SlideSpec]:
    """R27: insert a breathing slide between two consecutive data-heavy slides.

    Only ever fires on a *cross-type* data-heavy run (e.g. DATA_EMPHASIS →
    CHART_DATA): a same-type run was already split by ``_fix_consecutive_repeats``
    earlier in the pipeline, which interposes a SECTION_BREAK (a breathing type).

    The breather is seeded with a REAL takeaway pulled from the preceding data
    slide's highlighted (else first) stat, so it never ships as hollow filler.
    When that slide exposes no usable stat — CHART_DATA and TABLE_COMPACT carry
    their numbers in prose/rows, not ``stats`` — no breather is injected; absent
    beats hollow. The trade is deliberate: a chart→table run now gets no auto
    breather. The model-authored breathing content lands in the paid editorial
    pass (BUILD_STATE plan item 2) and will replace this stat-derived stub.
    """

    del interview
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


def _make_section_break(name: str) -> SlideSpec:
    return SlideSpec(
        slide_index=0,
        slide_type=SlideType.SECTION_BREAK,
        content=SlideContent(title=name[:300]),
        section_name=name[:100],
        narrative_role=NarrativePhase.CONTEXT.value,
    )


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
                title="Insufficient source material",
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
    "EditorialPass",
    "TableRow",
]
