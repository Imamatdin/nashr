"""Source upload routes (P3 item 1): presigned R2 PUT + row registration.

The P2-gate-proven gap: bot-era sources carry dead local paths, and the web
had no upload path at all. The browser flow is::

    POST /sources/presign  -> short-lived presigned PUT URL (rate-limited)
    PUT  <r2 url>          -> browser uploads directly to R2
    POST /sources          -> registers the sources row against the project

Enforcement split: extension/content-type allowlist and the declared size are
checked at presign time; the ACTUAL uploaded size is re-checked at register
time via a HEAD on the object (a presigned PUT cannot cap payload bytes).
Deep content validation (Magika) stays where it always ran — in the source
pipeline when the job executes.
"""

from __future__ import annotations

import logging
import uuid
from typing import Final

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from packages.api.middleware.auth import Authenticated
from packages.core.constants import MAX_FILE_SIZE_BYTES, MAX_FILES_PER_PROJECT
from packages.platform.rate_limit import UPLOAD_ACTION, RateLimiter
from packages.platform.storage import FileStorage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sources", tags=["sources"])

PRESIGN_TTL_SECONDS: Final[int] = 900

# Upload allowlist: extension -> (sources.file_type CHECK value, content type).
# Mirrors the bot's accepted set restricted to what migration 001's CHECK
# accepts; Magika re-validates actual bytes when the job runs.
_EXTENSION_ALLOWLIST: Final[dict[str, tuple[str, str]]] = {
    "pdf": ("pdf", "application/pdf"),
    "docx": (
        "docx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ),
    "pptx": (
        "pptx",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ),
    "xlsx": (
        "xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ),
    "png": ("png", "image/png"),
    "jpg": ("jpeg", "image/jpeg"),
    "jpeg": ("jpeg", "image/jpeg"),
    "webp": ("webp", "image/webp"),
    "gif": ("gif", "image/gif"),
    "txt": ("txt", "text/plain"),
    "md": ("markdown", "text/markdown"),
    "markdown": ("markdown", "text/markdown"),
    "csv": ("csv", "text/csv"),
}


class PresignRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    project_id: str = Field(min_length=1, max_length=64)
    filename: str = Field(min_length=1, max_length=255)
    size_bytes: int = Field(ge=1, le=MAX_FILE_SIZE_BYTES)


class PresignResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    storage_key: str
    upload_url: str
    content_type: str
    expires_in: int


class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    project_id: str = Field(min_length=1, max_length=64)
    storage_key: str = Field(min_length=1, max_length=512)
    filename: str = Field(min_length=1, max_length=255)


class SourceView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    project_id: str
    filename: str
    file_type: str
    file_size_bytes: int
    storage_key: str


def _client_ip(request: Request) -> str:
    """Last X-Forwarded-For entry (Caddy appends the peer; see jobs route)."""

    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"


def _file_type_for(filename: str) -> tuple[str, str]:
    """Map a filename to (sources.file_type, content type) or raise 422."""

    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    entry = _EXTENSION_ALLOWLIST.get(extension)
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"reason": "file_type_not_allowed", "extension": extension},
        )
    return entry


async def _owned_project(request: Request, project_id: str, user_id: str) -> dict[str, object]:
    """The caller's project row; 404 hides other users' projects."""

    project = await request.app.state.db.get_project(project_id)
    if project is None or str(project.get("user_id")) != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="project_not_found")
    return project  # type: ignore[no-any-return]


@router.post("/presign", response_model=PresignResponse)
async def presign_upload(
    request: Request, body: PresignRequest, auth: Authenticated
) -> PresignResponse:
    """Issue a short-lived presigned R2 PUT URL for one source file."""

    limiter: RateLimiter = request.app.state.rate_limiter
    storage: FileStorage = request.app.state.storage
    user_id = str(auth.user_id)

    decision = await limiter.check(action=UPLOAD_ACTION, user_id=user_id, ip=_client_ip(request))
    if not decision.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "reason": "rate_limited",
                "scope": decision.scope,
                "count": decision.count,
                "limit": decision.limit,
                "resets_at": decision.resets_at.isoformat(),
            },
        )

    await _owned_project(request, body.project_id, user_id)
    _file_type, content_type = _file_type_for(body.filename)

    storage_key = FileStorage.upload_source_key(user_id, uuid.uuid4().hex, body.filename)
    upload_url = await storage.presigned_put_url(
        storage_key, content_type, expires_in=PRESIGN_TTL_SECONDS
    )
    return PresignResponse(
        storage_key=storage_key,
        upload_url=upload_url,
        content_type=content_type,
        expires_in=PRESIGN_TTL_SECONDS,
    )


@router.post("", response_model=SourceView)
async def register_source(
    request: Request, body: RegisterRequest, auth: Authenticated
) -> SourceView:
    """Register an uploaded object as one of the project's sources."""

    storage: FileStorage = request.app.state.storage
    user_id = str(auth.user_id)

    await _owned_project(request, body.project_id, user_id)

    # A caller may only register keys minted for it: the presign route embeds
    # the caller's user id in the key prefix.
    if not body.storage_key.startswith(f"uploads/{user_id}/"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="storage_key_not_yours",
        )

    existing = await request.app.state.db.get_project_sources(body.project_id)
    if len(existing) >= MAX_FILES_PER_PROJECT:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"reason": "too_many_sources", "limit": MAX_FILES_PER_PROJECT},
        )
    if any(str(row.get("storage_key")) == body.storage_key for row in existing):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="source_already_registered",
        )

    file_type, _content_type = _file_type_for(body.filename)

    # The presigned PUT could not cap payload bytes; the object's REAL size is
    # the enforcement point (and proves the upload actually happened).
    actual_size = await storage.object_size(body.storage_key)
    if actual_size is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="object_not_uploaded",
        )
    if actual_size < 1 or actual_size > MAX_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"reason": "file_too_large", "size_bytes": actual_size},
        )

    row = await request.app.state.db.create_source(
        project_id=body.project_id,
        filename=body.filename,
        file_type=file_type,
        file_size=actual_size,
        storage_path=body.storage_key,
    )
    logger.info(
        "source_registered project=%s source=%s user=%s size=%d",
        body.project_id,
        row.get("id"),
        user_id,
        actual_size,
    )
    return SourceView(
        id=str(row.get("id")),
        project_id=body.project_id,
        filename=body.filename,
        file_type=file_type,
        file_size_bytes=actual_size,
        storage_key=body.storage_key,
    )
