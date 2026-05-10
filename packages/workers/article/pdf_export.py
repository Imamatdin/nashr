"""PDF export for drafted articles via LibreOffice headless conversion.

The DOCX exporter already encodes the Uzbek university submission
standard (A4, Times New Roman 14pt, 1.5-line spacing, exact margins,
title page, TOC, page numbers, footnotes). Producing a faithful PDF
therefore reduces to feeding that DOCX to a renderer that respects the
formatting — LibreOffice's headless ``soffice --convert-to pdf`` is the
standard server-side answer and preserves fonts, margins, page numbers,
and bibliography hanging indents end-to-end.

This module exposes:

* :class:`PDFExporter` — DOCX bytes → PDF bytes via a temp dir + a
  subprocess call to LibreOffice. Always returns a
  :class:`PDFExportResult`; failure modes (binary missing, conversion
  timeout, corrupt input) become ``success=False`` with an explanatory
  ``error`` so callers never need to wrap in try/except.
* :class:`ArticlePDFPipeline` — convenience that runs
  :class:`DOCXExporter` then :class:`PDFExporter` and returns both
  artefacts as an :class:`ArticleExportBundle`. PDF failure does not
  drop the DOCX.

Cross-platform binary discovery (PATH first, then per-OS install
locations) lives in module-scope :func:`_find_libreoffice` so tests can
monkeypatch it.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import platform
import shutil
import tempfile
import time

from packages.core.models.article import ArticleDraftResult, ArticleOutline
from packages.core.models.bibliography import (
    CitationMetadata,
    FormattedBibliography,
)
from packages.core.models.export import (
    ArticleExportBundle,
    ArticleExportMetadata,
    ExportResult,
    PDFExportResult,
)
from packages.core.models.verification import CitationVerificationReport
from packages.workers.article.docx_export import DOCXExporter


def _find_libreoffice() -> str:
    """Locate the LibreOffice binary; raise :class:`FileNotFoundError` if absent.

    Order: PATH (``libreoffice``/``soffice``/``soffice.exe``) → the OS-
    specific install paths LibreOffice's MSI/DMG/deb packages drop into.
    Module-level so tests can monkeypatch it.
    """

    for name in ("libreoffice", "soffice", "soffice.exe"):
        found = shutil.which(name)
        if found:
            return found

    system = platform.system()
    if system == "Windows":
        candidates = [
            r"C:\Program Files\LibreOffice\program\soffice.exe",
            r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
        ]
    elif system == "Darwin":
        candidates = ["/Applications/LibreOffice.app/Contents/MacOS/soffice"]
    else:
        candidates = [
            "/usr/bin/libreoffice",
            "/usr/bin/soffice",
            "/snap/bin/libreoffice",
        ]

    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate

    raise FileNotFoundError(
        "LibreOffice not found. Install it: "
        "Ubuntu: sudo apt-get install libreoffice-writer, "
        "macOS: brew install --cask libreoffice, "
        "Windows: https://www.libreoffice.org/download/"
    )


def _pdf_filename(filename: str) -> str:
    """Mirror the DOCX filename onto the .pdf extension; preserve the stem."""

    if filename.lower().endswith(".docx"):
        return filename[:-5] + ".pdf"
    if filename.lower().endswith(".pdf"):
        return filename
    return filename + ".pdf"


class PDFExporter:
    """Convert a DOCX file (bytes) to a PDF file (bytes) via LibreOffice.

    Stateless — one instance can serve every export. Public surface is
    :meth:`export` (raw bytes) and :meth:`export_from_docx_result` (the
    :class:`ExportResult` produced by :class:`DOCXExporter`). Both
    return :class:`PDFExportResult` and never raise on a conversion
    failure.
    """

    LIBREOFFICE_TIMEOUT: int = 60

    async def export(self, docx_bytes: bytes, filename: str) -> PDFExportResult:
        """Convert ``docx_bytes`` to PDF; return the bytes + counters or an error."""

        start = time.monotonic()
        out_filename = _pdf_filename(filename)

        try:
            pdf_bytes = await self._run_conversion(docx_bytes, filename)
        except (FileNotFoundError, TimeoutError, RuntimeError) as exc:
            return PDFExportResult(
                file_bytes=b"",
                filename=out_filename,
                file_size_bytes=0,
                source_docx_size=len(docx_bytes),
                conversion_time_ms=int((time.monotonic() - start) * 1000),
                success=False,
                error=str(exc),
            )

        return PDFExportResult(
            file_bytes=pdf_bytes,
            filename=out_filename,
            file_size_bytes=len(pdf_bytes),
            source_docx_size=len(docx_bytes),
            conversion_time_ms=int((time.monotonic() - start) * 1000),
            success=True,
            error=None,
        )

    async def export_from_docx_result(self, docx_result: ExportResult) -> PDFExportResult:
        """Convert an :class:`ExportResult` (from :class:`DOCXExporter`) to PDF."""

        return await self.export(docx_result.file_bytes, docx_result.filename)

    # -- internals ---------------------------------------------------------

    async def _run_conversion(self, docx_bytes: bytes, filename: str) -> bytes:
        """Drive a temp dir + LibreOffice subprocess; return the PDF bytes.

        Raises :class:`FileNotFoundError` (binary or output missing),
        :class:`TimeoutError`, or :class:`RuntimeError` (non-zero exit).
        Caller maps these onto a failed :class:`PDFExportResult`.
        """

        soffice = _find_libreoffice()

        with tempfile.TemporaryDirectory(prefix="nashr_pdf_") as tmpdir:
            docx_name = filename if filename.lower().endswith(".docx") else f"{filename}.docx"
            docx_path = os.path.join(tmpdir, os.path.basename(docx_name))
            with open(docx_path, "wb") as handle:
                handle.write(docx_bytes)

            await self._invoke_libreoffice(soffice, docx_path, tmpdir)

            pdf_name = os.path.splitext(os.path.basename(docx_path))[0] + ".pdf"
            pdf_path = os.path.join(tmpdir, pdf_name)
            if not os.path.isfile(pdf_path):
                raise FileNotFoundError(f"Expected PDF not found at {pdf_path}")

            with open(pdf_path, "rb") as handle:
                return handle.read()

    async def _invoke_libreoffice(self, soffice: str, docx_path: str, output_dir: str) -> None:
        """Spawn LibreOffice headless; enforce timeout; surface non-zero exit codes."""

        cmd = [
            soffice,
            "--headless",
            "--convert-to",
            "pdf",
            "--outdir",
            output_dir,
            docx_path,
        ]

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=self.LIBREOFFICE_TIMEOUT,
            )
        except TimeoutError as exc:
            with contextlib.suppress(ProcessLookupError):
                process.kill()
            with contextlib.suppress(Exception):
                await process.wait()
            raise TimeoutError(
                f"LibreOffice conversion timed out after {self.LIBREOFFICE_TIMEOUT}s"
            ) from exc

        if process.returncode != 0:
            detail = (stderr or b"").decode(errors="replace").strip() or (
                (stdout or b"").decode(errors="replace").strip()
            )
            raise RuntimeError(
                f"LibreOffice conversion failed (exit {process.returncode}): {detail}"
            )


class ArticlePDFPipeline:
    """Run :class:`DOCXExporter` then :class:`PDFExporter` in one call.

    Returns an :class:`ArticleExportBundle` carrying both artefacts. If
    PDF conversion fails the bundle still contains a valid DOCX — we
    never lose the canonical deliverable because the renderer is sick.
    """

    def __init__(
        self,
        docx_exporter: DOCXExporter | None = None,
        pdf_exporter: PDFExporter | None = None,
    ) -> None:
        self._docx_exporter = docx_exporter if docx_exporter is not None else DOCXExporter()
        self._pdf_exporter = pdf_exporter if pdf_exporter is not None else PDFExporter()

    async def export(
        self,
        draft: ArticleDraftResult,
        bibliography: FormattedBibliography,
        verification: CitationVerificationReport | None,
        outline: ArticleOutline,
        metadata: ArticleExportMetadata,
        language: str,
        citation_metadata: list[CitationMetadata] | None = None,
    ) -> ArticleExportBundle:
        """Render DOCX + PDF for one article; return both as a single bundle."""

        docx_result = await self._docx_exporter.export(
            draft,
            bibliography,
            verification,
            outline,
            metadata,
            language,
            citation_metadata=citation_metadata,
        )
        pdf_result = await self._pdf_exporter.export_from_docx_result(docx_result)
        return ArticleExportBundle(docx=docx_result, pdf=pdf_result)


__all__ = [
    "ArticlePDFPipeline",
    "PDFExporter",
]
