"""Bearer-token authentication dependency for the FastAPI surface (plan §5)."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

from packages.api.services.tokens import TokenError, verify_app_jwt
from packages.core.models.identity import AuthContext


def require_auth(request: Request) -> AuthContext:
    """Resolve the request's bearer token to a verified :class:`AuthContext`.

    401 carries the machine-readable reason (never key material) so the web
    client can distinguish an expired session from a malformed one.
    """

    header = request.headers.get("Authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="missing_bearer_token")
    secret: str = request.app.state.config.supabase_jwt_secret
    try:
        return verify_app_jwt(secret, token.strip())
    except TokenError as exc:
        # A missing server secret is a DEPLOYMENT fault, not bad client auth
        # (panel finding): surface it as 503, matching _mint_or_503 on the mint
        # side, instead of mislabeling it 401.
        if exc.reason == "server_missing_jwt_secret":
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=exc.reason
            ) from exc
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=exc.reason) from exc


Authenticated = Annotated[AuthContext, Depends(require_auth)]
