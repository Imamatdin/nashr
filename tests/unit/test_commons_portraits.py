"""Behaviour tests for the gated Wikidata→Commons portrait resolver.

Every HTTP call is served by an :class:`httpx.MockTransport`, so these tests
exercise the real resolution + license-gating + portrait-ranking code path
without touching the network (per ``.claude/rules/testing.md``: external HTTP
APIs may be mocked at the boundary). A separate gated test (``NASHR_LIVE_NET``)
hits the real Wikidata/Commons for the Voltaire acceptance case.
"""

from __future__ import annotations

import os
from typing import Any

import httpx
import pytest

from packages.presentation.commons_portraits import (
    CommonsPortraitResolver,
    classify_license,
)

# ---------------------------------------------------------------------------
# License classification (pure, no HTTP)
# ---------------------------------------------------------------------------


def _ext(**fields: str) -> dict[str, Any]:
    return {k: {"value": v} for k, v in fields.items()}


def test_public_domain_is_allowed_without_attribution() -> None:
    decision = classify_license(_ext(License="pd", LicenseShortName="Public domain"))
    assert decision.allowed is True
    assert decision.requires_attribution is False


def test_cc0_is_allowed_without_attribution() -> None:
    decision = classify_license(_ext(License="cc0", LicenseShortName="CC0"))
    assert decision.allowed is True
    assert decision.requires_attribution is False


def test_cc_by_is_allowed_with_attribution() -> None:
    decision = classify_license(_ext(License="cc-by-4.0", LicenseShortName="CC BY 4.0"))
    assert decision.allowed is True
    assert decision.requires_attribution is True


def test_cc_by_sa_is_rejected() -> None:
    # Contains "cc-by" but the -sa component must reject it.
    decision = classify_license(_ext(License="cc-by-sa-3.0", LicenseShortName="CC BY-SA 3.0"))
    assert decision.allowed is False


def test_cc_by_nc_and_nd_are_rejected() -> None:
    assert classify_license(_ext(License="cc-by-nc-2.0")).allowed is False
    assert classify_license(_ext(License="cc-by-nd-4.0")).allowed is False


def test_editorial_and_restricted_are_rejected() -> None:
    assert classify_license(_ext(LicenseShortName="Editorial use only")).allowed is False
    assert classify_license(_ext(License="cc-by-4.0", Restrictions="trademarked")).allowed is False


def test_missing_license_is_rejected() -> None:
    assert classify_license({}).allowed is False


# ---------------------------------------------------------------------------
# Full resolution flow (mocked Wikidata + Commons)
# ---------------------------------------------------------------------------

_IMAGE_URL = "https://upload.wikimedia.org/portrait.jpg"


def _search(
    qid: str = "Q9068", label: str = "Voltaire", description: str = "French writer"
) -> dict[str, Any]:
    return {"search": [{"id": qid, "label": label, "description": description}]}


def _entity(
    qid: str = "Q9068",
    *,
    human: bool = True,
    birth: int | None = 1694,
    death: int | None = 1778,
    image: str | None = "Largilliere Voltaire.jpg",
    description: str = "French Enlightenment writer and philosopher",
) -> dict[str, Any]:
    claims: dict[str, Any] = {}
    if human:
        claims["P31"] = [{"mainsnak": {"datavalue": {"value": {"id": "Q5"}}}}]
    else:
        claims["P31"] = [{"mainsnak": {"datavalue": {"value": {"id": "Q11424"}}}}]  # film
    if birth is not None:
        claims["P569"] = [
            {"mainsnak": {"datavalue": {"value": {"time": f"+{birth}-01-01T00:00:00Z"}}}}
        ]
    if death is not None:
        claims["P570"] = [
            {"mainsnak": {"datavalue": {"value": {"time": f"+{death}-01-01T00:00:00Z"}}}}
        ]
    if image is not None:
        claims["P18"] = [{"mainsnak": {"datavalue": {"value": image}}}]
    return {
        "entities": {
            qid: {
                "id": qid,
                "labels": {"en": {"language": "en", "value": "Voltaire"}},
                "descriptions": {"en": {"language": "en", "value": description}},
                "claims": claims,
            }
        }
    }


def _imageinfo(
    *,
    license_code: str = "pd",
    short: str = "Public domain",
    width: int = 1200,
    height: int = 1500,
    mime: str = "image/jpeg",
    artist: str = "Nicolas de Largillière",
    restrictions: str = "",
) -> dict[str, Any]:
    ext: dict[str, Any] = {
        "License": {"value": license_code},
        "LicenseShortName": {"value": short},
        "Artist": {"value": artist},
    }
    if restrictions:
        ext["Restrictions"] = {"value": restrictions}
    return {
        "query": {
            "pages": {
                "12345": {
                    "title": "File:portrait.jpg",
                    "imageinfo": [
                        {
                            "url": _IMAGE_URL,
                            "width": width,
                            "height": height,
                            "mime": mime,
                            "extmetadata": ext,
                        }
                    ],
                }
            }
        }
    }


def _client(
    *,
    search: dict[str, Any],
    entities: dict[str, Any],
    imageinfo: dict[str, Any],
    image_bytes: bytes = b"\x89PNG\r\n\x1a\n binary portrait data",
) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "wikidata.org" in url:
            action = request.url.params.get("action")
            if action == "wbsearchentities":
                return httpx.Response(200, json=search)
            if action == "wbgetentities":
                return httpx.Response(200, json=entities)
            return httpx.Response(404)
        if "commons.wikimedia.org" in url:
            return httpx.Response(200, json=imageinfo)
        # Anything else is the binary image download.
        return httpx.Response(200, content=image_bytes, headers={"content-type": "image/jpeg"})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=5)


@pytest.mark.asyncio
async def test_resolves_public_domain_portrait_no_attribution() -> None:
    async with _client(search=_search(), entities=_entity(), imageinfo=_imageinfo()) as client:
        result = await CommonsPortraitResolver().resolve(
            client, "Voltaire", years="1694-1778", role="philosopher"
        )
    assert result is not None
    assert result.data  # real bytes were downloaded and re-hosted by the caller
    assert result.content_type == "image/jpeg"
    assert result.attribution is None  # PD needs no attribution


@pytest.mark.asyncio
async def test_resolves_cc_by_portrait_records_attribution() -> None:
    info = _imageinfo(license_code="cc-by-4.0", short="CC BY 4.0", artist="Jane Photographer")
    async with _client(search=_search(), entities=_entity(), imageinfo=info) as client:
        result = await CommonsPortraitResolver().resolve(client, "Voltaire", years="1694-1778")
    assert result is not None
    assert result.attribution is not None
    assert result.attribution.creator == "Jane Photographer"
    assert "CC BY" in result.attribution.license_name
    assert "commons.wikimedia.org" in result.attribution.source_url
    # The note line is what the ImagePass folds into speaker_notes.
    assert "Jane Photographer" in result.attribution.to_note()


@pytest.mark.asyncio
async def test_abstains_on_date_mismatch_namesake() -> None:
    # The only candidate's dates contradict the provided context → abstain.
    async with _client(
        search=_search(), entities=_entity(birth=1950, death=2010), imageinfo=_imageinfo()
    ) as client:
        result = await CommonsPortraitResolver().resolve(client, "Voltaire", years="1694-1778")
    assert result is None


@pytest.mark.asyncio
async def test_abstains_on_non_whitelisted_license() -> None:
    info = _imageinfo(license_code="cc-by-sa-3.0", short="CC BY-SA 3.0")
    async with _client(search=_search(), entities=_entity(), imageinfo=info) as client:
        result = await CommonsPortraitResolver().resolve(client, "Voltaire", years="1694-1778")
    assert result is None


@pytest.mark.asyncio
async def test_abstains_when_entity_is_not_human() -> None:
    async with _client(
        search=_search(), entities=_entity(human=False), imageinfo=_imageinfo()
    ) as client:
        result = await CommonsPortraitResolver().resolve(client, "Voltaire", years="1694-1778")
    assert result is None


@pytest.mark.asyncio
async def test_abstains_on_statue_filename() -> None:
    entity = _entity(image="Voltaire statue in Paris.jpg")
    async with _client(search=_search(), entities=entity, imageinfo=_imageinfo()) as client:
        result = await CommonsPortraitResolver().resolve(client, "Voltaire", years="1694-1778")
    assert result is None


@pytest.mark.asyncio
async def test_abstains_on_low_resolution() -> None:
    async with _client(
        search=_search(), entities=_entity(), imageinfo=_imageinfo(width=80, height=100)
    ) as client:
        result = await CommonsPortraitResolver().resolve(client, "Voltaire", years="1694-1778")
    assert result is None


@pytest.mark.asyncio
async def test_abstains_when_no_search_results() -> None:
    async with _client(
        search={"search": []}, entities={"entities": {}}, imageinfo=_imageinfo()
    ) as client:
        result = await CommonsPortraitResolver().resolve(client, "Nobody At All")
    assert result is None


@pytest.mark.asyncio
async def test_abstains_when_entity_has_no_image() -> None:
    async with _client(
        search=_search(), entities=_entity(image=None), imageinfo=_imageinfo()
    ) as client:
        result = await CommonsPortraitResolver().resolve(client, "Voltaire", years="1694-1778")
    assert result is None


# ---------------------------------------------------------------------------
# Live network (gated) — run on the server with NASHR_LIVE_NET=1
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    os.environ.get("NASHR_LIVE_NET") != "1",
    reason="live network test; set NASHR_LIVE_NET=1 to run",
)
@pytest.mark.asyncio
async def test_live_voltaire_resolves_to_clean_portrait() -> None:
    async with httpx.AsyncClient(timeout=15) as client:
        result = await CommonsPortraitResolver().resolve(
            client, "Voltaire", years="1694-1778", role="writer philosopher"
        )
    assert result is not None
    assert result.content_type.startswith("image/")
    assert len(result.data) > 1000


@pytest.mark.skipif(
    os.environ.get("NASHR_LIVE_NET") != "1",
    reason="live network test; set NASHR_LIVE_NET=1 to run",
)
@pytest.mark.asyncio
async def test_live_namesake_with_wrong_dates_abstains() -> None:
    # A real person's name with deliberately wrong dates should not resolve.
    async with httpx.AsyncClient(timeout=15) as client:
        result = await CommonsPortraitResolver().resolve(client, "Voltaire", years="1850-1900")
    assert result is None
