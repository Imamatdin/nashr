"""Integrates approved suggestions into the project's evidence matrix.

When the user approves a suggestion in the UI it has not yet entered
the evidence matrix; this module performs the conversion. Each
approved suggestion becomes:

* one :class:`SourceChunkCreate` carrying the suggestion description
  (the "virtual source" body),
* one :class:`SourceClaimCreate` summarising the suggestion as a
  citable claim, and
* one :class:`EvidenceMatrixEntry` with ``citation_status=READY``
  pointing at the article section the user picked.

Authoritative providers (PubMed, World Bank, lex.uz) are pre-verified
external data, so suggestions enter the matrix as ``STRONG`` claims at
``READY`` status — no user-answer link is required.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import UUID, uuid4

from packages.core.enums import CitationStatus, ClaimStrength, ClaimType
from packages.core.models.evidence import EvidenceMatrix, EvidenceMatrixEntry
from packages.core.models.source import SourceChunkCreate, SourceClaimCreate
from packages.core.models.suggestion import (
    ApprovedSuggestion,
    BatchIntegrationResult,
    IntegrationResult,
    Suggestion,
    SuggestionSource,
)

logger = logging.getLogger(__name__)

_CLAIM_TEXT_DESCRIPTION_LIMIT: int = 200
_CLAIM_TEXT_MAX_LEN: int = 500


class SuggestionIntegrator:
    """Convert approved suggestions into evidence-matrix entries.

    Stateless: callers may share a single instance. The integrator does
    not perform persistence — it returns the new chunk/claim/entry
    objects so the article worker can write them in the same DB
    transaction as the rest of its updates.
    """

    def integrate_approved(
        self,
        approved: ApprovedSuggestion,
        evidence_matrix: EvidenceMatrix,
        project_id: str,
    ) -> IntegrationResult:
        """Add one approved suggestion to ``evidence_matrix`` in-place semantics.

        The matrix is not mutated; the caller should add the returned
        entry to the matrix's ``entries`` list (or use
        :meth:`integrate_batch` which does so).
        """

        suggestion = approved.suggestion
        suggestion_id = suggestion.suggestion_id
        try:
            section_uuid = _parse_section_id(approved.target_section_id)
            project_uuid = _parse_project_id(project_id)
            virtual_source_id = uuid4()
            chunk = _build_chunk(suggestion, virtual_source_id, project_id)
            claim = _build_claim(suggestion, virtual_source_id, project_id)
            entry = _build_matrix_entry(
                project_uuid=project_uuid,
                source_chunk_uuid=virtual_source_id,
                section_uuid=section_uuid,
            )
        except IntegrationError as exc:
            return IntegrationResult(
                success=False,
                suggestion_id=suggestion_id,
                error=str(exc),
            )
        except Exception as exc:
            logger.warning(
                "suggestion_integration_failed",
                extra={"suggestion_id": suggestion_id, "error": str(exc)},
            )
            return IntegrationResult(
                success=False,
                suggestion_id=suggestion_id,
                error=f"unexpected: {exc}",
            )

        _ = evidence_matrix
        return IntegrationResult(
            success=True,
            suggestion_id=suggestion_id,
            claim_created=claim,
            chunk_created=chunk,
            matrix_entry_created=entry,
        )

    def integrate_batch(
        self,
        approved: list[ApprovedSuggestion],
        evidence_matrix: EvidenceMatrix,
        project_id: str,
    ) -> BatchIntegrationResult:
        """Integrate a batch of approved suggestions, returning the updated matrix.

        Failed integrations are recorded in ``results`` with their error
        message; successful ones append to the matrix's ``entries``.
        """

        results: list[IntegrationResult] = []
        new_entries: list[EvidenceMatrixEntry] = list(evidence_matrix.entries)
        succeeded = 0
        failed = 0
        for item in approved:
            res = self.integrate_approved(item, evidence_matrix, project_id)
            results.append(res)
            if res.success and res.matrix_entry_created is not None:
                new_entries.append(res.matrix_entry_created)
                succeeded += 1
            else:
                failed += 1

        updated = evidence_matrix.model_copy(
            update={
                "entries": new_entries,
                "updated_at": datetime.now(UTC),
            }
        )
        return BatchIntegrationResult(
            total=len(approved),
            succeeded=succeeded,
            failed=failed,
            results=results,
            updated_matrix=updated,
        )


class IntegrationError(Exception):
    """Raised when a single suggestion cannot be integrated."""


def _parse_section_id(raw: str) -> UUID:
    """Parse the target section id; raise :class:`IntegrationError` if invalid."""

    try:
        return UUID(raw)
    except (ValueError, AttributeError) as exc:
        raise IntegrationError(f"invalid section id {raw!r}: {exc}") from exc


def _parse_project_id(raw: str) -> UUID:
    """Parse the project id; raise :class:`IntegrationError` if invalid."""

    try:
        return UUID(raw)
    except (ValueError, AttributeError) as exc:
        raise IntegrationError(f"invalid project id {raw!r}: {exc}") from exc


def _build_chunk(
    suggestion: Suggestion, virtual_source_id: UUID, project_id: str
) -> SourceChunkCreate:
    """Wrap the suggestion's description as a virtual source chunk."""

    text = suggestion.description.strip() or suggestion.title.strip()
    if not text:
        raise IntegrationError("suggestion has no description or title for chunk")
    return SourceChunkCreate(
        source_id=str(virtual_source_id),
        project_id=project_id,
        chunk_index=0,
        text=text[:10_000],
        page=None,
        is_ocr=False,
    )


def _build_claim(
    suggestion: Suggestion, virtual_source_id: UUID, project_id: str
) -> SourceClaimCreate:
    """Build a STRONG claim summarising the suggestion."""

    title = suggestion.title.strip()
    description = suggestion.description.strip()
    if description:
        snippet = description[:_CLAIM_TEXT_DESCRIPTION_LIMIT]
        body = f"{title}: {snippet}"
    else:
        body = title
    body = body[:_CLAIM_TEXT_MAX_LEN]
    if len(body) < 10:
        raise IntegrationError("suggestion text too short to form a claim")

    return SourceClaimCreate(
        source_chunk_id=str(virtual_source_id),
        project_id=project_id,
        claim_text=body,
        quote=None,
        strength=ClaimStrength.STRONG,
        claim_type=_infer_claim_type(suggestion.source_provider),
    )


def _build_matrix_entry(
    project_uuid: UUID,
    source_chunk_uuid: UUID,
    section_uuid: UUID,
) -> EvidenceMatrixEntry:
    """Build the matrix entry; status is READY since suggestions are pre-verified."""

    return EvidenceMatrixEntry(
        project_id=project_uuid,
        claim_id=uuid4(),
        source_chunk_id=source_chunk_uuid,
        user_answer_id=None,
        article_section_id=section_uuid,
        citation_status=CitationStatus.READY,
        created_at=datetime.now(UTC),
    )


def _infer_claim_type(provider: SuggestionSource) -> ClaimType:
    """Map provider source onto the most apt :class:`ClaimType`."""

    if provider is SuggestionSource.PUBMED:
        return ClaimType.EMPIRICAL_FINDING
    if provider in {SuggestionSource.WORLD_BANK, SuggestionSource.DATA_GOV_UZ}:
        return ClaimType.STATISTICAL_RESULT
    if provider is SuggestionSource.LEX_UZ:
        return ClaimType.GENERAL_FACT
    return ClaimType.THEORETICAL_ARGUMENT


__all__ = ["IntegrationError", "SuggestionIntegrator"]
