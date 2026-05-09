"""End-to-end check: every golden fixture survives the full validate→parse path.

Spot checks: sample_3page.pdf must come back with 3 pages, sample_article.docx
must produce a real word count, and sample_scanned.png must be flagged for
OCR. The detailed per-format behavior is in tests/unit/test_parsers.py; here
we just walk every fixture through the public service entry points.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from packages.workers.source import FileValidationService, SourceParseService

GOLDEN = Path(__file__).resolve().parent.parent / "golden"


@pytest.fixture(scope="module")
def validator() -> FileValidationService:
    return FileValidationService()


@pytest.fixture(scope="module")
def parse_service() -> SourceParseService:
    return SourceParseService()


def _binary_fixtures() -> list[Path]:
    return sorted(p for p in GOLDEN.iterdir() if p.is_file() and p.suffix != ".md")


async def test_parse_all_golden_files(
    validator: FileValidationService,
    parse_service: SourceParseService,
) -> None:
    fixtures = _binary_fixtures()
    assert fixtures, "no golden fixtures discovered"

    rows: list[tuple[str, str, int, int, str, str | None]] = []
    parsed_by_name = {}

    for path in fixtures:
        payload = path.read_bytes()

        validation = await validator.validate(payload, path.name)
        if not validation.valid:
            rows.append((path.name, "(rejected)", 0, 0, "-", None))
            continue

        parsed = await parse_service.parse(payload, path.name, validation.detected_type)
        parsed_by_name[path.name] = parsed

        needs_ocr_repr = ",".join(str(n) for n in parsed.needs_ocr_pages) or "-"
        rows.append(
            (
                path.name,
                parsed.file_type,
                len(parsed.pages),
                parsed.metadata.word_count,
                needs_ocr_repr,
                parsed.metadata.language_detected,
            )
        )

    print()
    print(f"{'filename':<28} {'type':<8} {'pages':>5} {'words':>6} {'needs_ocr':<10} {'lang':<5}")
    print("-" * 70)
    for name, file_type, pages, words, needs_ocr_repr, lang in rows:
        lang_repr = lang if lang is not None else "-"
        print(
            f"{name:<28} {file_type:<8} {pages:>5} {words:>6} {needs_ocr_repr:<10} {lang_repr:<5}"
        )

    pdf3 = parsed_by_name["sample_3page.pdf"]
    assert len(pdf3.pages) == 3, f"sample_3page.pdf returned {len(pdf3.pages)} pages"

    docx_doc = parsed_by_name["sample_article.docx"]
    assert docx_doc.metadata.word_count > 100

    png = parsed_by_name["sample_scanned.png"]
    assert png.needs_ocr_pages, "sample_scanned.png should request OCR"
