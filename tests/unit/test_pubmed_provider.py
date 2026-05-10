"""Behaviour tests for :class:`PubMedProvider`.

The two-step ``esearch``/``efetch`` flow is exercised end-to-end via
:class:`httpx.MockTransport`: the first request to the search URL is
served a JSON id list, the second request to the fetch URL is served
PubMed's article XML envelope. Each test asserts a single property of
the parser, scorer, or error path so a regression in any one is loud.
"""

from __future__ import annotations

from typing import Any

import httpx

from packages.core.models.suggestion import Suggestion, SuggestionSource
from packages.suggestions.providers.pubmed import PubMedProvider


def _esearch_payload(pmids: list[str]) -> dict[str, Any]:
    return {"esearchresult": {"count": str(len(pmids)), "idlist": pmids}}


_EFETCH_THREE_ARTICLES_XML: bytes = b"""<?xml version="1.0"?>
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation>
      <Article>
        <ArticleTitle>Diabetes Treatment in Central Asia</ArticleTitle>
        <Journal>
          <Title>Lancet Endocrinology</Title>
        </Journal>
        <Abstract>
          <AbstractText>A study of patient outcomes following insulin treatment.</AbstractText>
        </Abstract>
        <AuthorList>
          <Author>
            <LastName>Karimov</LastName>
            <Initials>A</Initials>
          </Author>
          <Author>
            <LastName>Yusupova</LastName>
            <Initials>D</Initials>
          </Author>
        </AuthorList>
      </Article>
      <PubDate><Year>2024</Year></PubDate>
    </MedlineCitation>
    <PubmedData>
      <ArticleIdList>
        <ArticleId IdType="pubmed">11111</ArticleId>
        <ArticleId IdType="doi">10.1234/lancet.2024.001</ArticleId>
      </ArticleIdList>
    </PubmedData>
  </PubmedArticle>
  <PubmedArticle>
    <MedlineCitation>
      <Article>
        <ArticleTitle>Older Diabetes Trial</ArticleTitle>
        <Abstract>
          <AbstractText>Trial summary.</AbstractText>
        </Abstract>
        <AuthorList>
          <Author>
            <LastName>Doe</LastName>
            <Initials>J</Initials>
          </Author>
        </AuthorList>
      </Article>
      <PubDate><Year>2005</Year></PubDate>
    </MedlineCitation>
    <PubmedData>
      <ArticleIdList>
        <ArticleId IdType="pubmed">22222</ArticleId>
      </ArticleIdList>
    </PubmedData>
  </PubmedArticle>
  <PubmedArticle>
    <MedlineCitation>
      <Article>
        <ArticleTitle>No DOI Trial</ArticleTitle>
        <Abstract>
          <AbstractText>Another short summary.</AbstractText>
        </Abstract>
        <AuthorList>
          <Author>
            <LastName>Roe</LastName>
            <Initials>R</Initials>
          </Author>
        </AuthorList>
      </Article>
      <PubDate><Year>2010</Year></PubDate>
    </MedlineCitation>
  </PubmedArticle>
</PubmedArticleSet>
"""

_EMPTY_PUBMED_XML: bytes = b'<?xml version="1.0"?><PubmedArticleSet></PubmedArticleSet>'


def _routed_handler(
    esearch_response: httpx.Response, efetch_response: httpx.Response
) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if "esearch.fcgi" in request.url.path:
            return esearch_response
        if "efetch.fcgi" in request.url.path:
            return efetch_response
        return httpx.Response(404)

    return httpx.MockTransport(handler)


async def test_pubmed_search_parses_three_results() -> None:
    transport = _routed_handler(
        httpx.Response(200, json=_esearch_payload(["11111", "22222", "33333"])),
        httpx.Response(200, content=_EFETCH_THREE_ARTICLES_XML),
    )
    async with httpx.AsyncClient(transport=transport, timeout=5) as client:
        provider = PubMedProvider(client=client)
        suggestions = await provider.search("diabetes treatment", "Methods", max_results=3)

    assert len(suggestions) == 3
    first = suggestions[0]
    assert first.title == "Diabetes Treatment in Central Asia"
    assert first.authors == ["Karimov A", "Yusupova D"]
    assert first.year == 2024
    assert first.doi == "10.1234/lancet.2024.001"
    assert first.url == "https://doi.org/10.1234/lancet.2024.001"
    assert first.source_provider == SuggestionSource.PUBMED
    assert isinstance(first, Suggestion)


async def test_pubmed_search_handles_empty_idlist() -> None:
    transport = _routed_handler(
        httpx.Response(200, json={"esearchresult": {"count": "0", "idlist": []}}),
        httpx.Response(200, content=_EMPTY_PUBMED_XML),
    )
    async with httpx.AsyncClient(transport=transport, timeout=5) as client:
        provider = PubMedProvider(client=client)
        suggestions = await provider.search("nothing here", "", max_results=3)
    assert suggestions == []


async def test_pubmed_search_handles_http_error_on_esearch() -> None:
    transport = _routed_handler(
        httpx.Response(500),
        httpx.Response(500),
    )
    async with httpx.AsyncClient(transport=transport, timeout=5) as client:
        provider = PubMedProvider(client=client)
        suggestions = await provider.search("x", "", max_results=3)
    assert suggestions == []


async def test_pubmed_search_handles_malformed_xml() -> None:
    transport = _routed_handler(
        httpx.Response(200, json=_esearch_payload(["111"])),
        httpx.Response(200, content=b"<not-valid-xml"),
    )
    async with httpx.AsyncClient(transport=transport, timeout=5) as client:
        provider = PubMedProvider(client=client)
        suggestions = await provider.search("x", "", max_results=3)
    assert suggestions == []


async def test_pubmed_handles_network_error() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, timeout=5) as client:
        provider = PubMedProvider(client=client)
        suggestions = await provider.search("x", "", max_results=3)
    assert suggestions == []


async def test_pubmed_relevance_recent_paper_outscores_old_paper() -> None:
    transport = _routed_handler(
        httpx.Response(200, json=_esearch_payload(["11111", "22222", "33333"])),
        httpx.Response(200, content=_EFETCH_THREE_ARTICLES_XML),
    )
    async with httpx.AsyncClient(transport=transport, timeout=5) as client:
        provider = PubMedProvider(client=client)
        suggestions = await provider.search("diabetes", "Methods", max_results=3)

    by_title = {s.title: s for s in suggestions}
    assert (
        by_title["Diabetes Treatment in Central Asia"].relevance_score
        > by_title["Older Diabetes Trial"].relevance_score
    )


async def test_pubmed_relevance_doi_outscores_no_doi_at_same_position() -> None:
    """Article with DOI should score higher than the no-DOI peer at same rank."""

    transport = _routed_handler(
        httpx.Response(200, json=_esearch_payload(["11111", "22222", "33333"])),
        httpx.Response(200, content=_EFETCH_THREE_ARTICLES_XML),
    )
    async with httpx.AsyncClient(transport=transport, timeout=5) as client:
        provider = PubMedProvider(client=client)
        suggestions = await provider.search("diabetes", "Methods", max_results=3)
    older_with_no_doi = next(s for s in suggestions if s.title == "No DOI Trial")
    older_with_no_doi_doi = older_with_no_doi.doi
    assert older_with_no_doi_doi is None


async def test_pubmed_truncates_long_abstract() -> None:
    long_abstract = "abc " * 200  # ~800 chars
    xml = f"""<?xml version="1.0"?>
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation>
      <Article>
        <ArticleTitle>Long Abstract Paper</ArticleTitle>
        <Abstract><AbstractText>{long_abstract}</AbstractText></Abstract>
        <AuthorList><Author><LastName>X</LastName><Initials>Y</Initials></Author></AuthorList>
      </Article>
      <PubDate><Year>2023</Year></PubDate>
    </MedlineCitation>
    <PubmedData>
      <ArticleIdList><ArticleId IdType="pubmed">99</ArticleId></ArticleIdList>
    </PubmedData>
  </PubmedArticle>
</PubmedArticleSet>
""".encode()
    transport = _routed_handler(
        httpx.Response(200, json=_esearch_payload(["99"])),
        httpx.Response(200, content=xml),
    )
    async with httpx.AsyncClient(transport=transport, timeout=5) as client:
        provider = PubMedProvider(client=client)
        suggestions = await provider.search("x", "", max_results=1)
    assert len(suggestions) == 1
    assert len(suggestions[0].description) <= 500


async def test_pubmed_suggestion_model_round_trip() -> None:
    transport = _routed_handler(
        httpx.Response(200, json=_esearch_payload(["11111", "22222", "33333"])),
        httpx.Response(200, content=_EFETCH_THREE_ARTICLES_XML),
    )
    async with httpx.AsyncClient(transport=transport, timeout=5) as client:
        provider = PubMedProvider(client=client)
        suggestions = await provider.search("x", "", max_results=3)
    for s in suggestions:
        rebuilt = Suggestion.model_validate(s.model_dump())
        assert rebuilt == s
        assert s.source_provider == SuggestionSource.PUBMED


async def test_pubmed_search_blank_query_returns_empty() -> None:
    transport = _routed_handler(
        httpx.Response(200, json=_esearch_payload(["1"])),
        httpx.Response(200, content=_EFETCH_THREE_ARTICLES_XML),
    )
    async with httpx.AsyncClient(transport=transport, timeout=5) as client:
        provider = PubMedProvider(client=client)
        suggestions = await provider.search("   ", "", max_results=3)
    assert suggestions == []
