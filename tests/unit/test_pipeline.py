"""Behaviour tests for :class:`SourcePipeline`.

The pipeline is mostly orchestration, so these tests substitute small
stand-ins for each stage so we can drive the orchestrator down each
branch (validation rejected, no text extracted, full success). The
underlying validator/parser/chunker/extractor each have their own deeper
test files; we don't re-cover that ground here.
"""

from __future__ import annotations

import pytest

from packages.core.enums import ClaimStrength
from packages.core.models.source import (
    FileValidationResult,
    ParsedPage,
    ParsedSource,
    SourceChunkCreate,
    SourceClaimCreate,
    SourceMetadataExtracted,
)
from packages.workers.source.pipeline import SourcePipeline


class _StubValidator:
    def __init__(self, result: FileValidationResult) -> None:
        self._result = result

    async def validate(self, file_bytes: bytes, filename: str) -> FileValidationResult:
        return self._result


class _StubParser:
    def __init__(self, parsed: ParsedSource) -> None:
        self._parsed = parsed

    async def parse(self, file_bytes: bytes, filename: str, detected_type: str) -> ParsedSource:
        return self._parsed


class _StubExtractor:
    def __init__(self, claims: list[SourceClaimCreate]) -> None:
        self._claims = claims

    async def extract_claims(
        self,
        chunks: list[SourceChunkCreate],
        source_metadata: SourceMetadataExtracted,
    ) -> list[SourceClaimCreate]:
        return list(self._claims)


def _ok_validation() -> FileValidationResult:
    return FileValidationResult(
        valid=True,
        detected_type="pdf",
        mime_type="application/pdf",
        confidence=0.99,
        file_size_bytes=2048,
        extension_mismatch=False,
        rejection_reason=None,
        warning=None,
    )


def _bad_validation(reason: str = "File type 'executable' is not allowed.") -> FileValidationResult:
    return FileValidationResult(
        valid=False,
        detected_type="executable",
        mime_type="application/x-executable",
        confidence=0.99,
        file_size_bytes=2048,
        extension_mismatch=False,
        rejection_reason=reason,
        warning=None,
    )


def _parsed_with_text() -> ParsedSource:
    body = "This is the parsed body text. " * 10
    page = ParsedPage(
        page_number=1,
        text=body,
        char_count=len(body.replace(" ", "")),
        needs_ocr=False,
    )
    return ParsedSource(
        filename="doc.pdf",
        file_type="pdf",
        file_size_bytes=2048,
        pages=[page],
        metadata=SourceMetadataExtracted(title="Test", authors=["A"], year=2020),
        full_text=body,
        needs_ocr_pages=[],
        parse_errors=[],
    )


def _parsed_empty() -> ParsedSource:
    page = ParsedPage(
        page_number=1,
        text="",
        char_count=0,
        needs_ocr=False,
    )
    return ParsedSource(
        filename="blank.pdf",
        file_type="pdf",
        file_size_bytes=2048,
        pages=[page],
        metadata=SourceMetadataExtracted(),
        full_text="",
        needs_ocr_pages=[],
        parse_errors=[],
    )


@pytest.mark.asyncio
async def test_pipeline_full_success() -> None:
    parsed = _parsed_with_text()
    claims = [
        SourceClaimCreate(
            claim_text="A long enough claim about a fact in the source.",
            quote=None,
            strength=ClaimStrength.STRONG,
        )
    ]
    pipeline = SourcePipeline(
        validator=_StubValidator(_ok_validation()),  # type: ignore[arg-type]
        parser=_StubParser(parsed),  # type: ignore[arg-type]
        extractor=_StubExtractor(claims),  # type: ignore[arg-type]
    )

    result = await pipeline.process(b"\x00" * 100, "doc.pdf")

    assert result.validation.valid is True
    assert result.parsed is parsed
    assert len(result.chunks) >= 1
    assert len(result.claims) == 1
    assert result.errors == []


@pytest.mark.asyncio
async def test_pipeline_validation_failure_short_circuits() -> None:
    rejection = "File type 'executable' is not allowed."
    pipeline = SourcePipeline(
        validator=_StubValidator(_bad_validation(rejection)),  # type: ignore[arg-type]
        parser=_StubParser(_parsed_with_text()),  # type: ignore[arg-type]
        extractor=_StubExtractor([]),  # type: ignore[arg-type]
    )

    result = await pipeline.process(b"\x00" * 100, "x.exe")

    assert result.parsed is None
    assert result.chunks == []
    assert result.claims == []
    assert rejection in result.errors


@pytest.mark.asyncio
async def test_pipeline_empty_text_warns() -> None:
    pipeline = SourcePipeline(
        validator=_StubValidator(_ok_validation()),  # type: ignore[arg-type]
        parser=_StubParser(_parsed_empty()),  # type: ignore[arg-type]
        extractor=_StubExtractor([]),  # type: ignore[arg-type]
    )

    result = await pipeline.process(b"\x00" * 100, "blank.pdf")

    assert result.chunks == []
    assert result.claims == []
    assert any("no text" in err.lower() for err in result.errors)


@pytest.mark.asyncio
async def test_pipeline_passes_validation_warning_through() -> None:
    validation = FileValidationResult(
        valid=True,
        detected_type="pdf",
        mime_type="application/pdf",
        confidence=0.99,
        file_size_bytes=2048,
        extension_mismatch=True,
        rejection_reason=None,
        warning="File extension '.docx' does not match detected type 'pdf'.",
    )
    pipeline = SourcePipeline(
        validator=_StubValidator(validation),  # type: ignore[arg-type]
        parser=_StubParser(_parsed_with_text()),  # type: ignore[arg-type]
        extractor=_StubExtractor([]),  # type: ignore[arg-type]
    )

    result = await pipeline.process(b"\x00" * 100, "mistitled.docx")

    assert any("does not match detected type" in err for err in result.errors)
