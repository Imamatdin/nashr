"""One hardened LibreOffice runner, shared by deck and article exports (D3).

Every PPTX-to-PDF and DOCX-to-PDF conversion in the system goes through
:func:`convert`. The CLI deck renderer and the legacy article pipeline used to
shell out to ``soffice`` themselves, each with its own flags, timeout and
cleanup; this module is the single place that does it safely:

- a fresh temp dir per call, with the input copied in under a fixed safe name,
  an isolated LibreOffice user profile, and HOME/TMPDIR pointed inside it, so one
  conversion cannot see or corrupt another's state;
- ``start_new_session=True`` and, on timeout, a SIGKILL of the whole process
  group, so a wedged ``soffice`` (which forks children) cannot outlive the call;
- typed errors for every failure (timeout, non-zero exit, missing or empty
  output, a PDF pypdfium2 cannot open), each carrying a bounded stderr excerpt,
  never the raw bytes or secrets;
- fontconfig pointed at the repo ``fonts/`` directory so the render uses the
  bundled fonts, plus an optional check that reads the PDF's embedded font names
  and refuses a render that substituted a font outside the expected families;
- one conversion at a time per process (LibreOffice is not safe to run
  concurrently against one profile), with the blocking subprocess run in a
  thread so the event loop keeps turning;
- the temp dir removed on every path.

The LibreOffice version is pinned as a constant (:data:`PINNED_LIBREOFFICE_VERSION`),
not read live: the renderer version (packages/platform/exports.py) must be
computable in the API container, which has no LibreOffice. The worker entrypoint
calls :func:`assert_libreoffice_version` at start-up to refuse a mismatched
binary; conversions themselves are never version-gated, so the CI and
workstation suites run honestly against whatever LibreOffice they ship.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import os
import re
import shutil
import signal
import subprocess
import tempfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

# Production ships Debian's LibreOffice (python:3.13-slim, bookworm: 7.4). The
# Dockerfile pins the packages to this major.minor and the worker entrypoint
# refuses to start on anything else. CI (24.2) and this pod (7.3) run the
# conversion tests ungated and only log their version.
PINNED_LIBREOFFICE_VERSION = "7.4"

# fonts/ at the repo root carries the bundled families.
_FONTS_DIR = Path(__file__).resolve().parents[2] / "fonts"

# How much of a failed run's stderr is kept in an error (never the input bytes).
_STDERR_LIMIT = 4000

# One LibreOffice conversion at a time per process.
_CONVERT_LOCK = asyncio.Semaphore(1)

_VERSION_RE = re.compile(r"LibreOffice\s+(\d+)\.(\d+)")
# A subset-embedded font is named like "ABCDEF+IBMPlexSerif-Bold"; drop the tag.
_SUBSET_PREFIX_RE = re.compile(r"^[A-Z]{6}\+")


@dataclass(frozen=True)
class _Target:
    input_suffix: str
    convert_to: str


class OfficeTarget(Enum):
    """A supported conversion: the input kind and the LibreOffice export filter."""

    PDF_FROM_PPTX = _Target("pptx", "pdf:impress_pdf_Export")
    PDF_FROM_DOCX = _Target("docx", "pdf:writer_pdf_Export")


@dataclass(frozen=True)
class ConvertedFile:
    """The result of one conversion: the PDF bytes and what they contain."""

    pdf_bytes: bytes
    page_count: int
    embedded_fonts: frozenset[str]


class OfficeRenderError(Exception):
    """Base class for every office-render failure."""


class LibreOfficeUnavailableError(OfficeRenderError):
    """LibreOffice is missing, or its version does not match the pin."""


class OfficeTimeoutError(OfficeRenderError):
    """The conversion did not finish within its timeout; the process was killed."""


class OfficeConversionError(OfficeRenderError):
    """LibreOffice exited non-zero, or produced no/empty/unreadable output."""


class UnexpectedFontError(OfficeRenderError):
    """The PDF embeds a font outside the expected families (a silent substitution)."""


def find_soffice() -> str:
    """The LibreOffice binary to run.

    ``NASHR_SOFFICE_BIN`` overrides discovery (the tests point it at a fake
    script); otherwise the first of ``soffice``/``libreoffice`` on PATH is used.
    """

    override = os.environ.get("NASHR_SOFFICE_BIN")
    if override:
        if not Path(override).is_file() or not os.access(override, os.X_OK):
            raise LibreOfficeUnavailableError(f"NASHR_SOFFICE_BIN is not executable: {override}")
        return override
    for name in ("soffice", "libreoffice"):
        found = shutil.which(name)
        if found:
            return found
    raise LibreOfficeUnavailableError("no soffice or libreoffice binary on PATH")


def libreoffice_version(soffice: str | None = None) -> str:
    """The full ``soffice --version`` string (for logging and the version gate)."""

    binary = soffice or find_soffice()
    try:
        result = subprocess.run(
            [binary, "--version"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise LibreOfficeUnavailableError(f"could not run {binary} --version: {exc}") from exc
    output = (result.stdout or result.stderr or "").strip()
    if not _VERSION_RE.search(output):
        raise LibreOfficeUnavailableError(f"unrecognised LibreOffice version line: {output!r}")
    return output


def assert_libreoffice_version(soffice: str | None = None) -> str:
    """Refuse to proceed unless the binary's major.minor matches the pin.

    Called by the worker entrypoint in the production image. Returns the full
    version string so the caller can log it.
    """

    full = libreoffice_version(soffice)
    match = _VERSION_RE.search(full)
    assert match is not None  # libreoffice_version already enforced this
    found = f"{match.group(1)}.{match.group(2)}"
    if found != PINNED_LIBREOFFICE_VERSION:
        raise LibreOfficeUnavailableError(
            f"LibreOffice {found} does not match the pinned {PINNED_LIBREOFFICE_VERSION}"
            f" (full version: {full})"
        )
    return full


def _fontconfig(tmp: Path) -> Path:
    """Write a fontconfig file that prefers the bundled fonts, return its path.

    The bundled fonts are copied into the temp dir rather than referenced in
    place: fontconfig writes a ``.uuid`` marker into every directory it scans, so
    pointing it at the repo ``fonts/`` would pollute the working tree (and fail on
    a read-only image). The copy, the cache and the marker all live in the temp
    dir and are removed with it.
    """

    conf = tmp / "fonts.conf"
    cache = tmp / "fc-cache"
    cache.mkdir()
    fonts = tmp / "fonts"
    fonts.mkdir()
    for font in _FONTS_DIR.glob("*"):
        if font.is_file() and font.suffix.lower() in (".ttf", ".otf", ".ttc"):
            shutil.copyfile(font, fonts / font.name)
    conf.write_text(
        '<?xml version="1.0"?>\n'
        '<!DOCTYPE fontconfig SYSTEM "fonts.dtd">\n'
        "<fontconfig>\n"
        f"  <dir>{fonts}</dir>\n"
        "  <dir>/usr/share/fonts</dir>\n"
        "  <dir>/usr/local/share/fonts</dir>\n"
        f"  <cachedir>{cache}</cachedir>\n"
        "</fontconfig>\n",
        encoding="utf-8",
    )
    return conf


def _embedded_fonts(pdf_bytes: bytes) -> frozenset[str]:
    """The base names of every font the PDF embeds, subset tags stripped."""

    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(pdf_bytes))
    names: set[str] = set()
    for page in reader.pages:
        resources = page.get("/Resources")
        if resources is None:
            continue
        fonts = resources.get("/Font")  # pyright: ignore[reportAttributeAccessIssue]
        if fonts is None:
            continue
        for font in fonts.values():  # pyright: ignore[reportAttributeAccessIssue]
            base = font.get_object().get("/BaseFont")
            if base is None:
                continue
            names.add(_SUBSET_PREFIX_RE.sub("", str(base).lstrip("/")))
    return frozenset(names)


def _family_stem(base_font: str) -> str:
    """The family part of a PDF base-font name (before the style suffix)."""

    return re.split(r"[-,]", base_font, maxsplit=1)[0].strip().lower()


def _check_fonts(fonts: frozenset[str], allowed: frozenset[str]) -> None:
    allowed_stems = {name.lower() for name in allowed}
    for base in fonts:
        if _family_stem(base) not in allowed_stems:
            raise UnexpectedFontError(
                f"PDF embeds an unexpected font {base!r}; allowed families: {sorted(allowed)}"
            )


def _open_pages(pdf_bytes: bytes) -> int:
    """Page count via pypdfium2; raises if the bytes are not a usable PDF."""

    import pypdfium2 as pdfium

    document = pdfium.PdfDocument(pdf_bytes)
    try:
        return len(document)
    finally:
        document.close()


def _convert_blocking(
    input_path: Path,
    target: OfficeTarget,
    timeout_s: float,
    allowed_font_families: frozenset[str] | None,
) -> ConvertedFile:
    spec = target.value
    tmp = Path(tempfile.mkdtemp(prefix="nashr_office_"))
    try:
        profile = tmp / "profile"
        profile.mkdir()
        staged = tmp / f"input.{spec.input_suffix}"
        shutil.copyfile(input_path, staged)
        conf = _fontconfig(tmp)

        env = {
            "HOME": str(tmp),
            "TMPDIR": str(tmp),
            "FONTCONFIG_FILE": str(conf),
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "LANG": "C.UTF-8",
        }
        cmd = [
            find_soffice(),
            "--headless",
            "--norestore",
            "--nolockcheck",
            "--nodefault",
            "--nologo",
            "--nofirststartwizard",
            f"-env:UserInstallation=file://{profile}",
            "--convert-to",
            spec.convert_to,
            "--outdir",
            str(tmp),
            str(staged),
        ]

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            start_new_session=True,
        )
        try:
            _, stderr = proc.communicate(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            _kill_group(proc)
            raise OfficeTimeoutError(
                f"LibreOffice did not convert {spec.input_suffix} within {timeout_s}s"
            ) from None

        if proc.returncode != 0:
            raise OfficeConversionError(f"LibreOffice exited {proc.returncode}: {_excerpt(stderr)}")

        output = tmp / "input.pdf"
        if not output.is_file():
            raise OfficeConversionError(f"LibreOffice produced no PDF: {_excerpt(stderr)}")
        pdf_bytes = output.read_bytes()
        if not pdf_bytes:
            raise OfficeConversionError("LibreOffice produced an empty PDF")

        try:
            page_count = _open_pages(pdf_bytes)
        except Exception as exc:
            raise OfficeConversionError(f"output is not a readable PDF: {exc}") from exc

        fonts = _embedded_fonts(pdf_bytes)
        if allowed_font_families is not None:
            _check_fonts(fonts, allowed_font_families)
        return ConvertedFile(pdf_bytes=pdf_bytes, page_count=page_count, embedded_fonts=fonts)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _kill_group(proc: subprocess.Popen[bytes]) -> None:
    # start_new_session=True made the child a process-group leader, so its pgid
    # is its pid; SIGKILL the whole group so forked soffice children die too.
    # POSIX-only; the worker runs on Linux (pyright targets Windows repo-wide).
    with contextlib.suppress(ProcessLookupError, OSError):
        os.killpg(proc.pid, signal.SIGKILL)  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]
    with contextlib.suppress(Exception):
        proc.wait(timeout=10)


def _excerpt(stderr: bytes | None) -> str:
    text = (stderr or b"").decode("utf-8", errors="replace").strip()
    return text[:_STDERR_LIMIT] if text else "(no stderr)"


async def convert(
    input_path: Path,
    target: OfficeTarget,
    *,
    timeout_s: float,
    allowed_font_families: frozenset[str] | None = None,
) -> ConvertedFile:
    """Convert ``input_path`` to PDF through LibreOffice, or raise a typed error.

    ``allowed_font_families``, when given, fails the render if the PDF embeds any
    font whose family is not listed (a LibreOffice substitution of a missing
    bundled font). Only one conversion runs at a time per process.
    """

    if timeout_s <= 0:
        raise ValueError("timeout_s must be positive")
    async with _CONVERT_LOCK:
        return await asyncio.to_thread(
            _convert_blocking, input_path, target, timeout_s, allowed_font_families
        )


__all__ = [
    "PINNED_LIBREOFFICE_VERSION",
    "ConvertedFile",
    "LibreOfficeUnavailableError",
    "OfficeConversionError",
    "OfficeRenderError",
    "OfficeTarget",
    "OfficeTimeoutError",
    "UnexpectedFontError",
    "assert_libreoffice_version",
    "convert",
    "find_soffice",
    "libreoffice_version",
]
