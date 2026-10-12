"""In-memory emulation of the migration-016 document functions for unit tests.

Unit tests run without PostgreSQL, but the code under test calls
``commit_revision`` / ``ensure_document`` / ``register_export`` through
``DatabaseClient.rpc``. This emulator gives those calls the same outcomes and
error codes as the SQL (privileged-caller path only), against the fake client's
tables. It is a test double for the database; the real functions are exercised
on PostgreSQL by ``tests/db`` in CI.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import re
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast

from postgrest.exceptions import APIError

_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
_KINDS = {
    "generation",
    "regeneration",
    "manual",
    "autosave",
    "ai_edit",
    "bot_edit",
    "import",
    "restore",
}
_PROPOSING = {"ai_edit", "regeneration", "import"}
_EPOCH = datetime(2026, 1, 1, tzinfo=UTC)
# One clock for every emulator in the process, so rows seeded by one emulator and
# rows written later by another still order correctly by created_at.
_TICKS = itertools.count(1)


def refuse(code: str) -> APIError:
    """The PostgREST error a refused function call raises (message carries the code)."""

    return APIError({"message": code, "code": "P0001", "hint": None, "details": None})


def content_hash(content: dict[str, Any]) -> str:
    """Stable digest of a JSON object (stands in for sha256(jsonb::text))."""

    canonical = json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class DocumentRpcEmulator:
    """Implements ensure_document, commit_revision, accept/reject_proposal, register_export."""

    def __init__(self, tables: dict[str, list[dict[str, Any]]]) -> None:
        self._tables = tables

    # ----------------------------------------------------------------- helpers

    def _rows(self, name: str) -> list[dict[str, Any]]:
        return self._tables.setdefault(name, [])

    def _now(self) -> str:
        return (_EPOCH + timedelta(microseconds=next(_TICKS))).isoformat()

    def _one(self, name: str, **match: Any) -> dict[str, Any] | None:
        return next(
            (row for row in self._rows(name) if all(row.get(k) == v for k, v in match.items())),
            None,
        )

    def _owner(self, project_id: str, actor: str | None, kind: str) -> str:
        project = self._one("projects", id=project_id)
        if project is None:
            raise refuse("document_not_found")
        owner = str(project["user_id"])
        if actor is None:
            raise refuse("invalid_actor")
        if re.fullmatch(_UUID, actor):
            if actor != owner:
                raise refuse("not_document_owner")
            allowed = {"manual", "autosave", "restore"}
        elif re.fullmatch(f"worker:{_UUID}", actor):
            raise refuse("worker_must_finish_job")
        elif re.fullmatch(r"bot:[0-9]{1,20}", actor):
            user = self._one("users", telegram_id=int(actor[4:]))
            if user is None or str(user["id"]) != owner:
                raise refuse("not_document_owner")
            allowed = {"bot_edit", "generation", "regeneration"}
        elif re.fullmatch(r"system:[a-z0-9_.:-]{1,64}", actor):
            allowed = {"import"}
        else:
            raise refuse("invalid_actor")
        if kind not in allowed:
            raise refuse("kind_not_allowed")
        return owner

    def _result(
        self,
        status: str,
        document_id: str,
        revision_id: str | None,
        head: str | None,
        proposal_id: str | None,
    ) -> list[dict[str, Any]]:
        return [
            {
                "status": status,
                "document_id": document_id,
                "revision_id": revision_id,
                "head_revision_id": head,
                "proposal_id": proposal_id,
            }
        ]

    def _insert_revision(self, document: dict[str, Any], values: dict[str, Any]) -> str:
        revision_id = str(uuid.uuid4())
        self._rows("document_revisions").append(
            {
                "id": revision_id,
                "document_id": document["id"],
                "parent_revision_id": document.get("head_revision_id"),
                "created_at": self._now(),
                "accepted_from_proposal_id": None,
                **values,
            }
        )
        document["head_revision_id"] = revision_id
        document["updated_at"] = self._now()
        return revision_id

    # --------------------------------------------------------------- functions

    def ensure_document(self, params: dict[str, Any]) -> str:
        """Create the project's document of a kind if missing; return its id."""

        actor = str(params["p_actor"])
        probe = (
            "generation"
            if actor.startswith(("worker:", "bot:"))
            else "import"
            if actor.startswith("system:")
            else "manual"
        )
        self._owner(str(params["p_project_id"]), actor, probe)
        existing = self._one("documents", project_id=params["p_project_id"], kind=params["p_kind"])
        if existing is not None:
            return str(existing["id"])
        document_id = str(uuid.uuid4())
        now = self._now()
        self._rows("documents").append(
            {
                "id": document_id,
                "project_id": params["p_project_id"],
                "kind": params["p_kind"],
                "schema_version": 1,
                "head_revision_id": None,
                "created_at": now,
                "updated_at": now,
            }
        )
        return document_id

    def commit_revision(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        """Compare-and-swap commit with idempotency, no-op and proposal semantics."""

        document = self._one("documents", id=params["p_document_id"])
        if document is None:
            raise refuse("document_not_found")
        kind = str(params["p_kind"])
        if kind not in _KINDS:
            raise refuse("invalid_revision_kind")
        actor = str(params["p_actor"])
        owner = self._owner(str(document["project_id"]), actor, kind)
        return self._commit_core(document, params, kind, actor, owner, None)

    def _commit_core(
        self,
        document: dict[str, Any],
        params: dict[str, Any],
        kind: str,
        actor: str,
        owner: str,
        source_job: str | None,
    ) -> list[dict[str, Any]]:
        if params["p_schema_version"] != 1:
            raise refuse("unsupported_schema_version")
        raw = params["p_content"]
        if not isinstance(raw, dict):
            raise refuse("invalid_content")
        content = cast(dict[str, Any], raw)
        digest = content_hash(content)
        key = params["p_idempotency_key"]
        head = document.get("head_revision_id")

        prior = self._one("document_revisions", document_id=document["id"], idempotency_key=key)
        if prior is not None:
            if prior["content_sha256"] != digest:
                raise refuse("idempotency_key_reused")
            return self._result("duplicate", document["id"], prior["id"], head, None)
        proposal = self._one("revision_proposals", document_id=document["id"], idempotency_key=key)
        if proposal is not None:
            if proposal["content_sha256"] != digest:
                raise refuse("idempotency_key_reused")
            return self._result("proposed", document["id"], None, head, proposal["id"])

        head_row = self._one("document_revisions", id=head) if head else None
        if head_row is not None and head_row["content_sha256"] == digest:
            return self._result("unchanged", document["id"], head, head, None)

        if params["p_base_revision_id"] == head:
            revision_id = self._insert_revision(
                document,
                {
                    "created_by": owner,
                    "idempotency_key": key,
                    "content": content,
                    "content_sha256": digest,
                    "kind": kind,
                    "schema_version": 1,
                    "actor": actor,
                },
            )
            return self._result("committed", document["id"], revision_id, revision_id, None)

        if kind in _PROPOSING:
            proposal_id = str(uuid.uuid4())
            self._rows("revision_proposals").append(
                {
                    "id": proposal_id,
                    "document_id": document["id"],
                    "base_revision_id": params["p_base_revision_id"],
                    "content": content,
                    "content_sha256": digest,
                    "schema_version": 1,
                    "kind": kind,
                    "actor": actor,
                    "source_job_id": source_job,
                    "idempotency_key": key,
                    "status": "pending",
                    "created_at": self._now(),
                    "resolved_at": None,
                    "resolved_by": None,
                    "accepted_revision_id": None,
                }
            )
            return self._result("proposed", document["id"], None, head, proposal_id)
        return self._result("conflict", document["id"], None, head, None)

    # ------------------------------------------------------------- job claims

    def _claimed_job(self, params: dict[str, Any], *, fresh: bool) -> dict[str, Any]:
        """The job, if the caller holds its live claim; SQL NULL never matches."""

        job = self._one("generation_jobs", id=params["p_job_id"])
        worker = params.get("p_worker_id")
        token = params.get("p_claim_token")
        if (
            job is None
            or job.get("status") != "processing"
            or worker is None
            or job.get("worker_id") is None
            or job["worker_id"] != worker
            or token is None
            or int(job.get("attempts") or 0) != token
        ):
            raise refuse("claim_lost")
        if fresh and job.get("heartbeat_at") is None:
            raise refuse("claim_expired")
        return job

    def claim_job(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        """Claim one queued job, incrementing its claim token."""

        job = self._one("generation_jobs", id=params["p_job_id"])
        if job is None or job.get("status") != "queued" or params.get("p_worker_id") is None:
            return []
        now = self._now()
        job.update(
            status="processing",
            worker_id=params["p_worker_id"],
            claimed_at=now,
            heartbeat_at=now,
            started_at=job.get("started_at") or now,
            attempts=int(job.get("attempts") or 0) + 1,
        )
        return [dict(job)]

    def heartbeat_job(self, params: dict[str, Any]) -> bool:
        """Bump the heartbeat of a job the caller still holds."""

        try:
            job = self._claimed_job(params, fresh=False)
        except APIError:
            return False
        job["heartbeat_at"] = self._now()
        return True

    def complete_job(self, params: dict[str, Any]) -> bool:
        """Complete a job that commits nothing; False when the claim is gone."""

        try:
            job = self._claimed_job(params, fresh=False)
        except APIError:
            return False
        if job["job_type"] in ("presentation_generation", "presentation_edit"):
            raise refuse("job_must_finish_with_revision")
        job.update(
            status="completed",
            completed_at=self._now(),
            progress={**(job.get("progress") or {}), **(params.get("p_progress") or {})},
        )
        return True

    def finish_generation_job(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        """Fenced commit + completion + render enqueue, as one step."""

        job = self._one("generation_jobs", id=params["p_job_id"])
        key = str(params["p_idempotency_key"])
        if (
            job is not None
            and job.get("status") == "completed"
            and job.get("worker_id") == params.get("p_worker_id")
            and int(job.get("attempts") or 0) == params.get("p_claim_token")
        ):
            document = self._one("documents", project_id=job["project_id"], kind="presentation")
            if document is not None:
                prior = self._one(
                    "document_revisions", document_id=document["id"], idempotency_key=key
                )
                if prior is not None:
                    head = document.get("head_revision_id")
                    return self._result("duplicate", document["id"], prior["id"], head, None)
                for candidate in (key, f"{key}:proposal"):
                    proposal = self._one(
                        "revision_proposals", document_id=document["id"], idempotency_key=candidate
                    )
                    if proposal is not None:
                        head = document.get("head_revision_id")
                        return self._result("proposed", document["id"], None, head, proposal["id"])
        job = self._claimed_job(params, fresh=True)
        kind = str(params["p_kind"])
        allowed = {
            "presentation_generation": {"generation", "regeneration"},
            "presentation_edit": {"ai_edit"},
        }.get(str(job["job_type"]), set())
        if kind not in allowed:
            raise refuse("kind_not_allowed")
        project = self._one("projects", id=job["project_id"])
        if project is None:
            raise refuse("document_not_found")
        owner = str(project["user_id"])
        if job.get("user_id") is None or str(job["user_id"]) != owner:
            raise refuse("not_document_owner")
        document = self._one("documents", project_id=job["project_id"], kind="presentation")
        if document is None:
            now = self._now()
            document = {
                "id": str(uuid.uuid4()),
                "project_id": job["project_id"],
                "kind": "presentation",
                "schema_version": 1,
                "head_revision_id": None,
                "created_at": now,
                "updated_at": now,
            }
            self._rows("documents").append(document)
        document_id = str(document["id"])
        actor = f"worker:{job['id']}"
        result = self._commit_core(document, params, kind, actor, owner, str(job["id"]))
        if result[0]["status"] == "conflict" and kind == "generation":
            retry = {**params, "p_base_revision_id": None, "p_idempotency_key": f"{key}:proposal"}
            result = self._commit_core(
                document, retry, "regeneration", actor, owner, str(job["id"])
            )
        outcome = result[0]
        job.update(
            status="completed",
            completed_at=self._now(),
            progress={
                **(job.get("progress") or {}),
                "step": "done",
                "outcome": outcome["status"],
                "revision_id": outcome["revision_id"],
                "proposal_id": outcome["proposal_id"],
            },
        )
        formats = sorted(set(params.get("p_render_formats") or []))
        if outcome["revision_id"] is not None and params.get("p_renderer_version") and formats:
            if not set(formats) <= {"html", "pptx", "pdf"}:
                raise refuse("invalid_render_formats")
            payload = {
                "document_id": document_id,
                "revision_id": outcome["revision_id"],
                "renderer_version": params["p_renderer_version"],
                "formats": formats,
                "requested_by_job": job["id"],
            }
            active = any(
                row.get("job_type") == "presentation_render"
                and row.get("status") in ("queued", "processing")
                and all(
                    (row.get("payload") or {}).get(k) == payload[k]
                    for k in ("revision_id", "renderer_version", "formats")
                )
                for row in self._rows("generation_jobs")
            )
            if not active:
                self._rows("generation_jobs").append(
                    {
                        "id": str(uuid.uuid4()),
                        "project_id": job["project_id"],
                        "user_id": owner,
                        "job_type": "presentation_render",
                        "status": "queued",
                        "payload": payload,
                        "attempts": 0,
                        "max_attempts": 1,
                        "progress": {},
                        "created_at": self._now(),
                    }
                )
        return result

    def accept_proposal(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        """Replace the head the caller saw with the proposal's content."""

        proposal = self._one("revision_proposals", id=params["p_proposal_id"])
        if proposal is None:
            raise refuse("proposal_not_found")
        document = self._one("documents", id=proposal["document_id"])
        assert document is not None
        owner = self._owner(str(document["project_id"]), str(params["p_actor"]), "manual")
        key = params["p_idempotency_key"]
        head = document.get("head_revision_id")
        prior = self._one("document_revisions", document_id=document["id"], idempotency_key=key)
        if prior is not None:
            if prior.get("accepted_from_proposal_id") != proposal["id"]:
                raise refuse("idempotency_key_reused")
            return self._result("duplicate", document["id"], prior["id"], head, proposal["id"])
        if proposal["status"] != "pending":
            raise refuse("proposal_not_pending")
        head_row = self._one("document_revisions", id=head) if head else None
        if head_row is not None and head_row["schema_version"] != proposal["schema_version"]:
            raise refuse("proposal_schema_mismatch")
        if params["p_expected_head_revision_id"] != head:
            return self._result("conflict", document["id"], None, head, proposal["id"])
        revision_id = self._insert_revision(
            document,
            {
                "created_by": owner,
                "idempotency_key": key,
                "content": proposal["content"],
                "content_sha256": proposal["content_sha256"],
                "kind": proposal["kind"],
                "schema_version": proposal["schema_version"],
                "actor": params["p_actor"],
                "accepted_from_proposal_id": proposal["id"],
            },
        )
        proposal.update(
            status="accepted",
            resolved_at=self._now(),
            resolved_by=owner,
            accepted_revision_id=revision_id,
        )
        return self._result("committed", document["id"], revision_id, revision_id, proposal["id"])

    def reject_proposal(self, params: dict[str, Any]) -> str:
        """Pending → rejected (idempotent)."""

        proposal = self._one("revision_proposals", id=params["p_proposal_id"])
        if proposal is None:
            raise refuse("proposal_not_found")
        document = self._one("documents", id=proposal["document_id"])
        assert document is not None
        owner = self._owner(str(document["project_id"]), str(params["p_actor"]), "manual")
        if proposal["status"] == "rejected":
            return "rejected"
        if proposal["status"] != "pending":
            raise refuse("proposal_not_pending")
        proposal.update(status="rejected", resolved_at=self._now(), resolved_by=owner)
        return "rejected"

    def register_export(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        """Claim-fenced, first-writer-wins export registration.

        Mirrors the SQL's three-valued logic: a missing (None) value on either side
        of a comparison refuses, never matches.
        """

        job = self._claimed_job(params, fresh=False)
        payload = cast(dict[str, Any], job.get("payload") or {})
        if job.get("job_type") != "presentation_render":
            raise refuse("job_type_not_allowed")
        target = payload.get("revision_id")
        if params.get("p_revision_id") is None or target is None:
            raise refuse("job_revision_mismatch")
        if str(target) != str(params["p_revision_id"]):
            raise refuse("job_revision_mismatch")
        version = params.get("p_renderer_version")
        if version is None or payload.get("renderer_version") is None:
            raise refuse("renderer_version_mismatch")
        if payload["renderer_version"] != version:
            raise refuse("renderer_version_mismatch")
        fmt = params.get("p_format")
        formats = payload.get("formats")
        if fmt is None or not isinstance(formats, list) or fmt not in formats:
            raise refuse("format_not_requested")
        revision = self._one("document_revisions", id=params["p_revision_id"])
        if revision is None:
            raise refuse("revision_not_found")
        document = self._one("documents", id=revision["document_id"])
        assert document is not None
        if document["project_id"] != job.get("project_id"):
            raise refuse("job_revision_mismatch")
        project = self._one("projects", id=document["project_id"])
        owner = project.get("user_id") if project is not None else None
        if owner is None or job.get("user_id") is None or str(job["user_id"]) != str(owner):
            raise refuse("not_document_owner")
        expected = (
            f"exports/{document['id']}/{revision['id']}/{version}/{fmt}/{params['p_sha256']}.{fmt}"
        )
        if params.get("p_storage_key") is None or params["p_storage_key"] != expected:
            raise refuse("invalid_storage_key")
        existing = self._one(
            "revision_exports", revision_id=revision["id"], format=fmt, renderer_version=version
        )
        if existing is None:
            self._rows("revision_exports").append(
                {
                    "revision_id": revision["id"],
                    "format": fmt,
                    "renderer_version": version,
                    "storage_key": params["p_storage_key"],
                    "sha256": params["p_sha256"],
                    "byte_size": params["p_byte_size"],
                    "page_count": params["p_page_count"],
                    "created_by_job": params["p_job_id"],
                    "created_at": self._now(),
                }
            )
            existing = self._rows("revision_exports")[-1]
            status = "registered"
        else:
            status = "existing"
        return [
            {
                "status": status,
                "storage_key": existing["storage_key"],
                "sha256": existing["sha256"],
                "byte_size": existing["byte_size"],
            }
        ]

    def record_revision_validation(self, params: dict[str, Any]) -> str:
        """Write-once validation verdict."""

        if self._one("revision_validations", revision_id=params["p_revision_id"]) is not None:
            return "exists"
        self._rows("revision_validations").append(
            {
                "revision_id": params["p_revision_id"],
                "validator": params["p_validator"],
                "status": params["p_status"],
                "detail": params["p_detail"],
                "created_at": self._now(),
            }
        )
        return "recorded"

    def call(self, fn: str, params: dict[str, Any]) -> SimpleNamespace | None:
        """Dispatch ``fn``; None when it is not one of the emulated functions."""

        handler = {
            "ensure_document": self.ensure_document,
            "commit_revision": self.commit_revision,
            "accept_proposal": self.accept_proposal,
            "reject_proposal": self.reject_proposal,
            "register_export": self.register_export,
            "record_revision_validation": self.record_revision_validation,
            "claim_job": self.claim_job,
            "heartbeat_job": self.heartbeat_job,
            "complete_job": self.complete_job,
            "finish_generation_job": self.finish_generation_job,
        }.get(fn)
        if handler is None:
            return None
        return SimpleNamespace(data=handler(params))


def seed_presentation(
    tables: dict[str, list[dict[str, Any]]],
    *,
    project_id: str,
    content: dict[str, Any],
    actor: str = "system:test",
) -> tuple[str, str]:
    """Give a project a presentation document whose head is ``content``.

    Returns ``(document_id, revision_id)``. Uses the emulator so the seeded rows
    have exactly the shape a real commit produces.
    """

    emulator = DocumentRpcEmulator(tables)
    document_id = emulator.ensure_document(
        {"p_project_id": project_id, "p_kind": "presentation", "p_actor": actor}
    )
    result = emulator.commit_revision(
        {
            "p_document_id": document_id,
            "p_base_revision_id": None,
            "p_content": content,
            "p_kind": "import",
            "p_schema_version": 1,
            "p_actor": actor,
            "p_idempotency_key": f"seed:{uuid.uuid4()}",
        }
    )
    return document_id, str(result[0]["revision_id"])
