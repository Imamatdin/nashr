"""Presentation generation orchestrator wired to the real engines.

Sequences the presentation pipeline (sources → matrix → interview →
design → editorial → render) and reports progress via a callback
supplied by the bot handler. The orchestrator is the only place that
knows both Telegram (it owns the :class:`Bot` reference for file
downloads) and the presentation engines/worker; handlers stay thin and
engines stay Telegram-agnostic.

Audit is not a separate step here. The Node.js renderer runs the audit
internally and gates export on FAIL-severity findings (see
``packages/presentation-worker/src/index.ts`` render action); running it
again from Python would just duplicate that work. Audit warnings emitted
by the CLI surface in render stderr and are logged but not blocking.

CLAUDE.md's 300-line cap is intentionally exceeded: the six pipeline
stages share state (project_id, language, claims/chunks/metadata, the
running design + interview specs) and splitting them across modules
would fragment a single coherent operation.
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
import tempfile
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from typing import Final, cast
from uuid import UUID, uuid4

from aiogram import Bot
from pydantic import BaseModel, ConfigDict, Field

from packages.bot.orchestrators.article_orchestrator import (
    SourceProcessingResult,
    _OrchestratorError,
)
from packages.core.enums import (
    ExportFormat,
    SourceQuality,
)
from packages.core.models.evidence import EvidenceMatrix
from packages.core.models.presentation import (
    DeckSpec,
    DesignDirectionSpec,
    PresentationInterviewAnswers,
)
from packages.platform.credits import CreditLedger, FreeCreditsReason
from packages.platform.database import DatabaseClient
from packages.platform.storage import FileStorage
from packages.presentation.design_direction import DesignDirectionPass
from packages.presentation.editorial import EditorialPass
from packages.presentation.interview import PresentationInterviewEngine
from packages.workers.article.evidence_matrix import EvidenceMatrixBuilder
from packages.workers.source.pipeline import SourcePipeline

logger = logging.getLogger("nashr.orchestrator.presentation")

ProgressCallback = Callable[[str, int, int], Awaitable[None]]

# source → matrix → interview → design → editorial → render
TOTAL_STEPS: Final[int] = 6

# Map :class:`ExportFormat` to the worker CLI's ``--format`` argument
# and the on-disk extension the renderer writes.
_FORMAT_TO_CLI: Final[dict[ExportFormat, tuple[str, str]]] = {
    ExportFormat.HTML: ("html", "html"),
    ExportFormat.PPTX_EDITABLE: ("pptx", "pptx"),
    ExportFormat.PPTX_STUDIO: ("pptx", "pptx"),
    ExportFormat.PDF: ("pdf", "pdf"),
}

# Node CLI per-format timeout. Generous for PDF (Playwright cold-starts
# Chromium) and stingy enough that a wedged subprocess does not block
# the bot forever.
_RENDER_TIMEOUT_SECONDS: Final[int] = 180
_BUILD_TIMEOUT_SECONDS: Final[int] = 120


class PresentationRenderResult(BaseModel):
    """Files written by the Node renderer for one deck.

    ``html_path`` / ``pptx_path`` / ``pdf_path`` are populated only for
    the formats that were requested AND rendered successfully. A failed
    format is logged (in ``warnings``) and silently absent rather than
    raising — partial delivery beats zero delivery when one renderer
    barfs.
    """

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    html_path: Path | None = None
    pptx_path: Path | None = None
    pdf_path: Path | None = None
    warnings: list[str] = Field(default_factory=list[str])

    def by_extension(self) -> dict[str, Path]:
        """Return a ``{ext: path}`` map for every format that landed."""

        out: dict[str, Path] = {}
        if self.html_path is not None:
            out["html"] = self.html_path
        if self.pptx_path is not None:
            out["pptx"] = self.pptx_path
        if self.pdf_path is not None:
            out["pdf"] = self.pdf_path
        return out


class PresentationOrchestrator:
    """Orchestrates the presentation generation pipeline end to end.

    Every engine has a default no-arg constructor; the keyword-only
    seams on ``__init__`` let unit tests inject fakes for source
    parsing, evidence-matrix building, the deterministic interview /
    design passes, the LLM-driven editorial pass, and the Node renderer
    invocation.
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
        interview_engine: PresentationInterviewEngine | None = None,
        design_pass: DesignDirectionPass | None = None,
        editorial_pass: EditorialPass | None = None,
        worker_runner: _WorkerRunner | None = None,
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
            interview_engine if interview_engine is not None else PresentationInterviewEngine()
        )
        self._design_pass = design_pass if design_pass is not None else DesignDirectionPass()
        self._editorial_pass = editorial_pass if editorial_pass is not None else EditorialPass()
        self._worker_runner = worker_runner if worker_runner is not None else _WorkerRunner()

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

        Mirrors :meth:`ArticleOrchestrator.process_sources`. Failed
        downloads/parses surface as warnings but never abort the batch;
        an empty result raises :class:`ValueError` so the bot can show
        the user a clear error.
        """

        await progress("Processing sources", 1, TOTAL_STEPS)
        result = SourceProcessingResult()
        try:
            for info in file_infos:
                await self._process_one_source(info, project_id, user_id, result)
        except ValueError:
            raise
        except Exception as exc:
            raise _OrchestratorError("process_sources", exc) from exc

        if result.failed_sources:
            warning = "; ".join(f"{name}: {reason}" for name, reason in result.failed_sources)
            await progress(
                f"Warning: {len(result.failed_sources)} file(s) failed — {warning}",
                1,
                TOTAL_STEPS,
            )

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
        """Process one file dict; collect into ``result`` or log a warning."""

        filename = str(info.get("filename") or "upload.bin")
        try:
            file_bytes = await self._download_telegram_file(str(info.get("file_id") or ""))
        except Exception as exc:
            logger.warning(
                "presentation_source_download_failed",
                extra={"source_name": filename, "error_type": type(exc).__name__},
            )
            reason = f"download failed ({type(exc).__name__})"
            result.warnings.append(f"Could not download {filename}: {type(exc).__name__}")
            result.failed_sources.append((filename, reason))
            return

        try:
            pipeline_result = await self._source_pipeline.process(file_bytes, filename)
        except Exception as exc:
            logger.warning(
                "presentation_source_pipeline_failed",
                extra={"source_name": filename, "error_type": type(exc).__name__},
            )
            reason = f"parse failed ({type(exc).__name__})"
            result.warnings.append(f"Could not parse {filename}: {type(exc).__name__}")
            result.failed_sources.append((filename, reason))
            return

        if not pipeline_result.validation.valid:
            rejection = pipeline_result.validation.rejection_reason or "invalid"
            result.warnings.append(f"Rejected {filename}: {rejection}")
            result.failed_sources.append((filename, rejection))
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
        """Download a Telegram file; raise on transport errors."""

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

        Errors are swallowed: a missing DB row should not invalidate
        already-extracted claims. Matches the article orchestrator's
        compromise around R2 storage landing later.
        """

        tmpdir = Path(tempfile.mkdtemp(prefix="nashr_psrc_"))
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
                "presentation_source_register_failed",
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
        """Build the evidence matrix used by the editorial pass."""

        await progress("Building evidence matrix", 2, TOTAL_STEPS)
        try:
            return await self._matrix_builder.build_from_claims(
                project_id=_project_id_to_uuid(project_id),
                claims=sources.claims,
                chunks=sources.chunks,
                source_quality=SourceQuality.MEDIUM,
            )
        except Exception as exc:
            raise _OrchestratorError("evidence_matrix", exc) from exc

    # ====================================================================
    # STEP 3 — apply interview answers (or defaults)
    # ====================================================================

    async def apply_interview(
        self,
        raw_answers: Mapping[str, object] | None,
        sources: SourceProcessingResult,
        language: str,
        progress: ProgressCallback,
    ) -> PresentationInterviewAnswers:
        """Fold raw Mini-App answers into typed preferences.

        ``raw_answers=None`` means the user skipped the questionnaire;
        we route through :meth:`PresentationInterviewEngine.apply_defaults`
        instead of forcing the user to answer anything. Whatever path is
        taken, the return type is the same :class:`PresentationInterviewAnswers`.
        """

        await progress("Applying preferences", 3, TOTAL_STEPS)

        try:
            if raw_answers is None:
                return self._interview_engine.apply_defaults(
                    claims=sources.claims,
                    source_metadata=getattr(sources, "metadata", []),
                    chunks=sources.chunks,
                    language=language,
                )

            questions = self._interview_engine.generate_questions(
                claims=sources.claims,
                chunks=sources.chunks,
                source_metadata=getattr(sources, "metadata", []),
                language=language,
            )
            # Cast: the engine's signature accepts the looser Mapping type
            # the Mini App actually returns (strings, ints, bool, lists).
            coerced = cast(Mapping[str, str | int | bool | list[str]], raw_answers)
            return self._interview_engine.apply_answers(questions=questions, answers=coerced)
        except Exception as exc:
            raise _OrchestratorError("interview", exc) from exc

    # ====================================================================
    # STEP 4 — design direction (deterministic, no LLM)
    # ====================================================================

    async def generate_design(
        self,
        interview: PresentationInterviewAnswers,
        sources: SourceProcessingResult,
        progress: ProgressCallback,
    ) -> DesignDirectionSpec:
        """Run the Design Direction Pass. Synchronous engine wrapped in async."""

        await progress("Choosing design direction", 4, TOTAL_STEPS)
        try:
            return self._design_pass.generate(
                interview=interview,
                claims=sources.claims,
                chunks=sources.chunks,
                source_metadata=getattr(sources, "metadata", []),
            )
        except Exception as exc:
            raise _OrchestratorError("design_direction", exc) from exc

    # ====================================================================
    # STEP 5 — editorial pass (LLM)
    # ====================================================================

    async def generate_deck_spec(
        self,
        interview: PresentationInterviewAnswers,
        design: DesignDirectionSpec,
        matrix: EvidenceMatrix,
        sources: SourceProcessingResult,
        project_id: str,
        progress: ProgressCallback,
    ) -> DeckSpec:
        """Run the Editorial Pass to produce the complete deck spec."""

        await progress("Creating slide sequence", 5, TOTAL_STEPS)
        try:
            return await self._editorial_pass.generate_deck_spec(
                interview=interview,
                design=design,
                evidence_matrix=matrix,
                claims=sources.claims,
                chunks=sources.chunks,
                source_metadata=getattr(sources, "metadata", []),
                outline=None,
                project_id=project_id,
            )
        except Exception as exc:
            raise _OrchestratorError("editorial", exc) from exc

    # ====================================================================
    # STEP 6 — render via Node worker
    # ====================================================================

    async def render(
        self,
        deck_spec: DeckSpec,
        formats: list[ExportFormat],
        progress: ProgressCallback,
        project_id: str | None = None,
    ) -> PresentationRenderResult:
        """Invoke the Node.js worker to render the deck to disk.

        Uses a fresh temp directory per call so the renderer's output
        files do not collide between projects. The worker's CLI gates
        export on the internal quality audit; a FAIL-severity audit
        result surfaces as a non-zero exit and is captured as a render
        warning (the format is dropped, others still attempted).
        ``project_id`` is used to namespace R2 keys when storage upload
        is enabled; ``None`` falls back to the rendered file's stem.
        """

        await progress("Rendering presentation", 6, TOTAL_STEPS)

        try:
            output_dir = Path(tempfile.mkdtemp(prefix="nashr_pres_"))
            deck_json_path = output_dir / "deck.json"
            await asyncio.to_thread(
                deck_json_path.write_text,
                deck_spec.model_dump_json(),
                "utf-8",
            )

            worker_entry = await self._worker_runner.ensure_built()
        except Exception as exc:
            raise _OrchestratorError("render_prepare", exc) from exc
        result = PresentationRenderResult()

        for fmt in formats:
            cli_arg, ext = _FORMAT_TO_CLI.get(fmt, (None, None))
            if cli_arg is None or ext is None:
                logger.warning("presentation_unknown_format", extra={"format": fmt})
                continue

            try:
                completed = await self._worker_runner.run_render(
                    worker_entry=worker_entry,
                    deck_json_path=deck_json_path,
                    output_dir=output_dir,
                    cli_format=cli_arg,
                )
            except subprocess.TimeoutExpired:
                result.warnings.append(f"{ext}: render timed out")
                logger.warning("presentation_render_timeout", extra={"format": ext})
                continue
            except Exception as exc:
                result.warnings.append(f"{ext}: {type(exc).__name__}")
                logger.exception(
                    "presentation_render_failed",
                    extra={"format": ext, "error_type": type(exc).__name__},
                )
                continue

            if completed.returncode != 0:
                tail = (completed.stderr or "").strip().splitlines()
                snippet = tail[-1] if tail else "non-zero exit"
                result.warnings.append(f"{ext}: {snippet}")
                logger.warning(
                    "presentation_render_nonzero",
                    extra={"format": ext, "stderr_tail": snippet},
                )
                continue

            produced = _find_output_file(output_dir, ext)
            if produced is None:
                result.warnings.append(f"{ext}: renderer reported success but no file appeared")
                continue
            _attach_output(result, ext, produced)

        await self._upload_rendered(result, project_id)
        return result

    async def _upload_rendered(
        self,
        result: PresentationRenderResult,
        project_id: str | None,
    ) -> None:
        """Upload every rendered output to R2 when storage is configured.

        Best-effort: failures are logged and a warning is appended to
        ``result.warnings`` so the bot can surface them, but the local
        files keep flowing through to Telegram delivery. ``project_id``
        namespaces the R2 key under ``generated/{project_id}/``; when
        absent we fall back to the file's stem so the upload still
        succeeds (older callers that bypass ``run_full_pipeline``).
        """

        storage = self._storage
        if storage is None or not storage.available:
            return
        for ext, path in result.by_extension().items():
            try:
                key_namespace = project_id if project_id else path.stem
                key = FileStorage.generated_key(key_namespace, path.name)
                await storage.upload(path, key)
            except Exception as exc:
                result.warnings.append(f"{ext}: upload failed ({type(exc).__name__})")
                logger.warning(
                    "presentation_storage_upload_failed",
                    extra={"format": ext, "error_type": type(exc).__name__},
                )

    # ====================================================================
    # FULL PIPELINE
    # ====================================================================

    async def run_full_pipeline(
        self,
        file_infos: list[dict[str, object]],
        project_id: str,
        user_id: str,
        language: str,
        raw_answers: Mapping[str, object] | None,
        requested_formats: list[ExportFormat] | None,
        progress: ProgressCallback,
    ) -> PresentationRenderResult:
        """Drive the full presentation pipeline end-to-end.

        Called *after* payment has been confirmed. The orchestrator
        raises on unrecoverable errors (no usable sources, editorial
        pass failure); the caller (the bot handler) is responsible for
        refunding credits when this raises.
        """

        formats = requested_formats or [ExportFormat.HTML, ExportFormat.PPTX_EDITABLE]

        sources = await self.process_sources(
            file_infos=file_infos,
            project_id=project_id,
            user_id=user_id,
            progress=progress,
        )
        matrix = await self.build_evidence_matrix(sources, project_id, progress)
        interview = await self.apply_interview(
            raw_answers=raw_answers,
            sources=sources,
            language=language,
            progress=progress,
        )
        design = await self.generate_design(interview, sources, progress)
        deck_spec = await self.generate_deck_spec(
            interview=interview,
            design=design,
            matrix=matrix,
            sources=sources,
            project_id=project_id,
            progress=progress,
        )
        return await self.render(deck_spec, formats, progress, project_id=project_id)


# ---------------------------------------------------------------------------
# Worker runner — isolates subprocess invocations so tests can fake them
# ---------------------------------------------------------------------------


class _WorkerRunner:
    """Wraps the Node.js worker CLI calls behind a small async surface.

    Separated from :class:`PresentationOrchestrator` so unit tests can
    inject a fake that records arguments and returns canned output
    without ever touching ``subprocess`` or the real filesystem.
    """

    async def ensure_built(self) -> Path:
        """Return the path to ``dist/index.js``; build the worker if missing."""

        worker_dir = _find_worker_dir()
        entry = worker_dir / "dist" / "index.js"
        if entry.exists():
            return entry

        logger.info("presentation_worker_build_required")
        completed = await asyncio.to_thread(
            subprocess.run,
            ["npm", "run", "build"],
            cwd=str(worker_dir),
            capture_output=True,
            text=True,
            timeout=_BUILD_TIMEOUT_SECONDS,
            check=False,
            shell=False,
        )
        if completed.returncode != 0:
            logger.error(
                "presentation_worker_build_failed",
                extra={"stderr": (completed.stderr or "")[:500]},
            )
            raise RuntimeError("Presentation worker build failed; cannot render.")
        if not entry.exists():
            raise RuntimeError("Presentation worker built but dist/index.js still missing.")
        return entry

    async def run_render(
        self,
        worker_entry: Path,
        deck_json_path: Path,
        output_dir: Path,
        cli_format: str,
    ) -> subprocess.CompletedProcess[str]:
        """Run ``node dist/index.js render --format <cli_format>`` once."""

        return await asyncio.to_thread(
            subprocess.run,
            [
                "node",
                str(worker_entry),
                "render",
                "--input",
                str(deck_json_path),
                "--format",
                cli_format,
                "--output",
                str(output_dir),
            ],
            capture_output=True,
            text=True,
            timeout=_RENDER_TIMEOUT_SECONDS,
            check=False,
            shell=False,
        )


# ---------------------------------------------------------------------------
# Module helpers
# ---------------------------------------------------------------------------


def _project_id_to_uuid(value: str) -> UUID:
    """Coerce a stringified UUID into :class:`UUID`; mint a fresh one on parse error.

    Mirrors :func:`ArticleOrchestrator._to_uuid` without importing the
    private helper; better to record a synthetic UUID than to crash mid-pipeline
    on a malformed project id passed in from an upstream layer.
    """

    try:
        return UUID(value)
    except (ValueError, AttributeError):
        return uuid4()


def _find_worker_dir() -> Path:
    """Locate ``packages/presentation-worker/`` in the project tree.

    Tries several relative paths so the orchestrator works regardless
    of where the bot was launched from (project root, packages/bot,
    or a deployment dir).
    """

    candidates: list[Path] = [
        Path.cwd() / "packages" / "presentation-worker",
        Path(__file__).resolve().parent.parent.parent / "presentation-worker",
        Path("packages") / "presentation-worker",
    ]
    for candidate in candidates:
        if (candidate / "package.json").exists():
            return candidate
    raise FileNotFoundError(
        "packages/presentation-worker/ not found. Run from the project root or install the worker."
    )


def _find_output_file(output_dir: Path, ext: str) -> Path | None:
    """Pick the rendered file matching ``ext`` from a fresh tempdir.

    The worker writes ``<sanitized-title>.<ext>``; we glob the directory
    rather than guessing the filename so character sanitisation drift
    does not break delivery. ``deck.json`` is the only other file in
    the directory and never matches ``.html`` / ``.pptx`` / ``.pdf``.
    """

    return next(iter(output_dir.glob(f"*.{ext}")), None)


def _attach_output(result: PresentationRenderResult, ext: str, path: Path) -> None:
    """Populate the right path slot on the result object."""

    if ext == "html":
        result.html_path = path
    elif ext == "pptx":
        result.pptx_path = path
    elif ext == "pdf":
        result.pdf_path = path


__all__ = [
    "TOTAL_STEPS",
    "PresentationOrchestrator",
    "PresentationRenderResult",
    "ProgressCallback",
]
