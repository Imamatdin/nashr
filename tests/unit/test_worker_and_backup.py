"""Behaviour tests for the worker entrypoint helpers and backup scripts."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

import pytest

from packages.core.models.presentation import SlideFix
from packages.platform.credits import CreditLedger
from packages.platform.jobs import GenerationJob, JobType
from packages.sessions_core import FixDispatchResult, PendingActionView
from scripts.backup_db import (
    BACKUP_PREFIX,
    RETENTION_DAYS,
    _dump_key,  # pyright: ignore[reportPrivateUsage]
    _seconds_until_nightly,  # pyright: ignore[reportPrivateUsage]
)
from scripts.worker_run_job import (
    JobRunner,
    _refund_amount,  # pyright: ignore[reportPrivateUsage]
    _refund_job,  # pyright: ignore[reportPrivateUsage]
)


def _job(**overrides: Any) -> GenerationJob:
    row: dict[str, Any] = {
        "id": "11111111-1111-1111-1111-111111111111",
        "project_id": "p1",
        "user_id": "u1",
        "job_type": "presentation_generation",
        "status": "processing",
        "payload": {"product_type": "presentation_standard"},
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
        self,
        job_id: str,
        worker_id: str,
        *,
        step: str,
        message: str,
        telemetry: dict[str, Any] | None = None,
    ) -> bool:
        self.failed.append({"job_id": job_id, "step": step, "message": message})
        return self.fail_lands

    async def complete(self, job_id: str, worker_id: str, telemetry: dict[str, Any]) -> bool:
        self.completed.append(job_id)
        return True

    async def heartbeat(self, job_id: str, worker_id: str) -> bool:
        return True

    async def set_progress(self, job_id: str, worker_id: str, progress: dict[str, Any]) -> None:
        self.progress.append(progress)


def test_refund_amount_reads_product_type_pricing() -> None:
    assert (
        _refund_amount({"product_type": "presentation_standard"})
        == (CreditLedger.PRICING["presentation_standard"])
    )
    assert _refund_amount({"product_type": "nonsense"}) is None
    assert _refund_amount({}) is None


def test_refund_amount_prefers_recorded_deduction_over_pricing() -> None:
    # F3: refund what was actually charged, not the current price.
    payload = {"product_type": "presentation_standard", "deducted_amount": 8_000}
    assert _refund_amount(payload) == 8_000
    assert (
        _refund_amount({"deducted_amount": 0, "product_type": "presentation_standard"})
        == (CreditLedger.PRICING["presentation_standard"])
    )


@pytest.mark.asyncio
async def test_refund_job_writes_priced_refund() -> None:
    credits = _FakeCredits()
    job = _job()
    await _refund_job(cast(Any, credits), job, "refund:job:x:render")
    assert credits.refunds == [("u1", "p1", 10_000, "refund:job:x:render")]
    # The refund row is stamped with the job it settles: JobView.refunded is
    # read off this link, so an unstamped refund would make a real refund
    # invisible to the user it belongs to.
    assert credits.stamped_jobs == [job.id]


@pytest.mark.asyncio
async def test_refund_job_skips_unpriced_payload() -> None:
    credits = _FakeCredits()
    await _refund_job(cast(Any, credits), _job(payload={}), "refund:job:x:render")
    assert credits.refunds == []


def _runner(queue: _FakeQueue, credits: _FakeCredits) -> JobRunner:
    return JobRunner(
        cast(Any, object()),
        cast(Any, object()),
        cast(Any, queue),
        cast(Any, credits),
        cast(Any, object()),
        "w-test",
    )


@pytest.mark.asyncio
async def test_unsupported_job_type_fails_honestly_and_refunds() -> None:
    queue, credits = _FakeQueue(), _FakeCredits()
    runner = _runner(queue, credits)
    job = _job(job_type=JobType.IMAGE_REGEN.value)
    await runner._execute(job)  # pyright: ignore[reportPrivateUsage]
    assert queue.failed[0]["step"] == "dispatch"
    assert "image_regen" in queue.failed[0]["message"]
    assert len(credits.refunds) == 1


@pytest.mark.asyncio
async def test_orchestrator_error_lands_step_named_failure_and_refund(
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
    assert credits.refunds[0][3].endswith(":editorial")


@pytest.mark.asyncio
async def test_reaped_then_worker_fails_produces_exactly_one_refund(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F1: a stalled-but-alive worker racing the reaper must not double-refund.

    Sequence: the reaper already took the row (and refunded it); the worker's
    pipeline then raises and calls fail(), whose guarded transition does NOT
    land. The worker's refund must be suppressed — the ledger ends with
    exactly the reaper's single refund row.
    """

    queue, credits = _FakeQueue(), _FakeCredits()
    # The reaper's refund has already been written.
    await credits.refund("u1", "p1", 10_000, "refund:job:x:reaped")
    queue.fail_lands = False
    runner = _runner(queue, credits)

    async def boom(job: GenerationJob) -> None:
        raise RuntimeError("worker woke up late")

    monkeypatch.setattr(runner, "_run_presentation", boom)
    await runner._execute(_job())  # pyright: ignore[reportPrivateUsage]

    assert len(queue.failed) == 1  # the attempt was made...
    assert len(credits.refunds) == 1  # ...but only the reaper's refund exists
    assert credits.refunds[0][3] == "refund:job:x:reaped"


@pytest.mark.asyncio
async def test_unsupported_type_refund_also_gated_on_fail_landing() -> None:
    queue, credits = _FakeQueue(), _FakeCredits()
    queue.fail_lands = False
    runner = _runner(queue, credits)
    await runner._execute(_job(job_type=JobType.IMAGE_REGEN.value))  # pyright: ignore[reportPrivateUsage]
    assert credits.refunds == []


@pytest.mark.asyncio
async def test_success_path_never_refunds(monkeypatch: pytest.MonkeyPatch) -> None:
    queue, credits = _FakeQueue(), _FakeCredits()
    runner = _runner(queue, credits)

    async def ok(job: GenerationJob) -> None:
        await queue.complete(job.id, "w-test", telemetry={})

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
    """Only the field the executors actually read off PlatformConfig."""

    telegram_bot_token = "0:test-token"


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


class _FakeRender:
    def by_extension(self) -> dict[str, str]:
        return {"html": "/out/deck.html"}


class _FakePipelineResult:
    def __init__(self) -> None:
        self.render = _FakeRender()
        self.sources: list[Any] = []


class _FakeOrchestrator:
    """Records the kwargs the worker hands the pipeline."""

    def __init__(self, bot: Any, db: Any, credits: Any, storage: Any) -> None:
        self.bot = bot
        self.db = db
        self.pipeline_kwargs: dict[str, Any] = {}

    async def run_full_pipeline(self, **kwargs: Any) -> _FakePipelineResult:
        self.pipeline_kwargs = kwargs
        return _FakePipelineResult()


def _wired_runner(queue: _FakeQueue, credits: _FakeCredits, db: Any) -> JobRunner:
    """A runner whose config carries a token, for the paths that build a Bot."""

    return JobRunner(
        cast(Any, _FakeConfig()),
        db,
        cast(Any, queue),
        cast(Any, credits),
        cast(Any, object()),
        "w-test",
    )


def _patch_bot_and_orchestrator(monkeypatch: pytest.MonkeyPatch) -> list[_FakeOrchestrator]:
    built: list[_FakeOrchestrator] = []

    def _make(*, bot: Any, db: Any, credits: Any, storage: Any) -> _FakeOrchestrator:
        orchestrator = _FakeOrchestrator(bot, db, credits, storage)
        built.append(orchestrator)
        return orchestrator

    monkeypatch.setattr("aiogram.Bot", _FakeBot)
    monkeypatch.setattr(
        "packages.bot.orchestrators.presentation_orchestrator.PresentationOrchestrator",
        _make,
    )
    return built


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


@pytest.mark.asyncio
async def test_failed_edit_refunds_nothing_but_failed_generation_does(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """W1: the refundable gate must discriminate by job type, not by payload.

    Both jobs below carry the SAME priced payload, so the only thing standing
    between a failure and a refund is ``job.job_type is PRESENTATION_GENERATION``.
    An edit spends the tier's fix allowance, not money — nothing was deducted
    when it was enqueued, so refunding one would mint credit out of a failure.
    """

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
    assert len(gen_credits.refunds) == 1


def test_executor_for_routes_by_job_type() -> None:
    runner = _runner(_FakeQueue(), _FakeCredits())
    executor_for = runner._executor_for  # pyright: ignore[reportPrivateUsage]
    assert executor_for(JobType.PRESENTATION_GENERATION) == runner._run_presentation  # pyright: ignore[reportPrivateUsage]
    assert executor_for(JobType.PRESENTATION_EDIT) == runner._run_presentation_edit  # pyright: ignore[reportPrivateUsage]
    assert executor_for(JobType.EXPORT) is None
    assert executor_for(JobType.ARTICLE_GENERATION) is None


@pytest.mark.asyncio
async def test_export_job_has_no_executor_and_is_failed_with_refund() -> None:
    queue, credits = _FakeQueue(), _FakeCredits()
    runner = _runner(queue, credits)
    await runner._execute(_job(job_type=JobType.EXPORT.value))  # pyright: ignore[reportPrivateUsage]
    assert queue.failed[0]["step"] == "dispatch"
    assert "export" in queue.failed[0]["message"]
    assert len(credits.refunds) == 1


@pytest.mark.asyncio
async def test_edit_inline_fixes_reach_dispatch_and_complete_the_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue, credits = _FakeQueue(), _FakeCredits()
    db = object()
    built = _patch_bot_and_orchestrator(monkeypatch)
    calls = _patch_dispatch_fix(monkeypatch, FixDispatchResult(True, slides_changed=2))
    runner = _wired_runner(queue, credits, db)
    job = _edit_job(
        {
            "fixes": [
                {"slide_id": "s2", "instruction": "tighten the title"},
                {"slide_id": "s5", "instruction": "drop the fourth bullet"},
            ],
            "call_count": 2,
        }
    )

    await runner._run_presentation_edit(job)  # pyright: ignore[reportPrivateUsage]

    assert len(calls) == 1
    kwargs = calls[0]
    assert kwargs["runner"] is built[0]
    assert kwargs["db"] is db
    assert kwargs["project_id"] == "p1"
    assert kwargs["call_count"] == 2
    fixes = cast(list[SlideFix], kwargs["fixes"])
    assert [f.slide_id for f in fixes] == ["s2", "s5"]
    assert all(isinstance(f, SlideFix) for f in fixes)
    assert queue.completed == [job.id]
    assert queue.failed == []
    assert cast(_FakeBot, built[0].bot).session.closed is True


@pytest.mark.asyncio
async def test_edit_from_pending_uses_the_parked_batch_and_its_call_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The parked action is the source of truth; a stale payload cannot override it."""

    queue, credits = _FakeQueue(), _FakeCredits()
    _patch_bot_and_orchestrator(monkeypatch)
    calls = _patch_dispatch_fix(monkeypatch, FixDispatchResult(True, slides_changed=1))
    _patch_pending(
        monkeypatch,
        PendingActionView(
            reason="approved",
            fixes=(SlideFix(slide_id="s9", instruction="make it warmer"),),
            call_count=7,
        ),
    )
    runner = _wired_runner(queue, credits, object())
    job = _edit_job(
        {
            "from_pending": True,
            "call_count": 2,
            "fixes": [{"slide_id": "s1", "instruction": "ignored"}],
        }
    )

    await runner._run_presentation_edit(job)  # pyright: ignore[reportPrivateUsage]

    kwargs = calls[0]
    assert [f.slide_id for f in cast(list[SlideFix], kwargs["fixes"])] == ["s9"]
    assert kwargs["call_count"] == 7
    assert queue.completed == [job.id]


@pytest.mark.asyncio
async def test_edit_from_pending_with_nothing_parked_fails_without_refund(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue, credits = _FakeQueue(), _FakeCredits()
    _patch_pending(monkeypatch, None)
    runner = _wired_runner(queue, credits, object())
    job = _edit_job({"from_pending": True, "product_type": "presentation_standard"})

    with pytest.raises(RuntimeError, match="no longer parked"):
        await runner._run_presentation_edit(job)  # pyright: ignore[reportPrivateUsage]

    await runner._execute(job)  # pyright: ignore[reportPrivateUsage]
    assert queue.failed[0]["step"] == "pipeline"
    assert credits.refunds == []


@pytest.mark.asyncio
async def test_edit_without_usable_fixes_raises() -> None:
    queue, credits = _FakeQueue(), _FakeCredits()
    runner = _wired_runner(queue, credits, object())

    with pytest.raises(RuntimeError, match="carries no fixes"):
        await runner._run_presentation_edit(_edit_job({}))  # pyright: ignore[reportPrivateUsage]
    with pytest.raises(RuntimeError, match="carries no fixes"):
        await runner._run_presentation_edit(_edit_job({"fixes": []}))  # pyright: ignore[reportPrivateUsage]
    with pytest.raises(RuntimeError, match="malformed fix entry"):
        await runner._run_presentation_edit(_edit_job({"fixes": ["s1", 7]}))  # pyright: ignore[reportPrivateUsage]
    # A MIXED batch is the sharp case, and it used to slip through: filtering
    # the junk out would apply half of an approved batch, spend the tier's fix
    # allowance on it, and report success. apply_fixes_and_render is atomic, so
    # its input parsing has to be too — one bad entry fails the whole job.
    with pytest.raises(RuntimeError, match="malformed fix entry"):
        await runner._run_presentation_edit(  # pyright: ignore[reportPrivateUsage]
            _edit_job({"fixes": [{"slide_id": "s2", "instruction": "fix the date"}, "junk"]})
        )
    assert queue.completed == [] and queue.failed == []


@pytest.mark.asyncio
async def test_edit_that_delivers_nothing_fails_the_row_at_apply_fixes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A fix that produced no file must not report success — dispatch_fix has
    already answered the parked call, so the row is all that is left to state."""

    queue, credits = _FakeQueue(), _FakeCredits()
    built = _patch_bot_and_orchestrator(monkeypatch)
    _patch_dispatch_fix(monkeypatch, FixDispatchResult(False, reason="fixes_exhausted"))
    runner = _wired_runner(queue, credits, object())
    job = _edit_job({"fixes": [{"slide_id": "s3", "instruction": "swap the image"}]})

    await runner._run_presentation_edit(job)  # pyright: ignore[reportPrivateUsage]

    assert queue.completed == []
    assert queue.failed == [{"job_id": job.id, "step": "apply_fixes", "message": "fixes_exhausted"}]
    assert credits.refunds == []
    assert cast(_FakeBot, built[0].bot).session.closed is True


@pytest.mark.asyncio
async def test_presentation_payload_topic_reaches_the_pipeline_verbatim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """W4: EnqueueRequest.topic -> payload["topic"] -> run_full_pipeline(topic=...).

    Without this seam the web's typed topic is silently dropped and the deck is
    generated from the registered sources alone.
    """

    async def _no_session(*args: Any, **kwargs: Any) -> None:
        return None

    monkeypatch.setattr("packages.bot.sessions.store.create_session", _no_session)

    async def topic_seen_for(payload: dict[str, Any]) -> object:
        built = _patch_bot_and_orchestrator(monkeypatch)
        runner = _wired_runner(_FakeQueue(), _FakeCredits(), object())
        await runner._run_presentation(_job(payload=payload))  # pyright: ignore[reportPrivateUsage]
        return built[0].pipeline_kwargs["topic"]

    assert await topic_seen_for({"topic": "Suv resurslari"}) == "Suv resurslari"
    assert await topic_seen_for({}) is None
    assert await topic_seen_for({"topic": "   "}) is None
