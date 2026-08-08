"""Presentation generation orchestrator wired to the real engines.

Sequences the presentation pipeline (sources → matrix → interview →
design → editorial → images → render) and reports progress via a callback
supplied by the bot handler. The orchestrator is the only place that
knows both Telegram (it owns the :class:`Bot` reference for file
downloads) and the presentation engines/worker; handlers stay thin and
engines stay Telegram-agnostic.

Audit is not a separate step here. The Node.js renderer runs the audit
internally and gates export on FAIL-severity findings (see
``packages/presentation-worker/src/index.ts`` render action); running it
again from Python would just duplicate that work. Audit warnings emitted
by the CLI surface in render stderr and are logged but not blocking.

CLAUDE.md's 300-line cap is intentionally exceeded: the seven pipeline
stages share state (project_id, language, claims/chunks/metadata/figures,
the running design + interview specs) and splitting them across modules
would fragment a single coherent operation.
"""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess
import tempfile
from collections.abc import Awaitable, Callable, Mapping, Sequence
from pathlib import Path
from typing import Final, cast
from uuid import UUID, uuid4

from aiogram import Bot
from pydantic import BaseModel, ConfigDict, Field

from packages.bot.orchestrators.article_orchestrator import (
    SourceProcessingResult,
    _OrchestratorError,
)
from packages.core.constants import image_budget_for_package
from packages.core.enums import (
    AuditSeverity,
    ExportFormat,
    GenerationPackage,
    SourceQuality,
)
from packages.core.models.evidence import EvidenceMatrix
from packages.core.models.presentation import (
    DeckSpec,
    DesignDirectionSpec,
    PresentationInterviewAnswers,
    SlideFix,
    SlideRegenResult,
    SlideSpec,
)
from packages.platform.credits import CreditLedger, FreeCreditsReason
from packages.platform.database import DatabaseClient
from packages.platform.storage import FileStorage
from packages.presentation.design_direction import DesignDirectionPass
from packages.presentation.editorial import EditorialPass
from packages.presentation.image_pass import ImagePass
from packages.presentation.interview import PresentationInterviewEngine
from packages.presentation.plan_validator import validate_section_against_plan
from packages.workers.article.evidence_matrix import EvidenceMatrixBuilder
from packages.workers.source.pipeline import SourcePipeline

logger = logging.getLogger("nashr.orchestrator.presentation")

ProgressCallback = Callable[[str, int, int], Awaitable[None]]

# source → matrix → interview → design → editorial → images → render
TOTAL_STEPS: Final[int] = 7

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


class FixAndRenderResult(BaseModel):
    """Result of applying a batch of slide fixes and re-rendering once.

    ``deck`` is the edited in-memory deck (every fix spliced in, persisted before
    render — a persist failure aborts before render, so a returned result always
    reflects a saved deck); ``render`` carries the freshly rendered file paths the
    handler re-delivers (and any best-effort upload warnings); ``fixes`` keeps the
    per-fix :class:`SlideRegenResult` findings — the brain reads ``.passed`` to
    decide whether to accept the batch or retry a slide, so they are not discarded.

    ``estimated_cost_usd`` and ``image_count`` are the batch totals the brain
    session records for billing/analytics: the summed editorial-regen LLM spend
    and the number of paid generated images across all fixes, summed from the
    per-fix :class:`SlideRegenResult`\\ s. They do NOT gate the session — the edit
    cap is a per-tier fix counter, not a cost — but the real cost is surfaced
    rather than discarded. The dollar value of the images
    (``image_count`` × :data:`IMAGE_COST_USD`) is folded in by the session,
    keeping LLM and image spend separately attributable.
    """

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    deck: DeckSpec
    render: PresentationRenderResult
    fixes: list[SlideRegenResult] = Field(default_factory=list[SlideRegenResult])
    estimated_cost_usd: float = Field(default=0.0, ge=0.0)
    image_count: int = Field(default=0, ge=0)


class PresentationPipelineResult(BaseModel):
    """The full first-generation output: the rendered files AND the sources.

    ``run_full_pipeline`` builds a :class:`SourceProcessingResult` and threads it
    through every stage; Stage 5a surfaces it (rather than discarding it) so the
    delivery handler can seed the brain editing session with the exact sources
    first-gen grounded against — no re-parsing of the uploads. ``render`` is the
    unchanged rendered-files result the delivery path already consumes.
    """

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    render: PresentationRenderResult
    sources: SourceProcessingResult


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
        image_pass: ImagePass | None = None,
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
        self._image_pass = image_pass if image_pass is not None else ImagePass()
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
            storage_key = str(info.get("storage_key") or "")
            if storage_key:
                # Queue jobs (P2): the web surface already uploaded the source
                # to R2; fetch by key instead of through Telegram.
                file_bytes = await self._download_stored_source(storage_key)
            else:
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

        # Web/queue jobs carry the persisted sources-row id: stamp it into
        # every claim/chunk so the provenance view can trace claim -> source
        # file + chunk. Bot uploads have no row id here and keep the bare
        # chunk-index refs the extractor emits.
        source_id = str(info.get("source_id") or "")
        if source_id:
            for claim in pipeline_result.claims:
                claim.source_chunk_id = (
                    f"{source_id}:{claim.source_chunk_id}" if claim.source_chunk_id else source_id
                )
            for chunk in pipeline_result.chunks:
                chunk.source_id = source_id
                chunk.project_id = project_id

        result.claims.extend(pipeline_result.claims)
        result.chunks.extend(pipeline_result.chunks)
        if pipeline_result.parsed is not None:
            result.metadata.append(pipeline_result.parsed.metadata)
            result.figures.extend(pipeline_result.parsed.figures)

        if source_id:
            # Row already registered by POST /sources; a second insert would
            # duplicate it with a dead local path.
            try:
                result.source_ids.append(UUID(source_id))
            except ValueError:
                result.source_ids.append(uuid4())
        else:
            result.source_ids.append(uuid4())
            await self._register_source(info, project_id, file_bytes, filename)
        await self._credits.grant_free_credit(
            user_id=user_id,
            project_id=project_id,
            reason=FreeCreditsReason.SOURCE_UPLOAD,
        )

    async def _download_stored_source(self, storage_key: str) -> bytes:
        """Fetch an already-uploaded source from R2 (web/queue path)."""

        if self._storage is None:
            raise RuntimeError("storage not configured; cannot fetch stored source")
        return await self._storage.get_bytes(storage_key)

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
    # STEP 4 — design direction (LLM, deterministic fallback)
    # ====================================================================

    async def generate_design(
        self,
        interview: PresentationInterviewAnswers,
        sources: SourceProcessingResult,
        progress: ProgressCallback,
    ) -> DesignDirectionSpec:
        """Run the Design Direction Pass (one Sonnet call, deterministic fallback)."""

        await progress("Choosing design direction", 4, TOTAL_STEPS)
        try:
            return await self._design_pass.generate(
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
    # STEP 6 — resolve image slots (Commons portraits + generated figures/bg)
    # ====================================================================

    async def resolve_images(
        self,
        deck_spec: DeckSpec,
        sources: SourceProcessingResult,
        project_id: str,
        progress: ProgressCallback,
        *,
        package: GenerationPackage,
    ) -> DeckSpec:
        """Fill the deck's image slots (parallel); abstain rather than fail.

        Best-effort and non-fatal: the image engine never blocks a deck. When
        no storage is configured we skip resolution entirely (nothing to write a
        retrievable url against) but still advance the progress step so the step
        count stays stable. Any unexpected error is swallowed — a deck with no
        images still renders.

        ``package`` derives the per-deck generated-image budget (invariant I1).
        Required keyword-only so a caller cannot silently default a paid tier.
        """

        await progress("Resolving images", 6, TOTAL_STEPS)
        return await self._resolve_deck_images(deck_spec, sources, project_id, package=package)

    async def _resolve_deck_images(
        self,
        deck_spec: DeckSpec,
        sources: SourceProcessingResult,
        project_id: str,
        *,
        package: GenerationPackage,
        only_slide_ids: frozenset[str] | None = None,
    ) -> DeckSpec:
        """Resolve the deck's unfilled image slots (best-effort, no progress step).

        The progress-free core shared by the full pipeline's :meth:`resolve_images`
        and the single-slide :meth:`regenerate_slide`. When no storage is
        configured it abstains; any failure is swallowed so a deck with no images
        still renders. ``only_slide_ids`` is forwarded to
        :meth:`ImagePass.resolve_deck`: ``None`` (the full pipeline) resolves every
        slot, while the regen path passes the regenerated slide's id so re-resolution
        touches ONLY its slots — an abstained slot on an untouched slide is never
        silently re-attempted.
        """

        storage = self._storage
        if storage is None:
            return deck_spec
        budget = image_budget_for_package(package)
        try:
            return await self._image_pass.resolve_deck(
                deck_spec,
                storage=storage,
                project_id=project_id,
                figures=sources.figures,
                max_generated_images=budget,
                only_slide_ids=only_slide_ids,
            )
        except Exception as exc:
            logger.warning(
                "presentation_image_stage_failed",
                extra={"error_type": type(exc).__name__},
            )
            return deck_spec

    # ====================================================================
    # Single-slide regeneration (judge + conversational edit layer)
    # ====================================================================

    async def regenerate_slide(
        self,
        deck: DeckSpec,
        slide_id: str,
        sources: SourceProcessingResult,
        project_id: str,
        progress: ProgressCallback,
        *,
        package: GenerationPackage,
        instruction: str | None = None,
    ) -> tuple[DeckSpec, SlideRegenResult]:
        """Regenerate one slide end-to-end: content → splice → re-validate → images.

        Chains the editorial single-slide regen, the id-keyed splice (with title
        propagation for the hero), the section-scoped figure re-check, and a
        scoped image re-resolution restricted to the regenerated slide's id (so
        only its null-URL slots resolve and every other slide keeps its image).
        Returns the updated deck plus a :class:`SlideRegenResult` whose findings
        combine the per-slide checks and the section-scoped re-check — the caller
        (quality judge or edit layer) reads ``passed`` to decide whether to keep or
        retry.

        The image re-run consumes the tier's generated-image budget for the
        regenerated slide even if the edit did not touch its image; the budget is
        logged (``presentation_slide_regenerated``) so a judge regenerating many
        slides can see the per-regen cost ceiling.
        :class:`EditorialSlideRegenError` (missing plan, unknown id, empty LLM
        output) propagates unchanged — it is a precise, caller-actionable error,
        not a generic pipeline stage failure.
        """

        await progress("Regenerating slide", 1, 2)
        result = await self._editorial_pass.regenerate_slide_content(
            deck, slide_id, instruction=instruction, claims=sources.claims
        )
        new_deck = self._editorial_pass.splice_regenerated_slide(deck, result.slide)

        findings = list(result.findings)
        if new_deck.plan is not None:
            findings.extend(
                validate_section_against_plan(new_deck.slides, new_deck.plan, result.slide)
            )
        passed = not any(f.severity is AuditSeverity.FAIL for f in findings)
        logger.info(
            "presentation_slide_regenerated %s",
            json.dumps(
                {
                    "slide_id": slide_id,
                    "passed": passed,
                    "findings": len(findings),
                    "image_budget": image_budget_for_package(package),
                },
                ensure_ascii=False,
                default=str,
            ),
        )

        await progress("Resolving slide image", 2, 2)
        new_deck = await self._resolve_deck_images(
            new_deck,
            sources,
            project_id,
            package=package,
            only_slide_ids=frozenset({result.slide.slide_id}),
        )
        # Count the PAID generated slots this regen filled by reading the slide
        # back out of the resolved deck (the image pass mutates it in place, and
        # ``result.slide`` may be a pre-resolution copy). Only generated figure /
        # title-hero background images cost money; Commons portraits are free.
        resolved = next(
            (s for s in new_deck.slides if s.slide_id == result.slide.slide_id),
            result.slide,
        )
        image_count = _count_generated_images(resolved)
        return new_deck, SlideRegenResult(
            slide=result.slide,
            findings=findings,
            estimated_cost_usd=result.estimated_cost_usd,
            image_count=image_count,
        )

    async def apply_fixes_and_render(
        self,
        deck: DeckSpec,
        fixes: Sequence[SlideFix],
        sources: SourceProcessingResult,
        project_id: str,
        formats: list[ExportFormat],
        progress: ProgressCallback,
        *,
        package: GenerationPackage,
    ) -> FixAndRenderResult:
        """Apply a batch of slide fixes, persist once, render once.

        The brain's primary fix tool (Build 2, Stage 3). Each fix re-runs the
        single-slide :meth:`regenerate_slide` — content regen, id-keyed splice,
        section-scoped re-check, and a scoped image re-resolution restricted to
        that slide — accumulating the edits on one deck. The batch persists ONCE
        (``save_deck`` upsert, replacing the project's current deck row) and
        renders ONCE; it never persists or renders per fix.

        Persist runs BEFORE render (mirroring :meth:`run_full_pipeline`) so
        durability does not hinge on the renderer subprocess, but here the chain
        owns its own ``try/except`` instead of the silent :meth:`_persist_deck`:
        an edit's persisted deck already exists, so a ``save_deck`` failure raises
        :class:`_OrchestratorError` (step ``persist_deck``) and ABORTS before render
        rather than being swallowed. Rendering past a failed persist would deliver
        files a stale DB deck cannot reflect — the next ``load_session`` resurrects
        the pre-fix deck and silently loses the delivered fix; failing here keeps the
        DB and the delivered files consistent (the edit-path caller degrades this
        raise gracefully, exactly as it already guards a fix-chain error).

        Batch semantics are ATOMIC: a fix that raises (unknown id, empty LLM
        output, or a content-critic hard stop) propagates before persist/render,
        so the persisted deck and the caller's deck are never left half-applied.
        Image budget already spent on earlier fixes is the accepted cost of a
        failed attempt. ``slide_id``\\ s are validated up front so a typo in a
        later fix never burns regen spend on the earlier ones.

        ``formats`` is required (no silent default): the caller passes the same
        set it originally delivered, because the renderer's output set — not
        ``deck.export_formats``, which first-gen never writes back — is what the
        download surface serves.
        """

        if not fixes:
            raise ValueError("apply_fixes_and_render requires at least one fix")
        known_ids = {slide.slide_id for slide in deck.slides}
        unknown = sorted({fix.slide_id for fix in fixes if fix.slide_id not in known_ids})
        if unknown:
            raise ValueError(f"unknown slide_id(s) in fix batch: {', '.join(unknown)}")

        working = deck
        outcomes: list[SlideRegenResult] = []
        total = len(fixes)
        for index, fix in enumerate(fixes, start=1):
            await progress(f"Applying fix {index}/{total}", index, total)
            working, outcome = await self.regenerate_slide(
                working,
                fix.slide_id,
                sources,
                project_id,
                progress,
                package=package,
                instruction=fix.instruction,
            )
            outcomes.append(outcome)

        try:
            await self._db.save_deck(project_id, working)
        except Exception as exc:
            logger.warning(
                "presentation_edit_persist_failed",
                extra={"project_id": project_id, "error_type": type(exc).__name__},
            )
            raise _OrchestratorError("persist_deck", exc) from exc

        render_result = await self.render(working, formats, progress, project_id=project_id)
        return FixAndRenderResult(
            deck=working,
            render=render_result,
            fixes=outcomes,
            estimated_cost_usd=sum(o.estimated_cost_usd for o in outcomes),
            image_count=sum(o.image_count for o in outcomes),
        )

    # ====================================================================
    # STEP 7 — render via Node worker
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

        await progress("Rendering presentation", 7, TOTAL_STEPS)

        try:
            output_dir = Path(tempfile.mkdtemp(prefix="nashr_pres_"))
            deck_json_path = output_dir / "deck.json"
            await asyncio.to_thread(
                deck_json_path.write_text,
                deck_spec.model_dump_json(),
                "utf-8",
            )

            try:
                Path("/app/debug").mkdir(parents=True, exist_ok=True)
                Path("/app/debug/last_deck.json").write_text(deck_spec.model_dump_json(), "utf-8")
            except Exception:
                pass
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
                full_err = (completed.stderr or "").strip()
                logger.warning(
                    "RENDER_STDERR_FULL fmt=%s code=%s err=%s",
                    ext,
                    completed.returncode,
                    full_err[:3000],
                )
                tail = full_err.splitlines()
                snippet = tail[-1] if tail else "non-zero exit"
                result.warnings.append(f"{ext}: {snippet}")
                logger.warning(
                    "presentation_render_nonzero",
                    extra={"format": ext, "stderr_tail": snippet},
                )
                continue

            # Render succeeded, but the worker still writes audit WARNINGS to
            # stderr — notably Q1 truncation (L1's reliability floor degraded a
            # slide so the deck could still export). Surface them so the degrade
            # is locatable in the logs instead of being swallowed on success.
            warn_text = (completed.stderr or "").strip()
            if warn_text:
                logger.warning(
                    "presentation_render_warnings",
                    extra={"format": ext, "stderr_tail": warn_text[:3000]},
                )

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
                if project_id:
                    # Stable per-format key (migration 007): a regenerated or
                    # brain-fixed deck OVERWRITES in place, so share links and
                    # web downloads never point at an orphaned title-named key.
                    key = FileStorage.stable_generated_key(project_id, ext)
                else:
                    key = FileStorage.generated_key(path.stem, path.name)
                await storage.upload(path, key)
                if project_id:
                    await self._register_generated_file(project_id, ext, key, path)
            except Exception as exc:
                result.warnings.append(f"{ext}: upload failed ({type(exc).__name__})")
                logger.warning(
                    "presentation_storage_upload_failed",
                    extra={"format": ext, "error_type": type(exc).__name__},
                )

    async def _register_generated_file(
        self,
        project_id: str,
        ext: str,
        key: str,
        path: Path,
    ) -> None:
        """Upsert the project's generated_files row for one format (best-effort).

        Keys on (project_id, file_type), so re-delivery refreshes the row
        instead of appending duplicates — the web surface reads these rows.
        A DB failure never blocks delivery; the local files still flow.
        """

        try:
            size = int(path.stat().st_size)
            await self._db.upsert_generated_file(project_id, ext, key, size)
        except Exception as exc:
            logger.warning(
                "presentation_generated_file_register_failed",
                extra={"format": ext, "error_type": type(exc).__name__},
            )

    # ====================================================================
    # FULL PIPELINE
    # ====================================================================

    async def _persist_deck(self, deck_spec: DeckSpec, project_id: str) -> None:
        """Persist the structurally final deck so it survives past delivery.

        Build 2, Stage 0: the brain later loads and edits this DeckSpec, so it
        must outlive the render that delivers it. Persisted from inside the
        pipeline because the spec never leaves the orchestrator — the handler
        receives only :class:`PresentationRenderResult` file paths.

        Best-effort and non-fatal, mirroring :meth:`_register_source`: a
        persistence failure logs a warning and is swallowed so the deck still
        renders and delivers. Stage 0 is additive and must not regress the
        working delivery path. Runs before :meth:`render` so durability does
        not depend on the renderer subprocess succeeding; ``render`` does not
        mutate the spec, so persisting first loses nothing.
        """

        try:
            await self._db.save_deck(project_id, deck_spec)
        except Exception as exc:
            logger.warning(
                "presentation_deck_persist_failed",
                extra={"project_id": project_id, "error_type": type(exc).__name__},
            )

    async def run_full_pipeline(
        self,
        file_infos: list[dict[str, object]],
        project_id: str,
        user_id: str,
        language: str,
        raw_answers: Mapping[str, object] | None,
        requested_formats: list[ExportFormat] | None,
        progress: ProgressCallback,
        *,
        package: GenerationPackage,
    ) -> PresentationPipelineResult:
        """Drive the full presentation pipeline end-to-end.

        Called *after* payment has been confirmed. The orchestrator
        raises on unrecoverable errors (no usable sources, editorial
        pass failure); the caller (the bot handler) is responsible for
        refunding credits when this raises.

        ``package`` is the paid tier; it threads through to the image stage to
        set the per-deck generated-image budget. Required keyword-only so a
        caller cannot silently default a paid path (invariant I1).
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
        deck_spec = await self.resolve_images(
            deck_spec, sources, project_id, progress, package=package
        )
        await self._persist_deck(deck_spec, project_id)
        render = await self.render(deck_spec, formats, progress, project_id=project_id)
        # render() degrades each format to a warning, so a total failure returns
        # normally with zero files — the delivery handler would then announce success
        # with nothing to download. Fail the job so the handler refunds; partial
        # success (>=1 file) still returns, preserving render()'s degrade semantics.
        if not render.by_extension():
            detail = "; ".join(render.warnings) or "no renderer output"
            raise _OrchestratorError(
                "render",
                RuntimeError(f"render produced no deliverable files — {detail}"),
            )
        return PresentationPipelineResult(render=render, sources=sources)


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


def _count_generated_images(slide: SlideSpec) -> int:
    """Count the PAID generated image slots filled on a freshly regenerated slide.

    Only the generated figure and the title-hero background go through the paid
    image model (:data:`IMAGE_COST_USD`); Commons portraits are free. A regen
    emits the slide with null image URLs and the image pass fills them, so a
    non-null url on either slot means one paid image was generated this regen.
    """

    content = slide.content
    return int(content.figure_url is not None) + int(content.background_url is not None)


__all__ = [
    "TOTAL_STEPS",
    "PresentationOrchestrator",
    "PresentationRenderResult",
    "ProgressCallback",
]
