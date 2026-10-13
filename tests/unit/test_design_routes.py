"""Behavior tests for versioned direct presentation design routes (ADR 0001)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

import httpx
import pytest

from packages.api.app import create_app
from packages.api.services.tokens import mint_app_jwt
from packages.core.enums import (
    AudienceType,
    BackgroundTreatment,
    PresentationMood,
    SlideType,
)
from packages.core.models.presentation import (
    ColorPalette,
    DeckSpec,
    DesignDirectionSpec,
    PresentationInterviewAnswers,
    SlideContent,
    SlideSpec,
)
from packages.platform.config import PlatformConfig
from packages.platform.database import DatabaseClient
from packages.platform.document_models import DocumentKind
from packages.platform.document_store import DocumentStore
from packages.platform.exports import renderer_version
from packages.platform.jobs import JobQueue
from packages.platform.rate_limit import RateDecision
from tests.unit.fake_documents import seed_presentation
from tests.unit.test_database_client import FakeSupabaseClient

pytestmark = pytest.mark.asyncio

_SECRET = "test-jwt-secret"
_USER_ID = uuid4()
_PROJECT_ID = str(uuid4())


def _deck(title: str = "Learning") -> DeckSpec:
    return DeckSpec(
        project_id=_PROJECT_ID,
        title=title,
        design=DesignDirectionSpec(
            mood=PresentationMood.WARM_HISTORICAL,
            palette=ColorPalette(
                background="#FFFCF0",
                surface="#F2F0E5",
                text="#100F0F",
                accent="#205EA6",
                text_secondary="#575653",
            ),
            heading_font="Source Serif 4",
            body_font="Inter",
            image_style_prefix="editorial classroom photograph, ",
            background_treatment=BackgroundTreatment.LIGHT,
        ),
        interview=PresentationInterviewAnswers(audience=AudienceType.UNDERGRADUATE),
        slides=[
            SlideSpec(
                slide_index=0,
                slide_type=SlideType.TITLE_HERO,
                content=SlideContent(title=title),
            )
        ],
    )


class _FakeDb:
    def __init__(self) -> None:
        self.owner = str(_USER_ID)

    async def get_project(self, project_id: str) -> dict[str, Any] | None:
        return {"id": project_id, "user_id": self.owner, "type": "presentation"}


class _FakeLimiter:
    async def check(self, *, action: str, user_id: str, ip: str) -> RateDecision:
        return RateDecision(
            allowed=True,
            scope="user",
            action=action,
            count=1,
            limit=120,
            resets_at=datetime.now(UTC) + timedelta(days=1),
        )


class _Harness:
    def __init__(self, *, with_deck: bool = True, head: dict[str, Any] | None = None) -> None:
        self.fake = FakeSupabaseClient()
        self.fake.seed("projects", [{"id": _PROJECT_ID, "user_id": str(_USER_ID)}])
        cfg = _config()
        self.store = DocumentStore(DatabaseClient(cfg, client=cast(Any, self.fake)))
        self.revision_id: str | None = None
        if with_deck:
            content = head if head is not None else _deck().model_dump(mode="json")
            _doc, self.revision_id = seed_presentation(
                self.fake.tables, project_id=_PROJECT_ID, content=content
            )
        # The real queue over the same fake: request_render runs the 016 emulator.
        self.queue = JobQueue(DatabaseClient(cfg, client=cast(Any, self.fake)))
        app = create_app(
            config=cfg,
            db=cast(Any, _FakeDb()),
            identity_service=cast(Any, object()),
            credits=cast(Any, object()),
            job_queue=cast(Any, self.queue),
            rate_limiter=cast(Any, _FakeLimiter()),
            storage=cast(Any, object()),
            documents=self.store,
        )
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        )

    async def save(
        self, base: str, content: dict[str, Any], key: str, kind: str = "manual"
    ) -> httpx.Response:
        return await self.client.put(
            f"/projects/{_PROJECT_ID}/design",
            json={
                "base_revision_id": base,
                "idempotency_key": key,
                "content": content,
                "kind": kind,
            },
            headers=_headers(),
        )


def _config() -> PlatformConfig:
    return PlatformConfig(
        supabase_url="https://example.supabase.co",
        supabase_service_key="service",
        telegram_bot_token="123:abc",
        supabase_jwt_secret=_SECRET,
    )


def _headers(user_id: UUID = _USER_ID) -> dict[str, str]:
    session = mint_app_jwt(_SECRET, user_id, 3600)
    return {"Authorization": f"Bearer {session.access_token}"}


async def test_get_design_returns_the_head_revision() -> None:
    h = _Harness()
    response = await h.client.get(f"/projects/{_PROJECT_ID}/design", headers=_headers())
    assert response.status_code == 200
    assert response.json()["revision_id"] == h.revision_id
    assert response.json()["content"]["slides"][0]["content"]["title"] == "Learning"


async def test_get_design_without_a_document_is_not_ready() -> None:
    h = _Harness(with_deck=False)
    response = await h.client.get(f"/projects/{_PROJECT_ID}/design", headers=_headers())
    assert response.status_code == 404
    assert response.json()["detail"] == "deck_not_ready"


async def test_save_design_commits_a_new_head_as_a_manual_revision() -> None:
    h = _Harness()
    content = _deck("Edited directly").model_dump(mode="json")
    saved = await h.save(str(h.revision_id), content, "save-1")
    assert saved.status_code == 200
    assert saved.json()["revision_id"] != h.revision_id
    assert saved.json()["content"]["slides"][0]["content"]["title"] == "Edited directly"
    head = await h.store.head(_PROJECT_ID, DocumentKind.PRESENTATION)
    assert head is not None and head.revision_id == saved.json()["revision_id"]
    assert head.revision.kind.value == "manual"
    assert head.revision.actor == str(_USER_ID)


async def test_stale_save_is_a_409_that_names_the_current_head() -> None:
    h = _Harness()
    first = await h.save(str(h.revision_id), _deck("First").model_dump(mode="json"), "save-a")
    stale = await h.save(str(h.revision_id), _deck("Second").model_dump(mode="json"), "save-b")
    assert stale.status_code == 409
    assert stale.json()["detail"] == {
        "reason": "stale_revision",
        "head_revision_id": first.json()["revision_id"],
    }
    head = await h.store.head(_PROJECT_ID, DocumentKind.PRESENTATION)
    assert head is not None and head.content["title"] == "First"


async def test_identical_save_is_a_no_op_that_keeps_the_head() -> None:
    # Resaving exactly what the editor loaded must not create a revision (an
    # identical autosave would otherwise turn every in-flight AI edit into a proposal).
    h = _Harness()
    opened = (await h.client.get(f"/projects/{_PROJECT_ID}/design", headers=_headers())).json()
    same = await h.save(opened["revision_id"], opened["content"], "save-same", kind="autosave")
    assert same.status_code == 200
    assert same.json()["revision_id"] == h.revision_id
    assert len(await h.store.list_revisions(await _doc_id(h))) == 1


async def _doc_id(h: _Harness) -> str:
    document_id = await h.store.document_id(_PROJECT_ID, DocumentKind.PRESENTATION)
    assert document_id is not None
    return document_id


async def test_retried_save_with_the_same_key_returns_the_same_revision() -> None:
    h = _Harness()
    content = _deck("Once").model_dump(mode="json")
    first = await h.save(str(h.revision_id), content, "retry-key")
    again = await h.save(str(h.revision_id), content, "retry-key")
    assert again.status_code == 200
    assert again.json()["revision_id"] == first.json()["revision_id"]


async def test_reusing_a_key_for_different_content_is_refused() -> None:
    h = _Harness()
    await h.save(str(h.revision_id), _deck("A").model_dump(mode="json"), "same-key")
    reused = await h.save(str(h.revision_id), _deck("B").model_dump(mode="json"), "same-key")
    assert reused.status_code == 409
    assert reused.json()["detail"] == {"reason": "idempotency_key_reused"}


async def test_autosave_is_recorded_as_an_autosave() -> None:
    h = _Harness()
    saved = await h.save(
        str(h.revision_id), _deck("Typed").model_dump(mode="json"), "auto-1", kind="autosave"
    )
    history = await h.client.get(f"/projects/{_PROJECT_ID}/design/revisions", headers=_headers())
    assert saved.status_code == 200
    assert history.json()["revisions"][0]["kind"] == "autosave"


async def test_manual_save_commits_even_while_an_ai_edit_is_running() -> None:
    # The old route refused manual saves while an edit job ran. The database now
    # arbitrates: the manual save commits; a racing AI edit becomes a proposal.
    h = _Harness()
    h.fake.tables.setdefault("generation_jobs", []).append(
        {
            "id": "edit-1",
            "project_id": _PROJECT_ID,
            "user_id": str(_USER_ID),
            "job_type": "presentation_edit",
            "status": "processing",
            "payload": {},
            "attempts": 1,
            "max_attempts": 1,
        }
    )
    saved = await h.save(str(h.revision_id), _deck("Human").model_dump(mode="json"), "busy")
    assert saved.status_code == 200


def _renders(h: _Harness) -> list[dict[str, Any]]:
    return [
        row
        for row in h.fake.tables.get("generation_jobs", [])
        if row["job_type"] == "presentation_render"
    ]


async def test_render_queues_the_exact_revision_with_renderer_and_formats() -> None:
    h = _Harness()
    response = await h.client.post(
        f"/projects/{_PROJECT_ID}/design/render",
        json={"revision_id": h.revision_id},
        headers=_headers(),
    )
    assert response.status_code == 200
    body = response.json()
    [render] = _renders(h)
    assert body["job_id"] == render["id"] and body["existing"] is False
    assert body["renderer_version"] == renderer_version()
    payload = render["payload"]
    assert payload["revision_id"] == h.revision_id
    assert payload["formats"] == ["html", "pdf", "pptx"]
    assert payload["renderer_version"] == renderer_version()
    # Render retries come from config (PlatformConfig.render_max_attempts).
    assert render["max_attempts"] == 3


async def test_render_of_the_same_revision_reuses_the_active_job() -> None:
    h = _Harness()
    url = f"/projects/{_PROJECT_ID}/design/render"
    first = await h.client.post(url, json={"revision_id": h.revision_id}, headers=_headers())
    second = await h.client.post(url, json={"revision_id": h.revision_id}, headers=_headers())
    assert second.json()["job_id"] == first.json()["job_id"]
    assert second.json()["existing"] is True
    assert len(_renders(h)) == 1


async def test_render_reuses_an_active_render_whose_formats_cover_the_request() -> None:
    # B1-FIX2 item 5: the automatic render for [html, pdf, pptx] registered html;
    # "Update exports" now needs [pdf, pptx], which that active job covers. The old
    # exact-tuple dedupe queued a second job rendering pdf and pptx twice.
    h = _Harness()
    url = f"/projects/{_PROJECT_ID}/design/render"
    first = await h.client.post(url, json={"revision_id": h.revision_id}, headers=_headers())
    _register(h, ("html",))
    second = await h.client.post(url, json={"revision_id": h.revision_id}, headers=_headers())
    assert second.json()["job_id"] == first.json()["job_id"]
    assert second.json()["existing"] is True
    assert second.json()["formats"] == ["pdf", "pptx"]
    assert len(_renders(h)) == 1


async def test_render_of_another_revision_gets_its_own_job() -> None:
    # The old per-project dedupe handed a request for the head an active render
    # of an older revision. Dedupe is now keyed on the revision.
    h = _Harness()
    saved = await h.save(str(h.revision_id), _deck("Newer").model_dump(mode="json"), "newer")
    url = f"/projects/{_PROJECT_ID}/design/render"
    older = await h.client.post(url, json={"revision_id": h.revision_id}, headers=_headers())
    newer = await h.client.post(
        url, json={"revision_id": saved.json()["revision_id"]}, headers=_headers()
    )
    assert older.json()["job_id"] != newer.json()["job_id"]
    assert newer.json()["revision_id"] == saved.json()["revision_id"]


def _register(h: _Harness, formats: tuple[str, ...]) -> None:
    """Exports of the harness revision as an earlier render registered them."""

    document = h.fake.tables["documents"][0]
    for name in formats:
        h.fake.tables.setdefault("revision_exports", []).append(
            {
                "revision_id": h.revision_id,
                "format": name,
                "renderer_version": renderer_version(),
                "storage_key": f"exports/{document['id']}/{h.revision_id}/x/{name}/k.{name}",
                "sha256": "a" * 64,
                "byte_size": 1,
                "page_count": None,
                "created_by_job": None,
                "created_at": "2026-01-01T00:00:00+00:00",
            }
        )


async def test_render_resumes_a_partial_set_with_only_the_missing_formats() -> None:
    # An earlier render registered html, then failed before pdf and pptx.
    h = _Harness()
    _register(h, ("html",))
    response = await h.client.post(
        f"/projects/{_PROJECT_ID}/design/render",
        json={"revision_id": h.revision_id},
        headers=_headers(),
    )
    assert response.status_code == 200
    assert response.json()["formats"] == ["pdf", "pptx"]
    assert _renders(h)[0]["payload"]["formats"] == ["pdf", "pptx"]


async def test_render_of_a_complete_set_queues_nothing() -> None:
    h = _Harness()
    _register(h, ("html", "pdf", "pptx"))
    response = await h.client.post(
        f"/projects/{_PROJECT_ID}/design/render",
        json={"revision_id": h.revision_id},
        headers=_headers(),
    )
    body = response.json()
    assert (body["status"], body["job_id"], body["formats"]) == ("ready", None, [])
    assert _renders(h) == []


async def test_render_of_an_unknown_revision_is_404() -> None:
    h = _Harness()
    response = await h.client.post(
        f"/projects/{_PROJECT_ID}/design/render",
        json={"revision_id": str(uuid4())},
        headers=_headers(),
    )
    assert response.status_code == 404


async def test_design_history_lists_revisions_and_restore_creates_new_head() -> None:
    h = _Harness()
    original = str(h.revision_id)
    saved = (await h.save(original, _deck("Second version").model_dump(mode="json"), "s")).json()

    history = await h.client.get(f"/projects/{_PROJECT_ID}/design/revisions", headers=_headers())
    assert history.status_code == 200
    assert len(history.json()["revisions"]) == 2

    restored = await h.client.post(
        f"/projects/{_PROJECT_ID}/design/restore",
        json={
            "revision_id": original,
            "base_revision_id": saved["revision_id"],
            "idempotency_key": "restore-original",
        },
        headers=_headers(),
    )
    assert restored.status_code == 200
    assert restored.json()["revision_id"] not in {original, saved["revision_id"]}
    assert restored.json()["content"]["slides"][0]["content"]["title"] == "Learning"
    head = await h.store.head(_PROJECT_ID, DocumentKind.PRESENTATION)
    assert head is not None and head.revision.kind.value == "restore"


async def test_restore_rejects_revision_from_another_document() -> None:
    h = _Harness()
    response = await h.client.post(
        f"/projects/{_PROJECT_ID}/design/restore",
        json={
            "revision_id": str(uuid4()),
            "base_revision_id": h.revision_id,
            "idempotency_key": "restore-missing",
        },
        headers=_headers(),
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "revision_not_found"


async def test_a_legacy_invalid_head_is_reported_not_crashed() -> None:
    h = _Harness(head={"legacy_raw": ["not", "a", "deck"]})
    response = await h.client.get(f"/projects/{_PROJECT_ID}/design", headers=_headers())
    assert response.status_code == 409
    assert response.json()["detail"] == {"reason": "legacy_invalid", "revision_id": h.revision_id}


async def test_other_user_cannot_open_design() -> None:
    h = _Harness()
    response = await h.client.get(f"/projects/{_PROJECT_ID}/design", headers=_headers(uuid4()))
    assert response.status_code == 404
