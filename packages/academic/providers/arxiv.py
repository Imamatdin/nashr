"""arXiv search client.

arXiv exposes a public Atom-XML query endpoint with no authentication, capped
informally at three requests per second. The response is parsed with
:mod:`feedparser`, which already handles the namespacing for arXiv-specific
extensions (``arxiv:doi``, ``arxiv:primary_category``).

arXiv has no citation-count concept on the search endpoint, so
``citation_count`` is always ``None`` from this provider; the federated
search service can still rank papers from other providers above arXiv ones
when both surface the same DOI.

Reference: https://info.arxiv.org/help/api/user-manual.html
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import feedparser  # type: ignore[import-untyped]
import httpx

from packages.academic.providers._json_utils import as_dict, as_list
from packages.core.enums import AcademicAPI
from packages.core.models.academic import AcademicPaper

logger = logging.getLogger(__name__)


_MAX_TITLE_LENGTH: int = 500
_MAX_ABSTRACT_LENGTH: int = 5000
_MAX_AUTHORS: int = 20


class ArxivProvider:
    """Async wrapper around the arXiv Atom search endpoint."""

    BASE_URL: str = "https://export.arxiv.org/api/query"

    async def search(
        self, client: httpx.AsyncClient, query: str, limit: int
    ) -> list[AcademicPaper]:
        """Return up to ``limit`` arXiv preprints matching ``query``."""

        params = {
            "search_query": f"all:{query}",
            "start": "0",
            "max_results": str(limit),
            "sortBy": "relevance",
            "sortOrder": "descending",
        }
        try:
            response = await client.get(self.BASE_URL, params=params)
        except httpx.HTTPError as exc:
            logger.warning("arxiv_request_failed", extra={"error": str(exc), "query": query})
            return []

        if response.status_code != 200:
            logger.warning(
                "arxiv_bad_status",
                extra={"status": response.status_code, "query": query},
            )
            return []

        try:
            parsed = await asyncio.to_thread(feedparser.parse, response.content)  # type: ignore[reportUnknownArgumentType, reportUnknownMemberType]
        except Exception as exc:
            logger.warning("arxiv_parse_failed", extra={"error": str(exc), "query": query})
            return []

        entries = as_list(getattr(parsed, "entries", None))
        if entries is None:
            return []

        papers: list[AcademicPaper] = []
        for entry in entries:
            paper = _parse_entry(entry)
            if paper is not None:
                papers.append(paper)
        return papers


def _parse_entry(entry: Any) -> AcademicPaper | None:
    """Parse one ``feedparser`` entry into an :class:`AcademicPaper`."""

    title_raw = getattr(entry, "title", None)
    if not isinstance(title_raw, str) or not title_raw.strip():
        return None
    title = " ".join(title_raw.split())[:_MAX_TITLE_LENGTH]

    entry_id = getattr(entry, "id", None)
    if not isinstance(entry_id, str) or not entry_id:
        return None

    authors: list[str] = []
    authors_raw = as_list(getattr(entry, "authors", None))
    if authors_raw is not None:
        for author in authors_raw[:_MAX_AUTHORS]:
            author_dict = as_dict(author)
            if author_dict is None:
                continue
            name = author_dict.get("name")
            if isinstance(name, str) and name.strip():
                authors.append(name.strip())

    year: int | None = None
    published = getattr(entry, "published", None)
    if isinstance(published, str) and len(published) >= 4 and published[:4].isdigit():
        year_int = int(published[:4])
        if 1500 <= year_int <= 2100:
            year = year_int

    summary = getattr(entry, "summary", None)
    abstract: str | None = None
    if isinstance(summary, str) and summary.strip():
        abstract = " ".join(summary.split())[:_MAX_ABSTRACT_LENGTH]

    doi: str | None = None
    doi_raw = getattr(entry, "arxiv_doi", None)
    if isinstance(doi_raw, str) and doi_raw.strip():
        doi = doi_raw.strip()[:200]

    pdf_url: str | None = None
    links = as_list(getattr(entry, "links", None))
    if links is not None:
        for link in links:
            link_dict = as_dict(link)
            if link_dict is None:
                continue
            link_type = link_dict.get("type")
            href = link_dict.get("href")
            if link_type == "application/pdf" and isinstance(href, str) and href:
                pdf_url = href[:1000]
                break

    return AcademicPaper(
        title=title,
        authors=authors,
        year=year,
        abstract=abstract,
        doi=doi,
        citation_count=None,
        pdf_url=pdf_url,
        source_api=AcademicAPI.ARXIV,
        external_id=entry_id[:500],
        journal=None,
    )
