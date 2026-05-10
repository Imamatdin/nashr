"""Domain-adaptive suggestion engine.

Sits between outline generation and drafting. For each article section
the engine:

1. Decides whether the section warrants suggestions (abstract and
   conclusion are skipped; literature review is always served; other
   sections are gated on existing evidence depth).
2. Builds 1-3 search queries from the section title, thesis, and
   strongest assigned claim.
3. Fans queries out to every provider whose academic domain matches
   the article, capped at :data:`MAX_CONCURRENT_PROVIDERS` concurrent
   calls.
4. Composes a relevance score per result, filters below
   :data:`RELEVANCE_THRESHOLD`, deduplicates by DOI / title, and keeps
   the top :data:`MAX_SUGGESTIONS_PER_SECTION`.

The 300-line file budget in CLAUDE.md is exceeded slightly: the engine
is one cohesive pipeline (detect → analyse → query → score → dedupe)
and splitting it into separate modules would just spread the data flow
across files without isolating any logic. Helpers stay in this module.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from datetime import datetime
from typing import Final

from packages.core.enums import CitationStatus, ClaimStrength, ClaimType
from packages.core.models.article import ArticleOutline, OutlineSection
from packages.core.models.evidence import EvidenceMatrix
from packages.core.models.source import (
    SourceChunkCreate,
    SourceClaimCreate,
    SourceMetadataExtracted,
)
from packages.core.models.suggestion import (
    DomainDetectionResult,
    DomainScore,
    SectionNeed,
    SectionNeedType,
    SectionSuggestions,
    Suggestion,
    SuggestionReport,
)
from packages.suggestions.domain_detector import DomainDetector
from packages.suggestions.provider_registry import ProviderRegistry, SuggestionProvider
from packages.suggestions.query_builder import SuggestionQueryBuilder
from packages.workers.article.claim_linker import ClaimLinker

logger = logging.getLogger(__name__)

_MIN_DOMAIN_CONFIDENCE: Final[float] = 0.1
_DOMAIN_TOP_K: Final[int] = 3
_PROVIDER_MAX_RESULTS: Final[int] = 5
_SECTION_CONTEXT_MAX_CHARS: Final[int] = 500
_DEDUPE_WORD_OVERLAP_THRESHOLD: Final[float] = 0.8
_TITLE_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"[\w']+", re.UNICODE)
_TITLE_STOPWORDS: Final[frozenset[str]] = frozenset(
    {
        "the",
        "a",
        "an",
        "of",
        "and",
        "or",
        "in",
        "on",
        "to",
        "for",
        "with",
        "from",
        "by",
        "at",
        "as",
        "is",
        "are",
    }
)

_ABSTRACT_KEYWORDS: Final[tuple[str, ...]] = (
    "abstract",
    "annotatsiya",
    "annotation",
    "аннотация",
    "summary",
    "tezislar",
)
_CONCLUSION_KEYWORDS: Final[tuple[str, ...]] = (
    "conclusion",
    "xulosa",
    "заключение",
    "concluding",
)
_LITERATURE_KEYWORDS: Final[tuple[str, ...]] = (
    "literature review",
    "literature",
    "nazariy",
    "обзор литературы",
    "обзор",
    "theoretical foundation",
    "theoretical framework",
)
_METHODOLOGY_KEYWORDS: Final[tuple[str, ...]] = (
    "methodology",
    "method",
    "metodika",
    "metodologiya",
    "методология",
    "методика",
    "методы",
)
_RESULTS_KEYWORDS: Final[tuple[str, ...]] = (
    "results",
    "natijalar",
    "результаты",
    "findings",
)
_DISCUSSION_KEYWORDS: Final[tuple[str, ...]] = (
    "discussion",
    "muhokama",
    "обсуждение",
)
_INTRODUCTION_KEYWORDS: Final[tuple[str, ...]] = (
    "introduction",
    "kirish",
    "введение",
    "background",
)
_LEGAL_KEYWORDS: Final[tuple[str, ...]] = (
    "policy",
    "regulation",
    "law",
    "legal",
    "qonun",
    "huquq",
    "закон",
    "право",
    "decree",
    "statute",
)


class SuggestionEngine:
    """Analyzes article sections and suggests authoritative external data.

    Runs after outline generation, before drafting. Returns a
    :class:`SuggestionReport` whose section_suggestions the user
    approves or skips item by item; approval routes through
    :class:`SuggestionIntegrator`.
    """

    RELEVANCE_THRESHOLD: float = 0.6
    MAX_SUGGESTIONS_PER_SECTION: int = 3
    MAX_CONCURRENT_PROVIDERS: int = 3

    def __init__(self, registry: ProviderRegistry | None = None) -> None:
        self._detector = DomainDetector()
        self._registry = registry if registry is not None else ProviderRegistry()
        self._query_builder = SuggestionQueryBuilder()
        self._linker = ClaimLinker()

    async def analyze_and_suggest(
        self,
        outline: ArticleOutline,
        evidence_matrix: EvidenceMatrix,
        claims: list[SourceClaimCreate],
        chunks: list[SourceChunkCreate],
        source_metadata: list[SourceMetadataExtracted],
        language: str,
    ) -> SuggestionReport:
        """Full suggestion pipeline.

        Detects domains, picks providers, walks every section to decide
        whether it warrants suggestions, and queries the providers in
        parallel under a single semaphore.
        """

        start = time.monotonic()
        domain_result = self._detector.detect_domains(claims, chunks, outline, source_metadata)
        providers = self._select_providers(domain_result)
        section_claims_map = self._linker.link_claims_to_sections(claims, outline)
        semaphore = asyncio.Semaphore(self.MAX_CONCURRENT_PROVIDERS)

        sections_with_suggestions = 0
        sections_skipped = 0
        all_section_suggestions: list[SectionSuggestions] = []
        all_errors: list[str] = []
        providers_queried: set[str] = set()

        for section in outline.sections:
            sid = str(section.id)
            section_claims = [claims[i] for i in section_claims_map.get(sid, [])]
            need = self._should_suggest_for_section(section, evidence_matrix, section_claims)

            if not need.needs_suggestions:
                sections_skipped += 1
                continue

            section_sugg = await self._query_section(
                section=section,
                section_claims=section_claims,
                need=need,
                providers=providers,
                language=language,
                semaphore=semaphore,
                providers_queried=providers_queried,
                errors=all_errors,
            )
            if section_sugg.suggestions:
                sections_with_suggestions += 1
                all_section_suggestions.append(section_sugg)

        elapsed_ms = max(1, int((time.monotonic() - start) * 1000))
        return SuggestionReport(
            domains_detected=domain_result,
            sections_analyzed=len(outline.sections),
            sections_with_suggestions=sections_with_suggestions,
            sections_skipped=sections_skipped,
            section_suggestions=all_section_suggestions,
            total_suggestions=sum(len(s.suggestions) for s in all_section_suggestions),
            providers_queried=sorted(providers_queried),
            search_time_ms=elapsed_ms,
            errors=all_errors,
        )

    async def suggest_for_section(
        self,
        section: OutlineSection,
        domains: list[DomainScore],
        evidence_matrix: EvidenceMatrix,
        claims: list[SourceClaimCreate],
        language: str,
    ) -> SectionSuggestions:
        """Generate suggestions for a single section.

        ``claims`` is treated as the subset already assigned to the
        section; the engine does not run a full link pass for the
        single-section path.
        """

        active = [d.domain for d in domains if d.confidence > _MIN_DOMAIN_CONFIDENCE]
        providers = self._registry.get_providers(active) if active else []
        need = self._should_suggest_for_section(section, evidence_matrix, claims)
        if not need.needs_suggestions:
            return SectionSuggestions(
                section_id=str(section.id),
                section_title=section.title,
                suggestions=[],
                search_queries_used=[],
                providers_searched=[],
            )

        semaphore = asyncio.Semaphore(self.MAX_CONCURRENT_PROVIDERS)
        providers_queried: set[str] = set()
        errors: list[str] = []
        return await self._query_section(
            section=section,
            section_claims=claims,
            need=need,
            providers=providers,
            language=language,
            semaphore=semaphore,
            providers_queried=providers_queried,
            errors=errors,
        )

    def _select_providers(self, result: DomainDetectionResult) -> list[SuggestionProvider]:
        """Pick the providers to fan out to for the detected domain set."""

        active = [d.domain for d in result.all_domains[:_DOMAIN_TOP_K]]
        if not active:
            active = [result.primary_domain]
        return self._registry.get_providers(active)

    def _should_suggest_for_section(
        self,
        section: OutlineSection,
        evidence_matrix: EvidenceMatrix,
        section_claims: list[SourceClaimCreate],
    ) -> SectionNeed:
        """Decide if ``section`` needs suggestions and explain why."""

        sid = str(section.id)
        kind = _classify_section(section)

        ready_entries = [
            e
            for e in evidence_matrix.entries
            if e.article_section_id is not None
            and str(e.article_section_id) == sid
            and e.citation_status in (CitationStatus.READY, CitationStatus.VERIFIED)
        ]
        total_entries = [
            e
            for e in evidence_matrix.entries
            if e.article_section_id is not None and str(e.article_section_id) == sid
        ]

        if kind in {_SectionKind.ABSTRACT, _SectionKind.CONCLUSION}:
            return SectionNeed(
                section_id=sid,
                needs_suggestions=False,
                need_types=[SectionNeedType.NO_NEED],
                ready_claim_count=len(ready_entries),
                total_claim_count=len(total_entries),
                reason=f"{kind} sections never receive suggestions.",
            )

        need_types: list[SectionNeedType] = []
        ready_count = len(ready_entries)

        if kind is _SectionKind.LITERATURE_REVIEW:
            need_types.append(SectionNeedType.THIN_EVIDENCE)
        elif kind is _SectionKind.INTRODUCTION:
            if ready_count < 2:
                need_types.append(SectionNeedType.THIN_EVIDENCE)
        elif kind is _SectionKind.DISCUSSION:
            if ready_count < 3:
                need_types.append(SectionNeedType.THIN_EVIDENCE)
        elif kind in {_SectionKind.METHODOLOGY, _SectionKind.RESULTS}:
            if section.needs_user_input:
                need_types.append(SectionNeedType.THIN_EVIDENCE)
        else:
            if ready_count < 2:
                need_types.append(SectionNeedType.THIN_EVIDENCE)

        if section_claims and all(c.strength is ClaimStrength.WEAK for c in section_claims):
            need_types.append(SectionNeedType.WEAK_CLAIMS_ONLY)

        if any(c.claim_type is ClaimType.STATISTICAL_RESULT for c in section_claims):
            need_types.append(SectionNeedType.NO_STATISTICAL_BACKING)

        text = f"{section.title} {section.section_thesis} {section.purpose}".lower()
        if any(kw in text for kw in _LEGAL_KEYWORDS):
            has_legal_grounding = any(
                "law" in c.claim_text.lower() or "statute" in c.claim_text.lower()
                for c in section_claims
            )
            if not has_legal_grounding:
                need_types.append(SectionNeedType.NO_LEGAL_GROUNDING)

        needs = bool(need_types)
        if not needs:
            need_types = [SectionNeedType.NO_NEED]
        reason = _format_reason(kind, ready_count, need_types)
        return SectionNeed(
            section_id=sid,
            needs_suggestions=needs,
            need_types=need_types,
            ready_claim_count=ready_count,
            total_claim_count=len(total_entries),
            reason=reason,
        )

    async def _query_section(
        self,
        section: OutlineSection,
        section_claims: list[SourceClaimCreate],
        need: SectionNeed,
        providers: list[SuggestionProvider],
        language: str,
        semaphore: asyncio.Semaphore,
        providers_queried: set[str],
        errors: list[str],
    ) -> SectionSuggestions:
        """Run every (provider × query) pair under ``semaphore`` and rank results."""

        queries = self._query_builder.build_queries(
            section,
            section_claims,
            language,
            needs_statistical=SectionNeedType.NO_STATISTICAL_BACKING in need.need_types,
        )
        section_context = _build_section_context(section, section_claims)
        sid = str(section.id)
        provider_names: list[str] = []
        raw_results: list[Suggestion] = []

        async def _run(provider: SuggestionProvider, query: str) -> list[Suggestion]:
            async with semaphore:
                return await provider.search(query, section_context, _PROVIDER_MAX_RESULTS)

        tasks = [_run(provider, query) for provider in providers for query in queries]
        if not tasks:
            return SectionSuggestions(
                section_id=sid,
                section_title=section.title,
                suggestions=[],
                search_queries_used=queries,
                providers_searched=[],
            )

        outcomes = await asyncio.gather(*tasks, return_exceptions=True)
        idx = 0
        for provider in providers:
            provider_called = False
            for _ in queries:
                outcome = outcomes[idx]
                idx += 1
                if isinstance(outcome, BaseException):
                    errors.append(f"{provider.provider_name}: {outcome}")
                    logger.warning(
                        "suggestion_provider_failed",
                        extra={"provider": provider.provider_name, "error": str(outcome)},
                    )
                    continue
                provider_called = True
                raw_results.extend(outcome)
            if provider_called:
                provider_names.append(provider.provider_name)
                providers_queried.add(provider.provider_name)

        scored = [
            s.model_copy(
                update={
                    "relevance_score": _compute_composite_score(s, section, need),
                    "target_section_id": sid,
                }
            )
            for s in raw_results
        ]
        filtered = [s for s in scored if s.relevance_score >= self.RELEVANCE_THRESHOLD]
        deduped = _dedupe(filtered)
        deduped.sort(key=lambda s: s.relevance_score, reverse=True)
        top = deduped[: self.MAX_SUGGESTIONS_PER_SECTION]

        return SectionSuggestions(
            section_id=sid,
            section_title=section.title,
            suggestions=top,
            search_queries_used=queries,
            providers_searched=provider_names,
        )


class _SectionKind:
    """Lightweight classifier output (string consts, not StrEnum to keep file local)."""

    ABSTRACT: Final[str] = "abstract"
    CONCLUSION: Final[str] = "conclusion"
    LITERATURE_REVIEW: Final[str] = "literature_review"
    METHODOLOGY: Final[str] = "methodology"
    RESULTS: Final[str] = "results"
    DISCUSSION: Final[str] = "discussion"
    INTRODUCTION: Final[str] = "introduction"
    OTHER: Final[str] = "other"


def _classify_section(section: OutlineSection) -> str:
    """Classify a section by its title, thesis, and purpose.

    Order matters: ``discussion`` is checked before ``results`` because
    "Discussion of Findings" contains the RESULTS keyword "findings"; we
    want it routed to discussion. Same goes for literature-review titles
    that mention "background".
    """

    text = f"{section.title} {section.section_thesis} {section.purpose}".lower()
    if any(kw in text for kw in _ABSTRACT_KEYWORDS):
        return _SectionKind.ABSTRACT
    if any(kw in text for kw in _CONCLUSION_KEYWORDS):
        return _SectionKind.CONCLUSION
    if any(kw in text for kw in _LITERATURE_KEYWORDS):
        return _SectionKind.LITERATURE_REVIEW
    if any(kw in text for kw in _DISCUSSION_KEYWORDS):
        return _SectionKind.DISCUSSION
    if any(kw in text for kw in _METHODOLOGY_KEYWORDS):
        return _SectionKind.METHODOLOGY
    if any(kw in text for kw in _RESULTS_KEYWORDS):
        return _SectionKind.RESULTS
    if any(kw in text for kw in _INTRODUCTION_KEYWORDS):
        return _SectionKind.INTRODUCTION
    return _SectionKind.OTHER


def _format_reason(kind: str, ready_count: int, need_types: list[SectionNeedType]) -> str:
    """One-line explanation of the SectionNeed verdict."""

    if SectionNeedType.NO_NEED in need_types and len(need_types) == 1:
        return f"Section ({kind}) has {ready_count} ready claims; sufficient evidence."
    joined = ", ".join(t.value for t in need_types)
    return f"Section ({kind}, {ready_count} ready claims): {joined}"


def _build_section_context(section: OutlineSection, section_claims: list[SourceClaimCreate]) -> str:
    """Concise string handed to providers as ``section_context``."""

    parts = [section.title]
    if section.section_thesis:
        parts.append(section.section_thesis)
    if section_claims:
        parts.append(section_claims[0].claim_text)
    joined = ". ".join(parts)
    return joined[:_SECTION_CONTEXT_MAX_CHARS]


def _compute_composite_score(
    suggestion: Suggestion,
    section: OutlineSection,
    need: SectionNeed,
) -> float:
    """Combine provider score with need-aware boosts and metadata penalties."""

    base = suggestion.relevance_score

    if (
        SectionNeedType.NO_STATISTICAL_BACKING in need.need_types
        and suggestion.indicator_value is not None
    ):
        base += 0.15
    if SectionNeedType.NO_LEGAL_GROUNDING in need.need_types and suggestion.law_number is not None:
        base += 0.15

    current_year = datetime.now().year
    if suggestion.year is not None and suggestion.year >= current_year - 3:
        base += 0.05
    if suggestion.doi:
        base += 0.05
    if suggestion.citation_count is not None and suggestion.citation_count > 50:
        base += 0.05
    if not suggestion.authors and not suggestion.law_number:
        base -= 0.1

    _ = section  # signature kept for future per-section term boosts
    return round(min(max(base, 0.0), 1.0), 4)


def _dedupe(suggestions: list[Suggestion]) -> list[Suggestion]:
    """Drop duplicates by DOI then by title-token overlap (keep highest score)."""

    by_doi: dict[str, Suggestion] = {}
    no_doi: list[Suggestion] = []
    for s in suggestions:
        if s.doi:
            existing = by_doi.get(s.doi)
            if existing is None or s.relevance_score > existing.relevance_score:
                by_doi[s.doi] = s
        else:
            no_doi.append(s)

    deduped: list[Suggestion] = list(by_doi.values())
    seen_titles: list[set[str]] = [_title_tokens(s.title) for s in deduped]
    for s in no_doi:
        tokens = _title_tokens(s.title)
        match_idx = _find_overlap(tokens, seen_titles, _DEDUPE_WORD_OVERLAP_THRESHOLD)
        if match_idx is None:
            deduped.append(s)
            seen_titles.append(tokens)
        elif s.relevance_score > deduped[match_idx].relevance_score:
            deduped[match_idx] = s
            seen_titles[match_idx] = tokens
    return deduped


def _title_tokens(title: str) -> set[str]:
    """Lowercase title token set with stopwords removed."""

    return {
        m.group(0).lower()
        for m in _TITLE_TOKEN_RE.finditer(title)
        if m.group(0).lower() not in _TITLE_STOPWORDS and len(m.group(0)) > 1
    }


def _find_overlap(candidate: set[str], existing: list[set[str]], threshold: float) -> int | None:
    """Return index of the first existing token set with overlap ≥ threshold."""

    if not candidate:
        return None
    for i, tokens in enumerate(existing):
        if not tokens:
            continue
        union = candidate | tokens
        intersect = candidate & tokens
        if not union:
            continue
        ratio = len(intersect) / len(union)
        if ratio >= threshold:
            return i
    return None


__all__ = ["SuggestionEngine"]
