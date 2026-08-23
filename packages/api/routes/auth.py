"""Auth routes: both identity doors + link/merge + whoami (plan §5).

Every response that grants access carries the SAME session shape
(:class:`packages.core.models.identity.MintedSession`); failures return a
machine-readable ``detail`` reason and never echo secrets or raw proofs.
"""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from packages.api.middleware.auth import Authenticated
from packages.api.services.identity import IdentityError, IdentityService
from packages.api.services.telegram_auth import InitDataError, validate_init_data
from packages.api.services.tokens import TokenError
from packages.core.models.identity import MintedSession

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

# Telegram caps initData well under this; the bound only rejects abuse payloads.
_INIT_DATA_MAX_CHARS = 8192


class TelegramLoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    init_data: str = Field(min_length=1, max_length=_INIT_DATA_MAX_CHARS)


class EmailExchangeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    supabase_access_token: str = Field(min_length=1, max_length=4096)


class LinkTelegramResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    merged: bool
    session: MintedSession


class WhoAmIResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str


def _service(request: Request) -> IdentityService:
    return request.app.state.identity_service


def _mint_or_503(service: IdentityService, user_id: UUID) -> MintedSession:
    try:
        return service.mint_session(user_id)
    except TokenError as exc:
        # server_missing_jwt_secret: a deployment fault, not a client one.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=exc.reason
        ) from exc


@router.post("/telegram", response_model=MintedSession)
async def telegram_login(request: Request, body: TelegramLoginRequest) -> MintedSession:
    """Telegram door: validate Mini App initData, resolve the user, mint a session."""

    try:
        payload = validate_init_data(body.init_data, request.app.state.config.telegram_bot_token)
    except InitDataError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=exc.reason) from exc
    service = _service(request)
    user_id = await service.resolve_telegram(payload)
    return _mint_or_503(service, user_id)


@router.post("/email/exchange", response_model=MintedSession)
async def email_exchange(request: Request, body: EmailExchangeRequest) -> MintedSession:
    """Email door: verify the Supabase magic-link session, exchange for the app session."""

    service = _service(request)
    try:
        user_id = await service.resolve_email_exchange(body.supabase_access_token)
    except IdentityError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=exc.reason) from exc
    return _mint_or_503(service, user_id)


@router.post("/link/telegram", response_model=LinkTelegramResponse)
async def link_telegram(
    request: Request, body: TelegramLoginRequest, auth: Authenticated
) -> LinkTelegramResponse:
    """Attach a proven Telegram identity to the authenticated user (merge if needed)."""

    try:
        payload = validate_init_data(body.init_data, request.app.state.config.telegram_bot_token)
    except InitDataError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=exc.reason) from exc
    service = _service(request)
    merged = await service.link_telegram(auth.user_id, payload)
    return LinkTelegramResponse(merged=merged, session=_mint_or_503(service, auth.user_id))


@router.post("/refresh", response_model=MintedSession)
async def refresh_session(request: Request, auth: Authenticated) -> MintedSession:
    """Re-mint the session token for a caller whose current one is still valid.

    A SLIDING session, not a refresh-token scheme: no second credential is
    introduced, so the stored-token surface stays exactly one short-lived JWT.
    The consequence is that this cannot rescue an ALREADY-expired token — the
    ``Authenticated`` dependency rejects it first — so the web must refresh
    PROACTIVELY (before ``expires_at``) and treat a 401-triggered attempt as a
    fallback that will usually fail. Documented rather than papered over.
    """

    return _mint_or_503(_service(request), auth.user_id)


@router.get("/me", response_model=WhoAmIResponse)
async def whoami(auth: Authenticated) -> WhoAmIResponse:
    """Return the verified identity of the current session."""

    return WhoAmIResponse(user_id=str(auth.user_id))
