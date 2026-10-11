"""Publish rendered presentation files as immutable revision exports (ADR 0001).

A rendered file becomes downloadable only after three things hold: its bytes are
in the object store at the content-addressed key, a HEAD request has shown the
same size and SHA-256, and ``register_export`` has accepted it under a job claim
the publishing worker still holds. Any failure raises; nothing is half-published.
"""

from __future__ import annotations

import asyncio
import functools
import hashlib
from collections.abc import Mapping
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from packages.platform.document_models import ExportFileFormat, export_storage_key
from packages.platform.document_store import DocumentStore
from packages.platform.storage import FileStorage

_RENDERER_ROOT = Path(__file__).resolve().parents[1] / "presentation-worker"


@functools.cache
def renderer_version() -> str:
    """Identity of the renderer that produced an export: a hash of its source tree.

    The package version (0.1.0) has never moved, so it cannot say whether two
    renders are comparable. Line endings are normalized so a Windows checkout and
    the Linux image agree.
    """

    source = _RENDERER_ROOT / "src"
    if not source.is_dir():
        raise RuntimeError(f"renderer source not found at {source}")
    paths = sorted(path for path in source.rglob("*") if path.is_file())
    lockfile = _RENDERER_ROOT / "package-lock.json"
    if lockfile.is_file():
        paths.append(lockfile)
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.relative_to(_RENDERER_ROOT).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes().replace(b"\r\n", b"\n"))
        digest.update(b"\0")
    return f"pw-{digest.hexdigest()[:16]}"


def file_format(extension: str) -> ExportFileFormat:
    """The export format for a rendered file extension (``html``, ``pptx``, ``pdf``)."""

    return ExportFileFormat(extension.lstrip(".").lower())


class PublishedExport(BaseModel):
    """One file that is now registered for its revision."""

    model_config = ConfigDict(extra="forbid")

    format: ExportFileFormat
    storage_key: str
    sha256: str
    byte_size: int
    page_count: int | None
    newly_registered: bool


def _digest(path: Path) -> tuple[str, int]:
    data = path.read_bytes()
    return hashlib.sha256(data).hexdigest(), len(data)


def _page_count(fmt: ExportFileFormat, path: Path) -> int | None:
    if fmt is ExportFileFormat.PDF:
        import fitz  # pyright: ignore[reportMissingTypeStubs]

        with fitz.open(str(path)) as document:  # pyright: ignore[reportUnknownMemberType]
            return int(document.page_count)  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
    if fmt is ExportFileFormat.PPTX:
        from pptx import Presentation

        return len(Presentation(str(path)).slides)
    return None


class ExportPublisher:
    """Upload, verify and register every rendered file of one revision."""

    def __init__(self, store: DocumentStore, storage: FileStorage) -> None:
        self._store = store
        self._storage = storage

    async def publish(
        self,
        *,
        job_id: str,
        worker_id: str,
        document_id: str,
        revision_id: str,
        files: Mapping[ExportFileFormat, Path],
        version: str | None = None,
    ) -> list[PublishedExport]:
        """Publish all ``files`` or raise; the first failure stops the rest."""

        if not files:
            raise ValueError("publish requires at least one rendered file")
        renderer = version or renderer_version()
        published: list[PublishedExport] = []
        for fmt in sorted(files, key=lambda item: item.value):
            path = files[fmt]
            sha256, size = await asyncio.to_thread(_digest, path)
            pages = await asyncio.to_thread(_page_count, fmt, path)
            key = export_storage_key(document_id, revision_id, renderer, fmt, sha256)
            await self._storage.put_verified(path, key, sha256, size)
            status = await self._store.register_export(
                job_id=job_id,
                worker_id=worker_id,
                revision_id=revision_id,
                file_format=fmt,
                renderer_version=renderer,
                storage_key=key,
                sha256=sha256,
                byte_size=size,
                page_count=pages,
            )
            published.append(
                PublishedExport(
                    format=fmt,
                    storage_key=key,
                    sha256=sha256,
                    byte_size=size,
                    page_count=pages,
                    newly_registered=status == "registered",
                )
            )
        return published


__all__ = ["ExportPublisher", "PublishedExport", "file_format", "renderer_version"]
