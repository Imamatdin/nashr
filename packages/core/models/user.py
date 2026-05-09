"""User-account models."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from packages.core.enums import Language, PrimaryUse


class UserCreate(BaseModel):
    """Payload accepted when registering a Telegram user for the first time."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    telegram_id: int = Field(gt=0, description="Telegram user ID (positive 64-bit int).")
    username: str | None = Field(default=None, max_length=64)
    first_name: str | None = Field(default=None, max_length=128)
    language: Language = Language.UZ
    primary_use: PrimaryUse = PrimaryUse.STUDY


class User(BaseModel):
    """Persisted user record returned by the API."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: UUID = Field(default_factory=uuid4)
    telegram_id: int = Field(gt=0)
    username: str | None = Field(default=None, max_length=64)
    first_name: str | None = Field(default=None, max_length=128)
    language: Language
    primary_use: PrimaryUse
    created_at: datetime
