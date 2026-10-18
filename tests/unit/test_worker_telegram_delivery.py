"""B8.1: the worker delivers a completed bot edit's files to Telegram (ADR 0004).

A bot-enqueued ``presentation_edit`` job carries a ``delivery.telegram`` block; a web
job carries none. When the job reaches ``completed`` the worker pushes the committed
revision's rendered files to the chat, best-effort: a send failure is swallowed (the
edit is unpaid and already settled, so nothing is refunded or re-run).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import scripts.worker_run_job as worker
from packages.bot.labels import get_bot_labels
from packages.platform.jobs import GenerationJob, JobStatus, JobType

pytestmark = pytest.mark.asyncio


class _Session:
    def __init__(self, bot: _StubBot) -> None:
        self._bot = bot

    async def close(self) -> None:
        self._bot.closed = True


class _StubBot:
    """Captures what the worker would send; the session close is a no-op."""

    def __init__(self, *, fail: bool = False) -> None:
        self.messages: list[tuple[int, str]] = []
        self.documents: list[tuple[int, Any]] = []
        self.fail = fail
        self.closed = False
        self.session = _Session(self)

    async def send_message(self, chat_id: int, text: str, **_kwargs: Any) -> None:
        if self.fail:
            raise RuntimeError("telegram unavailable")
        self.messages.append((chat_id, text))

    async def send_document(self, chat_id: int, document: Any, **_kwargs: Any) -> None:
        if self.fail:
            raise RuntimeError("telegram unavailable")
        self.documents.append((chat_id, document))


def _edit_job(status: JobStatus = JobStatus.COMPLETED, **payload: Any) -> GenerationJob:
    return GenerationJob(
        id="job-1",
        project_id="proj-1",
        job_type=JobType.PRESENTATION_EDIT,
        status=status,
        payload=payload,
    )


def _delivery(chat_id: int = 7, language: str = "uz") -> dict[str, Any]:
    return {"telegram": {"chat_id": chat_id, "language": language}}


async def test_telegram_delivery_parses_only_a_well_formed_bot_block() -> None:
    assert worker._telegram_delivery(_edit_job(delivery=_delivery(7, "ru"))) == (7, "ru")
    assert worker._telegram_delivery(_edit_job()) is None, "a web job must not deliver"
    # Fail closed on a malformed stamp rather than guess at a chat.
    assert worker._telegram_delivery(_edit_job(delivery={"telegram": {"chat_id": "7"}})) is None
    assert worker._telegram_delivery(_edit_job(delivery={"telegram": {"chat_id": 7}})) is None
    assert worker._telegram_delivery(_edit_job(delivery={"telegram": 5})) is None


async def test_deliver_edit_files_sends_caption_then_each_document(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    html, pptx = tmp_path / "d.html", tmp_path / "d.pptx"
    html.write_text("x")
    pptx.write_text("y")

    async def fake_fetch(_db: Any, _storage: Any, _rev: str) -> dict[str, Path]:
        return {"html": html, "pptx": pptx}

    monkeypatch.setattr(
        "packages.bot.orchestrators.inline_publish.fetch_exports", fake_fetch
    )
    bot = _StubBot()
    await worker._deliver_edit_files(
        bot,  # type: ignore[arg-type]  # a structural aiogram Bot stub
        object(),
        object(),  # type: ignore[arg-type]
        chat_id=7,
        language="en",
        revision_id="rev-1",
        slides_changed=3,
    )
    assert bot.messages == [(7, get_bot_labels("en").edit_applied.format(count=3))]
    assert len(bot.documents) == 2


async def test_deliver_edit_files_swallows_a_send_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    html = tmp_path / "d.html"
    html.write_text("x")

    async def fake_fetch(_db: Any, _storage: Any, _rev: str) -> dict[str, Path]:
        return {"html": html}

    monkeypatch.setattr(
        "packages.bot.orchestrators.inline_publish.fetch_exports", fake_fetch
    )
    bot = _StubBot(fail=True)
    # Best-effort: a Telegram error must not propagate into the job lifecycle.
    await worker._deliver_edit_files(
        bot,  # type: ignore[arg-type]
        object(),
        object(),  # type: ignore[arg-type]
        chat_id=7,
        language="en",
        revision_id="rev-1",
        slides_changed=1,
    )


async def test_deliver_edit_files_is_quiet_when_no_exports_exist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_fetch(_db: Any, _storage: Any, _rev: str) -> dict[str, Path]:
        return {}

    monkeypatch.setattr(
        "packages.bot.orchestrators.inline_publish.fetch_exports", fake_fetch
    )
    bot = _StubBot()
    await worker._deliver_edit_files(
        bot,  # type: ignore[arg-type]
        object(),
        object(),  # type: ignore[arg-type]
        chat_id=7,
        language="en",
        revision_id="rev-1",
        slides_changed=1,
    )
    assert bot.messages == [] and bot.documents == []


class _Queue:
    def __init__(self, parents: list[GenerationJob]) -> None:
        self._parents = parents

    async def jobs_for_render(self, render_job_id: str) -> list[GenerationJob]:
        return self._parents


class _Config:
    telegram_bot_token = "test-token"


async def test_render_completion_delivers_only_completed_bot_parents(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    html = tmp_path / "d.html"
    html.write_text("x")

    async def fake_fetch(_db: Any, _storage: Any, _rev: str) -> dict[str, Path]:
        return {"html": html}

    monkeypatch.setattr(
        "packages.bot.orchestrators.inline_publish.fetch_exports", fake_fetch
    )
    stub = _StubBot()
    monkeypatch.setattr("aiogram.Bot", lambda token: stub)

    parents = [
        _edit_job(delivery=_delivery(11, "uz"), slides_changed=2),  # bot, completed
        _edit_job(status=JobStatus.COMMITTED, delivery=_delivery(22, "ru")),  # not yet done
        _edit_job(),  # a web parent, no delivery block
    ]
    runner = worker.JobRunner.__new__(worker.JobRunner)
    runner._queue = _Queue(parents)  # type: ignore[attr-defined]
    runner._db = object()  # type: ignore[attr-defined]
    runner._storage = object()  # type: ignore[attr-defined]
    runner._config = _Config()  # type: ignore[attr-defined]

    render_job = GenerationJob(
        id="render-1",
        project_id="proj-1",
        job_type=JobType.PRESENTATION_RENDER,
        status=JobStatus.PROCESSING,
    )
    await runner._deliver_render_parents(render_job, "rev-1")

    # Only the completed bot parent was delivered; the committed and web parents were not.
    assert stub.messages == [(11, get_bot_labels("uz").edit_applied.format(count=2))]
    assert [chat for chat, _doc in stub.documents] == [11]
    assert stub.closed, "the delivery Bot session was not closed"
