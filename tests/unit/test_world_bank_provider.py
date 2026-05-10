"""Behaviour tests for :class:`WorldBankProvider`.

The provider has two query strategies (popular-indicator dictionary,
generic indicator search). The tests pin both: a query that hits the
popular dictionary should bypass the search endpoint and call the data
endpoint directly, and a query that misses should fall back to indicator
search before fetching data. Errors and missing values must collapse to
an empty list, never crash.
"""

from __future__ import annotations

from typing import Any

import httpx

from packages.core.models.suggestion import Suggestion, SuggestionSource
from packages.suggestions.providers.world_bank import WorldBankProvider


def _data_payload(value: float | int | None, year: str) -> list[Any]:
    """Shape: ``[meta, [row, ...]]`` matching World Bank API output."""

    return [
        {"page": 1, "pages": 1, "per_page": 10, "total": 1},
        [
            {
                "indicator": {"id": "X", "value": "Indicator"},
                "country": {"id": "UZ", "value": "Uzbekistan"},
                "value": value,
                "date": year,
            }
        ],
    ]


def _data_payload_multiple(rows: list[tuple[float | int | None, str]]) -> list[Any]:
    return [
        {"page": 1, "pages": 1, "per_page": 10, "total": len(rows)},
        [
            {
                "indicator": {"id": "X", "value": "Ind"},
                "country": {"id": "UZ", "value": "Uzbekistan"},
                "value": v,
                "date": y,
            }
            for v, y in rows
        ],
    ]


def _indicator_search_payload(items: list[dict[str, str]]) -> list[Any]:
    return [
        {"page": 1, "pages": 1, "per_page": 5, "total": len(items)},
        items,
    ]


def _route(handler_fn: Any) -> httpx.MockTransport:
    return httpx.MockTransport(handler_fn)


async def test_world_bank_search_popular_indicator_gdp() -> None:
    captured: dict[str, list[str]] = {"paths": []}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["paths"].append(request.url.path)
        if "/country/UZB/indicator/" in request.url.path:
            return httpx.Response(200, json=_data_payload(80_000_000_000, "2023"))
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=_route(handler), timeout=5) as client:
        provider = WorldBankProvider(client=client)
        suggestions = await provider.search("GDP growth Uzbekistan", "Results", max_results=2)

    assert len(suggestions) >= 1
    first = suggestions[0]
    assert first.source_provider == SuggestionSource.WORLD_BANK
    assert first.indicator_country == "Uzbekistan"
    assert first.indicator_year == 2023
    assert first.indicator_value is not None
    assert any("/country/UZB/indicator/NY.GDP" in path for path in captured["paths"])


async def test_world_bank_search_education_keyword_hits_popular_dict() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "/country/UZB/indicator/SE.XPD.TOTL.GD.ZS" in request.url.path:
            return httpx.Response(200, json=_data_payload(5.6, "2022"))
        return httpx.Response(200, json=_data_payload(None, "2022"))

    async with httpx.AsyncClient(transport=_route(handler), timeout=5) as client:
        provider = WorldBankProvider(client=client)
        suggestions = await provider.search("education spending policy", "", max_results=1)
    assert len(suggestions) == 1
    assert "education" in suggestions[0].title.lower()


async def test_world_bank_handles_no_data() -> None:
    def handler(_r: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_data_payload(None, "2023"))

    async with httpx.AsyncClient(transport=_route(handler), timeout=5) as client:
        provider = WorldBankProvider(client=client)
        suggestions = await provider.search("gdp", "", max_results=1)
    assert suggestions == []


async def test_world_bank_handles_http_error() -> None:
    async with httpx.AsyncClient(
        transport=_route(lambda _r: httpx.Response(500)), timeout=5
    ) as client:
        provider = WorldBankProvider(client=client)
        suggestions = await provider.search("gdp", "", max_results=1)
    assert suggestions == []


async def test_world_bank_description_includes_value_and_year() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "/country/UZB/indicator/" in request.url.path:
            return httpx.Response(200, json=_data_payload(5.6, "2023"))
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=_route(handler), timeout=5) as client:
        provider = WorldBankProvider(client=client)
        suggestions = await provider.search("inflation", "Results", max_results=1)

    assert len(suggestions) == 1
    desc = suggestions[0].description
    assert "5.60" in desc or "5.6" in desc
    assert "2023" in desc


async def test_world_bank_uses_uzb_country_code() -> None:
    captured: dict[str, list[str]] = {"paths": []}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["paths"].append(request.url.path)
        return httpx.Response(200, json=_data_payload(100, "2024"))

    async with httpx.AsyncClient(transport=_route(handler), timeout=5) as client:
        provider = WorldBankProvider(client=client)
        await provider.search("population", "", max_results=1)
    assert any("UZB" in path for path in captured["paths"])


async def test_world_bank_falls_back_to_indicator_search() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/v2/indicator"):
            return httpx.Response(
                200,
                json=_indicator_search_payload(
                    [{"id": "MISC.IND.001", "name": "Niche metric of foobar"}]
                ),
            )
        if "/country/UZB/indicator/MISC.IND.001" in request.url.path:
            return httpx.Response(200, json=_data_payload(7, "2022"))
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=_route(handler), timeout=5) as client:
        provider = WorldBankProvider(client=client)
        suggestions = await provider.search("foobar", "", max_results=1)
    assert len(suggestions) == 1
    assert suggestions[0].indicator_name is not None
    assert "foobar" in suggestions[0].indicator_name.lower()


async def test_world_bank_suggestion_model_valid() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "/country/UZB/indicator/" in request.url.path:
            return httpx.Response(200, json=_data_payload(34.5, "2024"))
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=_route(handler), timeout=5) as client:
        provider = WorldBankProvider(client=client)
        suggestions = await provider.search("gdp", "Results", max_results=1)

    assert len(suggestions) == 1
    s = suggestions[0]
    assert isinstance(s, Suggestion)
    assert s.source_provider == SuggestionSource.WORLD_BANK
    assert s.indicator_name is not None
    assert s.indicator_value is not None
    assert s.indicator_year == 2024
    rebuilt = Suggestion.model_validate(s.model_dump())
    assert rebuilt == s


async def test_world_bank_skips_null_values_uses_first_real() -> None:
    def handler(_r: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json=_data_payload_multiple([(None, "2024"), (None, "2023"), (8.2, "2022")])
        )

    async with httpx.AsyncClient(transport=_route(handler), timeout=5) as client:
        provider = WorldBankProvider(client=client)
        suggestions = await provider.search("gdp", "", max_results=1)
    assert len(suggestions) == 1
    assert suggestions[0].indicator_year == 2022


async def test_world_bank_blank_query_returns_empty() -> None:
    async with httpx.AsyncClient(
        transport=_route(lambda _r: httpx.Response(404)), timeout=5
    ) as client:
        provider = WorldBankProvider(client=client)
        suggestions = await provider.search("   ", "", max_results=1)
    assert suggestions == []
