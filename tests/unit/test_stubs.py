"""Tests for the stub legal/government providers.

The lex.uz and data.gov.uz providers exist as no-op stubs until upstream
API access is secured. The tests pin that they return empty lists,
neither raise nor crash, and accept the same call signature as the real
providers — so the orchestrator can call them uniformly and the swap-in
of the real implementation later is invisible.
"""

from __future__ import annotations

from packages.suggestions.providers.data_gov_uz import DataGovUzProvider
from packages.suggestions.providers.lex_uz import LexUzProvider


async def test_lex_uz_stub_returns_empty() -> None:
    provider = LexUzProvider()
    suggestions = await provider.search("Konstitusiya 2017", "1-bob: Nazariy asos", max_results=5)
    assert suggestions == []
    await provider.close()


async def test_lex_uz_stub_has_legal_domain() -> None:
    from packages.core.models.suggestion import AcademicDomain

    assert AcademicDomain.LEGAL in LexUzProvider.supported_domains


async def test_data_gov_uz_stub_returns_empty() -> None:
    provider = DataGovUzProvider()
    suggestions = await provider.search("aholi soni", "Statistika", max_results=5)
    assert suggestions == []
    await provider.close()


async def test_data_gov_uz_stub_has_economics_or_social_domain() -> None:
    from packages.core.models.suggestion import AcademicDomain

    assert (
        AcademicDomain.ECONOMICS in DataGovUzProvider.supported_domains
        or AcademicDomain.SOCIAL_SCIENCES in DataGovUzProvider.supported_domains
    )
