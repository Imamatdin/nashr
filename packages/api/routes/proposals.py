"""Review, accept and reject stored proposals (ADR 0001).

A proposal is an AI, regeneration or import write that lost the race to the head.
Accepting is replace-head-with-consent, not a rebase: the client first reads the
diff, which names the head it was computed against, and must send that head back
on accept. If the head moved in between, accept answers 409 and the client
refreshes the diff, so a user never approves changes they were not shown.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from packages.api.middleware.auth import Authenticated
from packages.api.routes.projects import owned_project
from packages.api.services.revisions import document_store, raise_store_error, stale_revision
from packages.core.enums import DiffUnit
from packages.core.revision_diff import RevisionDiff, diff_revisions
from packages.platform.document_models import (
    CommitStatus,
    DocumentKind,
    DocumentStoreError,
    ProposalRecord,
    ProposalStatus,
    RevisionKind,
    user_actor,
)

router = APIRouter(prefix="/projects", tags=["proposals"])


class ProposalView(BaseModel):
    """A proposal without its content."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    kind: RevisionKind
    status: ProposalStatus
    base_revision_id: UUID | None
    created_at: datetime

    @classmethod
    def of(cls, record: ProposalRecord) -> ProposalView:
        """Project a stored proposal onto the wire shape."""

        return cls(
            id=UUID(record.id),
            kind=record.kind,
            status=record.status,
            base_revision_id=UUID(record.base_revision_id) if record.base_revision_id else None,
            created_at=record.created_at,
        )


class ProposalListView(BaseModel):
    """Pending proposals, newest first, and the head they compete with."""

    model_config = ConfigDict(extra="forbid")

    head_revision_id: UUID | None
    proposals: list[ProposalView]


class ProposalDiffView(BaseModel):
    """What the AI changed, and what accepting would change right now."""

    model_config = ConfigDict(extra="forbid")

    proposal: ProposalView
    head_revision_id: UUID | None
    ai_changes: RevisionDiff
    accept_changes: RevisionDiff
    schema_matches_head: bool


class AcceptProposalRequest(BaseModel):
    """Consent to replace exactly the head the user was shown."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    expected_head_revision_id: UUID | None
    idempotency_key: str = Field(min_length=1, max_length=128)


class AcceptProposalView(BaseModel):
    """The new head after a successful accept."""

    model_config = ConfigDict(extra="forbid")

    status: CommitStatus
    revision_id: UUID | None
    head_revision_id: UUID | None


def _kind_for(project: dict[str, Any], requested: DocumentKind | None) -> DocumentKind:
    project_type = str(project.get("type"))
    if project_type in ("presentation", "article"):
        kind = DocumentKind(project_type)
        if requested is not None and requested is not kind:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="document_kind_mismatch"
            )
        return kind
    if requested is None:
        raise HTTPException(status_code=422, detail="document_kind_required")
    return requested


async def _document_id(request: Request, project_id: str, kind: DocumentKind) -> str:
    document_id = await document_store(request).document_id(project_id, kind)
    if document_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="document_not_found")
    return document_id


async def _proposal(request: Request, document_id: str, proposal_id: UUID) -> ProposalRecord:
    record = await document_store(request).proposal(document_id, str(proposal_id))
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="proposal_not_found")
    return record


@router.get("/{project_id}/proposals", response_model=ProposalListView)
async def list_proposals(
    request: Request, project_id: str, auth: Authenticated, kind: DocumentKind | None = None
) -> ProposalListView:
    """Pending proposals for the project's document."""

    project = await owned_project(request, project_id, str(auth.user_id))
    document_kind = _kind_for(project, kind)
    store = document_store(request)
    head = await store.head(project_id, document_kind)
    document_id = await _document_id(request, project_id, document_kind)
    records = await store.list_proposals(document_id)
    return ProposalListView(
        head_revision_id=UUID(head.revision_id) if head is not None else None,
        proposals=[ProposalView.of(record) for record in records],
    )


@router.get("/{project_id}/proposals/{proposal_id}/diff", response_model=ProposalDiffView)
async def proposal_diff(
    request: Request,
    project_id: str,
    proposal_id: UUID,
    auth: Authenticated,
    kind: DocumentKind | None = None,
) -> ProposalDiffView:
    """Base → proposal and head → proposal diffs, computed against the current head."""

    project = await owned_project(request, project_id, str(auth.user_id))
    document_kind = _kind_for(project, kind)
    document_id = await _document_id(request, project_id, document_kind)
    store = document_store(request)
    record = await _proposal(request, document_id, proposal_id)
    head = await store.head(project_id, document_kind)
    base_content: dict[str, Any] | None = None
    if record.base_revision_id is not None:
        base = await store.revision(document_id, record.base_revision_id)
        base_content = base.content if base is not None else None
    unit = DiffUnit.SLIDE if document_kind is DocumentKind.PRESENTATION else DiffUnit.BLOCK
    proposed = record.content or {}
    return ProposalDiffView(
        proposal=ProposalView.of(record),
        head_revision_id=UUID(head.revision_id) if head is not None else None,
        ai_changes=diff_revisions(unit, base_content, proposed),
        accept_changes=diff_revisions(unit, head.content if head is not None else None, proposed),
        schema_matches_head=head is None or head.revision.schema_version == record.schema_version,
    )


@router.post("/{project_id}/proposals/{proposal_id}/accept", response_model=AcceptProposalView)
async def accept_proposal(
    request: Request,
    project_id: str,
    proposal_id: UUID,
    body: AcceptProposalRequest,
    auth: Authenticated,
    kind: DocumentKind | None = None,
) -> AcceptProposalView:
    """Replace the head the user saw with the proposal; 409 if the head moved since."""

    user_id = str(auth.user_id)
    project = await owned_project(request, project_id, user_id)
    document_id = await _document_id(request, project_id, _kind_for(project, kind))
    await _proposal(request, document_id, proposal_id)
    expected = str(body.expected_head_revision_id) if body.expected_head_revision_id else None
    try:
        outcome = await document_store(request).accept_proposal(
            str(proposal_id), expected, user_actor(user_id), body.idempotency_key
        )
    except DocumentStoreError as exc:
        raise_store_error(exc)
    if outcome.status is CommitStatus.CONFLICT:
        raise stale_revision(outcome.head_revision_id)
    return AcceptProposalView(
        status=outcome.status,
        revision_id=UUID(outcome.revision_id) if outcome.revision_id else None,
        head_revision_id=UUID(outcome.head_revision_id) if outcome.head_revision_id else None,
    )


@router.post("/{project_id}/proposals/{proposal_id}/reject", response_model=ProposalView)
async def reject_proposal(
    request: Request,
    project_id: str,
    proposal_id: UUID,
    auth: Authenticated,
    kind: DocumentKind | None = None,
) -> ProposalView:
    """Dismiss a pending proposal (idempotent); its content stays in history."""

    user_id = str(auth.user_id)
    project = await owned_project(request, project_id, user_id)
    document_id = await _document_id(request, project_id, _kind_for(project, kind))
    await _proposal(request, document_id, proposal_id)
    try:
        await document_store(request).reject_proposal(str(proposal_id), user_actor(user_id))
    except DocumentStoreError as exc:
        raise_store_error(exc)
    return ProposalView.of(await _proposal(request, document_id, proposal_id))
