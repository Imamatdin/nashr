"""DOI → :class:`DOIMetadata` resolver, used to auto-format bibliography entries.

Wraps :class:`CrossRefProvider` with a connection-reusing :class:`httpx.AsyncClient`
and a small concurrency cap for batch resolution. The cap is intentionally low
(5) because CrossRef's polite limit is roughly that, and going higher risks a
``429`` that wastes a whole batch.
"""

from __future__ import annotations

import asyncio

import httpx

from packages.academic.providers import CrossRefProvider
from packages.core.models.academic import DOIMetadata

_DEFAULT_TIMEOUT_SECONDS: int = 10
_BATCH_CONCURRENCY: int = 5


class DOIResolver:
    """Resolves DOIs to full citation metadata via CrossRef."""

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._http = (
            client if client is not None else httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT_SECONDS)
        )
        self._owns_client = client is None
        self._crossref = CrossRefProvider()

    async def resolve(self, doi: str) -> DOIMetadata | None:
        """Resolve one DOI; ``None`` if not found or upstream errored."""

        return await self._crossref.resolve_doi(self._http, doi)

    async def resolve_batch(self, dois: list[str]) -> dict[str, DOIMetadata | None]:
        """Resolve many DOIs concurrently, capped at :data:`_BATCH_CONCURRENCY`.

        The returned dict is keyed by the input DOI string verbatim (not the
        cleaned form) so callers can map results back to their original list
        without bookkeeping. Duplicate input DOIs collapse into one entry.
        """

        unique = list(dict.fromkeys(dois))
        semaphore = asyncio.Semaphore(_BATCH_CONCURRENCY)

        async def _one(doi: str) -> tuple[str, DOIMetadata | None]:
            async with semaphore:
                return doi, await self._crossref.resolve_doi(self._http, doi)

        results = await asyncio.gather(*(_one(d) for d in unique))
        return dict(results)

    async def close(self) -> None:
        """Close the underlying HTTP client if this resolver created it."""

        if self._owns_client:
            await self._http.aclose()
