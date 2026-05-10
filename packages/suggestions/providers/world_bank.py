"""World Bank Open Data API client for economic & development indicators.

The provider has two strategies that run in order:

1. *Popular indicators* — a baked-in dictionary of indicators relevant to
   Uzbek academic writing (GDP, inflation, education spending, etc.).
   When the search query (case-insensitively) overlaps a popular keyword,
   we go straight to the country-level data endpoint for Uzbekistan,
   which is the fastest and most reliable path.
2. *Indicator search fallback* — for queries that don't match a popular
   key, hit the ``/indicator`` endpoint, take the first matching ID, and
   fetch its Uzbekistan data series.

All output is normalised into :class:`Suggestion` objects with the
``indicator_*`` fields populated. The ``country`` is always Uzbekistan
(ISO-3 ``UZB``); a future iteration can support comparators.

Reference: https://datahelpdesk.worldbank.org/knowledgebase/articles/889386-developer-information-overview
"""

from __future__ import annotations

import logging
from typing import Any, ClassVar

import httpx

from packages.academic.providers._json_utils import as_dict, as_list
from packages.core.models.suggestion import (
    AcademicDomain,
    Suggestion,
    SuggestionSource,
)

logger = logging.getLogger(__name__)


_BASE_URL: str = "https://api.worldbank.org/v2"
_COUNTRY_CODE: str = "UZB"
_COUNTRY_NAME: str = "Uzbekistan"
_REQUEST_TIMEOUT: float = 10.0
_DEFAULT_DATE_RANGE: str = "2018:2024"
_RECENT_DATA_YEAR_THRESHOLD: int = 3

POPULAR_INDICATORS: dict[str, str] = {
    "NY.GDP.MKTP.CD": "GDP (current US$)",
    "NY.GDP.MKTP.KD.ZG": "GDP growth (annual %)",
    "FP.CPI.TOTL.ZG": "Inflation, consumer prices (annual %)",
    "SL.UEM.TOTL.ZS": "Unemployment, total (% of labor force)",
    "SP.POP.TOTL": "Population, total",
    "SE.XPD.TOTL.GD.ZS": "Government expenditure on education (% of GDP)",
    "SH.XPD.CHEX.GD.ZS": "Current health expenditure (% of GDP)",
    "EG.USE.ELEC.KH.PC": "Electric power consumption (kWh per capita)",
    "EN.ATM.CO2E.PC": "CO2 emissions (metric tons per capita)",
    "IT.NET.USER.ZS": "Individuals using the Internet (% of population)",
    "BX.KLT.DINV.CD.WD": "Foreign direct investment (BoP, current US$)",
    "AG.LND.ARBL.ZS": "Arable land (% of land area)",
}

_KEYWORD_TO_INDICATOR: dict[str, str] = {
    "gdp": "NY.GDP.MKTP.CD",
    "growth": "NY.GDP.MKTP.KD.ZG",
    "inflation": "FP.CPI.TOTL.ZG",
    "unemploy": "SL.UEM.TOTL.ZS",
    "labor": "SL.UEM.TOTL.ZS",
    "population": "SP.POP.TOTL",
    "education": "SE.XPD.TOTL.GD.ZS",
    "health": "SH.XPD.CHEX.GD.ZS",
    "electric": "EG.USE.ELEC.KH.PC",
    "energy": "EG.USE.ELEC.KH.PC",
    "co2": "EN.ATM.CO2E.PC",
    "carbon": "EN.ATM.CO2E.PC",
    "emission": "EN.ATM.CO2E.PC",
    "internet": "IT.NET.USER.ZS",
    "investment": "BX.KLT.DINV.CD.WD",
    "fdi": "BX.KLT.DINV.CD.WD",
    "agriculture": "AG.LND.ARBL.ZS",
    "land": "AG.LND.ARBL.ZS",
}


class WorldBankProvider:
    """Async client for the World Bank Open Data REST API."""

    provider_name: str = "World Bank"
    supported_domains: ClassVar[list[AcademicDomain]] = [
        AcademicDomain.ECONOMICS,
        AcademicDomain.SOCIAL_SCIENCES,
    ]

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._http = client if client is not None else httpx.AsyncClient(timeout=_REQUEST_TIMEOUT)
        self._owns_client = client is None

    async def search(
        self,
        query: str,
        section_context: str,
        max_results: int = 5,
    ) -> list[Suggestion]:
        """Resolve query → indicator(s), fetch Uzbekistan data, return suggestions."""

        cleaned = query.strip().lower()
        if not cleaned:
            return []

        matched_ids = _match_popular_indicators(cleaned)
        suggestions: list[Suggestion] = []

        for indicator_id in matched_ids[:max_results]:
            data_point = await self._fetch_indicator_data(indicator_id)
            if data_point is None:
                continue
            indicator_name = POPULAR_INDICATORS.get(indicator_id, indicator_id)
            suggestions.append(_to_suggestion(indicator_id, indicator_name, data_point, 0.8))
            if len(suggestions) >= max_results:
                return suggestions

        if suggestions:
            return suggestions

        api_indicator = await self._search_indicator(cleaned)
        if api_indicator is None:
            return []
        indicator_id, indicator_name = api_indicator
        data_point = await self._fetch_indicator_data(indicator_id)
        if data_point is None:
            return []
        return [_to_suggestion(indicator_id, indicator_name, data_point, 0.6)]

    async def close(self) -> None:
        """Close the underlying HTTP client if this provider created it."""

        if self._owns_client:
            await self._http.aclose()

    async def _fetch_indicator_data(self, indicator_id: str) -> dict[str, Any] | None:
        """Fetch the latest non-null Uzbekistan value for an indicator."""

        url = f"{_BASE_URL}/country/{_COUNTRY_CODE}/indicator/{indicator_id}"
        params: dict[str, str] = {
            "format": "json",
            "date": _DEFAULT_DATE_RANGE,
            "per_page": "10",
        }
        try:
            response = await self._http.get(url, params=params)
        except httpx.HTTPError as exc:
            logger.warning(
                "world_bank_data_failed",
                extra={"error": str(exc), "indicator": indicator_id},
            )
            return None
        if response.status_code != 200:
            logger.warning(
                "world_bank_data_bad_status",
                extra={"status": response.status_code, "indicator": indicator_id},
            )
            return None
        try:
            payload = response.json()
        except ValueError as exc:
            logger.warning("world_bank_data_bad_json", extra={"error": str(exc)})
            return None

        outer = as_list(payload)
        if outer is None or len(outer) < 2:
            return None
        rows = as_list(outer[1])
        if rows is None:
            return None
        for raw_row in rows:
            row = as_dict(raw_row)
            if row is None:
                continue
            value = row.get("value")
            if value is None:
                continue
            year_raw = row.get("date")
            if not isinstance(year_raw, str) or not year_raw.isdigit():
                continue
            return {"value": value, "year": int(year_raw)}
        return None

    async def _search_indicator(self, query: str) -> tuple[str, str] | None:
        """Fallback: ask the World Bank /indicator endpoint for a match."""

        params: dict[str, str] = {
            "format": "json",
            "source": "2",
            "per_page": "5",
        }
        try:
            response = await self._http.get(f"{_BASE_URL}/indicator", params=params)
        except httpx.HTTPError as exc:
            logger.warning("world_bank_indicator_failed", extra={"error": str(exc), "query": query})
            return None
        if response.status_code != 200:
            return None
        try:
            payload = response.json()
        except ValueError:
            return None
        outer = as_list(payload)
        if outer is None or len(outer) < 2:
            return None
        rows = as_list(outer[1])
        if rows is None:
            return None
        query_tokens = {token for token in query.split() if token}
        best: tuple[str, str] | None = None
        for raw_row in rows:
            row = as_dict(raw_row)
            if row is None:
                continue
            indicator_id = row.get("id")
            name = row.get("name")
            if not isinstance(indicator_id, str) or not isinstance(name, str):
                continue
            name_lower = name.lower()
            if any(token in name_lower for token in query_tokens):
                best = (indicator_id, name)
                break
        return best


def _match_popular_indicators(query: str) -> list[str]:
    """Find every popular indicator ID whose keyword appears in the query."""

    matched: list[str] = []
    seen: set[str] = set()
    for keyword, indicator_id in _KEYWORD_TO_INDICATOR.items():
        if keyword in query and indicator_id not in seen:
            matched.append(indicator_id)
            seen.add(indicator_id)
    return matched


def _to_suggestion(
    indicator_id: str,
    indicator_name: str,
    data_point: dict[str, Any],
    base_score: float,
) -> Suggestion:
    """Convert one (indicator + value + year) tuple into a :class:`Suggestion`."""

    raw_value = data_point["value"]
    year_int: int = data_point["year"]
    value_str = _format_value(raw_value)

    score = base_score
    current_year = 2026
    if current_year - year_int <= _RECENT_DATA_YEAR_THRESHOLD:
        score += 0.1
    score = min(1.0, score)

    description = (
        f"{_COUNTRY_NAME}: {indicator_name} = {value_str} ({year_int}). "
        "Source: World Bank Open Data."
    )
    url = f"https://data.worldbank.org/indicator/{indicator_id}?locations={_COUNTRY_CODE}"

    return Suggestion(
        title=indicator_name[:500],
        description=description[:1000],
        source_provider=SuggestionSource.WORLD_BANK,
        relevance_score=round(score, 4),
        year=year_int,
        url=url,
        indicator_name=indicator_name[:300],
        indicator_value=value_str,
        indicator_year=year_int,
        indicator_country=_COUNTRY_NAME,
    )


def _format_value(raw: object) -> str:
    """Render a numeric value in a compact form suitable for descriptions."""

    if isinstance(raw, int | float):
        if abs(raw) >= 1_000_000_000:
            return f"{raw / 1_000_000_000:.2f}B"
        if abs(raw) >= 1_000_000:
            return f"{raw / 1_000_000:.2f}M"
        if isinstance(raw, float):
            return f"{raw:.2f}"
        return str(raw)
    return str(raw)[:100]
