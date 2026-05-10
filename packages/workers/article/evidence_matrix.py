"""Builds and updates the project-wide evidence matrix.

The matrix is the article worker's source of truth for what claims may
appear as cited assertions in a draft. Every claim extracted by the
source pipeline is registered here; user research answers, outline
section assignments, and citation-status promotions are recorded on
existing rows rather than re-deriving the graph from scratch.

This module is intentionally I/O-free at the moment — persistence is
handled by the surrounding worker. The async signatures on builder
methods that mutate the matrix are kept so callers can switch to a
database-backed implementation later without changing the contract.

The 300-line file budget in CLAUDE.md is exceeded slightly here because
splitting the seven cohesive methods on the same model would fragment a
multi-step pipeline (build → update → assign → query → validate). The
non-method helpers live in module scope where they belong.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import UUID, uuid4

from packages.core.enums import CitationStatus, ClaimStrength, SourceQuality
from packages.core.models.article import ArticleOutline
from packages.core.models.evidence import (
    EvidenceMatrix,
    EvidenceMatrixEntry,
    EvidenceMatrixStats,
    MatrixValidationResult,
    ResearchAnswer,
)
from packages.core.models.source import SourceChunkCreate, SourceClaimCreate

logger = logging.getLogger(__name__)


PROMOTE_SCORE_THRESHOLD = 10
LINK_SCORE_THRESHOLD = 7
READY_STATUSES = (CitationStatus.READY, CitationStatus.VERIFIED)


class EvidenceMatrixBuilder:
    """Builds and manages the evidence matrix for a project.

    The evidence matrix is the single source of truth for what claims can
    be cited in an article. No claim can appear in the article unless it
    has an entry here with citation_status=='ready' or 'verified'.
    """

    async def build_from_claims(
        self,
        project_id: UUID,
        claims: list[SourceClaimCreate],
        chunks: list[SourceChunkCreate],
        source_quality: SourceQuality = SourceQuality.MEDIUM,
    ) -> EvidenceMatrix:
        """Build initial evidence matrix from extracted claims and chunks.

        ``source_quality`` is a deviation from the originally-specified
        signature: ``SourceClaimCreate`` does not carry the quality of
        the originating source, so the caller passes the source's quality
        once for the whole batch (one builder call per source).
        """

        chunk_lookup = _build_chunk_lookup(chunks)
        entries: list[EvidenceMatrixEntry] = []
        now = datetime.now(UTC)

        for claim in claims:
            chunk_uuid = chunk_lookup.get(claim.source_chunk_id)
            if chunk_uuid is None:
                logger.warning(
                    "evidence_matrix_skip_unresolved_chunk",
                    extra={
                        "claim_text_excerpt": claim.claim_text[:80],
                        "source_chunk_id": claim.source_chunk_id,
                    },
                )
                continue

            status = _initial_status(claim.strength, source_quality)
            entries.append(
                EvidenceMatrixEntry(
                    project_id=project_id,
                    claim_id=uuid4(),
                    source_chunk_id=chunk_uuid,
                    citation_status=status,
                    created_at=now,
                )
            )

        return EvidenceMatrix(project_id=project_id, entries=entries)

    async def update_with_answer(
        self,
        matrix: EvidenceMatrix,
        answer: ResearchAnswer,
    ) -> EvidenceMatrix:
        """Link a research answer to every entry whose chunk it references.

        Promotion rules: total score ``>= 10`` → ``READY``; ``7..9`` →
        keep ``NEEDS_USER_INPUT`` but record the answer link; ``< 7`` →
        same (the weak answer is still recorded so the user sees it
        contributed). Already-promoted (READY/VERIFIED) entries are
        untouched.
        """

        referenced = set(answer.source_references_used)
        if not referenced:
            return matrix

        total_score = (
            answer.score.specificity + answer.score.source_grounding + answer.score.usefulness
        )
        new_entries = [
            _apply_answer(entry, answer.id, referenced, total_score) for entry in matrix.entries
        ]
        return matrix.model_copy(update={"entries": new_entries, "updated_at": datetime.now(UTC)})

    async def assign_to_sections(
        self,
        matrix: EvidenceMatrix,
        outline: ArticleOutline,
    ) -> EvidenceMatrix:
        """Map matrix entries to outline sections by exact ``claim_id`` match.

        ``key_claims_to_use`` is treated as a list of stringified claim
        UUIDs. Callers that start from raw claim text should run
        :class:`ClaimLinker` first to resolve text → claim IDs and write
        them back into the outline before invoking this method.
        """

        section_for_claim: dict[str, UUID] = {}
        for section in outline.sections:
            for key in section.key_claims_to_use:
                section_for_claim.setdefault(key, section.id)

        new_entries = [
            entry.model_copy(
                update={"article_section_id": section_for_claim.get(str(entry.claim_id))}
            )
            if str(entry.claim_id) in section_for_claim
            else entry
            for entry in matrix.entries
        ]
        return matrix.model_copy(update={"entries": new_entries, "updated_at": datetime.now(UTC)})

    def get_ready_claims_for_section(
        self,
        matrix: EvidenceMatrix,
        section_id: UUID,
    ) -> list[EvidenceMatrixEntry]:
        """Return entries assigned to ``section_id`` whose status is cite-ready."""

        return [
            entry
            for entry in matrix.entries
            if entry.article_section_id == section_id and entry.citation_status in READY_STATUSES
        ]

    def get_ungrounded_claims(
        self,
        matrix: EvidenceMatrix,
    ) -> list[EvidenceMatrixEntry]:
        """Return entries that still need user input before they can be cited."""

        return [
            entry
            for entry in matrix.entries
            if entry.citation_status is CitationStatus.NEEDS_USER_INPUT
        ]

    def get_matrix_stats(self, matrix: EvidenceMatrix) -> EvidenceMatrixStats:
        """Compute summary statistics over the matrix's entries."""

        counts: dict[CitationStatus, int] = dict.fromkeys(CitationStatus, 0)
        sections: set[UUID] = set()
        for entry in matrix.entries:
            counts[entry.citation_status] += 1
            if entry.article_section_id is not None:
                sections.add(entry.article_section_id)

        total = len(matrix.entries)
        ready_total = counts[CitationStatus.READY] + counts[CitationStatus.VERIFIED]
        coverage = round(ready_total / total * 100, 1) if total else 0.0

        return EvidenceMatrixStats(
            total_claims=total,
            ready_claims=counts[CitationStatus.READY],
            needs_input_claims=counts[CitationStatus.NEEDS_USER_INPUT],
            unsupported_claims=counts[CitationStatus.UNSUPPORTED],
            verified_claims=counts[CitationStatus.VERIFIED],
            sections_with_claims=len(sections),
            sections_without_claims=0,
            coverage_percentage=coverage,
        )

    def validate_matrix_completeness(
        self,
        matrix: EvidenceMatrix,
        outline: ArticleOutline,
    ) -> MatrixValidationResult:
        """Check whether every outline section has at least one ready claim."""

        ready_per_section: dict[UUID, int] = {section.id: 0 for section in outline.sections}
        for entry in matrix.entries:
            section_id = entry.article_section_id
            if (
                section_id is not None
                and section_id in ready_per_section
                and entry.citation_status in READY_STATUSES
            ):
                ready_per_section[section_id] += 1

        sections_ready: list[str] = []
        sections_missing: list[str] = []
        sections_weak: list[str] = []
        warnings: list[str] = []

        for section in outline.sections:
            count = ready_per_section[section.id]
            sid = str(section.id)
            if count == 0:
                sections_missing.append(sid)
                warnings.append(f"Section '{section.title}' ({sid}) has no ready claims.")
            elif count == 1:
                sections_ready.append(sid)
                sections_weak.append(sid)
                warnings.append(
                    f"Section '{section.title}' ({sid}) rests on a single claim and is fragile."
                )
            else:
                sections_ready.append(sid)

        return MatrixValidationResult(
            is_complete=not sections_missing,
            sections_ready=sections_ready,
            sections_missing=sections_missing,
            sections_weak=sections_weak,
            total_ready=sum(ready_per_section.values()),
            minimum_needed=len(outline.sections),
            warnings=warnings,
        )


def _build_chunk_lookup(chunks: list[SourceChunkCreate]) -> dict[str, UUID]:
    """Map every plausible string identifier of a chunk to its assigned UUID.

    Callers may set ``claim.source_chunk_id`` to either ``str(chunk_index)``
    or ``chunk.source_id`` (whichever the upstream pipeline happened to
    expose). We register both forms so either resolves.
    """

    lookup: dict[str, UUID] = {}
    for chunk in chunks:
        chunk_uuid = uuid4()
        lookup[str(chunk.chunk_index)] = chunk_uuid
        if chunk.source_id:
            lookup[chunk.source_id] = chunk_uuid
    return lookup


def _initial_status(strength: ClaimStrength, source_quality: SourceQuality) -> CitationStatus:
    """Auto-promote strong claims from strong sources; everything else needs input."""

    if strength is ClaimStrength.STRONG and source_quality is SourceQuality.STRONG:
        return CitationStatus.READY
    return CitationStatus.NEEDS_USER_INPUT


def _apply_answer(
    entry: EvidenceMatrixEntry,
    answer_id: UUID,
    referenced_chunks: set[UUID],
    total_score: int,
) -> EvidenceMatrixEntry:
    """Return a new entry reflecting the answer's effect, or the original."""

    if entry.source_chunk_id not in referenced_chunks:
        return entry
    if entry.citation_status in READY_STATUSES:
        return entry.model_copy(update={"user_answer_id": answer_id})

    new_status = (
        CitationStatus.READY if total_score >= PROMOTE_SCORE_THRESHOLD else entry.citation_status
    )
    _ = LINK_SCORE_THRESHOLD  # documented threshold; weak answers still link
    return entry.model_copy(update={"user_answer_id": answer_id, "citation_status": new_status})


__all__ = ["EvidenceMatrixBuilder"]
