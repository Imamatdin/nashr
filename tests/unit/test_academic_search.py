"""Behaviour tests for the academic search providers, search service, and DOI resolver.

Every HTTP call is served by an :class:`httpx.MockTransport` so the tests are
fully offline; only the providers' parsing logic and the federated search /
dedup / sort pipeline are exercised. Live-API smoke tests live in
``tests/integration/test_academic_search.py`` behind an env-var gate.

Each test asserts a concrete behaviour the rest of the system relies on
(parsed shape, error tolerance, dedup choice, ranking key) rather than mere
non-emptiness.
"""

from __future__ import annotations

from typing import Any

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
from packages.core.models.academic import (
    AcademicPaper,
    AcademicSearchResult,
    DOIMetadata,
)


def _client(handler: httpx.MockTransport) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=handler, timeout=5)


def _ok_json(payload: Any) -> httpx.Response:
    return httpx.Response(200, json=payload)


# ---------------------------------------------------------------------------
# Semantic Scholar
# ---------------------------------------------------------------------------

_SEMANTIC_SCHOLAR_PAYLOAD: dict[str, Any] = {
    "total": 2,
    "data": [
        {
            "paperId": "abc123",
            "title": "Attention Is All You Need",
            "authors": [{"name": "Ashish Vaswani"}, {"name": "Noam Shazeer"}],
            "year": 2017,
            "abstract": "We propose the Transformer architecture.",
            "citationCount": 95000,
            "externalIds": {"DOI": "10.48550/arXiv.1706.03762"},
            "openAccessPdf": {"url": "https://example.org/transformer.pdf"},
            "venue": "NeurIPS",
        },
        {
            "paperId": "def456",
            "title": "BERT",
            "authors": [{"name": "Jacob Devlin"}],
            "year": 2018,
            "abstract": None,
            "citationCount": 80000,
            "externalIds": {},
            "openAccessPdf": None,
            "venue": "NAACL",
        },
    ],
}


async def test_semantic_scholar_parses_response() -> None:
    captured: dict[str, httpx.Request] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return _ok_json(_SEMANTIC_SCHOLAR_PAYLOAD)

    transport = httpx.MockTransport(handler)
    async with _client(transport) as client:
        provider = SemanticScholarProvider()
        papers = await provider.search(client, "transformers", limit=5)

    assert len(papers) == 2
    first = papers[0]
    assert first.title == "Attention Is All You Need"
    assert first.authors == ["Ashish Vaswani", "Noam Shazeer"]
    assert first.year == 2017
    assert first.doi == "10.48550/arXiv.1706.03762"
    assert first.pdf_url == "https://example.org/transformer.pdf"
    assert first.citation_count == 95000
    assert first.source_api == AcademicAPI.SEMANTIC_SCHOLAR
    assert first.external_id == "abc123"
    assert first.journal == "NeurIPS"
    assert papers[1].doi is None
    assert papers[1].abstract is None
    assert papers[1].pdf_url is None
    assert "query=transformers" in str(captured["request"].url)
    assert "limit=5" in str(captured["request"].url)


async def test_semantic_scholar_handles_error() -> None:
    transport = httpx.MockTransport(lambda _r: httpx.Response(500))
    async with _client(transport) as client:
        papers = await SemanticScholarProvider().search(client, "x", limit=3)
    assert papers == []


async def test_semantic_scholar_handles_empty_results() -> None:
    transport = httpx.MockTransport(lambda _r: _ok_json({"total": 0, "data": []}))
    async with _client(transport) as client:
        papers = await SemanticScholarProvider().search(client, "x", limit=3)
    assert papers == []


async def test_semantic_scholar_handles_network_error() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline")

    transport = httpx.MockTransport(handler)
    async with _client(transport) as client:
        papers = await SemanticScholarProvider().search(client, "x", limit=3)
    assert papers == []


# ---------------------------------------------------------------------------
# arXiv
# ---------------------------------------------------------------------------

_ARXIV_XML: bytes = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2301.00001v1</id>
    <title>Quantum Foo
    Bar</title>
    <summary>A study of foo and bar.
    Multiple lines.</summary>
    <published>2023-01-15T00:00:00Z</published>
    <author><name>Alice Smith</name></author>
    <author><name>Bob Jones</name></author>
    <arxiv:doi xmlns:arxiv="http://arxiv.org/schemas/atom">10.1000/xyz123</arxiv:doi>
    <link rel="alternate" type="text/html" href="http://arxiv.org/abs/2301.00001v1"/>
    <link title="pdf" rel="related" type="application/pdf" href="http://arxiv.org/pdf/2301.00001v1.pdf"/>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2301.00002v1</id>
    <title>Second Paper</title>
    <summary>Just a summary.</summary>
    <published>2024-06-01T00:00:00Z</published>
    <author><name>Carol Davis</name></author>
    <link rel="alternate" type="text/html" href="http://arxiv.org/abs/2301.00002v1"/>
  </entry>
</feed>
"""


async def test_arxiv_parses_response() -> None:
    transport = httpx.MockTransport(lambda _r: httpx.Response(200, content=_ARXIV_XML))
    async with _client(transport) as client:
        papers = await ArxivProvider().search(client, "quantum", limit=10)

    assert len(papers) == 2
    first = papers[0]
    assert first.title == "Quantum Foo Bar"
    assert first.authors == ["Alice Smith", "Bob Jones"]
    assert first.year == 2023
    assert first.abstract == "A study of foo and bar. Multiple lines."
    assert first.doi == "10.1000/xyz123"
    assert first.pdf_url == "http://arxiv.org/pdf/2301.00001v1.pdf"
    assert first.citation_count is None
    assert first.source_api == AcademicAPI.ARXIV
    assert first.external_id == "http://arxiv.org/abs/2301.00001v1"
    assert papers[1].doi is None
    assert papers[1].pdf_url is None
    assert papers[1].year == 2024


async def test_arxiv_handles_error() -> None:
    transport = httpx.MockTransport(lambda _r: httpx.Response(500))
    async with _client(transport) as client:
        papers = await ArxivProvider().search(client, "x", limit=3)
    assert papers == []


async def test_arxiv_handles_empty_feed() -> None:
    empty = b"<?xml version='1.0'?><feed xmlns='http://www.w3.org/2005/Atom'></feed>"
    transport = httpx.MockTransport(lambda _r: httpx.Response(200, content=empty))
    async with _client(transport) as client:
        papers = await ArxivProvider().search(client, "x", limit=3)
    assert papers == []


# ---------------------------------------------------------------------------
# OpenAlex
# ---------------------------------------------------------------------------

_OPENALEX_PAYLOAD: dict[str, Any] = {
    "meta": {"count": 2},
    "results": [
        {
            "id": "https://openalex.org/W123",
            "title": "Renewable Energy in Central Asia",
            "authorships": [
                {"author": {"display_name": "Aziz Karimov"}},
                {"author": {"display_name": "Dilnoza Yusupova"}},
            ],
            "publication_year": 2022,
            "doi": "https://doi.org/10.1234/renewable.2022.001",
            "cited_by_count": 42,
            "open_access": {"oa_url": "https://example.org/renewable.pdf"},
            "abstract_inverted_index": {
                "Renewable": [0],
                "energy": [1, 5],
                "in": [2],
                "Uzbekistan": [3],
                "uses": [4],
                "solar": [6],
            },
            "primary_location": {"source": {"display_name": "Energy Policy"}},
        },
        {
            "id": "https://openalex.org/W456",
            "title": "Second Work",
            "authorships": [
                {"author": {"display_name": None}},
                {"author": None},
                {"author": {"display_name": "Real Author"}},
            ],
            "publication_year": 2020,
            "doi": None,
            "cited_by_count": 0,
            "open_access": {"oa_url": None},
            "abstract_inverted_index": None,
            "primary_location": None,
        },
    ],
}


async def test_openalex_parses_response() -> None:
    captured: dict[str, httpx.Request] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return _ok_json(_OPENALEX_PAYLOAD)

    transport = httpx.MockTransport(handler)
    async with _client(transport) as client:
        papers = await OpenAlexProvider().search(client, "renewable", limit=5)

    assert len(papers) == 2
    first = papers[0]
    assert first.title == "Renewable Energy in Central Asia"
    assert first.authors == ["Aziz Karimov", "Dilnoza Yusupova"]
    assert first.doi == "10.1234/renewable.2022.001"
    assert first.year == 2022
    assert first.citation_count == 42
    assert first.pdf_url == "https://example.org/renewable.pdf"
    assert first.abstract == "Renewable energy in Uzbekistan uses energy solar"
    assert first.source_api == AcademicAPI.OPENALEX
    assert first.external_id == "https://openalex.org/W123"
    assert first.journal == "Energy Policy"
    second = papers[1]
    assert second.authors == ["Real Author"]
    assert second.doi is None
    assert second.abstract is None
    assert second.journal is None
    assert captured["request"].headers["user-agent"].startswith("Nashr/")


async def test_openalex_handles_null_abstract() -> None:
    payload = {
        "results": [
            {
                "id": "https://openalex.org/W999",
                "title": "Null Abstract Paper",
                "authorships": [],
                "publication_year": 2021,
                "doi": None,
                "cited_by_count": None,
                "open_access": None,
                "abstract_inverted_index": None,
                "primary_location": None,
            }
        ]
    }
    transport = httpx.MockTransport(lambda _r: _ok_json(payload))
    async with _client(transport) as client:
        papers = await OpenAlexProvider().search(client, "x", limit=1)
    assert len(papers) == 1
    assert papers[0].abstract is None
    assert papers[0].citation_count is None


async def test_openalex_handles_error() -> None:
    transport = httpx.MockTransport(lambda _r: httpx.Response(500))
    async with _client(transport) as client:
        papers = await OpenAlexProvider().search(client, "x", limit=3)
    assert papers == []


# ---------------------------------------------------------------------------
# CrossRef
# ---------------------------------------------------------------------------

_CROSSREF_SEARCH_PAYLOAD: dict[str, Any] = {
    "status": "ok",
    "message": {
        "items": [
            {
                "DOI": "10.1038/nature12373",
                "title": ["A Mind at Play"],
                "author": [
                    {"family": "Soni", "given": "Jimmy"},
                    {"family": "Goodman", "given": "Rob"},
                ],
                "published-print": {"date-parts": [[2017, 7, 18]]},
                "container-title": ["Nature"],
            },
            {
                "DOI": "10.0000/missing-title",
                "title": [],
                "author": [],
                "published-print": {"date-parts": [[2010]]},
                "container-title": ["Some Journal"],
            },
        ]
    },
}


async def test_crossref_search_parses_response() -> None:
    transport = httpx.MockTransport(lambda _r: _ok_json(_CROSSREF_SEARCH_PAYLOAD))
    async with _client(transport) as client:
        papers = await CrossRefProvider().search(client, "shannon", limit=10)

    # Second item lacks a title, so the parser drops it.
    assert len(papers) == 1
    paper = papers[0]
    assert paper.title == "A Mind at Play"
    assert paper.authors == ["Soni, Jimmy", "Goodman, Rob"]
    assert paper.year == 2017
    assert paper.doi == "10.1038/nature12373"
    assert paper.journal == "Nature"
    assert paper.source_api == AcademicAPI.CROSSREF
    assert paper.citation_count is None
    assert paper.pdf_url is None
    assert paper.external_id == paper.doi


_CROSSREF_RESOLVE_PAYLOAD: dict[str, Any] = {
    "status": "ok",
    "message": {
        "DOI": "10.1038/nature12373",
        "title": ["Quantum Computing in the NISQ Era and Beyond"],
        "author": [
            {"family": "Preskill", "given": "John"},
            {"family": "Doe", "given": "Jane"},
        ],
        "published-print": {"date-parts": [[2018, 8]]},
        "container-title": ["Quantum"],
        "volume": "2",
        "issue": "3",
        "page": "79-95",
        "publisher": "Verein zur Forderung",
        "type": "journal-article",
        "URL": "https://doi.org/10.1038/nature12373",
    },
}


async def test_crossref_resolve_doi_returns_metadata() -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        return _ok_json(_CROSSREF_RESOLVE_PAYLOAD)

    transport = httpx.MockTransport(handler)
    async with _client(transport) as client:
        meta = await CrossRefProvider().resolve_doi(client, "10.1038/nature12373")

    assert isinstance(meta, DOIMetadata)
    assert meta.doi == "10.1038/nature12373"
    assert meta.title == "Quantum Computing in the NISQ Era and Beyond"
    assert meta.authors == ["Preskill, John", "Doe, Jane"]
    assert meta.year == 2018
    assert meta.journal == "Quantum"
    assert meta.volume == "2"
    assert meta.issue == "3"
    assert meta.pages == "79-95"
    assert meta.publisher == "Verein zur Forderung"
    assert meta.doc_type == "journal-article"
    assert meta.url == "https://doi.org/10.1038/nature12373"
    assert captured["path"].endswith("/works/10.1038/nature12373")


async def test_crossref_resolve_doi_not_found() -> None:
    transport = httpx.MockTransport(lambda _r: httpx.Response(404))
    async with _client(transport) as client:
        meta = await CrossRefProvider().resolve_doi(client, "10.1234/missing")
    assert meta is None


async def test_crossref_resolve_doi_handles_missing_fields() -> None:
    payload = {
        "status": "ok",
        "message": {
            "DOI": "10.1234/sparse",
            "title": ["Only A Title"],
            # no authors, no year, no journal, no volume/issue/page
        },
    }
    transport = httpx.MockTransport(lambda _r: _ok_json(payload))
    async with _client(transport) as client:
        meta = await CrossRefProvider().resolve_doi(client, "10.1234/sparse")

    assert isinstance(meta, DOIMetadata)
    assert meta.title == "Only A Title"
    assert meta.authors == []
    assert meta.year is None
    assert meta.journal is None
    assert meta.volume is None
    assert meta.issue is None
    assert meta.pages is None
    assert meta.publisher is None
    assert meta.doc_type is None


async def test_crossref_resolve_doi_falls_back_to_published_online() -> None:
    payload = {
        "message": {
            "title": ["Online Only"],
            "published-online": {"date-parts": [[2021, 5, 4]]},
        }
    }
    transport = httpx.MockTransport(lambda _r: _ok_json(payload))
    async with _client(transport) as client:
        meta = await CrossRefProvider().resolve_doi(client, "10.x/online")
    assert meta is not None
    assert meta.year == 2021


# ---------------------------------------------------------------------------
# AcademicSearchService — federation, dedup, ranking
# ---------------------------------------------------------------------------


def _multi_handler(routes: dict[str, httpx.Response | Exception]) -> httpx.MockTransport:
    """Route by host substring → Response or Exception (raised on call)."""

    def handler(request: httpx.Request) -> httpx.Response:
        host = request.url.host
        for needle, response in routes.items():
            if needle in host:
                if isinstance(response, Exception):
                    raise response
                return response
        return httpx.Response(404)

    return httpx.MockTransport(handler)


_RICH_S2 = {
    "data": [
        {
            "paperId": "s2-1",
            "title": "Shared Paper",
            "authors": [{"name": "Author One"}],
            "year": 2020,
            "abstract": "Rich abstract from S2.",
            "citationCount": 500,
            "externalIds": {"DOI": "10.1/shared"},
            "openAccessPdf": {"url": "https://s2.example/paper.pdf"},
            "venue": "Conf",
        },
        {
            "paperId": "s2-2",
            "title": "S2 Only",
            "authors": [],
            "year": 2019,
            "abstract": "abc",
            "citationCount": 100,
            "externalIds": {"DOI": "10.1/s2only"},
            "openAccessPdf": None,
            "venue": None,
        },
    ]
}

_LEAN_OPENALEX = {
    "results": [
        {
            "id": "oa-1",
            "title": "Shared Paper",
            "authorships": [{"author": {"display_name": "Author One"}}],
            "publication_year": 2020,
            "doi": "https://doi.org/10.1/shared",  # same DOI, less metadata
            "cited_by_count": 0,
            "open_access": None,
            "abstract_inverted_index": None,
            "primary_location": None,
        }
    ]
}

_ARXIV_FEED = b"""<?xml version='1.0'?>
<feed xmlns='http://www.w3.org/2005/Atom'>
<entry>
  <id>http://arxiv.org/abs/9999.99999</id>
  <title>Arxiv Only Paper</title>
  <summary>Foo</summary>
  <published>2025-01-01T00:00:00Z</published>
  <author><name>Newcomer</name></author>
</entry>
</feed>
"""

_CROSSREF_EMPTY = {"message": {"items": []}}


async def test_search_service_deduplicates_by_doi() -> None:
    transport = _multi_handler(
        {
            "semanticscholar.org": _ok_json(_RICH_S2),
            "arxiv.org": httpx.Response(200, content=_ARXIV_FEED),
            "openalex.org": _ok_json(_LEAN_OPENALEX),
            "crossref.org": _ok_json(_CROSSREF_EMPTY),
        }
    )
    async with httpx.AsyncClient(transport=transport, timeout=5) as client:
        service = AcademicSearchService(client=client)
        result = await service.search("test query", max_results=10)

    dois = [p.doi for p in result.papers]
    assert dois.count("10.1/shared") == 1, "duplicate DOI not collapsed"
    shared = next(p for p in result.papers if p.doi == "10.1/shared")
    assert shared.source_api == AcademicAPI.SEMANTIC_SCHOLAR, "richer record should win"
    assert shared.abstract == "Rich abstract from S2."
    assert shared.pdf_url == "https://s2.example/paper.pdf"
    # arXiv-only paper has no DOI → should still appear
    assert any(p.title == "Arxiv Only Paper" for p in result.papers)


async def test_search_service_sorts_by_citation_count() -> None:
    s2_payload = {
        "data": [
            {
                "paperId": f"p{i}",
                "title": f"Paper {i}",
                "authors": [],
                "year": 2020,
                "abstract": "x",
                "citationCount": cites,
                "externalIds": {"DOI": f"10.x/{i}"},
                "openAccessPdf": None,
                "venue": None,
            }
            for i, cites in enumerate([10, 1000, 50])
        ]
    }
    transport = _multi_handler(
        {
            "semanticscholar.org": _ok_json(s2_payload),
            "arxiv.org": httpx.Response(200, content=b"<?xml version='1.0'?><feed/>"),
            "openalex.org": _ok_json({"results": []}),
            "crossref.org": _ok_json({"message": {"items": []}}),
        }
    )
    async with httpx.AsyncClient(transport=transport, timeout=5) as client:
        service = AcademicSearchService(client=client)
        result = await service.search("ranking", max_results=10)

    counts = [p.citation_count for p in result.papers]
    assert counts == [1000, 50, 10]


async def test_search_service_sorts_unknown_citations_last() -> None:
    s2_payload = {
        "data": [
            {
                "paperId": "with-cites",
                "title": "Has Cites",
                "authors": [],
                "year": 2020,
                "abstract": "x",
                "citationCount": 5,
                "externalIds": {"DOI": "10.x/known"},
                "openAccessPdf": None,
                "venue": None,
            },
        ]
    }
    arxiv_xml = b"""<?xml version='1.0'?>
<feed xmlns='http://www.w3.org/2005/Atom'>
<entry>
  <id>http://arxiv.org/abs/1</id>
  <title>No Cites</title>
  <summary>x</summary>
  <published>2024-01-01T00:00:00Z</published>
  <author><name>Foo</name></author>
</entry>
</feed>
"""
    transport = _multi_handler(
        {
            "semanticscholar.org": _ok_json(s2_payload),
            "arxiv.org": httpx.Response(200, content=arxiv_xml),
            "openalex.org": _ok_json({"results": []}),
            "crossref.org": _ok_json({"message": {"items": []}}),
        }
    )
    async with httpx.AsyncClient(transport=transport, timeout=5) as client:
        service = AcademicSearchService(client=client)
        result = await service.search("q", max_results=10)
    assert [p.title for p in result.papers] == ["Has Cites", "No Cites"]


async def test_search_service_handles_partial_failures() -> None:
    """Succeeding providers' papers flow through when others 500 / time out.

    Providers swallow their own HTTP/network errors (per the per-provider
    contract — see ``test_semantic_scholar_handles_error``), so we assert the
    *resilience* property here: the federated result is non-empty as long as
    one provider succeeded. The ``errors`` list is exercised separately in
    :func:`test_search_service_captures_unexpected_provider_exception`.
    """

    transport = _multi_handler(
        {
            "semanticscholar.org": _ok_json(_RICH_S2),
            "arxiv.org": httpx.ConnectError("arxiv down"),
            "openalex.org": httpx.Response(500),
            "crossref.org": _ok_json(_CROSSREF_EMPTY),
        }
    )
    async with httpx.AsyncClient(transport=transport, timeout=5) as client:
        service = AcademicSearchService(client=client)
        result = await service.search("partial", max_results=10)

    s2_titles = {p.title for p in result.papers if p.source_api == AcademicAPI.SEMANTIC_SCHOLAR}
    assert "Shared Paper" in s2_titles
    assert "S2 Only" in s2_titles


async def test_search_service_captures_unexpected_provider_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A provider that raises (programming bug, unexpected error) → entry in errors."""

    transport = _multi_handler(
        {
            "semanticscholar.org": _ok_json({"data": []}),
            "arxiv.org": httpx.Response(200, content=b"<?xml version='1.0'?><feed/>"),
            "openalex.org": _ok_json({"results": []}),
            "crossref.org": _ok_json({"message": {"items": []}}),
        }
    )

    async def _explode(*_a: Any, **_kw: Any) -> list[AcademicPaper]:
        raise RuntimeError("provider blew up")

    async with httpx.AsyncClient(transport=transport, timeout=5) as client:
        service = AcademicSearchService(client=client)
        monkeypatch.setattr(service._arxiv, "search", _explode)
        result = await service.search("explode", max_results=5)

    assert any("arxiv" in err and "RuntimeError" in err for err in result.errors)


async def test_search_service_respects_max_results() -> None:
    s2_payload = {
        "data": [
            {
                "paperId": f"p{i}",
                "title": f"Paper {i}",
                "authors": [],
                "year": 2020,
                "abstract": "x",
                "citationCount": 100 - i,
                "externalIds": {"DOI": f"10.x/{i}"},
                "openAccessPdf": None,
                "venue": None,
            }
            for i in range(20)
        ]
    }
    transport = _multi_handler(
        {
            "semanticscholar.org": _ok_json(s2_payload),
            "arxiv.org": httpx.Response(200, content=b"<?xml version='1.0'?><feed/>"),
            "openalex.org": _ok_json({"results": []}),
            "crossref.org": _ok_json({"message": {"items": []}}),
        }
    )
    async with httpx.AsyncClient(transport=transport, timeout=5) as client:
        service = AcademicSearchService(client=client)
        result = await service.search("cap", max_results=5)
    assert len(result.papers) == 5
    assert result.total_found == 20


async def test_search_service_records_timing() -> None:
    transport = _multi_handler(
        {
            "semanticscholar.org": _ok_json({"data": []}),
            "arxiv.org": httpx.Response(200, content=b"<?xml version='1.0'?><feed/>"),
            "openalex.org": _ok_json({"results": []}),
            "crossref.org": _ok_json({"message": {"items": []}}),
        }
    )
    async with httpx.AsyncClient(transport=transport, timeout=5) as client:
        service = AcademicSearchService(client=client)
        result = await service.search("t", max_results=3)
    assert result.search_time_ms >= 0
    assert isinstance(result, AcademicSearchResult)


async def test_search_service_rejects_blank_query() -> None:
    transport = _multi_handler({})
    async with httpx.AsyncClient(transport=transport, timeout=5) as client:
        service = AcademicSearchService(client=client)
        result = await service.search("   ", max_results=3)
    assert result.papers == []
    assert result.total_found == 0


async def test_search_service_keeps_no_doi_papers_separate() -> None:
    arxiv_xml = b"""<?xml version='1.0'?>
<feed xmlns='http://www.w3.org/2005/Atom'>
<entry>
  <id>http://arxiv.org/abs/A</id>
  <title>NoDOI A</title>
  <summary>x</summary>
  <published>2024-01-01T00:00:00Z</published>
  <author><name>Foo</name></author>
</entry>
<entry>
  <id>http://arxiv.org/abs/B</id>
  <title>NoDOI B</title>
  <summary>y</summary>
  <published>2024-01-01T00:00:00Z</published>
  <author><name>Bar</name></author>
</entry>
</feed>
"""
    transport = _multi_handler(
        {
            "semanticscholar.org": _ok_json({"data": []}),
            "arxiv.org": httpx.Response(200, content=arxiv_xml),
            "openalex.org": _ok_json({"results": []}),
            "crossref.org": _ok_json({"message": {"items": []}}),
        }
    )
    async with httpx.AsyncClient(transport=transport, timeout=5) as client:
        service = AcademicSearchService(client=client)
        result = await service.search("nodoi", max_results=10)
    titles = sorted(p.title for p in result.papers)
    assert titles == ["NoDOI A", "NoDOI B"]


# ---------------------------------------------------------------------------
# DOIResolver
# ---------------------------------------------------------------------------


async def test_doi_resolver_single() -> None:
    transport = httpx.MockTransport(lambda _r: _ok_json(_CROSSREF_RESOLVE_PAYLOAD))
    async with httpx.AsyncClient(transport=transport, timeout=5) as client:
        resolver = DOIResolver(client=client)
        meta = await resolver.resolve("10.1038/nature12373")
    assert meta is not None
    assert meta.title == "Quantum Computing in the NISQ Era and Beyond"


async def test_doi_resolver_batch() -> None:
    call_log: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        call_log.append(path)
        if path.endswith("/missing"):
            return httpx.Response(404)
        return _ok_json(_CROSSREF_RESOLVE_PAYLOAD)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, timeout=5) as client:
        resolver = DOIResolver(client=client)
        result = await resolver.resolve_batch(["10.1/a", "10.1/b", "missing", "10.1/a"])

    assert set(result.keys()) == {"10.1/a", "10.1/b", "missing"}
    assert result["missing"] is None
    assert isinstance(result["10.1/a"], DOIMetadata)
    assert isinstance(result["10.1/b"], DOIMetadata)
    # Duplicate "10.1/a" must collapse — only 3 calls
    assert len(call_log) == 3


# ---------------------------------------------------------------------------
# Model round-trip (per core-models.md rule)
# ---------------------------------------------------------------------------


def test_academic_paper_round_trip() -> None:
    paper = AcademicPaper(
        title="X",
        authors=["A"],
        year=2020,
        abstract="abs",
        doi="10.x/y",
        citation_count=3,
        pdf_url="http://x",
        source_api=AcademicAPI.OPENALEX,
        external_id="ext",
        journal="Journal",
    )
    rebuilt = AcademicPaper.model_validate(paper.model_dump())
    assert rebuilt == paper


def test_academic_search_result_round_trip() -> None:
    result = AcademicSearchResult(
        query="q",
        papers=[],
        total_found=0,
        errors=["e"],
        search_time_ms=12,
    )
    rebuilt = AcademicSearchResult.model_validate(result.model_dump())
    assert rebuilt == result


def test_doi_metadata_round_trip() -> None:
    meta = DOIMetadata(
        doi="10.x/y",
        title="T",
        authors=["A"],
        year=2020,
        journal="J",
        volume="1",
        issue="2",
        pages="3-4",
        publisher="P",
        doc_type="journal-article",
        url="http://x",
    )
    rebuilt = DOIMetadata.model_validate(meta.model_dump())
    assert rebuilt == meta


def test_academic_paper_rejects_extra_fields() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        AcademicPaper.model_validate(
            {
                "title": "X",
                "source_api": AcademicAPI.ARXIV,
                "external_id": "id",
                "unknown_field": True,
            }
        )
