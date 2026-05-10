"""OpenAlex API client.

OpenAlex is the open replacement for Microsoft Academic Graph: ~200M works,
free, no auth, generous rate limits when a contact email is sent in the
``User-Agent`` (the "polite pool"). We use that header so usage gets pooled
deterministically rather than tossed into the lower-priority anonymous queue.

The trickiest piece is the abstract: OpenAlex stores it as an inverted index
(``{word: [pos1, pos2, ...]}``) for licensing reasons. ``_reconstruct_abstract``
flattens that back into prose. If the field is missing, we leave the abstract
``None`` rather than synthesising one — it would be a minor lie that compounds.

Reference: https://docs.openalex.org/
"""

from __future__ import annotations

import logging
from typing import Any, cast

import httpx

from packages.academic.providers._json_utils import as_dict, as_list
from packages.core.enums import AcademicAPI
from packages.core.models.academic import AcademicPaper

logger = logging.getLogger(__name__)


_MAX_TITLE_LENGTH: int = 500
_MAX_ABSTRACT_LENGTH: int = 5000
_MAX_AUTHORS_RETURNED: int = 5
_DOI_PREFIX: str = "https://doi.org/"
_USER_AGENT: str = "Nashr/1.0 (mailto:admin@nashr.uz)"
_REQUESTED_FIELDS: str = (
    "id,title,authorships,publication_year,doi,cited_by_count,"
    "open_access,abstract_inverted_index,primary_location"
)


class OpenAlexProvider:
    """Async wrapper for the OpenAlex ``/works`` search endpoint."""

    BASE_URL: str = "https://api.openalex.org/works"

    async def search(
        self, client: httpx.AsyncClient, query: str, limit: int
    ) -> list[AcademicPaper]:
        """Return up to ``limit`` works matching ``query``."""

        params = {
            "search": query,
            "per_page": str(limit),
            "sort": "relevance_score:desc",
            "select": _REQUESTED_FIELDS,
        }
        headers = {"User-Agent": _USER_AGENT}
        try:
            response = await client.get(self.BASE_URL, params=params, headers=headers)
        except httpx.HTTPError as exc:
            logger.warning(
                "openalex_request_failed",
                extra={"error": str(exc), "query": query},
            )
            return []

        if response.status_code != 200:
            logger.warning(
                "openalex_bad_status",
                extra={"status": response.status_code, "query": query},
            )
            return []

        try:
            raw_payload = response.json()
        except ValueError as exc:
            logger.warning("openalex_bad_json", extra={"error": str(exc), "query": query})
            return []

        payload = as_dict(raw_payload)
        if payload is None:
            return []
        items = as_list(payload.get("results"))
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
    """Parse one OpenAlex work record into an :class:`AcademicPaper`."""

    title_raw = item.get("title")
    if not isinstance(title_raw, str) or not title_raw.strip():
        return None
    title = title_raw.strip()[:_MAX_TITLE_LENGTH]

    work_id = item.get("id")
    if not isinstance(work_id, str) or not work_id:
        return None

    authors: list[str] = []
    authorships = as_list(item.get("authorships"))
    if authorships is not None:
        for entry in authorships[:_MAX_AUTHORS_RETURNED]:
            entry_dict = as_dict(entry)
            if entry_dict is None:
                continue
            author = as_dict(entry_dict.get("author"))
            if author is None:
                continue
            display_name = author.get("display_name")
            if isinstance(display_name, str) and display_name.strip():
                authors.append(display_name.strip())

    year_raw = item.get("publication_year")
    year = int(year_raw) if isinstance(year_raw, int) and 1500 <= year_raw <= 2100 else None

    doi: str | None = None
    doi_raw = item.get("doi")
    if isinstance(doi_raw, str) and doi_raw.strip():
        normalised = doi_raw.strip()
        if normalised.startswith(_DOI_PREFIX):
            normalised = normalised[len(_DOI_PREFIX) :]
        doi = normalised[:200]

    citation_count_raw = item.get("cited_by_count")
    citation_count = (
        int(citation_count_raw)
        if isinstance(citation_count_raw, int) and citation_count_raw >= 0
        else None
    )

    pdf_url: str | None = None
    open_access = as_dict(item.get("open_access"))
    if open_access is not None:
        oa_url = open_access.get("oa_url")
        if isinstance(oa_url, str) and oa_url.strip():
            pdf_url = oa_url.strip()[:1000]

    abstract = _reconstruct_abstract(item.get("abstract_inverted_index"))

    journal: str | None = None
    primary_location = as_dict(item.get("primary_location"))
    if primary_location is not None:
        source = as_dict(primary_location.get("source"))
        if source is not None:
            journal_raw = source.get("display_name")
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
        source_api=AcademicAPI.OPENALEX,
        external_id=work_id[:500],
        journal=journal,
    )


def _reconstruct_abstract(inverted: object) -> str | None:
    """Rebuild the abstract from OpenAlex's word→positions inverted index.

    Returns ``None`` if the field is missing, malformed, or yields no words —
    OpenAlex omits the abstract on works whose publishers disallow caching it,
    and we propagate that ``None`` rather than fabricate placeholder text.
    """

    if not isinstance(inverted, dict):
        return None
    pairs: list[tuple[int, str]] = []
    items: dict[Any, Any] = cast(dict[Any, Any], inverted)
    for word, positions in items.items():
        if not isinstance(word, str):
            continue
        positions_list = as_list(positions)
        if positions_list is None:
            continue
        for pos in positions_list:
            if isinstance(pos, int) and pos >= 0:
                pairs.append((pos, word))
    if not pairs:
        return None
    pairs.sort(key=lambda p: p[0])
    text = " ".join(word for _, word in pairs)
    return text[:_MAX_ABSTRACT_LENGTH] if text else None
