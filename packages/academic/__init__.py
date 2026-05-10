"""Academic source service: Semantic Scholar, arXiv, OpenAlex, CrossRef clients."""

from packages.academic.doi_resolver import DOIResolver
from packages.academic.search import AcademicSearchService

__all__ = ["AcademicSearchService", "DOIResolver"]
