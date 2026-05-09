"""Magika-backed file validation service for the upload pipeline.

Every byte stream the user sends — Telegram document, web upload, signed-URL
fetch — passes through ``FileValidationService.validate`` before any parsing
or LLM call touches it. The service rejects scripts, executables, oversized
files, low-confidence detections, and empty payloads. Extension/content
mismatches produce a non-blocking warning, since the content's true type is
what matters for processing.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Final

from magika import Magika
from magika.types import MagikaResult

from packages.core.constants import (
    ALLOWED_FILE_TYPES,
    BLOCKED_FILE_TYPES,
    MAGIKA_MIN_CONFIDENCE,
    MAX_FILE_SIZE_BYTES,
)
from packages.core.models.source import FileValidationResult

logger = logging.getLogger(__name__)


EXTENSION_MAP: Final[dict[str, frozenset[str]]] = {
    "pdf": frozenset({"pdf"}),
    "docx": frozenset({"docx", "doc"}),
    "pptx": frozenset({"pptx", "ppt"}),
    "xlsx": frozenset({"xlsx", "xls"}),
    "png": frozenset({"png"}),
    "jpeg": frozenset({"jpg", "jpeg"}),
    "webp": frozenset({"webp"}),
    "gif": frozenset({"gif"}),
    "txt": frozenset({"txt"}),
    "csv": frozenset({"csv"}),
    "markdown": frozenset({"md", "markdown"}),
}

UNKNOWN_MIME: Final[str] = "application/octet-stream"


class FileValidationService:
    """Validates upload bytes against Magika and the project allow/block lists.

    Magika is a synchronous CPU-bound model, so detection is dispatched via
    ``asyncio.to_thread`` to keep the event loop responsive under concurrent
    uploads. The Magika call itself is wrapped in a try/except so an
    unexpected library failure surfaces as a clean rejection rather than a
    500 to the user.
    """

    def __init__(self, magika: Magika | None = None) -> None:
        self._magika = magika if magika is not None else Magika()

    async def validate(
        self,
        file_bytes: bytes,
        claimed_filename: str,
    ) -> FileValidationResult:
        """Run the full validation pipeline against a single uploaded payload.

        Order matters: empty -> oversize -> magika detect -> confidence ->
        blocked -> allowed -> extension match. The first failure short-
        circuits with a populated ``rejection_reason``.
        """

        size = len(file_bytes)

        if size == 0:
            return _reject(
                detected_type="empty",
                mime_type=UNKNOWN_MIME,
                confidence=0.0,
                file_size_bytes=0,
                reason="File is empty.",
            )

        if size > MAX_FILE_SIZE_BYTES:
            mb = MAX_FILE_SIZE_BYTES // (1024 * 1024)
            return _reject(
                detected_type="oversize",
                mime_type=UNKNOWN_MIME,
                confidence=0.0,
                file_size_bytes=size,
                reason=f"File size {size} bytes exceeds the {mb} MB limit.",
            )

        try:
            result = await asyncio.to_thread(self._magika.identify_bytes, file_bytes)
        except Exception as exc:
            logger.error(
                "Magika analysis failed",
                exc_info=exc,
                extra={"upload_filename": claimed_filename, "upload_size": size},
            )
            return _reject(
                detected_type="unknown",
                mime_type=UNKNOWN_MIME,
                confidence=0.0,
                file_size_bytes=size,
                reason="File could not be analyzed. It may be corrupted.",
            )

        detected, mime, confidence = _unpack(result)

        if not result.ok:
            logger.warning(
                "magika returned non-ok status for upload",
                extra={
                    "upload_filename": claimed_filename,
                    "upload_size": size,
                    "magika_status": result.status,
                },
            )
            return _reject(
                detected_type=detected or "unknown",
                mime_type=mime or UNKNOWN_MIME,
                confidence=confidence,
                file_size_bytes=size,
                reason="File type could not be confidently determined.",
            )

        if confidence < MAGIKA_MIN_CONFIDENCE:
            return _reject(
                detected_type=detected,
                mime_type=mime,
                confidence=confidence,
                file_size_bytes=size,
                reason="File type could not be confidently determined.",
            )

        if detected in BLOCKED_FILE_TYPES:
            return _reject(
                detected_type=detected,
                mime_type=mime,
                confidence=confidence,
                file_size_bytes=size,
                reason=f"File type '{detected}' is not allowed.",
            )

        if detected not in ALLOWED_FILE_TYPES:
            return _reject(
                detected_type=detected,
                mime_type=mime,
                confidence=confidence,
                file_size_bytes=size,
                reason=f"Unsupported file type: {detected}.",
            )

        mismatch, warning = _check_extension(claimed_filename, detected)

        return FileValidationResult(
            valid=True,
            detected_type=detected,
            mime_type=mime,
            confidence=confidence,
            file_size_bytes=size,
            extension_mismatch=mismatch,
            rejection_reason=None,
            warning=warning,
        )


def _unpack(result: MagikaResult) -> tuple[str, str, float]:
    """Pull plain (label, mime, score) from Magika's structured result."""
    label = str(result.output.label)
    mime = result.output.mime_type or UNKNOWN_MIME
    score = float(result.score)
    return label, mime, score


def _reject(
    *,
    detected_type: str,
    mime_type: str,
    confidence: float,
    file_size_bytes: int,
    reason: str,
) -> FileValidationResult:
    return FileValidationResult(
        valid=False,
        detected_type=detected_type,
        mime_type=mime_type,
        confidence=confidence,
        file_size_bytes=file_size_bytes,
        extension_mismatch=False,
        rejection_reason=reason,
        warning=None,
    )


def _check_extension(claimed_filename: str, detected_type: str) -> tuple[bool, str | None]:
    """Compare the claimed extension against the expected set for ``detected_type``.

    Returns ``(mismatch, warning_or_none)``. A mismatch is *not* a rejection;
    callers should surface the warning to the user but still process the file.
    """

    expected = EXTENSION_MAP.get(detected_type)
    if expected is None:
        return False, None

    suffix = Path(claimed_filename).suffix.lower().lstrip(".")
    if not suffix:
        return False, None

    if suffix in expected:
        return False, None

    expected_repr = ", ".join(sorted(f".{ext}" for ext in expected))
    return (
        True,
        (
            f"File extension '.{suffix}' does not match detected type "
            f"'{detected_type}' (expected {expected_repr})."
        ),
    )
