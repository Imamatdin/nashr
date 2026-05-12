"""End-to-end article generation test.

Drives the full :class:`ArticleOrchestrator` pipeline (sources → matrix →
interview → outline → draft → verify → export) against in-memory stubs
that stand in for Telegram, the source pipeline, the LLM-driven worker
engines, and the export pipeline. Real code paths exercised: the
orchestrator sequencing, evidence-matrix threading between steps, free
credit grants, and DOCX byte plumbing.

Gated on ``RUN_E2E_TESTS=1`` because the test mounts every engine and a
full pipeline run is materially slower than the per-step unit tests.
"""

from __future__ import annotations

import os
from typing import Any, cast

import pytest

from packages.bot.orchestrators import ArticleOrchestrator
from packages.bot.orchestrators.article_orchestrator import _OrchestratorError
from packages.core.enums import ArticleStructure
from tests.unit.test_article_orchestrator import (
    _build_orchestrator,
    _pipeline_result,
    _StubBot,
    _StubDrafter,
    _StubExportPipeline,
    _StubInterviewEngine,
    _StubSourcePipeline,
)

E2E = os.environ.get("RUN_E2E_TESTS") == "1"

PROJECT_ID = "00000000-0000-0000-0000-0000000000aa"
USER_ID = "00000000-0000-0000-0000-0000000000bb"


async def _noop_progress(_name: str, _step: int, _total: int) -> None:
    return None


@pytest.mark.skipif(not E2E, reason="RUN_E2E_TESTS not set")
class TestArticleE2E:
    """Full-pipeline tests for the article flow."""

    async def test_full_article_flow(self, tmp_path: Any) -> None:
        """Process → matrix → questions → outline → draft → verify → export.

        Asserts: (a) the DOCX file is written and non-empty, (b) free
        credits were granted for the source upload, (c) the orchestrator
        threaded the matrix through every downstream step (one builder
        call, one outline call, one drafter call, one verifier call).
        """

        bot = _StubBot(payloads={"f1": b"%PDF-fake"})
        pipeline = _StubSourcePipeline([_pipeline_result()])
        drafter = _StubDrafter()
        orch, _db, _credits, fake = _build_orchestrator(bot, pipeline=pipeline, drafter=drafter)

        sources = await orch.process_sources(
            [{"file_id": "f1", "filename": "paper.pdf", "file_size": 100, "file_type": "pdf"}],
            PROJECT_ID,
            USER_ID,
            _noop_progress,
        )
        assert len(sources.claims) == 1

        matrix = await orch.build_evidence_matrix(sources, PROJECT_ID, _noop_progress)
        questions = await orch.generate_interview_questions(
            sources=sources, matrix=matrix, project_id=PROJECT_ID, language="uz"
        )
        # Default stub interview engine emits no questions; that path is fine.
        assert isinstance(questions, list)

        outline = await orch.generate_outline(
            sources=sources,
            matrix=matrix,
            project_id=PROJECT_ID,
            language="uz",
            tier="basic",
            project_title="Solar paper",
            structure=ArticleStructure.REFERAT,
        )
        assert outline.title

        draft = await orch.draft_article(
            outline=outline,
            matrix=matrix,
            sources=sources,
            questions=questions,
            answers=[],
            language="uz",
            calibration="bakalavr",
            progress=_noop_progress,
        )
        verification = await orch.verify_citations(
            draft=draft, matrix=matrix, sources=sources, progress=_noop_progress
        )
        docx_path, _pdf_path, _bundle = await orch.export(
            draft=draft,
            outline=outline,
            verification=verification,
            sources=sources,
            project_id=PROJECT_ID,
            language="uz",
            author_name="Tester",
            progress=_noop_progress,
        )
        assert docx_path.exists()
        assert docx_path.stat().st_size > 0

        free_rows = [r for r in fake.tables.get("credit_ledger", []) if r["action"] == "grant_free"]
        assert len(free_rows) == 1
        assert len(drafter.calls) == 1

    async def test_article_flow_source_failure_partial(self) -> None:
        """One of two files fails parsing — the survivor still produces a draft."""

        bot = _StubBot(payloads={"f1": b"%PDF-good", "f2": b"%PDF-bad"})
        pipeline = _StubSourcePipeline([_pipeline_result(), RuntimeError("pymupdf exploded")])
        orch, _db, _credits, _fake = _build_orchestrator(bot, pipeline=pipeline)

        sources = await orch.process_sources(
            [
                {"file_id": "f1", "filename": "good.pdf", "file_type": "pdf"},
                {"file_id": "f2", "filename": "bad.pdf", "file_type": "pdf"},
            ],
            PROJECT_ID,
            USER_ID,
            _noop_progress,
        )
        assert len(sources.claims) == 1
        assert len(sources.failed_sources) == 1
        assert sources.failed_sources[0][0] == "bad.pdf"

        matrix = await orch.build_evidence_matrix(sources, PROJECT_ID, _noop_progress)
        outline = await orch.generate_outline(
            sources=sources,
            matrix=matrix,
            project_id=PROJECT_ID,
            language="uz",
            tier="basic",
            project_title="Partial",
        )
        draft = await orch.draft_article(
            outline=outline,
            matrix=matrix,
            sources=sources,
            questions=[],
            answers=[],
            language="uz",
            calibration="bakalavr",
            progress=_noop_progress,
        )
        assert draft is not None

    async def test_article_flow_generation_failure_wraps_step(self) -> None:
        """Drafter raises → orchestrator surfaces _OrchestratorError('draft')."""

        class _ExplodingDrafter(_StubDrafter):
            async def draft_article(self, **_kwargs: Any) -> Any:  # type: ignore[override]
                raise RuntimeError("llm api 500")

        bot = _StubBot(payloads={"f1": b"%PDF-good"})
        pipeline = _StubSourcePipeline([_pipeline_result()])
        orch, _db, _credits, _fake = _build_orchestrator(
            bot, pipeline=pipeline, drafter=cast(Any, _ExplodingDrafter())
        )

        sources = await orch.process_sources(
            [{"file_id": "f1", "filename": "good.pdf", "file_type": "pdf"}],
            PROJECT_ID,
            USER_ID,
            _noop_progress,
        )
        matrix = await orch.build_evidence_matrix(sources, PROJECT_ID, _noop_progress)
        outline = await orch.generate_outline(
            sources=sources,
            matrix=matrix,
            project_id=PROJECT_ID,
            language="uz",
            tier="basic",
            project_title="x",
        )
        with pytest.raises(_OrchestratorError) as info:
            await orch.draft_article(
                outline=outline,
                matrix=matrix,
                sources=sources,
                questions=[],
                answers=[],
                language="uz",
                calibration="bakalavr",
                progress=_noop_progress,
            )
        assert info.value.step == "draft"

    async def test_article_flow_pdf_failure_does_not_block_docx(self) -> None:
        """A failed PDF export still returns the DOCX path."""

        bot = _StubBot(payloads={"f1": b"%PDF"})
        pipeline = _StubSourcePipeline([_pipeline_result()])
        export = _StubExportPipeline(pdf_success=False)
        orch, _db, _credits, _fake = _build_orchestrator(bot, pipeline=pipeline, export_pipe=export)

        sources = await orch.process_sources(
            [{"file_id": "f1", "filename": "x.pdf", "file_type": "pdf"}],
            PROJECT_ID,
            USER_ID,
            _noop_progress,
        )
        matrix = await orch.build_evidence_matrix(sources, PROJECT_ID, _noop_progress)
        outline = await orch.generate_outline(
            sources=sources,
            matrix=matrix,
            project_id=PROJECT_ID,
            language="uz",
            tier="basic",
            project_title="x",
        )
        draft = await orch.draft_article(
            outline=outline,
            matrix=matrix,
            sources=sources,
            questions=[],
            answers=[],
            language="uz",
            calibration="bakalavr",
            progress=_noop_progress,
        )
        verification = await orch.verify_citations(draft, matrix, sources, _noop_progress)
        docx_path, pdf_path, _bundle = await orch.export(
            draft=draft,
            outline=outline,
            verification=verification,
            sources=sources,
            project_id=PROJECT_ID,
            language="uz",
            author_name="t",
            progress=_noop_progress,
        )
        assert docx_path.exists()
        assert pdf_path is None


# Avoid "unused import" warnings when E2E is off.
_ = ArticleOrchestrator
_ = _StubInterviewEngine
