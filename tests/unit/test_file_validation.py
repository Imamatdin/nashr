"""Behavior tests for ``FileValidationService``.

These tests run against the real Magika model — Magika is local and runs in
~5ms per file, so there's no reason to mock it. Each test covers a specific
contract from the validation pipeline.
"""

from __future__ import annotations

import io
import os
from pathlib import Path

import pytest
from PIL import Image

from packages.core.constants import MAX_FILE_SIZE_BYTES
from packages.core.models import FileValidationResult
from packages.workers.source import FileValidationService

GOLDEN = Path(__file__).resolve().parent.parent / "golden"


@pytest.fixture(scope="module")
def service() -> FileValidationService:
    return FileValidationService()


# ---------------------------------------------------------------------------
# happy path: real document fixtures
# ---------------------------------------------------------------------------


async def test_validate_valid_pdf(service: FileValidationService) -> None:
    payload = (GOLDEN / "sample_3page.pdf").read_bytes()

    result = await service.validate(payload, "sample_3page.pdf")

    assert result.valid is True
    assert result.detected_type == "pdf"
    assert result.confidence > 0.7
    assert result.rejection_reason is None
    assert result.extension_mismatch is False
    assert result.warning is None


async def test_validate_valid_docx(service: FileValidationService) -> None:
    payload = (GOLDEN / "sample_article.docx").read_bytes()

    result = await service.validate(payload, "sample_article.docx")

    assert result.valid is True
    assert result.detected_type == "docx"
    assert result.confidence > 0.7
    assert result.rejection_reason is None


async def test_validate_valid_png(service: FileValidationService) -> None:
    payload = (GOLDEN / "sample_scanned.png").read_bytes()

    result = await service.validate(payload, "sample_scanned.png")

    assert result.valid is True
    assert result.detected_type == "png"
    assert result.confidence > 0.7
    assert result.rejection_reason is None


async def test_validate_prompt_injection_pdf_still_valid_as_file(
    service: FileValidationService,
) -> None:
    """Prompt-injection content is a downstream concern; the file is still a valid PDF."""

    payload = (GOLDEN / "prompt_injection.pdf").read_bytes()

    result = await service.validate(payload, "prompt_injection.pdf")

    assert result.valid is True
    assert result.detected_type == "pdf"


async def test_validate_empty_pdf(service: FileValidationService) -> None:
    """A valid-but-text-empty PDF must pass file-level validation; emptiness is the parser's concern."""

    payload = (GOLDEN / "empty.pdf").read_bytes()

    result = await service.validate(payload, "empty.pdf")

    assert result.valid is True
    assert result.detected_type == "pdf"
    assert result.file_size_bytes > 0


# ---------------------------------------------------------------------------
# rejection paths
# ---------------------------------------------------------------------------


async def test_validate_oversized_file(service: FileValidationService) -> None:
    payload = b"\x00" * (MAX_FILE_SIZE_BYTES + 1)

    result = await service.validate(payload, "huge.pdf")

    assert result.valid is False
    assert result.rejection_reason is not None
    assert "size" in result.rejection_reason.lower()
    assert result.file_size_bytes == MAX_FILE_SIZE_BYTES + 1


async def test_validate_empty_bytes(service: FileValidationService) -> None:
    result = await service.validate(b"", "empty.pdf")

    assert result.valid is False
    assert result.rejection_reason is not None
    assert "empty" in result.rejection_reason.lower()
    assert result.file_size_bytes == 0


async def test_validate_script_disguised_as_pdf(service: FileValidationService) -> None:
    script = (
        b"#!/usr/bin/env python\n"
        b"import os\n"
        b"import sys\n"
        b"def steal_secrets():\n"
        b"    for key, value in os.environ.items():\n"
        b"        print(key, value)\n"
        b"if __name__ == '__main__':\n"
        b"    steal_secrets()\n"
    )

    result = await service.validate(script, "homework.pdf")

    assert result.valid is False
    assert result.rejection_reason is not None
    assert (
        "not allowed" in result.rejection_reason.lower()
        or "unsupported" in result.rejection_reason.lower()
    )
    # Magika should detect this as a script type, not as a pdf
    assert result.detected_type != "pdf"


async def test_validate_extension_mismatch_but_valid(service: FileValidationService) -> None:
    """When the bytes are a real PDF but the filename claims docx, accept with warning."""

    payload = (GOLDEN / "sample_3page.pdf").read_bytes()

    result = await service.validate(payload, "document.docx")

    assert result.valid is True
    assert result.detected_type == "pdf"
    assert result.extension_mismatch is True
    assert result.warning is not None
    assert ".docx" in result.warning
    assert ".pdf" in result.warning


async def test_validate_low_confidence(service: FileValidationService) -> None:
    """Random bytes should be rejected — either as 'unknown' or for low confidence."""

    payload = os.urandom(1000)

    result = await service.validate(payload, "mystery.bin")

    assert result.valid is False
    assert result.rejection_reason is not None


async def test_validate_jpeg_image(service: FileValidationService) -> None:
    """A real JPEG produced by Pillow must validate cleanly."""

    image = Image.new("RGB", (100, 100), color=(123, 45, 67))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=85)
    payload = buffer.getvalue()

    result = await service.validate(payload, "swatch.jpg")

    assert result.valid is True
    assert result.detected_type == "jpeg"
    assert result.confidence > 0.7
    assert result.extension_mismatch is False


async def test_validate_blocked_html_file(service: FileValidationService) -> None:
    payload = b"<html><body>test</body></html>"

    result = await service.validate(payload, "page.html")

    assert result.valid is False
    assert result.rejection_reason is not None
    assert "not allowed" in result.rejection_reason.lower()


# ---------------------------------------------------------------------------
# extra contract checks
# ---------------------------------------------------------------------------


async def test_validate_returns_file_validation_result(service: FileValidationService) -> None:
    """The contract: validate() always returns a FileValidationResult, never raises for normal input."""

    result = await service.validate(b"hello world", "note.txt")

    assert isinstance(result, FileValidationResult)
    assert isinstance(result.valid, bool)
    assert 0.0 <= result.confidence <= 1.0
    assert result.file_size_bytes == len(b"hello world")


async def test_validate_jpeg_with_wrong_extension_warns(
    service: FileValidationService,
) -> None:
    image = Image.new("RGB", (50, 50), color=(0, 0, 0))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=80)

    result = await service.validate(buffer.getvalue(), "image.png")

    assert result.valid is True
    assert result.detected_type == "jpeg"
    assert result.extension_mismatch is True
    assert result.warning is not None


async def test_validate_extension_unknown_no_warning(service: FileValidationService) -> None:
    """If the claimed filename has no extension, we don't fabricate a mismatch warning."""

    payload = (GOLDEN / "sample_3page.pdf").read_bytes()

    result = await service.validate(payload, "noextension")

    assert result.valid is True
    assert result.extension_mismatch is False
    assert result.warning is None


async def test_validate_xlsx_routes_through(service: FileValidationService) -> None:
    """A real xlsx fixture must validate as 'xlsx' so the parser layer can pick it up."""

    payload = (GOLDEN / "sample_spreadsheet.xlsx").read_bytes()

    result = await service.validate(payload, "sample_spreadsheet.xlsx")

    assert result.valid is True
    assert result.detected_type == "xlsx"
    assert result.confidence > 0.7
    assert result.rejection_reason is None


async def test_validate_handles_magika_crash(monkeypatch: pytest.MonkeyPatch) -> None:
    """If Magika raises, the validator must reject cleanly without leaking the exception."""

    service = FileValidationService()

    def _boom(_payload: bytes) -> object:
        raise RuntimeError("magika model corrupted")

    monkeypatch.setattr(service._magika, "identify_bytes", _boom)

    result = await service.validate(b"some bytes that look like data", "mystery.bin")

    assert isinstance(result, FileValidationResult)
    assert result.valid is False
    assert result.rejection_reason is not None
    assert "could not be analyzed" in result.rejection_reason.lower()
    assert result.detected_type == "unknown"
