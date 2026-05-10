"""NCBI PubMed/PMC search for medical & health-science suggestions.

The provider performs a two-step E-utilities call: ``esearch`` to map the
query to PubMed IDs (PMIDs), then ``efetch`` to pull the article XML for
those IDs in a single batch. PubMed ``efetch`` always returns XML — there
is no JSON-mode equivalent for this resource — so parsing uses the stdlib
:mod:`xml.etree.ElementTree`.

Rate limits: 3 requests per second without an API key, 10 with. We honour
the unauthenticated cap by sleeping ~0.35s between the two requests of a
single search; the orchestrator rate-limits across searches.

References
----------
* E-utilities help:   https://www.ncbi.nlm.nih.gov/books/NBK25501/
* esearch:            https://www.ncbi.nlm.nih.gov/books/NBK25499/#chapter4.ESearch
* efetch (PubMed):    https://www.ncbi.nlm.nih.gov/books/NBK25499/#chapter4.EFetch
"""

from __future__ import annotations

import asyncio
import logging
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from typing import Any, ClassVar

import httpx

from packages.academic.providers._json_utils import as_dict, as_list
from packages.core.models.suggestion import (
    AcademicDomain,
    Suggestion,
    SuggestionSource,
)

logger = logging.getLogger(__name__)


_ESEARCH_URL: str = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
_EFETCH_URL: str = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
_REQUEST_TIMEOUT: float = 10.0
_RATE_LIMIT_SLEEP_S: float = 0.35
_MAX_DESCRIPTION_LEN: int = 500
_RECENT_YEAR_BOOST_THRESHOLD_YEARS: int = 5


class PubMedProvider:
    """Async client over the NCBI E-utilities ``esearch``/``efetch`` endpoints."""

    provider_name: str = "PubMed"
    supported_domains: ClassVar[list[AcademicDomain]] = [AcademicDomain.MEDICAL]

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._http = client if client is not None else httpx.AsyncClient(timeout=_REQUEST_TIMEOUT)
        self._owns_client = client is None

    async def search(
        self,
        query: str,
        section_context: str,
        max_results: int = 5,
    ) -> list[Suggestion]:
        """Return up to ``max_results`` PubMed-ranked articles as suggestions."""

        cleaned = query.strip()
        if not cleaned:
            return []

        pmids = await self._esearch(cleaned, max_results)
        if not pmids:
            return []
        await asyncio.sleep(_RATE_LIMIT_SLEEP_S)
        xml_bytes = await self._efetch(pmids)
        if xml_bytes is None:
            return []

        articles = _parse_efetch_xml(xml_bytes)
        suggestions: list[Suggestion] = []
        for index, article in enumerate(articles):
            score = _score_relevance(article, index, len(articles), section_context)
            suggestions.append(_to_suggestion(article, score))
        return suggestions

    async def close(self) -> None:
        """Close the underlying HTTP client if this provider created it."""

        if self._owns_client:
            await self._http.aclose()

    async def _esearch(self, query: str, max_results: int) -> list[str]:
        """Step 1: map query → list of PMIDs."""

        params: dict[str, str] = {
            "db": "pubmed",
            "term": query,
            "retmax": str(max_results),
            "sort": "relevance",
            "retmode": "json",
        }
        try:
            response = await self._http.get(_ESEARCH_URL, params=params)
        except httpx.HTTPError as exc:
            logger.warning("pubmed_esearch_failed", extra={"error": str(exc), "query": query})
            return []
        if response.status_code != 200:
            logger.warning(
                "pubmed_esearch_bad_status",
                extra={"status": response.status_code, "query": query},
            )
            return []
        try:
            payload = response.json()
        except ValueError as exc:
            logger.warning("pubmed_esearch_bad_json", extra={"error": str(exc)})
            return []

        outer = as_dict(payload)
        if outer is None:
            return []
        result = as_dict(outer.get("esearchresult"))
        if result is None:
            return []
        ids = as_list(result.get("idlist"))
        if ids is None:
            return []
        return [str(pmid) for pmid in ids if isinstance(pmid, str | int)]

    async def _efetch(self, pmids: list[str]) -> bytes | None:
        """Step 2: pull the article XML for the resolved PMIDs."""

        params: dict[str, str] = {
            "db": "pubmed",
            "id": ",".join(pmids),
            "retmode": "xml",
        }
        try:
            response = await self._http.get(_EFETCH_URL, params=params)
        except httpx.HTTPError as exc:
            logger.warning("pubmed_efetch_failed", extra={"error": str(exc)})
            return None
        if response.status_code != 200:
            logger.warning("pubmed_efetch_bad_status", extra={"status": response.status_code})
            return None
        return response.content


def _parse_efetch_xml(xml_bytes: bytes) -> list[dict[str, Any]]:
    """Parse the PubMed ``efetch`` XML envelope into a list of plain dicts."""

    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        logger.warning("pubmed_efetch_parse_failed", extra={"error": str(exc)})
        return []

    articles: list[dict[str, Any]] = []
    for article_node in root.findall(".//PubmedArticle"):
        parsed = _parse_one_article(article_node)
        if parsed is not None:
            articles.append(parsed)
    return articles


def _parse_one_article(node: ET.Element) -> dict[str, Any] | None:
    """Pull the fields we care about out of one ``<PubmedArticle>`` element."""

    title_el = node.find(".//ArticleTitle")
    if title_el is None or title_el.text is None or not title_el.text.strip():
        return None
    title = " ".join(title_el.itertext()).strip()

    authors: list[str] = []
    for author in node.findall(".//AuthorList/Author"):
        last = author.findtext("LastName")
        initials = author.findtext("Initials")
        if last and initials:
            authors.append(f"{last} {initials}")
        elif last:
            authors.append(last)

    year_text = node.findtext(".//PubDate/Year")
    year: int | None = None
    if year_text and year_text.isdigit():
        candidate = int(year_text)
        if 1500 <= candidate <= 2100:
            year = candidate

    journal = node.findtext(".//Journal/Title")

    doi: str | None = None
    for article_id in node.findall(".//ArticleIdList/ArticleId"):
        if article_id.attrib.get("IdType") == "doi" and article_id.text:
            doi = article_id.text.strip()[:200]
            break

    abstract_parts: list[str] = []
    for abst in node.findall(".//Abstract/AbstractText"):
        if abst.text:
            abstract_parts.append(abst.text)
    abstract = " ".join(abstract_parts).strip()

    return {
        "title": title[:500],
        "authors": authors[:20],
        "year": year,
        "journal": journal,
        "doi": doi,
        "abstract": abstract,
    }


def _score_relevance(
    article: dict[str, Any],
    index: int,
    total: int,
    section_context: str,
) -> float:
    """Combine PubMed rank + recency + DOI presence + context match."""

    base = 1.0 if total <= 1 else 1.0 - (0.5 * (index / (total - 1)))

    if article["year"] is not None:
        current_year = datetime.now(UTC).year
        if current_year - article["year"] <= _RECENT_YEAR_BOOST_THRESHOLD_YEARS:
            base += 0.1

    if article["doi"]:
        base += 0.1

    if article["abstract"] and section_context:
        section_lower = section_context.lower()
        abstract_lower = article["abstract"].lower()
        for token in {t.strip() for t in section_lower.split() if len(t) > 4}:
            if token in abstract_lower:
                base += 0.05
                break

    return min(1.0, max(0.0, base))


def _to_suggestion(article: dict[str, Any], score: float) -> Suggestion:
    """Build a :class:`Suggestion` from one parsed article dict."""

    abstract: str = article["abstract"] or ""
    description = (
        abstract[:_MAX_DESCRIPTION_LEN] if abstract else article["title"][:_MAX_DESCRIPTION_LEN]
    )
    url: str | None = None
    if article["doi"]:
        url = f"https://doi.org/{article['doi']}"

    return Suggestion(
        title=article["title"],
        description=description,
        source_provider=SuggestionSource.PUBMED,
        relevance_score=round(score, 4),
        authors=article["authors"],
        year=article["year"],
        doi=article["doi"],
        url=url,
    )
