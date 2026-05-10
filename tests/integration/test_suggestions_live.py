"""Live-API smoke tests for the suggestion-engine providers.

Hits real PubMed and World Bank endpoints to catch contract drift the
mocked unit tests cannot see (renamed JSON keys, retired indicator IDs,
changed XML envelopes). Gated behind ``RUN_LIVE_API_TESTS=1`` and
network errors short-circuit to ``pytest.skip`` so a flaky upstream
or no-network sandbox doesn't surface as a regression. Slow + rate-
limited; do not add many.
"""

from __future__ import annotations

import os

import httpx
import pytest

from packages.core.enums import ClaimStrength, ClaimType
from packages.core.models import SourceClaimCreate
from packages.core.models.suggestion import AcademicDomain
from packages.suggestions.domain_detector import DomainDetector
from packages.suggestions.provider_registry import ProviderRegistry
from packages.suggestions.providers.pubmed import PubMedProvider
from packages.suggestions.providers.world_bank import WorldBankProvider

LIVE_API_TESTS = pytest.mark.skipif(
    os.environ.get("RUN_LIVE_API_TESTS") != "1",
    reason="Set RUN_LIVE_API_TESTS=1 to run live suggestion-API tests",
)


def _skip_on_network(exc: BaseException) -> None:
    pytest.skip(f"network unavailable: {type(exc).__name__}: {exc}")


@LIVE_API_TESTS
async def test_live_pubmed_search() -> None:
    provider = PubMedProvider()
    try:
        suggestions = await provider.search(
            "diabetes treatment Uzbekistan", "Methods", max_results=3
        )
    except httpx.HTTPError as exc:
        await provider.close()
        _skip_on_network(exc)
    finally:
        await provider.close()
    if not suggestions:
        pytest.skip("PubMed returned no results")
    print(f"\nPubMed: {len(suggestions)} suggestions")
    for s in suggestions:
        print(f"  {s.title[:80]} ({s.year}) doi={s.doi}")
    assert suggestions[0].title


@LIVE_API_TESTS
async def test_live_world_bank_gdp() -> None:
    provider = WorldBankProvider()
    try:
        suggestions = await provider.search("GDP growth", "Results", max_results=3)
    except httpx.HTTPError as exc:
        await provider.close()
        _skip_on_network(exc)
    finally:
        await provider.close()
    if not suggestions:
        pytest.skip("World Bank returned no results")
    print(f"\nWorld Bank: {len(suggestions)} suggestions")
    for s in suggestions:
        print(f"  {s.indicator_name} = {s.indicator_value} ({s.indicator_year})")
    assert suggestions[0].indicator_country == "Uzbekistan"


@LIVE_API_TESTS
async def test_live_domain_to_provider_pipeline() -> None:
    detector = DomainDetector()
    claims = [
        SourceClaimCreate(
            source_chunk_id="x",
            project_id="x",
            claim_text=(
                "A randomized clinical trial of a new treatment showed improved patient"
                " outcomes for chronic disease over the placebo arm of the cohort."
            ),
            strength=ClaimStrength.STRONG,
            claim_type=ClaimType.EMPIRICAL_FINDING,
        ),
        SourceClaimCreate(
            source_chunk_id="x",
            project_id="x",
            claim_text=(
                "Mortality among hospital patients fell after the new therapy was"
                " adopted in the surgery ward, with reduced morbidity over twelve months."
            ),
            strength=ClaimStrength.STRONG,
            claim_type=ClaimType.EMPIRICAL_FINDING,
        ),
    ]
    detection = detector.detect_domains(claims, [], None, [])
    assert detection.primary_domain == AcademicDomain.MEDICAL

    registry = ProviderRegistry()
    providers = registry.get_providers([detection.primary_domain])
    assert any(isinstance(p, PubMedProvider) for p in providers)

    pubmed = next(p for p in providers if isinstance(p, PubMedProvider))
    try:
        suggestions = await pubmed.search(
            "patient outcomes randomized treatment", "Results", max_results=2
        )
    except httpx.HTTPError as exc:
        _skip_on_network(exc)
    if not suggestions:
        pytest.skip("PubMed returned no results")
    print(f"\nPipeline: {detection.primary_domain.value} → PubMed → {len(suggestions)} hits")
    for s in suggestions:
        print(f"  {s.title[:80]}")
    assert suggestions[0].title
