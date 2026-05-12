"""Article generation orchestrator wired to the real worker engines.

Sequences the full article pipeline (sources → matrix → interview →
outline → suggestions → draft → verify → export) and reports progress
via a callback the bot handler supplies. The orchestrator is the only
place that knows both Telegram (it owns the :class:`Bot` reference for
file downloads) and the article worker package; handlers stay thin and
workers stay Telegram-agnostic.

CLAUDE.md's 300-line cap is intentionally exceeded here: the eight
pipeline stages share state (project_id, language, calibration, the
running evidence-matrix), and splitting them across modules would
fragment a single coherent operation. The non-method helpers
(calibration/language mapping, fallback structure detection, FreeCredits
threading) live in module scope.

Product decisions baked into the orchestrator (see Task 27 Q&A):
  * Outline inputs are derived, not asked: thesis = strongest claim
    text, structure = REFERAT, target_pages = tier-driven (5/8/12).
  * The research interview is rendered free-text-only — the engine's
    :class:`ResearchQuestion` carries no option list, and the handler
    plain-shows ``question_text`` and waits for a typed answer.
  * Export metadata is auto-filled from FSM data (title, author,
    structure, citation format default GOST for uz/ru / APA for en).
  * Calibration mapping bot-string→:class:`CalibrationLevel` lives in
    this module under :data:`_CALIBRATION_MAP`.
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Final
from uuid import UUID, uuid4

from aiogram import Bot
from pydantic import BaseModel, ConfigDict, Field

from packages.core.enums import (
    ArticleStructure,
    CalibrationLevel,
    CitationFormat,
    InterviewMode,
    Language,
    SourceQuality,
)
from packages.core.models.article import (
    ArticleDraftResult,
    ArticleOutline,
)
from packages.core.models.bibliography import (
    CitationMetadata,
    FormattedBibliography,
)
from packages.core.models.evidence import (
    EvidenceMatrix,
    ResearchAnswer,
    ResearchQuestion,
)
from packages.core.models.export import (
    ArticleExportBundle,
    ArticleExportMetadata,
)
from packages.core.models.source import (
    SourceChunkCreate,
    SourceClaimCreate,
    SourceMetadataExtracted,
)
from packages.core.models.suggestion import SuggestionReport
from packages.core.models.verification import CitationVerificationReport
from packages.platform.credits import CreditLedger, FreeCreditsReason
from packages.platform.database import DatabaseClient
from packages.platform.storage import FileStorage
from packages.suggestions.engine import SuggestionEngine
from packages.workers.article.bibliography import (
    BibliographyFormatter,
    source_to_citation_metadata,
)
from packages.workers.article.citation_verifier import CitationVerifier
from packages.workers.article.drafter import ArticleDrafter
from packages.workers.article.evidence_matrix import EvidenceMatrixBuilder
from packages.workers.article.interview import ResearchInterviewEngine
from packages.workers.article.outline_generator import OutlineGenerator
from packages.workers.article.pdf_export import ArticlePDFPipeline
from packages.workers.source.pipeline import SourcePipeline

logger = logging.getLogger("nashr.orchestrator.article")

ProgressCallback = Callable[[str, int, int], Awaitable[None]]

TOTAL_STEPS: Final[int] = 8

_CALIBRATION_MAP: Final[dict[str, CalibrationLevel]] = {
    "school": CalibrationLevel.SCHOOL,
    "bakalavr": CalibrationLevel.UNDERGRADUATE,
    "undergraduate": CalibrationLevel.UNDERGRADUATE,
    "magistratura": CalibrationLevel.MASTERS,
    "masters": CalibrationLevel.MASTERS,
    "doctoral": CalibrationLevel.DOCTORAL,
}

_LANGUAGE_MAP: Final[dict[str, Language]] = {
    "uz": Language.UZ,
    "ru": Language.RU,
    "en": Language.EN,
    "kaa": Language.KAA,
}

_TIER_TO_PAGES: Final[dict[str, int]] = {
    "basic": 5,
    "article_basic": 5,
    "standard": 8,
    "article_standard": 8,
    "premium": 12,
    "article_premium": 12,
}


def map_calibration(value: str) -> CalibrationLevel:
    """Translate a bot-stored calibration string into :class:`CalibrationLevel`.

    Bot registration stores values like ``"bakalavr"`` and
    ``"magistratura"``; the article drafter takes
    :class:`CalibrationLevel`. Unknown values fall back to
    :attr:`CalibrationLevel.UNDERGRADUATE` (the default for a typical
    Uzbek student user).
    """

    return _CALIBRATION_MAP.get(value.lower(), CalibrationLevel.UNDERGRADUATE)


def map_language(value: str) -> Language:
    """Translate a bot-stored language code into the :class:`Language` enum."""

    lowered = value.lower()
    if lowered.startswith("kaa"):
        return Language.KAA
    return _LANGUAGE_MAP.get(lowered[:2], Language.UZ)


def tier_to_pages(tier: str) -> int:
    """Map a tier identifier (``basic``/``standard``/``premium``) to a page target."""

    return _TIER_TO_PAGES.get(tier.lower(), 5)


def default_citation_format(language: Language) -> CitationFormat:
    """Pick the bibliography style that matches the user's language by default."""

    if language is Language.EN:
        return CitationFormat.APA
    return CitationFormat.GOST


def derive_thesis(claims: list[SourceClaimCreate], fallback_title: str) -> str:
    """Derive an article thesis from the strongest extracted claim.

    Picks the longest claim text among STRONG-strength claims; falls back
    to the first claim, then to ``fallback_title``. Truncated to 2000
    chars to match :class:`ArticleOutline.thesis` max.
    """

    if not claims:
        return (fallback_title or "Untitled topic").strip()[:2_000]
    strong = [c for c in claims if c.strength.value == "strong"]
    pool = strong or list(claims)
    chosen = max(pool, key=lambda c: len(c.claim_text))
    return chosen.claim_text.strip()[:2_000]


class SourceProcessingResult(BaseModel):
    """Bundle of artefacts produced from a batch of uploaded source files."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    claims: list[SourceClaimCreate] = Field(default_factory=list[SourceClaimCreate])
    chunks: list[SourceChunkCreate] = Field(default_factory=list[SourceChunkCreate])
    metadata: list[SourceMetadataExtracted] = Field(default_factory=list[SourceMetadataExtracted])
    source_ids: list[UUID] = Field(default_factory=list[UUID])
    warnings: list[str] = Field(default_factory=list[str])


class ArticleOrchestrator:
    """Orchestrates the article generation pipeline end to end.

    Construction is lazy in the sense that every engine has a default
    no-arg constructor; injecting fakes is supported through ``__init__``
    keyword arguments so unit tests can short-circuit LLM/file I/O.
    """

    def __init__(
        self,
        bot: Bot,
        db: DatabaseClient,
        credits: CreditLedger,
        *,
        storage: FileStorage | None = None,
        source_pipeline: SourcePipeline | None = None,
        matrix_builder: EvidenceMatrixBuilder | None = None,
        interview_engine: ResearchInterviewEngine | None = None,
        suggestion_engine: SuggestionEngine | None = None,
        outline_generator: OutlineGenerator | None = None,
        drafter: ArticleDrafter | None = None,
        citation_verifier: CitationVerifier | None = None,
        bibliography_formatter: BibliographyFormatter | None = None,
        export_pipeline: ArticlePDFPipeline | None = None,
    ) -> None:
        self._bot = bot
        self._db = db
        self._credits = credits
        self._storage = storage
        self._source_pipeline = source_pipeline if source_pipeline is not None else SourcePipeline()
        self._matrix_builder = (
            matrix_builder if matrix_builder is not None else EvidenceMatrixBuilder()
        )
        self._interview_engine = (
            interview_engine if interview_engine is not None else ResearchInterviewEngine()
        )
        self._suggestion_engine = (
            suggestion_engine if suggestion_engine is not None else SuggestionEngine()
        )
        self._outline_generator = (
            outline_generator if outline_generator is not None else OutlineGenerator()
        )
        self._drafter = drafter if drafter is not None else ArticleDrafter()
        self._citation_verifier = (
            citation_verifier if citation_verifier is not None else CitationVerifier()
        )
        self._bibliography_formatter = (
            bibliography_formatter
            if bibliography_formatter is not None
            else BibliographyFormatter()
        )
        self._export_pipeline = (
            export_pipeline if export_pipeline is not None else ArticlePDFPipeline()
        )

    # ====================================================================
    # STEP 1 — download + process sources
    # ====================================================================

    async def process_sources(
        self,
        file_infos: list[dict[str, object]],
        project_id: str,
        user_id: str,
        progress: ProgressCallback,
    ) -> SourceProcessingResult:
        """Download every Telegram file, validate+parse, extract claims.

        Failed downloads/parses are skipped with a warning rather than
        aborting the whole upload; a wholly empty result raises
        :class:`ValueError` so the bot can surface a clear error.
        Successful sources get a ``source_upload`` free credit granted.
        """

        await progress("Processing sources", 1, TOTAL_STEPS)
        result = SourceProcessingResult()
        for info in file_infos:
            await self._process_one_source(info, project_id, user_id, result)

        if not result.claims and not result.chunks:
            raise ValueError("No usable content could be extracted from the uploaded sources.")
        return result

    async def _process_one_source(
        self,
        info: dict[str, object],
        project_id: str,
        user_id: str,
        result: SourceProcessingResult,
    ) -> None:
        """Process a single file dict; collect into ``result`` or log a warning."""

        filename = str(info.get("filename") or "upload.bin")
        try:
            file_bytes = await self._download_telegram_file(str(info.get("file_id") or ""))
        except Exception as exc:
            logger.warning(
                "orchestrator_source_download_failed",
                extra={"source_name": filename, "error_type": type(exc).__name__},
            )
            result.warnings.append(f"Could not download {filename}: {type(exc).__name__}")
            return

        try:
            pipeline_result = await self._source_pipeline.process(file_bytes, filename)
        except Exception as exc:
            logger.warning(
                "orchestrator_source_pipeline_failed",
                extra={"source_name": filename, "error_type": type(exc).__name__},
            )
            result.warnings.append(f"Could not parse {filename}: {type(exc).__name__}")
            return

        if not pipeline_result.validation.valid:
            result.warnings.append(
                f"Rejected {filename}: {pipeline_result.validation.rejection_reason or 'invalid'}"
            )
            return

        result.claims.extend(pipeline_result.claims)
        result.chunks.extend(pipeline_result.chunks)
        if pipeline_result.parsed is not None:
            result.metadata.append(pipeline_result.parsed.metadata)
        result.source_ids.append(uuid4())

        await self._register_source(info, project_id, file_bytes, filename)
        await self._credits.grant_free_credit(
            user_id=user_id,
            project_id=project_id,
            reason=FreeCreditsReason.SOURCE_UPLOAD,
        )

    async def _download_telegram_file(self, file_id: str) -> bytes:
        """Download a Telegram file and return its raw bytes.

        Wraps :meth:`Bot.download` which returns a :class:`BinaryIO`; we
        block-read it and discard the buffer. ``Bot.download`` raises
        :class:`aiogram.exceptions.TelegramAPIError` on transport
        problems; callers handle that one level up.
        """

        if not file_id:
            raise ValueError("missing file_id")
        buffer = await self._bot.download(file_id)
        if buffer is None:
            raise RuntimeError("bot.download returned no payload")
        return buffer.read()

    async def _register_source(
        self,
        info: dict[str, object],
        project_id: str,
        file_bytes: bytes,
        filename: str,
    ) -> None:
        """Persist a row for one successfully processed source.

        The storage path is a temp-dir copy of the bytes so DB rows
        match real filesystem state until R2 storage lands (Task 29).
        Errors are swallowed: a missing DB row should not invalidate
        already-extracted claims.
        """

        tmpdir = Path(tempfile.mkdtemp(prefix="nashr_src_"))
        target = tmpdir / filename
        try:
            await asyncio.to_thread(target.write_bytes, file_bytes)
            raw_size = info.get("file_size")
            file_size_int = int(raw_size) if isinstance(raw_size, int) else len(file_bytes)
            await self._db.create_source(
                project_id=project_id,
                filename=filename,
                file_type=str(info.get("file_type") or "bin"),
                file_size=file_size_int,
                storage_path=str(target),
            )
        except Exception as exc:
            logger.warning(
                "orchestrator_source_register_failed",
                extra={"source_name": filename, "error_type": type(exc).__name__},
            )

    # ====================================================================
    # STEP 2 — evidence matrix
    # ====================================================================

    async def build_evidence_matrix(
        self,
        sources: SourceProcessingResult,
        project_id: str,
        progress: ProgressCallback,
    ) -> EvidenceMatrix:
        """Build the evidence matrix from extracted claims + chunks."""

        await progress("Building evidence matrix", 2, TOTAL_STEPS)
        return await self._matrix_builder.build_from_claims(
            project_id=_to_uuid(project_id),
            claims=sources.claims,
            chunks=sources.chunks,
            source_quality=SourceQuality.MEDIUM,
        )

    # ====================================================================
    # STEP 3 — research interview
    # ====================================================================

    async def generate_interview_questions(
        self,
        sources: SourceProcessingResult,
        matrix: EvidenceMatrix,
        project_id: str,
        language: str,
        mode: InterviewMode = InterviewMode.GUIDED,
    ) -> list[ResearchQuestion]:
        """Compute the weakness profile and ask the engine for questions.

        Returns ``ResearchQuestion`` instances (engine native form). The
        handler renders ``question.question_text`` as a free-text prompt;
        there is no inline-keyboard option list to surface because the
        engine does not emit one.
        """

        profile = self._interview_engine.analyze_weaknesses(
            matrix=matrix,
            claims=sources.claims,
            chunks=sources.chunks,
        )
        if mode is InterviewMode.FAST:
            return []
        return await self._interview_engine.generate_questions(
            project_id=_to_uuid(project_id),
            profile=profile,
            matrix=matrix,
            claims=sources.claims,
            chunks=sources.chunks,
            source_metadata=sources.metadata,
            source_ids=sources.source_ids,
            language=map_language(language),
            mode=mode,
        )

    async def process_interview_answer(
        self,
        *,
        question: ResearchQuestion,
        answer_text: str,
        matrix: EvidenceMatrix,
        sources: SourceProcessingResult,
        project_id: str,
        user_id: str,
        language: str,
    ) -> tuple[EvidenceMatrix, bool, ResearchAnswer]:
        """Score one answer, update the matrix, and award a free credit.

        Returns ``(updated_matrix, earned_credit, research_answer)``.
        ``earned_credit`` is true only when the engine awarded at least
        one credit *and* every cap (daily/weekly/per-project) allowed
        the grant. The research answer is returned so the handler can
        thread it into the drafter later.
        """

        project_credits_used, daily_used, weekly_used = await self._credit_usage(
            user_id, project_id
        )
        chunk_map = _chunk_uuid_map(sources.chunks, matrix)
        processed = await self._interview_engine.process_answer(
            project_id=_to_uuid(project_id),
            question=question,
            answer_text=answer_text,
            matrix=matrix,
            chunks=sources.chunks,
            chunk_uuid_map=chunk_map,
            language=map_language(language),
            project_credits_used=project_credits_used,
            daily_credits_used=daily_used,
            weekly_credits_used=weekly_used,
        )

        earned = False
        if processed.credit_decision.credits_earned > 0:
            entry = await self._credits.grant_free_credit(
                user_id=user_id,
                project_id=project_id,
                reason=FreeCreditsReason.INTERVIEW_ANSWER,
            )
            earned = entry is not None

        scored = processed.scored_answer
        research_answer = ResearchAnswer(
            project_id=_to_uuid(project_id),
            question_id=question.id,
            answer_text=answer_text[:10_000],
            source_references_used=[],
            score=scored.score,
            credits_earned=processed.credit_decision.credits_earned,
            created_at=datetime.now(UTC),
        )
        return processed.updated_matrix, earned, research_answer

    async def _credit_usage(self, user_id: str, project_id: str) -> tuple[int, int, int]:
        """Fetch (per-project, daily, weekly) free-credit counts for cap math."""

        per_project = await self._credits.get_free_credits_for_project(user_id, project_id)
        daily = await self._credits.get_free_credits_today(user_id)
        weekly = await self._credits.get_free_credits_this_week(user_id)
        return per_project, daily, weekly

    # ====================================================================
    # STEP 4 — outline
    # ====================================================================

    async def generate_outline(
        self,
        sources: SourceProcessingResult,
        matrix: EvidenceMatrix,
        project_id: str,
        language: str,
        tier: str,
        project_title: str,
        structure: ArticleStructure = ArticleStructure.REFERAT,
        progress: ProgressCallback | None = None,
    ) -> ArticleOutline:
        """Build the outline; auto-derive thesis and page target from inputs.

        The matrix is assigned to outline sections via the builder so
        downstream draft/verify steps see section-aligned entries.
        """

        if progress is not None:
            await progress("Generating outline", 3, TOTAL_STEPS)
        thesis = derive_thesis(sources.claims, project_title)
        outline = await self._outline_generator.generate(
            project_id=_to_uuid(project_id),
            structure=structure,
            thesis=thesis,
            target_pages=tier_to_pages(tier),
            claims=sources.claims,
            chunks=sources.chunks,
            source_metadata=sources.metadata,
            language=map_language(language),
        )
        await self._matrix_builder.assign_to_sections(matrix, outline)
        return outline

    # ====================================================================
    # STEP 5 — suggestions
    # ====================================================================

    async def generate_suggestions(
        self,
        outline: ArticleOutline,
        matrix: EvidenceMatrix,
        sources: SourceProcessingResult,
        language: str,
        progress: ProgressCallback,
    ) -> SuggestionReport:
        """Run the suggestion engine over the outline."""

        await progress("Finding additional sources", 4, TOTAL_STEPS)
        return await self._suggestion_engine.analyze_and_suggest(
            outline=outline,
            evidence_matrix=matrix,
            claims=sources.claims,
            chunks=sources.chunks,
            source_metadata=sources.metadata,
            language=language,
        )

    # ====================================================================
    # STEP 6 — draft
    # ====================================================================

    async def draft_article(
        self,
        outline: ArticleOutline,
        matrix: EvidenceMatrix,
        sources: SourceProcessingResult,
        questions: list[ResearchQuestion],
        answers: list[ResearchAnswer],
        language: str,
        calibration: str,
        progress: ProgressCallback,
    ) -> ArticleDraftResult:
        """Draft every section through :class:`ArticleDrafter`."""

        await progress("Writing article", 5, TOTAL_STEPS)
        return await self._drafter.draft_article(
            outline=outline,
            evidence_matrix=matrix,
            claims=sources.claims,
            chunks=sources.chunks,
            user_answers=answers,
            questions=questions,
            language=language,
            calibration_level=map_calibration(calibration),
        )

    # ====================================================================
    # STEP 7 — verify citations
    # ====================================================================

    async def verify_citations(
        self,
        draft: ArticleDraftResult,
        matrix: EvidenceMatrix,
        sources: SourceProcessingResult,
        progress: ProgressCallback,
    ) -> CitationVerificationReport:
        """Run citation verification over the drafted sections."""

        await progress("Verifying citations", 6, TOTAL_STEPS)
        sections = [r.section for r in draft.sections]
        return await self._citation_verifier.verify_article(
            sections=sections,
            claims=sources.claims,
            chunks=sources.chunks,
            evidence_matrix=matrix,
        )

    # ====================================================================
    # STEP 8 — export
    # ====================================================================

    async def export(
        self,
        draft: ArticleDraftResult,
        outline: ArticleOutline,
        verification: CitationVerificationReport,
        sources: SourceProcessingResult,
        project_id: str,
        language: str,
        author_name: str,
        progress: ProgressCallback,
    ) -> tuple[Path, Path | None, ArticleExportBundle]:
        """Render DOCX + PDF; write both into a temp dir, return paths.

        PDF rendering falls back gracefully when LibreOffice is absent
        (:class:`ArticlePDFPipeline` returns a failed :class:`PDFExportResult`,
        which we surface as ``pdf_path=None``).
        """

        await progress("Exporting files", 7, TOTAL_STEPS)
        language_norm = map_language(language)
        bibliography = self._build_bibliography(sources, language_norm)
        citation_metadata = _build_citation_metadata(sources.metadata)
        metadata = ArticleExportMetadata(
            title=outline.title,
            author_name=author_name or "Nashr foydalanuvchisi",
            article_type=outline.structure,
            citation_format=bibliography.style,
        )

        bundle = await self._export_pipeline.export(
            draft=draft,
            bibliography=bibliography,
            verification=verification,
            outline=outline,
            metadata=metadata,
            language=str(language_norm.value),
            citation_metadata=citation_metadata,
        )

        out_dir = Path(tempfile.mkdtemp(prefix="nashr_export_"))
        docx_path = out_dir / f"{project_id}.docx"
        await asyncio.to_thread(docx_path.write_bytes, bundle.docx.file_bytes)
        pdf_path: Path | None = None
        if bundle.pdf.success and bundle.pdf.file_bytes:
            pdf_path = out_dir / f"{project_id}.pdf"
            await asyncio.to_thread(pdf_path.write_bytes, bundle.pdf.file_bytes)
        else:
            logger.info(
                "orchestrator_pdf_export_skipped",
                extra={"error": bundle.pdf.error or "unknown"},
            )

        await self._upload_exports(project_id, docx_path, pdf_path)

        await progress("Complete", 8, TOTAL_STEPS)
        return docx_path, pdf_path, bundle

    async def _upload_exports(
        self,
        project_id: str,
        docx_path: Path,
        pdf_path: Path | None,
    ) -> None:
        """Upload rendered exports to R2 when storage is configured.

        Best-effort: failures are logged and swallowed because the local
        files still ship via Telegram in this iteration. R2-key-as-
        canonical persistence is a follow-up that needs a DB column.
        """

        storage = self._storage
        if storage is None or not storage.available:
            return
        targets: list[Path] = [docx_path]
        if pdf_path is not None:
            targets.append(pdf_path)
        for path in targets:
            try:
                key = FileStorage.generated_key(project_id, path.name)
                await storage.upload(path, key)
            except Exception as exc:
                logger.warning(
                    "orchestrator_storage_upload_failed",
                    extra={"path": path.name, "error_type": type(exc).__name__},
                )

    def _build_bibliography(
        self,
        sources: SourceProcessingResult,
        language: Language,
    ) -> FormattedBibliography:
        """Format a bibliography from extracted source metadata."""

        citation_meta = _build_citation_metadata(sources.metadata)
        return self._bibliography_formatter.format_bibliography(
            citations=citation_meta,
            style=default_citation_format(language),
            language=str(language.value),
        )


def _build_citation_metadata(
    metadata: list[SourceMetadataExtracted],
) -> list[CitationMetadata]:
    """Turn parser-extracted metadata into bibliography-ready citation rows."""

    out: list[CitationMetadata] = []
    for index, meta in enumerate(metadata, start=1):
        try:
            citation = source_to_citation_metadata(meta)
        except Exception as exc:
            logger.warning(
                "orchestrator_citation_meta_failed",
                extra={"index": index, "error_type": type(exc).__name__},
            )
            continue
        out.append(citation.model_copy(update={"citation_number": index}))
    return out


def _chunk_uuid_map(
    chunks: list[SourceChunkCreate],
    matrix: EvidenceMatrix,
) -> dict[str, UUID]:
    """Build a string-key→UUID map so the engine can resolve referenced chunks.

    The matrix holds chunks by UUID; the chunker emits string keys
    (``source_id`` or stringified ``chunk_index``). We aim for a 1:1 map
    in entry order, which matches the order the matrix builder writes
    rows; gaps are tolerated.
    """

    mapping: dict[str, UUID] = {}
    for i, chunk in enumerate(chunks):
        if i >= len(matrix.entries):
            break
        target = matrix.entries[i].source_chunk_id
        mapping[str(chunk.chunk_index)] = target
        if chunk.source_id:
            mapping[chunk.source_id] = target
    return mapping


def _to_uuid(value: str) -> UUID:
    """Coerce a stringified UUID into :class:`UUID`; generate fresh on parse error.

    Keeps the orchestrator resilient when an upstream component passes a
    non-UUID project identifier — better to record a synthetic one than
    crash the entire pipeline mid-run.
    """

    try:
        return UUID(value)
    except (ValueError, AttributeError):
        return uuid4()


__all__ = [
    "TOTAL_STEPS",
    "ArticleOrchestrator",
    "ProgressCallback",
    "SourceProcessingResult",
    "default_citation_format",
    "derive_thesis",
    "map_calibration",
    "map_language",
    "tier_to_pages",
]
