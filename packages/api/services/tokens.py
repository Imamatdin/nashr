"""App session JWTs — identity Path A mint/verify (plan §5).

Mints Supabase-compatible HS256 JWTs with ``sub = users.id`` and
``role = authenticated`` so every existing ``auth.uid()``-keyed RLS policy
works unchanged, and verifies the same shape on inbound API requests.
Stdlib-only on purpose: one signing scheme, no dependency surface.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import time
from datetime import UTC, datetime
from uuid import UUID

from packages.core.models.identity import AuthContext, MintedSession


class TokenError(ValueError):
    """A rejected session token; ``reason`` is machine-readable."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


# The issuer marker that distinguishes an APP session from a raw Supabase GoTrue
# token (panel finding): GoTrue tokens also carry aud=role=authenticated, so
# without an issuer check a user could send their Supabase access token directly
# as a bearer and be accepted as an authenticated app session.
_APP_JWT_ISSUER: str = "nashr-api"


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def mint_app_jwt(secret: str, user_id: UUID, ttl_seconds: int) -> MintedSession:
    """Mint the Path A session token for a resolved app user."""

    if not secret:
        # Fail closed: an unset secret must never silently mint unverifiable tokens.
        raise TokenError("server_missing_jwt_secret")
    now = int(time.time())
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "sub": str(user_id),
        "role": "authenticated",
        "aud": "authenticated",
        "iss": _APP_JWT_ISSUER,
        "iat": now,
        "exp": now + ttl_seconds,
    }
    signing_input = (
        _b64url_encode(json.dumps(header, separators=(",", ":")).encode())
        + "."
        + _b64url_encode(json.dumps(payload, separators=(",", ":")).encode())
    )
    signature = hmac.new(secret.encode(), signing_input.encode(), hashlib.sha256).digest()
    return MintedSession(
        access_token=f"{signing_input}.{_b64url_encode(signature)}",
        expires_at=datetime.fromtimestamp(now + ttl_seconds, tz=UTC),
        user_id=user_id,
    )


def verify_app_jwt(secret: str, token: str, *, now: float | None = None) -> AuthContext:
    """Verify signature, expiry, audience, and role; return the request identity.

    Raises :class:`TokenError` with reason ``malformed`` / ``wrong_alg`` /
    ``bad_signature`` / ``expired`` / ``wrong_audience`` / ``wrong_role`` /
    ``wrong_issuer`` / ``bad_subject`` / ``server_missing_jwt_secret``.
    """

    if not secret:
        raise TokenError("server_missing_jwt_secret")
    parts = token.split(".")
    if len(parts) != 3:
        raise TokenError("malformed")
    # Pin the header alg to HS256 BEFORE verifying (panel finding): defense in
    # depth against alg-confusion. The HMAC below only proves the holder knows
    # the shared secret; an explicit alg check refuses `none`/`RS256`-shaped
    # tokens outright rather than relying on the verifier's fixed algorithm.
    try:
        header = json.loads(_b64url_decode(parts[0]))
    except (binascii.Error, ValueError, json.JSONDecodeError) as exc:
        raise TokenError("malformed") from exc
    if header.get("alg") != "HS256" or header.get("typ") != "JWT":
        raise TokenError("wrong_alg")
    signing_input = f"{parts[0]}.{parts[1]}"
    try:
        expected = hmac.new(secret.encode(), signing_input.encode(), hashlib.sha256).digest()
        provided = _b64url_decode(parts[2])
    except (binascii.Error, ValueError) as exc:
        raise TokenError("malformed") from exc
    if not hmac.compare_digest(expected, provided):
        raise TokenError("bad_signature")
    try:
        payload = json.loads(_b64url_decode(parts[1]))
    except (binascii.Error, ValueError, json.JSONDecodeError) as exc:
        raise TokenError("malformed") from exc
    current = time.time() if now is None else now
    if not isinstance(payload.get("exp"), int) or payload["exp"] <= current:
        raise TokenError("expired")
    if payload.get("aud") != "authenticated":
        raise TokenError("wrong_audience")
    if payload.get("role") != "authenticated":
        raise TokenError("wrong_role")
    # Issuer marker (panel finding): reject anything not minted by this API,
    # e.g. a raw Supabase GoTrue token that happens to share the same secret
    # and the authenticated aud/role.
    if payload.get("iss") != _APP_JWT_ISSUER:
        raise TokenError("wrong_issuer")
    try:
        user_id = UUID(str(payload.get("sub")))
    except ValueError as exc:
        raise TokenError("bad_subject") from exc
    return AuthContext(user_id=user_id)
