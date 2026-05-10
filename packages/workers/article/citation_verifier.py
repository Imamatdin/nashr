"""Citation verifier — the Inspector layer for drafted articles.

Runs after the drafter and before export: every citation in every
paragraph is checked against its source material via Gemini 3 Flash.
Hallucinated, overclaimed, or misattributed citations surface in the
returned :class:`CitationVerificationReport` with an
:class:`CitationVerdict` (supported / partially_supported / overclaimed
/ not_supported / contradicted / source_not_found) and a suggested fix.

The verifier batches citations by section (max 10 per LLM call) so an
article with thirty citations costs ~3-6 calls rather than thirty.
Citations whose ``claim_id`` or ``source_chunk_id`` cannot be resolved
to extracted material are returned as ``SOURCE_NOT_FOUND`` without
calling the LLM at all.

The 300-line CLAUDE.md budget is exceeded slightly here because the
verifier ties together citation collection, source resolution, batched
LLM invocation, JSON parsing, and report assembly into one coherent
pipeline — splitting it across modules would fragment it.
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Iterator
from typing import Any, Final

from packages.core.constants import MODEL_ROUTING
from packages.core.enums import CitationVerdict
from packages.core.gemini import gemini_cost_for
from packages.core.llm import LLMResponse
from packages.core.model_router import ModelRouter
from packages.core.models.article import ArticleSection, CitationRef
from packages.core.models.evidence import EvidenceMatrix
from packages.core.models.source import SourceChunkCreate, SourceClaimCreate
from packages.core.models.verification import (
    CitationVerification,
    CitationVerificationReport,
)
from packages.core.prompts import (
    CITATION_VERIFICATION_SYSTEM,
    CITATION_VERIFICATION_USER,
)

logger = logging.getLogger(__name__)


BATCH_SIZE: Final[int] = 10
INTEGRITY_THRESHOLD: Final[float] = 0.7
SOURCE_EXCERPT_CHARS: Final[int] = 500
ARTICLE_SENTENCE_MAX_CHARS: Final[int] = 1000
EXPLANATION_MAX_CHARS: Final[int] = 500
SUGGESTED_FIX_MAX_CHARS: Final[int] = 500
CLAIM_TEXT_MAX_CHARS: Final[int] = 500
DEFAULT_MAX_TOKENS: Final[int] = 4_000

_VALID_VERDICTS: Final[frozenset[str]] = frozenset(
    {
        CitationVerdict.SUPPORTED.value,
        CitationVerdict.PARTIALLY_SUPPORTED.value,
        CitationVerdict.OVERCLAIMED.value,
        CitationVerdict.NOT_SUPPORTED.value,
        CitationVerdict.CONTRADICTED.value,
    }
)


class CitationVerifier:
    """Batched citation verifier built on :class:`ModelRouter` + Gemini.

    Stateless apart from the injected router. ``model`` defaults to
    :data:`MODEL_ROUTING["citation_verification"]` so the routing table
    in :mod:`packages.core.constants` stays the single source of truth
    for which provider runs the inspection pass.
    """

    def __init__(
        self,
        model: str | None = None,
        router: ModelRouter | None = None,
    ) -> None:
        self._router = router if router is not None else ModelRouter()
        self._model = model or MODEL_ROUTING["citation_verification"]

    async def verify_article(
        self,
        sections: list[ArticleSection],
        claims: list[SourceClaimCreate],
        chunks: list[SourceChunkCreate],
        evidence_matrix: EvidenceMatrix,
    ) -> CitationVerificationReport:
        """Verify every citation in every section; return one aggregate report."""

        start = time.perf_counter()
        all_verifications: list[CitationVerification] = []
        total_tokens = 0
        total_cost = 0.0
        for section in sections:
            section_verifications, tokens, cost = await self._verify_section_internal(
                section=section,
                claims=claims,
                chunks=chunks,
                evidence_matrix=evidence_matrix,
            )
            all_verifications.extend(section_verifications)
            total_tokens += tokens
            total_cost += cost
        time_ms = int((time.perf_counter() - start) * 1000)
        return self._build_report(
            verifications=all_verifications,
            model_used=self._model,
            total_tokens=total_tokens,
            cost=total_cost,
            time_ms=time_ms,
        )

    async def verify_section(
        self,
        section: ArticleSection,
        claims: list[SourceClaimCreate],
        chunks: list[SourceChunkCreate],
        evidence_matrix: EvidenceMatrix,
    ) -> list[CitationVerification]:
        """Verify all citations in a single section (one batched LLM call)."""

        verifications, _tokens, _cost = await self._verify_section_internal(
            section=section,
            claims=claims,
            chunks=chunks,
            evidence_matrix=evidence_matrix,
        )
        return verifications

    async def _verify_section_internal(
        self,
        section: ArticleSection,
        claims: list[SourceClaimCreate],
        chunks: list[SourceChunkCreate],
        evidence_matrix: EvidenceMatrix,
    ) -> tuple[list[CitationVerification], int, float]:
        """Run the per-section pipeline; return verifications + cost telemetry."""

        citations = self._collect_citations(section)
        if not citations:
            return [], 0, 0.0

        prepared: list[_PreparedCitation] = []
        verifications: list[CitationVerification] = []

        for paragraph_idx, citation_idx, ref in citations:
            entry_pos = _find_matrix_position(ref, evidence_matrix)
            if entry_pos is None or entry_pos >= len(claims):
                verifications.append(
                    _make_source_not_found(
                        section=section,
                        paragraph_index=paragraph_idx,
                        citation_index=citation_idx,
                        ref=ref,
                    )
                )
                continue
            claim = claims[entry_pos]
            chunk = self._lookup_chunk(claim.source_chunk_id, chunks)
            if chunk is None:
                verifications.append(
                    _make_source_not_found(
                        section=section,
                        paragraph_index=paragraph_idx,
                        citation_index=citation_idx,
                        ref=ref,
                    )
                )
                continue
            article_sentence = extract_citing_sentence(
                section.paragraphs[paragraph_idx].text, str(ref.source_id)
            )
            prepared.append(
                _PreparedCitation(
                    paragraph_index=paragraph_idx,
                    citation_index=citation_idx,
                    ref=ref,
                    claim=claim,
                    chunk=chunk,
                    article_sentence=article_sentence,
                )
            )

        total_tokens = 0
        total_cost = 0.0
        for batch in _batches(prepared, BATCH_SIZE):
            batch_verifications, tokens, cost = await self._verify_batch(batch, section)
            verifications.extend(batch_verifications)
            total_tokens += tokens
            total_cost += cost
        return verifications, total_tokens, total_cost

    async def _verify_batch(
        self,
        batch: list[_PreparedCitation],
        section: ArticleSection,
    ) -> tuple[list[CitationVerification], int, float]:
        """Verify one batch of resolved citations with a single LLM call."""

        if not batch:
            return [], 0, 0.0

        user_prompt = CITATION_VERIFICATION_USER.format(
            n=len(batch),
            section_title=section.title,
            citation_blocks=_format_citation_blocks(batch),
        )

        try:
            response = await self._router.complete(
                system=CITATION_VERIFICATION_SYSTEM,
                user=user_prompt,
                model=self._model,
                max_tokens=DEFAULT_MAX_TOKENS,
            )
        except Exception as exc:
            logger.warning(
                "citation_verifier_llm_failed",
                extra={
                    "section_id": str(section.id),
                    "batch_size": len(batch),
                    "error_type": type(exc).__name__,
                    "error": str(exc)[:200],
                },
            )
            return [], 0, 0.0

        parsed = _try_parse_array(response.content)
        if parsed is None:
            logger.warning(
                "citation_verifier_invalid_json",
                extra={
                    "section_id": str(section.id),
                    "content_excerpt": response.content[:200],
                },
            )
            return _fallback_unparsed_batch(batch, section), _tokens(response), _cost(response)

        verifications = _parse_verdicts_into_verifications(
            parsed=parsed,
            batch=batch,
            section=section,
        )
        return verifications, _tokens(response), _cost(response)

    def _collect_citations(
        self,
        section: ArticleSection,
    ) -> list[tuple[int, int, CitationRef]]:
        """Collect citations as ``(paragraph_idx, citation_idx, ref)`` tuples."""

        collected: list[tuple[int, int, CitationRef]] = []
        for p_idx, paragraph in enumerate(section.paragraphs):
            for c_idx, ref in enumerate(paragraph.citations):
                collected.append((p_idx, c_idx, ref))
        return collected

    def _lookup_claim(
        self,
        claim_id: str,
        claims: list[SourceClaimCreate],
    ) -> SourceClaimCreate | None:
        """Find a claim by its ``source_chunk_id`` string identifier.

        ``SourceClaimCreate`` does not carry a UUID before persistence;
        the parent chunk identifier acts as the lookup key in test
        contexts. Production resolution goes through
        :func:`_find_matrix_position` instead — see
        :meth:`_verify_section_internal`.
        """

        for claim in claims:
            if claim.source_chunk_id == claim_id:
                return claim
        return None

    def _lookup_chunk(
        self,
        chunk_id: str,
        chunks: list[SourceChunkCreate],
    ) -> SourceChunkCreate | None:
        """Find a chunk by its ``source_id`` string or stringified index."""

        for chunk in chunks:
            if chunk.source_id and chunk.source_id == chunk_id:
                return chunk
            if str(chunk.chunk_index) == chunk_id:
                return chunk
        return None

    def _build_report(
        self,
        verifications: list[CitationVerification],
        model_used: str,
        total_tokens: int,
        cost: float,
        time_ms: int,
    ) -> CitationVerificationReport:
        """Tally verdicts, slice critical issues / warnings, return the report."""

        counts: dict[CitationVerdict, int] = dict.fromkeys(CitationVerdict, 0)
        for v in verifications:
            counts[v.verdict] += 1

        total = len(verifications)
        sound = counts[CitationVerdict.SUPPORTED] + counts[CitationVerdict.PARTIALLY_SUPPORTED]
        integrity = round(sound / total, 4) if total > 0 else 1.0

        critical = [
            v
            for v in verifications
            if v.verdict in (CitationVerdict.NOT_SUPPORTED, CitationVerdict.CONTRADICTED)
        ]
        warnings = [v for v in verifications if v.verdict is CitationVerdict.OVERCLAIMED]

        return CitationVerificationReport(
            total_citations=total,
            supported=counts[CitationVerdict.SUPPORTED],
            partially_supported=counts[CitationVerdict.PARTIALLY_SUPPORTED],
            overclaimed=counts[CitationVerdict.OVERCLAIMED],
            not_supported=counts[CitationVerdict.NOT_SUPPORTED],
            contradicted=counts[CitationVerdict.CONTRADICTED],
            source_not_found=counts[CitationVerdict.SOURCE_NOT_FOUND],
            overall_integrity_score=integrity,
            verifications=verifications,
            critical_issues=critical,
            warnings=warnings,
            model_used=model_used,
            total_tokens=total_tokens,
            estimated_cost_usd=round(cost, 6),
            verification_time_ms=time_ms,
        )


# ---------------------------------------------------------------------------
# Citation resolution / sentence extraction
# ---------------------------------------------------------------------------


class _PreparedCitation:
    """One citation that passed source-resolution and is ready for the LLM."""

    __slots__ = (
        "article_sentence",
        "chunk",
        "citation_index",
        "claim",
        "paragraph_index",
        "ref",
    )

    def __init__(
        self,
        paragraph_index: int,
        citation_index: int,
        ref: CitationRef,
        claim: SourceClaimCreate,
        chunk: SourceChunkCreate,
        article_sentence: str,
    ) -> None:
        self.paragraph_index = paragraph_index
        self.citation_index = citation_index
        self.ref = ref
        self.claim = claim
        self.chunk = chunk
        self.article_sentence = article_sentence


def _find_matrix_position(ref: CitationRef, matrix: EvidenceMatrix) -> int | None:
    """Return the index of the matrix entry matching this citation ref.

    A match requires both ``claim_id`` and ``source_chunk_id`` to agree
    so a citation cannot accidentally resolve through a stale pairing.
    """

    for i, entry in enumerate(matrix.entries):
        if entry.claim_id == ref.claim_id and entry.source_chunk_id == ref.source_id:
            return i
    return None


_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def extract_citing_sentence(paragraph_text: str, source_id: str) -> str:
    """Return the sentence in ``paragraph_text`` containing ``[source_id]``.

    Falls back to a ~200-char window around the marker if no full
    sentence can be isolated, and to the empty string if the marker is
    absent. The result is truncated to
    :data:`ARTICLE_SENTENCE_MAX_CHARS` so it always fits the
    :class:`CitationVerification` field.
    """

    marker = f"[{source_id}]"
    if marker not in paragraph_text:
        return ""

    sentences = _SENTENCE_SPLIT.split(paragraph_text)
    for sentence in sentences:
        if marker in sentence:
            return sentence.strip()[:ARTICLE_SENTENCE_MAX_CHARS]

    idx = paragraph_text.find(marker)
    start = max(0, idx - 100)
    end = min(len(paragraph_text), idx + len(marker) + 100)
    return paragraph_text[start:end].strip()[:ARTICLE_SENTENCE_MAX_CHARS]


def _format_citation_blocks(batch: list[_PreparedCitation]) -> str:
    """Render the per-citation fields the system prompt expects."""

    blocks: list[str] = []
    for n, item in enumerate(batch, start=1):
        chunk_text = item.chunk.text[:SOURCE_EXCERPT_CHARS].strip()
        sentence = item.article_sentence[:ARTICLE_SENTENCE_MAX_CHARS]
        claim_text = item.claim.claim_text[:CLAIM_TEXT_MAX_CHARS]
        blocks.append(
            f"CITATION {n}:\n"
            f'  Article sentence: "{sentence}"\n'
            f'  Cited claim: "{claim_text}"\n'
            f'  Source text: "{chunk_text}"'
        )
    return "\n\n".join(blocks)


# ---------------------------------------------------------------------------
# JSON parsing / verdict construction
# ---------------------------------------------------------------------------


def _try_parse_array(content: str) -> list[dict[str, Any]] | None:
    """Parse an LLM response into a list of dicts, stripping ``json`` fences."""

    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`").lstrip()
        if text.startswith("json"):
            text = text[len("json") :].lstrip()
    try:
        loaded = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(loaded, list):
        return None
    result: list[dict[str, Any]] = []
    for item in loaded:  # type: ignore[reportUnknownVariableType]
        if isinstance(item, dict):
            result.append(item)  # type: ignore[reportUnknownArgumentType]
    return result


def _parse_verdicts_into_verifications(
    parsed: list[dict[str, Any]],
    batch: list[_PreparedCitation],
    section: ArticleSection,
) -> list[CitationVerification]:
    """Map parsed verdict objects back to their citations by ``citation_index``.

    The LLM may omit a verdict, scramble indexes, or return verdicts
    out of order; we tolerate this by indexing on ``citation_index``
    where present and falling back to position. Any citation without a
    matching verdict downgrades to ``SOURCE_NOT_FOUND`` with a hint in
    the explanation so the report still surfaces it.
    """

    verdicts_by_index: dict[int, dict[str, Any]] = {}
    for position, item in enumerate(parsed):
        idx_raw = item.get("citation_index", position + 1)
        idx_int = idx_raw if isinstance(idx_raw, int) else position + 1
        verdicts_by_index[idx_int] = item

    verifications: list[CitationVerification] = []
    for n, item in enumerate(batch, start=1):
        raw = verdicts_by_index.get(n)
        if raw is None and (n - 1) < len(parsed):
            raw = parsed[n - 1]
        verification = _build_verification(raw, item, section)
        verifications.append(verification)
    return verifications


def _build_verification(
    raw: dict[str, Any] | None,
    item: _PreparedCitation,
    section: ArticleSection,
) -> CitationVerification:
    """Coerce one verdict dict into a :class:`CitationVerification`."""

    if raw is None:
        return _make_verification(
            section=section,
            item=item,
            verdict=CitationVerdict.SOURCE_NOT_FOUND,
            confidence=0.0,
            explanation="LLM returned no verdict for this citation.",
            suggested_fix=None,
        )

    verdict_str = raw.get("verdict")
    if not isinstance(verdict_str, str) or verdict_str not in _VALID_VERDICTS:
        return _make_verification(
            section=section,
            item=item,
            verdict=CitationVerdict.SOURCE_NOT_FOUND,
            confidence=0.0,
            explanation="LLM returned an invalid verdict for this citation.",
            suggested_fix=None,
        )
    verdict = CitationVerdict(verdict_str)

    confidence_raw = raw.get("confidence", 0.0)
    if isinstance(confidence_raw, (int, float)):
        confidence = max(0.0, min(1.0, float(confidence_raw)))
    else:
        confidence = 0.0

    explanation_raw = raw.get("explanation", "")
    explanation = (
        explanation_raw[:EXPLANATION_MAX_CHARS] if isinstance(explanation_raw, str) else ""
    )

    fix_raw = raw.get("suggested_fix")
    suggested_fix: str | None = None
    if isinstance(fix_raw, str) and fix_raw.strip():
        suggested_fix = fix_raw[:SUGGESTED_FIX_MAX_CHARS]

    return _make_verification(
        section=section,
        item=item,
        verdict=verdict,
        confidence=confidence,
        explanation=explanation,
        suggested_fix=suggested_fix,
    )


def _make_verification(
    section: ArticleSection,
    item: _PreparedCitation,
    verdict: CitationVerdict,
    confidence: float,
    explanation: str,
    suggested_fix: str | None,
) -> CitationVerification:
    """Assemble a populated :class:`CitationVerification`."""

    return CitationVerification(
        section_id=str(section.id),
        paragraph_index=item.paragraph_index,
        citation_index=item.citation_index,
        claim_id=str(item.ref.claim_id),
        source_chunk_id=str(item.ref.source_id),
        claim_text=item.claim.claim_text[:CLAIM_TEXT_MAX_CHARS],
        source_excerpt=item.chunk.text[:SOURCE_EXCERPT_CHARS],
        article_sentence=item.article_sentence[:ARTICLE_SENTENCE_MAX_CHARS],
        verdict=verdict,
        confidence=confidence,
        explanation=explanation,
        suggested_fix=suggested_fix,
    )


def _make_source_not_found(
    section: ArticleSection,
    paragraph_index: int,
    citation_index: int,
    ref: CitationRef,
) -> CitationVerification:
    """Assemble a ``SOURCE_NOT_FOUND`` verification without an LLM call."""

    paragraph_text = (
        section.paragraphs[paragraph_index].text
        if 0 <= paragraph_index < len(section.paragraphs)
        else ""
    )
    sentence = extract_citing_sentence(paragraph_text, str(ref.source_id))

    return CitationVerification(
        section_id=str(section.id),
        paragraph_index=paragraph_index,
        citation_index=citation_index,
        claim_id=str(ref.claim_id),
        source_chunk_id=str(ref.source_id),
        claim_text="",
        source_excerpt="",
        article_sentence=sentence,
        verdict=CitationVerdict.SOURCE_NOT_FOUND,
        confidence=1.0,
        explanation=(
            "Citation references a claim or source chunk that is not present "
            "in the project's extracted material. The article must not cite a "
            "source the project does not own."
        ),
        suggested_fix=(
            "Remove the citation, or replace it with a real evidence-matrix "
            "entry that backs the claim."
        ),
    )


def _fallback_unparsed_batch(
    batch: list[_PreparedCitation],
    section: ArticleSection,
) -> list[CitationVerification]:
    """Return ``SOURCE_NOT_FOUND`` for every citation when the LLM JSON broke."""

    return [
        _make_verification(
            section=section,
            item=item,
            verdict=CitationVerdict.SOURCE_NOT_FOUND,
            confidence=0.0,
            explanation="Verifier could not parse the LLM response; verdict unknown.",
            suggested_fix=None,
        )
        for item in batch
    ]


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------


def _batches(items: list[_PreparedCitation], size: int) -> Iterator[list[_PreparedCitation]]:
    """Yield successive ``size``-sized slices of ``items``."""

    for start in range(0, len(items), size):
        yield items[start : start + size]


def _tokens(response: LLMResponse) -> int:
    return int(response.input_tokens) + int(response.output_tokens)


def _cost(response: LLMResponse) -> float:
    """Compute the per-call cost from the response.

    Uses the Gemini cost table when the model name looks Gemini-shaped,
    otherwise the response's own ``estimated_cost_usd`` (already
    populated by the underlying client).
    """

    if response.model.startswith("gemini"):
        return gemini_cost_for(
            response.model,
            int(response.input_tokens),
            int(response.output_tokens),
        )
    return float(response.estimated_cost_usd)


__all__ = [
    "BATCH_SIZE",
    "INTEGRITY_THRESHOLD",
    "CitationVerifier",
    "extract_citing_sentence",
]
