"""Proposal review: diffs, replace-head-with-consent accept, reject (ADR 0001)."""

from __future__ import annotations

from typing import Any, cast
from uuid import UUID, uuid4

import httpx
import pytest

from packages.api.app import create_app
from packages.api.services.tokens import mint_app_jwt
from packages.platform.config import PlatformConfig
from packages.platform.database import DatabaseClient
from packages.platform.document_models import DocumentKind, RevisionKind
from packages.platform.document_store import DocumentStore
from tests.unit.fake_documents import DocumentRpcEmulator, seed_presentation
from tests.unit.test_database_client import FakeSupabaseClient

pytestmark = pytest.mark.asyncio

_SECRET = "test-jwt-secret"
_USER_ID = uuid4()
_PROJECT_ID = str(uuid4())
_JOB_ID = str(uuid4())


def _slide(slide_id: str, title: str) -> dict[str, Any]:
    return {"slide_id": slide_id, "slide_type": "content_split", "content": {"title": title}}


def _deck(*titles: tuple[str, str], title: str = "Deck") -> dict[str, Any]:
    return {"title": title, "slides": [_slide(slide_id, t) for slide_id, t in titles]}


def _config() -> PlatformConfig:
    return PlatformConfig(
        supabase_url="https://example.supabase.co",
        supabase_service_key="service",
        telegram_bot_token="123:abc",
        supabase_jwt_secret=_SECRET,
    )


class _FakeDb:
    async def get_project(self, project_id: str) -> dict[str, Any] | None:
        if project_id != _PROJECT_ID:
            return None
        return {"id": project_id, "user_id": str(_USER_ID), "type": "presentation"}


def _headers(user_id: UUID = _USER_ID) -> dict[str, str]:
    return {"Authorization": f"Bearer {mint_app_jwt(_SECRET, user_id, 3600).access_token}"}


class _World:
    """Base B; an AI edit started on B; the user then saved H on top of B."""

    def __init__(self) -> None:
        self.fake = FakeSupabaseClient()
        self.fake.seed("projects", [{"id": _PROJECT_ID, "user_id": str(_USER_ID)}])
        self.fake.seed(
            "generation_jobs",
            [
                {
                    "id": _JOB_ID,
                    "project_id": _PROJECT_ID,
                    "user_id": str(_USER_ID),
                    "job_type": "presentation_edit",
                    "status": "processing",
                    "worker_id": "w1",
                    "attempts": 1,
                    "heartbeat_at": "2026-01-01T00:00:00+00:00",
                }
            ],
        )
        self.store = DocumentStore(DatabaseClient(_config(), client=cast(Any, self.fake)))
        self.emulator = DocumentRpcEmulator(self.fake.tables)
        base_content = _deck(("a", "Intro"), ("b", "Method"))
        self.document_id, self.base = seed_presentation(
            self.fake.tables, project_id=_PROJECT_ID, content=base_content
        )
        # The user edited slide b after the AI edit started (the head moved).
        self.head = self._commit(
            self.base, _deck(("a", "Intro"), ("b", "Method, by hand")), "import", "system:web", "h"
        )
        # The AI rewrote slide a from the old base: stored as a proposal.
        proposed = self.emulator.finish_generation_job(
            {
                "p_job_id": _JOB_ID,
                "p_worker_id": "w1",
                "p_claim_token": 1,
                "p_base_revision_id": self.base,
                "p_content": _deck(("a", "Intro, by the AI"), ("b", "Method")),
                "p_kind": "ai_edit",
                "p_schema_version": 1,
                "p_idempotency_key": "ai",
                "p_renderer_version": None,
                "p_render_formats": [],
            }
        )[0]
        assert proposed["status"] == "proposed"
        self.proposal = str(proposed["proposal_id"])
        app = create_app(
            config=_config(),
            db=cast(Any, _FakeDb()),
            identity_service=cast(Any, object()),
            credits=cast(Any, object()),
            job_queue=cast(Any, object()),
            rate_limiter=cast(Any, object()),
            storage=cast(Any, object()),
            documents=self.store,
        )
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        )

    def _commit(self, base: str, content: dict[str, Any], kind: str, actor: str, key: str) -> str:
        result = self.emulator.commit_revision(
            {
                "p_document_id": self.document_id,
                "p_base_revision_id": base,
                "p_content": content,
                "p_kind": kind,
                "p_schema_version": 1,
                "p_actor": actor,
                "p_idempotency_key": key,
            }
        )[0]
        assert result["status"] == "committed"
        return str(result["revision_id"])

    async def accept(self, expected: str | None, key: str = "accept-1", user: UUID = _USER_ID):
        return await self.client.post(
            f"/projects/{_PROJECT_ID}/proposals/{self.proposal}/accept",
            json={"expected_head_revision_id": expected, "idempotency_key": key},
            headers=_headers(user),
        )


async def test_pending_proposals_are_listed_with_the_head_they_compete_with() -> None:
    w = _World()
    body = (await w.client.get(f"/projects/{_PROJECT_ID}/proposals", headers=_headers())).json()
    assert body["head_revision_id"] == w.head
    assert [p["id"] for p in body["proposals"]] == [w.proposal]
    assert body["proposals"][0]["kind"] == "ai_edit"
    assert body["proposals"][0]["base_revision_id"] == w.base


async def test_the_diff_shows_what_the_ai_changed_and_what_accepting_reverts() -> None:
    w = _World()
    body = (
        await w.client.get(
            f"/projects/{_PROJECT_ID}/proposals/{w.proposal}/diff", headers=_headers()
        )
    ).json()

    assert body["head_revision_id"] == w.head
    # base → proposal: the AI changed slide a only
    assert [(e["item_id"], e["change"]) for e in body["ai_changes"]["entries"]] == [
        ("a", "changed")
    ]
    # head → proposal: accepting ALSO reverts the user's later edit to slide b
    assert [(e["item_id"], e["change"]) for e in body["accept_changes"]["entries"]] == [
        ("a", "changed"),
        ("b", "changed"),
    ]
    assert body["accept_changes"]["entries"][1]["label"] == "Method"
    assert body["schema_matches_head"] is True


async def test_accept_against_the_head_the_user_saw_commits_on_top_of_it() -> None:
    w = _World()
    response = await w.accept(w.head)

    assert response.status_code == 200
    new_head = response.json()["revision_id"]
    head = await w.store.head(_PROJECT_ID, DocumentKind.PRESENTATION)
    assert head is not None and head.revision_id == new_head
    assert head.revision.parent_revision_id == w.head
    assert head.revision.kind is RevisionKind.AI_EDIT
    assert head.revision.accepted_from_proposal_id == w.proposal
    assert head.content["slides"][0]["content"]["title"] == "Intro, by the AI"
    proposal = w.fake.tables["revision_proposals"][0]
    assert proposal["status"] == "accepted" and proposal["resolved_by"] == str(_USER_ID)


async def test_accept_after_the_head_moved_conflicts_and_changes_nothing() -> None:
    w = _World()
    seen = w.head
    moved = w._commit(w.head, _deck(("a", "Intro"), ("b", "Again")), "import", "system:web", "x")

    response = await w.accept(seen)

    assert response.status_code == 409
    assert response.json()["detail"] == {"reason": "stale_revision", "head_revision_id": moved}
    head = await w.store.head(_PROJECT_ID, DocumentKind.PRESENTATION)
    assert head is not None and head.revision_id == moved
    assert w.fake.tables["revision_proposals"][0]["status"] == "pending"


async def test_a_retried_accept_is_idempotent() -> None:
    w = _World()
    first = await w.accept(w.head, key="accept-once")
    again = await w.accept(w.head, key="accept-once")

    assert again.status_code == 200
    assert again.json()["revision_id"] == first.json()["revision_id"]
    assert len(w.fake.tables["document_revisions"]) == 3  # base, user head, accepted


async def test_accept_by_another_user_is_refused() -> None:
    w = _World()
    response = await w.accept(w.head, user=uuid4())
    assert response.status_code == 404
    assert w.fake.tables["revision_proposals"][0]["status"] == "pending"


async def test_a_proposal_from_another_schema_version_is_refused() -> None:
    w = _World()
    w.fake.tables["revision_proposals"][0]["schema_version"] = 2

    response = await w.accept(w.head)

    assert response.status_code == 409
    assert response.json()["detail"] == {"reason": "proposal_schema_mismatch"}


async def test_the_replaced_head_stays_restorable_from_history() -> None:
    w = _World()
    await w.accept(w.head)

    revision = await w.store.revision(w.document_id, w.head)

    assert revision is not None and revision.content is not None
    assert revision.content["slides"][1]["content"]["title"] == "Method, by hand"


async def test_reject_dismisses_and_keeps_the_content() -> None:
    w = _World()
    response = await w.client.post(
        f"/projects/{_PROJECT_ID}/proposals/{w.proposal}/reject", headers=_headers()
    )
    assert response.status_code == 200 and response.json()["status"] == "rejected"
    stored = await w.store.proposal(w.document_id, w.proposal)
    assert stored is not None and stored.content is not None
    after = await w.accept(w.head, key="after-reject")
    assert after.status_code == 409
    assert after.json()["detail"] == {"reason": "proposal_not_pending"}


async def test_an_unknown_proposal_is_404() -> None:
    w = _World()
    response = await w.client.get(
        f"/projects/{_PROJECT_ID}/proposals/{uuid4()}/diff", headers=_headers()
    )
    assert response.status_code == 404
