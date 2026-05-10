"""Domain-adaptive suggestion engine.

Detects the academic domain(s) of an article from its claims, chunks, outline,
and source metadata, and routes per-section searches to domain-specific data
providers (PubMed for medical, World Bank for economic indicators, etc.).
The orchestrator that combines detection + provider search into ranked
:class:`SectionSuggestions` lives in a separate task; this module ships only
the foundation: detector, registry, and the first set of providers.
"""

from packages.suggestions.domain_detector import DomainDetector
from packages.suggestions.provider_registry import ProviderRegistry, SuggestionProvider

__all__ = [
    "DomainDetector",
    "ProviderRegistry",
    "SuggestionProvider",
]
