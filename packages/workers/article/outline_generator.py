"""Outline generator: international-quality structural plan, then localise.

The generator turns ``(structure, thesis, claims, chunks, language,
target_pages)`` into an :class:`ArticleOutline` whose section list
matches the structural expectations encoded in
:mod:`packages.workers.article.article_structures`.

Pipeline:

1. For ilmiy_maqola, detect empirical vs theoretical from claim/chunk
   markers (or honour an explicit user override).
2. Resolve the template; compute per-section word targets from
   ``target_pages`` clamped to the template's page bounds.
3. Build a prompt that hands the LLM the per-section quality checklists,
   each section's allowance for subsections, ``min_citations`` floors,
   the user thesis, and a numbered claim list.
4. Call the LLM with the same retry-on-bad-JSON / fallback pattern
   used by :class:`ResearchInterviewEngine`.
5. Materialise an :class:`OutlineSection` per LLM-returned subsection,
   inheriting the parent template section's ``purpose`` and a per-
   subsection ``min_citations`` floor. Run :class:`ClaimLinker` over
   any claims the LLM did not pick up so they still land in the most
   semantically related section.
6. Validate against the template; raise non-blocking ``quality_flags``
   for missing claims, undersized abstracts, etc.
7. If a *required* section is entirely absent from the LLM output, run
   one repair call. Beyond that, fall back to the template-only outline.

The 300-line CLAUDE.md budget is intentionally exceeded here: the
pipeline's seven stages share state (template, word targets, claim
indices, repair flag) and splitting them across modules would just
fan-out a single coherent operation. Module-level helpers live in
module scope, not inside the class.
"""

from __future__ import annotations

import json
import logging
import math
from typing import Any, Final
from uuid import UUID

from packages.core.enums import ArticleStructure, Language
from packages.core.llm import LLMClient
from packages.core.models.article import ArticleOutline, OutlineSection
from packages.core.models.source import (
    SourceChunkCreate,
    SourceClaimCreate,
    SourceMetadataExtracted,
)
from packages.core.prompts import (
    OUTLINE_GENERATION_RETRY_SUFFIX,
    OUTLINE_GENERATION_SYSTEM,
    OUTLINE_GENERATION_USER,
)
from packages.workers.article.article_structures import (
    ABSTRACT_MAX_WORDS,
    ABSTRACT_MIN_WORDS,
    EMPIRICAL_VARIANT,
    THEORETICAL_VARIANT,
    WORDS_PER_PAGE,
    ArticleStructureTemplate,
    SectionRequirement,
    get_template,
    title_for,
)
from packages.workers.article.claim_linker import ClaimLinker

logger = logging.getLogger(__name__)


MIN_EMPIRICAL_MARKERS: Final[int] = 3
MAX_TARGET_WORDS: Final[int] = 20_000
MAX_CLAIMS_IN_PROMPT: Final[int] = 60
MAX_SOURCES_IN_PROMPT: Final[int] = 10
CLAIM_EXCERPT_CHARS: Final[int] = 220
ABSTRACT_SECTION_ID: Final[str] = "abstract"

_EMPIRICAL_MARKERS: Final[frozenset[str]] = frozenset(
    {
        "p-value",
        "p<",
        "p <",
        "p=",
        "p =",
        "significant",
        "correlation",
        "regression",
        "sample",
        "n=",
        "n =",
        "%",
        "mean",
        "std",
        "std.",
        "standard deviation",
        "dataset",
        "survey",
        "experiment",
        "measurement",
        "participants",
        "respondents",
        "anova",
        "t-test",
        "chi-square",
        "qualitative analysis",
        "coding scheme",
        "interview protocol",
    }
)


class OutlineGenerator:
    """Builds the structural outline that drafting will fill in.

    Stateless apart from the injected :class:`LLMClient` and
    :class:`ClaimLinker`. One generator may be reused across projects.
    """

    def __init__(
        self,
        llm: LLMClient | None = None,
        claim_linker: ClaimLinker | None = None,
    ) -> None:
        self._llm = llm if llm is not None else LLMClient()
        self._claim_linker = claim_linker if claim_linker is not None else ClaimLinker()

    @staticmethod
    def detect_variant(
        claims: list[SourceClaimCreate],
        chunks: list[SourceChunkCreate],
        override: str | None = None,
    ) -> str:
        """Return :data:`EMPIRICAL_VARIANT` or :data:`THEORETICAL_VARIANT`.

        ``override`` wins outright when supplied. Otherwise, the function
        scans concatenated claim text and chunk text for distinct
        empirical markers; ``MIN_EMPIRICAL_MARKERS`` distinct hits flips
        the verdict to empirical. Ambiguous cases default to theoretical
        because reviewers tolerate AIMRAD where IMRAD lacks results.
        """

        if override in (EMPIRICAL_VARIANT, THEORETICAL_VARIANT):
            return override
        haystack = " ".join(c.claim_text for c in claims) + " " + " ".join(c.text for c in chunks)
        haystack_lower = haystack.lower()
        hits = sum(1 for marker in _EMPIRICAL_MARKERS if marker in haystack_lower)
        return EMPIRICAL_VARIANT if hits >= MIN_EMPIRICAL_MARKERS else THEORETICAL_VARIANT

    @staticmethod
    def calculate_word_targets(
        template: ArticleStructureTemplate,
        target_pages: int,
    ) -> dict[str, int]:
        """Map ``section_id`` to integer word target.

        Pages are clamped to the template's ``[min_pages, max_pages]``.
        Each section gets ``round(total_words * typical_word_percentage)``,
        with the abstract additionally clamped to
        ``[ABSTRACT_MIN_WORDS, ABSTRACT_MAX_WORDS]`` regardless of total
        page budget.
        """

        clamped = max(template.min_pages, min(template.max_pages, target_pages))
        total = min(clamped * WORDS_PER_PAGE, MAX_TARGET_WORDS)
        targets: dict[str, int] = {}
        for section in template.sections:
            words = max(1, round(total * section.typical_word_percentage))
            if section.section_id == ABSTRACT_SECTION_ID:
                words = max(ABSTRACT_MIN_WORDS, min(ABSTRACT_MAX_WORDS, words))
            targets[section.section_id] = words
        return targets

    async def generate(
        self,
        *,
        project_id: UUID,
        structure: ArticleStructure,
        thesis: str,
        target_pages: int,
        claims: list[SourceClaimCreate],
        chunks: list[SourceChunkCreate],
        source_metadata: list[SourceMetadataExtracted],
        language: Language,
        empirical_override: str | None = None,
    ) -> ArticleOutline:
        """Build an :class:`ArticleOutline` for one project."""

        del project_id  # reserved for future persistence; not used in v1
        variant = (
            self.detect_variant(claims, chunks, empirical_override)
            if structure is ArticleStructure.ILMIY_MAQOLA
            else None
        )
        template = get_template(structure, variant)
        word_targets = self.calculate_word_targets(template, target_pages)

        parsed = await self._call_llm_with_repair(
            template=template,
            language=language,
            thesis=thesis,
            claims=claims,
            source_metadata=source_metadata,
            word_targets=word_targets,
        )

        if parsed is None:
            return _fallback_outline(
                template=template,
                language=language,
                thesis=thesis,
                claims=claims,
                claim_linker=self._claim_linker,
                word_targets=word_targets,
                variant=variant,
            )

        return _materialise_outline(
            template=template,
            language=language,
            thesis=thesis,
            parsed=parsed,
            claims=claims,
            word_targets=word_targets,
            variant=variant,
            claim_linker=self._claim_linker,
        )

    async def _call_llm_with_repair(
        self,
        *,
        template: ArticleStructureTemplate,
        language: Language,
        thesis: str,
        claims: list[SourceClaimCreate],
        source_metadata: list[SourceMetadataExtracted],
        word_targets: dict[str, int],
    ) -> dict[str, Any] | None:
        """Run the LLM call; on missing required sections, repair once."""

        system_prompt = OUTLINE_GENERATION_SYSTEM.format(
            quality_checklists=_format_quality_checklists(template),
        )
        user_prompt = OUTLINE_GENERATION_USER.format(
            structure_label=template.structure.value,
            variant=template.variant or "n/a",
            language=language.value,
            thesis=thesis,
            total_words=sum(word_targets.values()),
            section_briefs=_format_section_briefs(template, language, word_targets),
            claim_briefs=_format_claim_briefs(claims),
            source_briefs=_format_source_briefs(source_metadata),
        )

        try:
            parsed = await self._call_outline_with_retry(system_prompt, user_prompt)
        except Exception as exc:
            logger.warning(
                "outline_generation_llm_failed",
                extra={"error_type": type(exc).__name__, "error": str(exc)[:200]},
            )
            return None

        if parsed is None:
            return None

        missing = _missing_required_section_ids(template, parsed)
        if not missing:
            return parsed

        logger.info(
            "outline_generation_repair_required",
            extra={"missing_sections": list(missing)},
        )
        repair_prompt = (
            user_prompt
            + "\n\nThe following required sections were missing in your previous response: "
            + ", ".join(sorted(missing))
            + ". Regenerate the FULL JSON object including every required section."
        )
        try:
            repaired = await self._call_outline_with_retry(system_prompt, repair_prompt)
        except Exception as exc:
            logger.warning(
                "outline_generation_repair_failed",
                extra={"error_type": type(exc).__name__, "error": str(exc)[:200]},
            )
            return parsed
        return repaired if repaired is not None else parsed

    async def _call_outline_with_retry(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> dict[str, Any] | None:
        """One LLM call; on bad JSON, retry once with a stricter suffix."""

        first = await self._llm.complete(system=system_prompt, user=user_prompt, max_tokens=4_000)
        parsed = _try_parse_object(first.content)
        if parsed is not None:
            return parsed
        retry = await self._llm.complete(
            system=system_prompt,
            user=user_prompt + OUTLINE_GENERATION_RETRY_SUFFIX,
            max_tokens=4_000,
        )
        return _try_parse_object(retry.content)


# ---------------------------------------------------------------------------
# Materialisation: parse LLM output into an ArticleOutline
# ---------------------------------------------------------------------------


def _materialise_outline(
    *,
    template: ArticleStructureTemplate,
    language: Language,
    thesis: str,
    parsed: dict[str, Any],
    claims: list[SourceClaimCreate],
    word_targets: dict[str, int],
    variant: str | None,
    claim_linker: ClaimLinker,
) -> ArticleOutline:
    """Turn the LLM JSON object into a validated :class:`ArticleOutline`."""

    title = _coerce_str(parsed.get("title")) or _default_title(thesis)
    refined_thesis = _coerce_str(parsed.get("thesis")) or thesis
    by_id = _index_sections_by_id(parsed.get("sections"))

    outline_sections: list[OutlineSection] = []
    quality_flags: list[str] = []
    assigned_indices: set[int] = set()
    for tpl_section in template.sections:
        raw = by_id.get(tpl_section.section_id)
        if raw is None:
            outline_sections.extend(
                _template_only_sections(tpl_section, language, word_targets, claims=[], indices=[])
            )
            quality_flags.append(f"missing_llm_output:{tpl_section.section_id}")
            continue
        produced, flags, used = _expand_subsections(
            tpl_section=tpl_section,
            language=language,
            word_targets=word_targets,
            raw_section=raw,
            claims=claims,
        )
        outline_sections.extend(produced)
        quality_flags.extend(flags)
        assigned_indices.update(used)

    outline_sections = _supplement_unassigned_with_linker(
        outline_sections,
        claims=claims,
        assigned_indices=assigned_indices,
        structure=template.structure,
        thesis=refined_thesis,
        claim_linker=claim_linker,
    )

    return ArticleOutline(
        title=title[:300],
        structure=template.structure,
        sections=outline_sections,
        thesis=refined_thesis[:2_000],
        total_target_words=sum(s.target_words for s in outline_sections),
        empirical_or_theoretical=variant,
        quality_flags=quality_flags[:50],
    )


def _supplement_unassigned_with_linker(
    sections: list[OutlineSection],
    *,
    claims: list[SourceClaimCreate],
    assigned_indices: set[int],
    structure: ArticleStructure,
    thesis: str,
    claim_linker: ClaimLinker,
) -> list[OutlineSection]:
    """Run :class:`ClaimLinker` over claims the LLM did not pick up.

    The LLM's ``claim_indices`` are the primary signal; this is the
    safety net the spec calls out as step 5 of the pipeline. Claims
    that the LLM ignored are routed to the section whose existing
    ``key_claims_to_use`` overlaps them most by Jaccard similarity.
    Sections whose ``key_claims_to_use`` is empty get nothing.
    """

    unassigned = [(i, claims[i]) for i in range(len(claims)) if i not in assigned_indices]
    if not unassigned or not sections:
        return sections

    unassigned_claims = [c for _, c in unassigned]
    temp_outline = ArticleOutline(
        title="tmp",
        structure=structure,
        sections=sections,
        thesis=thesis or "tmp",
        total_target_words=sum(s.target_words for s in sections) or 1,
    )
    assignments = claim_linker.link_claims_to_sections(unassigned_claims, temp_outline)

    new_sections: list[OutlineSection] = []
    for section in sections:
        added_local = assignments.get(str(section.id), [])
        if not added_local:
            new_sections.append(section)
            continue
        keys = list(section.key_claims_to_use)
        for local_idx in added_local:
            text = unassigned_claims[local_idx].claim_text[:200]
            if text not in keys and len(keys) < 50:
                keys.append(text)
        new_sections.append(section.model_copy(update={"key_claims_to_use": keys}))
    return new_sections


def _expand_subsections(
    *,
    tpl_section: SectionRequirement,
    language: Language,
    word_targets: dict[str, int],
    raw_section: dict[str, Any],
    claims: list[SourceClaimCreate],
) -> tuple[list[OutlineSection], list[str], set[int]]:
    """Build one ``OutlineSection`` per LLM-returned subsection.

    Returns ``(sections, flags, used_indices)`` where ``used_indices`` is
    the set of claim indices the LLM actually assigned across all
    subsections of this template section. The caller uses that set to
    feed unassigned claims back through :class:`ClaimLinker`.
    """

    subs_raw = raw_section.get("subsections")
    subs: list[dict[str, Any]] = []
    if isinstance(subs_raw, list):
        for item in subs_raw:  # type: ignore[reportUnknownVariableType]
            if isinstance(item, dict):
                subs.append(item)  # type: ignore[reportUnknownArgumentType]
    if not subs:
        subs = [{}]
    subs = subs[:1] if not tpl_section.allows_subsections else subs[: tpl_section.max_subsections]

    parent_words = word_targets[tpl_section.section_id]
    per_sub_words = max(1, parent_words // len(subs))
    per_sub_min_citations = (
        tpl_section.min_citations
        if len(subs) <= 1
        else math.ceil(tpl_section.min_citations / len(subs))
    )
    parent_title = title_for(tpl_section, language)

    sections: list[OutlineSection] = []
    flags: list[str] = []
    used_indices: set[int] = set()
    for sub in subs:
        sub_title = _coerce_str(sub.get("title")) or parent_title
        if tpl_section.allows_subsections and len(subs) > 1:
            display_title = f"{parent_title}: {sub_title}"
        else:
            display_title = sub_title
        section_thesis = _coerce_str(sub.get("section_thesis"))
        claim_indices = _coerce_int_list(sub.get("claim_indices"), max_value=len(claims))
        used_indices.update(claim_indices)
        key_claims = [claims[i].claim_text[:200] for i in claim_indices]
        needs_input = bool(sub.get("needs_user_input")) or tpl_section.needs_user_input

        section_flags: list[str] = []
        if len(claim_indices) < per_sub_min_citations:
            section_flags.append(
                f"min_citations_short:{tpl_section.section_id}:{len(claim_indices)}/{per_sub_min_citations}"
            )
            flags.append(section_flags[-1])
        if not section_thesis:
            section_flags.append(f"missing_thesis:{tpl_section.section_id}")
            flags.append(section_flags[-1])
        if needs_input and not key_claims:
            section_flags.append(f"needs_user_input:{tpl_section.section_id}")

        outline_section = OutlineSection(
            title=display_title[:200],
            target_words=per_sub_words,
            key_claims_to_use=key_claims[:50],
            purpose=tpl_section.internal_purpose[:500],
            section_thesis=section_thesis[:1_000],
            quality_flags=section_flags[:20],
            needs_user_input=needs_input,
            min_citations=per_sub_min_citations,
        )
        sections.append(outline_section)
    return sections, flags, used_indices


def _template_only_sections(
    tpl_section: SectionRequirement,
    language: Language,
    word_targets: dict[str, int],
    *,
    claims: list[SourceClaimCreate],
    indices: list[int],
) -> list[OutlineSection]:
    """Build placeholder OutlineSection(s) when the LLM produced nothing."""

    parent_title = title_for(tpl_section, language)
    parent_words = word_targets[tpl_section.section_id]
    key_claims = [claims[i].claim_text[:200] for i in indices if 0 <= i < len(claims)]
    return [
        OutlineSection(
            title=parent_title[:200],
            target_words=parent_words,
            key_claims_to_use=key_claims[:50],
            purpose=tpl_section.internal_purpose[:500],
            section_thesis="",
            quality_flags=[f"missing_llm_output:{tpl_section.section_id}"],
            needs_user_input=tpl_section.needs_user_input,
            min_citations=tpl_section.min_citations,
        )
    ]


# ---------------------------------------------------------------------------
# Fallback outline (no LLM at all)
# ---------------------------------------------------------------------------


def _fallback_outline(
    *,
    template: ArticleStructureTemplate,
    language: Language,
    thesis: str,
    claims: list[SourceClaimCreate],
    claim_linker: ClaimLinker,
    word_targets: dict[str, int],
    variant: str | None,
) -> ArticleOutline:
    """Return a template-only outline with claims distributed by linker."""

    placeholder_sections = [
        OutlineSection(
            title=title_for(tpl_section, language)[:200],
            target_words=word_targets[tpl_section.section_id],
            key_claims_to_use=[tpl_section.section_id],
            purpose=tpl_section.internal_purpose[:500],
            section_thesis="",
            quality_flags=["fallback_template_only"],
            needs_user_input=tpl_section.needs_user_input,
            min_citations=tpl_section.min_citations,
        )
        for tpl_section in template.sections
    ]
    placeholder_outline = ArticleOutline(
        title=_default_title(thesis),
        structure=template.structure,
        sections=placeholder_sections,
        thesis=thesis[:2_000],
        total_target_words=sum(s.target_words for s in placeholder_sections),
        empirical_or_theoretical=variant,
        quality_flags=["fallback_template_only"],
    )

    section_assignments = claim_linker.link_claims_to_sections(claims, placeholder_outline)
    rebuilt: list[OutlineSection] = []
    for tpl_section, placeholder in zip(template.sections, placeholder_sections, strict=True):
        indices = section_assignments.get(str(placeholder.id), [])
        key_claims = [claims[i].claim_text[:200] for i in indices][:50]
        rebuilt.append(
            placeholder.model_copy(
                update={
                    "key_claims_to_use": key_claims or [tpl_section.section_id],
                    "quality_flags": ["fallback_template_only"],
                }
            )
        )
    return placeholder_outline.model_copy(update={"sections": rebuilt})


# ---------------------------------------------------------------------------
# Prompt formatters
# ---------------------------------------------------------------------------


def _format_quality_checklists(template: ArticleStructureTemplate) -> str:
    lines: list[str] = []
    for section in template.sections:
        lines.append(f"- {section.section_id}:")
        for item in section.quality_checklist:
            lines.append(f"    * {item}")
    return "\n".join(lines)


def _format_section_briefs(
    template: ArticleStructureTemplate,
    language: Language,
    word_targets: dict[str, int],
) -> str:
    lines: list[str] = []
    for section in template.sections:
        title = title_for(section, language)
        lines.append(
            f"- section_id={section.section_id}, title={title!r}, "
            f"target_words={word_targets[section.section_id]}, "
            f"allows_subsections={str(section.allows_subsections).lower()}, "
            f"max_subsections={section.max_subsections}, "
            f"min_citations={section.min_citations}, "
            f"needs_user_input={str(section.needs_user_input).lower()}, "
            f"purpose={section.internal_purpose}"
        )
    return "\n".join(lines)


def _format_claim_briefs(claims: list[SourceClaimCreate]) -> str:
    if not claims:
        return "(no claims supplied — generate the outline from the thesis alone)"
    lines: list[str] = []
    for index, claim in enumerate(claims[:MAX_CLAIMS_IN_PROMPT]):
        excerpt = claim.claim_text.replace("\n", " ")[:CLAIM_EXCERPT_CHARS]
        source = claim.source_chunk_id or "?"
        lines.append(f"{index}. {excerpt} [source: {source}]")
    return "\n".join(lines)


def _format_source_briefs(metadata: list[SourceMetadataExtracted]) -> str:
    if not metadata:
        return "(no source metadata available)"
    lines: list[str] = []
    for index, meta in enumerate(metadata[:MAX_SOURCES_IN_PROMPT]):
        title = (meta.title or "Untitled").strip()[:160]
        authors = ", ".join(meta.authors[:3])
        year = str(meta.year) if meta.year else ""
        bits = [p for p in (authors, year) if p]
        suffix = f" ({', '.join(bits)})" if bits else ""
        lines.append(f"- source_{index}: {title}{suffix}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Validation / parsing helpers
# ---------------------------------------------------------------------------


def _missing_required_section_ids(
    template: ArticleStructureTemplate, parsed: dict[str, Any]
) -> set[str]:
    """Return the IDs of required template sections absent from the LLM output."""

    seen = set(_index_sections_by_id(parsed.get("sections")).keys())
    return {s.section_id for s in template.sections if s.is_required and s.section_id not in seen}


def _index_sections_by_id(raw: object) -> dict[str, dict[str, Any]]:
    """Coerce ``parsed["sections"]`` into a ``{section_id: raw_section}`` map.

    The LLM response is genuinely untyped (``json.loads`` of a free-form
    string), so we narrow at this single boundary into a strongly typed
    dict everywhere else in the module can rely on.
    """

    if not isinstance(raw, list):
        return {}
    by_id: dict[str, dict[str, Any]] = {}
    for item in raw:  # type: ignore[reportUnknownVariableType]
        if not isinstance(item, dict):
            continue
        section_id = item.get("section_id")  # type: ignore[reportUnknownMemberType]
        if isinstance(section_id, str):
            by_id[section_id] = item  # type: ignore[reportUnknownArgumentType]
    return by_id


def _try_parse_object(content: str) -> dict[str, Any] | None:
    """Parse an LLM response into a dict, stripping ``json`` fences."""

    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`").lstrip()
        if text.startswith("json"):
            text = text[len("json") :].lstrip()
    try:
        loaded = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(loaded, dict):
        return None
    return loaded  # type: ignore[reportUnknownVariableType]


def _coerce_str(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()


def _coerce_int_list(value: object, *, max_value: int) -> list[int]:
    if not isinstance(value, list):
        return []
    out: list[int] = []
    seen: set[int] = set()
    for item in value:  # type: ignore[reportUnknownVariableType]
        if isinstance(item, bool):
            continue
        if isinstance(item, int):
            idx = item
        elif isinstance(item, str) and item.lstrip("-").isdigit():
            idx = int(item)
        else:
            continue
        if 0 <= idx < max_value and idx not in seen:
            seen.add(idx)
            out.append(idx)
    return out


def _default_title(thesis: str) -> str:
    """Build a plausible article title from the thesis when LLM omits one."""

    stripped = thesis.strip()
    if not stripped:
        return "Untitled article"
    first_sentence = stripped.split(".")[0].strip() or stripped
    return first_sentence[:200]


__all__ = ["OutlineGenerator"]
