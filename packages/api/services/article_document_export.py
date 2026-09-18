"""Render the versioned web article document as an editable DOCX file."""

from __future__ import annotations

from io import BytesIO
from typing import Any, cast

from docx import Document  # pyright: ignore[reportUnknownVariableType]
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.shared import Cm, Pt

from packages.core.models.document import ArticleBlockType, ArticleDocumentContent


def render_article_document_docx(content: ArticleDocumentContent) -> bytes:
    """Build a restrained A4 manuscript from the canonical editor blocks."""

    document = Document()
    section = document.sections[0]
    section.top_margin = Cm(2)
    section.bottom_margin = Cm(2)
    section.left_margin = Cm(2.5)
    section.right_margin = Cm(2.5)

    # python-docx exposes style subclasses through an untyped base collection.
    normal = cast(Any, document.styles["Normal"])
    normal.font.name = "Times New Roman"
    normal.font.size = Pt(12)
    normal.paragraph_format.line_spacing_rule = WD_LINE_SPACING.ONE_POINT_FIVE
    normal.paragraph_format.space_after = Pt(8)

    title = document.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title.paragraph_format.space_after = Pt(24)
    title_run = title.add_run(content.title)
    title_run.bold = True
    title_run.font.name = "Times New Roman"
    title_run.font.size = Pt(18)

    for block in content.blocks:
        if block.type is ArticleBlockType.HEADING:
            paragraph = document.add_heading(block.text, level=block.level or 2)
        elif block.type is ArticleBlockType.BULLET:
            paragraph = document.add_paragraph(block.text, style="List Bullet")
        elif block.type is ArticleBlockType.QUOTE:
            paragraph = document.add_paragraph(block.text)
            paragraph.paragraph_format.left_indent = Cm(1)
            paragraph.paragraph_format.right_indent = Cm(1)
            for run in paragraph.runs:
                run.italic = True
        else:
            paragraph = document.add_paragraph(block.text)
            paragraph.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY

        if block.citations:
            labels = "; ".join(citation.label for citation in block.citations)
            citation_run = paragraph.add_run(f" [{labels}]")
            citation_run.font.size = Pt(9)
            citation_run.font.superscript = True

    document.core_properties.title = content.title
    document.core_properties.subject = "Nashr article export"
    document.core_properties.author = "Nashr"
    output = BytesIO()
    document.save(output)
    return output.getvalue()
