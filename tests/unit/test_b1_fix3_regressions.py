"""B1-FIX3 regressions (Codex Review A of B1-FIX2 at fdb14bc), over the 016 emulator.

CI runs this module twice: against the application as of fdb14bc (the
``prefix-fdb14bc`` job), where every test must fail for the reason pinned in
``tests/prefix/unit_fix2.json``, and against the fix, where every test passes.
Each test therefore drives only interfaces fdb14bc already had: the HTTP routes,
the session store, ``dispatch_fix`` and the job functions.

A1  a worker killed after ``finish_generation_job`` returned, before any session
    write, lost the edit's allowance hold and its chat notice;
A2  a ``GET /chat`` poll rewrote the whole session it had read, deleting what a
    worker or a turn saved meanwhile;
A3  a persisted session or job row that does not parse crashed the request (500).
And the user's check on the split counter: no web or worker path writes
``brain_sessions.fixes_used``.
"""

from __future__ import annotations

import asyncio
import copy
import logging
import threading
import uuid
from typing import Any, cast

import httpx
import pytest

from packages.api.app import create_app
from packages.api.services.tokens import mint_app_jwt
from packages.bot.sessions import create_session, load_session, persist_session
from packages.bot.sessions.budget import session_fix_limit
from packages.bot.sessions.driver import ScriptedStubDriver, StubResponse
from packages.bot.sessions.models import TurnAction
from packages.core.enums import AudienceType, ExportFormat, GenerationPackage
from packages.core.models.presentation import DeckSpec, SlideFix
from packages.platform.config import PlatformConfig
from packages.platform.database import DatabaseClient
from packages.platform.document_models import CommitOutcome, RevisionKind
from packages.platform.document_store import DocumentStore
from packages.platform.rate_limit import RateDecision
from packages.sessions_core.chat import dispatch_fix, has_dangling_call
from tests.unit.fake_documents import seed_presentation
from tests.unit.test_brain_session import (  # pyright: ignore[reportPrivateUsage]
    _FakeOrchestrator,
    _make_sources,
)
from tests.unit.test_database_client import (  # pyright: ignore[reportPrivateUsage]
    FakeSupabaseClient,
    _make_db,
    _make_deck,
    _seed_project,
)
from tests.unit.test_sessions_core_chat import (  # pyright: ignore[reportPrivateUsage]
    _model_turn,
    _progress,
    _response_payload,
    _user_turn,
)

pytestmark = pytest.mark.asyncio

_SECRET = "fix3-jwt-secret"
_USER = uuid.uuid4()
_PROJECT = "proj-1"


class _Killed(BaseException):
    """The worker process dies: nothing after this point runs (not an Exception)."""


class _Credits:
    async def has_refund_for_job(self, user_id: str, job_id: str) -> bool:
        return False


class _Limiter:
    async def check(self, *, action: str, user_id: str, ip: str) -> RateDecision:
        from datetime import UTC, datetime, timedelta

        return RateDecision(
            allowed=True,
            scope="user",
            action=action,
            count=1,
            limit=200,
            resets_at=datetime.now(UTC) + timedelta(hours=1),
        )


class _World:
    """One presentation project with a session, served by the real API over the fake."""

    def __init__(self, replies: list[str] | None = None) -> None:
        self.db: DatabaseClient
        self.fake: FakeSupabaseClient
        self.db, self.fake = _make_db()
        _seed_project(self.fake)
        self.fake.tables["projects"][0]["user_id"] = str(_USER)
        self.deck: DeckSpec = _make_deck(title="Cooling", audience=AudienceType.UNDERGRADUATE)
        driver = ScriptedStubDriver(
            script=[StubResponse(action=TurnAction.REPLY, reply_text=r) for r in replies or []]
        )
        app = create_app(
            config=PlatformConfig(
                supabase_url="https://example.supabase.co",
                supabase_service_key="service",
                telegram_bot_token="123:abc",
                supabase_jwt_secret=_SECRET,
            ),
            db=self.db,
            identity_service=cast(Any, object()),
            credits=cast(Any, _Credits()),
            rate_limiter=cast(Any, _Limiter()),
            brain_driver_factory=lambda: driver,
        )
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        )
        self.headers = {
            "Authorization": f"Bearer {mint_app_jwt(_SECRET, _USER, 3600).access_token}"
        }

    async def open(self) -> _World:
        _document, revision = seed_presentation(
            self.fake.tables, project_id=_PROJECT, content=self.deck.model_dump(mode="json")
        )
        await create_session(
            self.db,
            project_id=_PROJECT,
            sources=_make_sources(with_figure=False),
            package=GenerationPackage.PRESENTATION_PREMIUM,
            formats=[ExportFormat.HTML],
            revision_id=revision,
            deck=self.deck,
        )
        return self

    def session_row(self) -> dict[str, Any]:
        [row] = self.fake.tables["brain_sessions"]
        return row

    async def chat(self) -> dict[str, Any]:
        response = await self.client.get(f"/projects/{_PROJECT}/chat", headers=self.headers)
        assert response.status_code == 200, response.text
        return cast(dict[str, Any], response.json())

    async def park(self) -> str:
        """Park one edit_slides call the way POST /chat does; return its edit job."""

        session = await load_session(self.db, _PROJECT)
        assert session is not None
        session.history = [*session.history, _user_turn("tighten"), _model_turn("ok", calls=1)]
        await persist_session(self.db, session)
        reloaded = await load_session(self.db, _PROJECT)
        assert reloaded is not None and has_dangling_call(reloaded) == 1
        job_id = str(uuid.uuid4())
        self.fake.tables.setdefault("generation_jobs", []).append(
            {
                "id": job_id,
                "project_id": _PROJECT,
                "user_id": str(_USER),
                "job_type": "presentation_edit",
                "status": "processing",
                "worker_id": "w1",
                "attempts": 1,
                "max_attempts": 1,
                "payload": {
                    "slides_changed": 1,
                    "history_len": len(reloaded.history),
                    "session_id": str(self.session_row()["id"]),
                    "base_revision_id": reloaded.revision_id,
                },
                "progress": {},
                "heartbeat_at": "2026-01-01T00:00:00+00:00",
                "created_at": f"2026-01-0{len(self.fake.tables['generation_jobs']) + 1}",
            }
        )
        return job_id

    async def dispatch(self, job_id: str, title: str, *, kill: bool = False) -> None:
        """The worker's edit: commit with the job (one transaction), then answer."""

        store = DocumentStore(self.db)

        async def commit(edited: Any, base: str | None) -> CommitOutcome:
            outcome = await store.finish_generation_job(
                job_id=job_id,
                worker_id="w1",
                claim_token=1,
                base_revision_id=base,
                content=edited.model_dump(mode="json"),
                kind=RevisionKind.AI_EDIT,
                idempotency_key=f"chat-edit:{job_id}",
                renderer_version="pw-test",
                render_formats=["html"],
                render_max_attempts=1,
            )
            if kill:
                raise _Killed
            return outcome

        session = await load_session(self.db, _PROJECT)
        assert session is not None and session.revision_id is not None
        await dispatch_fix(
            runner=cast(Any, _FakeOrchestrator(self.deck.model_copy(update={"title": title}))),
            db=self.db,
            project_id=_PROJECT,
            fixes=[SlideFix(slide_id="s0", instruction="tighten")],
            call_count=1,
            progress=_progress(),
            base_revision_id=session.revision_id,
            commit=commit,
            deliver=None,
            delivery_job_id=job_id,
        )

    async def delivered_edit(self, title: str) -> str:
        job_id = await self.park()
        await self.dispatch(job_id, title)
        await _render_succeeds(self.db, _job(self.db, job_id)["render_job_id"])
        return job_id


def _job(db: DatabaseClient, job_id: str) -> dict[str, Any]:
    fake = cast(FakeSupabaseClient, db._client)  # pyright: ignore[reportPrivateUsage]
    return next(row for row in fake.tables["generation_jobs"] if row["id"] == job_id)


async def _claim_render(db: DatabaseClient, render_id: str) -> int:
    [claimed] = db.rpc("claim_job", {"p_job_id": render_id, "p_worker_id": "r1"}).data
    return int(claimed["attempts"])


async def _render_succeeds(db: DatabaseClient, render_id: str) -> None:
    """The render publishes every requested format (rows as register_export writes them)."""

    token = await _claim_render(db, render_id)
    render = _job(db, render_id)
    payload = render["payload"]
    fake = cast(FakeSupabaseClient, db._client)  # pyright: ignore[reportPrivateUsage]
    for fmt in payload["formats"]:
        fake.tables.setdefault("revision_exports", []).append(
            {
                "revision_id": payload["revision_id"],
                "format": fmt,
                "renderer_version": payload["renderer_version"],
                "storage_key": f"exports/d/{payload['revision_id']}/pw-test/{fmt}/k.{fmt}",
                "sha256": "a" * 64,
                "byte_size": 1,
                "page_count": None,
                "created_by_job": render_id,
                "created_at": "2026-01-01T00:00:00+00:00",
            }
        )
    params = {"p_job_id": render_id, "p_worker_id": "r1", "p_claim_token": token}
    assert db.rpc("complete_job", {**params, "p_progress": {}}).data is True


async def _render_fails(db: DatabaseClient, render_id: str) -> None:
    """The render gives up for good (these renders get one attempt)."""

    token = await _claim_render(db, render_id)
    params = {"p_job_id": render_id, "p_worker_id": "r1", "p_claim_token": token}
    assert db.rpc("fail_job", {**params, "p_step": "render", "p_message": "crash"}).data is True


def _system(view: dict[str, Any]) -> list[str]:
    return [m["text"] for m in view["messages"] if m["role"] == "system"]


def _writes(fake: FakeSupabaseClient) -> int:
    return len(fake.inserts) + len(fake.updates) + len(fake.deletes)


# ------------------------------------------------------------------------- A1


async def test_a_worker_killed_after_the_commit_still_counts_the_edit_once_and_says_so_once() -> (
    None
):
    world = await _World().open()
    job_id = await world.park()
    with pytest.raises(_Killed):
        await world.dispatch(job_id, "Edited", kill=True)
    await _render_succeeds(world.db, _job(world.db, job_id)["render_job_id"])

    for _ in range(2):  # every read, not only the first
        view = await world.chat()
        assert view["fixes_used"] == 1, "the delivered edit was not counted"
        assert view["fixes_pending"] == 0
        assert len(_system(view)) == 1, f"notices: {_system(view)}"
    session = await load_session(world.db, _PROJECT)
    assert session is not None
    assert has_dangling_call(session) == 0, "the edit's call was never answered"
    assert _response_payload(session.history[-1])["committed"] is True
    await persist_session(world.db, session)  # the next write folds it in
    view = await world.chat()
    assert view["fixes_used"] == 1 and len(_system(view)) == 1


async def test_a_worker_killed_after_the_commit_still_holds_the_fix_until_the_render_fails() -> (
    None
):
    world = await _World().open()
    job_id = await world.park()
    with pytest.raises(_Killed):
        await world.dispatch(job_id, "Edited", kill=True)

    rendering = await world.chat()
    assert rendering["fixes_pending"] == 1, "the committed edit held nothing"
    assert rendering["delivering_job_ids"] == [job_id]
    await _render_fails(world.db, _job(world.db, job_id)["render_job_id"])

    view = await world.chat()
    limit = session_fix_limit(GenerationPackage.PRESENTATION_PREMIUM)
    assert (view["fixes_used"], view["fixes_pending"], view["fixes_remaining"]) == (0, 0, limit)
    assert len(_system(view)) == 1


async def test_no_web_or_worker_path_writes_fixes_used() -> None:
    world = await _World(replies=["Albatta.", "Yana savol?"]).open()
    turn = await world.client.post(
        f"/projects/{_PROJECT}/chat", json={"message": "Salom"}, headers=world.headers
    )
    assert turn.status_code == 200
    await world.chat()
    await world.delivered_edit("Edited")
    await world.chat()
    turn = await world.client.post(
        f"/projects/{_PROJECT}/chat", json={"message": "Rahmat"}, headers=world.headers
    )
    assert turn.status_code == 200

    writes = [
        (table, payload)
        for table, payload in [*world.fake.inserts, *[(t, p) for t, p, _f in world.fake.updates]]
        if table == "brain_sessions"
    ]
    assert writes, "no session write was observed"
    offenders = [payload for _table, payload in writes if "fixes_used" in payload]
    assert offenders == [], f"a web/worker session write wrote fixes_used: {len(offenders)}"


# ------------------------------------------------------------------------- A2


async def test_get_chat_performs_no_writes() -> None:
    world = await _World().open()
    await world.delivered_edit("Edited")
    before = _writes(world.fake)

    view = await world.chat()

    assert view["fixes_used"] == 1
    assert _writes(world.fake) == before, "GET /chat wrote to the database"


class _Barrier:
    """Pause the first generation_jobs read on the reading thread until released."""

    def __init__(self, fake: FakeSupabaseClient) -> None:
        self.paused = threading.Event()
        self.release = threading.Event()
        self._fake = fake
        fake.before_select = self._hook

    def _hook(self, table: str, _filters: list[tuple[str, Any]]) -> None:
        if table != "generation_jobs":
            return
        self._fake.before_select = None
        self.paused.set()
        self.release.wait(timeout=30)

    async def wait_paused(self) -> None:
        assert await asyncio.to_thread(self.paused.wait, 30), "the poll never reached a job read"


async def test_a_poll_overlapping_a_worker_loses_nothing_the_worker_saved() -> None:
    world = await _World().open()
    # Codex's schedule: edit A is rendering when B is parked, and A's render
    # finishes just before the poll reads A's hold.
    first = await world.park()
    await world.dispatch(first, "First edit")
    second = await world.park()
    await _render_succeeds(world.db, _job(world.db, first)["render_job_id"])

    barrier = _Barrier(world.fake)
    poll = asyncio.create_task(world.chat())
    await barrier.wait_paused()
    await world.dispatch(second, "Second edit")  # the worker answers and saves meanwhile
    barrier.release.set()
    await poll

    session = await load_session(world.db, _PROJECT)
    assert session is not None
    assert has_dangling_call(session) == 0, "the poll overwrote the worker's answer"
    assert _response_payload(session.history[-1])["committed"] is True
    assert [p.job_id for p in session.pending_deliveries] == [second], (
        "the poll dropped the worker's delivery hold"
    )
    assert session.fixes_used == 1


async def test_a_poll_overlapping_a_turn_loses_nothing_the_turn_saved() -> None:
    world = await _World(replies=["Mana javob."]).open()
    await world.delivered_edit("Edited")

    barrier = _Barrier(world.fake)
    poll = asyncio.create_task(world.chat())
    await barrier.wait_paused()
    turn = await world.client.post(
        f"/projects/{_PROJECT}/chat", json={"message": "Savolim bor"}, headers=world.headers
    )
    assert turn.status_code == 200, turn.text
    barrier.release.set()
    await poll

    texts = [m["text"] for m in (await world.chat())["messages"]]
    assert "Savolim bor" in texts and "Mana javob." in texts, (
        "the poll overwrote the turn the user just had"
    )


# ------------------------------------------------------------------------- A3


async def _expect_session_invalid(world: _World, column: str) -> None:
    row = copy.deepcopy(world.session_row())
    holds = copy.deepcopy(world.fake.tables.get("edit_deliveries", []))
    for method, body in (("GET", None), ("POST", {"message": "Salom"})):
        response = await world.client.request(
            method, f"/projects/{_PROJECT}/chat", json=body, headers=world.headers
        )
        assert response.status_code == 409, response.text
        assert response.json()["detail"] == {"reason": "session_invalid", "column": column}
    # Nothing was "repaired": the allowance and the delivery receipts are intact.
    assert world.session_row() == row
    assert world.fake.tables.get("edit_deliveries", []) == holds


async def test_the_old_fixture_format_value_is_409_session_invalid_not_500(
    caplog: pytest.LogCaptureFixture,
) -> None:
    world = await _World().open()
    await world.delivered_edit("Edited")
    world.session_row()["formats_json"] = ["html", "pdf", "pptx"]

    with caplog.at_level(logging.ERROR):
        await _expect_session_invalid(world, "formats_json")
    logged = [r.getMessage() for r in caplog.records if "session_invalid" in r.getMessage()]
    assert any('"column": "formats_json"' in line and _PROJECT in line for line in logged)


async def test_a_session_row_missing_a_column_is_409_session_invalid() -> None:
    world = await _World().open()
    del world.session_row()["package"]

    await _expect_session_invalid(world, "package")


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("formats_json", ["html", 7]),
        (
            "delivery_notes_json",
            [{"kind": "bogus", "job_id": "j", "text": "t", "history_index": 0}],
        ),
        ("history_json", [{"role": "user", "parts": "not-a-list"}]),
        ("pending_action_json", {"fixes": []}),
    ],
)
async def test_bad_array_items_in_a_session_row_are_409_session_invalid(
    column: str, value: Any
) -> None:
    world = await _World().open()
    world.session_row()[column] = value

    await _expect_session_invalid(world, column)


def _job_row(**overrides: Any) -> dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "project_id": _PROJECT,
        "user_id": str(_USER),
        "job_type": "presentation_generation",
        "status": "committed",
        "payload": {},
        "progress": {},
        "attempts": 1,
        "max_attempts": 1,
        "created_at": "2026-01-01T00:00:00+00:00",
        **overrides,
    }


@pytest.mark.parametrize(
    ("row", "child"),
    [
        ({"payload": []}, None),
        ({"progress": ["rendering"]}, None),
        ({}, {"progress": "half-written"}),
        ({}, {"payload": [1, 2]}),
    ],
    ids=["parent_payload_array", "parent_progress_array", "child_progress", "child_payload"],
)
async def test_malformed_parent_and_child_job_rows_are_409_job_data_invalid(
    row: dict[str, Any], child: dict[str, Any] | None
) -> None:
    world = await _World().open()
    jobs = world.fake.tables.setdefault("generation_jobs", [])
    parent = _job_row(**row)
    if child is not None:
        render = _job_row(job_type="presentation_render", status="processing", **child)
        parent["render_job_id"] = render["id"]
        jobs.append(render)
    jobs.append(parent)
    before = copy.deepcopy(jobs)

    for path in (f"/jobs/{parent['id']}", f"/jobs?project_id={_PROJECT}"):
        response = await world.client.get(path, headers=world.headers)
        assert response.status_code == 409, response.text
        assert response.json()["detail"]["reason"] == "job_data_invalid"
    assert jobs == before
