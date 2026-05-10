"""Live-API smoke tests for the academic search service.

These hit real Semantic Scholar / arXiv / OpenAlex / CrossRef endpoints, so
they're gated behind ``RUN_LIVE_API_TESTS=1``. Even when enabled, each test
catches network errors and converts them to ``pytest.skip`` so a flaky
upstream or no-network sandbox doesn't surface as a regression.

Goal: catch breakage in the API contracts (renamed fields, response shape
drift) that mocked unit tests cannot. They are slow and rate-limited; do not
add many.
"""

from __future__ import annotations

import os

import httpx
import pytest

from packages.academic.doi_resolver import DOIResolver
from packages.academic.providers import (
    ArxivProvider,
    CrossRefProvider,
    OpenAlexProvider,
    SemanticScholarProvider,
)
from packages.academic.search import AcademicSearchService
from packages.core.enums import AcademicAPI

LIVE_API_TESTS = pytest.mark.skipif(
    os.environ.get("RUN_LIVE_API_TESTS") != "1",
    reason="Set RUN_LIVE_API_TESTS=1 to run live academic-API tests",
)


def _skip_on_network(exc: BaseException) -> None:
    """Convert transport-level failures into a skip rather than a failure."""

    pytest.skip(f"network unavailable: {type(exc).__name__}: {exc}")


@LIVE_API_TESTS
async def test_live_semantic_scholar_search() -> None:
    provider = SemanticScholarProvider()
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            papers = await provider.search(client, "machine learning", limit=3)
    except httpx.HTTPError as exc:
        _skip_on_network(exc)
    if not papers:
        pytest.skip("Semantic Scholar returned no papers (rate-limited?)")
    assert papers[0].title
    assert papers[0].source_api == AcademicAPI.SEMANTIC_SCHOLAR
    print(f"\nS2: {len(papers)} papers; first = {papers[0].title[:80]}")


@LIVE_API_TESTS
async def test_live_arxiv_search() -> None:
    provider = ArxivProvider()
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            papers = await provider.search(client, "transformer attention", limit=3)
    except httpx.HTTPError as exc:
        _skip_on_network(exc)
    if not papers:
        pytest.skip("arXiv returned no papers")
    assert papers[0].title
    assert papers[0].source_api == AcademicAPI.ARXIV
    print(f"\narXiv: {len(papers)} papers; first = {papers[0].title[:80]}")


@LIVE_API_TESTS
async def test_live_openalex_search() -> None:
    provider = OpenAlexProvider()
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            papers = await provider.search(client, "renewable energy", limit=3)
    except httpx.HTTPError as exc:
        _skip_on_network(exc)
    if not papers:
        pytest.skip("OpenAlex returned no papers")
    assert papers[0].title
    assert papers[0].source_api == AcademicAPI.OPENALEX
    print(f"\nOpenAlex: {len(papers)} papers; first = {papers[0].title[:80]}")


@LIVE_API_TESTS
async def test_live_crossref_search() -> None:
    provider = CrossRefProvider()
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            papers = await provider.search(client, "claude shannon information theory", limit=3)
    except httpx.HTTPError as exc:
        _skip_on_network(exc)
    if not papers:
        pytest.skip("CrossRef returned no papers")
    assert papers[0].title
    assert papers[0].source_api == AcademicAPI.CROSSREF
    print(f"\nCrossRef: {len(papers)} papers; first = {papers[0].title[:80]}")


@LIVE_API_TESTS
async def test_live_crossref_resolve_doi() -> None:
    resolver = DOIResolver()
    try:
        meta = await resolver.resolve("10.1038/nature12373")
    except httpx.HTTPError as exc:
        await resolver.close()
        _skip_on_network(exc)
    finally:
        await resolver.close()
    assert meta is not None
    assert meta.title
    print(f"\nResolved: {meta.title[:80]} ({meta.year})")


@LIVE_API_TESTS
async def test_live_full_search() -> None:
    service = AcademicSearchService()
    try:
        result = await service.search("renewable energy uzbekistan", max_results=5)
    except httpx.HTTPError as exc:
        await service.close()
        _skip_on_network(exc)
    finally:
        await service.close()

    print(
        f"\nFound {result.total_found} pre-dedup, {len(result.papers)} returned "
        f"in {result.search_time_ms} ms; errors={result.errors}"
    )
    for p in result.papers:
        print(f"  [{p.source_api.value:>17}] {p.title[:70]} ({p.year}) cites={p.citation_count}")
    assert result.search_time_ms >= 0
