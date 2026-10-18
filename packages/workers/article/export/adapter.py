"""Adapter from the bot's drafted-article shape onto the one exporter's input.

The bot drafts into :class:`ArticleDraftResult` (sections of paragraphs with
inline ``[<source_id>]`` markers and :class:`CitationRef` links) plus an
:class:`ArticleExportMetadata`. This module converts that into the canonical
:class:`ArticleExportInput` so the bot renders through the same builder as the
web, with no second exporter. Inline markers are lifted into canonical
block-level citations (ADR 0001 citation model); the builder re-emits them as
in-text markers, so they are never doubled or left raw.
"""

from __future__ import annotations

import re
from typing import Final

from packages.core.enums import ArticleStructure, Language
from packages.core.models.article import ArticleDraftResult, Paragraph
from packages.core.models.bibliography import CitationMetadata
from packages.core.models.document import (
    ArticleBlock,
    ArticleBlockType,
    ArticleDocumentContent,
    DocumentCitation,
)
from packages.core.models.export import ArticleExportMetadata
from packages.workers.article.export.models import ArticleAuthorship, ArticleExportInput
from packages.workers.article.export.profiles import ArticleProfileId

_MARKER_RE: Final[re.Pattern[str]] = re.compile(r"\s*\[([^\[\]\s]+)\]")
_LABEL_MAX = 300


def article_input_from_draft(
    draft: ArticleDraftResult,
    metadata: ArticleExportMetadata,
    citation_metadata: list[CitationMetadata],
    language: Language,
    profile_id: ArticleProfileId = "oak_default",
) -> ArticleExportInput:
    """Convert a bot draft into the one exporter's transport-neutral input."""

    sources = {meta.source_id: meta for meta in citation_metadata if meta.source_id is not None}
    blocks: list[ArticleBlock] = []
    for index, section_result in enumerate(draft.sections, start=1):
        section = section_result.section
        blocks.append(
            ArticleBlock(
                type=ArticleBlockType.HEADING,
                level=1,
                text=f"{index}. {section.title}",
            )
        )
        for paragraph in section.paragraphs:
            block = _paragraph_block(paragraph, sources)
            if block is not None:
                blocks.append(block)

    content = ArticleDocumentContent(title=metadata.title, blocks=blocks)
    return ArticleExportInput(
        content=content,
        profile_id=profile_id,
        language=language,
        citation_style=metadata.citation_format,
        authorship=ArticleAuthorship(
            author_name=metadata.author_name,
            author_group=metadata.author_group,
            supervisor_name=metadata.supervisor_name,
            supervisor_title=metadata.supervisor_title,
            university_name=metadata.university_name,
            faculty_name=metadata.faculty_name,
            department_name=metadata.department_name,
            city=metadata.city,
            year=metadata.year,
        ),
        article_type=metadata.article_type,
        abstract=metadata.abstract_text,
        keywords=list(metadata.keywords),
        include_toc=metadata.article_type is ArticleStructure.KURS_ISHI,
        sources=sources,
    )


def _paragraph_block(
    paragraph: Paragraph, sources: dict[str, CitationMetadata]
) -> ArticleBlock | None:
    """One drafted paragraph becomes one canonical paragraph block.

    Inline ``[<source_id>]`` and bare ``[<n>]`` chunk markers are removed from the
    text; the paragraph's :class:`CitationRef` links become block-level citations
    in appearance order (deduplicated by source id).
    """

    sids = {str(ref.source_id) for ref in paragraph.citations}
    text = _strip_markers(paragraph.text, sids)

    citations: list[DocumentCitation] = []
    seen: set[str] = set()
    for ref in paragraph.citations:
        sid = str(ref.source_id)
        if sid in seen:
            continue
        seen.add(sid)
        citations.append(
            DocumentCitation(
                source_id=ref.source_id,
                claim_id=ref.claim_id,
                label=_label_for(sid, sources),
            )
        )

    if not text and not citations:
        return None
    return ArticleBlock(type=ArticleBlockType.PARAGRAPH, text=text, citations=citations)


def _strip_markers(text: str, sids: set[str]) -> str:
    """Drop ``[<source_id>]`` and bare ``[<n>]`` markers; keep other brackets."""

    def replace(match: re.Match[str]) -> str:
        inner = match.group(1)
        if inner in sids or inner.isdigit():
            return ""
        return match.group(0)

    return _MARKER_RE.sub(replace, text).strip()


def _label_for(source_id: str, sources: dict[str, CitationMetadata]) -> str:
    meta = sources.get(source_id)
    if meta is not None and meta.title:
        return meta.title[:_LABEL_MAX]
    return source_id[:_LABEL_MAX]


__all__ = ["article_input_from_draft"]
