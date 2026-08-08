"""Project routes (P3): create, deck viewer URLs, share links, provenance.

Reads ride the owner check (404, never 403 — existence is not leaked); the
web app's project LISTS come straight from Supabase under RLS, so this module
only carries what the anon key cannot do: creation with the service role,
signed R2 URLs, share-token writes, and the brain-session provenance read.
"""

from __future__ import annotations

import logging
import secrets
from enum import StrEnum
from typing import Any, cast

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from packages.api.middleware.auth import Authenticated
from packages.core.enums import Audience, Language, ProjectType
from packages.platform.storage import FileStorage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/projects", tags=["projects"])

# The HTML render URL is deliberately short-lived (15 min): it is re-minted on
# every viewer load, so a leaked URL goes stale fast. Downloads get an hour.
DECK_HTML_TTL_SECONDS = 900
DOWNLOAD_TTL_SECONDS = 3600
_SHARE_TOKEN_BYTES = 24


class CreateProjectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=200)
    project_type: ProjectType = ProjectType.PRESENTATION
    language: Language = Language.UZ
    audience: Audience = Audience.TALABA


class ProjectView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    project_type: str
    status: str


class DownloadLink(BaseModel):
    model_config = ConfigDict(extra="forbid")

    format: str
    url: str
    expires_in: int


class DeckAccessView(BaseModel):
    """Signed URLs for the delivered deck: inline HTML + download formats."""

    model_config = ConfigDict(extra="forbid")

    html_url: str
    html_expires_in: int
    downloads: list[DownloadLink]


class ShareAction(StrEnum):
    ENABLE = "enable"
    ROTATE = "rotate"
    DISABLE = "disable"


class ShareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: ShareAction


class ShareView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    share_token: str | None


class ProvenanceRow(BaseModel):
    """One extracted claim traced back to its uploaded source."""

    model_config = ConfigDict(extra="forbid")

    claim_text: str
    quote: str | None
    strength: str
    source_filename: str | None
    chunk_index: int | None


class ProvenanceView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rows: list[ProvenanceRow]
    total_claims: int


_MAX_PROVENANCE_ROWS = 200


async def _owned_project(request: Request, project_id: str, user_id: str) -> dict[str, Any]:
    project = await request.app.state.db.get_project(project_id)
    if project is None or str(project.get("user_id")) != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="project_not_found")
    return cast(dict[str, Any], project)


@router.post("", response_model=ProjectView)
async def create_project(
    request: Request, body: CreateProjectRequest, auth: Authenticated
) -> ProjectView:
    """Create a project owned by the caller."""

    row = await request.app.state.db.create_project(
        user_id=str(auth.user_id),
        title=body.title,
        project_type=body.project_type.value,
        language=body.language.value,
        audience=body.audience.value,
    )
    return ProjectView(
        id=str(row.get("id")),
        title=str(row.get("title")),
        project_type=str(row.get("type")),
        status=str(row.get("status")),
    )


@router.get("/{project_id}/deck", response_model=DeckAccessView)
async def get_deck_access(request: Request, project_id: str, auth: Authenticated) -> DeckAccessView:
    """Short-TTL signed URL for the rendered HTML plus download links."""

    await _owned_project(request, project_id, str(auth.user_id))
    storage: FileStorage = request.app.state.storage

    files = await request.app.state.db.get_project_files(project_id)
    by_type = {str(row.get("file_type")): str(row.get("storage_path")) for row in files}
    html_key = by_type.get("html")
    if html_key is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="deck_not_ready")

    html_url = await storage.signed_url(html_key, expires_in=DECK_HTML_TTL_SECONDS)
    downloads: list[DownloadLink] = []
    for fmt in ("pptx", "pdf"):
        key = by_type.get(fmt)
        if key is not None:
            downloads.append(
                DownloadLink(
                    format=fmt,
                    url=await storage.signed_url(key, expires_in=DOWNLOAD_TTL_SECONDS),
                    expires_in=DOWNLOAD_TTL_SECONDS,
                )
            )
    return DeckAccessView(
        html_url=html_url,
        html_expires_in=DECK_HTML_TTL_SECONDS,
        downloads=downloads,
    )


@router.post("/{project_id}/share", response_model=ShareView)
async def manage_share(
    request: Request, project_id: str, body: ShareRequest, auth: Authenticated
) -> ShareView:
    """Enable, rotate, or disable the project's public share link.

    Rotation IS revocation: the old token stops resolving as soon as the new
    one is written. ``enable`` on an already-shared project keeps the current
    token so a double-click does not silently kill circulating links.
    """

    project = await _owned_project(request, project_id, str(auth.user_id))
    current = project.get("share_token")

    if body.action is ShareAction.DISABLE:
        await request.app.state.db.set_project_share_token(project_id, None)
        return ShareView(share_token=None)
    if body.action is ShareAction.ENABLE and isinstance(current, str) and current:
        return ShareView(share_token=current)

    token = secrets.token_urlsafe(_SHARE_TOKEN_BYTES)
    await request.app.state.db.set_project_share_token(project_id, token)
    logger.info("share_token_set project=%s action=%s", project_id, body.action.value)
    return ShareView(share_token=token)


@router.get("/{project_id}/provenance", response_model=ProvenanceView)
async def get_provenance(request: Request, project_id: str, auth: Authenticated) -> ProvenanceView:
    """Owner-only evidence table: extracted claims traced to source files.

    Reads the brain session's stored sources JSON. Claims stamped with
    ``{source_id}:{chunk_index}`` resolve to a filename + chunk; bot-era rows
    predate the stamping and render with the claim text alone.
    """

    await _owned_project(request, project_id, str(auth.user_id))

    sources_json = await request.app.state.db.get_brain_session_sources(project_id)
    if sources_json is None:
        return ProvenanceView(rows=[], total_claims=0)

    filenames = {
        str(row.get("id")): str(row.get("filename"))
        for row in await request.app.state.db.get_project_sources(project_id)
    }

    claims_raw = sources_json.get("claims")
    claims = cast(list[Any], claims_raw) if isinstance(claims_raw, list) else []
    rows: list[ProvenanceRow] = []
    for entry in claims[:_MAX_PROVENANCE_ROWS]:
        if not isinstance(entry, dict):
            continue
        claim = cast(dict[str, Any], entry)
        source_filename, chunk_index = _parse_chunk_ref(
            str(claim.get("source_chunk_id") or ""), filenames
        )
        rows.append(
            ProvenanceRow(
                claim_text=str(claim.get("claim_text") or ""),
                quote=cast("str | None", claim.get("quote")),
                strength=str(claim.get("strength") or ""),
                source_filename=source_filename,
                chunk_index=chunk_index,
            )
        )
    return ProvenanceView(rows=rows, total_claims=len(claims))


def _parse_chunk_ref(ref: str, filenames: dict[str, str]) -> tuple[str | None, int | None]:
    """Split a ``{source_id}:{chunk_index}`` (or bare-index) claim ref."""

    if not ref:
        return None, None
    source_part, _, index_part = ref.partition(":")
    if not index_part:
        # Bare chunk index — stamped by the extractor but never bound to a
        # persisted source (bot path).
        return None, int(source_part) if source_part.isdigit() else None
    filename = filenames.get(source_part)
    return filename, int(index_part) if index_part.isdigit() else None
