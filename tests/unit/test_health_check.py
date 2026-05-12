"""Smoke test for the ``/health`` endpoint registered by ``build_aiohttp_app``.

Docker and load balancers probe ``/health`` to decide whether the
container is alive. The endpoint must always return HTTP 200 with a
JSON body containing ``status: ok`` even when nothing else (database,
LLM providers) is configured.
"""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_health_endpoint_returns_ok() -> None:
    """The /health route built by ``build_aiohttp_app`` returns 200 + JSON."""

    from unittest.mock import AsyncMock, MagicMock

    from aiogram import Dispatcher
    from aiogram.fsm.storage.memory import MemoryStorage
    from aiohttp.test_utils import TestClient, TestServer

    from packages.bot.app import build_aiohttp_app

    bot = MagicMock()
    bot.session = MagicMock()
    bot.session.close = AsyncMock(return_value=None)
    dp = Dispatcher(storage=MemoryStorage())

    app = build_aiohttp_app(bot, dp)

    async with TestClient(TestServer(app)) as client:
        resp = await client.get("/health")
        assert resp.status == 200
        body = await resp.json()
        assert body == {"status": "ok", "service": "nashr-bot", "version": "1.0.0"}
