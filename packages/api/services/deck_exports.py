"""Resolve which registered exports a deck viewer or share link may serve (ADR 0001).

Downloads are keyed by revision and renderer, never by project. The exact
(revision, current renderer) set is served when it exists. Otherwise the answer
is ``render_needed``, optionally with a clearly labelled fallback: the same
revision from an earlier renderer, or the newest older revision that has exports.
A fallback is never presented as the requested revision.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from packages.platform.document_models import DocumentKind, ExportFileFormat, ExportRecord
from packages.platform.document_store import DocumentStore
from packages.platform.exports import renderer_version
from packages.platform.storage import FileStorage

DECK_HTML_TTL_SECONDS = 900
DOWNLOAD_TTL_SECONDS = 3600
# Every primary format is delivered (SPEC §0 rule 7); fewer is a partial set.
REQUIRED_FORMATS: tuple[str, ...] = ("html", "pdf", "pptx")


class DeckExportState(StrEnum):
    """How much of the required set the current renderer has made for the revision."""

    READY = "ready"
    PARTIAL = "partial"
    RENDER_NEEDED = "render_needed"


class FallbackReason(StrEnum):
    """Why the fallback is not the requested export."""

    OLDER_RENDERER = "older_renderer"
    OLDER_REVISION = "older_revision"


class DownloadLink(BaseModel):
    """One signed download."""

    model_config = ConfigDict(extra="forbid")

    format: str
    url: str
    expires_in: int


class ExportLinks(BaseModel):
    """Signed URLs for one (revision, renderer) export set."""

    model_config = ConfigDict(extra="forbid")

    revision_id: str
    renderer_version: str
    created_at: datetime
    html_url: str | None
    html_expires_in: int
    downloads: list[DownloadLink]


class FallbackExport(ExportLinks):
    """An export set that is NOT the requested one; the UI must say so."""

    reason: FallbackReason


class DeckAccessView(BaseModel):
    """What the deck viewer may show for one revision."""

    model_config = ConfigDict(extra="forbid")

    revision_id: str
    head_revision_id: str
    is_head: bool
    state: DeckExportState
    renderer_version: str
    required_formats: list[str]
    available_formats: list[str]
    missing_formats: list[str]
    current: ExportLinks | None
    fallback: FallbackExport | None


class DeckNotReadyError(LookupError):
    """The project has no presentation head (or the revision is not in it)."""


def _groups(exports: list[ExportRecord]) -> list[list[ExportRecord]]:
    """Exports grouped by (revision, renderer), newest group first."""

    grouped: dict[tuple[str, str], list[ExportRecord]] = {}
    for record in exports:
        grouped.setdefault((record.revision_id, record.renderer_version), []).append(record)
    return sorted(
        grouped.values(), key=lambda group: max(item.created_at for item in group), reverse=True
    )


async def _links(storage: FileStorage, group: list[ExportRecord]) -> ExportLinks:
    html_url: str | None = None
    downloads: list[DownloadLink] = []
    for record in sorted(group, key=lambda item: item.format.value):
        if record.format is ExportFileFormat.HTML:
            html_url = await storage.signed_url(
                record.storage_key, expires_in=DECK_HTML_TTL_SECONDS
            )
            continue
        downloads.append(
            DownloadLink(
                format=record.format.value,
                url=await storage.signed_url(record.storage_key, expires_in=DOWNLOAD_TTL_SECONDS),
                expires_in=DOWNLOAD_TTL_SECONDS,
            )
        )
    return ExportLinks(
        revision_id=group[0].revision_id,
        renderer_version=group[0].renderer_version,
        created_at=max(item.created_at for item in group),
        html_url=html_url,
        html_expires_in=DECK_HTML_TTL_SECONDS,
        downloads=downloads,
    )


async def deck_access(
    store: DocumentStore, storage: FileStorage, project_id: str, revision_id: str | None
) -> DeckAccessView:
    """Signed URLs for ``revision_id`` (default: the head), or ``render_needed``."""

    head = await store.head(project_id, DocumentKind.PRESENTATION)
    if head is None:
        raise DeckNotReadyError("deck_not_ready")
    target = revision_id or head.revision_id
    if revision_id is not None and await store.revision_in_project(project_id, revision_id) is None:
        raise DeckNotReadyError("revision_not_found")
    version = renderer_version()
    groups = _groups(await store.exports([target]))
    current = next((g for g in groups if g[0].renderer_version == version), None)
    fallback: FallbackExport | None = None
    if current is None:
        fallback = await _fallback(store, storage, head.document_id, target, groups)
    available = sorted({record.format.value for record in current or []})
    missing = [name for name in REQUIRED_FORMATS if name not in available]
    if not missing:
        state = DeckExportState.READY
    elif available:
        # A render that failed after registering some formats (or a bot render
        # of fewer formats) is not "ready": say exactly what is missing.
        state = DeckExportState.PARTIAL
    else:
        state = DeckExportState.RENDER_NEEDED
    return DeckAccessView(
        revision_id=target,
        head_revision_id=head.revision_id,
        is_head=target == head.revision_id,
        state=state,
        renderer_version=version,
        required_formats=list(REQUIRED_FORMATS),
        available_formats=available,
        missing_formats=missing,
        current=await _links(storage, current) if current is not None else None,
        fallback=fallback,
    )


async def _fallback(
    store: DocumentStore,
    storage: FileStorage,
    document_id: str,
    target: str,
    same_revision: list[list[ExportRecord]],
) -> FallbackExport | None:
    with_html = [g for g in same_revision if any(r.format is ExportFileFormat.HTML for r in g)]
    if with_html:
        links = await _links(storage, with_html[0])
        return FallbackExport(**links.model_dump(), reason=FallbackReason.OLDER_RENDERER)
    revisions = await store.list_revisions(document_id)
    ids = [record.id for record in revisions]
    older = ids[ids.index(target) + 1 :] if target in ids else []
    order = {revision_id: index for index, revision_id in enumerate(older)}
    candidates = [
        g
        for g in _groups(await store.exports(older))
        if any(r.format is ExportFileFormat.HTML for r in g)
    ]
    if not candidates:
        return None
    newest = min(candidates, key=lambda g: order[g[0].revision_id])
    links = await _links(storage, newest)
    return FallbackExport(**links.model_dump(), reason=FallbackReason.OLDER_REVISION)


async def shared_head_links(
    store: DocumentStore, storage: FileStorage, project_id: str
) -> ExportLinks | None:
    """The head's newest export set with HTML, for a public share link, or None."""

    head = await store.head(project_id, DocumentKind.PRESENTATION)
    if head is None:
        return None
    version = renderer_version()
    groups = [
        g
        for g in _groups(await store.exports([head.revision_id]))
        if any(r.format is ExportFileFormat.HTML for r in g)
    ]
    if not groups:
        return None
    chosen = next((g for g in groups if g[0].renderer_version == version), groups[0])
    return await _links(storage, chosen)


__all__ = [
    "DECK_HTML_TTL_SECONDS",
    "DOWNLOAD_TTL_SECONDS",
    "REQUIRED_FORMATS",
    "DeckAccessView",
    "DeckExportState",
    "DeckNotReadyError",
    "DownloadLink",
    "ExportLinks",
    "FallbackExport",
    "FallbackReason",
    "deck_access",
    "shared_head_links",
]
