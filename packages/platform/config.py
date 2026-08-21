"""Platform configuration. Reads from environment variables.

A single immutable dataclass holds every credential and endpoint the
platform layer needs. Frozen so accidental mutation cannot leak between
services. ``from_env`` is the only construction path used in production;
tests construct directly with explicit values.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _parse_admin_ids(raw: str) -> tuple[int, ...]:
    """Parse a comma-separated list of Telegram user IDs.

    Whitespace around each entry is tolerated. Non-numeric entries are
    silently skipped so a typo in one ID does not lock every admin out
    of the bot.
    """

    out: list[int] = []
    for piece in raw.split(","):
        token = piece.strip()
        if token.isdigit():
            out.append(int(token))
    return tuple(out)


@dataclass(frozen=True)
class PlatformConfig:
    """Environment-derived configuration for the platform layer.

    Credential fields default to empty strings rather than ``None`` so a
    misconfigured deployment surfaces as an auth error from the relevant
    provider rather than a TypeError deep in client construction.
    ``dev_mode`` and ``admin_telegram_ids`` exist so the bot can offer
    free generations and admin-only credit grants during local testing
    without breaking the prod-grade balance enforcement.
    """

    supabase_url: str
    supabase_service_key: str
    telegram_bot_token: str
    redis_url: str = "redis://localhost:6379"
    r2_endpoint: str = ""
    r2_access_key: str = ""
    r2_secret_key: str = ""
    r2_bucket: str = "nashr-files"
    payme_merchant_id: str = ""
    payme_secret_key: str = ""
    click_merchant_id: str = ""
    click_secret_key: str = ""
    click_service_id: str = ""
    # DEPRECATED: dead since the in-bot flow decision; no handler reads it. Do not delete.
    mini_app_base_url: str = "https://nashr.uz"
    webhook_url: str = ""
    webhook_port: int = 8080
    dev_mode: bool = False
    admin_telegram_ids: tuple[int, ...] = field(default_factory=tuple)
    # --- web platform (packages/api) ---
    supabase_anon_key: str = ""
    # The project's legacy shared HS256 JWT secret — identity Path A mints
    # session JWTs with it. Empty ⇒ the auth surface refuses to mint (fail
    # closed) rather than falling back to an insecure default.
    supabase_jwt_secret: str = ""
    app_jwt_ttl_seconds: int = 3600
    web_cors_origins: tuple[str, ...] = field(default_factory=tuple)

    @classmethod
    def from_env(cls) -> PlatformConfig:
        """Build a config from process environment variables.

        ``NASHR_ENV=development`` flips :attr:`dev_mode` on so generation
        flows skip balance checks; any other value (including unset)
        keeps production behaviour.
        """

        dev_mode = os.environ.get("NASHR_ENV", "production").strip().lower() == "development"
        admin_ids = _parse_admin_ids(os.environ.get("NASHR_ADMIN_IDS", ""))

        return cls(
            supabase_url=os.environ.get("SUPABASE_URL", ""),
            supabase_service_key=os.environ.get("SUPABASE_SERVICE_KEY", ""),
            telegram_bot_token=os.environ.get("TELEGRAM_BOT_TOKEN", ""),
            redis_url=os.environ.get("REDIS_URL", "redis://localhost:6379"),
            r2_endpoint=os.environ.get("R2_ENDPOINT", ""),
            r2_access_key=os.environ.get("R2_ACCESS_KEY", ""),
            r2_secret_key=os.environ.get("R2_SECRET_KEY", ""),
            r2_bucket=os.environ.get("R2_BUCKET", "nashr-files"),
            payme_merchant_id=os.environ.get("PAYME_MERCHANT_ID", ""),
            payme_secret_key=os.environ.get("PAYME_SECRET_KEY", ""),
            click_merchant_id=os.environ.get("CLICK_MERCHANT_ID", ""),
            click_secret_key=os.environ.get("CLICK_SECRET_KEY", ""),
            click_service_id=os.environ.get("CLICK_SERVICE_ID", ""),
            mini_app_base_url=os.environ.get("MINI_APP_BASE_URL", "https://nashr.uz"),
            webhook_url=os.environ.get("WEBHOOK_URL", ""),
            webhook_port=_parse_port(os.environ.get("WEBHOOK_PORT", "8080")),
            dev_mode=dev_mode,
            admin_telegram_ids=admin_ids,
            supabase_anon_key=os.environ.get("SUPABASE_ANON_KEY", ""),
            supabase_jwt_secret=os.environ.get("SUPABASE_JWT_SECRET", ""),
            app_jwt_ttl_seconds=_parse_ttl(os.environ.get("APP_JWT_TTL_SECONDS", "3600")),
            web_cors_origins=_parse_origins(os.environ.get("WEB_CORS_ORIGINS", "")),
        )


def _parse_port(raw: str) -> int:
    """Parse a port string, falling back to 8080 on garbage input."""

    try:
        port = int(raw)
    except ValueError:
        return 8080
    if port < 1 or port > 65535:
        return 8080
    return port


def _parse_ttl(raw: str) -> int:
    """Parse a session-TTL string in seconds, falling back to one hour."""

    try:
        ttl = int(raw)
    except ValueError:
        return 3600
    if ttl < 60 or ttl > 86_400:
        return 3600
    return ttl


def _parse_origins(raw: str) -> tuple[str, ...]:
    """Parse a comma-separated CORS origin allowlist; blanks and wildcards dropped.

    The web contract is an explicit allowlist — a ``*`` entry is dropped (panel
    finding) so a stray ``WEB_CORS_ORIGINS=*`` cannot open bearer-auth endpoints
    to every origin. An empty result means CORS middleware is not installed.
    """

    return tuple(
        origin
        for piece in raw.split(",")
        if (origin := piece.strip().rstrip("/")) and origin != "*"
    )
