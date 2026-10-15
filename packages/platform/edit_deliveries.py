"""Reads of ``edit_deliveries``: the allowance holds of queued AI edits (B1-FIX3).

Migration 016 writes every row inside the job transactions that decide it:
``finish_generation_job`` creates it (``reserved``, or ``delivered`` when nothing
was left to render), the render's completion delivers it and its final failure
releases it. Application code only reads the rows, and acknowledges a settled
row's notice once a session write has folded it into the chat
(``acknowledge_edit_notices``). The allowance is counted from these rows; it is
never stored on the session.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from enum import StrEnum
from typing import Any, cast

from pydantic import BaseModel, ConfigDict, Field

from packages.platform.database import DatabaseClient


class EditDeliveryStatus(StrEnum):
    """edit_deliveries.status (migration 016)."""

    RESERVED = "reserved"
    DELIVERED = "delivered"
    RELEASED = "released"


class EditDelivery(BaseModel):
    """One edit_deliveries row."""

    model_config = ConfigDict(extra="ignore")

    job_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    session_id: str | None = None
    revision_id: str = Field(min_length=1)
    slides_changed: int = Field(ge=0, le=1000)
    status: EditDeliveryStatus
    notice_acknowledged: bool = False
    created_at: datetime | None = None
    settled_at: datetime | None = None


async def session_deliveries(db: DatabaseClient, session_id: str) -> list[EditDelivery]:
    """Every delivery row owned by the session, oldest first."""

    def run() -> Any:
        return (
            db._query("edit_deliveries")  # pyright: ignore[reportPrivateUsage]
            .select("*")
            .eq("session_id", session_id)
            .order("created_at")
            .execute()
        )

    result = await asyncio.to_thread(run)
    rows = cast(list[dict[str, Any]], list(result.data or []))
    return [EditDelivery.model_validate(row) for row in rows]


async def acknowledge_notices(db: DatabaseClient, session_id: str, job_ids: list[str]) -> int:
    """Mark settled rows' notices as folded into the session; returns how many changed."""

    if not job_ids:
        return 0
    result = await asyncio.to_thread(
        lambda: db.rpc(
            "acknowledge_edit_notices", {"p_session_id": session_id, "p_job_ids": job_ids}
        )
    )
    return int(result.data or 0)


__all__ = ["EditDelivery", "EditDeliveryStatus", "acknowledge_notices", "session_deliveries"]
