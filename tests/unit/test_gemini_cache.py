"""Unit tests for the explicit brain context cache (5B-Q5b).

The SDK boundary (``caches.create``) is stubbed via the injectable
``create_cache_fn``; a fake clock drives expiry. Behaviours locked here: the
env gate, lazy single creation, reuse within the TTL window, recreation after
client-side expiry (TTL minus margin), fail-once-disable-for-process,
pinned-system mismatch bypass, and invalidate().
"""

from __future__ import annotations

from typing import Any

import pytest
from google.genai import types as genai_types

from packages.core.gemini_cache import (
    BRAIN_CACHE_ENV,
    CACHE_EXPIRY_MARGIN_SECONDS,
    BrainContextCache,
    brain_cache_enabled,
)

_SYSTEM = "brain rules " * 50
_TOOLS = [
    genai_types.Tool(
        function_declarations=[
            genai_types.FunctionDeclaration(name="edit_slides", description="Request edits.")
        ]
    )
]


class _FakeCreate:
    """Injectable create_cache_fn recording calls and returning sequential names."""

    def __init__(self, fail: bool = False) -> None:
        self.calls: list[dict[str, Any]] = []
        self.fail = fail

    async def __call__(
        self,
        *,
        model: str,
        system_instruction: str,
        tools: list[genai_types.Tool],
        ttl_seconds: int,
        display_name: str,
    ) -> str:
        self.calls.append(
            {
                "model": model,
                "system_instruction": system_instruction,
                "tools": tools,
                "ttl_seconds": ttl_seconds,
                "display_name": display_name,
            }
        )
        if self.fail:
            raise RuntimeError("cache API down")
        return f"cachedContents/fake-{len(self.calls)}"


class _FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _cache(
    *,
    enabled: bool = True,
    create: _FakeCreate | None = None,
    clock: _FakeClock | None = None,
    ttl_seconds: int = 3600,
) -> tuple[BrainContextCache, _FakeCreate, _FakeClock]:
    create = create or _FakeCreate()
    clock = clock or _FakeClock()
    cache = BrainContextCache(
        system=_SYSTEM,
        tools=_TOOLS,
        enabled=enabled,
        create_cache_fn=create,
        clock=clock,
        ttl_seconds=ttl_seconds,
    )
    return cache, create, clock


def test_env_gate_defaults_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(BRAIN_CACHE_ENV, raising=False)
    assert brain_cache_enabled() is False
    monkeypatch.setenv(BRAIN_CACHE_ENV, "1")
    assert brain_cache_enabled() is True
    monkeypatch.setenv(BRAIN_CACHE_ENV, "0")
    assert brain_cache_enabled() is False
    monkeypatch.setenv(BRAIN_CACHE_ENV, "true")
    assert brain_cache_enabled() is True


@pytest.mark.asyncio
async def test_disabled_cache_hands_out_no_handle() -> None:
    cache, create, _ = _cache(enabled=False)
    assert await cache.handle_for(_SYSTEM) is None
    assert create.calls == []
    assert cache.enabled is False


@pytest.mark.asyncio
async def test_creates_once_and_reuses_within_ttl() -> None:
    cache, create, clock = _cache()
    first = await cache.handle_for(_SYSTEM)
    assert first == "cachedContents/fake-1"
    clock.now += 100
    second = await cache.handle_for(_SYSTEM)
    assert second == first
    assert len(create.calls) == 1
    assert create.calls[0]["system_instruction"] == _SYSTEM
    assert create.calls[0]["tools"] == _TOOLS


@pytest.mark.asyncio
async def test_recreates_after_client_side_expiry() -> None:
    cache, create, clock = _cache(ttl_seconds=3600)
    first = await cache.handle_for(_SYSTEM)
    # Client-side lifetime is TTL minus the safety margin — a handle inside the
    # margin is treated as dead so a turn never starts on a cache about to expire.
    clock.now += 3600 - CACHE_EXPIRY_MARGIN_SECONDS + 1
    second = await cache.handle_for(_SYSTEM)
    assert second == "cachedContents/fake-2"
    assert second != first
    assert len(create.calls) == 2


@pytest.mark.asyncio
async def test_create_failure_disables_for_process_lifetime() -> None:
    create = _FakeCreate(fail=True)
    cache, _, _ = _cache(create=create)
    assert await cache.handle_for(_SYSTEM) is None
    assert cache.enabled is False
    # Second call must NOT hammer the failing API again.
    assert await cache.handle_for(_SYSTEM) is None
    assert len(create.calls) == 1


@pytest.mark.asyncio
async def test_system_mismatch_bypasses_cache() -> None:
    cache, create, _ = _cache()
    assert await cache.handle_for("a different system block") is None
    assert create.calls == []
    # The pinned block still works afterwards.
    assert await cache.handle_for(_SYSTEM) == "cachedContents/fake-1"


@pytest.mark.asyncio
async def test_invalidate_forces_recreation() -> None:
    cache, create, _ = _cache()
    first = await cache.handle_for(_SYSTEM)
    cache.invalidate()
    second = await cache.handle_for(_SYSTEM)
    assert first != second
    assert len(create.calls) == 2


def test_singleton_survives_successive_event_loops() -> None:
    # Codex round-2 RISK: the process-wide singleton outlives an event loop
    # (gate scripts, successive asyncio.run). The internal lock must rebind to
    # the running loop instead of raising "bound to a different event loop".
    import asyncio

    cache, _, _ = _cache()

    first = asyncio.run(cache.handle_for(_SYSTEM))
    second = asyncio.run(cache.handle_for(_SYSTEM))

    assert first == "cachedContents/fake-1"
    assert second == first


@pytest.mark.asyncio
async def test_concurrent_cold_start_failure_creates_exactly_once() -> None:
    # Panel finding (3 lenses): a waiter that passed the pre-lock _failed check
    # while another caller's create was failing must NOT re-call the API — the
    # in-lock re-check enforces the process-lifetime disable.
    import asyncio

    release = asyncio.Event()

    class _BlockingFailCreate(_FakeCreate):
        async def __call__(self, **kwargs: Any) -> str:
            self.calls.append(kwargs)
            await release.wait()
            raise RuntimeError("cache API down")

    create = _BlockingFailCreate()
    cache = BrainContextCache(system=_SYSTEM, tools=_TOOLS, enabled=True, create_cache_fn=create)

    first = asyncio.create_task(cache.handle_for(_SYSTEM))
    await asyncio.sleep(0)  # first caller is now blocked inside the lock
    second = asyncio.create_task(cache.handle_for(_SYSTEM))
    await asyncio.sleep(0)  # second caller passed the pre-lock check, waits on the lock
    release.set()

    assert await first is None
    assert await second is None
    assert len(create.calls) == 1


@pytest.mark.asyncio
async def test_create_timeout_counts_as_failure_and_disables() -> None:
    # Panel finding: caches.create had no bound — a stalled SDK call would hang
    # the user's turn under the session lock. Timeout ⇒ create failure.
    import asyncio

    from packages.core import gemini_cache as cache_module

    class _HangingCreate(_FakeCreate):
        async def __call__(self, **kwargs: Any) -> str:
            self.calls.append(kwargs)
            await asyncio.sleep(3600)
            return "never"

    create = _HangingCreate()
    cache = BrainContextCache(system=_SYSTEM, tools=_TOOLS, enabled=True, create_cache_fn=create)
    original = cache_module.CACHE_CREATE_TIMEOUT_SECONDS
    try:
        cache_module.CACHE_CREATE_TIMEOUT_SECONDS = 0  # type: ignore[misc]
        assert await cache.handle_for(_SYSTEM) is None
    finally:
        cache_module.CACHE_CREATE_TIMEOUT_SECONDS = original  # type: ignore[misc]
    assert cache.enabled is False
