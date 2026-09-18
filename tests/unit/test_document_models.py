"""Validation tests for the canonical editable article schema."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from packages.core.models.document import ArticleBlock, ArticleBlockType, ArticleDocumentContent


def test_article_blocks_have_stable_unique_ids() -> None:
    """Duplicate edit targets are rejected before persistence."""

    block_id = uuid4()
    with pytest.raises(ValidationError, match="block ids must be unique"):
        ArticleDocumentContent(
            title="Learning",
            blocks=[ArticleBlock(id=block_id, text="One"), ArticleBlock(id=block_id, text="Two")],
        )


def test_heading_gets_a_default_level() -> None:
    """A heading can be created without exposing schema details to the UI."""

    block = ArticleBlock(type=ArticleBlockType.HEADING, text="Methods")
    assert block.level == 2


def test_non_heading_cannot_carry_a_heading_level() -> None:
    """Invalid block attributes do not enter revision history."""

    with pytest.raises(ValidationError, match="only valid for heading"):
        ArticleBlock(type=ArticleBlockType.PARAGRAPH, text="Body", level=2)
