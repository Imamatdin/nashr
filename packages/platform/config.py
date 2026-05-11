"""Platform configuration. Reads from environment variables.

A single immutable dataclass holds every credential and endpoint the
platform layer needs. Frozen so accidental mutation cannot leak between
services. ``from_env`` is the only construction path used in production;
tests construct directly with explicit values.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class PlatformConfig:
    """Environment-derived configuration for the platform layer.

    Credential fields default to empty strings rather than ``None`` so a
    misconfigured deployment surfaces as an auth error from the relevant
    provider rather than a TypeError deep in client construction.
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

    @classmethod
    def from_env(cls) -> PlatformConfig:
        """Build a config from process environment variables."""

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
        )
