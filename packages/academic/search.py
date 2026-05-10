"""Federated academic search across Semantic Scholar, arXiv, OpenAlex, CrossRef.

The four providers are queried concurrently with :func:`asyncio.gather`. A
provider exception is captured into ``AcademicSearchResult.errors`` and does
not abort the search — the user-visible promise is "we found something",
not "every backend was reachable".

Deduplication is by DOI: when the same paper surfaces from multiple
providers we keep the richest version (most metadata), so e.g. a
Semantic-Scholar record with abstract + citation count wins over the same
DOI from CrossRef (which has neither). Records without a DOI are *never*
collapsed because their identity cannot be established across APIs.

Final ordering is citation count desc, then year desc; ``None`` values
sort last so unknown-citation papers rank below any with a known count.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable

import httpx

from packages.academic.providers import (
    ArxivProvider,
    CrossRefProvider,
    OpenAlexProvider,
    SemanticScholarProvider,
)
from packages.core.enums import AcademicAPI
from packages.core.models.academic import AcademicPaper, AcademicSearchResult

logger = logging.getLogger(__name__)


_MAX_RESULT_PAPERS: int = 100


class AcademicSearchService:
    """Federated search facade owning one shared :class:`httpx.AsyncClient`.

    ``API_TIMEOUT`` is per-request, not per-search; callers waiting for the
    overall search can additionally wrap :meth:`search` in :func:`asyncio.wait_for`
    for a hard ceiling.
    """

    API_TIMEOUT: int = 10

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._http = client if client is not None else httpx.AsyncClient(timeout=self.API_TIMEOUT)
        self._owns_client = client is None
        self._semantic_scholar = SemanticScholarProvider()
        self._arxiv = ArxivProvider()
        self._openalex = OpenAlexProvider()
        self._crossref = CrossRefProvider()

    async def search(self, query: str, max_results: int = 10) -> AcademicSearchResult:
        """Search all four providers concurrently, deduplicate, and rank."""

        cleaned_query = query.strip()
        if not cleaned_query:
            return AcademicSearchResult(query=query, papers=[], total_found=0, errors=[])

        per_provider_limit = max(max_results, 1)
        start = time.perf_counter()

        provider_calls: list[tuple[AcademicAPI, Callable[[], Awaitable[list[AcademicPaper]]]]] = [
            (
                AcademicAPI.SEMANTIC_SCHOLAR,
                lambda: self._semantic_scholar.search(
                    self._http, cleaned_query, per_provider_limit
                ),
            ),
            (
                AcademicAPI.ARXIV,
                lambda: self._arxiv.search(self._http, cleaned_query, per_provider_limit),
            ),
            (
                AcademicAPI.OPENALEX,
                lambda: self._openalex.search(self._http, cleaned_query, per_provider_limit),
            ),
            (
                AcademicAPI.CROSSREF,
                lambda: self._crossref.search(self._http, cleaned_query, per_provider_limit),
            ),
        ]

        results = await asyncio.gather(
            *(call() for _, call in provider_calls), return_exceptions=True
        )

        all_papers: list[AcademicPaper] = []
        errors: list[str] = []
        for (api, _), result in zip(provider_calls, results, strict=True):
            if isinstance(result, BaseException):
                errors.append(f"{api.value}: {type(result).__name__}: {result}")
                logger.warning(
                    "academic_provider_failed",
                    extra={"provider": api.value, "error": str(result)},
                )
                continue
            all_papers.extend(result)

        deduped = _deduplicate(all_papers)
        deduped.sort(key=_rank_key)
        truncated = deduped[:max_results]
        elapsed_ms = int((time.perf_counter() - start) * 1000)

        return AcademicSearchResult(
            query=cleaned_query[:500],
            papers=truncated[:_MAX_RESULT_PAPERS],
            total_found=len(all_papers),
            errors=errors,
            search_time_ms=elapsed_ms,
        )

    async def close(self) -> None:
        """Close the underlying HTTP client if this service created it."""

        if self._owns_client:
            await self._http.aclose()


def _deduplicate(papers: list[AcademicPaper]) -> list[AcademicPaper]:
    """Collapse same-DOI duplicates, keeping the richest record.

    Papers with a ``None`` DOI are kept verbatim because their identity is
    unknown; collapsing them would silently merge unrelated works.
    """

    by_doi: dict[str, AcademicPaper] = {}
    no_doi: list[AcademicPaper] = []

    for paper in papers:
        if paper.doi is None:
            no_doi.append(paper)
            continue
        key = paper.doi.lower()
        existing = by_doi.get(key)
        if existing is None or _richness(paper) > _richness(existing):
            by_doi[key] = paper

    return list(by_doi.values()) + no_doi


def _richness(paper: AcademicPaper) -> int:
    """Score how much metadata a paper carries; higher is preferred in dedup ties."""

    score = 0
    if paper.abstract:
        score += 4
    if paper.pdf_url:
        score += 3
    if paper.citation_count is not None:
        score += 2
    if paper.journal:
        score += 1
    if paper.authors:
        score += 1
    if paper.year is not None:
        score += 1
    return score


def _rank_key(paper: AcademicPaper) -> tuple[int, int, int]:
    """Sort key: known citations first, then highest count, then newest year."""

    citations_unknown = 1 if paper.citation_count is None else 0
    neg_citations = -(paper.citation_count or 0)
    neg_year = -(paper.year or 0)
    return (citations_unknown, neg_citations, neg_year)
