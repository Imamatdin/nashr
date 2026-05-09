"""PDF parser built on PyMuPDF (``fitz``).

Per-page text, headings (font-size heuristic), tables (PyMuPDF 1.23+ API),
metadata, and a DOI scan over the first two pages. Pages with very little
extractable text are flagged ``needs_ocr=True`` for the OCR worker downstream.

PyMuPDF ships no type stubs, so every fitz call site casts to its concrete
expected return type before doing real work. This keeps the rest of the file
(and downstream consumers) in strict-typed territory.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Final, cast

import fitz  # type: ignore[reportMissingTypeStubs]

from packages.core.models.source import (
    ParsedPage,
    ParsedSource,
    SourceMetadataExtracted,
)
from packages.workers.source.parsers.lang_detect import detect_language

logger = logging.getLogger(__name__)


DOI_RE: Final[re.Pattern[str]] = re.compile(
    r"10\.\d{4,9}/[-._;()/:A-Z0-9]+",
    re.IGNORECASE,
)

HEADING_FONT_SIZE: Final[float] = 14.0
HEADING_FLAG_BOLD: Final[int] = 16


class PDFParser:
    """Parses a PDF byte stream into a :class:`ParsedSource`."""

    TEXT_DENSITY_THRESHOLD: int = 50

    async def parse(self, file_bytes: bytes, filename: str) -> ParsedSource:
        return await asyncio.to_thread(self._parse_sync, file_bytes, filename)

    def _parse_sync(self, file_bytes: bytes, filename: str) -> ParsedSource:
        errors: list[str] = []

        try:
            doc = fitz.open(stream=file_bytes, filetype="pdf")
        except Exception as exc:
            logger.warning("Failed to open PDF %s: %s", filename, exc)
            return ParsedSource(
                filename=filename,
                file_type="pdf",
                file_size_bytes=len(file_bytes),
                pages=[],
                metadata=SourceMetadataExtracted(),
                full_text="",
                needs_ocr_pages=[],
                parse_errors=[f"Failed to open PDF: {exc}"],
            )

        if doc.is_encrypted:
            errors.append("PDF is encrypted; parsed text may be incomplete.")

        pages: list[ParsedPage] = []
        needs_ocr_pages: list[int] = []
        has_images = False

        for page_index in range(len(doc)):
            try:
                parsed_page, page_has_images = self._parse_page(doc, page_index, errors)
            except Exception as exc:
                msg = f"Page {page_index + 1} parse error: {exc}"
                errors.append(msg)
                logger.warning(msg)
                continue
            has_images = has_images or page_has_images
            pages.append(parsed_page)
            if parsed_page.needs_ocr:
                needs_ocr_pages.append(parsed_page.page_number)

        full_text = "\n\n".join(p.text for p in pages)
        word_count = len(full_text.split()) if full_text else 0

        metadata = self._build_metadata(
            doc=doc,
            pages=pages,
            full_text=full_text,
            word_count=word_count,
            has_images=has_images,
        )
        doc.close()

        return ParsedSource(
            filename=filename,
            file_type="pdf",
            file_size_bytes=len(file_bytes),
            pages=pages,
            metadata=metadata,
            full_text=full_text,
            needs_ocr_pages=needs_ocr_pages,
            parse_errors=errors,
        )

    def _parse_page(
        self,
        doc: fitz.Document,
        page_index: int,
        errors: list[str],
    ) -> tuple[ParsedPage, bool]:
        page = doc[page_index]
        text: str = cast("str", page.get_text("text"))  # type: ignore[reportUnknownMemberType]
        char_count = len(re.sub(r"\s+", "", text))
        needs_ocr = char_count < self.TEXT_DENSITY_THRESHOLD

        headings = self._extract_headings(page)
        tables = self._extract_tables(page, errors, page_index)
        images = cast("list[object]", page.get_images(full=False))
        page_has_images = bool(images)

        return (
            ParsedPage(
                page_number=page_index + 1,
                text=text,
                char_count=char_count,
                needs_ocr=needs_ocr,
                headings=headings,
                tables=tables,
            ),
            page_has_images,
        )

    @staticmethod
    def _extract_headings(page: fitz.Page) -> list[str]:
        headings: list[str] = []
        try:
            details = cast("dict[str, object]", page.get_text("dict"))  # type: ignore[reportUnknownMemberType]
        except Exception:
            return headings

        blocks = cast("list[dict[str, object]]", details.get("blocks", []))
        for block in blocks:
            lines = cast("list[dict[str, object]]", block.get("lines", []))
            for line in lines:
                line_text_parts: list[str] = []
                line_is_heading = False
                spans = cast("list[dict[str, object]]", line.get("spans", []))
                for span in spans:
                    span_text = cast("str", span.get("text", "")).strip()
                    if not span_text:
                        continue
                    size = float(cast("float | int", span.get("size", 0)))
                    flags = int(cast("int", span.get("flags", 0)))
                    bold = bool(flags & HEADING_FLAG_BOLD)
                    if size >= HEADING_FONT_SIZE or bold:
                        line_is_heading = True
                    line_text_parts.append(span_text)
                if line_is_heading and line_text_parts:
                    candidate = " ".join(line_text_parts).strip()
                    if candidate and candidate not in headings:
                        headings.append(candidate)
        return headings

    @staticmethod
    def _extract_tables(
        page: fitz.Page,
        errors: list[str],
        page_index: int,
    ) -> list[list[list[str]]]:
        if not hasattr(page, "find_tables"):
            return []
        try:
            finder = page.find_tables()  # type: ignore[reportUnknownMemberType]
        except Exception as exc:
            errors.append(f"Page {page_index + 1} table-extraction failed: {exc}")
            return []

        if finder is None:
            return []

        tables: list[list[list[str]]] = []
        finder_tables = cast("list[object]", finder.tables)
        for table in finder_tables:
            try:
                extracted = cast("list[list[str | None]]", table.extract())  # type: ignore[reportUnknownMemberType]
            except Exception as exc:
                errors.append(f"Page {page_index + 1} table.extract() failed: {exc}")
                continue
            cleaned = [[(cell or "").strip() for cell in row] for row in extracted]
            if any(any(cell for cell in row) for row in cleaned):
                tables.append(cleaned)
        return tables

    @staticmethod
    def _build_metadata(
        *,
        doc: fitz.Document,
        pages: list[ParsedPage],
        full_text: str,
        word_count: int,
        has_images: bool,
    ) -> SourceMetadataExtracted:
        raw: dict[str, str] = cast("dict[str, str]", doc.metadata or {})  # type: ignore[reportUnknownMemberType]
        title = (raw.get("title") or "").strip() or None
        author_field = (raw.get("author") or "").strip()
        authors = [a.strip() for a in re.split(r"[,;]", author_field) if a.strip()]
        creation_date = (raw.get("creationDate") or "").strip() or None

        doi_search_text = "\n".join(p.text for p in pages[:2])
        doi_match = DOI_RE.search(doi_search_text) or DOI_RE.search(_metadata_blob(raw))
        doi = doi_match.group(0) if doi_match else None

        year_match = re.search(r"(?:19|20)\d{2}", creation_date or "")
        year = int(year_match.group(0)) if year_match else None

        language_detected = detect_language(full_text)

        return SourceMetadataExtracted(
            title=title,
            authors=authors,
            year=year,
            doi=doi,
            page_count=len(doc),
            word_count=word_count,
            language_detected=language_detected,
            has_images=has_images,
            creation_date=creation_date,
        )


def _metadata_blob(raw: dict[str, str]) -> str:
    return " ".join(value for value in raw.values() if value)
