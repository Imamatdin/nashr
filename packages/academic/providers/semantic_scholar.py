"""Semantic Scholar Graph API client.

Free, no auth required, ~214M papers indexed. Public rate limit is 100
requests per 5-minute window per IP. We use the ``/paper/search`` endpoint
because it returns the bibliographic plus open-access fields we need in one
shot; richer endpoints would cost extra calls without adding value to the
search-and-pick UX.

Reference: https://api.semanticscholar.org/api-docs/graph
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from packages.academic.providers._json_utils import as_dict, as_list
from packages.core.enums import AcademicAPI
from packages.core.models.academic import AcademicPaper

logger = logging.getLogger(__name__)


_MAX_TITLE_LENGTH: int = 500
_MAX_ABSTRACT_LENGTH: int = 5000
_MAX_AUTHORS: int = 20
_REQUESTED_FIELDS: str = "title,authors,year,abstract,citationCount,externalIds,openAccessPdf,venue"


class SemanticScholarProvider:
    """Thin async wrapper over the Semantic Scholar paper search endpoint."""

    BASE_URL: str = "https://api.semanticscholar.org/graph/v1/paper/search"

    async def search(
        self, client: httpx.AsyncClient, query: str, limit: int
    ) -> list[AcademicPaper]:
        """Return up to ``limit`` papers matching ``query``.

        Network and parsing failures degrade to an empty list rather than
        raising, so a single provider outage does not break the federated
        search. The error is logged with the upstream status / exception.
        """

        params = {"query": query, "limit": str(limit), "fields": _REQUESTED_FIELDS}
        try:
            response = await client.get(self.BASE_URL, params=params)
        except httpx.HTTPError as exc:
            logger.warning(
                "semantic_scholar_request_failed",
                extra={"error": str(exc), "query": query},
            )
            return []

        if response.status_code != 200:
            logger.warning(
                "semantic_scholar_bad_status",
                extra={"status": response.status_code, "query": query},
            )
            return []

        try:
            raw_payload = response.json()
        except ValueError as exc:
            logger.warning("semantic_scholar_bad_json", extra={"error": str(exc), "query": query})
            return []

        payload = as_dict(raw_payload)
        if payload is None:
            return []
        items = as_list(payload.get("data"))
        if items is None:
            return []

        papers: list[AcademicPaper] = []
        for raw in items:
            item_dict = as_dict(raw)
            if item_dict is None:
                continue
            paper = _parse_item(item_dict)
            if paper is not None:
                papers.append(paper)
        return papers


def _parse_item(item: dict[str, Any]) -> AcademicPaper | None:
    """Parse one item from the ``data`` array, returning None on missing core fields."""

    title_raw = item.get("title")
    if not isinstance(title_raw, str) or not title_raw.strip():
        return None
    title = title_raw.strip()[:_MAX_TITLE_LENGTH]

    paper_id = item.get("paperId")
    if not isinstance(paper_id, str) or not paper_id:
        return None

    authors: list[str] = []
    authors_raw = as_list(item.get("authors"))
    if authors_raw is not None:
        for entry in authors_raw[:_MAX_AUTHORS]:
            entry_dict = as_dict(entry)
            if entry_dict is None:
                continue
            name = entry_dict.get("name")
            if isinstance(name, str) and name.strip():
                authors.append(name.strip())

    year_raw = item.get("year")
    year = int(year_raw) if isinstance(year_raw, int) and 1500 <= year_raw <= 2100 else None

    abstract_raw = item.get("abstract")
    abstract: str | None = None
    if isinstance(abstract_raw, str) and abstract_raw.strip():
        abstract = abstract_raw.strip()[:_MAX_ABSTRACT_LENGTH]

    doi: str | None = None
    ext_ids = as_dict(item.get("externalIds"))
    if ext_ids is not None:
        doi_raw = ext_ids.get("DOI")
        if isinstance(doi_raw, str) and doi_raw.strip():
            doi = doi_raw.strip()[:200]

    citation_count_raw = item.get("citationCount")
    citation_count = (
        int(citation_count_raw)
        if isinstance(citation_count_raw, int) and citation_count_raw >= 0
        else None
    )

    pdf_url: str | None = None
    oa_dict = as_dict(item.get("openAccessPdf"))
    if oa_dict is not None:
        url_raw = oa_dict.get("url")
        if isinstance(url_raw, str) and url_raw.strip():
            pdf_url = url_raw.strip()[:1000]

    journal_raw = item.get("venue")
    journal: str | None = None
    if isinstance(journal_raw, str) and journal_raw.strip():
        journal = journal_raw.strip()[:500]

    return AcademicPaper(
        title=title,
        authors=authors,
        year=year,
        abstract=abstract,
        doi=doi,
        citation_count=citation_count,
        pdf_url=pdf_url,
        source_api=AcademicAPI.SEMANTIC_SCHOLAR,
        external_id=paper_id[:500],
        journal=journal,
    )
