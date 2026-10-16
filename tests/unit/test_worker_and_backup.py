"""Behaviour tests for the worker entrypoint helpers and backup scripts."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest

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
    SlideFix,
    SlideSpec,
)
from packages.platform.exports import renderer_version
from packages.platform.jobs import GenerationJob, JobQueue, JobType
from packages.platform.storage import StorageVerificationError
from packages.sessions_core import FixDispatchResult, FixStatus, PendingActionView
from scripts.backup_db import (
    BACKUP_PREFIX,
    RETENTION_DAYS,
    _dump_key,  # pyright: ignore[reportPrivateUsage]
    _seconds_until_nightly,  # pyright: ignore[reportPrivateUsage]
)
from scripts.worker_run_job import (
    JobRunner,
)
from tests.unit.fake_documents import DocumentRpcEmulator, seed_presentation
from tests.unit.test_database_client import FakeSupabaseClient


def _job(**overrides: Any) -> GenerationJob:
    row: dict[str, Any] = {
        "id": "11111111-1111-1111-1111-111111111111",
        "project_id": "p1",
        "user_id": "u1",
        "job_type": "presentation_generation",
        "status": "processing",
        "payload": {"product_type": "presentation_standard"},
        "attempts": 1,
    }
    row.update(overrides)
    return GenerationJob.model_validate(row)


class _FakeCredits:
    def __init__(self) -> None:
        self.refunds: list[tuple[str, str, int, str]] = []
        self.stamped_jobs: list[str | None] = []

    async def refund(
        self,
        user_id: str,
        project_id: str,
        amount: int,
        reason: str,
        *,
        generation_job_id: str | None = None,
    ) -> None:
        self.refunds.append((user_id, project_id, amount, reason))
        self.stamped_jobs.append(generation_job_id)


class _FakeQueue:
    def __init__(self) -> None:
        self.failed: list[dict[str, Any]] = []
        self.completed: list[str] = []
        self.progress: list[dict[str, Any]] = []
        # False simulates the guarded transition NOT landing (row reaped).
        self.fail_lands = True

    async def fail(
        self, job_id: str, worker_id: str, claim_token: int, *, step: str, message: str
    ) -> bool:
        self.failed.append({"job_id": job_id, "step": step, "message": message})
        return self.fail_lands

    async def complete(
        self, job_id: str, worker_id: str, claim_token: int, progress: dict[str, Any]
    ) -> bool:
        self.completed.append(job_id)
        self.progress.append(progress)
        return True

    async def heartbeat(self, job_id: str, worker_id: str, claim_token: int) -> bool:
        return True

    async def set_progress(
        self, job_id: str, worker_id: str, claim_token: int, progress: dict[str, Any]
    ) -> None:
        self.progress.append(progress)


@pytest.mark.asyncio
async def test_unsupported_job_type_fails_honestly() -> None:
    queue, credits = _FakeQueue(), _FakeCredits()
    runner = _runner(queue, credits)
    job = _job(job_type=JobType.IMAGE_REGEN.value)
    await runner._execute(job)  # pyright: ignore[reportPrivateUsage]
    assert queue.failed[0]["step"] == "dispatch"
    assert "image_regen" in queue.failed[0]["message"]
    # The refund is written by fail_job in the failing transaction, not here.
    assert credits.refunds == []


@pytest.mark.asyncio
async def test_orchestrator_error_lands_step_named_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue, credits = _FakeQueue(), _FakeCredits()
    runner = _runner(queue, credits)

    class _StepError(Exception):
        def __init__(self) -> None:
            super().__init__("editorial blew up")
            self.step = "editorial"
            self.original = RuntimeError("schema cascade")

    async def boom(job: GenerationJob) -> None:
        raise _StepError()

    monkeypatch.setattr(runner, "_run_presentation", boom)
    await runner._execute(_job())  # pyright: ignore[reportPrivateUsage]
    assert queue.failed[0]["step"] == "editorial"
    assert "schema cascade" in queue.failed[0]["message"]
    assert credits.refunds == []


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_lands", [True, False])
async def test_the_worker_never_writes_a_refund_itself(
    monkeypatch: pytest.MonkeyPatch, fail_lands: bool
) -> None:
    """Exactly-once refunds live in the database (fail_job, reap_stale_jobs).

    Whether the worker's fail lands or the reaper got there first, the worker
    process writes no ledger row: a crash between "failed" and "refunded" is
    impossible because there is no such gap in the worker any more.
    """

    queue, credits = _FakeQueue(), _FakeCredits()
    queue.fail_lands = fail_lands
    runner = _runner(queue, credits)

    async def boom(job: GenerationJob) -> None:
        raise RuntimeError("worker woke up late")

    monkeypatch.setattr(runner, "_run_presentation", boom)
    await runner._execute(_job())  # pyright: ignore[reportPrivateUsage]

    assert len(queue.failed) == 1
    assert credits.refunds == []


@pytest.mark.asyncio
async def test_a_failed_paid_job_is_refunded_its_stamped_charge_once(tmp_path: Path) -> None:
    # Through the real queue client and the emulated fail_job: the refund is
    # the amount deducted at enqueue (not today's price), stamped with the job,
    # and a repeated fail of the same job writes nothing more.
    job = _job(payload={"product_type": "presentation_standard", "deducted_amount": 8_000})
    world = _World(tmp_path, job)
    queue = JobQueue(world.db)

    assert await queue.fail(job.id, "w-test", 1, step="render", message="boom") is True
    assert await queue.fail(job.id, "w-test", 1, step="render", message="again") is False

    refunds = [r for r in world.fake.tables["credit_ledger"] if r["action"] == "refund"]
    assert [(r["amount"], r["generation_job_id"]) for r in refunds] == [(8_000, job.id)]
    assert world.job_row(job.id)["status"] == "failed"


@pytest.mark.asyncio
async def test_a_failed_unpaid_edit_is_not_refunded(tmp_path: Path) -> None:
    job = _edit_job({"document_id": "d", "base_revision_id": "r"})
    world = _World(tmp_path, job)

    assert await JobQueue(world.db).fail(job.id, "w-test", 1, step="x", message="y") is True
    assert world.fake.tables.get("credit_ledger", []) == []


@pytest.mark.asyncio
async def test_success_path_never_refunds(monkeypatch: pytest.MonkeyPatch) -> None:
    queue, credits = _FakeQueue(), _FakeCredits()
    runner = _runner(queue, credits)

    async def ok(job: GenerationJob) -> None:
        await queue.complete(job.id, "w-test", job.attempts, {})

    monkeypatch.setattr(runner, "_run_presentation", ok)
    await runner._execute(_job())  # pyright: ignore[reportPrivateUsage]
    assert queue.failed == [] and credits.refunds == []


# ------------------------------------------------------------------- backup


def test_dump_key_is_timestamped_under_backups_prefix() -> None:
    key = _dump_key(datetime(2026, 8, 3, 2, 0, 0, tzinfo=UTC))
    assert key == f"{BACKUP_PREFIX}nashr_20260803T020000Z.dump"


def test_seconds_until_nightly_rolls_to_next_day() -> None:
    before = datetime(2026, 8, 3, 1, 0, 0, tzinfo=UTC)
    after = datetime(2026, 8, 3, 3, 0, 0, tzinfo=UTC)
    assert _seconds_until_nightly(before) == 3600.0
    assert _seconds_until_nightly(after) == 23 * 3600.0


def test_retention_days_is_fourteen() -> None:
    assert RETENTION_DAYS == 14


# ----------------------------------------------------- worker executors (W1-W4)


class _FakeConfig:
    """Only the fields the executors actually read off PlatformConfig."""

    telegram_bot_token = "0:test-token"
    render_max_attempts = 3


class _FakeBotSession:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class _FakeBot:
    """aiogram's Bot minus token validation and the HTTP session."""

    def __init__(self, token: str) -> None:
        self.token = token
        self.session = _FakeBotSession()


class _FakeStorage:
    """Records verified uploads; ``fail`` makes the post-upload verification fail."""

    def __init__(self) -> None:
        self.uploads: list[tuple[str, str, int]] = []
        self.fail = False

    async def put_verified(self, path: Path, key: str, sha256: str, size: int) -> None:
        if self.fail:
            raise StorageVerificationError(f"{key}: stored checksum does not match")
        self.uploads.append((key, sha256, size))


class _FakeBuilt:
    def __init__(self, deck: DeckSpec) -> None:
        self.deck = deck
        self.sources: list[Any] = []


class _FakeOrchestrator:
    """Records what the worker hands the pipeline; renders real temp files."""

    def __init__(self, bot: Any, db: Any, credits: Any, storage: Any, out: Path) -> None:
        self.bot = bot
        self.db = db
        self.out = out
        self.build_kwargs: dict[str, Any] = {}
        self.rendered: list[DeckSpec] = []
        self.deck = _render_deck()
        self.before_commit: Any = None

    async def build_deck(self, **kwargs: Any) -> _FakeBuilt:
        self.build_kwargs = kwargs
        if self.before_commit is not None:
            await self.before_commit()
        return _FakeBuilt(self.deck)

    async def render(self, deck: DeckSpec, formats: list[Any], progress: Any) -> Any:
        from packages.bot.orchestrators.presentation_orchestrator import (
            PresentationRenderResult,
        )

        self.rendered.append(deck)
        await progress("Rendering presentation", 7, 7)
        html = self.out / f"deck-{len(self.rendered)}.html"
        html.write_text(f"<h1>{deck.title}</h1>", encoding="utf-8")
        return PresentationRenderResult(html_path=html)


class _World:
    """A DatabaseClient over the emulated client: project p1 owned by u1, one job row."""

    def __init__(self, tmp_path: Path, job: GenerationJob, *, worker_id: str = "w-test") -> None:
        from packages.platform.config import PlatformConfig
        from packages.platform.database import DatabaseClient
        from packages.platform.document_store import DocumentStore

        self.fake = FakeSupabaseClient()
        self.fake.seed("projects", [{"id": "p1", "user_id": "u1", "type": "presentation"}])
        self.fake.seed("users", [{"id": "u1", "telegram_id": 555}])
        self.fake.seed(
            "generation_jobs",
            [
                {
                    **job.model_dump(mode="json"),
                    "worker_id": worker_id,
                    "status": "processing",
                    "heartbeat_at": "2026-01-01T00:00:00+00:00",
                }
            ],
        )
        cfg = PlatformConfig(
            supabase_url="https://x.supabase.co",
            supabase_service_key="k",
            telegram_bot_token="t",
        )
        self.db = DatabaseClient(cfg, client=cast(Any, self.fake))
        self.store = DocumentStore(self.db)
        self.storage = _FakeStorage()
        self.queue = _FakeQueue()
        self.credits = _FakeCredits()
        self.tmp = tmp_path
        self.built: list[_FakeOrchestrator] = []
        # Runs inside build_deck: simulates another writer moving the head mid-run.
        self.race: Any = None

    def runner(self) -> JobRunner:
        return JobRunner(
            cast(Any, _FakeConfig()),
            self.db,
            cast(Any, self.queue),
            cast(Any, self.credits),
            cast(Any, self.storage),
            "w-test",
        )

    def patch(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _make(*, bot: Any, db: Any, credits: Any, storage: Any) -> _FakeOrchestrator:
            orchestrator = _FakeOrchestrator(bot, db, credits, storage, self.tmp)
            orchestrator.before_commit = self.race
            self.built.append(orchestrator)
            return orchestrator

        monkeypatch.setattr("aiogram.Bot", _FakeBot)
        monkeypatch.setattr(
            "packages.bot.orchestrators.presentation_orchestrator.PresentationOrchestrator",
            _make,
        )

    def seed_revision(self, title: str) -> tuple[str, str]:
        """Commit a deck titled ``title`` as the new head; (document_id, revision_id)."""

        documents = self.fake.tables.get("documents")
        if not documents:
            return seed_presentation(
                self.fake.tables,
                project_id="p1",
                content=_render_deck(title).model_dump(mode="json"),
            )
        document = documents[0]
        result = DocumentRpcEmulator(self.fake.tables).commit_revision(
            {
                "p_document_id": document["id"],
                "p_base_revision_id": document["head_revision_id"],
                "p_content": _render_deck(title).model_dump(mode="json"),
                "p_kind": "import",
                "p_schema_version": 1,
                "p_actor": "system:migration-016",
                "p_idempotency_key": f"seed-{title}",
            }
        )
        return str(document["id"]), str(result[0]["revision_id"])

    def exports(self) -> list[dict[str, Any]]:
        return self.fake.tables.get("revision_exports", [])

    def job_row(self, job_id: str) -> dict[str, Any]:
        return next(r for r in self.fake.tables["generation_jobs"] if r["id"] == job_id)

    def queued_renders(self) -> list[dict[str, Any]]:
        return [
            row
            for row in self.fake.tables["generation_jobs"]
            if row.get("job_type") == "presentation_render" and row.get("status") == "queued"
        ]

    def head(self) -> str | None:
        documents = self.fake.tables.get("documents") or [{}]
        return documents[0].get("head_revision_id")


def _render_job(revision_id: str) -> GenerationJob:
    return _job(
        job_type=JobType.PRESENTATION_RENDER.value,
        payload={
            "revision_id": revision_id,
            "renderer_version": renderer_version(),
            "formats": ["html"],
        },
    )


def _runner(queue: _FakeQueue, credits: _FakeCredits) -> JobRunner:
    return JobRunner(
        cast(Any, object()),
        cast(Any, object()),
        cast(Any, queue),
        cast(Any, credits),
        cast(Any, object()),
        "w-test",
    )


def _patch_dispatch_fix(
    monkeypatch: pytest.MonkeyPatch, result: FixDispatchResult
) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    async def _dispatch(**kwargs: Any) -> FixDispatchResult:
        calls.append(kwargs)
        return result

    monkeypatch.setattr("packages.sessions_core.dispatch_fix", _dispatch)
    return calls


def _patch_pending(monkeypatch: pytest.MonkeyPatch, pending: PendingActionView | None) -> None:
    async def _park(db: Any, project_id: str) -> PendingActionView | None:
        return pending

    monkeypatch.setattr("packages.sessions_core.park_pending_for_apply", _park)


def _edit_job(payload: dict[str, Any]) -> GenerationJob:
    return _job(job_type=JobType.PRESENTATION_EDIT.value, payload=payload)


def _render_deck(title: str = "Direct design") -> DeckSpec:
    return DeckSpec(
        project_id="p1",
        title=title,
        design=DesignDirectionSpec(
            mood=PresentationMood.CLEAN_PROFESSIONAL,
            palette=ColorPalette(
                background="#FFFCF0",
                surface="#F2F0E5",
                text="#100F0F",
                accent="#205EA6",
                text_secondary="#575653",
            ),
            heading_font="Source Serif 4",
            body_font="Inter",
            image_style_prefix="editorial photograph, ",
            background_treatment=BackgroundTreatment.LIGHT,
        ),
        interview=PresentationInterviewAnswers(audience=AudienceType.UNDERGRADUATE),
        slides=[
            SlideSpec(
                slide_index=0,
                slide_type=SlideType.TITLE_HERO,
                content=SlideContent(title="Edited without a model"),
            )
        ],
    )


@pytest.mark.asyncio
async def test_render_of_an_older_revision_publishes_only_that_revisions_exports(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Bug (a), worker side: the render job used to overwrite the project's stable
    # export keys and the decks row with the older revision. Now its exports are
    # keyed by that revision, and the head is untouched.
    _doc, older = (None, None)
    job = _render_job("placeholder")
    world = _World(tmp_path, job)
    document_id, older = world.seed_revision("Older")
    _doc, newer = world.seed_revision("Newer")
    job = _render_job(older)
    world.fake.tables["generation_jobs"][0]["payload"] = job.payload
    world.patch(monkeypatch)

    await world.runner()._run_presentation_render(job)  # pyright: ignore[reportPrivateUsage]

    assert world.head() == newer
    assert [row["revision_id"] for row in world.exports()] == [older]
    key = world.exports()[0]["storage_key"]
    assert key.startswith(f"exports/{document_id}/{older}/{renderer_version()}/html/")
    assert world.storage.uploads[0][0] == key
    assert world.built[0].rendered[0].title == "Older"
    assert world.queue.completed == [job.id]
    assert world.queue.progress[-1]["outcome"] == "rendered"
    assert world.credits.refunds == []


@pytest.mark.asyncio
async def test_a_retried_render_publishes_only_formats_not_yet_registered(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # The first render registered html; a recovery render of the same revision
    # renders and uploads nothing more, and completes.
    world = _World(tmp_path, _render_job("x"))
    _doc, revision = world.seed_revision("Deck")
    job = _render_job(revision)
    world.fake.tables["generation_jobs"][0]["payload"] = job.payload
    world.patch(monkeypatch)
    await world.runner()._run_presentation_render(job)  # pyright: ignore[reportPrivateUsage]
    first_upload = list(world.storage.uploads)

    row = world.job_row(job.id)
    row.update(status="processing", worker_id="w-test", attempts=2)
    retry = job.model_copy(update={"attempts": 2})
    await world.runner()._run_presentation_render(retry)  # pyright: ignore[reportPrivateUsage]

    assert len(world.exports()) == 1
    assert world.storage.uploads == first_upload
    assert len(world.built) == 1  # the retry built no renderer at all
    assert world.queue.progress[-1]["rendered_formats"] == []
    assert world.queue.completed == [job.id, job.id]


@pytest.mark.asyncio
async def test_a_render_requested_for_another_renderer_fails_before_rendering(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    world = _World(tmp_path, _render_job("x"))
    _doc, revision = world.seed_revision("Deck")
    job = _render_job(revision)
    job.payload["renderer_version"] = "pw-0000000000000000"
    world.fake.tables["generation_jobs"][0]["payload"] = job.payload
    world.patch(monkeypatch)

    with pytest.raises(RuntimeError, match="requested for renderer pw-0000000000000000"):
        await world.runner()._run_presentation_render(job)  # pyright: ignore[reportPrivateUsage]
    assert world.exports() == [] and world.built == []


@pytest.mark.asyncio
async def test_render_with_a_lost_claim_registers_nothing_and_never_completes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # (f) The row was reaped and re-claimed by another worker while this one
    # rendered: register_export refuses, the job is not completed by us, and no
    # refund fires from this worker (the guarded fail does not land).
    world = _World(tmp_path, _render_job("x"), worker_id="someone-else")
    _doc, revision = world.seed_revision("Deck")
    job = _render_job(revision)
    world.fake.tables["generation_jobs"][0]["payload"] = job.payload
    world.queue.fail_lands = False
    world.patch(monkeypatch)

    await world.runner()._execute(job)  # pyright: ignore[reportPrivateUsage]

    assert world.exports() == []
    assert world.queue.completed == []
    assert "claim_lost" in world.queue.failed[0]["message"]
    assert world.credits.refunds == []


@pytest.mark.asyncio
async def test_render_job_cannot_publish_a_revision_of_another_project(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # (g) A render job for revision X can never register exports for a revision
    # it does not target: one from another project is not even loaded.
    world = _World(tmp_path, _render_job("x"))
    world.fake.tables["projects"].append({"id": "p2", "user_id": "u1", "type": "presentation"})
    _doc, foreign = seed_presentation(
        world.fake.tables, project_id="p2", content=_render_deck("Other").model_dump(mode="json")
    )
    job = _render_job(foreign)
    world.patch(monkeypatch)

    await world.runner()._execute(job)  # pyright: ignore[reportPrivateUsage]

    assert world.exports() == []
    assert "not in this project" in world.queue.failed[0]["message"]


@pytest.mark.asyncio
async def test_upload_verification_failure_fails_the_render_job(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    world = _World(tmp_path, _render_job("x"))
    _doc, revision = world.seed_revision("Deck")
    job = _render_job(revision)
    world.fake.tables["generation_jobs"][0]["payload"] = job.payload
    world.storage.fail = True
    world.patch(monkeypatch)

    await world.runner()._execute(job)  # pyright: ignore[reportPrivateUsage]

    assert world.exports() == []
    assert world.queue.completed == []
    assert world.queue.failed[0]["step"] == "publish"
    assert "checksum" in world.queue.failed[0]["message"]


@pytest.mark.asyncio
async def test_generation_commits_with_its_job_queues_the_render_and_opens_the_session(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    job = _job(payload={"product_type": "presentation_standard", "formats": ["html"]})
    world = _World(tmp_path, job)
    world.patch(monkeypatch)
    sessions: list[dict[str, Any]] = []

    async def _session(*_args: Any, **kwargs: Any) -> None:
        sessions.append(kwargs)

    monkeypatch.setattr("packages.bot.sessions.store.create_session", _session)

    await world.runner()._run_presentation(job)  # pyright: ignore[reportPrivateUsage]

    head = world.head()
    assert head is not None
    revision = next(r for r in world.fake.tables["document_revisions"] if r["id"] == head)
    assert revision["kind"] == "generation" and revision["actor"] == f"worker:{job.id}"
    # The commit settled the job in the same step: 'committed' until the queued
    # render publishes (B1-FIX2), linked to that render.
    row = world.job_row(job.id)
    assert row["status"] == "committed" and row["progress"]["outcome"] == "committed"
    assert world.exports() == [] and world.built[0].rendered == []
    renders = world.queued_renders()
    assert len(renders) == 1
    assert renders[0]["payload"]["revision_id"] == head
    assert renders[0]["payload"]["formats"] == ["html"]
    assert renders[0]["payload"]["renderer_version"] == renderer_version()
    assert renders[0]["max_attempts"] == 3  # PlatformConfig.render_max_attempts
    assert row["render_job_id"] == renders[0]["id"]
    assert sessions[0]["revision_id"] == head
    assert world.queue.completed == [] and world.queue.failed == []


@pytest.mark.asyncio
async def test_generation_racing_a_new_head_becomes_a_proposal_not_an_overwrite(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # A head appeared while the deck was generated. The paid output is kept as a
    # proposal for the owner; the other writer's head is not overwritten, nothing
    # is rendered, and the job completes (no refund: the work was delivered).
    job = _job(payload={"product_type": "presentation_standard", "formats": ["html"]})
    world = _World(tmp_path, job)
    raced: list[str] = []

    async def _another_writer() -> None:
        raced.append(world.seed_revision("Someone else")[1])

    world.race = _another_writer
    world.patch(monkeypatch)

    await world.runner()._run_presentation(job)  # pyright: ignore[reportPrivateUsage]

    assert world.head() == raced[0]
    proposals = world.fake.tables["revision_proposals"]
    assert len(proposals) == 1 and proposals[0]["kind"] == "regeneration"
    assert proposals[0]["source_job_id"] == job.id
    assert proposals[0]["base_revision_id"] is None
    assert world.exports() == [] and world.queued_renders() == []
    assert world.built[0].rendered == []
    row = world.job_row(job.id)
    assert row["status"] == "completed" and row["progress"]["outcome"] == "proposed"
    assert world.queue.failed == []
    assert world.credits.refunds == []


@pytest.mark.asyncio
async def test_regeneration_commits_against_the_head_it_started_from(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    job = _job(payload={"product_type": "presentation_standard", "formats": ["html"]})
    world = _World(tmp_path, job)
    _doc, first = world.seed_revision("First generation")
    world.patch(monkeypatch)

    async def _session(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr("packages.bot.sessions.store.create_session", _session)

    await world.runner()._run_presentation(job)  # pyright: ignore[reportPrivateUsage]

    head = world.head()
    revision = next(r for r in world.fake.tables["document_revisions"] if r["id"] == head)
    assert revision["kind"] == "regeneration" and revision["parent_revision_id"] == first


@pytest.mark.asyncio
async def test_presentation_payload_topic_reaches_the_pipeline_verbatim(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """W4: EnqueueRequest.topic -> payload["topic"] -> build_deck(topic=...)."""

    async def _no_session(*args: Any, **kwargs: Any) -> None:
        return None

    monkeypatch.setattr("packages.bot.sessions.store.create_session", _no_session)

    async def topic_seen_for(payload: dict[str, Any]) -> object:
        job = _job(payload=payload)
        world = _World(tmp_path, job)
        world.patch(monkeypatch)
        await world.runner()._run_presentation(job)  # pyright: ignore[reportPrivateUsage]
        return world.built[0].build_kwargs["topic"]

    assert await topic_seen_for({"topic": "Suv resurslari"}) == "Suv resurslari"
    assert await topic_seen_for({}) is None
    assert await topic_seen_for({"topic": "   "}) is None


@pytest.mark.asyncio
async def test_failed_edit_refunds_nothing_but_failed_generation_does(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """W1: neither job type is refunded by the worker; fail_job settles paid ones."""

    priced = {"product_type": "presentation_standard"}

    async def boom(job: GenerationJob) -> None:
        raise RuntimeError("render died")

    edit_queue, edit_credits = _FakeQueue(), _FakeCredits()
    edit_runner = _runner(edit_queue, edit_credits)
    monkeypatch.setattr(edit_runner, "_run_presentation_edit", boom)
    await edit_runner._execute(_edit_job(priced))  # pyright: ignore[reportPrivateUsage]
    assert len(edit_queue.failed) == 1
    assert "render died" in edit_queue.failed[0]["message"]
    assert edit_credits.refunds == []

    gen_queue, gen_credits = _FakeQueue(), _FakeCredits()
    gen_runner = _runner(gen_queue, gen_credits)
    monkeypatch.setattr(gen_runner, "_run_presentation", boom)
    await gen_runner._execute(_job(payload=priced))  # pyright: ignore[reportPrivateUsage]
    assert len(gen_queue.failed) == 1
    assert gen_credits.refunds == []


def test_executor_for_routes_by_job_type() -> None:
    runner = _runner(_FakeQueue(), _FakeCredits())
    executor_for = runner._executor_for  # pyright: ignore[reportPrivateUsage]
    assert executor_for(JobType.PRESENTATION_GENERATION) == runner._run_presentation  # pyright: ignore[reportPrivateUsage]
    assert executor_for(JobType.PRESENTATION_EDIT) == runner._run_presentation_edit  # pyright: ignore[reportPrivateUsage]
    assert executor_for(JobType.PRESENTATION_RENDER) == runner._run_presentation_render  # pyright: ignore[reportPrivateUsage]
    assert executor_for(JobType.EXPORT) is None
    assert executor_for(JobType.ARTICLE_GENERATION) is None


@pytest.mark.asyncio
async def test_export_job_has_no_executor_and_is_failed() -> None:
    queue, credits = _FakeQueue(), _FakeCredits()
    runner = _runner(queue, credits)
    await runner._execute(_job(job_type=JobType.EXPORT.value))  # pyright: ignore[reportPrivateUsage]
    assert queue.failed[0]["step"] == "dispatch"
    assert "export" in queue.failed[0]["message"]
    assert credits.refunds == []


# The parked call an edit job answers (B1-FIX4): the API stamps both ids.
_SESSION_ID = "5e551017-0000-4000-8000-000000000001"
_OPERATION_ID = "0be7a710-0000-4000-8000-000000000002"


def _edit_payload(**extra: Any) -> dict[str, Any]:
    return {
        "document_id": "document-1",
        "base_revision_id": "revision-1",
        "session_id": _SESSION_ID,
        "operation_id": _OPERATION_ID,
        **extra,
    }


@pytest.mark.asyncio
async def test_edit_inline_fixes_reach_dispatch_against_the_stamped_base(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    job = _edit_job(
        _edit_payload(
            fixes=[
                {"slide_id": "s2", "instruction": "tighten the title"},
                {"slide_id": "s5", "instruction": "drop the fourth bullet"},
            ],
            call_count=2,
        )
    )
    world = _World(tmp_path, job)
    world.patch(monkeypatch)
    calls = _patch_dispatch_fix(
        monkeypatch,
        FixDispatchResult(FixStatus.DELIVERED, slides_changed=2, revision_id="revision-2"),
    )

    await world.runner()._run_presentation_edit(job)  # pyright: ignore[reportPrivateUsage]

    kwargs = calls[0]
    assert kwargs["runner"] is world.built[0]
    assert kwargs["db"] is world.db
    assert kwargs["project_id"] == "p1"
    assert kwargs["call_count"] == 2
    assert kwargs["base_revision_id"] == "revision-1"
    assert (kwargs["session_id"], kwargs["operation_id"]) == (_SESSION_ID, _OPERATION_ID)
    fixes = cast(list[SlideFix], kwargs["fixes"])
    assert [f.slide_id for f in fixes] == ["s2", "s5"]
    # A delivered edit was completed by its commit (finish_generation_job), so
    # the worker neither completes nor fails the row afterwards.
    assert world.queue.completed == [] and world.queue.failed == []
    assert cast(_FakeBot, world.built[0].bot).session.closed is True


@pytest.mark.asyncio
async def test_edit_commit_callback_commits_an_ai_edit_as_this_worker(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    job = _edit_job(_edit_payload(fixes=[{"slide_id": "s1", "instruction": "x"}]))
    world = _World(tmp_path, job)
    document_id, base = world.seed_revision("Before")
    job.payload.update(document_id=document_id, base_revision_id=base)
    # An edit is parked on a session, whose allowance its commit holds a fix of.
    world.fake.tables.setdefault("brain_sessions", []).append(
        {
            "id": _SESSION_ID,
            "project_id": "p1",
            "version": 3,
            "parked_operation_id": _OPERATION_ID,
        }
    )
    world.patch(monkeypatch)
    edited = _render_deck("After the AI edit")

    seen: dict[str, Any] = {}

    async def _dispatch(**kwargs: Any) -> FixDispatchResult:
        outcome = await kwargs["commit"](edited, kwargs["base_revision_id"])
        seen.update(
            deliver=kwargs["deliver"], delivery_job_id=kwargs["delivery_job_id"], outcome=outcome
        )
        return FixDispatchResult(FixStatus.COMMITTED, revision_id=outcome.revision_id)

    monkeypatch.setattr("packages.sessions_core.dispatch_fix", _dispatch)

    await world.runner()._run_presentation_edit(job)  # pyright: ignore[reportPrivateUsage]

    head = world.head()
    revision = next(r for r in world.fake.tables["document_revisions"] if r["id"] == head)
    assert revision["kind"] == "ai_edit" and revision["actor"] == f"worker:{job.id}"
    assert revision["parent_revision_id"] == base
    assert revision["idempotency_key"] == f"chat-edit:{job.id}"
    # The worker renders nothing in-process: the job's own render delivers the
    # edit, so the session holds the fix until that render settles the job.
    assert seen["deliver"] is None and seen["delivery_job_id"] == job.id
    row = world.job_row(job.id)
    assert row["status"] == "committed" == seen["outcome"].job_status
    assert world.exports() == [] and world.built[0].rendered == []
    renders = world.queued_renders()
    assert [r["payload"]["revision_id"] for r in renders] == [head]
    assert renders[0]["payload"]["formats"] == ["html", "pdf", "pptx"]
    assert row["render_job_id"] == renders[0]["id"] == seen["outcome"].render_job_id
    assert world.queue.completed == [] and world.queue.failed == []
    # The hold was recorded with the commit, not by a later session write.
    [hold] = world.fake.tables["edit_deliveries"]
    assert (hold["job_id"], hold["session_id"], hold["status"]) == (
        job.id,
        _SESSION_ID,
        "reserved",
    )


@pytest.mark.asyncio
async def test_edit_without_an_operation_identity_is_refused() -> None:
    runner = _runner(_FakeQueue(), _FakeCredits())
    payload = _edit_payload(fixes=[{"slide_id": "s1", "instruction": "x"}])
    del payload["operation_id"]
    with pytest.raises(RuntimeError, match="no operation identity"):
        await runner._run_presentation_edit(_edit_job(payload))  # pyright: ignore[reportPrivateUsage]


@pytest.mark.asyncio
async def test_an_edit_that_became_a_proposal_completes_the_job(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    job = _edit_job(_edit_payload(fixes=[{"slide_id": "s1", "instruction": "x"}]))
    world = _World(tmp_path, job)
    world.patch(monkeypatch)
    _patch_dispatch_fix(
        monkeypatch, FixDispatchResult(FixStatus.PROPOSED, proposal_id="proposal-1")
    )

    await world.runner()._run_presentation_edit(job)  # pyright: ignore[reportPrivateUsage]

    # The proposal's commit completed the job; the worker leaves the row alone.
    assert world.queue.completed == [] and world.queue.failed == []


@pytest.mark.asyncio
async def test_edit_from_pending_uses_the_parked_batch_and_its_call_count(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The parked action is the source of truth; a stale payload cannot override it."""

    job = _edit_job(
        _edit_payload(
            from_pending=True, call_count=2, fixes=[{"slide_id": "s1", "instruction": "ignored"}]
        )
    )
    world = _World(tmp_path, job)
    world.patch(monkeypatch)
    calls = _patch_dispatch_fix(monkeypatch, FixDispatchResult(FixStatus.DELIVERED))
    _patch_pending(
        monkeypatch,
        PendingActionView(
            reason="approved",
            fixes=(SlideFix(slide_id="s9", instruction="make it warmer"),),
            call_count=7,
        ),
    )

    await world.runner()._run_presentation_edit(job)  # pyright: ignore[reportPrivateUsage]

    kwargs = calls[0]
    assert [f.slide_id for f in cast(list[SlideFix], kwargs["fixes"])] == ["s9"]
    assert kwargs["call_count"] == 7
    assert world.queue.failed == []


@pytest.mark.asyncio
async def test_edit_from_pending_with_nothing_parked_fails_without_refund(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue, credits = _FakeQueue(), _FakeCredits()
    _patch_pending(monkeypatch, None)
    runner = _runner(queue, credits)
    job = _edit_job({"from_pending": True, "product_type": "presentation_standard"})

    with pytest.raises(RuntimeError, match="no longer parked"):
        await runner._run_presentation_edit(job)  # pyright: ignore[reportPrivateUsage]

    await runner._execute(job)  # pyright: ignore[reportPrivateUsage]
    assert queue.failed[0]["step"] == "pipeline"
    assert credits.refunds == []


@pytest.mark.asyncio
async def test_edit_without_a_base_revision_is_refused() -> None:
    runner = _runner(_FakeQueue(), _FakeCredits())
    with pytest.raises(RuntimeError, match="no document revision"):
        await runner._run_presentation_edit(  # pyright: ignore[reportPrivateUsage]
            _edit_job({"fixes": [{"slide_id": "s1", "instruction": "x"}]})
        )


@pytest.mark.asyncio
async def test_edit_without_usable_fixes_raises() -> None:
    queue, credits = _FakeQueue(), _FakeCredits()
    runner = _runner(queue, credits)

    with pytest.raises(RuntimeError, match="carries no fixes"):
        await runner._run_presentation_edit(_edit_job({}))  # pyright: ignore[reportPrivateUsage]
    with pytest.raises(RuntimeError, match="carries no fixes"):
        await runner._run_presentation_edit(_edit_job({"fixes": []}))  # pyright: ignore[reportPrivateUsage]
    with pytest.raises(RuntimeError, match="malformed fix entry"):
        await runner._run_presentation_edit(_edit_job({"fixes": ["s1", 7]}))  # pyright: ignore[reportPrivateUsage]
    # A MIXED batch is the sharp case: filtering the junk out would apply half of
    # an approved batch and report success. One bad entry fails the whole job.
    with pytest.raises(RuntimeError, match="malformed fix entry"):
        await runner._run_presentation_edit(  # pyright: ignore[reportPrivateUsage]
            _edit_job({"fixes": [{"slide_id": "s2", "instruction": "fix the date"}, "junk"]})
        )
    assert queue.completed == [] and queue.failed == []


@pytest.mark.asyncio
async def test_edit_that_delivers_nothing_fails_the_row_at_apply_fixes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """dispatch_fix already answered the parked call; the row is all that is left to state."""

    job = _edit_job(_edit_payload(fixes=[{"slide_id": "s3", "instruction": "swap the image"}]))
    world = _World(tmp_path, job)
    world.patch(monkeypatch)
    _patch_dispatch_fix(
        monkeypatch, FixDispatchResult(FixStatus.EXHAUSTED, reason="fixes_exhausted")
    )

    await world.runner()._run_presentation_edit(job)  # pyright: ignore[reportPrivateUsage]

    assert world.queue.completed == []
    assert world.queue.failed == [
        {"job_id": job.id, "step": "apply_fixes", "message": "fixes_exhausted"}
    ]
    assert world.credits.refunds == []
    assert cast(_FakeBot, world.built[0].bot).session.closed is True
