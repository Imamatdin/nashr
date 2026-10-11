"""Commit a deck as a revision, then render and publish exactly that revision (ADR 0001).

Shared by the queue worker and the Telegram bot so both follow one write path:
the deck becomes a revision through ``commit_revision`` (or a proposal when the
head moved), and only a committed revision is rendered, uploaded, verified and
registered under the caller's job claim.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from packages.bot.orchestrators.article_orchestrator import _OrchestratorError
from packages.bot.orchestrators.presentation_orchestrator import (
    PresentationOrchestrator,
    PresentationRenderResult,
    ProgressCallback,
)
from packages.core.enums import ExportFormat
from packages.core.models.presentation import DeckSpec
from packages.platform.document_models import (
    CommitOutcome,
    CommitStatus,
    DocumentKind,
    RevisionKind,
)
from packages.platform.document_store import DocumentStore
from packages.platform.exports import ExportPublisher, PublishedExport, file_format


class PublishedRender(BaseModel):
    """The rendered local files and the exports registered for them."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    render: PresentationRenderResult
    exports: list[PublishedExport]


_RENDER_FORMAT: dict[str, ExportFormat] = {
    "html": ExportFormat.HTML,
    "pptx": ExportFormat.PPTX_EDITABLE,
    "pdf": ExportFormat.PDF,
}


def file_formats(formats: list[ExportFormat]) -> list[str]:
    """The sorted, de-duplicated file formats a render request produces."""

    return sorted({"pptx" if fmt.value.startswith("pptx") else fmt.value for fmt in formats})


def render_formats(names: list[str]) -> list[ExportFormat]:
    """Renderer formats for stored file-format names (``html``, ``pptx``, ``pdf``)."""

    return [_RENDER_FORMAT[name] for name in sorted(set(names))]


def renderable(outcome: CommitOutcome) -> str | None:
    """The revision to render after a commit, or None when nothing new was committed."""

    if outcome.status in (CommitStatus.COMMITTED, CommitStatus.DUPLICATE):
        return outcome.revision_id
    return None


async def commit_generated_deck(
    store: DocumentStore,
    *,
    project_id: str,
    deck: DeckSpec,
    actor: str,
    base_revision_id: str | None,
    idempotency_key: str,
) -> CommitOutcome:
    """Commit a freshly generated deck; never drop it.

    ``base_revision_id`` is the head observed when generation started: None makes
    this a first ``generation``, anything else a ``regeneration``. If a head
    appeared while a first generation ran, the commit conflicts; the deck is then
    re-submitted as a ``regeneration`` against no base, which stores it as a
    proposal for the owner instead of losing paid output.
    """

    document_id = await store.ensure_document(project_id, DocumentKind.PRESENTATION, actor)
    content = deck.model_dump(mode="json")
    kind = RevisionKind.GENERATION if base_revision_id is None else RevisionKind.REGENERATION
    outcome = await store.commit(
        document_id,
        base_revision_id,
        content,
        kind=kind,
        actor=actor,
        idempotency_key=idempotency_key,
    )
    if outcome.status is CommitStatus.CONFLICT and kind is RevisionKind.GENERATION:
        outcome = await store.commit(
            document_id,
            None,
            content,
            kind=RevisionKind.REGENERATION,
            actor=actor,
            idempotency_key=f"{idempotency_key}:proposal",
        )
    return outcome


async def render_and_publish(
    *,
    orchestrator: PresentationOrchestrator,
    publisher: ExportPublisher,
    job_id: str,
    worker_id: str,
    document_id: str,
    revision_id: str,
    deck: DeckSpec,
    formats: list[ExportFormat],
    progress: ProgressCallback,
) -> PublishedRender:
    """Render every format of one committed revision and publish all of them, or raise.

    A publishing failure (upload, verification, lost claim, revision mismatch) is
    raised as step ``publish`` so the job fails honestly; its ``original`` keeps
    the precise cause.
    """

    render = await orchestrator.render(deck, formats, progress)
    files = {file_format(ext): path for ext, path in render.by_extension().items()}
    try:
        exports = await publisher.publish(
            job_id=job_id,
            worker_id=worker_id,
            document_id=document_id,
            revision_id=revision_id,
            files=files,
        )
    except Exception as exc:
        raise _OrchestratorError("publish", exc) from exc
    return PublishedRender(render=render, exports=exports)


__all__ = [
    "PublishedRender",
    "commit_generated_deck",
    "file_formats",
    "render_and_publish",
    "render_formats",
    "renderable",
]
