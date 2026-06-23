"""Adversarial content critic — the Phase-3 source-grounding gate.

Runs inside the editorial pass AFTER the structural deck-vs-plan gate and BEFORE
the interactive pass, on the post-adherence content slides. The structural gate
(:func:`packages.presentation.plan_validator.validate_deck_against_plan`) already
guarantees the deck only portrays PEOPLE the source names (D-X1) and covers every
planned section; this critic catches the defects that gate cannot see — a slide
asserting a NON-PERSON fact the source never stated, a chart whose title
contradicts its own series, a title whose body is about something else, a hollow
slide, and softer drift signals.

The keystone is that CODE decides severity, not the model. The critic LLM only
PROPOSES findings with verbatim evidence; code grounds and gates them:

* every emitted finding must quote on-slide text that is found (after
  :func:`packages.core.text.normalize_for_grounding`) in the slide's visible
  text — a finding that quotes text not on the slide is dropped, which both
  kills hallucinated defects and confirms the slide handle;
* a fabrication / unsupported finding becomes a hard-stop-eligible FAIL ONLY
  when its verbatim fact-token is on the slide AND absent from the FULL claims
  list (not the capped prompt pool); a token that is actually present, or a
  paraphrase with no atomic token, degrades to WARN — so a paraphrase the model
  dislikes can never refund a good deck;
* chart/title internal-consistency findings need a verbatim second quote, both
  on the slide;
* structural and cosmetic findings are emit-only WARNs that, per
  :class:`packages.core.models.presentation.PlanValidationResult`, can never
  flip ``passed`` and so never block export;
* hollow slides are detected in CODE, not judged by the LLM.

The result reuses the existing :class:`PlanValidationResult` vocabulary so the
editorial pass routes, hard-stops, and ships on the same ``.failures`` /
``.warnings`` it already understands. The short ``C-*`` ``check_id`` tags and the
routable / hard-stop membership live here as constants, mirroring how the
``D-*`` / ``P-*`` checks are constants in
:mod:`packages.presentation.plan_validator`.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sized
from typing import Any, Final, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from packages.core.enums import (
    AuditSeverity,
    ContentCriticCategory,
    Language,
    SlideType,
)
from packages.core.gemini import GEMINI_PRO_3_1_MODEL, GeminiClient
from packages.core.llm import LLMResponse
from packages.core.models.presentation import (
    AuditCheckResult,
    DeckPlan,
    PlanValidationResult,
    SlideSpec,
)
from packages.core.models.source import SourceClaimCreate
from packages.core.prompts import (
    CONTENT_CRITIC_RETRY_SUFFIX,
    CONTENT_CRITIC_SYSTEM,
    CONTENT_CRITIC_USER,
)
from packages.core.text import grounded_in

logger = logging.getLogger(__name__)


# Per-call output budget. Gemini 3.1 Pro spends MORE "thoughts" tokens than Flash
# before visible output, and the critic's input is large (the full deck plus up to
# 60 claims), so a thin budget risks truncating the findings JSON — which would
# silently degrade the critic to a no-op via the unparseable→retry→ship path.
# Match the planner's Pro budget rather than the classifier's Flash 8k.
CRITIC_MAX_TOKENS: Final[int] = 12_000

# How many source claims the critic SEES in its prompt. The hard-stop absence
# check reads the FULL claims list (never this capped pool), so a token beyond
# the cap can never manufacture a false fabrication → false refund.
CONTENT_CRITIC_CLAIM_POOL_LIMIT: Final[int] = 60

# Audit check_id tags for each category — the short uppercase namespace the
# D-*/P-* checks also use (AuditCheckResult.check_id is max_length=10).
_CHECK_FABRICATION: Final[str] = "C-FB"
_CHECK_CLAIM_UNSUPPORTED: Final[str] = "C-US"
_CHECK_CHART_ENCODING: Final[str] = "C-CE"
_CHECK_TITLE_SUBJECT: Final[str] = "C-TS"
_CHECK_HOLLOW_SLIDE: Final[str] = "C-HL"
_CHECK_SECTION_OFF_THESIS: Final[str] = "C-SO"
_CHECK_PLAN_TYPES: Final[str] = "C-PT"
_CHECK_CROSS_SECTION: Final[str] = "C-XC"
_CHECK_WEAK_CRAFT: Final[str] = "C-CO"

CATEGORY_TO_CHECK_ID: Final[dict[ContentCriticCategory, str]] = {
    ContentCriticCategory.FABRICATION: _CHECK_FABRICATION,
    ContentCriticCategory.CLAIM_UNSUPPORTED: _CHECK_CLAIM_UNSUPPORTED,
    ContentCriticCategory.CHART_ENCODING_WRONG: _CHECK_CHART_ENCODING,
    ContentCriticCategory.TITLE_SUBJECT_MISMATCH: _CHECK_TITLE_SUBJECT,
    ContentCriticCategory.HOLLOW_SLIDE: _CHECK_HOLLOW_SLIDE,
    ContentCriticCategory.SECTION_OFF_THESIS: _CHECK_SECTION_OFF_THESIS,
    ContentCriticCategory.PLAN_TYPES_NOT_HONORED: _CHECK_PLAN_TYPES,
    ContentCriticCategory.CROSS_SECTION_INCOHERENCE: _CHECK_CROSS_SECTION,
    ContentCriticCategory.WEAK_CRAFT: _CHECK_WEAK_CRAFT,
}

# A finding routes to single-slide regen only when its check_id is here AND it is
# a FAIL with a resolvable slide_id. The structural/cosmetic categories are
# absent, so they can never trigger a regen. Hollow-slide (C-HL) is deliberately
# EXCLUDED: it is a code-detected WARN, surfaced for visibility but never
# auto-regenerated — routing it would add a Sonnet regen to the happy path of
# every deck carrying a legitimately title-dominant slide, and the structural
# gate plus _drop_hollow_dividers already catch the load-bearing empty cases.
ROUTABLE_CHECK_IDS: Final[frozenset[str]] = frozenset(
    {
        _CHECK_FABRICATION,
        _CHECK_CLAIM_UNSUPPORTED,
        _CHECK_CHART_ENCODING,
        _CHECK_TITLE_SUBJECT,
    }
)

# A finding here that STILL FAILS after one regen round is a hard stop: the deck
# asserts a fact the source does not support and must not ship. Only the
# source-grounded categories qualify; chart/title/hollow degrade-and-ship.
HARD_STOP_CHECK_IDS: Final[frozenset[str]] = frozenset(
    {_CHECK_FABRICATION, _CHECK_CLAIM_UNSUPPORTED}
)

# Slide types whose renderer is legitimately title-dominant, so "only a title"
# is a design choice, not a hollow defect.
_SPARSE_OK_TYPES: Final[frozenset[SlideType]] = frozenset(
    {SlideType.TITLE_HERO, SlideType.SECTION_BREAK}
)


# ---------------------------------------------------------------------------
# Parse models for the raw Gemini output (typed at the boundary)
# ---------------------------------------------------------------------------


class CriticEvidence(BaseModel):
    """The verbatim quotes a finding must carry to be groundable in code."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    slide_quote: str = Field(min_length=1, max_length=400)
    unsupported_token: str | None = Field(default=None, max_length=120)
    second_quote: str | None = Field(default=None, max_length=400)


class CriticRawFinding(BaseModel):
    """One defect the critic proposes, before code grounding + severity gating."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    slide_handle: int | None = Field(default=None, ge=1)
    category: ContentCriticCategory
    message: str = Field(min_length=1, max_length=500)
    evidence: CriticEvidence | None = None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def critique_deck_adversarially(
    slides: list[SlideSpec],
    plan: DeckPlan,
    *,
    claims: list[SourceClaimCreate],
    gemini: GeminiClient,
    language: Language = Language.UZ,
) -> PlanValidationResult:
    """Audit a generated slide sequence against its plan and source claims.

    Runs the code-detected hollow-slide check (no LLM) plus, when ``claims`` are
    present, one Gemini 3.1 Pro critique whose proposed findings are grounded and
    severity-gated in code (see the module docstring). Builds a fresh slide-handle
    map every call, so a re-judge after a splice maps handles against the current
    list.

    Returns the hollow-slide findings alone if the model output is unparseable
    after one retry: the critic is an additive quality gate over an
    already-structurally-valid deck, so an unusable critic response degrades to
    ship — it does not block a deck the model could not audit. (A Gemini API
    error, by contrast, propagates like every other pipeline call.)
    """

    findings: list[AuditCheckResult] = list(_detect_hollow_slides(slides))

    raw = await _call_critic_with_retry(slides, plan, claims, gemini, language)
    if raw:
        findings.extend(_translate_findings(raw, slides, claims, plan))
    return PlanValidationResult(findings=findings)


# ---------------------------------------------------------------------------
# Code-detected hollow slides (no LLM)
# ---------------------------------------------------------------------------


def _detect_hollow_slides(slides: list[SlideSpec]) -> list[AuditCheckResult]:
    """Flag a content slide that carries a title but no other content at all.

    Deterministic and conservative: a slide is hollow only when literally nothing
    besides the title is populated — no body, bullets, stats, people, image, or
    any other content field. Legitimately title-dominant types (title hero,
    section break) are skipped so a normal divider is never flagged.
    """

    out: list[AuditCheckResult] = []
    for slide in slides:
        if slide.slide_type in _SPARSE_OK_TYPES:
            continue
        if _is_hollow(slide):
            out.append(
                _make_finding(
                    ContentCriticCategory.HOLLOW_SLIDE,
                    AuditSeverity.WARN,
                    slide,
                    f"Slide #{slide.slide_index} ({slide.slide_type.value}) has a title "
                    "but no supporting content — it would render as an empty slide.",
                )
            )
    return out


def _is_hollow(slide: SlideSpec) -> bool:
    """True when only ``content.title`` carries anything.

    Inspects the dumped content so new fields are covered automatically. Anything
    truthy outside ``title`` — a subtitle, a bullet, an image hint, a chart —
    means the slide is not hollow.
    """

    data = slide.content.model_dump()
    data.pop("title", None)
    return not any(_is_meaningful(value) for value in data.values())


def _is_meaningful(value: object) -> bool:
    """Whether a dumped content-field value represents real slide content."""

    if value is None or isinstance(value, bool):
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, Sized):
        return len(value) > 0
    return True


# ---------------------------------------------------------------------------
# LLM call + parse
# ---------------------------------------------------------------------------


async def _call_critic_with_retry(
    slides: list[SlideSpec],
    plan: DeckPlan,
    claims: list[SourceClaimCreate],
    gemini: GeminiClient,
    language: Language,
) -> list[CriticRawFinding] | None:
    """One Gemini critique; on unparseable output, retry once with the suffix.

    Returns the parsed findings (possibly empty), or ``None`` if both attempts
    are unparseable. Returns an empty list without any LLM call when there are no
    claims to ground against or no slides to audit.
    """

    if not claims or not slides:
        return []

    pool = claims[:CONTENT_CRITIC_CLAIM_POOL_LIMIT]
    user = CONTENT_CRITIC_USER.format(
        language=language.value,
        thesis=plan.thesis,
        plan_spine=_format_plan_spine(plan),
        claim_pool=_format_claim_pool(pool),
        slides=_format_slides_by_handle(slides),
    )

    first = await gemini.complete(
        system=CONTENT_CRITIC_SYSTEM,
        user=user,
        model=GEMINI_PRO_3_1_MODEL,
        max_tokens=CRITIC_MAX_TOKENS,
    )
    _log_usage(first, "content_critic")
    parsed = _parse_findings(first.content)
    if parsed is not None:
        return parsed

    logger.warning(
        "content_critic_first_attempt_unparseable",
        extra={"response_length": len(first.content)},
    )
    retry = await gemini.complete(
        system=CONTENT_CRITIC_SYSTEM,
        user=user + CONTENT_CRITIC_RETRY_SUFFIX,
        model=GEMINI_PRO_3_1_MODEL,
        max_tokens=CRITIC_MAX_TOKENS,
    )
    _log_usage(retry, "content_critic_retry")
    parsed = _parse_findings(retry.content)
    if parsed is None:
        logger.warning(
            "content_critic_unparseable_after_retry",
            extra={"response_length": len(retry.content)},
        )
    return parsed


def _parse_findings(text: str) -> list[CriticRawFinding] | None:
    """Decode a critic response into raw findings, or ``None`` on a hard failure.

    A hard failure is unparseable JSON or a missing/wrong-typed ``findings``
    array (the caller retries, then degrades). An individual finding that fails
    schema validation is skipped, not fatal: one malformed finding must not blind
    the critic to the rest.
    """

    obj = _try_parse_object(text)
    if obj is None:
        return None
    raw_findings = obj.get("findings")
    if not isinstance(raw_findings, list):
        return None

    out: list[CriticRawFinding] = []
    for item in cast(list[object], raw_findings):
        try:
            out.append(CriticRawFinding.model_validate(item))
        except ValidationError as exc:
            logger.warning(
                "content_critic_finding_schema_skipped",
                extra={"error": str(exc)[:500]},
            )
    return out


def _try_parse_object(text: str) -> dict[str, Any] | None:
    """Parse a JSON object from a model response that may include code fences."""

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
        return {str(k): v for k, v in loaded.items()}  # type: ignore[misc]
    return None


# ---------------------------------------------------------------------------
# Grounding + severity gating (code decides, the model only proposes)
# ---------------------------------------------------------------------------


def _translate_findings(
    raw: list[CriticRawFinding],
    slides: list[SlideSpec],
    claims: list[SourceClaimCreate],
    plan: DeckPlan,
) -> list[AuditCheckResult]:
    """Ground each proposed finding and emit the survivors as AuditCheckResults.

    The slide handle is the 1-indexed position in ``slides`` as the model saw it;
    the map is rebuilt here every call so a re-judge after a splice resolves
    against the current list.
    """

    handles: dict[int, SlideSpec] = dict(enumerate(slides, start=1))
    visible: dict[int, str] = {
        index: _slide_visible_text(slide) for index, slide in handles.items()
    }

    out: list[AuditCheckResult] = []
    for finding in raw:
        result = _ground_and_classify(finding, handles, visible, claims, plan)
        if result is not None:
            out.append(result)
    return out


def _ground_and_classify(
    finding: CriticRawFinding,
    handles: dict[int, SlideSpec],
    visible: dict[int, str],
    claims: list[SourceClaimCreate],
    plan: DeckPlan,
) -> AuditCheckResult | None:
    """Apply the per-category grounding contract; return a finding or ``None``.

    Returns ``None`` when the proposed finding is ungroundable (off-slide quote,
    missing required evidence, or — for hollow-slide — a category the LLM is not
    allowed to raise). Severity is decided here, never by the model.
    """

    category = finding.category
    # Hollow slides are code-detected; an LLM-proposed one is ignored.
    if category is ContentCriticCategory.HOLLOW_SLIDE:
        return None

    slide = handles.get(finding.slide_handle) if finding.slide_handle else None
    slide_visible = visible.get(finding.slide_handle, "") if finding.slide_handle else ""
    evidence = finding.evidence

    if category in _SOURCE_GROUNDED_CATEGORIES:
        return _gate_source_grounded(category, finding, slide, slide_visible, claims, plan)
    if category in _INTERNAL_CONSISTENCY_CATEGORIES:
        return _gate_internal_consistency(category, finding, slide, slide_visible)
    return _gate_advisory(category, finding, slide, slide_visible, evidence)


def _gate_source_grounded(
    category: ContentCriticCategory,
    finding: CriticRawFinding,
    slide: SlideSpec | None,
    slide_visible: str,
    claims: list[SourceClaimCreate],
    plan: DeckPlan,
) -> AuditCheckResult | None:
    """C-FB / C-US: FAIL only when a verbatim token is on-slide and absent from claims."""

    evidence = finding.evidence
    if slide is None or evidence is None or not evidence.unsupported_token:
        return None
    token = evidence.unsupported_token
    # The quote must be on the slide, and the token must be inside that quote.
    if not grounded_in(evidence.slide_quote, slide_visible):
        return None
    if not grounded_in(token, evidence.slide_quote):
        return None
    # Fabricated PEOPLE are already owned by the deck-vs-plan D-X1 gate; the
    # critic's fabrication category is for non-person facts only.
    if category is ContentCriticCategory.FABRICATION and _matches_roster_person(token, plan):
        return None
    # The keystone: a hard-stop only when the token is genuinely absent from the
    # FULL claim set. A present token (or a paraphrase the model disliked)
    # degrades to WARN — never a false refund.
    severity = AuditSeverity.WARN if _token_present_in_claims(token, claims) else AuditSeverity.FAIL
    return _make_finding(category, severity, slide, finding.message)


def _gate_internal_consistency(
    category: ContentCriticCategory,
    finding: CriticRawFinding,
    slide: SlideSpec | None,
    slide_visible: str,
) -> AuditCheckResult | None:
    """C-CE / C-TS: FAIL when both the quote and the contradicting quote are on-slide."""

    evidence = finding.evidence
    if slide is None or evidence is None or not evidence.second_quote:
        return None
    if not grounded_in(evidence.slide_quote, slide_visible):
        return None
    if not grounded_in(evidence.second_quote, slide_visible):
        return None
    return _make_finding(category, AuditSeverity.FAIL, slide, finding.message)


def _gate_advisory(
    category: ContentCriticCategory,
    finding: CriticRawFinding,
    slide: SlideSpec | None,
    slide_visible: str,
    evidence: CriticEvidence | None,
) -> AuditCheckResult | None:
    """Structural / cosmetic: emit-only WARN; drop if it quotes off-slide text."""

    if (
        slide is not None
        and evidence is not None
        and evidence.slide_quote
        and not grounded_in(evidence.slide_quote, slide_visible)
    ):
        return None
    return _make_finding(category, AuditSeverity.WARN, slide, finding.message)


_SOURCE_GROUNDED_CATEGORIES: Final[frozenset[ContentCriticCategory]] = frozenset(
    {ContentCriticCategory.FABRICATION, ContentCriticCategory.CLAIM_UNSUPPORTED}
)
_INTERNAL_CONSISTENCY_CATEGORIES: Final[frozenset[ContentCriticCategory]] = frozenset(
    {ContentCriticCategory.CHART_ENCODING_WRONG, ContentCriticCategory.TITLE_SUBJECT_MISMATCH}
)


def _token_present_in_claims(token: str, claims: list[SourceClaimCreate]) -> bool:
    """True when ``token`` grounds into ANY claim's text (the full list, uncapped)."""

    return any(grounded_in(token, claim.claim_text) for claim in claims)


def _matches_roster_person(token: str, plan: DeckPlan) -> bool:
    """True when ``token`` looks like a roster figure (either name contains the other)."""

    for figure in plan.figures:
        if grounded_in(token, figure.name) or grounded_in(figure.name, token):
            return True
    return False


def _make_finding(
    category: ContentCriticCategory,
    severity: AuditSeverity,
    slide: SlideSpec | None,
    message: str,
) -> AuditCheckResult:
    """Build an AuditCheckResult, pinning the durable slide_id for routing."""

    check_id = CATEGORY_TO_CHECK_ID[category]
    return AuditCheckResult(
        check_id=check_id,
        check_name=f"content_critic.{category.value}",
        passed=False,
        severity=severity,
        slide_index=slide.slide_index if slide is not None else None,
        slide_id=slide.slide_id if slide is not None else None,
        rule_reference=check_id,
        message=message[:500],
    )


# ---------------------------------------------------------------------------
# Visible-text extraction (audience-visible text only; excludes notes + images)
# ---------------------------------------------------------------------------


def _slide_visible_text(slide: SlideSpec) -> str:
    """Concatenate every audience-visible text field of a slide.

    Excludes ``speaker_notes`` (not on the slide) and all image hint/URL fields
    (``*_prompt`` / ``*_url`` — generation inputs, not rendered text). This is the
    haystack the grounding check matches a finding's ``slide_quote`` against, and
    the basis of the hollow-slide check's notion of "content".
    """

    content = slide.content
    parts: list[str] = []

    def add(*values: str | None) -> None:
        parts.extend(value for value in values if value)

    add(
        content.title,
        content.subtitle,
        content.body_text,
        content.caption,
        content.source_citation,
        content.quote_text,
        content.quote_attribution,
        content.debate_prompt,
    )
    for items in (
        content.bullets,
        content.table_headers,
        content.chart_group_labels,
        content.category_labels,
    ):
        if items:
            add(*items)
    if content.stats:
        for stat in content.stats:
            add(stat.value, stat.unit, stat.label, stat.comparison)
    if content.people:
        for person in content.people:
            add(person.name, person.years, person.role, person.description)
    if content.keywords:
        for keyword in content.keywords:
            add(keyword.term, keyword.explanation)
    for column in (content.left_column, content.right_column):
        if column:
            add(column.heading, *column.points)
    if content.timeline_nodes:
        for node in content.timeline_nodes:
            add(node.date, node.label)
    if content.steps:
        for step in content.steps:
            add(step.label, step.description)
    if content.table_rows:
        for row in content.table_rows:
            add(*row.cells)
    if content.chart_series:
        for point in content.chart_series:
            add(point.label, point.unit)
    if content.resources:
        for resource in content.resources:
            add(resource.name, resource.description)
    if content.quiz_questions:
        for question in content.quiz_questions:
            add(question.question, question.explanation_correct, question.explanation_wrong)
            add(*[option.text for option in question.options])
    if content.matching_pairs:
        for pair in content.matching_pairs:
            add(pair.left, pair.right)
    if content.category_items:
        for category_item in content.category_items:
            add(category_item.term, category_item.category)
    if content.fill_blanks:
        for blank in content.fill_blanks:
            add(blank.statement, blank.answer)
    if content.true_false_items:
        for item in content.true_false_items:
            add(item.statement, item.explanation)
    if content.debate_options:
        for option in content.debate_options:
            add(option.position, option.framework_label)
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Prompt assembly
# ---------------------------------------------------------------------------


def _format_plan_spine(plan: DeckPlan) -> str:
    """Render the plan's sections and figure roster for the critic prompt."""

    lines: list[str] = []
    for index, section in enumerate(plan.sections, start=1):
        figures = ", ".join(name for name in section.figure_names if name) or "(none)"
        lines.append(f"{index}. {section.section_name}: {section.thesis} [figures: {figures}]")
    if plan.figures:
        lines.append("Figure roster (the only people the deck may portray):")
        for figure in plan.figures:
            years = f" ({figure.years})" if figure.years else ""
            lines.append(f"  - {figure.name}{years}: {figure.why_in_source}")
    return "\n".join(lines)


def _format_claim_pool(claims: list[SourceClaimCreate]) -> str:
    """Render the source claims as a numbered, 1-indexed block."""

    return "\n".join(f"{index}. {claim.claim_text}" for index, claim in enumerate(claims, start=1))


def _format_slides_by_handle(slides: list[SlideSpec]) -> str:
    """Render each slide as a handle-tagged block of its visible text."""

    blocks: list[str] = []
    for handle, slide in enumerate(slides, start=1):
        visible = _slide_visible_text(slide) or "(no visible text)"
        blocks.append(f"[HANDLE {handle}] type={slide.slide_type.value}\n{visible}")
    return "\n\n".join(blocks)


def _log_usage(response: LLMResponse, label: str) -> None:
    """Emit token + cost telemetry for one critic call (no cache on Gemini)."""

    logger.info(
        "content_critic_llm_call",
        extra={
            "label": label,
            "model": response.model,
            "input_tokens": response.input_tokens,
            "output_tokens": response.output_tokens,
            "cache_read_input_tokens": response.cache_read_input_tokens,
            "cache_creation_input_tokens": response.cache_creation_input_tokens,
            "estimated_cost_usd": response.estimated_cost_usd,
        },
    )


__all__ = [
    "CATEGORY_TO_CHECK_ID",
    "CONTENT_CRITIC_CLAIM_POOL_LIMIT",
    "HARD_STOP_CHECK_IDS",
    "ROUTABLE_CHECK_IDS",
    "CriticEvidence",
    "CriticRawFinding",
    "critique_deck_adversarially",
]
