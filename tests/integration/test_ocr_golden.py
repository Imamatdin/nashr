"""End-to-end OCR integration: validate -> parse -> OCR on real golden fixtures.

These tests print their findings (text excerpt, confidence, language, word
count) so a human reviewer can sanity-check Tesseract output without rerunning
the recognition step. They are skipped if the host has no Tesseract binary.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from packages.workers.source import FileValidationService, SourceParseService

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


@pytest.fixture(scope="module")
def validator() -> FileValidationService:
    return FileValidationService()


@pytest.fixture(scope="module")
def parse_service() -> SourceParseService:
    return SourceParseService()


@needs_tesseract
async def test_full_pipeline_scanned_png(
    validator: FileValidationService,
    parse_service: SourceParseService,
) -> None:
    payload = (GOLDEN / "sample_scanned.png").read_bytes()

    validation = await validator.validate(payload, "sample_scanned.png")
    assert validation.valid, validation.rejection_reason
    parsed = await parse_service.parse(payload, "sample_scanned.png", validation.detected_type)

    assert parsed.full_text != ""
    assert parsed.pages[0].is_ocr is True
    assert parsed.pages[0].needs_ocr is False
    assert parsed.pages[0].ocr_confidence is not None
    assert parsed.metadata.word_count > 0
    assert parsed.needs_ocr_pages == []

    text_lower = parsed.full_text.lower()
    assert "volter" in text_lower
    assert "xviii" in text_lower

    print()
    print("file:       sample_scanned.png")
    print(f"detected:   {validation.detected_type}")
    print(f"confidence: {parsed.pages[0].ocr_confidence:.1f}")
    print(f"language:   {parsed.metadata.language_detected}")
    print(f"words:      {parsed.metadata.word_count}")
    print("--- excerpt (first 400 chars) ---")
    print(parsed.full_text[:400])


async def test_full_pipeline_pdf_with_text_no_ocr_needed(
    validator: FileValidationService,
    parse_service: SourceParseService,
) -> None:
    """A native-text PDF must round-trip without OCR being invoked at all."""

    payload = (GOLDEN / "sample_3page.pdf").read_bytes()

    validation = await validator.validate(payload, "sample_3page.pdf")
    assert validation.valid
    parsed = await parse_service.parse(payload, "sample_3page.pdf", validation.detected_type)

    assert len(parsed.pages) == 3
    assert all(page.is_ocr is False for page in parsed.pages)
    assert all(page.ocr_confidence is None for page in parsed.pages)
    assert parsed.needs_ocr_pages == []
    assert parsed.metadata.word_count > 500
