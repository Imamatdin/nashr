"""Unit tests for the OCR service and preprocessor.

Tests run against the real Tesseract binary with the bundled ``uzb+rus+eng``
traineddata. When Tesseract is not installed (CI without the system package)
the OCR-touching tests skip via :data:`TESSERACT_AVAILABLE`; the preprocessor
and pure-pydantic tests always run because they do not need Tesseract.

We deliberately do not mock pytesseract or PIL: the testing rules forbid
mocking local libraries, and OCR only earns trust by being exercised against
real pixels.
"""

from __future__ import annotations

import asyncio
import random
import shutil
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont
from pydantic import ValidationError
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import (
    Image as RLImage,
)
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
)

from packages.core.models.source import (
    OCRResult,
    ParsedPage,
    ParsedSource,
    SourceMetadataExtracted,
)
from packages.workers.source.ocr import OCRService
from packages.workers.source.ocr_preprocess import OCRPreprocessor

GOLDEN = Path(__file__).resolve().parent.parent / "golden"

TESSERACT_AVAILABLE = shutil.which("tesseract") is not None or any(
    Path(p).exists()
    for p in (
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    )
)

needs_tesseract = pytest.mark.skipif(
    not TESSERACT_AVAILABLE,
    reason="Tesseract not installed",
)


# ---------------------------------------------------------------------------
# Image fixture builders (Pillow only, no OpenCV)
# ---------------------------------------------------------------------------


def _resolve_font(size: int) -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    """Pick a TrueType font that exists on the host so OCR sees real glyph shapes."""

    candidates = [
        r"C:\Windows\Fonts\arial.ttf",
        r"C:\Windows\Fonts\segoeui.ttf",
        r"/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        r"/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        r"/System/Library/Fonts/Helvetica.ttc",
    ]
    for path in candidates:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size=size)
            except OSError:
                continue
    return ImageFont.load_default()


def _make_clean_text_image(text: str = "OCR test sentence one") -> Image.Image:
    """High-contrast, large-font PNG-style image: easy work for Tesseract."""

    image = Image.new("RGB", (1200, 200), color="white")
    draw = ImageDraw.Draw(image)
    draw.text((40, 60), text, fill="black", font=_resolve_font(64))
    return image


def _make_full_page_text_image(lines: list[str]) -> Image.Image:
    """4:3 page image with large-font text on multiple lines.

    Sized to roughly match the 400x300 PDF-point embed in ``_embed_image_in_pdf``
    so the bitmap is not aspect-stretched when ReportLab places it.
    """

    image = Image.new("RGB", (1600, 1200), color="white")
    draw = ImageDraw.Draw(image)
    font = _resolve_font(72)
    y = 80
    for line in lines:
        draw.text((80, y), line, fill="black", font=font)
        y += 110
    return image


def _make_noisy_text_image(text: str = "OCR test sentence one") -> Image.Image:
    """Same content but tiny font + random salt-and-pepper noise: harder for Tesseract."""

    image = Image.new("RGB", (300, 80), color="white")
    draw = ImageDraw.Draw(image)
    draw.text((6, 28), text, fill=(60, 60, 60), font=_resolve_font(14))
    rng = random.Random(7)
    pixels = image.load()
    assert pixels is not None
    for _ in range(2000):
        x = rng.randint(0, image.width - 1)
        y = rng.randint(0, image.height - 1)
        shade = rng.randint(0, 180)
        pixels[x, y] = (shade, shade, shade)
    return image


def _make_blank_image() -> Image.Image:
    return Image.new("RGB", (800, 200), color="white")


def _embed_image_in_pdf(text_page_body: str, embedded_image: Image.Image) -> bytes:
    """Page 1: extracted-text paragraph. Page 2: full-bleed image (forces needs_ocr)."""

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, title="ocr fixture")
    styles = getSampleStyleSheet()
    image_buffer = BytesIO()
    embedded_image.save(image_buffer, format="PNG")
    image_buffer.seek(0)
    story: list[object] = [
        Paragraph(text_page_body, styles["BodyText"]),
        PageBreak(),
        RLImage(image_buffer, width=400, height=300),
    ]
    doc.build(story)
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# OCRResult model
# ---------------------------------------------------------------------------


def test_ocr_result_model_accepts_valid_payload() -> None:
    result = OCRResult(
        text="hello world",
        word_count=2,
        average_confidence=87.5,
        low_confidence_words=0,
        language_detected="en",
        processing_time_ms=120,
        success=True,
    )

    assert result.text == "hello world"
    assert result.average_confidence == 87.5
    assert result.success is True


def test_ocr_result_rejects_negative_confidence() -> None:
    with pytest.raises(ValidationError):
        OCRResult(average_confidence=-5.0)


def test_ocr_result_rejects_confidence_above_100() -> None:
    with pytest.raises(ValidationError):
        OCRResult(average_confidence=120.0)


def test_ocr_result_allows_blank_page_with_success_true() -> None:
    """A blank scan is a valid OCR run (zero words), not a failure."""

    result = OCRResult(text="", word_count=0, average_confidence=0.0, success=True)

    assert result.success is True
    assert result.word_count == 0


def test_ocr_result_round_trip() -> None:
    payload = {
        "text": "Sample",
        "word_count": 1,
        "average_confidence": 75.0,
        "low_confidence_words": 0,
        "language_detected": "en",
        "processing_time_ms": 50,
        "success": True,
        "error": None,
    }
    rebuilt = OCRResult.model_validate(payload).model_dump()
    assert rebuilt == payload


# ---------------------------------------------------------------------------
# Preprocessor (no Tesseract dependency)
# ---------------------------------------------------------------------------


def test_preprocessor_converts_to_grayscale() -> None:
    rgb = Image.new("RGB", (1200, 800), color=(120, 60, 200))

    out = OCRPreprocessor().preprocess(rgb)

    assert out.mode == "L"


def test_preprocessor_upscales_small_images() -> None:
    small = Image.new("RGB", (400, 300), color="white")

    out = OCRPreprocessor().preprocess(small)

    assert out.width >= 800
    assert out.height >= 600


def test_preprocessor_does_not_upscale_large_images() -> None:
    large = Image.new("RGB", (2000, 1500), color="white")

    out = OCRPreprocessor().preprocess(large)

    assert out.width == 2000
    assert out.height == 1500


# ---------------------------------------------------------------------------
# OCR direct image API
# ---------------------------------------------------------------------------


@needs_tesseract
async def test_ocr_returns_confidence_scores() -> None:
    service = OCRService()

    result = await service.ocr_pil_image(_make_clean_text_image("Hello world OCR"))

    assert result.success is True
    assert result.word_count >= 2
    assert result.average_confidence > 60
    assert "Hello" in result.text or "hello" in result.text.lower()


@needs_tesseract
async def test_ocr_low_quality_image_has_lower_confidence() -> None:
    service = OCRService()

    clean = await service.ocr_pil_image(_make_clean_text_image("OCR sample text"))
    noisy = await service.ocr_pil_image(_make_noisy_text_image("OCR sample text"))

    assert clean.success is True
    assert noisy.success is True
    assert noisy.average_confidence < clean.average_confidence


@needs_tesseract
async def test_ocr_empty_image_returns_empty_text() -> None:
    service = OCRService()

    result = await service.ocr_pil_image(_make_blank_image())

    assert result.success is True
    assert result.word_count == 0
    assert result.text.strip() == ""


@needs_tesseract
async def test_ocr_image_bytes_decodes_png() -> None:
    service = OCRService()
    image = _make_clean_text_image("Bytes path works")
    buffer = BytesIO()
    image.save(buffer, format="PNG")

    result = await service.ocr_image_bytes(buffer.getvalue())

    assert result.success is True
    assert result.word_count >= 2


@needs_tesseract
async def test_ocr_image_bytes_rejects_non_image_bytes() -> None:
    service = OCRService()

    result = await service.ocr_image_bytes(b"not an image at all")

    assert result.success is False
    assert result.error is not None


# ---------------------------------------------------------------------------
# OCR ParsedSource integration
# ---------------------------------------------------------------------------


@needs_tesseract
async def test_ocr_scanned_png_fills_in_parsed_source() -> None:
    from packages.workers.source.parsers import ImageParser

    payload = (GOLDEN / "sample_scanned.png").read_bytes()
    parsed = await ImageParser().parse(payload, "sample_scanned.png")
    assert parsed.pages[0].needs_ocr is True
    assert parsed.pages[0].text == ""

    result = await OCRService().process_parsed_source(parsed, payload)

    page = result.pages[0]
    assert page.is_ocr is True
    assert page.needs_ocr is False
    assert page.ocr_confidence is not None
    assert page.ocr_confidence > OCRService.MIN_PAGE_CONFIDENCE
    assert page.text != ""
    text_lower = result.full_text.lower()
    assert "volter" in text_lower
    assert "xviii" in text_lower
    assert result.metadata.word_count > 0
    assert result.metadata.language_detected in {"uz", "ru", "en"}
    assert result.needs_ocr_pages == []


@needs_tesseract
async def test_ocr_updates_pdf_with_image_page() -> None:
    """Page 1 has extractable text, page 2 is a full-page image: only page 2 OCRs."""

    from packages.workers.source.parsers import PDFParser

    body = (
        "This first page contains a generous helping of textual content "
        "well above the OCR threshold so it must NOT be re-OCRed. "
        "Page two is rendered as a single image and forces the OCR path."
    )
    embedded = _make_full_page_text_image(
        [
            "Second page OCR target",
            "rendered as a bitmap image",
            "so Tesseract must read it",
        ]
    )
    pdf_bytes = _embed_image_in_pdf(body, embedded)

    parsed = await PDFParser().parse(pdf_bytes, "two_page.pdf")
    assert len(parsed.pages) == 2
    assert parsed.pages[0].needs_ocr is False
    assert parsed.pages[1].needs_ocr is True

    page1_before = parsed.pages[0].text
    result = await OCRService().process_parsed_source(parsed, pdf_bytes)

    assert result.pages[0].text == page1_before
    assert result.pages[0].is_ocr is False
    assert result.pages[1].is_ocr is True
    assert result.pages[1].needs_ocr is False
    assert result.pages[1].text != ""
    assert result.full_text.startswith(page1_before)
    assert result.pages[1].text in result.full_text
    assert result.metadata.word_count > 0
    assert result.needs_ocr_pages == []


async def test_ocr_preserves_already_parsed_pages() -> None:
    """If no pages need OCR, process_parsed_source must short-circuit."""

    parsed = ParsedSource(
        filename="text.pdf",
        file_type="pdf",
        file_size_bytes=1234,
        pages=[
            ParsedPage(page_number=1, text="hello world", char_count=10, needs_ocr=False),
        ],
        metadata=SourceMetadataExtracted(word_count=2, page_count=1),
        full_text="hello world",
        needs_ocr_pages=[],
        parse_errors=[],
    )

    result = await OCRService().process_parsed_source(parsed, b"")

    assert result is parsed


@needs_tesseract
async def test_ocr_timeout_handling(monkeypatch: pytest.MonkeyPatch) -> None:
    """When OCR exceeds PAGE_TIMEOUT, the page stays needs_ocr and an error is recorded."""

    monkeypatch.setattr(OCRService, "PAGE_TIMEOUT", 1)

    def slow(*_args: object, **_kwargs: object) -> dict[str, list[object]]:
        import time

        time.sleep(3)
        return {
            "text": [],
            "conf": [],
            "block_num": [],
            "par_num": [],
            "line_num": [],
        }

    import pytesseract

    monkeypatch.setattr(pytesseract, "image_to_data", slow)

    service = OCRService()
    result = await service.ocr_pil_image(_make_blank_image())

    assert result.success is False
    assert result.error is not None
    assert "timed out" in result.error.lower()


@needs_tesseract
async def test_ocr_low_confidence_keeps_page_flagged_for_ocr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the page-level confidence is below ``MIN_PAGE_CONFIDENCE``, do not accept the text."""

    from packages.workers.source.parsers import ImageParser

    payload = (GOLDEN / "sample_scanned.png").read_bytes()
    parsed = await ImageParser().parse(payload, "sample_scanned.png")

    monkeypatch.setattr(OCRService, "MIN_PAGE_CONFIDENCE", 99.9)

    result = await OCRService().process_parsed_source(parsed, payload)

    assert result.pages[0].is_ocr is False
    assert result.pages[0].needs_ocr is True
    assert any("confidence too low" in err for err in result.parse_errors)
    assert 1 in result.needs_ocr_pages


def test_ocr_service_reports_tesseract_availability() -> None:
    service = OCRService()
    assert service.tesseract_available is TESSERACT_AVAILABLE


async def test_ocr_returns_failure_when_tesseract_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """When the binary is absent, ocr_pil_image must surface failure rather than crash."""

    monkeypatch.setattr(
        "packages.workers.source.ocr._resolve_tesseract_cmd",
        lambda: None,
    )
    service = OCRService()
    assert service.tesseract_available is False

    result = await service.ocr_pil_image(_make_blank_image())

    assert result.success is False
    assert result.error is not None
    assert "tesseract" in result.error.lower()


async def test_run_concurrent_ocr_calls_do_not_crash() -> None:
    """The service must be reusable across concurrent invocations (asyncio safety)."""

    if not TESSERACT_AVAILABLE:
        pytest.skip("Tesseract not installed")

    service = OCRService()
    images = [_make_clean_text_image(f"Concurrent text {i}") for i in range(3)]
    results = await asyncio.gather(*(service.ocr_pil_image(img) for img in images))

    assert all(r.success for r in results)
    assert all(r.word_count >= 2 for r in results)
