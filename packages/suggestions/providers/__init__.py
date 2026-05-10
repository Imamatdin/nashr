"""Suggestion-engine data providers, one module per upstream source."""

from packages.suggestions.providers.academic_bridge import AcademicBridgeProvider
from packages.suggestions.providers.data_gov_uz import DataGovUzProvider
from packages.suggestions.providers.lex_uz import LexUzProvider
from packages.suggestions.providers.pubmed import PubMedProvider
from packages.suggestions.providers.world_bank import WorldBankProvider

__all__ = [
    "AcademicBridgeProvider",
    "DataGovUzProvider",
    "LexUzProvider",
    "PubMedProvider",
    "WorldBankProvider",
]
