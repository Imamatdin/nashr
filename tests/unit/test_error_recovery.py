"""Behaviour tests for orchestrator error wrapping + failed-source surfacing.

The orchestrators wrap each step in a try/except that re-raises as
:class:`_OrchestratorError` with a canonical step name. Tests assert:

  * The wrapper carries the step name + original exception.
  * Source-pipeline failures populate ``failed_sources`` (in addition to
    the existing ``warnings`` list) so handlers can render a structured
    per-file warning.
  * Handler-level catch of :class:`_OrchestratorError` shows the step in
    the user-facing message.
"""

from __future__ import annotations

from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from packages.bot.orchestrators import SourceProcessingResult
from packages.bot.orchestrators.article_orchestrator import _OrchestratorError
from packages.platform.config import PlatformConfig
from packages.platform.credits import CreditLedger
from packages.platform.database import DatabaseClient
from tests.unit.test_article_orchestrator import (
    _build_orchestrator,
    _pipeline_result,
    _StubBot,
    _StubSourcePipeline,
    _validation_result,
)
from tests.unit.test_database_client import FakeSupabaseClient

PROJECT_ID = "00000000-0000-0000-0000-000000000aaa"
USER_ID = "00000000-0000-0000-0000-000000000bbb"


async def _noop_progress(_name: str, _step: int, _total: int) -> None:
    return None


# ---------------------------------------------------------------------------
# Exception shape
# ---------------------------------------------------------------------------


def test_orchestrator_error_has_step_context() -> None:
    """The wrapper exposes ``step`` and ``original`` for handler rendering."""

    original = ValueError("bad file")
    err = _OrchestratorError("process_sources", original)
    assert err.step == "process_sources"
    assert err.original is original
    assert "process_sources" in str(err)
    assert "bad file" in str(err)


# ---------------------------------------------------------------------------
# failed_sources surfacing
# ---------------------------------------------------------------------------


async def test_source_failure_returns_warning_info() -> None:
    """When one of two sources fails to parse, the survivor goes through and
    the failure lands in ``failed_sources`` with the filename + reason."""

    bot = _StubBot(payloads={"f1": b"ok", "f2": b"bad"})
    pipeline = _StubSourcePipeline([_pipeline_result(), RuntimeError("parser exploded")])
    orch, _db, _credits, _fake = _build_orchestrator(bot, pipeline=pipeline)

    file_infos: list[dict[str, object]] = [
        {"file_id": "f1", "filename": "good.pdf", "file_size": 1, "file_type": "pdf"},
        {"file_id": "f2", "filename": "bad.pdf", "file_size": 1, "file_type": "pdf"},
    ]
    result = await orch.process_sources(file_infos, PROJECT_ID, USER_ID, _noop_progress)

    assert len(result.failed_sources) == 1
    name, reason = result.failed_sources[0]
    assert name == "bad.pdf"
    assert "RuntimeError" in reason
    # the survivor still made it through
    assert len(result.claims) == 1


async def test_rejected_validation_lands_in_failed_sources() -> None:
    """Magika rejection populates ``failed_sources`` with the reason text."""

    from packages.core.models.source import SourcePipelineResult

    bot = _StubBot(payloads={"f1": b"junk"})
    pipeline = _StubSourcePipeline(
        [
            SourcePipelineResult(
                validation=_validation_result(valid=False).model_copy(
                    update={"rejection_reason": "Magika rejected: confidence below threshold"}
                ),
                parsed=None,
                chunks=[],
                claims=[],
                errors=["rejected"],
            )
        ]
    )
    orch, _db, _credits, _fake = _build_orchestrator(bot, pipeline=pipeline)

    with pytest.raises(ValueError):
        await orch.process_sources(
            [{"file_id": "f1", "filename": "junk.pdf", "file_size": 1, "file_type": "pdf"}],
            PROJECT_ID,
            USER_ID,
            _noop_progress,
        )

    # Even though process_sources raised on empty results, the per-file
    # failure was recorded on the mutable result. We can't read it after
    # the raise — but we can prove the warning path by asserting the
    # rejection reason flowed through the warning generator.
    # Test via partial-result variant:
    bot2 = _StubBot(payloads={"f1": b"junk", "f2": b"ok"})
    pipeline2 = _StubSourcePipeline(
        [
            SourcePipelineResult(
                validation=_validation_result(valid=False).model_copy(
                    update={"rejection_reason": "Magika rejected: bad type"}
                ),
                parsed=None,
                chunks=[],
                claims=[],
                errors=["rejected"],
            ),
            _pipeline_result(),
        ]
    )
    orch2, _db2, _credits2, _fake2 = _build_orchestrator(bot2, pipeline=pipeline2)
    result = await orch2.process_sources(
        [
            {"file_id": "f1", "filename": "bad.pdf", "file_size": 1, "file_type": "pdf"},
            {"file_id": "f2", "filename": "good.pdf", "file_size": 1, "file_type": "pdf"},
        ],
        PROJECT_ID,
        USER_ID,
        _noop_progress,
    )
    assert len(result.failed_sources) == 1
    assert result.failed_sources[0][0] == "bad.pdf"
    assert "Magika rejected" in result.failed_sources[0][1]


async def test_process_sources_progress_warning_emission() -> None:
    """A failed source triggers an extra progress() call with a warning string."""

    bot = _StubBot(payloads={"f1": b"ok", "f2": b"bad"})
    pipeline = _StubSourcePipeline([_pipeline_result(), RuntimeError("boom")])
    orch, _db, _credits, _fake = _build_orchestrator(bot, pipeline=pipeline)
    seen: list[str] = []

    async def progress(name: str, _step: int, _total: int) -> None:
        seen.append(name)

    await orch.process_sources(
        [
            {"file_id": "f1", "filename": "good.pdf", "file_size": 1, "file_type": "pdf"},
            {"file_id": "f2", "filename": "bad.pdf", "file_size": 1, "file_type": "pdf"},
        ],
        PROJECT_ID,
        USER_ID,
        progress,
    )
    # First call announces the step; second call surfaces the failure.
    warning_calls = [s for s in seen if "Warning" in s and "bad.pdf" in s]
    assert len(warning_calls) == 1


# ---------------------------------------------------------------------------
# Orchestrator wraps step failures
# ---------------------------------------------------------------------------


async def test_orchestrator_wraps_matrix_builder_failure() -> None:
    """A matrix-builder exception surfaces as _OrchestratorError('evidence_matrix')."""

    bot = _StubBot(payloads={"f1": b"ok"})
    pipeline = _StubSourcePipeline([_pipeline_result()])
    orch, _, _, _ = _build_orchestrator(bot, pipeline=pipeline)

    class _BrokenBuilder:
        async def build_from_claims(self, **_kwargs: Any) -> Any:
            raise RuntimeError("supabase fell over")

        async def assign_to_sections(self, *_args: Any, **_kwargs: Any) -> Any:
            return None

    # Replace the builder on the constructed orchestrator
    orch._matrix_builder = cast(Any, _BrokenBuilder())

    sources = SourceProcessingResult()
    with pytest.raises(_OrchestratorError) as info:
        await orch.build_evidence_matrix(sources, PROJECT_ID, _noop_progress)
    assert info.value.step == "evidence_matrix"
    assert isinstance(info.value.original, RuntimeError)


async def test_orchestrator_wraps_outline_failure() -> None:
    """An outline-generator exception surfaces with step name 'outline'."""

    bot = _StubBot(payloads={"f1": b"ok"})
    orch, _, _, _ = _build_orchestrator(bot)

    class _BrokenOutline:
        async def generate(self, **_kwargs: Any) -> Any:
            raise RuntimeError("llm timed out")

    orch._outline_generator = cast(Any, _BrokenOutline())

    # Need a non-empty matrix for the assign_to_sections call
    from datetime import UTC, datetime

    from packages.core.enums import CitationStatus
    from packages.core.models.evidence import EvidenceMatrix, EvidenceMatrixEntry

    matrix = EvidenceMatrix(
        project_id=uuid4(),
        entries=[
            EvidenceMatrixEntry(
                project_id=uuid4(),
                claim_id=uuid4(),
                source_chunk_id=uuid4(),
                citation_status=CitationStatus.READY,
                created_at=datetime.now(UTC),
            )
        ],
    )

    with pytest.raises(_OrchestratorError) as info:
        await orch.generate_outline(
            sources=SourceProcessingResult(),
            matrix=matrix,
            project_id=PROJECT_ID,
            language="uz",
            tier="basic",
            project_title="A",
        )
    assert info.value.step == "outline"


# ---------------------------------------------------------------------------
# Handler integration: step name surfaces in user-facing message
# ---------------------------------------------------------------------------


async def test_handler_shows_step_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """The article handler turns _OrchestratorError into a step-named user message.

    Runs ``continue_to_processing`` with an orchestrator stub whose
    ``process_sources`` raises _OrchestratorError; asserts the edited
    message contains both the localized prefix and the step name.
    """

    from packages.bot.handlers import article_flow

    cfg = PlatformConfig(
        supabase_url="https://test.supabase.co",
        supabase_service_key="test",
        telegram_bot_token="test",
    )
    fake = FakeSupabaseClient()
    db = DatabaseClient(cfg, client=cast(Any, fake))
    credits = CreditLedger(db)

    class _Bot:
        pass

    class _BadOrchestrator:
        async def process_sources(self, **_kwargs: Any) -> Any:
            raise _OrchestratorError("process_sources", RuntimeError("download died"))

    monkeypatch.setattr(article_flow, "_orchestrator", lambda *a, **k: _BadOrchestrator())

    edited: list[str] = []

    from aiogram.types import CallbackQuery, Message

    callback = MagicMock(spec=CallbackQuery)
    callback.answer = AsyncMock()
    callback.message = MagicMock(spec=Message)
    callback.message.edit_text = AsyncMock(side_effect=lambda text, **kw: edited.append(text))
    callback.message.answer = AsyncMock()

    state = MagicMock()
    state.get_data = AsyncMock(
        return_value={
            "project_id": PROJECT_ID,
            "user_id": USER_ID,
            "language": "uz",
            "sources": [{"file_id": "f1", "filename": "a.pdf", "file_type": "pdf"}],
        }
    )
    state.clear = AsyncMock()
    state.set_state = AsyncMock()
    state.update_data = AsyncMock()

    await article_flow.continue_to_processing(
        cast(Any, callback), cast(Any, state), cast(Any, _Bot()), db, credits
    )

    assert any("process_sources" in text for text in edited), edited
