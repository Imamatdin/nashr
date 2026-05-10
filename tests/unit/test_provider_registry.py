"""Behaviour tests for :class:`ProviderRegistry`.

These tests pin the registry's contract: every domain in
:class:`AcademicDomain` resolves to at least one provider, the right
domain-specific providers fire for medical/economics/legal queries,
multi-domain queries deduplicate shared providers, and custom
:class:`SuggestionProvider` implementations register cleanly.
"""

from __future__ import annotations

from typing import ClassVar

from packages.core.models.suggestion import (
    AcademicDomain,
    Suggestion,
)
from packages.suggestions.provider_registry import (
    ProviderRegistry,
    SuggestionProvider,
)
from packages.suggestions.providers import (
    AcademicBridgeProvider,
    LexUzProvider,
    PubMedProvider,
    WorldBankProvider,
)


class _FakeProvider:
    """Minimal :class:`SuggestionProvider` implementation for registration tests."""

    provider_name = "Fake"
    supported_domains: ClassVar[list[AcademicDomain]] = [AcademicDomain.GENERAL]

    async def search(
        self,
        query: str,
        section_context: str,
        max_results: int = 5,
    ) -> list[Suggestion]:
        return []

    async def close(self) -> None:
        return None


def _has_type(providers: list[SuggestionProvider], cls: type) -> bool:
    return any(isinstance(p, cls) for p in providers)


def test_registry_returns_pubmed_and_bridge_for_medical() -> None:
    registry = ProviderRegistry()
    providers = registry.get_providers([AcademicDomain.MEDICAL])
    assert _has_type(providers, PubMedProvider)
    assert _has_type(providers, AcademicBridgeProvider)


def test_registry_returns_world_bank_for_economics() -> None:
    registry = ProviderRegistry()
    providers = registry.get_providers([AcademicDomain.ECONOMICS])
    assert _has_type(providers, WorldBankProvider)
    assert _has_type(providers, AcademicBridgeProvider)


def test_registry_returns_lex_uz_for_legal() -> None:
    registry = ProviderRegistry()
    providers = registry.get_providers([AcademicDomain.LEGAL])
    assert _has_type(providers, LexUzProvider)
    assert _has_type(providers, AcademicBridgeProvider)


def test_registry_deduplicates_providers() -> None:
    registry = ProviderRegistry()
    providers = registry.get_providers([AcademicDomain.MEDICAL, AcademicDomain.GENERAL])
    bridge_count = sum(1 for p in providers if isinstance(p, AcademicBridgeProvider))
    assert bridge_count == 1


def test_registry_general_always_has_academic_bridge() -> None:
    registry = ProviderRegistry()
    providers = registry.get_providers([AcademicDomain.GENERAL])
    assert _has_type(providers, AcademicBridgeProvider)


def test_register_custom_provider() -> None:
    registry = ProviderRegistry()
    fake = _FakeProvider()
    registry.register(AcademicDomain.AGRICULTURE, fake)
    providers = registry.get_providers([AcademicDomain.AGRICULTURE])
    assert fake in providers


def test_register_same_provider_twice_is_idempotent() -> None:
    registry = ProviderRegistry()
    fake = _FakeProvider()
    registry.register(AcademicDomain.GENERAL, fake)
    registry.register(AcademicDomain.GENERAL, fake)
    providers = registry.get_providers([AcademicDomain.GENERAL])
    assert sum(1 for p in providers if p is fake) == 1


def test_registry_all_domains_have_at_least_one_provider() -> None:
    registry = ProviderRegistry()
    for domain in AcademicDomain:
        providers = registry.get_providers([domain])
        assert len(providers) >= 1, f"{domain} has no providers"


def test_registry_empty_request_returns_empty_list() -> None:
    registry = ProviderRegistry()
    providers = registry.get_providers([])
    assert providers == []


def test_registry_preserves_domain_order_for_multi_domain_request() -> None:
    """First domain's providers come first; later domains only add new ones."""

    registry = ProviderRegistry()
    providers = registry.get_providers([AcademicDomain.MEDICAL, AcademicDomain.ECONOMICS])
    pubmed_idx = next(i for i, p in enumerate(providers) if isinstance(p, PubMedProvider))
    wb_idx = next(i for i, p in enumerate(providers) if isinstance(p, WorldBankProvider))
    assert pubmed_idx < wb_idx
