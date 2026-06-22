"""Behaviour tests for :class:`PresentationOrchestrator`.

Every external collaborator (Telegram bot download, source pipeline,
evidence-matrix builder, interview / design / editorial engines, and
the Node worker invocation) is replaced with a fake at the constructor
seam. Tests assert one property of the orchestration contract per
case: progress callback wiring, free-credit grants on source upload,
correct fan-out between "apply answers" and "apply defaults", the
render→file mapping, and the full-pipeline glue.
"""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import pytest

from packages.bot.orchestrators import SourceProcessingResult
from packages.bot.orchestrators.presentation_orchestrator import (
    TOTAL_STEPS,
    PresentationOrchestrator,
    PresentationRenderResult,
)
from packages.core.enums import (
    AudienceType,
    BackgroundTreatment,
    CitationStatus,
    ClaimStrength,
    ClaimType,
    DiagramStrategy,
    ExportFormat,
    GenerationPackage,
    Language,
    NarrativeEmphasis,
    NarrativePhase,
    PresentationMood,
    SlideType,
    SpeakerNotesStyle,
    TitleStyle,
)
from packages.core.models.evidence import EvidenceMatrix, EvidenceMatrixEntry
from packages.core.models.presentation import (
    ColorPalette,
    DeckPlan,
    DeckSpec,
    DesignDirectionSpec,
    InterviewQuestion,
    PersonItem,
    PlannedFigure,
    PlannedSection,
    PresentationInterviewAnswers,
    PresentationInterviewQuestions,
    SlideContent,
    SlideRegenResult,
    SlideSpec,
)
from packages.core.models.source import (
    FileValidationResult,
    SourceChunkCreate,
    SourceClaimCreate,
    SourcePipelineResult,
)
from packages.platform.config import PlatformConfig
from packages.platform.credits import CreditLedger
from packages.platform.database import DatabaseClient
from packages.presentation.editorial import EditorialPass, EditorialSlideRegenError
from tests.unit.test_database_client import FakeSupabaseClient

PROJECT_ID = "00000000-0000-0000-0000-000000000aaa"
USER_ID = "00000000-0000-0000-0000-000000000bbb"


# ---------------------------------------------------------------------------
# Builders / fakes
# ---------------------------------------------------------------------------


def _make_db() -> tuple[DatabaseClient, FakeSupabaseClient, CreditLedger]:
    cfg = PlatformConfig(
        supabase_url="https://test.supabase.co",
        supabase_service_key="test",
        telegram_bot_token="test",
    )
    fake = FakeSupabaseClient()
    db = DatabaseClient(cfg, client=cast(Any, fake))
    ledger = CreditLedger(db)
    return db, fake, ledger


def _claim(text: str = "Solar cells convert sunlight efficiently.") -> SourceClaimCreate:
    return SourceClaimCreate(
        source_chunk_id="0",
        project_id=PROJECT_ID,
        claim_text=text,
        strength=ClaimStrength.MODERATE,
        claim_type=ClaimType.EMPIRICAL_FINDING,
    )


def _chunk(text: str = "Sample chunk text for source content.") -> SourceChunkCreate:
    return SourceChunkCreate(chunk_index=0, text=text, source_id="0")


def _pipeline_result(
    *,
    valid: bool = True,
    claims: list[SourceClaimCreate] | None = None,
    chunks: list[SourceChunkCreate] | None = None,
) -> SourcePipelineResult:
    validation = FileValidationResult(
        valid=valid,
        detected_type="pdf",
        mime_type="application/pdf",
        confidence=0.95,
        file_size_bytes=1024,
    )
    return SourcePipelineResult(
        validation=validation,
        parsed=None,
        chunks=chunks if chunks is not None else [_chunk()],
        claims=claims if claims is not None else [_claim()],
        errors=[],
    )


class _StubBot:
    """In-memory stand-in for :class:`aiogram.Bot.download`."""

    def __init__(self, payloads: dict[str, bytes] | None = None) -> None:
        self.payloads: dict[str, bytes] = dict(payloads or {})
        self.downloaded: list[str] = []

    async def download(self, file_id: str) -> BytesIO:
        self.downloaded.append(file_id)
        return BytesIO(self.payloads.get(file_id, b"%PDF-1.4\n%fake\n"))


class _StubSourcePipeline:
    def __init__(self, results: list[SourcePipelineResult | Exception]) -> None:
        self.results: list[SourcePipelineResult | Exception] = list(results)
        self.calls: list[tuple[bytes, str]] = []

    async def process(self, file_bytes: bytes, filename: str) -> SourcePipelineResult:
        self.calls.append((file_bytes, filename))
        if not self.results:
            raise RuntimeError("StubSourcePipeline ran out of responses")
        nxt = self.results.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt


class _StubMatrixBuilder:
    def __init__(self) -> None:
        self.build_calls: list[dict[str, Any]] = []

    async def build_from_claims(self, **kwargs: Any) -> EvidenceMatrix:
        self.build_calls.append(kwargs)
        project_id_arg = kwargs["project_id"]
        entry = EvidenceMatrixEntry(
            project_id=project_id_arg,
            claim_id=uuid4(),
            source_chunk_id=uuid4(),
            citation_status=CitationStatus.READY,
            created_at=datetime.now(UTC),
        )
        return EvidenceMatrix(project_id=project_id_arg, entries=[entry])


def _interview_questions() -> PresentationInterviewQuestions:
    return PresentationInterviewQuestions(
        questions=[
            InterviewQuestion(
                question_id="audience",
                question_text="Who?",
                question_type="single_select",
            )
        ],
        detected_domain="general",
        estimated_slide_count=10,
        available_stats_count=0,
        available_people_count=0,
    )


def _interview_answers() -> PresentationInterviewAnswers:
    return PresentationInterviewAnswers(
        audience=AudienceType.UNDERGRADUATE,
        talk_duration_minutes=15,
        language=Language.UZ,
        narrative_emphasis=NarrativeEmphasis.BALANCED,
        title_style=TitleStyle.TAKEAWAY,
        include_interactive=True,
        mood_override=PresentationMood.CLEAN_PROFESSIONAL,
        background_treatment=BackgroundTreatment.LIGHT,
        diagram_strategy=DiagramStrategy.BUILD_SVG,
        speaker_notes_style=SpeakerNotesStyle.BRIEF_TALKING_POINTS,
    )


class _StubInterviewEngine:
    def __init__(self) -> None:
        self.apply_defaults_calls: list[dict[str, Any]] = []
        self.apply_answers_calls: list[dict[str, Any]] = []
        self.generate_questions_calls: list[dict[str, Any]] = []

    def generate_questions(self, **kwargs: Any) -> PresentationInterviewQuestions:
        self.generate_questions_calls.append(kwargs)
        return _interview_questions()

    def apply_defaults(self, **kwargs: Any) -> PresentationInterviewAnswers:
        self.apply_defaults_calls.append(kwargs)
        return _interview_answers()

    def apply_answers(self, **kwargs: Any) -> PresentationInterviewAnswers:
        self.apply_answers_calls.append(kwargs)
        return _interview_answers()


def _design_spec() -> DesignDirectionSpec:
    return DesignDirectionSpec(
        mood=PresentationMood.CLEAN_PROFESSIONAL,
        palette=ColorPalette(
            background="#F8F8FA",
            surface="#FFFFFF",
            text="#2A2A2A",
            accent="#0A8A7A",
            text_secondary="#6A6A7A",
        ),
        heading_font="Inter",
        body_font="Inter",
        decorative_font=None,
        image_style_prefix="clean modern photography",
        background_treatment=BackgroundTreatment.LIGHT,
    )


class _StubDesignPass:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def generate(self, **kwargs: Any) -> DesignDirectionSpec:
        self.calls.append(kwargs)
        return _design_spec()


def _deck_spec() -> DeckSpec:
    slide = SlideSpec(
        slide_index=0,
        slide_type=SlideType.TITLE_HERO,
        content=SlideContent(title="Test deck"),
        narrative_role=NarrativePhase.HOOK.value,
    )
    return DeckSpec(
        project_id=PROJECT_ID,
        title="Test deck",
        language=Language.UZ,
        design=_design_spec(),
        interview=_interview_answers(),
        slides=[slide],
        export_formats=[ExportFormat.HTML],
    )


class _StubEditorialPass:
    def __init__(self, raises: Exception | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self._raises = raises

    async def generate_deck_spec(self, **kwargs: Any) -> DeckSpec:
        self.calls.append(kwargs)
        if self._raises is not None:
            raise self._raises
        return _deck_spec()


class _StubWorkerRunner:
    """Fake worker runner that writes canned output files to ``output_dir``."""

    def __init__(
        self,
        *,
        formats_to_succeed: tuple[str, ...] = ("html", "pptx"),
        raise_on_ensure: Exception | None = None,
        force_returncode: int = 0,
        timeout_on: tuple[str, ...] = (),
        exception_on: tuple[str, ...] = (),
    ) -> None:
        self.ensure_calls = 0
        self.render_calls: list[dict[str, Any]] = []
        self._formats_to_succeed = set(formats_to_succeed)
        self._raise_on_ensure = raise_on_ensure
        self._force_returncode = force_returncode
        self._timeout_on = set(timeout_on)
        self._exception_on = set(exception_on)

    async def ensure_built(self) -> Path:
        self.ensure_calls += 1
        if self._raise_on_ensure is not None:
            raise self._raise_on_ensure
        return Path("fake/dist/index.js")

    async def run_render(
        self,
        worker_entry: Path,
        deck_json_path: Path,
        output_dir: Path,
        cli_format: str,
    ) -> subprocess.CompletedProcess[str]:
        self.render_calls.append(
            {
                "worker_entry": worker_entry,
                "deck_json_path": deck_json_path,
                "output_dir": output_dir,
                "cli_format": cli_format,
            }
        )
        if cli_format in self._timeout_on:
            raise subprocess.TimeoutExpired(cmd=["node"], timeout=1)
        if cli_format in self._exception_on:
            raise RuntimeError(f"explosion in {cli_format}")

        if cli_format in self._formats_to_succeed and self._force_returncode == 0:
            out = output_dir / f"Test_deck.{cli_format}"
            out.write_bytes(b"fake output")
            return subprocess.CompletedProcess(
                args=["node"], returncode=0, stdout=f"written {cli_format}\n", stderr=""
            )
        return subprocess.CompletedProcess(
            args=["node"],
            returncode=self._force_returncode or 1,
            stdout="",
            stderr=f"render {cli_format} failed",
        )


def _build_orch(
    bot: _StubBot,
    *,
    pipeline: _StubSourcePipeline | None = None,
    builder: _StubMatrixBuilder | None = None,
    interview: _StubInterviewEngine | None = None,
    design: _StubDesignPass | None = None,
    editorial: _StubEditorialPass | None = None,
    worker: _StubWorkerRunner | None = None,
    storage: Any = None,
    image_pass: Any = None,
) -> tuple[PresentationOrchestrator, DatabaseClient, CreditLedger, FakeSupabaseClient]:
    db, fake, credits = _make_db()
    orch = PresentationOrchestrator(
        bot=cast(Any, bot),
        db=db,
        credits=credits,
        storage=storage,
        source_pipeline=cast(
            Any, pipeline if pipeline is not None else _StubSourcePipeline([_pipeline_result()])
        ),
        matrix_builder=cast(Any, builder if builder is not None else _StubMatrixBuilder()),
        interview_engine=cast(Any, interview if interview is not None else _StubInterviewEngine()),
        design_pass=cast(Any, design if design is not None else _StubDesignPass()),
        editorial_pass=cast(Any, editorial if editorial is not None else _StubEditorialPass()),
        worker_runner=cast(Any, worker if worker is not None else _StubWorkerRunner()),
        image_pass=image_pass,
    )
    return orch, db, credits, fake


async def _noop_progress(_name: str, _step: int, _total: int) -> None:
    return None


# ---------------------------------------------------------------------------
# Step 1 — process_sources
# ---------------------------------------------------------------------------


async def test_process_sources_downloads_and_parses_each_file() -> None:
    bot = _StubBot(payloads={"f1": b"pdf1", "f2": b"pdf2"})
    pipeline = _StubSourcePipeline([_pipeline_result(), _pipeline_result()])
    orch, _db, _credits, fake = _build_orch(bot, pipeline=pipeline)

    file_infos: list[dict[str, object]] = [
        {"file_id": "f1", "filename": "a.pdf", "file_size": 100, "file_type": "pdf"},
        {"file_id": "f2", "filename": "b.pdf", "file_size": 200, "file_type": "pdf"},
    ]

    result = await orch.process_sources(file_infos, PROJECT_ID, USER_ID, _noop_progress)

    assert bot.downloaded == ["f1", "f2"]
    assert len(pipeline.calls) == 2
    assert len(result.claims) == 2
    # One free credit per successful source.
    free_rows = [r for r in fake.tables.get("credit_ledger", []) if r["action"] == "grant_free"]
    assert len(free_rows) == 2


async def test_process_sources_skips_failed_source_but_keeps_good_one() -> None:
    bot = _StubBot(payloads={"f1": b"pdf1", "f2": b"pdf2"})
    pipeline = _StubSourcePipeline([_pipeline_result(), RuntimeError("parser exploded")])
    orch, _db, _credits, _fake = _build_orch(bot, pipeline=pipeline)

    file_infos: list[dict[str, object]] = [
        {"file_id": "f1", "filename": "a.pdf", "file_type": "pdf"},
        {"file_id": "f2", "filename": "b.pdf", "file_type": "pdf"},
    ]
    result = await orch.process_sources(file_infos, PROJECT_ID, USER_ID, _noop_progress)

    assert len(result.claims) == 1
    assert any("b.pdf" in w for w in result.warnings)


async def test_process_sources_raises_when_no_content_extracted() -> None:
    bot = _StubBot(payloads={"f1": b"x"})
    pipeline = _StubSourcePipeline([RuntimeError("boom")])
    orch, _db, _credits, _fake = _build_orch(bot, pipeline=pipeline)

    with pytest.raises(ValueError, match="No usable content"):
        await orch.process_sources(
            [{"file_id": "f1", "filename": "a.pdf", "file_type": "pdf"}],
            PROJECT_ID,
            USER_ID,
            _noop_progress,
        )


async def test_process_sources_emits_progress_step_1() -> None:
    bot = _StubBot(payloads={"f1": b"pdf"})
    pipeline = _StubSourcePipeline([_pipeline_result()])
    orch, _, _, _ = _build_orch(bot, pipeline=pipeline)
    seen: list[tuple[str, int, int]] = []

    async def progress(name: str, step: int, total: int) -> None:
        seen.append((name, step, total))

    await orch.process_sources(
        [{"file_id": "f1", "filename": "a.pdf", "file_type": "pdf"}],
        PROJECT_ID,
        USER_ID,
        progress,
    )
    assert seen and seen[0] == ("Processing sources", 1, TOTAL_STEPS)


# ---------------------------------------------------------------------------
# Step 2 — build_evidence_matrix
# ---------------------------------------------------------------------------


async def test_build_evidence_matrix_passes_uuid_to_builder() -> None:
    bot = _StubBot()
    builder = _StubMatrixBuilder()
    orch, _, _, _ = _build_orch(bot, builder=builder)
    sources = SourceProcessingResult(claims=[_claim()], chunks=[_chunk()])

    matrix = await orch.build_evidence_matrix(sources, PROJECT_ID, _noop_progress)

    assert len(matrix.entries) == 1
    assert isinstance(builder.build_calls[0]["project_id"], UUID)
    assert builder.build_calls[0]["project_id"] == UUID(PROJECT_ID)


async def test_build_evidence_matrix_invents_uuid_on_bad_input() -> None:
    bot = _StubBot()
    builder = _StubMatrixBuilder()
    orch, _, _, _ = _build_orch(bot, builder=builder)
    sources = SourceProcessingResult(claims=[_claim()], chunks=[_chunk()])

    await orch.build_evidence_matrix(sources, "not-a-uuid", _noop_progress)
    assert isinstance(builder.build_calls[0]["project_id"], UUID)


# ---------------------------------------------------------------------------
# Step 3 — apply_interview
# ---------------------------------------------------------------------------


async def test_apply_interview_with_answers_calls_apply_answers() -> None:
    bot = _StubBot()
    interview = _StubInterviewEngine()
    orch, _, _, _ = _build_orch(bot, interview=interview)
    sources = SourceProcessingResult(claims=[_claim()], chunks=[_chunk()])

    answers = await orch.apply_interview(
        raw_answers={"audience": "undergraduate", "duration": 20},
        sources=sources,
        language="uz",
        progress=_noop_progress,
    )

    assert isinstance(answers, PresentationInterviewAnswers)
    assert len(interview.apply_answers_calls) == 1
    assert interview.apply_defaults_calls == []
    # questions must be generated first so the engine has context
    assert len(interview.generate_questions_calls) == 1


async def test_apply_interview_skip_uses_apply_defaults() -> None:
    bot = _StubBot()
    interview = _StubInterviewEngine()
    orch, _, _, _ = _build_orch(bot, interview=interview)
    sources = SourceProcessingResult(claims=[_claim()], chunks=[_chunk()])

    await orch.apply_interview(
        raw_answers=None,
        sources=sources,
        language="uz",
        progress=_noop_progress,
    )

    assert len(interview.apply_defaults_calls) == 1
    assert interview.apply_answers_calls == []


# ---------------------------------------------------------------------------
# Step 4 — generate_design
# ---------------------------------------------------------------------------


async def test_generate_design_uses_interview_and_claims() -> None:
    bot = _StubBot()
    design = _StubDesignPass()
    orch, _, _, _ = _build_orch(bot, design=design)
    sources = SourceProcessingResult(claims=[_claim()], chunks=[_chunk()])

    spec = await orch.generate_design(_interview_answers(), sources, _noop_progress)

    assert isinstance(spec, DesignDirectionSpec)
    assert len(design.calls) == 1
    assert design.calls[0]["interview"].audience is AudienceType.UNDERGRADUATE
    assert design.calls[0]["claims"] == sources.claims


# ---------------------------------------------------------------------------
# Step 5 — generate_deck_spec
# ---------------------------------------------------------------------------


async def test_generate_deck_spec_passes_inputs_to_editorial() -> None:
    bot = _StubBot()
    editorial = _StubEditorialPass()
    orch, _, _, _ = _build_orch(bot, editorial=editorial)
    sources = SourceProcessingResult(claims=[_claim()], chunks=[_chunk()])
    matrix = EvidenceMatrix(project_id=UUID(PROJECT_ID), entries=[])

    deck = await orch.generate_deck_spec(
        interview=_interview_answers(),
        design=_design_spec(),
        matrix=matrix,
        sources=sources,
        project_id=PROJECT_ID,
        progress=_noop_progress,
    )

    assert isinstance(deck, DeckSpec)
    assert editorial.calls[0]["outline"] is None
    assert editorial.calls[0]["project_id"] == PROJECT_ID


async def test_generate_deck_spec_propagates_editorial_failure() -> None:
    from packages.bot.orchestrators.article_orchestrator import _OrchestratorError

    bot = _StubBot()
    editorial = _StubEditorialPass(raises=RuntimeError("LLM down"))
    orch, _, _, _ = _build_orch(bot, editorial=editorial)
    sources = SourceProcessingResult(claims=[_claim()], chunks=[_chunk()])

    with pytest.raises(_OrchestratorError) as info:
        await orch.generate_deck_spec(
            interview=_interview_answers(),
            design=_design_spec(),
            matrix=EvidenceMatrix(project_id=UUID(PROJECT_ID), entries=[]),
            sources=sources,
            project_id=PROJECT_ID,
            progress=_noop_progress,
        )
    assert info.value.step == "editorial"
    assert isinstance(info.value.original, RuntimeError)
    assert "LLM down" in str(info.value.original)


# ---------------------------------------------------------------------------
# Step 6 — render
# ---------------------------------------------------------------------------


async def test_render_returns_paths_for_successful_formats() -> None:
    bot = _StubBot()
    worker = _StubWorkerRunner(formats_to_succeed=("html", "pptx"))
    orch, _, _, _ = _build_orch(bot, worker=worker)

    result = await orch.render(
        _deck_spec(),
        [ExportFormat.HTML, ExportFormat.PPTX_EDITABLE],
        _noop_progress,
    )

    assert result.html_path is not None and result.html_path.exists()
    assert result.pptx_path is not None and result.pptx_path.exists()
    assert result.pdf_path is None
    assert len(worker.render_calls) == 2


async def test_render_uploads_to_storage_with_project_id_namespace() -> None:
    """When R2 storage is configured, render uploads using project_id-namespaced keys.

    Catches regressions where the orchestrator falls back to the rendered
    file's stem (the deck title) and collides with other projects.
    """

    from unittest.mock import AsyncMock, MagicMock

    bot = _StubBot()
    worker = _StubWorkerRunner(formats_to_succeed=("html", "pptx"))

    storage_stub = MagicMock()
    storage_stub.available = True
    storage_stub.upload = AsyncMock(return_value="")

    orch, _, _, _ = _build_orch(bot, worker=worker, storage=storage_stub)

    await orch.render(
        _deck_spec(),
        [ExportFormat.HTML, ExportFormat.PPTX_EDITABLE],
        _noop_progress,
        project_id=PROJECT_ID,
    )

    assert storage_stub.upload.await_count == 2
    keys = [call.args[1] for call in storage_stub.upload.await_args_list]
    for key in keys:
        assert key.startswith(f"generated/{PROJECT_ID}/")


async def test_render_records_timeout_as_warning_and_continues() -> None:
    bot = _StubBot()
    worker = _StubWorkerRunner(
        formats_to_succeed=("html",),
        timeout_on=("pptx",),
    )
    orch, _, _, _ = _build_orch(bot, worker=worker)

    result = await orch.render(
        _deck_spec(),
        [ExportFormat.HTML, ExportFormat.PPTX_EDITABLE],
        _noop_progress,
    )

    assert result.html_path is not None
    assert result.pptx_path is None
    assert any("timed out" in w for w in result.warnings)


async def test_render_records_nonzero_exit_as_warning() -> None:
    bot = _StubBot()
    worker = _StubWorkerRunner(formats_to_succeed=("html",), force_returncode=1)
    orch, _, _, _ = _build_orch(bot, worker=worker)

    result = await orch.render(_deck_spec(), [ExportFormat.HTML], _noop_progress)

    assert result.html_path is None
    assert any("html" in w for w in result.warnings)


async def test_render_calls_ensure_built_once() -> None:
    bot = _StubBot()
    worker = _StubWorkerRunner(formats_to_succeed=("html", "pptx"))
    orch, _, _, _ = _build_orch(bot, worker=worker)

    await orch.render(
        _deck_spec(),
        [ExportFormat.HTML, ExportFormat.PPTX_EDITABLE],
        _noop_progress,
    )
    assert worker.ensure_calls == 1


async def test_render_propagates_build_failure() -> None:
    from packages.bot.orchestrators.article_orchestrator import _OrchestratorError

    bot = _StubBot()
    worker = _StubWorkerRunner(raise_on_ensure=RuntimeError("npm build failed"))
    orch, _, _, _ = _build_orch(bot, worker=worker)

    with pytest.raises(_OrchestratorError) as info:
        await orch.render(_deck_spec(), [ExportFormat.HTML], _noop_progress)
    assert info.value.step == "render_prepare"
    assert isinstance(info.value.original, RuntimeError)
    assert "npm build failed" in str(info.value.original)


# ---------------------------------------------------------------------------
# run_full_pipeline
# ---------------------------------------------------------------------------


async def test_full_pipeline_emits_seven_progress_steps() -> None:
    bot = _StubBot(payloads={"f1": b"pdf"})
    pipeline = _StubSourcePipeline([_pipeline_result()])
    worker = _StubWorkerRunner(formats_to_succeed=("html", "pptx"))
    orch, _, _, _ = _build_orch(bot, pipeline=pipeline, worker=worker)
    seen_steps: list[int] = []

    async def progress(_name: str, step: int, total: int) -> None:
        assert total == TOTAL_STEPS
        seen_steps.append(step)

    result = await orch.run_full_pipeline(
        file_infos=[{"file_id": "f1", "filename": "a.pdf", "file_type": "pdf"}],
        project_id=PROJECT_ID,
        user_id=USER_ID,
        language="uz",
        raw_answers=None,
        requested_formats=None,
        progress=progress,
        package=GenerationPackage.PRESENTATION_STANDARD,
    )

    assert isinstance(result, PresentationRenderResult)
    assert result.html_path is not None
    # source → matrix → interview → design → editorial → images → render
    assert seen_steps == [1, 2, 3, 4, 5, 6, 7]


async def test_full_pipeline_uses_defaults_when_no_answers() -> None:
    bot = _StubBot(payloads={"f1": b"pdf"})
    interview = _StubInterviewEngine()
    worker = _StubWorkerRunner(formats_to_succeed=("html",))
    orch, _, _, _ = _build_orch(bot, interview=interview, worker=worker)

    await orch.run_full_pipeline(
        file_infos=[{"file_id": "f1", "filename": "a.pdf", "file_type": "pdf"}],
        project_id=PROJECT_ID,
        user_id=USER_ID,
        language="uz",
        raw_answers=None,
        requested_formats=[ExportFormat.HTML],
        progress=_noop_progress,
        package=GenerationPackage.PRESENTATION_STANDARD,
    )

    assert interview.apply_defaults_calls and not interview.apply_answers_calls


async def test_full_pipeline_propagates_editorial_failure() -> None:
    from packages.bot.orchestrators.article_orchestrator import _OrchestratorError

    bot = _StubBot(payloads={"f1": b"pdf"})
    editorial = _StubEditorialPass(raises=RuntimeError("LLM unreachable"))
    orch, _, _, _ = _build_orch(bot, editorial=editorial)

    with pytest.raises(_OrchestratorError) as info:
        await orch.run_full_pipeline(
            file_infos=[{"file_id": "f1", "filename": "a.pdf", "file_type": "pdf"}],
            project_id=PROJECT_ID,
            user_id=USER_ID,
            language="uz",
            raw_answers=None,
            requested_formats=[ExportFormat.HTML],
            progress=_noop_progress,
            package=GenerationPackage.PRESENTATION_STANDARD,
        )
    assert info.value.step == "editorial"


# ---------------------------------------------------------------------------
# Tier → image budget wire (invariant I1)
# ---------------------------------------------------------------------------


class _SpyImagePass:
    """Records the ``max_generated_images`` and ``only_slide_ids`` per call."""

    def __init__(self) -> None:
        self.resolve_calls: list[int | None] = []
        self.scope_calls: list[frozenset[str] | None] = []

    async def resolve_deck(
        self,
        deck: DeckSpec,
        *,
        storage: Any,
        project_id: str,
        figures: list[Any],
        max_generated_images: int | None = None,
        only_slide_ids: frozenset[str] | None = None,
    ) -> DeckSpec:
        del storage, project_id, figures
        self.resolve_calls.append(max_generated_images)
        self.scope_calls.append(only_slide_ids)
        return deck


@pytest.mark.parametrize(
    ("package", "expected_budget"),
    [
        (GenerationPackage.PRESENTATION_BASIC, 0),
        (GenerationPackage.PRESENTATION_STANDARD, 2),
        (GenerationPackage.PRESENTATION_PREMIUM, 5),
    ],
)
async def test_full_pipeline_threads_package_to_image_budget(
    package: GenerationPackage, expected_budget: int
) -> None:
    """Invariant I1: the paid tier MUST set the per-deck image budget.

    This test fails on any code that lets the budget default in the
    orchestrator (the bug the image-engine fix corrects). The spy records
    exactly what the orchestrator passed to ``ImagePass.resolve_deck`` and
    the SPEC budgets (0/2/5) must round-trip.
    """

    from unittest.mock import MagicMock

    bot = _StubBot(payloads={"f1": b"pdf"})
    worker = _StubWorkerRunner(formats_to_succeed=("html",))
    storage_stub = MagicMock()
    storage_stub.available = False  # disables _upload_rendered, keeps render local
    spy = _SpyImagePass()
    orch, _, _, _ = _build_orch(bot, worker=worker, storage=storage_stub, image_pass=spy)

    await orch.run_full_pipeline(
        file_infos=[{"file_id": "f1", "filename": "a.pdf", "file_type": "pdf"}],
        project_id=PROJECT_ID,
        user_id=USER_ID,
        language="uz",
        raw_answers=None,
        requested_formats=[ExportFormat.HTML],
        progress=_noop_progress,
        package=package,
    )

    assert spy.resolve_calls == [expected_budget]


async def test_full_pipeline_premium_image_budget_strictly_exceeds_standard() -> None:
    """The headline regression: premium > standard observable in the wire.

    Captures the budget for both tiers from the same orchestrator harness and
    asserts strict inequality. The whole point of charging more for premium
    is more images; if this passes on a build where premium == standard, the
    test is wrong, not the code.
    """

    from unittest.mock import MagicMock

    async def _run(package: GenerationPackage) -> int | None:
        bot = _StubBot(payloads={"f1": b"pdf"})
        worker = _StubWorkerRunner(formats_to_succeed=("html",))
        storage_stub = MagicMock()
        storage_stub.available = False
        spy = _SpyImagePass()
        orch, _, _, _ = _build_orch(bot, worker=worker, storage=storage_stub, image_pass=spy)
        await orch.run_full_pipeline(
            file_infos=[{"file_id": "f1", "filename": "a.pdf", "file_type": "pdf"}],
            project_id=PROJECT_ID,
            user_id=USER_ID,
            language="uz",
            raw_answers=None,
            requested_formats=[ExportFormat.HTML],
            progress=_noop_progress,
            package=package,
        )
        assert len(spy.resolve_calls) == 1
        return spy.resolve_calls[0]

    standard = await _run(GenerationPackage.PRESENTATION_STANDARD)
    premium = await _run(GenerationPackage.PRESENTATION_PREMIUM)
    assert standard is not None and premium is not None
    assert premium > standard


# ---------------------------------------------------------------------------
# PresentationRenderResult.by_extension
# ---------------------------------------------------------------------------


def test_render_result_by_extension_includes_only_present_paths(tmp_path: Path) -> None:
    html_path = tmp_path / "a.html"
    html_path.write_bytes(b"html")
    result = PresentationRenderResult(html_path=html_path)
    mapping = result.by_extension()
    assert set(mapping.keys()) == {"html"}
    assert mapping["html"] == html_path


# ---------------------------------------------------------------------------
# Single-slide regeneration wiring (regenerate_slide)
#
# The orchestrator method is thin glue over the editorial regen + splice and the
# image stage (both tested in depth elsewhere); these pin the WIRING — that it
# splices, runs the section-scoped re-check, combines findings, re-resolves
# images on the tier budget, and propagates the typed error unwrapped.
# ---------------------------------------------------------------------------


class _StubRegenEditorial:
    """Canned content-regen plus the real id-keyed splice, for wiring tests."""

    def __init__(self, result: SlideRegenResult, *, raises: Exception | None = None) -> None:
        self.result = result
        self._raises = raises
        self.regen_calls: list[dict[str, Any]] = []
        self.splice_calls: list[str] = []
        # Delegate the splice to the REAL EditorialPass so the wiring test exercises
        # genuine title propagation (no LLM is needed — splice_regenerated_slide is a
        # pure deck->deck transform).
        self._real = EditorialPass()

    async def regenerate_slide_content(
        self,
        deck: DeckSpec,
        slide_id: str,
        *,
        instruction: str | None = None,
        claims: Any,
    ) -> SlideRegenResult:
        del deck
        self.regen_calls.append(
            {"slide_id": slide_id, "instruction": instruction, "claims": list(claims)}
        )
        if self._raises is not None:
            raise self._raises
        return self.result

    def splice_regenerated_slide(self, deck: DeckSpec, new_slide: SlideSpec) -> DeckSpec:
        self.splice_calls.append(new_slide.slide_id)
        return self._real.splice_regenerated_slide(deck, new_slide)


def _regen_deck() -> DeckSpec:
    plan = DeckPlan(
        thesis="A clear deck thesis long enough to pass validation.",
        audience_takeaway="The audience leaves with the core argument.",
        sections=[
            PlannedSection(
                section_name="Origins",
                thesis="It began as a concrete reaction to a cause.",
                phase=NarrativePhase.HOOK,
                figure_names=["Voltaire"],
            ),
            PlannedSection(
                section_name="Legacy",
                thesis="Its ideas reshaped institutions that still stand.",
                phase=NarrativePhase.CLOSE,
            ),
        ],
        figures=[PlannedFigure(name="Voltaire", why_in_source="the source names Voltaire")],
        image_cohesion_note="One cohesive visual voice across every slide.",
    )
    slides = [
        SlideSpec(
            slide_id="hero",
            slide_index=0,
            slide_type=SlideType.TITLE_HERO,
            content=SlideContent(title="The Enlightenment"),
            section_name="Origins",
            section_thesis=plan.sections[0].thesis,
        ),
        SlideSpec(
            slide_id="gallery",
            slide_index=1,
            slide_type=SlideType.GALLERY_PEOPLE,
            content=SlideContent(title="Thinkers", people=[PersonItem(name="Voltaire")]),
            section_name="Origins",
            section_thesis=plan.sections[0].thesis,
        ),
        SlideSpec(
            slide_id="end",
            slide_index=2,
            slide_type=SlideType.SUMMARY_TAKEAWAY,
            content=SlideContent(title="Legacy", bullets=["One concrete lesson."]),
            section_name="Legacy",
            section_thesis=plan.sections[1].thesis,
        ),
    ]
    return DeckSpec(
        project_id=PROJECT_ID,
        title="The Enlightenment",
        design=_design_spec(),
        interview=_interview_answers(),
        plan=plan,
        slides=slides,
    )


async def test_regenerate_slide_chains_splice_and_image_resolution() -> None:
    from unittest.mock import MagicMock

    deck = _regen_deck()
    new_slide = deck.slides[1].model_copy(
        update={
            "content": SlideContent(title="Sharper thinkers", people=[PersonItem(name="Voltaire")])
        }
    )
    editorial = _StubRegenEditorial(SlideRegenResult(slide=new_slide, findings=[]))
    storage_stub = MagicMock()
    storage_stub.available = False
    spy = _SpyImagePass()
    orch, _, _, _ = _build_orch(
        _StubBot(payloads={}), editorial=cast(Any, editorial), storage=storage_stub, image_pass=spy
    )
    sources = SourceProcessingResult(claims=[_claim()], chunks=[_chunk()])

    new_deck, outcome = await orch.regenerate_slide(
        deck,
        "gallery",
        sources,
        PROJECT_ID,
        _noop_progress,
        package=GenerationPackage.PRESENTATION_STANDARD,
        instruction="punchier",
    )

    assert editorial.regen_calls[0]["slide_id"] == "gallery"
    assert editorial.regen_calls[0]["instruction"] == "punchier"
    assert editorial.splice_calls == ["gallery"]
    assert new_deck.slides[1].content.title == "Sharper thinkers"  # spliced in place
    assert spy.resolve_calls == [2]  # images re-resolved on the STANDARD tier budget
    assert spy.scope_calls == [frozenset({"gallery"})]  # scoped to the regenerated slide ONLY
    assert outcome.passed  # no findings


async def test_regenerate_hero_through_orchestrator_updates_deck_title() -> None:
    from unittest.mock import MagicMock

    deck = _regen_deck()
    hero = deck.slides[0]  # TITLE_HERO at position 0
    new_hero = hero.model_copy(
        update={"content": SlideContent(title="A bolder headline", subtitle="With a subtitle")}
    )
    editorial = _StubRegenEditorial(SlideRegenResult(slide=new_hero, findings=[]))
    storage_stub = MagicMock()
    storage_stub.available = False
    orch, _, _, _ = _build_orch(
        _StubBot(payloads={}),
        editorial=cast(Any, editorial),
        storage=storage_stub,
        image_pass=_SpyImagePass(),
    )
    sources = SourceProcessingResult(claims=[_claim()], chunks=[_chunk()])

    new_deck, _outcome = await orch.regenerate_slide(
        deck,
        "hero",
        sources,
        PROJECT_ID,
        _noop_progress,
        package=GenerationPackage.PRESENTATION_STANDARD,
    )

    # The real splice runs through the orchestrator, so the deck title tracks the hero.
    assert new_deck.title == "A bolder headline"
    assert new_deck.subtitle == "With a subtitle"
    assert new_deck.slides[0].content.title == "A bolder headline"


async def test_regenerate_slide_surfaces_section_scoped_dropped_figure() -> None:
    from unittest.mock import MagicMock

    deck = _regen_deck()
    # The regenerated gallery drops Voltaire — the Origins section's only portrayal.
    dropped = deck.slides[1].model_copy(update={"content": SlideContent(title="Empty gallery")})
    editorial = _StubRegenEditorial(SlideRegenResult(slide=dropped, findings=[]))
    storage_stub = MagicMock()
    storage_stub.available = False
    orch, _, _, _ = _build_orch(
        _StubBot(payloads={}),
        editorial=cast(Any, editorial),
        storage=storage_stub,
        image_pass=_SpyImagePass(),
    )
    sources = SourceProcessingResult(claims=[_claim()], chunks=[_chunk()])

    _new_deck, outcome = await orch.regenerate_slide(
        deck,
        "gallery",
        sources,
        PROJECT_ID,
        _noop_progress,
        package=GenerationPackage.PRESENTATION_STANDARD,
    )

    assert not outcome.passed
    assert any(f.check_id == "D-F1" for f in outcome.findings)  # section re-check caught it


async def test_regenerate_slide_propagates_editorial_error_unwrapped() -> None:
    from unittest.mock import MagicMock

    deck = _regen_deck()
    editorial = _StubRegenEditorial(
        SlideRegenResult(slide=deck.slides[1]), raises=EditorialSlideRegenError("boom")
    )
    storage_stub = MagicMock()
    storage_stub.available = False
    orch, _, _, _ = _build_orch(
        _StubBot(payloads={}),
        editorial=cast(Any, editorial),
        storage=storage_stub,
        image_pass=_SpyImagePass(),
    )
    sources = SourceProcessingResult(claims=[_claim()], chunks=[_chunk()])

    with pytest.raises(EditorialSlideRegenError):
        await orch.regenerate_slide(
            deck,
            "gallery",
            sources,
            PROJECT_ID,
            _noop_progress,
            package=GenerationPackage.PRESENTATION_STANDARD,
        )
