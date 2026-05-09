"""Project models — a project is the user-facing container for sources, articles, and decks."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from packages.core.enums import Audience, Language, ProjectStatus, ProjectType


class ProjectCreate(BaseModel):
    """Payload sent by the bot or API when creating a new project."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    user_id: UUID
    type: ProjectType
    title: str = Field(min_length=1, max_length=200)
    language: Language
    audience: Audience


class Project(BaseModel):
    """Persisted project record."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: UUID = Field(default_factory=uuid4)
    user_id: UUID
    type: ProjectType
    title: str = Field(min_length=1, max_length=200)
    language: Language
    audience: Audience
    status: ProjectStatus = ProjectStatus.DRAFT
    created_at: datetime
    updated_at: datetime
