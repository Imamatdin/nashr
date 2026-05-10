"""Domain-adaptive suggestion engine.

Detects the academic domain(s) of an article from its claims, chunks, outline,
and source metadata, and routes per-section searches to domain-specific data
providers (PubMed for medical, World Bank for economic indicators, etc.).
The :class:`SuggestionEngine` orchestrates detection, query construction,
provider fan-out, scoring and deduplication; :class:`SuggestionIntegrator`
turns user-approved suggestions into evidence-matrix entries.
"""

from packages.suggestions.domain_detector import DomainDetector
from packages.suggestions.engine import SuggestionEngine
from packages.suggestions.integrator import IntegrationError, SuggestionIntegrator
from packages.suggestions.provider_registry import ProviderRegistry, SuggestionProvider
from packages.suggestions.query_builder import SuggestionQueryBuilder

__all__ = [
    "DomainDetector",
    "IntegrationError",
    "ProviderRegistry",
    "SuggestionEngine",
    "SuggestionIntegrator",
    "SuggestionProvider",
    "SuggestionQueryBuilder",
]
