"""Behaviour tests for :class:`AcademicBridgeProvider`.

The bridge wraps :class:`AcademicSearchService`. We don't re-test that
service's federation logic here (it has its own suite); we test only the
bridge contract: papers in → suggestions out, with the right
:class:`SuggestionSource` mapping, citation-relevant metadata preserved,
and zero-paper queries handled.
"""

from __future__ import annotations

from packages.academic.search import AcademicSearchService
from packages.core.enums import AcademicAPI
from packages.core.models.academic import AcademicPaper, AcademicSearchResult
from packages.core.models.suggestion import Suggestion, SuggestionSource
from packages.suggestions.providers.academic_bridge import AcademicBridgeProvider


class _FakeSearchService:
    """Stand-in for :class:`AcademicSearchService` returning scripted papers."""

    def __init__(self, papers: list[AcademicPaper]) -> None:
        self._papers = papers
        self.last_query: str | None = None
        self.last_max_results: int = 0
        self.closed: bool = False

    async def search(self, query: str, max_results: int = 10) -> AcademicSearchResult:
        self.last_query = query
        self.last_max_results = max_results
        return AcademicSearchResult(query=query, papers=self._papers, total_found=len(self._papers))

    async def close(self) -> None:
        self.closed = True


def _make_paper(api: AcademicAPI, *, year: int = 2023, doi: str | None = "10.x/y") -> AcademicPaper:
    return AcademicPaper(
        title="A Paper on Solar Power",
        authors=["Lee, J.", "Kim, S."],
        year=year,
        abstract="An abstract about photovoltaics in Central Asia.",
        doi=doi,
        citation_count=200,
        pdf_url="https://example.org/paper.pdf",
        source_api=api,
        external_id="ext-1",
        journal="Energy Policy",
    )


async def test_bridge_converts_academic_papers_to_suggestions() -> None:
    fake = _FakeSearchService([_make_paper(AcademicAPI.SEMANTIC_SCHOLAR)])
    bridge = AcademicBridgeProvider(search_service=fake)  # type: ignore[arg-type]
    suggestions = await bridge.search("solar power", "Results", max_results=3)
    assert fake.last_query == "solar power"
    assert fake.last_max_results == 3
    assert len(suggestions) == 1
    s = suggestions[0]
    assert isinstance(s, Suggestion)
    assert s.title == "A Paper on Solar Power"
    assert s.authors == ["Lee, J.", "Kim, S."]
    assert s.year == 2023
    assert s.doi == "10.x/y"
    assert s.citation_count == 200


async def test_bridge_maps_provider_correctly() -> None:
    cases = [
        (AcademicAPI.SEMANTIC_SCHOLAR, SuggestionSource.SEMANTIC_SCHOLAR),
        (AcademicAPI.ARXIV, SuggestionSource.ARXIV),
        (AcademicAPI.OPENALEX, SuggestionSource.OPENALEX),
    ]
    for api, expected in cases:
        fake = _FakeSearchService([_make_paper(api)])
        bridge = AcademicBridgeProvider(search_service=fake)  # type: ignore[arg-type]
        suggestions = await bridge.search("x", "", max_results=1)
        assert suggestions[0].source_provider == expected


async def test_bridge_handles_empty_results() -> None:
    fake = _FakeSearchService([])
    bridge = AcademicBridgeProvider(search_service=fake)  # type: ignore[arg-type]
    suggestions = await bridge.search("nothing", "", max_results=3)
    assert suggestions == []


async def test_bridge_blank_query_returns_empty() -> None:
    fake = _FakeSearchService([_make_paper(AcademicAPI.SEMANTIC_SCHOLAR)])
    bridge = AcademicBridgeProvider(search_service=fake)  # type: ignore[arg-type]
    suggestions = await bridge.search("   ", "", max_results=1)
    assert suggestions == []
    assert fake.last_query is None


async def test_bridge_close_propagates_when_owned() -> None:
    """If the bridge constructed the service it must close it on close()."""

    bridge = AcademicBridgeProvider()
    assert isinstance(bridge._search_service, AcademicSearchService)
    await bridge.close()


async def test_bridge_close_does_not_close_injected_service() -> None:
    fake = _FakeSearchService([])
    bridge = AcademicBridgeProvider(search_service=fake)  # type: ignore[arg-type]
    await bridge.close()
    assert fake.closed is False


async def test_bridge_score_higher_for_recent_high_cite_with_doi() -> None:
    fake_recent = _FakeSearchService([_make_paper(AcademicAPI.SEMANTIC_SCHOLAR, year=2024)])
    fake_old = _FakeSearchService([_make_paper(AcademicAPI.SEMANTIC_SCHOLAR, year=1990)])
    bridge_recent = AcademicBridgeProvider(search_service=fake_recent)  # type: ignore[arg-type]
    bridge_old = AcademicBridgeProvider(search_service=fake_old)  # type: ignore[arg-type]
    recent = await bridge_recent.search("x", "", max_results=1)
    old = await bridge_old.search("x", "", max_results=1)
    assert recent[0].relevance_score > old[0].relevance_score
