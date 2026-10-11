"""Print shell exports for the disposable local stack; every value is a local constant.

Usage: ``eval "$(python scripts/local_stack/local_env.py)"``. Never point this at
production: the URLs are loopback-only and the keys are minted from a local secret.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

JWT_SECRET = "local-only-jwt-secret-not-for-production-0000"
REST_URL = "http://127.0.0.1:54321"
S3_URL = "http://127.0.0.1:54322"
WEB_ORIGIN = "http://127.0.0.1:3100"


def _b64(data: bytes) -> str:
    """Encode unpadded base64url."""

    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def role_key(role: str) -> str:
    """Mint a long-lived HS256 PostgREST key for ``role`` from the local secret."""

    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    claims = {"role": role, "iss": "supabase", "exp": int(time.time()) + 30 * 86_400}
    body = _b64(json.dumps(claims).encode())
    signature = hmac.new(JWT_SECRET.encode(), f"{header}.{body}".encode(), hashlib.sha256)
    return f"{header}.{body}.{_b64(signature.digest())}"


def exports() -> dict[str, str]:
    """Return the environment the API, worker and web need for the local stack."""

    return {
        "NASHR_ENV": "development",
        "SUPABASE_URL": REST_URL,
        "SUPABASE_SERVICE_KEY": role_key("service_role"),
        "SUPABASE_ANON_KEY": role_key("anon"),
        "SUPABASE_JWT_SECRET": JWT_SECRET,
        "R2_ENDPOINT": S3_URL,
        "R2_ACCESS_KEY": "local-access",
        "R2_SECRET_KEY": "local-secret",
        "R2_BUCKET": "nashr-local",
        "WEB_CORS_ORIGINS": WEB_ORIGIN,
        "NEXT_PUBLIC_API_BASE_URL": "http://127.0.0.1:8090",
        "NEXT_PUBLIC_SUPABASE_URL": REST_URL,
        "NEXT_PUBLIC_SUPABASE_ANON_KEY": role_key("anon"),
    }


if __name__ == "__main__":
    for name, value in exports().items():
        print(f"export {name}='{value}'")
