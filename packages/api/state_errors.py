"""Persisted state the API cannot use is a 409 with a reason, never a 500 (B1-FIX3).

Request input is validated by the route models (422). This is the other kind of
bad data: a brain_sessions or generation_jobs row that no longer parses (Codex
A3). The read fails cleanly with a machine-readable reason and the row is left
exactly as it is: nothing resets the allowance or drops a delivery receipt to
"repair" it. The structured log that names the row and column is written where
the row failed to parse; this layer adds the request that hit it.
"""

from __future__ import annotations

import json
import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from packages.bot.sessions.session_rows import SessionConflictError, SessionDataInvalidError
from packages.platform.jobs import JobDataInvalidError

logger = logging.getLogger(__name__)


async def _session_invalid(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, SessionDataInvalidError)
    logger.error(
        "api_session_invalid %s",
        json.dumps({"path": request.url.path, "project_id": exc.project_id, "column": exc.column}),
    )
    return JSONResponse(
        status_code=409,
        content={"detail": {"reason": "session_invalid", "column": exc.column}},
    )


async def _job_data_invalid(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, JobDataInvalidError)
    logger.error(
        "api_job_data_invalid %s",
        json.dumps({"path": request.url.path, "job_id": exc.job_id, "fields": exc.detail}),
    )
    return JSONResponse(
        status_code=409,
        content={"detail": {"reason": "job_data_invalid", "job_id": exc.job_id}},
    )


async def _session_conflict(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, SessionConflictError)
    logger.warning(
        "api_session_conflict %s",
        json.dumps({"path": request.url.path, "project_id": exc.project_id, "why": exc.reason}),
    )
    return JSONResponse(
        status_code=409, content={"detail": {"reason": "session_busy", "why": exc.reason}}
    )


def install_state_error_handlers(app: FastAPI) -> None:
    """Map the persisted-state errors to their 409 answers."""

    app.add_exception_handler(SessionDataInvalidError, _session_invalid)
    app.add_exception_handler(JobDataInvalidError, _job_data_invalid)
    app.add_exception_handler(SessionConflictError, _session_conflict)


__all__ = ["install_state_error_handlers"]
