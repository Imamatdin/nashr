"""Public (unauthenticated) share-link resolution (P3 item 5).

``GET /public/decks/{share_token}`` is the ONLY unauthenticated read surface.
The token is the whole capability: resolution is a single indexed equality
probe, rate-limited per IP against enumeration, and the response carries a
short-TTL signed R2 URL — the raw project id never appears in any public
route or link (the id embedded inside the signed R2 object key is inert;
every API surface that accepts a project id requires owner auth).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from packages.platform.rate_limit import SHARE_VIEW_ACTION, RateLimiter
from packages.platform.storage import FileStorage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/public", tags=["public"])

SHARED_HTML_TTL_SECONDS = 900
SHARED_DOWNLOAD_TTL_SECONDS = 3600


class SharedDownload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    format: str
    url: str
    expires_in: int


class SharedDeckView(BaseModel):
    """What a share-link recipient gets.

    ``expires_in`` is the SIGNED-URL lifetime in seconds, not the link's — the
    token itself does not expire until the owner rotates or disables it. The
    two were conflated in the viewer's copy (G19); naming them separately is
    what lets the web stop guessing.
    """

    model_config = ConfigDict(extra="forbid")

    title: str
    html_url: str
    expires_in: int
    downloads: list[SharedDownload] = Field(default_factory=list[SharedDownload])


def _client_ip(request: Request) -> str:
    """Last X-Forwarded-For entry (Caddy appends the peer; see jobs route)."""

    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"


@router.get("/decks/{share_token}", response_model=SharedDeckView)
async def resolve_shared_deck(request: Request, share_token: str) -> SharedDeckView:
    """Resolve a share token to a signed URL for the deck's HTML render."""

    limiter: RateLimiter = request.app.state.rate_limiter
    storage: FileStorage = request.app.state.storage

    decision = await limiter.check_ip(action=SHARE_VIEW_ACTION, ip=_client_ip(request))
    if not decision.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "reason": "rate_limited",
                "count": decision.count,
                "limit": decision.limit,
                "resets_at": decision.resets_at.isoformat(),
            },
        )

    if not 16 <= len(share_token) <= 64:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")

    project = await request.app.state.db.get_project_by_share_token(share_token)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")

    project_id = str(project.get("id"))
    files = await request.app.state.db.get_project_files(project_id)
    html_key = next(
        (str(row.get("storage_path")) for row in files if str(row.get("file_type")) == "html"),
        None,
    )
    if html_key is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")

    html_url = await storage.signed_url(html_key, expires_in=SHARED_HTML_TTL_SECONDS)

    # Recipients can TAKE the deck, not just look at it. The token is already
    # the whole capability — anyone holding it can open the HTML — so handing
    # over the same deck's PPTX/PDF grants nothing new; withholding them only
    # made the share view useless to the students it was built for (G19).
    by_type = {str(row.get("file_type")): str(row.get("storage_path")) for row in files}
    downloads: list[SharedDownload] = []
    for fmt in ("pptx", "pdf"):
        key = by_type.get(fmt)
        if key is None:
            continue
        downloads.append(
            SharedDownload(
                format=fmt,
                url=await storage.signed_url(key, expires_in=SHARED_DOWNLOAD_TTL_SECONDS),
                expires_in=SHARED_DOWNLOAD_TTL_SECONDS,
            )
        )

    logger.info("share_view project=%s", project_id)
    return SharedDeckView(
        title=str(project.get("title") or ""),
        html_url=html_url,
        expires_in=SHARED_HTML_TTL_SECONDS,
        downloads=downloads,
    )
