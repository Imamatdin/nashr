"""Bridges the federated AcademicSearchService into the suggestion provider API.

The Week-1 :class:`AcademicSearchService` already federates Semantic Scholar,
arXiv, OpenAlex, and CrossRef and returns a single deduplicated list of
:class:`AcademicPaper`. This bridge wraps that service so the suggestion
engine can plug it in alongside domain-specific providers (PubMed, World
Bank, etc.) without re-implementing search.

The bridge owns no HTTP client of its own; the bridged
:class:`AcademicSearchService` takes the optional ``httpx.AsyncClient``
exactly as it does in production code, so tests can inject one.
"""

from __future__ import annotations

import logging
from typing import ClassVar

import httpx

from packages.academic.search import AcademicSearchService
from packages.core.enums import AcademicAPI
from packages.core.models.academic import AcademicPaper
from packages.core.models.suggestion import (
    AcademicDomain,
    Suggestion,
    SuggestionSource,
)

logger = logging.getLogger(__name__)


_BASELINE_SCORE: float = 0.7
_RECENT_YEAR_BOOST_THRESHOLD: int = 5
_HIGH_CITATION_THRESHOLD: int = 100
_CURRENT_YEAR: int = 2026


class AcademicBridgeProvider:
    """Adapter from :class:`AcademicSearchService` to the suggestion-provider API."""

    provider_name: str = "Academic Search"
    supported_domains: ClassVar[list[AcademicDomain]] = [
        AcademicDomain.GENERAL,
        AcademicDomain.EDUCATION,
        AcademicDomain.ENGINEERING,
        AcademicDomain.COMPUTER_SCIENCE,
        AcademicDomain.SOCIAL_SCIENCES,
        AcademicDomain.ENVIRONMENTAL,
        AcademicDomain.AGRICULTURE,
    ]

    def __init__(
        self,
        search_service: AcademicSearchService | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if search_service is not None:
            self._search_service = search_service
            self._owns_service = False
        else:
            self._search_service = AcademicSearchService(client=client)
            self._owns_service = True

    async def search(
        self,
        query: str,
        section_context: str,
        max_results: int = 5,
    ) -> list[Suggestion]:
        """Run a federated academic search and adapt papers into suggestions."""

        cleaned = query.strip()
        if not cleaned:
            return []

        result = await self._search_service.search(cleaned, max_results=max_results)
        suggestions: list[Suggestion] = []
        for paper in result.papers:
            suggestions.append(_paper_to_suggestion(paper))
        return suggestions

    async def close(self) -> None:
        """Close the bridged search service if this bridge owns it."""

        if self._owns_service:
            await self._search_service.close()


def _paper_to_suggestion(paper: AcademicPaper) -> Suggestion:
    """Convert one :class:`AcademicPaper` into a :class:`Suggestion` with score."""

    description = paper.abstract or paper.title
    return Suggestion(
        title=paper.title,
        description=description[:1000],
        source_provider=_map_source(paper.source_api),
        relevance_score=_score(paper),
        authors=list(paper.authors),
        year=paper.year,
        doi=paper.doi,
        url=paper.pdf_url,
        citation_count=paper.citation_count,
    )


def _map_source(api: AcademicAPI) -> SuggestionSource:
    """Map the federated provider tag to the suggestion-source enum."""

    if api is AcademicAPI.SEMANTIC_SCHOLAR:
        return SuggestionSource.SEMANTIC_SCHOLAR
    if api is AcademicAPI.ARXIV:
        return SuggestionSource.ARXIV
    if api is AcademicAPI.OPENALEX:
        return SuggestionSource.OPENALEX
    return SuggestionSource.SEMANTIC_SCHOLAR


def _score(paper: AcademicPaper) -> float:
    """Derive a 0..1 relevance score from citation count and recency."""

    score = _BASELINE_SCORE
    if paper.citation_count is not None and paper.citation_count >= _HIGH_CITATION_THRESHOLD:
        score += 0.15
    if paper.year is not None and _CURRENT_YEAR - paper.year <= _RECENT_YEAR_BOOST_THRESHOLD:
        score += 0.1
    if paper.doi:
        score += 0.05
    return round(min(1.0, score), 4)
