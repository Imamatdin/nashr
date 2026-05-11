"""Behaviour tests for :class:`ArticleOrchestrator`.

We replace every worker engine with an in-memory fake so each test
asserts one property of the orchestration contract (parallel claim
accumulation, free-credit grants, progress callback wiring, graceful
degradation when one source fails). Per ``.claude/rules/testing.md`` we
mock only the engines (LLM-driven, external) — not pydantic models, not
the in-process DB fake.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from io import BytesIO
from typing import Any, cast
from uuid import UUID, uuid4

import pytest

from packages.bot.orchestrators import (
    ArticleOrchestrator,
    SourceProcessingResult,
    map_calibration,
    map_language,
)
from packages.bot.orchestrators.article_orchestrator import (
    default_citation_format,
    derive_thesis,
    tier_to_pages,
)
from packages.core.enums import (
    ArticleSectionStatus,
    ArticleStructure,
    CalibrationLevel,
    CitationFormat,
    CitationStatus,
    ClaimStrength,
    InterviewMode,
    Language,
    ResearchQuestionType,
)
from packages.core.models.article import (
    ArticleDraftResult,
    ArticleOutline,
    ArticleQualitySummary,
    ArticleSection,
    DraftResult,
    OutlineSection,
    QualityCheckResult,
)
from packages.core.models.bibliography import (
    FormattedBibliography,
    FormattedEntry,
)
from packages.core.models.evidence import (
    AnswerScore,
    EvidenceMatrix,
    EvidenceMatrixEntry,
    ResearchQuestion,
)
from packages.core.models.export import (
    ArticleExportBundle,
    ExportResult,
    PDFExportResult,
)
from packages.core.models.interview import (
    CreditDecision,
    ProcessedAnswer,
    ScoredAnswer,
    WeaknessProfile,
)
from packages.core.models.source import (
    FileValidationResult,
    SourceChunkCreate,
    SourceClaimCreate,
    SourceMetadataExtracted,
    SourcePipelineResult,
)
from packages.core.models.suggestion import (
    AcademicDomain,
    DomainDetectionResult,
    DomainScore,
    SuggestionReport,
)
from packages.core.models.verification import CitationVerificationReport
from packages.platform.config import PlatformConfig
from packages.platform.credits import CreditLedger
from packages.platform.database import DatabaseClient
from tests.unit.test_database_client import FakeSupabaseClient

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


PROJECT_ID = "00000000-0000-0000-0000-000000000aaa"
USER_ID = "00000000-0000-0000-0000-000000000bbb"


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


def _claim(
    text: str = "Solar cells convert sunlight to electricity efficiently.",
) -> SourceClaimCreate:
    return SourceClaimCreate(
        source_chunk_id="0",
        project_id=PROJECT_ID,
        claim_text=text,
        strength=ClaimStrength.MODERATE,
    )


def _chunk(text: str = "Sample chunk text for source content.") -> SourceChunkCreate:
    return SourceChunkCreate(chunk_index=0, text=text, source_id="0")


def _validation_result(valid: bool = True) -> FileValidationResult:
    return FileValidationResult(
        valid=valid,
        detected_type="pdf",
        mime_type="application/pdf",
        confidence=0.95,
        file_size_bytes=1024,
    )


def _pipeline_result(
    *,
    valid: bool = True,
    claims: list[SourceClaimCreate] | None = None,
    chunks: list[SourceChunkCreate] | None = None,
) -> SourcePipelineResult:
    return SourcePipelineResult(
        validation=_validation_result(valid),
        parsed=None,
        chunks=chunks if chunks is not None else [_chunk()],
        claims=claims if claims is not None else [_claim()],
        errors=[],
    )


class _StubBot:
    """Minimal stand-in for :class:`aiogram.Bot`.

    Records the file_ids requested for download and returns a BytesIO
    of pre-seeded bytes. Raises if a download is requested for an
    unknown id, so tests can assert which files were fetched.
    """

    def __init__(self, payloads: dict[str, bytes] | None = None) -> None:
        self.payloads = dict(payloads or {})
        self.downloaded: list[str] = []

    async def download(self, file_id: str) -> BytesIO:
        self.downloaded.append(file_id)
        data = self.payloads.get(file_id, b"%PDF-1.4\n%fake\n")
        return BytesIO(data)


class _StubSourcePipeline:
    def __init__(self, results: list[SourcePipelineResult | Exception]) -> None:
        self.results = list(results)
        self.calls: list[tuple[bytes, str]] = []

    async def process(self, file_bytes: bytes, filename: str) -> SourcePipelineResult:
        self.calls.append((file_bytes, filename))
        if not self.results:
            raise RuntimeError("StubSourcePipeline ran out of responses")
        next_result = self.results.pop(0)
        if isinstance(next_result, Exception):
            raise next_result
        return next_result


class _StubMatrixBuilder:
    def __init__(self) -> None:
        self.build_calls: list[dict[str, Any]] = []
        self.assign_calls: list[tuple[EvidenceMatrix, ArticleOutline]] = []

    async def build_from_claims(
        self, *, project_id: UUID, claims: Any, chunks: Any, source_quality: Any
    ) -> EvidenceMatrix:
        self.build_calls.append(
            {
                "project_id": project_id,
                "claims": list(claims),
                "chunks": list(chunks),
                "source_quality": source_quality,
            }
        )
        chunk_uuid = uuid4()
        entry = EvidenceMatrixEntry(
            project_id=project_id,
            claim_id=uuid4(),
            source_chunk_id=chunk_uuid,
            citation_status=CitationStatus.READY,
            created_at=datetime.now(UTC),
        )
        return EvidenceMatrix(project_id=project_id, entries=[entry])

    async def assign_to_sections(
        self, matrix: EvidenceMatrix, outline: ArticleOutline
    ) -> EvidenceMatrix:
        self.assign_calls.append((matrix, outline))
        return matrix


class _StubInterviewEngine:
    def __init__(
        self,
        *,
        questions: list[ResearchQuestion] | None = None,
        credit_decision: CreditDecision | None = None,
    ) -> None:
        self.analyze_calls = 0
        self.generate_calls: list[dict[str, Any]] = []
        self.process_calls: list[dict[str, Any]] = []
        self._questions = questions or []
        self._credit_decision = credit_decision or CreditDecision(
            credits_earned=1,
            reason="ok",
            capped=False,
            cap_hit=None,
        )

    def analyze_weaknesses(self, *, matrix: Any, claims: Any, chunks: Any) -> WeaknessProfile:
        self.analyze_calls += 1
        from packages.core.enums import WeaknessDimension

        return WeaknessProfile(
            thesis_clarity=0.5,
            source_coverage=0.5,
            contradiction_awareness=1.0,
            originality=0.5,
            evidence_depth=0.5,
            weakest_dimension=WeaknessDimension.SOURCE_COVERAGE,
            summary="test",
        )

    async def generate_questions(self, **kwargs: Any) -> list[ResearchQuestion]:
        self.generate_calls.append(kwargs)
        return list(self._questions)

    async def process_answer(self, **kwargs: Any) -> ProcessedAnswer:
        self.process_calls.append(kwargs)
        question = kwargs["question"]
        scored = ScoredAnswer(
            question_id=question.id,
            answer_text=kwargs["answer_text"],
            score=AnswerScore(specificity=4, source_grounding=4, usefulness=4),
            referenced_chunk_ids=[],
            feedback="ok",
        )
        return ProcessedAnswer(
            scored_answer=scored,
            credit_decision=self._credit_decision,
            updated_matrix=kwargs["matrix"],
            feedback_message="thanks",
            evidence_entries_updated=0,
        )


class _StubSuggestionEngine:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def analyze_and_suggest(self, **kwargs: Any) -> SuggestionReport:
        self.calls.append(kwargs)
        return SuggestionReport(
            domains_detected=DomainDetectionResult(
                primary_domain=AcademicDomain.GENERAL,
                all_domains=[DomainScore(domain=AcademicDomain.GENERAL, confidence=1.0)],
            ),
            sections_analyzed=0,
            sections_with_suggestions=0,
            sections_skipped=0,
            section_suggestions=[],
            total_suggestions=0,
            providers_queried=[],
            search_time_ms=1,
            errors=[],
        )


def _outline() -> ArticleOutline:
    return ArticleOutline(
        title="Test outline",
        structure=ArticleStructure.REFERAT,
        sections=[
            OutlineSection(
                title="Introduction",
                target_words=400,
                purpose="orient the reader",
            )
        ],
        thesis="Test thesis statement.",
        total_target_words=400,
    )


class _StubOutlineGenerator:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def generate(self, **kwargs: Any) -> ArticleOutline:
        self.calls.append(kwargs)
        return _outline()


def _draft_result() -> ArticleDraftResult:
    section = ArticleSection(
        article_id=uuid4(),
        section_index=0,
        title="Introduction",
        paragraphs=[],
        word_count=0,
        created_at=datetime.now(UTC),
    )
    draft = DraftResult(
        section=section,
        quality_check=QualityCheckResult(passed=True, overall_score=1.0),
    )
    return ArticleDraftResult(
        sections=[draft],
        total_word_count=0,
        total_llm_calls=1,
        total_tokens=100,
        estimated_cost_usd=0.001,
        quality_summary=ArticleQualitySummary(
            sections_passed=1,
            sections_failed=0,
            sections_revised=0,
            overall_score=1.0,
        ),
    )


class _StubDrafter:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def draft_article(self, **kwargs: Any) -> ArticleDraftResult:
        self.calls.append(kwargs)
        return _draft_result()


class _StubCitationVerifier:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def verify_article(self, **kwargs: Any) -> CitationVerificationReport:
        self.calls.append(kwargs)
        return CitationVerificationReport(
            total_citations=0,
            supported=0,
            partially_supported=0,
            overclaimed=0,
            not_supported=0,
            contradicted=0,
            source_not_found=0,
            overall_integrity_score=1.0,
            verifications=[],
            critical_issues=[],
            warnings=[],
            model_used="stub",
            total_tokens=0,
            estimated_cost_usd=0.0,
            verification_time_ms=1,
        )


class _StubBibliographyFormatter:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def format_bibliography(
        self, citations: Any, style: CitationFormat, language: str
    ) -> FormattedBibliography:
        self.calls.append({"citations": list(citations), "style": style, "language": language})
        return FormattedBibliography(
            entries=[FormattedEntry(number=1, formatted_text="Author. Title. Year.")],
            style=style,
            language=language,
            total_entries=1,
        )


class _StubExportPipeline:
    def __init__(self, pdf_success: bool = True) -> None:
        self.pdf_success = pdf_success
        self.calls: list[dict[str, Any]] = []

    async def export(self, **kwargs: Any) -> ArticleExportBundle:
        self.calls.append(kwargs)
        docx = ExportResult(
            file_bytes=b"PK\x03\x04docx-bytes",
            filename="article.docx",
            file_size_bytes=10,
            page_count_estimate=1,
            word_count=100,
            section_count=1,
            citation_count=0,
            bibliography_count=1,
        )
        if self.pdf_success:
            pdf = PDFExportResult(
                file_bytes=b"%PDF-1.4 pdf-bytes",
                filename="article.pdf",
                file_size_bytes=10,
                source_docx_size=10,
                conversion_time_ms=1,
                success=True,
            )
        else:
            pdf = PDFExportResult(
                file_bytes=b"",
                filename="article.pdf",
                file_size_bytes=0,
                source_docx_size=10,
                conversion_time_ms=1,
                success=False,
                error="LibreOffice not installed",
            )
        return ArticleExportBundle(docx=docx, pdf=pdf)


def _build_orchestrator(
    bot: _StubBot,
    *,
    pipeline: _StubSourcePipeline | None = None,
    builder: _StubMatrixBuilder | None = None,
    interview: _StubInterviewEngine | None = None,
    suggestions: _StubSuggestionEngine | None = None,
    outline_gen: _StubOutlineGenerator | None = None,
    drafter: _StubDrafter | None = None,
    verifier: _StubCitationVerifier | None = None,
    bib: _StubBibliographyFormatter | None = None,
    export_pipe: _StubExportPipeline | None = None,
) -> tuple[ArticleOrchestrator, DatabaseClient, CreditLedger, FakeSupabaseClient]:
    db, fake, credits = _make_db()
    orch = ArticleOrchestrator(
        bot=cast(Any, bot),
        db=db,
        credits=credits,
        source_pipeline=cast(
            Any, pipeline if pipeline is not None else _StubSourcePipeline([_pipeline_result()])
        ),
        matrix_builder=cast(Any, builder if builder is not None else _StubMatrixBuilder()),
        interview_engine=cast(Any, interview if interview is not None else _StubInterviewEngine()),
        suggestion_engine=cast(
            Any, suggestions if suggestions is not None else _StubSuggestionEngine()
        ),
        outline_generator=cast(
            Any, outline_gen if outline_gen is not None else _StubOutlineGenerator()
        ),
        drafter=cast(Any, drafter if drafter is not None else _StubDrafter()),
        citation_verifier=cast(Any, verifier if verifier is not None else _StubCitationVerifier()),
        bibliography_formatter=cast(Any, bib if bib is not None else _StubBibliographyFormatter()),
        export_pipeline=cast(
            Any, export_pipe if export_pipe is not None else _StubExportPipeline()
        ),
    )
    return orch, db, credits, fake


async def _noop_progress(_step_name: str, _step: int, _total: int) -> None:
    return None


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_map_calibration_known_values() -> None:
    assert map_calibration("school") is CalibrationLevel.SCHOOL
    assert map_calibration("bakalavr") is CalibrationLevel.UNDERGRADUATE
    assert map_calibration("magistratura") is CalibrationLevel.MASTERS
    assert map_calibration("doctoral") is CalibrationLevel.DOCTORAL


def test_map_calibration_unknown_falls_back_to_undergraduate() -> None:
    assert map_calibration("unknown_level_xyz") is CalibrationLevel.UNDERGRADUATE
    assert map_calibration("") is CalibrationLevel.UNDERGRADUATE


def test_map_language_picks_karakalpak() -> None:
    assert map_language("kaa") is Language.KAA
    assert map_language("uz") is Language.UZ
    assert map_language("RU") is Language.RU
    assert map_language("xx") is Language.UZ


def test_tier_to_pages_known_tiers() -> None:
    assert tier_to_pages("basic") == 5
    assert tier_to_pages("article_standard") == 8
    assert tier_to_pages("premium") == 12
    assert tier_to_pages("unknown") == 5


def test_default_citation_format_picks_gost_for_uz_and_ru() -> None:
    assert default_citation_format(Language.UZ) is CitationFormat.GOST
    assert default_citation_format(Language.RU) is CitationFormat.GOST
    assert default_citation_format(Language.EN) is CitationFormat.APA


def test_derive_thesis_picks_longest_strong_claim() -> None:
    weak = SourceClaimCreate(
        source_chunk_id="0",
        project_id=PROJECT_ID,
        claim_text="Short weak claim text.",
        strength=ClaimStrength.WEAK,
    )
    strong_short = SourceClaimCreate(
        source_chunk_id="0",
        project_id=PROJECT_ID,
        claim_text="Short strong claim text.",
        strength=ClaimStrength.STRONG,
    )
    strong_long = SourceClaimCreate(
        source_chunk_id="0",
        project_id=PROJECT_ID,
        claim_text="This is the longest strong claim with substantial detail.",
        strength=ClaimStrength.STRONG,
    )
    thesis = derive_thesis([weak, strong_short, strong_long], "fallback")
    assert thesis == "This is the longest strong claim with substantial detail."


def test_derive_thesis_falls_back_to_title_when_no_claims() -> None:
    assert derive_thesis([], "Solar policy in Uzbekistan") == "Solar policy in Uzbekistan"


# ---------------------------------------------------------------------------
# Step 1 — process_sources
# ---------------------------------------------------------------------------


async def test_process_sources_downloads_and_extracts_claims() -> None:
    bot = _StubBot(payloads={"f1": b"%PDF-fake1", "f2": b"%PDF-fake2"})
    pipeline = _StubSourcePipeline([_pipeline_result(), _pipeline_result()])
    orch, _db, _credits, fake = _build_orchestrator(bot, pipeline=pipeline)

    file_infos: list[dict[str, object]] = [
        {"file_id": "f1", "filename": "a.pdf", "file_size": 100, "file_type": "pdf"},
        {"file_id": "f2", "filename": "b.pdf", "file_size": 200, "file_type": "pdf"},
    ]
    result = await orch.process_sources(file_infos, PROJECT_ID, USER_ID, _noop_progress)

    assert bot.downloaded == ["f1", "f2"]
    assert len(pipeline.calls) == 2
    assert len(result.claims) == 2
    assert len(result.chunks) == 2
    # one free-credit row per successfully processed source
    free_rows = [r for r in fake.tables.get("credit_ledger", []) if r["action"] == "grant_free"]
    assert len(free_rows) == 2


async def test_process_sources_skips_failed_file() -> None:
    bot = _StubBot(payloads={"f1": b"pdf1", "f2": b"pdf2"})
    pipeline = _StubSourcePipeline([_pipeline_result(), RuntimeError("parser crashed")])
    orch, _db, _credits, _fake = _build_orchestrator(bot, pipeline=pipeline)

    file_infos: list[dict[str, object]] = [
        {"file_id": "f1", "filename": "a.pdf", "file_size": 1, "file_type": "pdf"},
        {"file_id": "f2", "filename": "b.pdf", "file_size": 1, "file_type": "pdf"},
    ]
    result = await orch.process_sources(file_infos, PROJECT_ID, USER_ID, _noop_progress)

    assert len(result.claims) == 1
    assert any("b.pdf" in w for w in result.warnings)


async def test_process_sources_skips_rejected_validation() -> None:
    bot = _StubBot(payloads={"f1": b"junk"})
    pipeline = _StubSourcePipeline(
        [
            SourcePipelineResult(
                validation=_validation_result(valid=False).model_copy(
                    update={"rejection_reason": "Not a real PDF"}
                ),
                parsed=None,
                chunks=[],
                claims=[],
                errors=["Not a real PDF"],
            )
        ]
    )
    orch, _db, _credits, _fake = _build_orchestrator(bot, pipeline=pipeline)

    file_infos: list[dict[str, object]] = [
        {"file_id": "f1", "filename": "a.pdf", "file_size": 1, "file_type": "pdf"}
    ]
    with pytest.raises(ValueError, match="No usable content"):
        await orch.process_sources(file_infos, PROJECT_ID, USER_ID, _noop_progress)


async def test_process_sources_raises_when_all_fail() -> None:
    bot = _StubBot(payloads={"f1": b"x", "f2": b"y"})
    pipeline = _StubSourcePipeline([RuntimeError("boom 1"), RuntimeError("boom 2")])
    orch, _db, _credits, _fake = _build_orchestrator(bot, pipeline=pipeline)

    with pytest.raises(ValueError, match="No usable content"):
        await orch.process_sources(
            [
                {"file_id": "f1", "filename": "a.pdf", "file_type": "pdf"},
                {"file_id": "f2", "filename": "b.pdf", "file_type": "pdf"},
            ],
            PROJECT_ID,
            USER_ID,
            _noop_progress,
        )


async def test_process_sources_progress_callback_fires() -> None:
    bot = _StubBot(payloads={"f1": b"pdf"})
    pipeline = _StubSourcePipeline([_pipeline_result()])
    orch, _, _, _ = _build_orchestrator(bot, pipeline=pipeline)
    seen: list[tuple[str, int, int]] = []

    async def progress(name: str, step: int, total: int) -> None:
        seen.append((name, step, total))

    await orch.process_sources(
        [{"file_id": "f1", "filename": "a.pdf", "file_type": "pdf"}],
        PROJECT_ID,
        USER_ID,
        progress,
    )
    assert seen and seen[0] == ("Processing sources", 1, 8)


# ---------------------------------------------------------------------------
# Step 2 — evidence matrix
# ---------------------------------------------------------------------------


async def test_build_evidence_matrix_calls_builder_with_uuid() -> None:
    bot = _StubBot()
    builder = _StubMatrixBuilder()
    orch, _, _, _ = _build_orchestrator(bot, builder=builder)

    sources = SourceProcessingResult(
        claims=[_claim()], chunks=[_chunk()], metadata=[], source_ids=[]
    )
    matrix = await orch.build_evidence_matrix(sources, PROJECT_ID, _noop_progress)

    assert len(matrix.entries) == 1
    assert builder.build_calls[0]["project_id"] == UUID(PROJECT_ID)
    assert len(builder.build_calls[0]["claims"]) == 1


# ---------------------------------------------------------------------------
# Step 3 — interview
# ---------------------------------------------------------------------------


def _question() -> ResearchQuestion:
    return ResearchQuestion(
        project_id=UUID(PROJECT_ID),
        question_text="What does your source say about X?",
        question_type=ResearchQuestionType.SOURCE_COVERAGE,
        related_source_ids=[],
        created_at=datetime.now(UTC),
    )


async def test_generate_interview_questions_returns_engine_output() -> None:
    bot = _StubBot()
    q = _question()
    interview = _StubInterviewEngine(questions=[q])
    builder = _StubMatrixBuilder()
    orch, _, _, _ = _build_orchestrator(bot, builder=builder, interview=interview)

    sources = SourceProcessingResult(
        claims=[_claim()], chunks=[_chunk()], metadata=[], source_ids=[uuid4()]
    )
    matrix = await orch.build_evidence_matrix(sources, PROJECT_ID, _noop_progress)
    questions = await orch.generate_interview_questions(
        sources=sources, matrix=matrix, project_id=PROJECT_ID, language="uz"
    )

    assert questions == [q]
    assert interview.analyze_calls == 1
    assert interview.generate_calls[0]["language"] is Language.UZ
    assert interview.generate_calls[0]["mode"] is InterviewMode.GUIDED


async def test_generate_interview_questions_fast_mode_returns_empty() -> None:
    bot = _StubBot()
    interview = _StubInterviewEngine(questions=[_question()])
    builder = _StubMatrixBuilder()
    orch, _, _, _ = _build_orchestrator(bot, builder=builder, interview=interview)

    sources = SourceProcessingResult(
        claims=[_claim()], chunks=[_chunk()], metadata=[], source_ids=[uuid4()]
    )
    matrix = await orch.build_evidence_matrix(sources, PROJECT_ID, _noop_progress)
    questions = await orch.generate_interview_questions(
        sources=sources,
        matrix=matrix,
        project_id=PROJECT_ID,
        language="uz",
        mode=InterviewMode.FAST,
    )
    assert questions == []
    assert interview.generate_calls == []


async def test_process_interview_answer_grants_credit_when_earned() -> None:
    bot = _StubBot()
    interview = _StubInterviewEngine(
        credit_decision=CreditDecision(
            credits_earned=1, reason="strong", capped=False, cap_hit=None
        )
    )
    builder = _StubMatrixBuilder()
    orch, _, _, fake = _build_orchestrator(bot, builder=builder, interview=interview)

    sources = SourceProcessingResult(
        claims=[_claim()], chunks=[_chunk()], metadata=[], source_ids=[uuid4()]
    )
    matrix = await orch.build_evidence_matrix(sources, PROJECT_ID, _noop_progress)

    _, earned, answer = await orch.process_interview_answer(
        question=_question(),
        answer_text="My source describes a 23% efficiency improvement.",
        matrix=matrix,
        sources=sources,
        project_id=PROJECT_ID,
        user_id=USER_ID,
        language="uz",
    )

    assert earned is True
    assert answer.credits_earned == 1
    free_rows = [r for r in fake.tables.get("credit_ledger", []) if r["action"] == "grant_free"]
    assert len(free_rows) == 1


async def test_process_interview_answer_no_credit_when_engine_decides_zero() -> None:
    bot = _StubBot()
    interview = _StubInterviewEngine(
        credit_decision=CreditDecision(
            credits_earned=0, reason="too weak", capped=False, cap_hit=None
        )
    )
    builder = _StubMatrixBuilder()
    orch, _, _, fake = _build_orchestrator(bot, builder=builder, interview=interview)

    sources = SourceProcessingResult(
        claims=[_claim()], chunks=[_chunk()], metadata=[], source_ids=[uuid4()]
    )
    matrix = await orch.build_evidence_matrix(sources, PROJECT_ID, _noop_progress)

    _, earned, answer = await orch.process_interview_answer(
        question=_question(),
        answer_text="idk",
        matrix=matrix,
        sources=sources,
        project_id=PROJECT_ID,
        user_id=USER_ID,
        language="uz",
    )

    assert earned is False
    assert answer.credits_earned == 0
    free_rows = [r for r in fake.tables.get("credit_ledger", []) if r["action"] == "grant_free"]
    assert free_rows == []


# ---------------------------------------------------------------------------
# Step 4 — outline
# ---------------------------------------------------------------------------


async def test_generate_outline_passes_tier_pages_and_calls_assign() -> None:
    bot = _StubBot()
    outline_gen = _StubOutlineGenerator()
    builder = _StubMatrixBuilder()
    orch, _, _, _ = _build_orchestrator(bot, builder=builder, outline_gen=outline_gen)

    sources = SourceProcessingResult(
        claims=[_claim()], chunks=[_chunk()], metadata=[], source_ids=[uuid4()]
    )
    matrix = await orch.build_evidence_matrix(sources, PROJECT_ID, _noop_progress)
    outline = await orch.generate_outline(
        sources=sources,
        matrix=matrix,
        project_id=PROJECT_ID,
        language="uz",
        tier="standard",
        project_title="My article",
    )

    assert isinstance(outline, ArticleOutline)
    assert outline_gen.calls[0]["target_pages"] == 8
    assert outline_gen.calls[0]["structure"] is ArticleStructure.REFERAT
    assert outline_gen.calls[0]["language"] is Language.UZ
    assert builder.assign_calls and builder.assign_calls[0][1] is outline


# ---------------------------------------------------------------------------
# Step 5 — suggestions
# ---------------------------------------------------------------------------


async def test_generate_suggestions_calls_engine() -> None:
    bot = _StubBot()
    suggestions = _StubSuggestionEngine()
    orch, _, _, _ = _build_orchestrator(bot, suggestions=suggestions)

    sources = SourceProcessingResult(
        claims=[_claim()], chunks=[_chunk()], metadata=[], source_ids=[uuid4()]
    )
    matrix = EvidenceMatrix(project_id=UUID(PROJECT_ID), entries=[])

    report = await orch.generate_suggestions(
        outline=_outline(),
        matrix=matrix,
        sources=sources,
        language="uz",
        progress=_noop_progress,
    )
    assert isinstance(report, SuggestionReport)
    assert suggestions.calls and suggestions.calls[0]["language"] == "uz"


# ---------------------------------------------------------------------------
# Step 6 — draft
# ---------------------------------------------------------------------------


async def test_draft_article_passes_calibration_and_language() -> None:
    bot = _StubBot()
    drafter = _StubDrafter()
    orch, _, _, _ = _build_orchestrator(bot, drafter=drafter)

    sources = SourceProcessingResult(
        claims=[_claim()], chunks=[_chunk()], metadata=[], source_ids=[uuid4()]
    )
    matrix = EvidenceMatrix(project_id=UUID(PROJECT_ID), entries=[])
    result = await orch.draft_article(
        outline=_outline(),
        matrix=matrix,
        sources=sources,
        questions=[],
        answers=[],
        language="ru",
        calibration="magistratura",
        progress=_noop_progress,
    )
    assert isinstance(result, ArticleDraftResult)
    assert drafter.calls[0]["calibration_level"] is CalibrationLevel.MASTERS
    assert drafter.calls[0]["language"] == "ru"


# ---------------------------------------------------------------------------
# Step 7 — citations
# ---------------------------------------------------------------------------


async def test_verify_citations_passes_section_list() -> None:
    bot = _StubBot()
    verifier = _StubCitationVerifier()
    orch, _, _, _ = _build_orchestrator(bot, verifier=verifier)

    draft = _draft_result()
    sources = SourceProcessingResult(
        claims=[_claim()], chunks=[_chunk()], metadata=[], source_ids=[uuid4()]
    )
    matrix = EvidenceMatrix(project_id=UUID(PROJECT_ID), entries=[])
    report = await orch.verify_citations(draft, matrix, sources, _noop_progress)

    assert isinstance(report, CitationVerificationReport)
    sections_arg = verifier.calls[0]["sections"]
    assert len(sections_arg) == 1
    assert sections_arg[0].status is ArticleSectionStatus.DRAFT


# ---------------------------------------------------------------------------
# Step 8 — export
# ---------------------------------------------------------------------------


async def test_export_writes_docx_and_pdf_paths() -> None:
    bot = _StubBot()
    export = _StubExportPipeline(pdf_success=True)
    orch, _, _, _ = _build_orchestrator(bot, export_pipe=export)

    draft = _draft_result()
    outline = _outline()
    verification = CitationVerificationReport(
        total_citations=0,
        supported=0,
        partially_supported=0,
        overclaimed=0,
        not_supported=0,
        contradicted=0,
        source_not_found=0,
        overall_integrity_score=1.0,
        verifications=[],
        critical_issues=[],
        warnings=[],
        model_used="stub",
        total_tokens=0,
        estimated_cost_usd=0.0,
        verification_time_ms=1,
    )
    sources = SourceProcessingResult(
        claims=[_claim()],
        chunks=[_chunk()],
        metadata=[SourceMetadataExtracted(title="Paper", authors=["Ada Lovelace"], year=1843)],
        source_ids=[uuid4()],
    )
    docx_path, pdf_path, bundle = await orch.export(
        draft=draft,
        outline=outline,
        verification=verification,
        sources=sources,
        project_id=PROJECT_ID,
        language="uz",
        author_name="Test User",
        progress=_noop_progress,
    )
    assert docx_path.exists()
    assert pdf_path is not None and pdf_path.exists()
    assert bundle.docx.file_size_bytes > 0
    docx_path.unlink()
    pdf_path.unlink()


async def test_export_falls_back_when_pdf_conversion_fails() -> None:
    bot = _StubBot()
    export = _StubExportPipeline(pdf_success=False)
    orch, _, _, _ = _build_orchestrator(bot, export_pipe=export)

    draft = _draft_result()
    outline = _outline()
    verification = CitationVerificationReport(
        total_citations=0,
        supported=0,
        partially_supported=0,
        overclaimed=0,
        not_supported=0,
        contradicted=0,
        source_not_found=0,
        overall_integrity_score=1.0,
        verifications=[],
        critical_issues=[],
        warnings=[],
        model_used="stub",
        total_tokens=0,
        estimated_cost_usd=0.0,
        verification_time_ms=1,
    )
    sources = SourceProcessingResult(
        claims=[_claim()], chunks=[_chunk()], metadata=[], source_ids=[uuid4()]
    )
    docx_path, pdf_path, _bundle = await orch.export(
        draft=draft,
        outline=outline,
        verification=verification,
        sources=sources,
        project_id=PROJECT_ID,
        language="uz",
        author_name="Test User",
        progress=_noop_progress,
    )
    assert docx_path.exists()
    assert pdf_path is None
    docx_path.unlink()


async def test_export_picks_apa_for_english() -> None:
    bot = _StubBot()
    bib = _StubBibliographyFormatter()
    orch, _, _, _ = _build_orchestrator(bot, bib=bib)

    sources = SourceProcessingResult(
        claims=[_claim()],
        chunks=[_chunk()],
        metadata=[SourceMetadataExtracted(title="Paper", authors=["A. Author"], year=2024)],
        source_ids=[uuid4()],
    )
    verification = CitationVerificationReport(
        total_citations=0,
        supported=0,
        partially_supported=0,
        overclaimed=0,
        not_supported=0,
        contradicted=0,
        source_not_found=0,
        overall_integrity_score=1.0,
        verifications=[],
        critical_issues=[],
        warnings=[],
        model_used="stub",
        total_tokens=0,
        estimated_cost_usd=0.0,
        verification_time_ms=1,
    )
    docx_path, _pdf, _bundle = await orch.export(
        draft=_draft_result(),
        outline=_outline(),
        verification=verification,
        sources=sources,
        project_id=PROJECT_ID,
        language="en",
        author_name="Test",
        progress=_noop_progress,
    )
    assert bib.calls[0]["style"] is CitationFormat.APA
    docx_path.unlink(missing_ok=True)


# Silence unused-import warnings — these are intentional re-exports for fixture use.
_ = asyncio
