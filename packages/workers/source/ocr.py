"""OCR service for pages and images that the parsers flagged as ``needs_ocr``.

The service is the second half of the source-processing pipeline: a parser
decides a page has too little extractable text (PDFs with rasterised pages,
uploaded photos), and this module fills in that text by running Tesseract
against the rasterised pixels.

Why these specific design choices:

* **Languages bundle**: ``uzb+rus+eng`` are passed to Tesseract together. The
  LSTM model picks per-script — Uzbek Latin and English share the Latin block
  while Russian uses Cyrillic, so passing all three is essentially free and
  handles mixed-language scans (a common case for Uzbek textbooks).
* **Confidence is reported, not enforced silently**: we emit
  :class:`OCRResult` with a 0–100 average confidence and a count of words
  below ``MIN_WORD_CONFIDENCE`` so callers can downstream-flag low-quality
  pages instead of having the OCR layer drop them on the floor.
* **Timeout via :func:`asyncio.wait_for`**: a malformed image can make
  Tesseract hum for minutes; we cap each page at ``PAGE_TIMEOUT`` seconds
  and record a parse error rather than blocking the whole job.
* **Sync libraries on a worker thread**: PyMuPDF, Pillow, and pytesseract are
  all blocking; every call routes through :func:`asyncio.to_thread` per the
  source-workers rules.
* **Windows ``tesseract.exe`` autodetect**: in dev on Windows the binary is
  often installed under ``Program Files\\Tesseract-OCR`` but not on PATH; we
  probe for it once at construction so unit tests do not have to special-case
  the platform.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import sys
import time
from io import BytesIO
from typing import Final, cast

import fitz  # type: ignore[reportMissingTypeStubs]
import pytesseract  # type: ignore[reportMissingTypeStubs]
from PIL import Image, UnidentifiedImageError

from packages.core.models.source import OCRResult, ParsedSource
from packages.workers.source.ocr_preprocess import OCRPreprocessor
from packages.workers.source.parsers.lang_detect import detect_language

logger = logging.getLogger(__name__)


_WINDOWS_TESSERACT_CANDIDATES: Final[tuple[str, ...]] = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
)

PDF_RASTERIZE_DPI: Final[int] = 300


def _resolve_tesseract_cmd() -> str | None:
    """Return a path to the ``tesseract`` binary or ``None`` if not installed.

    Honours an explicit ``TESSERACT_CMD`` env var first, then ``PATH``, then
    falls back to the well-known Windows installer locations.
    """

    explicit = os.environ.get("TESSERACT_CMD")
    if explicit and os.path.exists(explicit):
        return explicit

    on_path = shutil.which("tesseract")
    if on_path:
        return on_path

    if sys.platform.startswith("win"):
        for candidate in _WINDOWS_TESSERACT_CANDIDATES:
            if os.path.exists(candidate):
                return candidate

    return None


class OCRService:
    """OCR service using Tesseract for Uzbek, Russian, and English text extraction."""

    LANGUAGES: str = "uzb+rus+eng"
    MIN_WORD_CONFIDENCE: int = 30
    MIN_PAGE_CONFIDENCE: float = 40.0
    PAGE_TIMEOUT: int = 30
    TESSERACT_CONFIG: str = "--psm 6"

    def __init__(self, preprocessor: OCRPreprocessor | None = None) -> None:
        self._preprocessor = preprocessor or OCRPreprocessor()
        resolved = _resolve_tesseract_cmd()
        if resolved is not None:
            pytesseract.pytesseract.tesseract_cmd = resolved
            self._tesseract_available = True
        else:
            self._tesseract_available = False
            logger.warning(
                "Tesseract binary not found; OCRService will return failure results.",
            )

    @property
    def tesseract_available(self) -> bool:
        """True iff a Tesseract binary was located at construction time."""

        return self._tesseract_available

    async def process_parsed_source(
        self,
        parsed: ParsedSource,
        file_bytes: bytes,
    ) -> ParsedSource:
        """Run OCR on every page in ``parsed`` whose ``needs_ocr`` is set.

        Behaviour notes:
        * If no pages need OCR, ``parsed`` is returned untouched.
        * If a page's OCR fails or its average confidence is below
          ``MIN_PAGE_CONFIDENCE``, the page keeps ``needs_ocr=True`` and a
          message is appended to ``parse_errors`` — we do not silently accept
          low-quality OCR.
        * After at least one page is filled in, ``full_text``,
          ``metadata.word_count`` and (if previously empty)
          ``metadata.language_detected`` are recomputed.
        """

        if not parsed.needs_ocr_pages:
            return parsed

        new_pages = list(parsed.pages)
        new_errors = list(parsed.parse_errors)
        still_needs_ocr: list[int] = []
        any_text_added = False

        is_pdf = parsed.file_type == "pdf"
        is_image = parsed.file_type in {"png", "jpeg", "jpg", "webp", "gif", "image"}

        rasterised: dict[int, Image.Image] | None = None
        if is_pdf:
            try:
                rasterised = await asyncio.to_thread(
                    self._rasterise_pdf_pages,
                    file_bytes,
                    parsed.needs_ocr_pages,
                )
            except Exception as exc:
                new_errors.append(f"PDF rasterisation failed: {exc}")
                logger.warning("PDF rasterisation failed: %s", exc)
                rasterised = {}

        image_for_image_source: Image.Image | None = None
        if is_image:
            try:
                image_for_image_source = await asyncio.to_thread(
                    self._open_image_bytes,
                    file_bytes,
                )
            except Exception as exc:
                new_errors.append(f"Failed to open uploaded image: {exc}")
                logger.warning("Image open failed during OCR: %s", exc)

        try:
            for index, page in enumerate(new_pages):
                if not page.needs_ocr:
                    continue

                if is_pdf:
                    image = (rasterised or {}).get(page.page_number)
                elif is_image:
                    image = image_for_image_source
                else:
                    image = None

                if image is None:
                    new_errors.append(
                        f"OCR skipped for page {page.page_number}: no rasterised image available."
                    )
                    still_needs_ocr.append(page.page_number)
                    continue

                ocr_result = await self._ocr_with_timeout(image, page.page_number, new_errors)

                if not ocr_result.success:
                    still_needs_ocr.append(page.page_number)
                    continue

                if ocr_result.average_confidence < self.MIN_PAGE_CONFIDENCE and ocr_result.text:
                    new_errors.append(
                        f"OCR confidence too low on page {page.page_number} "
                        f"({ocr_result.average_confidence:.1f} < {self.MIN_PAGE_CONFIDENCE})."
                    )
                    still_needs_ocr.append(page.page_number)
                    continue

                stripped = ocr_result.text.strip()
                char_count = len(stripped.replace(" ", "").replace("\n", ""))
                new_pages[index] = page.model_copy(
                    update={
                        "text": stripped,
                        "char_count": char_count,
                        "needs_ocr": False,
                        "ocr_confidence": ocr_result.average_confidence,
                        "is_ocr": True,
                    }
                )
                if stripped:
                    any_text_added = True
        finally:
            if rasterised:
                for img in rasterised.values():
                    img.close()
            if image_for_image_source is not None:
                image_for_image_source.close()

        full_text = "\n\n".join(p.text for p in new_pages if p.text)
        word_count = len(full_text.split()) if full_text else parsed.metadata.word_count
        language_detected = parsed.metadata.language_detected
        if any_text_added and not language_detected:
            language_detected = detect_language(full_text)

        new_metadata = parsed.metadata.model_copy(
            update={
                "word_count": word_count,
                "language_detected": language_detected,
            }
        )

        return parsed.model_copy(
            update={
                "pages": new_pages,
                "metadata": new_metadata,
                "full_text": full_text,
                "needs_ocr_pages": still_needs_ocr,
                "parse_errors": new_errors,
            }
        )

    async def ocr_image_bytes(self, image_bytes: bytes) -> OCRResult:
        """Decode raw image bytes and run OCR; never raises on bad input."""

        try:
            image = await asyncio.to_thread(self._open_image_bytes, image_bytes)
        except UnidentifiedImageError as exc:
            return OCRResult(success=False, error=f"Unidentified image: {exc}")
        except Exception as exc:  # pragma: no cover - defensive
            return OCRResult(success=False, error=f"Image decode failed: {exc}")

        try:
            return await self._ocr_with_timeout(image, page_number=1, errors_sink=None)
        finally:
            image.close()

    async def ocr_pil_image(self, image: Image.Image) -> OCRResult:
        """Run OCR on an already-decoded :class:`PIL.Image.Image`."""

        return await self._ocr_with_timeout(image, page_number=1, errors_sink=None)

    async def _ocr_with_timeout(
        self,
        image: Image.Image,
        page_number: int,
        errors_sink: list[str] | None,
    ) -> OCRResult:
        if not self._tesseract_available:
            return OCRResult(success=False, error="Tesseract binary not found.")

        try:
            return await asyncio.wait_for(
                asyncio.to_thread(self._ocr_sync, image),
                timeout=self.PAGE_TIMEOUT,
            )
        except TimeoutError:
            message = f"OCR timed out on page {page_number}"
            logger.warning(message)
            if errors_sink is not None:
                errors_sink.append(message)
            return OCRResult(success=False, error=message)
        except Exception as exc:
            message = f"OCR failed on page {page_number}: {exc}"
            logger.warning(message)
            if errors_sink is not None:
                errors_sink.append(message)
            return OCRResult(success=False, error=str(exc))

    def _ocr_sync(self, image: Image.Image) -> OCRResult:
        """Synchronous core: preprocess, call Tesseract, parse the data dict."""

        start = time.perf_counter()
        prepared = self._preprocessor.preprocess(image)
        try:
            raw = pytesseract.image_to_data(  # pyright: ignore[reportUnknownMemberType,reportUnknownVariableType]
                prepared,
                lang=self.LANGUAGES,
                output_type=pytesseract.Output.DICT,
                config=self.TESSERACT_CONFIG,
            )
        finally:
            if prepared is not image:
                prepared.close()

        data = cast("dict[str, list[object]]", raw)
        text, word_count, avg_conf, low_conf = self._collate_words(data)
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        language = detect_language(text) if text else None

        return OCRResult(
            text=text,
            word_count=word_count,
            average_confidence=avg_conf,
            low_confidence_words=low_conf,
            language_detected=language,
            processing_time_ms=elapsed_ms,
            success=True,
        )

    def _collate_words(
        self,
        data: dict[str, list[object]],
    ) -> tuple[str, int, float, int]:
        """Walk the Tesseract per-word dict and rebuild text + confidence stats.

        Lines are reconstructed from ``(block_num, par_num, line_num)`` so the
        output preserves vertical structure; words within a line are joined
        by single spaces.
        """

        texts = data.get("text", [])
        confs = data.get("conf", [])
        block_nums = data.get("block_num", [])
        par_nums = data.get("par_num", [])
        line_nums = data.get("line_num", [])

        accepted_confs: list[float] = []
        low_conf_count = 0
        word_count = 0

        lines: list[str] = []
        current_line: tuple[object, object, object] | None = None
        current_words: list[str] = []

        for i, raw_text in enumerate(texts):
            token = str(raw_text).strip()
            try:
                conf = float(str(confs[i])) if i < len(confs) else -1.0
            except (TypeError, ValueError):
                conf = -1.0

            line_key = (
                block_nums[i] if i < len(block_nums) else None,
                par_nums[i] if i < len(par_nums) else None,
                line_nums[i] if i < len(line_nums) else None,
            )
            if line_key != current_line:
                if current_words:
                    lines.append(" ".join(current_words))
                    current_words = []
                current_line = line_key

            if conf < 0 or not token:
                continue

            current_words.append(token)
            accepted_confs.append(conf)
            word_count += 1
            if conf < self.MIN_WORD_CONFIDENCE:
                low_conf_count += 1

        if current_words:
            lines.append(" ".join(current_words))

        text = "\n".join(line for line in lines if line)
        avg_conf = sum(accepted_confs) / len(accepted_confs) if accepted_confs else 0.0
        return text, word_count, avg_conf, low_conf_count

    @staticmethod
    def _open_image_bytes(image_bytes: bytes) -> Image.Image:
        image = Image.open(BytesIO(image_bytes))
        image.load()
        if image.mode not in {"L", "RGB", "RGBA"}:
            image = image.convert("RGB")
        return image

    @staticmethod
    def _rasterise_pdf_pages(
        file_bytes: bytes,
        page_numbers: list[int],
    ) -> dict[int, Image.Image]:
        """Open ``file_bytes`` once and render each requested 1-indexed page to a PIL image."""

        result: dict[int, Image.Image] = {}
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        try:
            for page_number in page_numbers:
                index = page_number - 1
                if index < 0 or index >= len(doc):
                    continue
                page = doc[index]
                pix = page.get_pixmap(  # pyright: ignore[reportUnknownMemberType,reportUnknownVariableType]
                    dpi=PDF_RASTERIZE_DPI,
                    alpha=False,
                )
                width = int(pix.width)  # pyright: ignore[reportUnknownArgumentType,reportUnknownMemberType]
                height = int(pix.height)  # pyright: ignore[reportUnknownArgumentType,reportUnknownMemberType]
                samples: bytes = pix.samples  # pyright: ignore[reportUnknownMemberType]
                image = Image.frombytes("RGB", (width, height), samples)
                result[page_number] = image
        finally:
            doc.close()
        return result
