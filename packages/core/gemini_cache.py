"""Explicit Gemini context cache for the brain's static system+tools block (5B-Q5b).

The Way 2 brain re-sends ~10.6k static tokens (``assemble_brain_system()`` + the
``edit_slides`` tool declaration) on every loop iteration. The droplet probe
(``scripts/probe_gemini_cache.py``, 2026-07-04) proved an explicit ``cached_content``
over exactly that block is accepted on ``gemini-3.1-pro-preview`` — this module wires
it into production.

Scope is deliberately Way 2 only. Way 1 (editorial escalation) uses a different
system block (``BRAIN_FIX_ONLY_SYSTEM``) with a forced-``ANY`` tool config, and
``cached_content`` is mutually exclusive with per-request
``system_instruction``/``tools``/``tool_config`` — so those calls stay uncached
(:meth:`packages.core.gemini.GeminiClient.generate_with_tools` bypasses the cache
for any non-default tool config rather than dropping the caller's constraint).

Failure posture: the cache is a COST optimisation, never a correctness dependency.
Any create failure logs loudly and disables caching for the process lifetime; a
``None`` handle simply means the caller sends the full uncached request. Enable with
``GEMINI_BRAIN_CACHE=1`` — code default is OFF until the live P0 gate records a real
``cached_content_token_count > 0`` (docker-compose defaults it ON for the VM).
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import Awaitable, Callable
from typing import Final, Protocol

import google.genai as genai
from google.genai import types as genai_types

from packages.core.gemini import GEMINI_PRO_3_1_MODEL, build_default_genai_client

logger = logging.getLogger(__name__)

BRAIN_CACHE_ENV: Final[str] = "GEMINI_BRAIN_CACHE"
BRAIN_CACHE_DISPLAY_NAME: Final[str] = "nashr-brain-context"
DEFAULT_BRAIN_CACHE_TTL_SECONDS: Final[int] = 3600
# A handle within this margin of its server-side TTL is treated as expired and
# recreated, so a turn never starts against a cache that dies mid-call.
CACHE_EXPIRY_MARGIN_SECONDS: Final[int] = 120
# Upper bound on the caches.create round-trip (see handle_for for why).
CACHE_CREATE_TIMEOUT_SECONDS: Final[int] = 30

_TRUTHY: Final[frozenset[str]] = frozenset({"1", "true", "yes", "on"})


def brain_cache_enabled() -> bool:
    """Whether the explicit brain context cache is enabled via ``GEMINI_BRAIN_CACHE``."""

    return os.environ.get(BRAIN_CACHE_ENV, "0").strip().lower() in _TRUTHY


class CreateCacheFn(Protocol):
    """Injectable cache-creation boundary (tests stub this; prod binds the SDK)."""

    def __call__(
        self,
        *,
        model: str,
        system_instruction: str,
        tools: list[genai_types.Tool],
        ttl_seconds: int,
        display_name: str,
    ) -> Awaitable[str]: ...


def _default_create_cache_fn() -> CreateCacheFn:
    """Bind ``client.aio.caches.create`` lazily so import/construction never needs creds."""

    client: genai.Client | None = None

    async def fn(
        *,
        model: str,
        system_instruction: str,
        tools: list[genai_types.Tool],
        ttl_seconds: int,
        display_name: str,
    ) -> str:
        nonlocal client
        if client is None:
            client = build_default_genai_client()
        cached = await client.aio.caches.create(
            model=model,
            config=genai_types.CreateCachedContentConfig(
                system_instruction=system_instruction,
                tools=list(tools),
                ttl=f"{ttl_seconds}s",
                display_name=display_name,
            ),
        )
        name = cached.name
        if not name:
            raise RuntimeError("Gemini cache create returned no cache name")
        return name

    return fn


class BrainContextCache:
    """Lazily-created explicit ``cached_content`` over ONE pinned system+tools block.

    :meth:`handle_for` returns the live cache name — creating it on first use and
    recreating it when the client-side expiry window (TTL minus
    :data:`CACHE_EXPIRY_MARGIN_SECONDS`) has passed — or ``None`` whenever the
    caller should send the full uncached request instead: caching disabled, a
    previous create failed (disabled for the process lifetime), or the caller's
    ``system`` does not byte-match the pinned block (a mismatched cache would
    silently answer with the WRONG rules, so bypass is the only safe response).

    The cache is model-bound: a handle created for ``model`` is only valid on
    generation calls to that same model. Expired caches are not deleted — the
    server reclaims them at TTL; deleting eagerly could race an in-flight call.
    """

    def __init__(
        self,
        *,
        system: str,
        tools: list[genai_types.Tool],
        model: str = GEMINI_PRO_3_1_MODEL,
        ttl_seconds: int = DEFAULT_BRAIN_CACHE_TTL_SECONDS,
        enabled: bool | None = None,
        create_cache_fn: CreateCacheFn | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._system = system
        self._tools = list(tools)
        self._model = model
        self._ttl_seconds = ttl_seconds
        self._enabled = brain_cache_enabled() if enabled is None else enabled
        self._create_cache_fn = create_cache_fn or _default_create_cache_fn()
        self._clock = clock
        self._name: str | None = None
        self._expires_at = 0.0
        self._failed = False
        self._mismatch_warned = False
        self._lock: asyncio.Lock | None = None
        self._lock_loop: asyncio.AbstractEventLoop | None = None

    def _loop_lock(self) -> asyncio.Lock:
        # An asyncio.Lock binds to the event loop that first awaits it, and this
        # object is a PROCESS-WIDE singleton that can outlive a loop (gate scripts
        # and successive asyncio.run() calls create fresh loops). Rebind the lock
        # when the running loop changes; loops in one thread run sequentially, so
        # cross-loop exclusion is not needed — worst case on the (untrue for this
        # codebase) multi-threaded-loops topology is a duplicate cache create,
        # a cost blip, never a correctness fault.
        loop = asyncio.get_running_loop()
        if self._lock is None or self._lock_loop is not loop:
            self._lock = asyncio.Lock()
            self._lock_loop = loop
        return self._lock

    @property
    def enabled(self) -> bool:
        """Whether this cache will ever hand out a handle."""

        return self._enabled and not self._failed

    @property
    def model(self) -> str:
        """The model this cache's handles are bound to."""

        return self._model

    async def handle_for(self, system: str) -> str | None:
        """Return the live cache name for ``system``, or ``None`` to send uncached."""

        if not self._enabled or self._failed:
            return None
        if system != self._system:
            if not self._mismatch_warned:
                self._mismatch_warned = True
                logger.warning(
                    "gemini_brain_cache_system_mismatch",
                    extra={"pinned_chars": len(self._system), "caller_chars": len(system)},
                )
            return None
        async with self._loop_lock():
            # Re-check under the lock (panel finding, 3 lenses): a waiter that
            # passed the pre-lock check while another caller's create was failing
            # must honor the process-lifetime disable, not re-hammer the API.
            if self._failed:
                return None
            now = self._clock()
            if self._name is not None and now < self._expires_at:
                return self._name
            try:
                # Bounded: this await runs BEFORE the generate call's own timeout
                # and (in the bot) under the per-session lock — an unbounded SDK
                # stall here would hang the user's turn. A timeout counts as a
                # create failure: worst case is ONE turn delayed by the bound,
                # then uncached for the process lifetime.
                self._name = await asyncio.wait_for(
                    self._create_cache_fn(
                        model=self._model,
                        system_instruction=self._system,
                        tools=self._tools,
                        ttl_seconds=self._ttl_seconds,
                        display_name=BRAIN_CACHE_DISPLAY_NAME,
                    ),
                    timeout=CACHE_CREATE_TIMEOUT_SECONDS,
                )
            except Exception:
                self._failed = True
                self._name = None
                logger.exception("gemini_brain_cache_create_failed — uncached for process lifetime")
                return None
            self._expires_at = now + self._ttl_seconds - CACHE_EXPIRY_MARGIN_SECONDS
            logger.info(
                "gemini_brain_cache_created",
                extra={
                    # Suffix only (panel finding): the full resource name is a
                    # usable cached_content handle for any same-project principal;
                    # logs need a correlation id, not the capability.
                    "cache_name_suffix": self._name[-12:],
                    "model": self._model,
                    "ttl_seconds": self._ttl_seconds,
                },
            )
            return self._name

    def invalidate(self) -> None:
        """Drop the current handle so the next :meth:`handle_for` recreates the cache."""

        self._name = None
        self._expires_at = 0.0


__all__ = [
    "BRAIN_CACHE_DISPLAY_NAME",
    "BRAIN_CACHE_ENV",
    "CACHE_EXPIRY_MARGIN_SECONDS",
    "DEFAULT_BRAIN_CACHE_TTL_SECONDS",
    "BrainContextCache",
    "CreateCacheFn",
    "brain_cache_enabled",
]
