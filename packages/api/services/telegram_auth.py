"""Telegram Mini App ``initData`` validation (plan §5, Telegram door).

Implements the documented Web App scheme: the data-check string is every
``key=value`` pair EXCEPT ``hash``, sorted by key and joined with newlines;
the signing key is ``HMAC_SHA256(key="WebAppData", msg=bot_token)``; the
provided ``hash`` must equal ``HMAC_SHA256(key=secret, msg=data_check_string)``
hex, compared constant-time. ``auth_date`` older than the freshness window is
a replay and is rejected even with a valid signature.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import UTC, datetime
from typing import Final
from urllib.parse import parse_qsl

from packages.core.models.identity import TelegramAuthPayload

INIT_DATA_MAX_AGE_SECONDS: Final[int] = 300  # plan §5: auth_date ≤ 5 min


class InitDataError(ValueError):
    """A failed initData proof; ``reason`` is machine-readable, never secret-bearing."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def validate_init_data(
    init_data: str,
    bot_token: str,
    *,
    max_age_seconds: int = INIT_DATA_MAX_AGE_SECONDS,
    now: float | None = None,
) -> TelegramAuthPayload:
    """Validate a raw ``initData`` query string and return the trusted payload.

    Raises :class:`InitDataError` with reason ``missing_hash`` / ``bad_signature``
    / ``missing_auth_date`` / ``stale_auth_date`` / ``missing_user`` /
    ``malformed_user``. Only a fully-verified string yields a payload.
    """

    if not bot_token:
        # Refusing to validate beats validating against an empty key.
        raise InitDataError("server_missing_bot_token")

    pairs = parse_qsl(init_data, keep_blank_values=True)
    fields = dict(pairs)
    provided_hash = fields.pop("hash", "")
    if not provided_hash:
        raise InitDataError("missing_hash")

    data_check_string = "\n".join(f"{key}={value}" for key, value in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected_hash = hmac.new(secret, data_check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected_hash, provided_hash):
        raise InitDataError("bad_signature")

    raw_auth_date = fields.get("auth_date", "")
    if not raw_auth_date.isdigit():
        raise InitDataError("missing_auth_date")
    auth_date = int(raw_auth_date)
    current = time.time() if now is None else now
    if current - auth_date > max_age_seconds:
        raise InitDataError("stale_auth_date")

    raw_user = fields.get("user", "")
    if not raw_user:
        raise InitDataError("missing_user")
    try:
        user = json.loads(raw_user)
        telegram_id = int(user["id"])
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise InitDataError("malformed_user") from exc

    return TelegramAuthPayload(
        telegram_id=telegram_id,
        username=user.get("username"),
        first_name=user.get("first_name"),
        auth_date=datetime.fromtimestamp(auth_date, tz=UTC),
    )
