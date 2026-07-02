"""End-to-end presentation generation test.

Drives :meth:`PresentationOrchestrator.run_full_pipeline` end-to-end:
sources → matrix → interview (skip or answers) → design → editorial →
render. Mocks Telegram, source pipeline, evidence builder, the design /
editorial passes, and the Node worker via the same stubs the unit tests
use; real code path: the orchestrator's stage sequencing, the per-format
render loop, and free-credit grants.

Gated on ``RUN_E2E_TESTS=1`` — see :mod:`test_article_e2e` for the
rationale.
"""

from __future__ import annotations

import os
from typing import Any, cast

import pytest

from packages.bot.orchestrators.article_orchestrator import _OrchestratorError
from packages.bot.orchestrators.presentation_orchestrator import (
    PresentationOrchestrator,
)
from packages.core.enums import ExportFormat, GenerationPackage
from tests.unit.test_presentation_orchestrator import (
    _build_orch,
    _pipeline_result,
    _StubBot,
    _StubEditorialPass,
    _StubInterviewEngine,
    _StubSourcePipeline,
    _StubWorkerRunner,
)

E2E = os.environ.get("RUN_E2E_TESTS") == "1"

PROJECT_ID = "00000000-0000-0000-0000-0000000000aa"
USER_ID = "00000000-0000-0000-0000-0000000000bb"


async def _noop_progress(_name: str, _step: int, _total: int) -> None:
    return None


@pytest.mark.skipif(not E2E, reason="RUN_E2E_TESTS not set")
class TestPresentationE2E:
    """Full-pipeline tests for the presentation flow."""

    async def test_full_presentation_flow_skip_questionnaire(self) -> None:
        """Skip path: ``raw_answers=None`` routes through ``apply_defaults``."""

        bot = _StubBot(payloads={"f1": b"%PDF"})
        pipeline = _StubSourcePipeline([_pipeline_result()])
        interview = _StubInterviewEngine()
        worker = _StubWorkerRunner(formats_to_succeed=("html", "pptx"))
        orch, _db, _credits, fake = _build_orch(
            bot, pipeline=pipeline, interview=interview, worker=worker
        )

        result = await orch.run_full_pipeline(
            file_infos=[{"file_id": "f1", "filename": "deck.pdf", "file_type": "pdf"}],
            project_id=PROJECT_ID,
            user_id=USER_ID,
            language="uz",
            raw_answers=None,
            requested_formats=[ExportFormat.HTML, ExportFormat.PPTX_EDITABLE],
            progress=_noop_progress,
            package=GenerationPackage.PRESENTATION_STANDARD,
        )
        assert result.render.html_path is not None and result.render.html_path.exists()
        assert result.render.pptx_path is not None and result.render.pptx_path.exists()
        # Skip routed through apply_defaults, not apply_answers.
        assert len(interview.apply_defaults_calls) == 1
        assert len(interview.apply_answers_calls) == 0
        # One free credit per successful source.
        free_rows = [r for r in fake.tables.get("credit_ledger", []) if r["action"] == "grant_free"]
        assert len(free_rows) == 1

    async def test_full_presentation_flow_with_answers(self) -> None:
        """Mini-App answers path: ``raw_answers`` routes through ``apply_answers``."""

        bot = _StubBot(payloads={"f1": b"%PDF"})
        pipeline = _StubSourcePipeline([_pipeline_result()])
        interview = _StubInterviewEngine()
        worker = _StubWorkerRunner(formats_to_succeed=("html",))
        orch, _db, _credits, _fake = _build_orch(
            bot, pipeline=pipeline, interview=interview, worker=worker
        )

        result = await orch.run_full_pipeline(
            file_infos=[{"file_id": "f1", "filename": "deck.pdf", "file_type": "pdf"}],
            project_id=PROJECT_ID,
            user_id=USER_ID,
            language="uz",
            raw_answers={"audience": "talaba"},
            requested_formats=[ExportFormat.HTML],
            progress=_noop_progress,
            package=GenerationPackage.PRESENTATION_STANDARD,
        )
        assert result.render.html_path is not None and result.render.html_path.exists()
        assert len(interview.apply_answers_calls) == 1
        assert len(interview.apply_defaults_calls) == 0

    async def test_presentation_flow_render_failure_returns_warnings(self) -> None:
        """Subprocess timeout on every format yields warnings + no files.

        The orchestrator continues past per-format failures (other
        formats still attempted); we assert the warning text mentions
        the format and the final result has no successful paths.
        """

        bot = _StubBot(payloads={"f1": b"%PDF"})
        pipeline = _StubSourcePipeline([_pipeline_result()])
        worker = _StubWorkerRunner(timeout_on=("html", "pptx"))
        orch, _db, _credits, _fake = _build_orch(bot, pipeline=pipeline, worker=worker)

        result = await orch.run_full_pipeline(
            file_infos=[{"file_id": "f1", "filename": "deck.pdf", "file_type": "pdf"}],
            project_id=PROJECT_ID,
            user_id=USER_ID,
            language="uz",
            raw_answers=None,
            requested_formats=[ExportFormat.HTML, ExportFormat.PPTX_EDITABLE],
            progress=_noop_progress,
            package=GenerationPackage.PRESENTATION_STANDARD,
        )
        assert result.render.html_path is None
        assert result.render.pptx_path is None
        assert any("timed out" in w for w in result.render.warnings)

    async def test_presentation_flow_editorial_failure_wraps_step(self) -> None:
        """Editorial pass raising surfaces as _OrchestratorError('editorial')."""

        bot = _StubBot(payloads={"f1": b"%PDF"})
        pipeline = _StubSourcePipeline([_pipeline_result()])
        editorial = _StubEditorialPass(raises=RuntimeError("anthropic 429"))
        orch, _db, _credits, _fake = _build_orch(bot, pipeline=pipeline, editorial=editorial)

        with pytest.raises(_OrchestratorError) as info:
            await orch.run_full_pipeline(
                file_infos=[{"file_id": "f1", "filename": "deck.pdf", "file_type": "pdf"}],
                project_id=PROJECT_ID,
                user_id=USER_ID,
                language="uz",
                raw_answers=None,
                requested_formats=[ExportFormat.HTML],
                progress=_noop_progress,
                package=GenerationPackage.PRESENTATION_STANDARD,
            )
        assert info.value.step == "editorial"

    async def test_presentation_flow_source_failure_partial(self) -> None:
        """One bad source + one good source: pipeline completes for the good one."""

        bot = _StubBot(payloads={"f1": b"%PDF-bad", "f2": b"%PDF-good"})
        pipeline = _StubSourcePipeline([RuntimeError("magika rejected"), _pipeline_result()])
        worker = _StubWorkerRunner(formats_to_succeed=("html",))
        orch, _db, _credits, _fake = _build_orch(bot, pipeline=pipeline, worker=worker)

        result = await orch.run_full_pipeline(
            file_infos=[
                {"file_id": "f1", "filename": "bad.pdf", "file_type": "pdf"},
                {"file_id": "f2", "filename": "good.pdf", "file_type": "pdf"},
            ],
            project_id=PROJECT_ID,
            user_id=USER_ID,
            language="uz",
            raw_answers=None,
            requested_formats=[ExportFormat.HTML],
            progress=_noop_progress,
            package=GenerationPackage.PRESENTATION_STANDARD,
        )
        assert result.render.html_path is not None and result.render.html_path.exists()


# Avoid unused-import linter complaints when E2E is off.
_ = PresentationOrchestrator
_ = cast
_ = Any
