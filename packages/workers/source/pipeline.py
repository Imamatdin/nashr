"""End-to-end source-processing pipeline: validate → parse → OCR → chunk → claims.

This is the single entry point a worker should call when a user uploads a
file. It composes the four stages already built (validation, parsing, OCR,
chunking, claim extraction) and returns one :class:`SourcePipelineResult`
that captures every artefact produced — including soft warnings so callers
can decide whether to surface them to the user or silently ignore.

Failure semantics:

* Hard validation failure (Magika rejects the file) → short-circuits with
  ``parsed=None`` and the rejection reason in ``errors``.
* Empty extracted text after parsing+OCR → ``chunks`` and ``claims`` empty,
  warning appended to ``errors``. Pipeline does not raise: a scanned PDF
  with unrecognisable text is a real and recoverable user case.
* Per-chunk claim-extraction failures are already absorbed inside
  :class:`ClaimExtractor`; the pipeline just collects the result.
"""

from __future__ import annotations

import logging

from packages.core.models.source import (
    SourceChunkCreate,
    SourceClaimCreate,
    SourcePipelineResult,
)
from packages.workers.source.chunker import SourceChunker
from packages.workers.source.claim_extractor import ClaimExtractor
from packages.workers.source.parse_service import SourceParseService
from packages.workers.source.validation import FileValidationService

logger = logging.getLogger(__name__)


class SourcePipeline:
    """Composes validation, parsing, chunking, and claim extraction."""

    def __init__(
        self,
        validator: FileValidationService | None = None,
        parser: SourceParseService | None = None,
        chunker: SourceChunker | None = None,
        extractor: ClaimExtractor | None = None,
    ) -> None:
        self._validator = validator if validator is not None else FileValidationService()
        self._parser = parser if parser is not None else SourceParseService()
        self._chunker = chunker if chunker is not None else SourceChunker()
        self._extractor = extractor if extractor is not None else ClaimExtractor()

    async def process(
        self,
        file_bytes: bytes,
        filename: str,
    ) -> SourcePipelineResult:
        """Run the complete pipeline against one upload."""

        validation = await self._validator.validate(file_bytes, filename)
        if not validation.valid:
            reason = validation.rejection_reason or "File validation failed."
            return SourcePipelineResult(
                validation=validation,
                parsed=None,
                chunks=[],
                claims=[],
                errors=[reason],
            )

        errors: list[str] = []
        if validation.warning is not None:
            errors.append(validation.warning)

        parsed = await self._parser.parse(file_bytes, filename, validation.detected_type)
        errors.extend(parsed.parse_errors)

        chunks: list[SourceChunkCreate] = self._chunker.chunk_parsed_source(parsed)
        if not chunks:
            errors.append("No text could be extracted from this file.")
            return SourcePipelineResult(
                validation=validation,
                parsed=parsed,
                chunks=[],
                claims=[],
                errors=errors,
            )

        claims: list[SourceClaimCreate] = await self._extractor.extract_claims(
            chunks, parsed.metadata
        )

        return SourcePipelineResult(
            validation=validation,
            parsed=parsed,
            chunks=chunks,
            claims=claims,
            errors=errors,
        )


__all__ = ["SourcePipeline"]
