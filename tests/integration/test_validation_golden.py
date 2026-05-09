"""End-to-end check: every golden fixture survives the validator without crashing.

This is a regression net for changes to the validation pipeline. Individual
behaviors are covered by unit tests; here we just exercise the full set and
print a summary table for human inspection.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from packages.core.models import FileValidationResult
from packages.workers.source import FileValidationService

GOLDEN = Path(__file__).resolve().parent.parent / "golden"

EXPECTED_BINARY_FIXTURES: frozenset[str] = frozenset(
    {
        "sample_3page.pdf",
        "sample_with_doi.pdf",
        "prompt_injection.pdf",
        "empty.pdf",
        "sample_article.docx",
        "sample_scanned.png",
        "sample_spreadsheet.xlsx",
    }
)


@pytest.fixture(scope="module")
def service() -> FileValidationService:
    return FileValidationService()


def _binary_fixtures() -> list[Path]:
    return sorted(p for p in GOLDEN.iterdir() if p.is_file() and p.suffix != ".md")


async def test_all_golden_files_dont_crash(service: FileValidationService) -> None:
    fixtures = _binary_fixtures()
    assert {p.name for p in fixtures} == EXPECTED_BINARY_FIXTURES, (
        "Golden fixture set drifted from expectation; "
        "regenerate via scripts/generate_golden.py and update EXPECTED_BINARY_FIXTURES."
    )

    rows: list[tuple[str, bool, str, float]] = []
    for path in fixtures:
        payload = path.read_bytes()
        result = await service.validate(payload, path.name)

        assert isinstance(result, FileValidationResult)
        assert 0.0 <= result.confidence <= 1.0
        assert result.file_size_bytes == len(payload)

        rows.append((path.name, result.valid, result.detected_type, result.confidence))

    print()
    print(f"{'filename':<28} {'valid':<7} {'type':<10} {'confidence':>10}")
    print("-" * 60)
    for name, valid, detected, confidence in rows:
        print(f"{name:<28} {valid!s:<7} {detected:<10} {confidence:>10.4f}")


async def test_every_pdf_fixture_validates_as_pdf(service: FileValidationService) -> None:
    """Sanity check: each .pdf fixture must be detected as pdf, not misclassified."""

    pdf_fixtures = [p for p in _binary_fixtures() if p.suffix == ".pdf"]
    assert pdf_fixtures, "no PDF fixtures found"

    for path in pdf_fixtures:
        result = await service.validate(path.read_bytes(), path.name)
        assert result.detected_type == "pdf", (
            f"{path.name} detected as {result.detected_type} instead of pdf"
        )
        assert result.valid is True, f"{path.name} unexpectedly rejected: {result.rejection_reason}"
