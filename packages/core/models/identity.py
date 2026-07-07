"""Identity models for the web platform's auth surface (plan §5, migration 005).

The canonical identity is ``users.id``; these models cover the mapping rows
(:class:`AuthIdentity`), the validated Telegram Mini App login payload
(:class:`TelegramAuthPayload`), the verified request identity
(:class:`AuthContext`), and a minted app session (:class:`MintedSession`).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from packages.core.enums import IdentityProvider

# Telegram usernames cap at 32 chars and first names at 64; external ids are a
# telegram id (<= 20 digits) or an RFC-length email (254).
_EXTERNAL_ID_MAX: int = 254


class AuthIdentity(BaseModel):
    """One row of ``user_auth_identities`` — an external identity → users.id link."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: UUID
    provider: IdentityProvider
    external_id: str = Field(min_length=1, max_length=_EXTERNAL_ID_MAX)
    user_id: UUID
    auth_user_id: UUID | None = None
    created_at: datetime


class TelegramAuthPayload(BaseModel):
    """The fields the API trusts from a VALIDATED Mini App ``initData`` string.

    Constructed only by ``validate_init_data`` after the HMAC and freshness
    checks pass — holding one of these means the login proof already succeeded.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    telegram_id: int = Field(gt=0)
    username: str | None = Field(None, max_length=32)
    first_name: str | None = Field(None, max_length=64)
    auth_date: datetime


class AuthContext(BaseModel):
    """The verified identity attached to an authenticated API request."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    user_id: UUID


class MintedSession(BaseModel):
    """An app session token minted for a resolved user (Path A HS256 JWT)."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    access_token: str = Field(min_length=1, max_length=4096)
    token_type: str = "bearer"
    expires_at: datetime
    user_id: UUID
