"""Unavailable academic providers must not masquerade as empty searches."""

import httpx

from packages.academic.search import AcademicSearchService


async def test_http_outages_are_reported_without_aborting_search() -> None:
    """All four upstream errors remain distinguishable from no matches."""
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(503))
    ) as client:
        service = AcademicSearchService(client)
        result = await service.search("education")
    assert result.papers == []
    assert len(result.errors) == 4
    assert {error.partition(":")[0] for error in result.errors} == {
        "semantic_scholar",
        "arxiv",
        "openalex",
        "crossref",
    }
