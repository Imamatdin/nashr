"""Academic-search provider clients (one module per upstream API)."""

from packages.academic.providers.arxiv import ArxivProvider
from packages.academic.providers.crossref import CrossRefProvider
from packages.academic.providers.openalex import OpenAlexProvider
from packages.academic.providers.semantic_scholar import SemanticScholarProvider

__all__ = [
    "ArxivProvider",
    "CrossRefProvider",
    "OpenAlexProvider",
    "SemanticScholarProvider",
]
