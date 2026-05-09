"""Routing service that dispatches a validated upload to the right parser."""

from __future__ import annotations

from typing import Final

from packages.core.models.source import ParsedSource
from packages.workers.source.ocr import OCRService
from packages.workers.source.parsers import (
    DOCXParser,
    ImageParser,
    PDFParser,
    PPTXParser,
    TextParser,
    XLSXParser,
)

TEXT_TYPES: Final[frozenset[str]] = frozenset({"txt", "csv", "markdown"})
IMAGE_TYPES: Final[frozenset[str]] = frozenset({"png", "jpeg", "webp", "gif"})


class SourceParseService:
    """Single entry point for callers that have already validated an upload."""

    def __init__(self, ocr_service: OCRService | None = None) -> None:
        self._pdf = PDFParser()
        self._docx = DOCXParser()
        self._pptx = PPTXParser()
        self._xlsx = XLSXParser()
        self._text = TextParser()
        self._image = ImageParser()
        self._ocr = ocr_service or OCRService()

    async def parse(
        self,
        file_bytes: bytes,
        filename: str,
        detected_type: str,
    ) -> ParsedSource:
        """Run the parser appropriate to ``detected_type`` and return a :class:`ParsedSource`.

        ``detected_type`` is the Magika label produced by ``FileValidationService``;
        callers must not pass a raw extension or MIME string. After parsing,
        any pages flagged ``needs_ocr=True`` are routed through the OCR
        service, so callers receive a :class:`ParsedSource` with text on every
        page that could be recognised.
        """

        result = await self._route_parser(file_bytes, filename, detected_type)

        if result.needs_ocr_pages:
            result = await self._ocr.process_parsed_source(result, file_bytes)

        return result

    async def _route_parser(
        self,
        file_bytes: bytes,
        filename: str,
        detected_type: str,
    ) -> ParsedSource:
        match detected_type:
            case "pdf":
                return await self._pdf.parse(file_bytes, filename)
            case "docx":
                return await self._docx.parse(file_bytes, filename)
            case "pptx":
                return await self._pptx.parse(file_bytes, filename)
            case "xlsx":
                return await self._xlsx.parse(file_bytes, filename)
            case t if t in TEXT_TYPES:
                return await self._text.parse(file_bytes, filename)
            case t if t in IMAGE_TYPES:
                return await self._image.parse(file_bytes, filename)
            case other:
                raise ValueError(
                    f"No parser is registered for detected type '{other}'. "
                    f"Supported: pdf, docx, pptx, xlsx, txt, csv, markdown, "
                    f"png, jpeg, webp, gif."
                )
