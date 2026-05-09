"""Image parser placeholder for OCR.

Images carry no inline text we can extract here. The parser returns a single
:class:`ParsedPage` with ``needs_ocr=True`` and stores the pixel dimensions in
metadata so the OCR worker downstream can choose preprocessing.
"""

from __future__ import annotations

import asyncio
import logging
from io import BytesIO

from PIL import Image, UnidentifiedImageError

from packages.core.models.source import (
    ParsedPage,
    ParsedSource,
    SourceMetadataExtracted,
)

logger = logging.getLogger(__name__)


class ImageParser:
    """Marks an uploaded image as requiring OCR; OCR happens in the next worker."""

    async def parse(self, file_bytes: bytes, filename: str) -> ParsedSource:
        return await asyncio.to_thread(self._parse_sync, file_bytes, filename)

    def _parse_sync(self, file_bytes: bytes, filename: str) -> ParsedSource:
        errors: list[str] = []
        title: str | None = None
        creation_date: str | None = None

        try:
            with Image.open(BytesIO(file_bytes)) as image:
                width, height = image.size
                file_format = (image.format or "").lower() or _ext(filename)
                title = f"{file_format.upper()} image ({width}x{height})"
        except UnidentifiedImageError as exc:
            errors.append(f"Pillow could not identify image: {exc}")
            file_format = _ext(filename)
        except Exception as exc:
            errors.append(f"Failed to open image: {exc}")
            logger.warning("Image open failed for %s: %s", filename, exc)
            file_format = _ext(filename)

        page = ParsedPage(
            page_number=1,
            text="",
            char_count=0,
            needs_ocr=True,
        )
        metadata = SourceMetadataExtracted(
            title=title,
            page_count=1,
            word_count=0,
            language_detected=None,
            has_images=True,
            creation_date=creation_date,
        )

        return ParsedSource(
            filename=filename,
            file_type=file_format or "image",
            file_size_bytes=len(file_bytes),
            pages=[page],
            metadata=metadata,
            full_text="",
            needs_ocr_pages=[1],
            parse_errors=errors,
        )


def _ext(filename: str) -> str:
    if "." not in filename:
        return "image"
    return filename.rsplit(".", 1)[-1].lower()
