"""Planner Pass for the presentation pipeline.

The pass turns the user's interview answers plus the project's parsed
source material — :class:`SourceChunkCreate` (the actual text the source
contains), :class:`SourceClaimCreate` (the claim extractor's view), and
:class:`SourceMetadataExtracted` (file-level provenance) — into a binding
:class:`DeckPlan`.

This pass exists to repair a structural defect in the editorial pipeline:
:meth:`EditorialPass.generate_deck_spec` discards ``chunks`` (and the
``evidence_matrix`` / ``outline``) via a ``del`` statement and authors the
deck from curated claim strings alone, so the model never sees what the
source actually says. The figure roster the editorial pass worked with was
itself filtered through a hardcoded keyword roster inside the editorial
pass, which made any figure outside that list invisible to the editorial
LLM. The two defects compounded: the model filled the resulting gap with
its prior, e.g. substituting Beethoven for Bach + Mozart on an
Enlightenment deck.

The planner runs BEFORE editorial, reads the chunk text directly, and
extracts the figure roster from people the source actually names. Phase 1
(this file plus :mod:`packages.presentation.plan_validator`) was additive.
Phase 2 binds editorial to the plan and deletes that keyword roster: this
pass now produces the roster editorial fills.

The pass is intentionally small: build a source view, call Sonnet with a
retry-once pattern that feeds the exact schema errors back on a malformed
response, parse into a :class:`DeckPlan`. There is no silent fallback — a
repeated parse failure raises
:class:`PlannerError` rather than degrading to a blank plan, because a
blank plan is exactly what a downstream executor must not be handed.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Final, NamedTuple

from pydantic import ValidationError

from packages.core.llm import LLMClient
from packages.core.models.presentation import (
    AuditCheckResult,
    DeckPlan,
    PresentationInterviewAnswers,
)
from packages.core.models.source import (
    SourceChunkCreate,
    SourceClaimCreate,
    SourceMetadataExtracted,
)
from packages.core.prompts import (
    PLANNER_FEEDBACK_HEADER,
    PLANNER_RETRY_SUFFIX,
    PLANNER_SCHEMA_RETRY_HEADER,
    PLANNER_SYSTEM,
    PLANNER_USER,
)
from packages.presentation._schema_feedback import (
    Loc,
    format_schema_feedback,
    loc_path,
    summarise_errors,
)

logger = logging.getLogger(__name__)


SONNET_MODEL: Final[str] = "claude-sonnet-4-6"
PLANNER_MAX_TOKENS: Final[int] = 6_000

# Bound the chunk text we send to the planner. The editorial pass's
# content summary is implicitly bounded by ContentAnalysis list caps
# (200 / 100 / 50 entries); the planner has no such intermediate, so we
# cap directly in characters. 32_000 characters ≈ 8K Sonnet tokens for
# the source view alone, leaving room for claims + metadata + the
# system prompt under Sonnet 4.6's 200K context window with comfort.
_MAX_CHUNK_CHARS_TOTAL: Final[int] = 32_000

# Per-chunk cap so one outlier chunk cannot starve the rest. 4_000 chars
# is roughly one printed page — enough to let the model see real
# paragraph structure rather than a flattened blur.
_MAX_CHARS_PER_CHUNK: Final[int] = 4_000

# Claim list cap: matches the largest grouped-claim cap on
# ContentAnalysis (200) so the planner sees the same breadth the
# editorial pass would have seen.
_MAX_CLAIMS_FORWARDED: Final[int] = 200


class PlannerError(RuntimeError):
    """Raised when the planner cannot produce a usable DeckPlan.

    Distinct from a generic RuntimeError so callers (the orchestrator,
    the proof harness) can distinguish a planner failure from any other
    pipeline fault and route it accordingly — a missed plan is not a
    transient API error; it is a hard stop that needs human attention.
    """


class PlannerPass:
    """Produce a :class:`DeckPlan` from interview answers + parsed source."""

    def __init__(self, llm: LLMClient | None = None) -> None:
        self._llm = llm

    def _get_llm(self) -> LLMClient:
        if self._llm is None:
            self._llm = LLMClient()
        return self._llm

    async def plan_deck(
        self,
        interview: PresentationInterviewAnswers,
        claims: list[SourceClaimCreate],
        chunks: list[SourceChunkCreate],
        source_metadata: list[SourceMetadataExtracted],
        feedback: list[AuditCheckResult] | None = None,
    ) -> DeckPlan:
        """Run one planner LLM call and return a validated DeckPlan.

        On unrecoverable parse failure (JSON malformed twice, or schema
        validation fails twice), raises :class:`PlannerError`. There is
        no silent fallback — a downstream executor must never be handed
        a blank plan, because that defeats the structural guarantee the
        planner exists to provide.

        ``feedback`` carries plan-validator findings from a prior rejected
        plan. When supplied, the specific problems are appended to the user
        prompt so this re-plan fixes the exact sections/figures the validator
        flagged (the editorial pass's one plan-reject retry). It is distinct
        from the parse/schema retry inside :meth:`_call_with_retry`, which
        recovers a response that never produced a valid DeckPlan at all.
        """

        system = PLANNER_SYSTEM
        user = PLANNER_USER.format(
            audience=interview.audience.value,
            language=interview.language.value,
            narrative_emphasis=interview.narrative_emphasis.value,
            headline_numbers=_format_headline_numbers(interview.headline_numbers),
            closing_ask=interview.closing_ask or "(none)",
            source_chunks=_build_chunk_view(chunks),
            source_claims=_build_claim_view(claims),
            source_metadata_summary=_build_metadata_view(source_metadata),
        )
        if feedback:
            user += _format_plan_feedback(feedback)
        return await self._call_with_retry(system, user)

    async def _call_with_retry(self, system: str, user: str) -> DeckPlan:
        """One Sonnet call; on failure, retry ONCE with a failure-specific nudge.

        The retry is INFORMED, not blind. The two failure modes need different
        corrections, and conflating them is why the first design could not
        recover a schema violation:

        * Malformed JSON (could not parse, or parsed to a non-object) takes
          :data:`PLANNER_RETRY_SUFFIX` — "return ONLY a JSON object".
        * Valid JSON that FAILS DeckPlan validation takes the EXACT field errors,
          already translated into corrective instructions (see
          :func:`packages.presentation._schema_feedback.format_schema_feedback`).
          At temperature 0 a blind resample
          re-rolls the same near-boundary output; telling the model which field
          violated the contract is what moves it off the boundary.

        After two failures we raise rather than synthesising a bland plan: the
        planner's whole job is to ground the deck, so an ungrounded substitute
        would silently reintroduce the bug. We do NOT add a second blind retry
        for the reason above — more rolls at temperature 0 do not help.
        """

        first = await self._get_llm().complete(
            system=system,
            user=user,
            model=SONNET_MODEL,
            max_tokens=PLANNER_MAX_TOKENS,
        )
        parsed = _parse_plan(first.content)
        if parsed.plan is not None:
            return parsed.plan

        if parsed.schema_feedback is not None:
            logger.warning(
                "planner_first_attempt_schema_invalid_retrying",
                extra={"response_length": len(first.content)},
            )
            retry_user = user + parsed.schema_feedback
        else:
            logger.warning(
                "planner_first_attempt_malformed_json_retrying",
                extra={"response_length": len(first.content)},
            )
            retry_user = user + PLANNER_RETRY_SUFFIX

        retry = await self._get_llm().complete(
            system=system,
            user=retry_user,
            model=SONNET_MODEL,
            max_tokens=PLANNER_MAX_TOKENS,
        )
        parsed = _parse_plan(retry.content)
        if parsed.plan is None:
            raise PlannerError("Planner failed to return a valid DeckPlan after one retry.")
        return parsed.plan


# ---------------------------------------------------------------------------
# Source view builders — turn the raw source artefacts into prompt text
# ---------------------------------------------------------------------------


def _build_chunk_view(chunks: list[SourceChunkCreate]) -> str:
    """Format chunk text for the planner prompt.

    Bounded so an outsized source cannot blow the context window: each
    chunk is truncated at a word boundary to :data:`_MAX_CHARS_PER_CHUNK`,
    and the cumulative budget :data:`_MAX_CHUNK_CHARS_TOTAL` stops
    appending further chunks once spent. When budget runs out before all
    chunks are seen we record a truncation marker so the model knows the
    source extends beyond what it sees.
    """

    if not chunks:
        return "(no source chunks supplied)"

    blocks: list[str] = []
    used = 0
    for chunk in chunks:
        if used >= _MAX_CHUNK_CHARS_TOTAL:
            blocks.append(
                f"[...source continues; {len(chunks) - len(blocks)} further "
                "chunks not shown due to prompt-size budget]"
            )
            break
        text = chunk.text.strip()
        if not text:
            continue
        if len(text) > _MAX_CHARS_PER_CHUNK:
            text = _truncate_at_word(text, _MAX_CHARS_PER_CHUNK)
        remaining = _MAX_CHUNK_CHARS_TOTAL - used
        if len(text) > remaining:
            text = _truncate_at_word(text, remaining)
        header = f"--- CHUNK {chunk.chunk_index}"
        if chunk.page is not None:
            header += f" (page {chunk.page})"
        header += " ---"
        blocks.append(f"{header}\n{text}")
        used += len(text)

    return "\n\n".join(blocks)


def _build_claim_view(claims: list[SourceClaimCreate]) -> str:
    """Format the extracted-claim list for the planner prompt.

    Capped at :data:`_MAX_CLAIMS_FORWARDED` so a source with thousands of
    extracted claims does not crowd out the chunks. Each line carries
    strength and type — both are signal the planner uses to weight which
    claims to anchor section theses on.
    """

    if not claims:
        return "(no extracted claims supplied)"
    lines: list[str] = []
    for claim in claims[:_MAX_CLAIMS_FORWARDED]:
        line = f"- [{claim.strength.value} / {claim.claim_type.value}] {claim.claim_text}"
        if claim.quote:
            line += f'  (quote: "{claim.quote}")'
        lines.append(line)
    if len(claims) > _MAX_CLAIMS_FORWARDED:
        lines.append(
            f"[...{len(claims) - _MAX_CLAIMS_FORWARDED} further claims not "
            "shown due to prompt-size budget]"
        )
    return "\n".join(lines)


def _build_metadata_view(metas: list[SourceMetadataExtracted]) -> str:
    """One-line provenance per source file, when available.

    The planner uses this to refer to the source by its real title in
    `why_in_source` rather than a generic "the source". Missing fields
    are omitted, not stubbed.
    """

    if not metas:
        return "(no source metadata supplied)"
    lines: list[str] = []
    for index, meta in enumerate(metas, start=1):
        parts: list[str] = []
        if meta.title:
            parts.append(f"title: {meta.title}")
        if meta.authors:
            parts.append("authors: " + ", ".join(meta.authors[:5]))
        if meta.year is not None:
            parts.append(f"year: {meta.year}")
        if meta.doi:
            parts.append(f"doi: {meta.doi}")
        if not parts:
            continue
        lines.append(f"- source {index}: " + "; ".join(parts))
    return "\n".join(lines) if lines else "(no source metadata supplied)"


def _format_headline_numbers(numbers: list[str]) -> str:
    if not numbers:
        return "(none specified)"
    return "\n".join(f"  - {n}" for n in numbers)


def _format_plan_feedback(findings: list[AuditCheckResult]) -> str:
    """Render plan-validator findings as a feedback block for the re-plan.

    Each line carries the check id, the section it concerns (when the finding
    pins one via ``slide_index``), and the validator's message — enough for the
    planner to fix the exact sections/figures that were rejected.
    """

    bullets: list[str] = []
    for finding in findings:
        where = f" (section #{finding.slide_index})" if finding.slide_index is not None else ""
        bullets.append(f"  - [{finding.check_id}]{where} {finding.message or ''}")
    return PLANNER_FEEDBACK_HEADER + "\n".join(bullets)


# ---------------------------------------------------------------------------
# JSON parsing
# ---------------------------------------------------------------------------


class _PlanParse(NamedTuple):
    """Outcome of parsing one planner response.

    ``plan`` is the validated :class:`DeckPlan`, or None on any failure.
    ``schema_feedback`` is the model-facing correction text — populated ONLY
    when the response parsed as a JSON object but failed DeckPlan validation,
    so :meth:`PlannerPass._call_with_retry` can make the retry INFORMED. It
    stays None on malformed JSON (which takes the generic JSON nudge) and on
    success. The two-field shape is what lets the caller distinguish the two
    failure modes — the single ``DeckPlan | None`` it replaced could not.
    """

    plan: DeckPlan | None
    schema_feedback: str | None


def _parse_plan(text: str) -> _PlanParse:
    """Decode a planner LLM response into a :class:`DeckPlan`.

    Returns a :class:`_PlanParse`. On malformed JSON (unparseable, or parsed to
    a non-object) both fields are None — the caller resamples with the generic
    JSON suffix. On a JSON object that FAILS DeckPlan validation, ``plan`` is
    None and ``schema_feedback`` carries the exact field errors translated into
    corrective instructions, so the retry fixes the specific violation instead
    of resampling blind.

    We do not attempt the partial-coercion salvage the editorial pass uses: a
    planner output that fails schema validation indicates the model misread the
    contract (an extra field, an invalid slide_type, sections over 8), and a
    coerced plan would silently weaken the very constraints the validator gate
    will then enforce. The informed retry is the correct recovery — it repairs
    the misread rather than papering over it.
    """

    obj = _try_parse_object(text)
    if obj is None:
        return _PlanParse(plan=None, schema_feedback=None)
    try:
        return _PlanParse(plan=DeckPlan.model_validate(obj), schema_feedback=None)
    except ValidationError as exc:
        errors = exc.errors(include_input=False)
        logger.warning(
            # Summary in the MESSAGE (not just `extra`) so it surfaces even under
            # a default formatter that drops `extra` fields — the reason the
            # original error was invisible in the Phase-2 gate console.
            "planner_schema_validation_failed: %s",
            summarise_errors(errors),
            extra={"error_locs": [loc_path(e["loc"]) for e in errors]},
        )
        feedback = format_schema_feedback(
            errors, header=PLANNER_SCHEMA_RETRY_HEADER, caveat=_planned_slide_type_caveat
        )
        return _PlanParse(plan=None, schema_feedback=feedback)


def _planned_slide_type_caveat(loc: Loc) -> str:
    """Extra retry guidance for a ``planned_slide_types`` enum miss.

    Pydantic's enum message lists ALL SlideType values, including the
    interactive_* ones PLANNER_SYSTEM rule 6 forbids in ``planned_slide_types``
    (a later pass appends those). Without this, the retry menu would contradict
    the system prompt on the prime-suspect trip for a technical source.
    """

    if "planned_slide_types" in loc:
        return (
            " Do NOT use any interactive_* value here — those are appended by a "
            "separate pass, not planned."
        )
    return ""


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


def _truncate_at_word(value: str, limit: int) -> str:
    """Clamp ``value`` to ``limit`` chars, preferring a nearby word boundary."""

    if len(value) <= limit:
        return value
    hard = value[:limit].rstrip()
    space = hard.rfind(" ")
    if space >= limit // 2:
        return hard[:space].rstrip()
    return hard


__all__ = ["SONNET_MODEL", "PlannerError", "PlannerPass"]
