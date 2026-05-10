"""Behaviour tests for :class:`CitationVerifier`.

The verifier makes batched LLM calls (max 10 citations per call) so we
mock the :class:`ModelRouter` and assert on either the resolved
citations, the parsed verdicts, or the aggregate report. Per
``.claude/rules/testing.md`` we mock only the LLM transport; everything
else (citation collection, source resolution, sentence extraction,
report assembly) runs against the real implementation.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

from packages.core.enums import (
    ArticleSectionStatus,
    CitationStatus,
    CitationVerdict,
    ClaimStrength,
    ClaimType,
)
from packages.core.llm import LLMResponse
from packages.core.models import (
    ArticleSection,
    CitationRef,
    CitationVerification,
    CitationVerificationReport,
    EvidenceMatrix,
    EvidenceMatrixEntry,
    Paragraph,
    SourceChunkCreate,
    SourceClaimCreate,
)
from packages.workers.article.citation_verifier import (
    BATCH_SIZE,
    INTEGRITY_THRESHOLD,
    CitationVerifier,
    extract_citing_sentence,
)

# ---------------------------------------------------------------------------
# Stubs / fixtures
# ---------------------------------------------------------------------------


class _StubRouter:
    """Stand-in for :class:`ModelRouter` returning scripted JSON responses."""

    def __init__(
        self,
        responses: list[str] | None = None,
        raise_on_call: Exception | None = None,
    ) -> None:
        self.responses = list(responses or [])
        self.raise_on_call = raise_on_call
        self.calls: list[tuple[str, str, str]] = []

    async def complete(
        self,
        system: str,
        user: str,
        model: str = "gemini-3-flash",
        max_tokens: int = 2000,
        temperature: float = 0.0,
    ) -> LLMResponse:
        del max_tokens, temperature
        self.calls.append((system, user, model))
        if self.raise_on_call is not None:
            raise self.raise_on_call
        if not self.responses:
            raise RuntimeError("router stub ran out of scripted responses")
        content = self.responses.pop(0)
        # Approximate token counts so cost computation is non-zero.
        return LLMResponse(
            content=content,
            model=model,
            input_tokens=400,
            output_tokens=120,
            latency_ms=20,
            estimated_cost_usd=0.0008,
        )


def _make_claim(
    text: str,
    *,
    chunk_id: str = "0",
    strength: ClaimStrength = ClaimStrength.MODERATE,
    claim_type: ClaimType = ClaimType.GENERAL_FACT,
) -> SourceClaimCreate:
    return SourceClaimCreate(
        source_chunk_id=chunk_id,
        claim_text=text,
        strength=strength,
        claim_type=claim_type,
    )


def _make_chunk(text: str, *, index: int = 0, source_id: str = "") -> SourceChunkCreate:
    return SourceChunkCreate(
        source_id=source_id or str(index),
        chunk_index=index,
        text=text,
    )


def _make_entry(
    project_id: UUID,
    *,
    claim_uuid: UUID,
    chunk_uuid: UUID,
    section_id: UUID | None = None,
) -> EvidenceMatrixEntry:
    return EvidenceMatrixEntry(
        project_id=project_id,
        claim_id=claim_uuid,
        source_chunk_id=chunk_uuid,
        article_section_id=section_id,
        citation_status=CitationStatus.READY,
        created_at=datetime.now(UTC),
    )


def _make_paragraph(text: str, citations: list[CitationRef] | None = None) -> Paragraph:
    return Paragraph(text=text, citations=citations or [])


def _make_section(
    *,
    article_id: UUID | None = None,
    paragraphs: list[Paragraph] | None = None,
    title: str = "Section",
    section_index: int = 0,
) -> ArticleSection:
    return ArticleSection(
        article_id=article_id or uuid4(),
        section_index=section_index,
        title=title,
        paragraphs=paragraphs or [],
        word_count=sum(len(p.text.split()) for p in (paragraphs or [])),
        status=ArticleSectionStatus.DRAFT,
        created_at=datetime.now(UTC),
    )


def _setup_resolved_citation(
    *,
    claim_text: str = "Energy efficient cooling reduces demand by 47% [src].",
    chunk_text: str = "Field measurements demonstrate 47% cooling reduction across the trial cohort.",
    paragraph_text: str | None = None,
) -> tuple[
    ArticleSection,
    list[SourceClaimCreate],
    list[SourceChunkCreate],
    EvidenceMatrix,
    UUID,
    UUID,
]:
    """Build a one-citation section whose citation resolves through the matrix."""

    project_id = uuid4()
    claim_uuid = uuid4()
    chunk_uuid = uuid4()
    chunk = _make_chunk(chunk_text, index=0, source_id="src_0")
    claim = _make_claim(claim_text, chunk_id="src_0")
    matrix = EvidenceMatrix(
        project_id=project_id,
        entries=[_make_entry(project_id, claim_uuid=claim_uuid, chunk_uuid=chunk_uuid)],
    )
    if paragraph_text is None:
        paragraph_text = (
            f"The pilot data demonstrates a 47% reduction in cooling demand [{chunk_uuid}]."
        )
    paragraph = _make_paragraph(
        paragraph_text,
        [CitationRef(source_id=chunk_uuid, claim_id=claim_uuid)],
    )
    section = _make_section(paragraphs=[paragraph])
    return section, [claim], [chunk], matrix, claim_uuid, chunk_uuid


def _verdict_response(verdicts: list[dict[str, Any]]) -> str:
    return json.dumps(verdicts)


# ---------------------------------------------------------------------------
# Citation collection
# ---------------------------------------------------------------------------


class TestCollectCitations:
    def test_collect_citations_from_section(self) -> None:
        verifier = CitationVerifier(router=_StubRouter())  # type: ignore[arg-type]
        refs = [
            CitationRef(source_id=uuid4(), claim_id=uuid4()),
            CitationRef(source_id=uuid4(), claim_id=uuid4()),
        ]
        paragraphs = [
            _make_paragraph(f"Para 1 [{refs[0].source_id}] [{refs[1].source_id}].", refs),
            _make_paragraph(f"Para 2 [{refs[0].source_id}] [{refs[1].source_id}].", list(refs)),
            _make_paragraph(f"Para 3 [{refs[0].source_id}] [{refs[1].source_id}].", list(refs)),
        ]
        section = _make_section(paragraphs=paragraphs)

        collected = verifier._collect_citations(section)  # type: ignore[reportPrivateUsage]
        assert len(collected) == 6
        assert {(p, c) for p, c, _ in collected} == {(0, 0), (0, 1), (1, 0), (1, 1), (2, 0), (2, 1)}

    def test_collect_citations_empty_section(self) -> None:
        verifier = CitationVerifier(router=_StubRouter())  # type: ignore[arg-type]
        section = _make_section(
            paragraphs=[
                _make_paragraph("Just narrative text without citations."),
                _make_paragraph("Another bare paragraph."),
            ]
        )
        assert verifier._collect_citations(section) == []  # type: ignore[reportPrivateUsage]

    def test_collect_citations_mixed_paragraphs(self) -> None:
        verifier = CitationVerifier(router=_StubRouter())  # type: ignore[arg-type]
        refs = [CitationRef(source_id=uuid4(), claim_id=uuid4())]
        paragraphs = [
            _make_paragraph(f"Cited paragraph [{refs[0].source_id}].", list(refs)),
            _make_paragraph("Bare narrative paragraph."),
            _make_paragraph(f"Another citation [{refs[0].source_id}].", list(refs)),
        ]
        section = _make_section(paragraphs=paragraphs)

        collected = verifier._collect_citations(section)  # type: ignore[reportPrivateUsage]
        para_indexes = sorted(p_idx for p_idx, _, _ in collected)
        assert para_indexes == [0, 2]


# ---------------------------------------------------------------------------
# Source / chunk lookup
# ---------------------------------------------------------------------------


class TestLookups:
    def test_lookup_claim_found(self) -> None:
        verifier = CitationVerifier(router=_StubRouter())  # type: ignore[arg-type]
        claims = [
            _make_claim("Claim A about cooling systems and field results", chunk_id="alpha"),
            _make_claim("Claim B about a separate measured outcome", chunk_id="beta"),
        ]
        result = verifier._lookup_claim("beta", claims)  # type: ignore[reportPrivateUsage]
        assert result is claims[1]

    def test_lookup_claim_not_found(self) -> None:
        verifier = CitationVerifier(router=_StubRouter())  # type: ignore[arg-type]
        claims = [_make_claim("Some claim about renewable cooling", chunk_id="alpha")]
        assert verifier._lookup_claim("does-not-exist", claims) is None  # type: ignore[reportPrivateUsage]

    def test_lookup_chunk_found(self) -> None:
        verifier = CitationVerifier(router=_StubRouter())  # type: ignore[arg-type]
        chunks = [
            _make_chunk("text 0", index=0, source_id="src_a"),
            _make_chunk("text 1", index=1, source_id="src_b"),
        ]
        assert verifier._lookup_chunk("src_b", chunks) is chunks[1]  # type: ignore[reportPrivateUsage]
        assert verifier._lookup_chunk("0", chunks) is chunks[0]  # type: ignore[reportPrivateUsage]

    def test_lookup_chunk_not_found(self) -> None:
        verifier = CitationVerifier(router=_StubRouter())  # type: ignore[arg-type]
        chunks = [_make_chunk("text", index=0, source_id="src_a")]
        assert verifier._lookup_chunk("src_z", chunks) is None  # type: ignore[reportPrivateUsage]


# ---------------------------------------------------------------------------
# Sentence extraction
# ---------------------------------------------------------------------------


class TestExtractCitingSentence:
    def test_finds_citation_marker(self) -> None:
        text = "This is proven by research [chunk_1]. Further work shows extra results."
        result = extract_citing_sentence(text, "chunk_1")
        assert "[chunk_1]" in result
        assert "Further work" not in result

    def test_no_match_returns_empty(self) -> None:
        text = "This paragraph has no citation markers anywhere."
        assert extract_citing_sentence(text, "missing_id") == ""

    def test_returns_marker_text_when_paragraph_has_no_periods(self) -> None:
        text = "no period here just a [marker_x] embedded in a long fragment of text"
        result = extract_citing_sentence(text, "marker_x")
        assert "[marker_x]" in result
        assert result.startswith("no period here")


# ---------------------------------------------------------------------------
# Batched verification (LLM mocked)
# ---------------------------------------------------------------------------


class TestVerifySection:
    @pytest.mark.asyncio
    async def test_parses_valid_verdicts(self) -> None:
        section, claims, chunks, matrix, _, _ = _setup_resolved_citation()
        # Add two more citations resolved via additional matrix entries
        extra_claim_uuids = [uuid4(), uuid4()]
        extra_chunk_uuids = [uuid4(), uuid4()]
        for n, (cu, ch) in enumerate(
            zip(extra_claim_uuids, extra_chunk_uuids, strict=True), start=1
        ):
            chunks.append(_make_chunk(f"chunk {n} text body", index=n, source_id=f"src_{n}"))
            claims.append(
                _make_claim(f"extra claim {n} about cooling research", chunk_id=f"src_{n}")
            )
            matrix.entries.append(_make_entry(matrix.project_id, claim_uuid=cu, chunk_uuid=ch))

        # Add citations to the section paragraph
        section.paragraphs[0] = _make_paragraph(
            f"Sentence one [{section.paragraphs[0].citations[0].source_id}]. "
            f"Sentence two [{extra_chunk_uuids[0]}]. "
            f"Sentence three [{extra_chunk_uuids[1]}].",
            [
                section.paragraphs[0].citations[0],
                CitationRef(source_id=extra_chunk_uuids[0], claim_id=extra_claim_uuids[0]),
                CitationRef(source_id=extra_chunk_uuids[1], claim_id=extra_claim_uuids[1]),
            ],
        )

        router = _StubRouter(
            responses=[
                _verdict_response(
                    [
                        {
                            "citation_index": 1,
                            "verdict": "supported",
                            "confidence": 0.95,
                            "explanation": "Source clearly backs the claim.",
                            "suggested_fix": None,
                        },
                        {
                            "citation_index": 2,
                            "verdict": "overclaimed",
                            "confidence": 0.8,
                            "explanation": "Article is more confident than source.",
                            "suggested_fix": "Soften to 'may suggest'.",
                        },
                        {
                            "citation_index": 3,
                            "verdict": "not_supported",
                            "confidence": 0.9,
                            "explanation": "Source does not address this point.",
                            "suggested_fix": "Remove citation.",
                        },
                    ]
                )
            ]
        )
        verifier = CitationVerifier(router=router)  # type: ignore[arg-type]

        verifications = await verifier.verify_section(section, claims, chunks, matrix)
        assert len(verifications) == 3
        assert verifications[0].verdict is CitationVerdict.SUPPORTED
        assert verifications[1].verdict is CitationVerdict.OVERCLAIMED
        assert verifications[2].verdict is CitationVerdict.NOT_SUPPORTED
        assert (
            verifications[1].suggested_fix is not None
            and "soften" in verifications[1].suggested_fix.lower()
        )

    @pytest.mark.asyncio
    async def test_handles_invalid_json(self) -> None:
        section, claims, chunks, matrix, _, _ = _setup_resolved_citation()
        router = _StubRouter(responses=["this is not valid JSON at all"])
        verifier = CitationVerifier(router=router)  # type: ignore[arg-type]

        verifications = await verifier.verify_section(section, claims, chunks, matrix)
        # graceful degradation: each citation gets a SOURCE_NOT_FOUND
        assert len(verifications) == 1
        assert verifications[0].verdict is CitationVerdict.SOURCE_NOT_FOUND

    @pytest.mark.asyncio
    async def test_handles_router_failure(self) -> None:
        section, claims, chunks, matrix, _, _ = _setup_resolved_citation()
        router = _StubRouter(raise_on_call=RuntimeError("network down"))
        verifier = CitationVerifier(router=router)  # type: ignore[arg-type]

        verifications = await verifier.verify_section(section, claims, chunks, matrix)
        assert verifications == []

    @pytest.mark.asyncio
    async def test_source_not_found_for_missing_claim(self) -> None:
        # Citation references a claim_id with no matching matrix entry
        project_id = uuid4()
        chunk_uuid = uuid4()
        chunk = _make_chunk("real source body", index=0, source_id="src_0")
        claim = _make_claim("real claim about cooling research", chunk_id="src_0")
        matrix = EvidenceMatrix(project_id=project_id, entries=[])

        bogus_claim_id = uuid4()
        ref = CitationRef(source_id=chunk_uuid, claim_id=bogus_claim_id)
        section = _make_section(paragraphs=[_make_paragraph(f"Cited [{chunk_uuid}].", [ref])])
        router = _StubRouter()
        verifier = CitationVerifier(router=router)  # type: ignore[arg-type]

        verifications = await verifier.verify_section(section, [claim], [chunk], matrix)
        assert len(verifications) == 1
        assert verifications[0].verdict is CitationVerdict.SOURCE_NOT_FOUND
        assert len(router.calls) == 0  # no LLM call was made

    @pytest.mark.asyncio
    async def test_source_not_found_for_missing_chunk(self) -> None:
        # Matrix entry exists but its position has no matching SourceChunkCreate
        project_id = uuid4()
        claim_uuid = uuid4()
        chunk_uuid = uuid4()
        # claim references chunk "missing" which is not in chunks list
        claim = _make_claim("claim citing nonexistent chunk", chunk_id="missing")
        matrix = EvidenceMatrix(
            project_id=project_id,
            entries=[_make_entry(project_id, claim_uuid=claim_uuid, chunk_uuid=chunk_uuid)],
        )
        ref = CitationRef(source_id=chunk_uuid, claim_id=claim_uuid)
        section = _make_section(paragraphs=[_make_paragraph(f"Cited [{chunk_uuid}].", [ref])])
        router = _StubRouter()
        verifier = CitationVerifier(router=router)  # type: ignore[arg-type]

        verifications = await verifier.verify_section(section, [claim], [], matrix)
        assert len(verifications) == 1
        assert verifications[0].verdict is CitationVerdict.SOURCE_NOT_FOUND
        assert len(router.calls) == 0

    @pytest.mark.asyncio
    async def test_batches_large_sections(self) -> None:
        project_id = uuid4()
        claim_uuids = [uuid4() for _ in range(15)]
        chunk_uuids = [uuid4() for _ in range(15)]
        chunks = [
            _make_chunk(f"chunk {i} body text", index=i, source_id=f"src_{i}") for i in range(15)
        ]
        claims = [
            _make_claim(f"claim {i} about cooling research detail", chunk_id=f"src_{i}")
            for i in range(15)
        ]
        entries = [
            _make_entry(project_id, claim_uuid=claim_uuids[i], chunk_uuid=chunk_uuids[i])
            for i in range(15)
        ]
        matrix = EvidenceMatrix(project_id=project_id, entries=entries)

        refs = [CitationRef(source_id=chunk_uuids[i], claim_id=claim_uuids[i]) for i in range(15)]
        marker_text = " ".join(f"sentence {i} [{chunk_uuids[i]}]." for i in range(15))
        paragraph = _make_paragraph(marker_text, refs)
        section = _make_section(paragraphs=[paragraph])

        # Stub returns one verdict per citation, in two LLM calls (10 + 5)
        verdicts_batch_1 = [
            {
                "citation_index": i + 1,
                "verdict": "supported",
                "confidence": 0.9,
                "explanation": "ok",
                "suggested_fix": None,
            }
            for i in range(10)
        ]
        verdicts_batch_2 = [
            {
                "citation_index": i + 1,
                "verdict": "supported",
                "confidence": 0.9,
                "explanation": "ok",
                "suggested_fix": None,
            }
            for i in range(5)
        ]
        router = _StubRouter(
            responses=[
                _verdict_response(verdicts_batch_1),
                _verdict_response(verdicts_batch_2),
            ]
        )
        verifier = CitationVerifier(router=router)  # type: ignore[arg-type]

        verifications = await verifier.verify_section(section, claims, chunks, matrix)
        assert len(verifications) == 15
        assert len(router.calls) == 2  # batched 10 + 5
        assert all(v.verdict is CitationVerdict.SUPPORTED for v in verifications)


# ---------------------------------------------------------------------------
# Full-article verification
# ---------------------------------------------------------------------------


class TestVerifyArticle:
    @pytest.mark.asyncio
    async def test_aggregates_sections(self) -> None:
        # 3 sections, 1 citation each
        sections: list[ArticleSection] = []
        claims: list[SourceClaimCreate] = []
        chunks: list[SourceChunkCreate] = []
        entries: list[EvidenceMatrixEntry] = []
        project_id = uuid4()

        for i in range(3):
            claim_uuid = uuid4()
            chunk_uuid = uuid4()
            chunks.append(_make_chunk(f"chunk {i} body", index=i, source_id=f"src_{i}"))
            claims.append(_make_claim(f"claim {i} about cooling research", chunk_id=f"src_{i}"))
            entries.append(_make_entry(project_id, claim_uuid=claim_uuid, chunk_uuid=chunk_uuid))
            ref = CitationRef(source_id=chunk_uuid, claim_id=claim_uuid)
            paragraph = _make_paragraph(f"Sentence {i} [{chunk_uuid}].", [ref])
            sections.append(_make_section(paragraphs=[paragraph], section_index=i))

        matrix = EvidenceMatrix(project_id=project_id, entries=entries)
        responses = [
            _verdict_response(
                [
                    {
                        "citation_index": 1,
                        "verdict": "supported",
                        "confidence": 0.9,
                        "explanation": "fine",
                        "suggested_fix": None,
                    }
                ]
            )
        ] * 3
        router = _StubRouter(responses=responses)
        verifier = CitationVerifier(router=router)  # type: ignore[arg-type]

        report = await verifier.verify_article(sections, claims, chunks, matrix)
        assert report.total_citations == 3
        assert report.supported == 3
        assert len(router.calls) == 3

    @pytest.mark.asyncio
    async def test_computes_integrity_score(self) -> None:
        sections, claims, chunks, matrix = _build_n_citations_in_one_section(
            verdict_distribution=(7, 2, 1, 0, 0)
        )
        # 7 supported, 2 partially_supported, 1 overclaimed → 9/10 = 0.9
        verdicts = (
            [
                {
                    "citation_index": i + 1,
                    "verdict": "supported",
                    "confidence": 0.95,
                    "explanation": "ok",
                    "suggested_fix": None,
                }
                for i in range(7)
            ]
            + [
                {
                    "citation_index": 7 + i + 1,
                    "verdict": "partially_supported",
                    "confidence": 0.75,
                    "explanation": "partial",
                    "suggested_fix": None,
                }
                for i in range(2)
            ]
            + [
                {
                    "citation_index": 10,
                    "verdict": "overclaimed",
                    "confidence": 0.8,
                    "explanation": "overclaimed",
                    "suggested_fix": "soften",
                }
            ]
        )
        router = _StubRouter(responses=[_verdict_response(verdicts)])
        verifier = CitationVerifier(router=router)  # type: ignore[arg-type]

        report = await verifier.verify_article(sections, claims, chunks, matrix)
        assert report.total_citations == 10
        assert report.supported == 7
        assert report.partially_supported == 2
        assert report.overclaimed == 1
        assert report.overall_integrity_score == pytest.approx(0.9)

    @pytest.mark.asyncio
    async def test_identifies_critical_issues(self) -> None:
        sections, claims, chunks, matrix = _build_n_citations_in_one_section(
            verdict_distribution=(0, 0, 0, 1, 1)
        )
        verdicts = [
            {
                "citation_index": 1,
                "verdict": "not_supported",
                "confidence": 0.95,
                "explanation": "missing",
                "suggested_fix": "remove",
            },
            {
                "citation_index": 2,
                "verdict": "contradicted",
                "confidence": 0.95,
                "explanation": "opposite",
                "suggested_fix": "rewrite",
            },
        ]
        router = _StubRouter(responses=[_verdict_response(verdicts)])
        verifier = CitationVerifier(router=router)  # type: ignore[arg-type]

        report = await verifier.verify_article(sections, claims, chunks, matrix)
        assert len(report.critical_issues) == 2
        assert {v.verdict for v in report.critical_issues} == {
            CitationVerdict.NOT_SUPPORTED,
            CitationVerdict.CONTRADICTED,
        }

    @pytest.mark.asyncio
    async def test_identifies_warnings(self) -> None:
        sections, claims, chunks, matrix = _build_n_citations_in_one_section(
            verdict_distribution=(0, 0, 2, 0, 0)
        )
        verdicts = [
            {
                "citation_index": i + 1,
                "verdict": "overclaimed",
                "confidence": 0.85,
                "explanation": "overclaim",
                "suggested_fix": "soften",
            }
            for i in range(2)
        ]
        router = _StubRouter(responses=[_verdict_response(verdicts)])
        verifier = CitationVerifier(router=router)  # type: ignore[arg-type]

        report = await verifier.verify_article(sections, claims, chunks, matrix)
        assert len(report.warnings) == 2
        assert all(v.verdict is CitationVerdict.OVERCLAIMED for v in report.warnings)

    @pytest.mark.asyncio
    async def test_clean_report(self) -> None:
        sections, claims, chunks, matrix = _build_n_citations_in_one_section(
            verdict_distribution=(3, 0, 0, 0, 0)
        )
        verdicts = [
            {
                "citation_index": i + 1,
                "verdict": "supported",
                "confidence": 0.99,
                "explanation": "perfect",
                "suggested_fix": None,
            }
            for i in range(3)
        ]
        router = _StubRouter(responses=[_verdict_response(verdicts)])
        verifier = CitationVerifier(router=router)  # type: ignore[arg-type]

        report = await verifier.verify_article(sections, claims, chunks, matrix)
        assert report.overall_integrity_score == pytest.approx(1.0)
        assert report.critical_issues == []
        assert report.warnings == []

    @pytest.mark.asyncio
    async def test_flags_low_integrity(self) -> None:
        sections, claims, chunks, matrix = _build_n_citations_in_one_section(
            verdict_distribution=(4, 0, 0, 6, 0)
        )
        verdicts = [
            {
                "citation_index": i + 1,
                "verdict": "supported",
                "confidence": 0.95,
                "explanation": "ok",
                "suggested_fix": None,
            }
            for i in range(4)
        ] + [
            {
                "citation_index": 4 + i + 1,
                "verdict": "not_supported",
                "confidence": 0.9,
                "explanation": "missing",
                "suggested_fix": "remove",
            }
            for i in range(6)
        ]
        router = _StubRouter(responses=[_verdict_response(verdicts)])
        verifier = CitationVerifier(router=router)  # type: ignore[arg-type]

        report = await verifier.verify_article(sections, claims, chunks, matrix)
        assert report.overall_integrity_score == pytest.approx(0.4)
        assert report.overall_integrity_score < INTEGRITY_THRESHOLD

    @pytest.mark.asyncio
    async def test_tracks_cost(self) -> None:
        section, claims, chunks, matrix, _, _ = _setup_resolved_citation()
        verdicts = [
            {
                "citation_index": 1,
                "verdict": "supported",
                "confidence": 0.95,
                "explanation": "ok",
                "suggested_fix": None,
            }
        ]
        router = _StubRouter(responses=[_verdict_response(verdicts)])
        verifier = CitationVerifier(router=router)  # type: ignore[arg-type]

        report = await verifier.verify_article([section], claims, chunks, matrix)
        assert report.total_tokens > 0
        assert report.estimated_cost_usd > 0
        assert report.model_used.startswith("gemini")

    @pytest.mark.asyncio
    async def test_empty_article(self) -> None:
        verifier = CitationVerifier(router=_StubRouter())  # type: ignore[arg-type]
        report = await verifier.verify_article([], [], [], EvidenceMatrix(project_id=uuid4()))
        assert report.total_citations == 0
        assert report.overall_integrity_score == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Model round-trip / enum coverage
# ---------------------------------------------------------------------------


class TestModels:
    def test_citation_verification_round_trip(self) -> None:
        v = CitationVerification(
            section_id="sec_1",
            paragraph_index=2,
            citation_index=0,
            claim_id="claim_x",
            source_chunk_id="chunk_y",
            claim_text="The claim text",
            source_excerpt="The source excerpt",
            article_sentence="The article sentence",
            verdict=CitationVerdict.OVERCLAIMED,
            confidence=0.7,
            explanation="reason",
            suggested_fix="soften the verb",
        )
        clone = CitationVerification.model_validate(v.model_dump())
        assert clone == v

    def test_citation_verification_report_round_trip(self) -> None:
        v = CitationVerification(
            section_id="sec_1",
            paragraph_index=0,
            citation_index=0,
            claim_id="claim_x",
            source_chunk_id="chunk_y",
            verdict=CitationVerdict.NOT_SUPPORTED,
            confidence=0.9,
            explanation="missing",
        )
        report = CitationVerificationReport(
            total_citations=1,
            supported=0,
            partially_supported=0,
            overclaimed=0,
            not_supported=1,
            contradicted=0,
            source_not_found=0,
            overall_integrity_score=0.0,
            verifications=[v],
            critical_issues=[v],
            warnings=[],
            model_used="gemini-3-flash",
            total_tokens=100,
            estimated_cost_usd=0.001,
            verification_time_ms=50,
        )
        clone = CitationVerificationReport.model_validate(report.model_dump())
        assert clone == report

    def test_citation_verdict_enum_has_all_values(self) -> None:
        values = {v.value for v in CitationVerdict}
        assert values == {
            "supported",
            "partially_supported",
            "overclaimed",
            "not_supported",
            "contradicted",
            "source_not_found",
        }


# ---------------------------------------------------------------------------
# Integration with hedging-aligned scenarios
# ---------------------------------------------------------------------------


class TestHedgingAlignment:
    @pytest.mark.asyncio
    async def test_overclaimed_when_source_hedges_but_article_is_confident(self) -> None:
        section, claims, chunks, matrix, _, _ = _setup_resolved_citation(
            claim_text="results may suggest a correlation between A and B",
            chunk_text="results may suggest a correlation between A and B in pilot data",
            paragraph_text=(f"research demonstrates a clear correlation between A and B [{None}]."),
        )
        # rewrite paragraph to use real source_id marker
        chunk_uuid = section.paragraphs[0].citations[0].source_id
        section.paragraphs[0] = _make_paragraph(
            f"research demonstrates a clear correlation between A and B [{chunk_uuid}].",
            list(section.paragraphs[0].citations),
        )

        verdicts = [
            {
                "citation_index": 1,
                "verdict": "overclaimed",
                "confidence": 0.85,
                "explanation": "Source hedges; article asserts.",
                "suggested_fix": "Soften 'demonstrates' to 'may suggest'.",
            }
        ]
        router = _StubRouter(responses=[_verdict_response(verdicts)])
        verifier = CitationVerifier(router=router)  # type: ignore[arg-type]

        verifications = await verifier.verify_section(section, claims, chunks, matrix)
        assert len(verifications) == 1
        assert verifications[0].verdict is CitationVerdict.OVERCLAIMED
        assert verifications[0].suggested_fix is not None
        assert "may" in verifications[0].suggested_fix.lower()


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


def test_batch_size_is_ten() -> None:
    assert BATCH_SIZE == 10


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_n_citations_in_one_section(
    verdict_distribution: tuple[int, int, int, int, int],
) -> tuple[list[ArticleSection], list[SourceClaimCreate], list[SourceChunkCreate], EvidenceMatrix]:
    """Build one section with N citations resolved through the matrix.

    ``verdict_distribution`` is unused for routing (the test wires
    verdict outputs directly through the LLM stub); it merely controls
    how many citations to create.
    """

    n = sum(verdict_distribution)
    project_id = uuid4()
    claim_uuids = [uuid4() for _ in range(n)]
    chunk_uuids = [uuid4() for _ in range(n)]
    chunks = [_make_chunk(f"chunk {i} text body", index=i, source_id=f"src_{i}") for i in range(n)]
    claims = [
        _make_claim(f"claim {i} about cooling research detail", chunk_id=f"src_{i}")
        for i in range(n)
    ]
    entries = [
        _make_entry(project_id, claim_uuid=claim_uuids[i], chunk_uuid=chunk_uuids[i])
        for i in range(n)
    ]
    matrix = EvidenceMatrix(project_id=project_id, entries=entries)

    refs = [CitationRef(source_id=chunk_uuids[i], claim_id=claim_uuids[i]) for i in range(n)]
    marker_text = " ".join(f"sentence {i} [{chunk_uuids[i]}]." for i in range(n))
    paragraph = _make_paragraph(marker_text, refs)
    section = _make_section(paragraphs=[paragraph])
    return [section], claims, chunks, matrix
