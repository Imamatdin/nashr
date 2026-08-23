"""FastAPI application factory for the Nashr web backend (plan §4/§5, P1).

The API is the privileged tier: it holds the bot token, service key, and JWT
secret; the Vercel-hosted web app holds only the anon key. CORS is an explicit
env-driven allowlist (``WEB_CORS_ORIGINS``) — no wildcard, credentials never
needed because auth rides the Authorization header.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from packages.api.routes.auth import router as auth_router
from packages.api.routes.chat import router as chat_router
from packages.api.routes.credits import router as credits_router
from packages.api.routes.jobs import router as jobs_router
from packages.api.routes.projects import router as projects_router
from packages.api.routes.public import router as public_router
from packages.api.routes.sources import router as sources_router
from packages.api.services.identity import IdentityService
from packages.platform.config import PlatformConfig
from packages.platform.credits import CreditLedger
from packages.platform.database import DatabaseClient
from packages.platform.jobs import JobQueue
from packages.platform.rate_limit import RateLimiter
from packages.platform.storage import FileStorage

logger = logging.getLogger(__name__)


def create_app(
    config: PlatformConfig | None = None,
    db: DatabaseClient | None = None,
    identity_service: IdentityService | None = None,
    credits: CreditLedger | None = None,
    job_queue: JobQueue | None = None,
    rate_limiter: RateLimiter | None = None,
    storage: FileStorage | None = None,
    brain_driver_factory: Callable[[], Any] | None = None,
) -> FastAPI:
    """Build the API app; tests inject config/db/service, production uses env."""

    resolved_config = config if config is not None else PlatformConfig.from_env()
    resolved_db = db if db is not None else DatabaseClient(resolved_config)
    resolved_identity = (
        identity_service
        if identity_service is not None
        else IdentityService(resolved_config, resolved_db)
    )
    resolved_credits = (
        credits
        if credits is not None
        else CreditLedger(resolved_db, dev_mode=resolved_config.dev_mode)
    )

    app = FastAPI(title="Nashr API", docs_url=None, redoc_url=None)
    app.state.config = resolved_config
    app.state.db = resolved_db
    app.state.identity_service = resolved_identity
    app.state.credits = resolved_credits
    app.state.job_queue = job_queue if job_queue is not None else JobQueue(resolved_db)
    app.state.rate_limiter = rate_limiter if rate_limiter is not None else RateLimiter(resolved_db)
    app.state.storage = storage if storage is not None else FileStorage(resolved_config)
    # None means "build the real Gemini brain lazily, per turn" (see
    # packages/api/routes/chat.py::_driver). Tests inject a scripted stub.
    app.state.brain_driver_factory = brain_driver_factory

    if resolved_config.web_cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(resolved_config.web_cors_origins),
            allow_methods=["GET", "POST"],
            allow_headers=["Authorization", "Content-Type"],
        )

    app.include_router(auth_router)
    app.include_router(credits_router)
    app.include_router(chat_router)
    app.include_router(jobs_router)
    app.include_router(sources_router)
    app.include_router(projects_router)
    app.include_router(public_router)
    app.add_api_route("/health", _health, methods=["GET"])

    return app


async def _health() -> dict[str, str]:
    return {"status": "ok", "service": "nashr-api"}
