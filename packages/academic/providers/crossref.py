"""CrossRef API client.

CrossRef is the authoritative DOI registrar; it serves two roles for Nashr:

1. ``search`` — generic bibliographic search used as a fourth corpus in the
   federated academic search, mostly to backfill journal/publisher metadata
   that the other three APIs don't always carry.
2. ``resolve_doi`` — lookup of a single DOI to full citation metadata, used
   when a PDF's metadata exposes a DOI and we want to format a perfect
   bibliography entry without prompting the user.

Reference: https://api.crossref.org/swagger-ui/index.html
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from packages.academic.providers._json_utils import as_dict, as_list
from packages.core.enums import AcademicAPI
from packages.core.models.academic import AcademicPaper, DOIMetadata

logger = logging.getLogger(__name__)


_MAX_TITLE_LENGTH: int = 500
_MAX_AUTHORS_RESOLVE: int = 50
_MAX_AUTHORS_SEARCH: int = 20
_SEARCH_FIELDS: str = (
    "DOI,title,author,published-print,published-online,issued,"
    "container-title,volume,issue,page,publisher,type,URL,abstract"
)


class CrossRefProvider:
    """Async wrapper for CrossRef ``/works`` and ``/works/{doi}`` endpoints."""

    BASE_URL: str = "https://api.crossref.org/works"

    async def search(
        self, client: httpx.AsyncClient, query: str, limit: int
    ) -> list[AcademicPaper]:
        """Return up to ``limit`` works matching ``query``."""

        params = {
            "query.bibliographic": query,
            "rows": str(limit),
            "select": _SEARCH_FIELDS,
        }
        try:
            response = await client.get(self.BASE_URL, params=params)
        except httpx.HTTPError as exc:
            logger.warning(
                "crossref_request_failed",
                extra={"error": str(exc), "query": query},
            )
            return []

        if response.status_code != 200:
            logger.warning(
                "crossref_bad_status",
                extra={"status": response.status_code, "query": query},
            )
            return []

        try:
            raw_payload = response.json()
        except ValueError as exc:
            logger.warning("crossref_bad_json", extra={"error": str(exc), "query": query})
            return []

        payload = as_dict(raw_payload)
        if payload is None:
            return []
        message = as_dict(payload.get("message"))
        if message is None:
            return []
        items = as_list(message.get("items"))
        if items is None:
            return []

        papers: list[AcademicPaper] = []
        for raw in items:
            item_dict = as_dict(raw)
            if item_dict is None:
                continue
            paper = _parse_search_item(item_dict)
            if paper is not None:
                papers.append(paper)
        return papers

    async def resolve_doi(self, client: httpx.AsyncClient, doi: str) -> DOIMetadata | None:
        """Resolve ``doi`` to full citation metadata; return ``None`` if not found.

        ``doi`` is appended to the URL path as-is; CrossRef accepts the literal
        ``10.xxxx/yyyy`` form and the slashes do not need to be percent-encoded.
        404 responses (DOI not registered) collapse to ``None`` so callers can
        treat missing and ambiguous identically.
        """

        cleaned = doi.strip()
        if not cleaned:
            return None
        url = f"{self.BASE_URL}/{cleaned}"
        try:
            response = await client.get(url)
        except httpx.HTTPError as exc:
            logger.warning("crossref_resolve_failed", extra={"error": str(exc), "doi": cleaned})
            return None

        if response.status_code == 404:
            return None
        if response.status_code != 200:
            logger.warning(
                "crossref_resolve_bad_status",
                extra={"status": response.status_code, "doi": cleaned},
            )
            return None

        try:
            raw_payload = response.json()
        except ValueError as exc:
            logger.warning("crossref_resolve_bad_json", extra={"error": str(exc), "doi": cleaned})
            return None

        payload = as_dict(raw_payload)
        if payload is None:
            return None
        message = as_dict(payload.get("message"))
        if message is None:
            return None
        return _parse_resolve_message(cleaned, message)


def _first_string(value: object) -> str | None:
    """Return the first non-empty string from a list-of-strings field, else None."""

    items = as_list(value)
    if items is not None:
        for entry in items:
            if isinstance(entry, str) and entry.strip():
                return entry.strip()
    elif isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _extract_year(message: dict[str, Any]) -> int | None:
    """Extract a publication year, preferring print, then online, then issued."""

    for key in ("published-print", "published-online", "issued"):
        block = as_dict(message.get(key))
        if block is None:
            continue
        date_parts = as_list(block.get("date-parts"))
        if date_parts is None or not date_parts:
            continue
        first = as_list(date_parts[0])
        if first is None or not first:
            continue
        candidate = first[0]
        if isinstance(candidate, int) and 1500 <= candidate <= 2100:
            return candidate
    return None


def _format_authors(raw: object, max_count: int) -> list[str]:
    """Format CrossRef author records as ``"Family, Given"`` strings."""

    entries = as_list(raw)
    if entries is None:
        return []
    out: list[str] = []
    for entry in entries[:max_count]:
        entry_dict = as_dict(entry)
        if entry_dict is None:
            continue
        family = entry_dict.get("family")
        given = entry_dict.get("given")
        if isinstance(family, str) and family.strip():
            if isinstance(given, str) and given.strip():
                out.append(f"{family.strip()}, {given.strip()}")
            else:
                out.append(family.strip())
        elif isinstance(given, str) and given.strip():
            out.append(given.strip())
        else:
            name = entry_dict.get("name")
            if isinstance(name, str) and name.strip():
                out.append(name.strip())
    return out


def _parse_search_item(item: dict[str, Any]) -> AcademicPaper | None:
    """Parse one CrossRef search-result item into an :class:`AcademicPaper`."""

    title = _first_string(item.get("title"))
    if title is None:
        return None
    title = title[:_MAX_TITLE_LENGTH]

    doi_raw = item.get("DOI")
    if not isinstance(doi_raw, str) or not doi_raw.strip():
        return None
    doi = doi_raw.strip()[:200]

    authors = _format_authors(item.get("author"), _MAX_AUTHORS_SEARCH)
    year = _extract_year(item)
    journal = _first_string(item.get("container-title"))
    if journal is not None:
        journal = journal[:500]

    return AcademicPaper(
        title=title,
        authors=authors,
        year=year,
        abstract=None,
        doi=doi,
        citation_count=None,
        pdf_url=None,
        source_api=AcademicAPI.CROSSREF,
        external_id=doi,
        journal=journal,
    )


def _parse_resolve_message(doi: str, message: dict[str, Any]) -> DOIMetadata | None:
    """Parse the ``message`` block of a single-DOI CrossRef response."""

    title = _first_string(message.get("title"))
    if title is None:
        return None
    title = title[:_MAX_TITLE_LENGTH]

    authors = _format_authors(message.get("author"), _MAX_AUTHORS_RESOLVE)
    year = _extract_year(message)

    journal = _first_string(message.get("container-title"))
    if journal is not None:
        journal = journal[:500]

    volume_raw = message.get("volume")
    volume = volume_raw.strip()[:50] if isinstance(volume_raw, str) and volume_raw.strip() else None

    issue_raw = message.get("issue")
    issue = issue_raw.strip()[:50] if isinstance(issue_raw, str) and issue_raw.strip() else None

    page_raw = message.get("page")
    pages = page_raw.strip()[:50] if isinstance(page_raw, str) and page_raw.strip() else None

    publisher_raw = message.get("publisher")
    publisher = (
        publisher_raw.strip()[:300]
        if isinstance(publisher_raw, str) and publisher_raw.strip()
        else None
    )

    type_raw = message.get("type")
    doc_type = type_raw.strip()[:100] if isinstance(type_raw, str) and type_raw.strip() else None

    url_raw = message.get("URL")
    url = url_raw.strip()[:1000] if isinstance(url_raw, str) and url_raw.strip() else None

    return DOIMetadata(
        doi=doi[:200],
        title=title,
        authors=authors,
        year=year,
        journal=journal,
        volume=volume,
        issue=issue,
        pages=pages,
        publisher=publisher,
        doc_type=doc_type,
        url=url,
    )
