"""Tests for :class:`PDFExporter` and :class:`ArticlePDFPipeline`.

LibreOffice's headless ``soffice --convert-to pdf`` is the conversion
engine, so the conversion-path tests need the binary on the host. They
are guarded by ``LIBREOFFICE_AVAILABLE`` and skip cleanly when it is
absent (CI without the package, dev machines that haven't installed
it). Tests that exercise pure error-handling — binary missing, timeout,
corrupt input — monkeypatch around the subprocess and always run, so
the failure surface is covered everywhere.

Following ``.claude/rules/testing.md`` we do not mock python-docx; the
real :class:`DOCXExporter` is used to build any DOCX we need to feed
the converter so the test exercises the integration end-to-end.
"""

from __future__ import annotations

import asyncio
import os
import platform
import shutil
from datetime import UTC, datetime
from io import BytesIO
from typing import Any
from uuid import UUID, uuid4

import pytest
from docx import Document  # pyright: ignore[reportUnknownVariableType]

from packages.core.enums import (
    ArticleSectionStatus,
    ArticleStructure,
    CitationFormat,
)
from packages.core.models.article import (
    ArticleDraftResult,
    ArticleOutline,
    ArticleQualitySummary,
    ArticleSection,
    DraftResult,
    OutlineSection,
    Paragraph,
    QualityCheckResult,
)
from packages.core.models.bibliography import FormattedBibliography
from packages.core.models.export import (
    ArticleExportBundle,
    ArticleExportMetadata,
    ExportResult,
    PDFExportResult,
)
from packages.workers.article import pdf_export as pdf_export_module
from packages.workers.article.docx_export import DOCXExporter
from packages.workers.article.pdf_export import (
    ArticlePDFPipeline,
    PDFExporter,
    _find_libreoffice,
    _pdf_filename,
)

# ---------------------------------------------------------------------------
# LibreOffice availability gate
# ---------------------------------------------------------------------------

_LIBREOFFICE_WINDOWS_PATHS = (
    r"C:\Program Files\LibreOffice\program\soffice.exe",
    r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
)
_LIBREOFFICE_UNIX_PATHS = (
    "/usr/bin/libreoffice",
    "/usr/bin/soffice",
    "/snap/bin/libreoffice",
    "/Applications/LibreOffice.app/Contents/MacOS/soffice",
)


def _detect_libreoffice() -> bool:
    if any(shutil.which(name) for name in ("libreoffice", "soffice", "soffice.exe")):
        return True
    candidates = (
        _LIBREOFFICE_WINDOWS_PATHS if platform.system() == "Windows" else _LIBREOFFICE_UNIX_PATHS
    )
    return any(os.path.isfile(p) for p in candidates)


LIBREOFFICE_AVAILABLE = _detect_libreoffice()
needs_libreoffice = pytest.mark.skipif(
    not LIBREOFFICE_AVAILABLE,
    reason="LibreOffice not installed",
)


# ---------------------------------------------------------------------------
# Fixtures: minimal DOCX bytes via python-docx, plus full article DOCX
# ---------------------------------------------------------------------------


def _minimal_docx_bytes(text: str = "Hello World") -> bytes:
    document = Document()
    document.add_paragraph(text)
    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _make_section(article_id: UUID, index: int, title: str, body: str) -> ArticleSection:
    paragraphs = [Paragraph(text=body, citations=[])]
    return ArticleSection(
        article_id=article_id,
        section_index=index,
        title=title,
        paragraphs=paragraphs,
        word_count=len(body.split()),
        status=ArticleSectionStatus.DRAFT,
        created_at=datetime.now(UTC),
    )


def _make_draft(sections: list[ArticleSection]) -> ArticleDraftResult:
    summary = ArticleQualitySummary(
        sections_passed=len(sections),
        sections_failed=0,
        sections_revised=0,
        overall_score=1.0,
        weakest_section="",
        strongest_section="",
    )
    return ArticleDraftResult(
        sections=[
            DraftResult(
                section=s,
                quality_check=QualityCheckResult(
                    passed=True, checks_passed=["ok"], checks_failed=[], overall_score=1.0
                ),
            )
            for s in sections
        ],
        total_word_count=sum(s.word_count for s in sections),
        total_llm_calls=len(sections),
        total_tokens=100 * len(sections),
        estimated_cost_usd=0.01,
        quality_summary=summary,
        warnings=[],
    )


def _make_outline(titles: list[str]) -> ArticleOutline:
    return ArticleOutline(
        title="Test Article",
        structure=ArticleStructure.REFERAT,
        sections=[
            OutlineSection(title=t, target_words=200, purpose="purpose body text") for t in titles
        ],
        thesis="A non-trivial thesis statement that meets the length requirement.",
        total_target_words=200 * len(titles),
    )


def _make_metadata() -> ArticleExportMetadata:
    return ArticleExportMetadata(
        title="Test Article",
        author_name="Tursunov B.",
        author_group="IF-22-01",
        supervisor_name="Karimov A.",
        supervisor_title="dots., professor",
        university_name="Toshkent davlat universiteti",
        faculty_name="Informatika fakulteti",
        department_name="Dasturlash kafedrasi",
        city="Toshkent",
        year=2026,
        article_type=ArticleStructure.REFERAT,
        citation_format=CitationFormat.GOST,
        keywords=[],
        abstract_text=None,
    )


async def _build_real_article_docx() -> ExportResult:
    article_id = uuid4()
    sections = [
        _make_section(
            article_id,
            i,
            title,
            "Bu test paragrafi. " * 20,
        )
        for i, title in enumerate(["Kirish", "Asosiy qism", "Xulosa"])
    ]
    draft = _make_draft(sections)
    outline = _make_outline([s.title for s in sections])
    bibliography = FormattedBibliography(
        entries=[],
        style=CitationFormat.GOST,
        language="uz",
        total_entries=0,
    )
    metadata = _make_metadata()
    return await DOCXExporter().export(draft, bibliography, None, outline, metadata, "uz")


# ---------------------------------------------------------------------------
# Fake subprocess used by the timeout / non-zero-exit tests
# ---------------------------------------------------------------------------


class _FakeProcess:
    """Stand-in for :class:`asyncio.subprocess.Process` used in error-path tests."""

    def __init__(
        self,
        *,
        hang: bool = False,
        returncode: int = 0,
        stderr: bytes = b"",
        stdout: bytes = b"",
    ) -> None:
        self._hang = hang
        self.returncode: int | None = returncode
        self._stderr = stderr
        self._stdout = stdout
        self.killed = False

    async def communicate(self) -> tuple[bytes, bytes]:
        if self._hang:
            await asyncio.sleep(60)
        return self._stdout, self._stderr

    def kill(self) -> None:
        self.killed = True

    async def wait(self) -> int:
        return self.returncode if self.returncode is not None else 0


def _patch_subprocess(
    monkeypatch: pytest.MonkeyPatch, process: _FakeProcess, *, write_pdf: bytes | None = None
) -> None:
    """Replace :func:`asyncio.create_subprocess_exec` to return ``process``.

    If ``write_pdf`` is given, the patched function also drops a fake PDF
    file at the expected ``--outdir`` path so the success-path read does
    not raise. Tests that need conversion to fail outright omit it.
    """

    async def _fake_create(*args: str, **_kwargs: Any) -> _FakeProcess:
        if write_pdf is not None:
            # Args: [soffice, --headless, --convert-to, pdf, --outdir, OUT, DOCX]
            outdir = args[5]
            docx_path = args[6]
            pdf_name = os.path.splitext(os.path.basename(docx_path))[0] + ".pdf"
            with open(os.path.join(outdir, pdf_name), "wb") as handle:
                handle.write(write_pdf)
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_create)
    monkeypatch.setattr(pdf_export_module, "_find_libreoffice", lambda: "/fake/soffice")


# ---------------------------------------------------------------------------
# Binary discovery
# ---------------------------------------------------------------------------


@needs_libreoffice
def test_find_libreoffice_returns_existing_path() -> None:
    path = _find_libreoffice()
    assert os.path.isfile(path)


def test_find_libreoffice_raises_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pdf_export_module.shutil, "which", lambda _name: None)
    monkeypatch.setattr(pdf_export_module.os.path, "isfile", lambda _p: False)
    with pytest.raises(FileNotFoundError, match="LibreOffice not found"):
        _find_libreoffice()


# ---------------------------------------------------------------------------
# Filename mapping
# ---------------------------------------------------------------------------


def test_pdf_filename_swaps_docx_extension() -> None:
    assert _pdf_filename("my_article.docx") == "my_article.pdf"


def test_pdf_filename_handles_uppercase_extension() -> None:
    assert _pdf_filename("Report.DOCX") == "Report.pdf"


def test_pdf_filename_appends_when_no_extension() -> None:
    assert _pdf_filename("Report") == "Report.pdf"


# ---------------------------------------------------------------------------
# Real conversion (requires LibreOffice)
# ---------------------------------------------------------------------------


@needs_libreoffice
@pytest.mark.asyncio
async def test_export_simple_docx_to_pdf() -> None:
    docx_bytes = _minimal_docx_bytes("Hello World from Nashr")
    result = await PDFExporter().export(docx_bytes, "hello.docx")
    assert result.success is True
    assert result.error is None
    assert result.file_bytes[:4] == b"%PDF"
    assert result.file_size_bytes > 0
    assert result.file_size_bytes == len(result.file_bytes)
    assert result.conversion_time_ms > 0
    assert result.source_docx_size == len(docx_bytes)


@needs_libreoffice
@pytest.mark.asyncio
async def test_export_preserves_filename() -> None:
    result = await PDFExporter().export(_minimal_docx_bytes(), "my_article.docx")
    assert result.filename == "my_article.pdf"


@needs_libreoffice
@pytest.mark.asyncio
async def test_export_real_article_docx() -> None:
    docx_result = await _build_real_article_docx()
    pdf_result = await PDFExporter().export_from_docx_result(docx_result)
    assert pdf_result.success is True
    assert pdf_result.file_bytes[:4] == b"%PDF"
    # Sanity: a real article should not produce a suspiciously tiny PDF
    assert pdf_result.file_size_bytes > docx_result.file_size_bytes * 0.3


# ---------------------------------------------------------------------------
# Counters / metadata propagation (no LibreOffice needed: patched subprocess)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_export_records_source_docx_size(monkeypatch: pytest.MonkeyPatch) -> None:
    docx_bytes = _minimal_docx_bytes("size-check")
    _patch_subprocess(
        monkeypatch,
        _FakeProcess(returncode=0),
        write_pdf=b"%PDF-1.4\n%fake content\n",
    )
    result = await PDFExporter().export(docx_bytes, "size.docx")
    assert result.success is True
    assert result.source_docx_size == len(docx_bytes)


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_export_handles_libreoffice_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise() -> str:
        raise FileNotFoundError("LibreOffice not found. Install it: ...")

    monkeypatch.setattr(pdf_export_module, "_find_libreoffice", _raise)
    result = await PDFExporter().export(_minimal_docx_bytes(), "doc.docx")
    assert result.success is False
    assert result.file_bytes == b""
    assert result.file_size_bytes == 0
    assert result.error is not None
    assert "LibreOffice not found" in result.error
    assert result.filename == "doc.pdf"


@pytest.mark.asyncio
async def test_export_handles_conversion_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeProcess(hang=True)
    _patch_subprocess(monkeypatch, fake)
    exporter = PDFExporter()
    exporter.LIBREOFFICE_TIMEOUT = 1
    result = await exporter.export(_minimal_docx_bytes(), "doc.docx")
    assert result.success is False
    assert result.error is not None
    assert "timed out" in result.error
    assert fake.killed is True


@pytest.mark.asyncio
async def test_export_handles_nonzero_exit_code(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_subprocess(monkeypatch, _FakeProcess(returncode=137, stderr=b"OOM killed"))
    result = await PDFExporter().export(_minimal_docx_bytes(), "doc.docx")
    assert result.success is False
    assert result.error is not None
    assert "exit 137" in result.error
    assert "OOM killed" in result.error


@needs_libreoffice
@pytest.mark.asyncio
async def test_export_handles_corrupt_docx() -> None:
    corrupt = b"this is not a docx file at all"
    result = await PDFExporter().export(corrupt, "corrupt.docx")
    assert result.success is False
    assert result.file_bytes == b""
    assert result.error is not None


# ---------------------------------------------------------------------------
# Convenience method + temp-file cleanup
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_export_from_docx_result_threads_filename(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    docx_result = ExportResult(
        file_bytes=_minimal_docx_bytes("convenience"),
        filename="convenience_referat.docx",
        file_size_bytes=100,
        page_count_estimate=1,
        word_count=10,
        section_count=1,
        citation_count=0,
        bibliography_count=0,
        warnings=[],
    )
    _patch_subprocess(
        monkeypatch,
        _FakeProcess(returncode=0),
        write_pdf=b"%PDF-1.4\nfake\n",
    )
    pdf_result = await PDFExporter().export_from_docx_result(docx_result)
    assert pdf_result.success is True
    assert pdf_result.filename == "convenience_referat.pdf"
    assert pdf_result.source_docx_size == len(docx_result.file_bytes)


@pytest.mark.asyncio
async def test_export_cleans_temp_files(monkeypatch: pytest.MonkeyPatch) -> None:
    """The TemporaryDirectory context must be torn down after export."""

    captured: dict[str, str] = {}

    async def _fake_create(*args: str, **_kwargs: Any) -> _FakeProcess:
        outdir = args[5]
        docx_path = args[6]
        captured["outdir"] = outdir
        pdf_name = os.path.splitext(os.path.basename(docx_path))[0] + ".pdf"
        with open(os.path.join(outdir, pdf_name), "wb") as handle:
            handle.write(b"%PDF-1.4\nfake\n")
        return _FakeProcess(returncode=0)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_create)
    monkeypatch.setattr(pdf_export_module, "_find_libreoffice", lambda: "/fake/soffice")

    result = await PDFExporter().export(_minimal_docx_bytes(), "doc.docx")
    assert result.success is True
    assert "outdir" in captured
    assert not os.path.exists(captured["outdir"])


# ---------------------------------------------------------------------------
# ArticlePDFPipeline
# ---------------------------------------------------------------------------


@needs_libreoffice
@pytest.mark.asyncio
async def test_article_pdf_pipeline_produces_both() -> None:
    article_id = uuid4()
    section = _make_section(article_id, 0, "Kirish", "Birinchi paragraf matni. " * 15)
    draft = _make_draft([section])
    outline = _make_outline(["Kirish"])
    bibliography = FormattedBibliography(
        entries=[],
        style=CitationFormat.GOST,
        language="uz",
        total_entries=0,
    )
    metadata = _make_metadata()

    bundle = await ArticlePDFPipeline().export(draft, bibliography, None, outline, metadata, "uz")

    assert bundle.docx.file_bytes
    assert bundle.docx.filename.endswith(".docx")
    assert bundle.pdf.success is True
    assert bundle.pdf.file_bytes[:4] == b"%PDF"
    assert bundle.pdf.filename.endswith(".pdf")


@pytest.mark.asyncio
async def test_article_pdf_pipeline_pdf_failure_keeps_docx(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PDF conversion failure must not invalidate the DOCX deliverable."""

    article_id = uuid4()
    section = _make_section(article_id, 0, "Kirish", "Test matni. " * 10)
    draft = _make_draft([section])
    outline = _make_outline(["Kirish"])
    bibliography = FormattedBibliography(
        entries=[],
        style=CitationFormat.GOST,
        language="uz",
        total_entries=0,
    )
    metadata = _make_metadata()

    def _raise() -> str:
        raise FileNotFoundError("LibreOffice not found.")

    monkeypatch.setattr(pdf_export_module, "_find_libreoffice", _raise)

    bundle = await ArticlePDFPipeline().export(draft, bibliography, None, outline, metadata, "uz")
    assert bundle.docx.file_bytes
    assert bundle.docx.file_size_bytes > 0
    # The DOCX should be a real ZIP container (DOCX is a ZIP under the hood)
    assert bundle.docx.file_bytes[:2] == b"PK"
    assert bundle.pdf.success is False
    assert bundle.pdf.file_bytes == b""
    assert bundle.pdf.error is not None


# ---------------------------------------------------------------------------
# Model validation + round-trip
# ---------------------------------------------------------------------------


def test_pdf_export_result_round_trip() -> None:
    original = PDFExportResult(
        file_bytes=b"%PDF-1.4\nbytes\n",
        filename="doc.pdf",
        file_size_bytes=15,
        source_docx_size=200,
        conversion_time_ms=123,
        success=True,
        error=None,
    )
    rebuilt = PDFExportResult.model_validate(original.model_dump())
    assert rebuilt == original


def test_pdf_export_result_failure_state_is_valid() -> None:
    failure = PDFExportResult(
        file_bytes=b"",
        filename="doc.pdf",
        file_size_bytes=0,
        source_docx_size=512,
        conversion_time_ms=8,
        success=False,
        error="LibreOffice not found",
    )
    rebuilt = PDFExportResult.model_validate(failure.model_dump())
    assert rebuilt.success is False
    assert rebuilt.error == "LibreOffice not found"
    assert rebuilt.file_size_bytes == 0


def test_article_export_bundle_round_trip() -> None:
    docx_result = ExportResult(
        file_bytes=b"PK\x03\x04 fake docx",
        filename="article.docx",
        file_size_bytes=15,
        page_count_estimate=1,
        word_count=10,
        section_count=1,
        citation_count=0,
        bibliography_count=0,
        warnings=[],
    )
    pdf_result = PDFExportResult(
        file_bytes=b"%PDF-1.4 fake pdf",
        filename="article.pdf",
        file_size_bytes=17,
        source_docx_size=15,
        conversion_time_ms=42,
        success=True,
        error=None,
    )
    bundle = ArticleExportBundle(docx=docx_result, pdf=pdf_result)
    rebuilt = ArticleExportBundle.model_validate(bundle.model_dump())
    assert rebuilt == bundle
