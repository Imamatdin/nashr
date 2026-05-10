"""Stub provider for the Uzbekistan legal database.

lex.uz is the official portal for Uzbek legislation, but it does not yet
expose a stable public API; we are waiting on the client to secure access
arrangements. The interface and registration are wired up so that flipping
the implementation on later requires no changes to the registry, the
detector, or the orchestrator.

Until the API contract is signed, :meth:`search` returns an empty list
and logs the call so operators can see how often the missing provider
would have been queried.
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


class LexUzProvider:
    """Placeholder client for the lex.uz legal database."""

    provider_name: str = "Lex.uz"
    supported_domains: ClassVar[list[AcademicDomain]] = [AcademicDomain.LEGAL]

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._http = client
        self._owns_client = False

    async def search(
        self,
        query: str,
        section_context: str,
        max_results: int = 5,
    ) -> list[Suggestion]:
        """Return an empty list until lex.uz API access is secured."""

        logger.info(
            "lex_uz_stub_called",
            extra={"query": query, "section_context": section_context[:120]},
        )
        return []

    async def close(self) -> None:
        """No-op while the implementation is a stub."""

        return None
