"""Maps :class:`AcademicDomain` values to the providers that serve them.

The registry is the only piece the orchestrator calls when it needs to
fan out a section's search across the right backends. Every domain in
:class:`AcademicDomain` — including ``GENERAL`` — has at least one
provider registered, so callers never have to special-case the empty
case.

The :class:`SuggestionProvider` :class:`Protocol` is structural: any
object with the four members below satisfies it. The built-in providers
do not subclass it; the registry simply trusts the structural contract.
"""

from __future__ import annotations

from typing import ClassVar, Protocol, runtime_checkable

from packages.core.models.suggestion import (
    AcademicDomain,
    Suggestion,
)
from packages.suggestions.providers import (
    AcademicBridgeProvider,
    LexUzProvider,
    PubMedProvider,
    WorldBankProvider,
)


@runtime_checkable
class SuggestionProvider(Protocol):
    """Structural contract every suggestion data provider must satisfy."""

    provider_name: str
    supported_domains: ClassVar[list[AcademicDomain]]

    async def search(
        self,
        query: str,
        section_context: str,
        max_results: int = 5,
    ) -> list[Suggestion]:
        """Search for relevant suggestions, returning a ranked list."""

        ...

    async def close(self) -> None:
        """Release any resources owned by the provider."""

        ...


class ProviderRegistry:
    """Maps academic domains to the providers configured to serve them.

    Adding a new domain requires:

    1. A new :class:`SuggestionProvider` implementation.
    2. A single :meth:`register` call (or an entry in :data:`_DEFAULTS`).

    Beyond that the registry is plain bookkeeping. Lookups deduplicate
    providers across multiple requested domains so the orchestrator never
    fans the same query out twice.
    """

    def __init__(self) -> None:
        self._providers: dict[AcademicDomain, list[SuggestionProvider]] = {}
        self._register_defaults()

    def register(self, domain: AcademicDomain, provider: SuggestionProvider) -> None:
        """Register a provider for a single domain.

        Same-instance re-registrations are no-ops; this lets call sites
        stack ``register`` calls without bookkeeping.
        """

        bucket = self._providers.setdefault(domain, [])
        if provider in bucket:
            return
        bucket.append(provider)

    def get_providers(self, domains: list[AcademicDomain]) -> list[SuggestionProvider]:
        """Return every provider serving any of the requested domains, deduped.

        Order follows the request order (so the primary domain's providers
        come first), with later domains appending only providers not yet
        seen via :func:`id` identity.
        """

        seen: set[int] = set()
        ordered: list[SuggestionProvider] = []
        for domain in domains:
            for provider in self._providers.get(domain, []):
                marker = id(provider)
                if marker in seen:
                    continue
                seen.add(marker)
                ordered.append(provider)
        return ordered

    def _register_defaults(self) -> None:
        """Wire the built-in provider set into every supported domain.

        :class:`DataGovUzProvider` exists as a stub but is intentionally
        not registered yet — it returns no results until the API key is
        secured, so registering it would only add overhead. Add it to
        ECONOMICS / SOCIAL_SCIENCES once the implementation lands.
        """

        academic_bridge = AcademicBridgeProvider()
        pubmed = PubMedProvider()
        world_bank = WorldBankProvider()
        lex_uz = LexUzProvider()

        defaults: dict[AcademicDomain, list[SuggestionProvider]] = {
            AcademicDomain.MEDICAL: [pubmed, academic_bridge],
            AcademicDomain.ECONOMICS: [world_bank, academic_bridge],
            AcademicDomain.LEGAL: [lex_uz, academic_bridge],
            AcademicDomain.ENGINEERING: [academic_bridge],
            AcademicDomain.ENVIRONMENTAL: [academic_bridge],
            AcademicDomain.EDUCATION: [academic_bridge],
            AcademicDomain.AGRICULTURE: [academic_bridge],
            AcademicDomain.COMPUTER_SCIENCE: [academic_bridge],
            AcademicDomain.SOCIAL_SCIENCES: [world_bank, academic_bridge],
            AcademicDomain.GENERAL: [academic_bridge],
        }
        for domain, providers in defaults.items():
            for provider in providers:
                self.register(domain, provider)
