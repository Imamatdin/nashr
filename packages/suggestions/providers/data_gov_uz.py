"""Stub provider for the Uzbekistan government open-data portal.

data.gov.uz publishes datasets on demographics, statistics, public
finance, and registries. An API key is required for programmatic access
and the registration flow is still in progress; until it lands the
provider is wired into the registry as a no-op.

The proposed AcademicDomain enum currently lacks a dedicated
``STATISTICS`` value, so the supported-domains list points at the two
closest existing buckets (``ECONOMICS`` and ``SOCIAL_SCIENCES``). When
``STATISTICS`` is added in a future iteration the support list should
gain it without dropping the others.
"""

from __future__ import annotations

import logging
from typing import ClassVar

import httpx

from packages.core.models.suggestion import (
    AcademicDomain,
    Suggestion,
)

logger = logging.getLogger(__name__)


class DataGovUzProvider:
    """Placeholder client for the data.gov.uz open-data API."""

    provider_name: str = "data.gov.uz"
    supported_domains: ClassVar[list[AcademicDomain]] = [
        AcademicDomain.ECONOMICS,
        AcademicDomain.SOCIAL_SCIENCES,
    ]

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._http = client
        self._owns_client = False

    async def search(
        self,
        query: str,
        section_context: str,
        max_results: int = 5,
    ) -> list[Suggestion]:
        """Return an empty list until an API key is registered."""

        logger.info(
            "data_gov_uz_stub_called",
            extra={"query": query, "section_context": section_context[:120]},
        )
        return []

    async def close(self) -> None:
        """No-op while the implementation is a stub."""

        return None
