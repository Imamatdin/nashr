"""Versioned authoring document models shared by API and workers."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ArticleBlockType(StrEnum):
    """Block types supported by the first article editor schema."""

    PARAGRAPH = "paragraph"
    HEADING = "heading"
    QUOTE = "quote"
    BULLET = "bullet"


class DocumentCitation(BaseModel):
    """A visible link from authored text to one persisted source claim."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    source_id: UUID
    claim_id: UUID
    label: str = Field(min_length=1, max_length=300)


class ArticleBlock(BaseModel):
    """One stable, directly editable article block."""

    model_config = ConfigDict(extra="forbid")

    id: UUID = Field(default_factory=uuid4)
    type: ArticleBlockType = ArticleBlockType.PARAGRAPH
    text: str = Field(default="", max_length=20_000)
    level: int | None = Field(default=None, ge=1, le=3)
    citations: list[DocumentCitation] = Field(
        default_factory=list[DocumentCitation], max_length=100
    )

    @model_validator(mode="after")
    def heading_level_matches_type(self) -> ArticleBlock:
        """Only headings carry levels; every heading gets one."""

        if self.type is ArticleBlockType.HEADING and self.level is None:
            self.level = 2
        if self.type is not ArticleBlockType.HEADING and self.level is not None:
            raise ValueError("level is only valid for heading blocks")
        return self


class ArticleDocumentContent(BaseModel):
    """Canonical content saved in each immutable article revision."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["article"] = "article"
    schema_version: Literal[1] = 1
    title: str = Field(min_length=1, max_length=300)
    blocks: list[ArticleBlock] = Field(default_factory=list[ArticleBlock], max_length=1_000)

    @model_validator(mode="after")
    def block_identity_and_size_are_bounded(self) -> ArticleDocumentContent:
        """Keep edit targets unique and reject unreasonably large request bodies."""

        ids = [block.id for block in self.blocks]
        if len(ids) != len(set(ids)):
            raise ValueError("article block ids must be unique")
        if sum(len(block.text) for block in self.blocks) > 1_000_000:
            raise ValueError("article document text exceeds 1,000,000 characters")
        return self
