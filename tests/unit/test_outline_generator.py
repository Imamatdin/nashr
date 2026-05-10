"""Behaviour tests for :class:`OutlineGenerator` and the structure templates.

These tests pin the contract that downstream drafting depends on: every
article structure template carries the international quality baseline
(quality checklists, ``min_citations``, trilingual titles), word-target
maths follows the page → words conversion (with the abstract clamp), and
the LLM-driven outline pipeline gracefully degrades through repair, then
fallback, when JSON or section coverage breaks.

LLM calls are mocked via :class:`_StubLLM`; per ``.claude/rules/testing.md``
we only mock external services (Anthropic), never local libraries.
"""

from __future__ import annotations

import json
from uuid import uuid4

import pytest
from pydantic import ValidationError

from packages.core.enums import (
    ArticleStructure,
    ClaimStrength,
    Language,
)
from packages.core.llm import LLMResponse
from packages.core.models import (
    ArticleOutline,
    OutlineSection,
    SourceChunkCreate,
    SourceClaimCreate,
    SourceMetadataExtracted,
)
from packages.workers.article.article_structures import (
    ABSTRACT_MAX_WORDS,
    ABSTRACT_MIN_WORDS,
    EMPIRICAL_VARIANT,
    HISOBOT_TEMPLATE,
    ILMIY_MAQOLA_EMPIRICAL_TEMPLATE,
    ILMIY_MAQOLA_THEORETICAL_TEMPLATE,
    KURS_ISHI_TEMPLATE,
    REFERAT_TEMPLATE,
    THEORETICAL_VARIANT,
    WORDS_PER_PAGE,
    SectionRequirement,
    all_templates,
    get_template,
)
from packages.workers.article.outline_generator import OutlineGenerator

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


class _StubLLM:
    """Stand-in for :class:`LLMClient` returning scripted responses in order."""

    def __init__(
        self,
        responses: list[str] | None = None,
        raise_on_call: Exception | None = None,
    ) -> None:
        self.responses = list(responses or [])
        self.raise_on_call = raise_on_call
        self.calls: list[tuple[str, str]] = []

    async def complete(
        self,
        system: str,
        user: str,
        model: str = "claude-haiku-4-5-20251001",
        max_tokens: int = 2000,
        temperature: float = 0.0,
    ) -> LLMResponse:
        self.calls.append((system, user))
        if self.raise_on_call is not None:
            raise self.raise_on_call
        if not self.responses:
            raise RuntimeError("LLM stub ran out of scripted responses")
        content = self.responses.pop(0)
        return LLMResponse(
            content=content,
            model=model,
            input_tokens=100,
            output_tokens=80,
            latency_ms=5,
            estimated_cost_usd=0.0001,
        )


def _claims(texts: list[str]) -> list[SourceClaimCreate]:
    """Build claims, padding any short stub text to satisfy claim_text min_length=10."""

    return [
        SourceClaimCreate(
            source_chunk_id=str(i),
            claim_text=text if len(text) >= 10 else f"claim about {text}".ljust(12),
            strength=ClaimStrength.MODERATE,
        )
        for i, text in enumerate(texts)
    ]


def _chunks(texts: list[str]) -> list[SourceChunkCreate]:
    return [
        SourceChunkCreate(
            chunk_index=i,
            text=text,
            source_id=str(i),
        )
        for i, text in enumerate(texts)
    ]


def _metadata(titles: list[str]) -> list[SourceMetadataExtracted]:
    return [
        SourceMetadataExtracted(
            title=title,
            authors=["A. Author"],
            year=2024,
        )
        for title in titles
    ]


def _good_referat_response(thesis: str = "Education reshaped Uzbek society.") -> str:
    return json.dumps(
        {
            "title": "Ag'artıwshılıq haqında ma'ruza",
            "thesis": thesis,
            "sections": [
                {
                    "section_id": "kirish",
                    "subsections": [
                        {
                            "title": "Kirish",
                            "section_thesis": "Bu mavzuning hozirgi dolzarbligi.",
                            "claim_indices": [0],
                            "needs_user_input": False,
                        }
                    ],
                },
                {
                    "section_id": "asosiy_qism",
                    "subsections": [
                        {
                            "title": "Tarixiy ko'rinish",
                            "section_thesis": "XVII-XVIII asrlardagi rivoj.",
                            "claim_indices": [1, 2],
                            "needs_user_input": False,
                        },
                        {
                            "title": "Ta'sirlar",
                            "section_thesis": "G'arbiy ta'sirning kuchayishi.",
                            "claim_indices": [3],
                            "needs_user_input": False,
                        },
                    ],
                },
                {
                    "section_id": "xulosa",
                    "subsections": [
                        {
                            "title": "Xulosa",
                            "section_thesis": "Maqolaning natijalari.",
                            "claim_indices": [],
                            "needs_user_input": False,
                        }
                    ],
                },
            ],
        }
    )


# ---------------------------------------------------------------------------
# Structure-template tests (8)
# ---------------------------------------------------------------------------


class TestStructureTemplates:
    def test_referat_has_required_sections(self) -> None:
        ids = [s.section_id for s in REFERAT_TEMPLATE.sections]
        assert ids == ["kirish", "asosiy_qism", "xulosa"]

    def test_kurs_ishi_has_required_sections(self) -> None:
        ids = [s.section_id for s in KURS_ISHI_TEMPLATE.sections]
        assert ids == ["kirish", "nazariy_asos", "amaliy_qism", "xulosa"]

    def test_ilmiy_maqola_empirical_has_methodology_and_results(self) -> None:
        ids = [s.section_id for s in ILMIY_MAQOLA_EMPIRICAL_TEMPLATE.sections]
        assert "methodology" in ids
        assert "results" in ids
        assert "theoretical_framework" not in ids
        method = next(
            s for s in ILMIY_MAQOLA_EMPIRICAL_TEMPLATE.sections if s.section_id == "methodology"
        )
        results = next(
            s for s in ILMIY_MAQOLA_EMPIRICAL_TEMPLATE.sections if s.section_id == "results"
        )
        assert method.needs_user_input is True
        assert results.needs_user_input is True

    def test_ilmiy_maqola_theoretical_has_framework_and_analysis(self) -> None:
        ids = [s.section_id for s in ILMIY_MAQOLA_THEORETICAL_TEMPLATE.sections]
        assert "theoretical_framework" in ids
        assert "analysis" in ids
        assert "methodology" not in ids
        assert "results" not in ids

    def test_hisobot_has_executive_summary_and_recommendations(self) -> None:
        ids = [s.section_id for s in HISOBOT_TEMPLATE.sections]
        assert "executive_summary" in ids
        assert "recommendations" in ids
        assert "findings" in ids

    def test_all_templates_have_trilingual_titles(self) -> None:
        for tpl in all_templates():
            for section in tpl.sections:
                assert set(section.titles.keys()) == {"uz", "ru", "en"}
                for value in section.titles.values():
                    assert value, (
                        f"empty title in {tpl.structure}/{tpl.variant}/{section.section_id}"
                    )

    def test_all_templates_have_quality_checklists(self) -> None:
        for tpl in all_templates():
            for section in tpl.sections:
                assert len(section.quality_checklist) >= 1, (
                    f"empty checklist in {tpl.structure}/{tpl.variant}/{section.section_id}"
                )

    def test_word_percentages_sum_to_one(self) -> None:
        for tpl in all_templates():
            total = sum(s.typical_word_percentage for s in tpl.sections)
            assert abs(total - 1.0) < 0.01, (
                f"{tpl.structure}/{tpl.variant} percentages sum to {total}"
            )


# ---------------------------------------------------------------------------
# Detection tests (4)
# ---------------------------------------------------------------------------


class TestEmpiricalDetection:
    def test_claims_with_statistical_markers_detected_empirical(self) -> None:
        claims = _claims(
            [
                "Adoption rate increased by 23% with p < 0.05 across the sample.",
                "We ran ANOVA on the dataset of 234 participants.",
                "Mean satisfaction score was 4.2 with std 0.8.",
            ]
        )
        chunks = _chunks(["Filler chunk text."])
        assert OutlineGenerator.detect_variant(claims, chunks) == EMPIRICAL_VARIANT

    def test_claims_without_markers_detected_theoretical(self) -> None:
        claims = _claims(
            [
                "Montesquieu argued for separation of powers as the foundation of liberty.",
                "Voltaire framed religious tolerance as essential to civil society.",
            ]
        )
        chunks = _chunks(["Theoretical discussion of Enlightenment philosophy."])
        assert OutlineGenerator.detect_variant(claims, chunks) == THEORETICAL_VARIANT

    def test_ambiguous_defaults_to_theoretical(self) -> None:
        claims = _claims(
            [
                "The dataset contains some entries.",
            ]
        )
        chunks = _chunks(["Background discussion only."])
        assert OutlineGenerator.detect_variant(claims, chunks) == THEORETICAL_VARIANT

    def test_user_override_respected(self) -> None:
        empirical_claims = _claims(
            [
                "p < 0.001, ANOVA, regression all confirm n = 500.",
            ]
        )
        chunks = _chunks(["with measurements and standard deviation"])
        forced = OutlineGenerator.detect_variant(
            empirical_claims, chunks, override=THEORETICAL_VARIANT
        )
        assert forced == THEORETICAL_VARIANT


# ---------------------------------------------------------------------------
# Word-target tests (4)
# ---------------------------------------------------------------------------


class TestWordTargets:
    def test_three_page_referat_word_count(self) -> None:
        targets = OutlineGenerator.calculate_word_targets(REFERAT_TEMPLATE, target_pages=3)
        # 3 pages * 275 words/page = 825 total (within rounding error)
        total_target = 3 * WORDS_PER_PAGE
        total = sum(targets.values())
        assert abs(total - total_target) <= len(targets), (
            f"total {total} too far from {total_target}"
        )
        assert targets["kirish"] == round(total_target * 0.15)
        assert targets["asosiy_qism"] == round(total_target * 0.70)

    def test_twenty_page_kurs_ishi_word_count(self) -> None:
        targets = OutlineGenerator.calculate_word_targets(KURS_ISHI_TEMPLATE, target_pages=20)
        total_target = 20 * WORDS_PER_PAGE
        total = sum(targets.values())
        assert abs(total - total_target) <= len(targets)
        assert targets["nazariy_asos"] == round(total_target * 0.40)

    def test_eight_page_ilmiy_maqola_word_count(self) -> None:
        targets = OutlineGenerator.calculate_word_targets(
            ILMIY_MAQOLA_EMPIRICAL_TEMPLATE, target_pages=8
        )
        # 8 pages * 275 = 2200 minus abstract clamp adjustment
        assert ABSTRACT_MIN_WORDS <= targets["abstract"] <= ABSTRACT_MAX_WORDS
        assert targets["introduction"] == round(8 * WORDS_PER_PAGE * 0.12)

    def test_abstract_capped_regardless_of_page_count(self) -> None:
        # Very long paper: 30 pages clamped to ilmiy_maqola max (12 pages),
        # then abstract section computed at 5% of total = 165 — under cap.
        long_targets = OutlineGenerator.calculate_word_targets(
            ILMIY_MAQOLA_EMPIRICAL_TEMPLATE, target_pages=30
        )
        assert ABSTRACT_MIN_WORDS <= long_targets["abstract"] <= ABSTRACT_MAX_WORDS
        # Very short paper: 3 pages clamped up to ilmiy_maqola min (6 pages).
        short_targets = OutlineGenerator.calculate_word_targets(
            ILMIY_MAQOLA_EMPIRICAL_TEMPLATE, target_pages=3
        )
        assert ABSTRACT_MIN_WORDS <= short_targets["abstract"] <= ABSTRACT_MAX_WORDS


# ---------------------------------------------------------------------------
# LLM-mocked outline-generation tests (12)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestOutlineGeneration:
    async def test_referat_generates_correct_structure(self) -> None:
        stub = _StubLLM(responses=[_good_referat_response()])
        gen = OutlineGenerator(llm=stub)  # type: ignore[arg-type]
        claims = _claims(
            [
                "Education was a key driver of social change in 18th-century Europe.",
                "Philosophical salons spread ideas across borders.",
                "Print culture lowered the cost of disseminating arguments.",
                "Reform movements responded to enlightened thinkers.",
            ]
        )
        outline = await gen.generate(
            project_id=uuid4(),
            structure=ArticleStructure.REFERAT,
            thesis="Education reshaped Uzbek society.",
            target_pages=4,
            claims=claims,
            chunks=_chunks(["Discussion of enlightenment thinkers and their ideas."]),
            source_metadata=_metadata(["Encyclopedia of Enlightenment"]),
            language=Language.UZ,
        )
        section_titles = [s.title for s in outline.sections]
        assert any("Kirish" in t for t in section_titles)
        assert any("Asosiy qism" in t for t in section_titles)
        assert any("Xulosa" in t for t in section_titles)
        # Asosiy qism produced two subsections, total 4 sections
        assert len(outline.sections) == 4

    async def test_kurs_ishi_generates_chapters_with_subsections(self) -> None:
        body = json.dumps(
            {
                "title": "Kurs ishi: ta'lim islohoti",
                "thesis": "Refined kurs ishi thesis.",
                "sections": [
                    {
                        "section_id": "kirish",
                        "subsections": [
                            {
                                "title": "Kirish",
                                "section_thesis": "Mavzuning dolzarbligi.",
                                "claim_indices": [0],
                                "needs_user_input": False,
                            }
                        ],
                    },
                    {
                        "section_id": "nazariy_asos",
                        "subsections": [
                            {
                                "title": "Asosiy tushunchalar",
                                "section_thesis": "Asosiy nazariy tushunchalar.",
                                "claim_indices": [1, 2],
                                "needs_user_input": False,
                            },
                            {
                                "title": "Tarixi",
                                "section_thesis": "Tarixiy rivojlanish.",
                                "claim_indices": [3, 4],
                                "needs_user_input": False,
                            },
                        ],
                    },
                    {
                        "section_id": "amaliy_qism",
                        "subsections": [
                            {
                                "title": "Misollar",
                                "section_thesis": "O'zbekistondagi misollar.",
                                "claim_indices": [5],
                                "needs_user_input": True,
                            },
                            {
                                "title": "Tahlil",
                                "section_thesis": "Misollarning tahlili.",
                                "claim_indices": [6],
                                "needs_user_input": True,
                            },
                        ],
                    },
                    {
                        "section_id": "xulosa",
                        "subsections": [
                            {
                                "title": "Xulosa",
                                "section_thesis": "Asosiy natijalar.",
                                "claim_indices": [],
                                "needs_user_input": False,
                            }
                        ],
                    },
                ],
            }
        )
        stub = _StubLLM(responses=[body])
        gen = OutlineGenerator(llm=stub)  # type: ignore[arg-type]
        claims = _claims([f"Kurs ishi claim {i}." for i in range(7)])
        outline = await gen.generate(
            project_id=uuid4(),
            structure=ArticleStructure.KURS_ISHI,
            thesis="Ta'lim islohoti haqida.",
            target_pages=20,
            claims=claims,
            chunks=_chunks(["x"]),
            source_metadata=[],
            language=Language.UZ,
        )
        # 1 (kirish) + 2 (nazariy) + 2 (amaliy) + 1 (xulosa) = 6 sections
        assert len(outline.sections) == 6
        nazariy_titles = [t for t in (s.title for s in outline.sections) if "1-bob" in t]
        assert len(nazariy_titles) == 2
        amaliy_titles = [t for t in (s.title for s in outline.sections) if "2-bob" in t]
        assert len(amaliy_titles) == 2

    async def test_empirical_article_generates_imrad(self) -> None:
        # Provide claims with empirical markers so detection picks empirical
        claims = _claims(
            [
                "Sample n = 250 with p < 0.05 results.",
                "ANOVA showed significant correlation across the dataset.",
                "Mean response time decreased by 18%.",
            ]
        )
        body = json.dumps(
            {
                "title": "Empirical study",
                "thesis": "Empirical thesis.",
                "sections": [
                    {
                        "section_id": s.section_id,
                        "subsections": [
                            {
                                "title": s.section_id,
                                "section_thesis": "x",
                                "claim_indices": [0],
                                "needs_user_input": False,
                            }
                        ],
                    }
                    for s in ILMIY_MAQOLA_EMPIRICAL_TEMPLATE.sections
                ],
            }
        )
        stub = _StubLLM(responses=[body])
        gen = OutlineGenerator(llm=stub)  # type: ignore[arg-type]
        outline = await gen.generate(
            project_id=uuid4(),
            structure=ArticleStructure.ILMIY_MAQOLA,
            thesis="Empirical thesis.",
            target_pages=8,
            claims=claims,
            chunks=_chunks(["with mean and standard deviation across participants"]),
            source_metadata=[],
            language=Language.EN,
        )
        assert outline.empirical_or_theoretical == EMPIRICAL_VARIANT
        section_ids_seen = [s.purpose for s in outline.sections]
        # Methodology purpose should be present (not theoretical framework)
        assert any("Methodology" in p for p in section_ids_seen)
        assert not any("framework" in p.lower() for p in section_ids_seen)

    async def test_theoretical_article_generates_aimrad(self) -> None:
        claims = _claims(
            [
                "Conceptual argument about deliberative democracy.",
                "Habermas grounded the public sphere in rational discourse.",
            ]
        )
        body = json.dumps(
            {
                "title": "Theoretical study",
                "thesis": "Theoretical thesis.",
                "sections": [
                    {
                        "section_id": s.section_id,
                        "subsections": [
                            {
                                "title": s.section_id,
                                "section_thesis": "x",
                                "claim_indices": [0],
                                "needs_user_input": False,
                            }
                        ],
                    }
                    for s in ILMIY_MAQOLA_THEORETICAL_TEMPLATE.sections
                ],
            }
        )
        stub = _StubLLM(responses=[body])
        gen = OutlineGenerator(llm=stub)  # type: ignore[arg-type]
        outline = await gen.generate(
            project_id=uuid4(),
            structure=ArticleStructure.ILMIY_MAQOLA,
            thesis="Theoretical thesis.",
            target_pages=8,
            claims=claims,
            chunks=_chunks(["abstract conceptual discussion only"]),
            source_metadata=[],
            language=Language.EN,
        )
        assert outline.empirical_or_theoretical == THEORETICAL_VARIANT
        assert any("Theoretical framework" in s.purpose for s in outline.sections)
        assert any("Analysis" in s.purpose for s in outline.sections)

    async def test_claims_assigned_to_sections(self) -> None:
        stub = _StubLLM(responses=[_good_referat_response()])
        gen = OutlineGenerator(llm=stub)  # type: ignore[arg-type]
        claims = _claims(
            [
                "Claim about education.",
                "Claim about salons.",
                "Claim about print.",
                "Claim about reforms.",
            ]
        )
        outline = await gen.generate(
            project_id=uuid4(),
            structure=ArticleStructure.REFERAT,
            thesis="Education reshaped Uzbek society.",
            target_pages=4,
            claims=claims,
            chunks=_chunks(["x"]),
            source_metadata=[],
            language=Language.UZ,
        )
        all_assigned = [c for s in outline.sections for c in s.key_claims_to_use]
        assert len(all_assigned) >= 3
        assert any("salons" in c for c in all_assigned)

    async def test_section_theses_populated(self) -> None:
        stub = _StubLLM(responses=[_good_referat_response()])
        gen = OutlineGenerator(llm=stub)  # type: ignore[arg-type]
        outline = await gen.generate(
            project_id=uuid4(),
            structure=ArticleStructure.REFERAT,
            thesis="Education reshaped Uzbek society.",
            target_pages=4,
            claims=_claims(["a", "b", "c", "d"]),
            chunks=_chunks(["x"]),
            source_metadata=[],
            language=Language.UZ,
        )
        for section in outline.sections:
            assert section.section_thesis, f"section {section.title} has empty section_thesis"

    async def test_min_citations_respected_in_assignment(self) -> None:
        # Only assign one claim to asosiy_qism, which has min_citations=2;
        # we expect the section to be flagged.
        body = json.dumps(
            {
                "title": "Title",
                "thesis": "Thesis.",
                "sections": [
                    {
                        "section_id": "kirish",
                        "subsections": [
                            {
                                "title": "Kirish",
                                "section_thesis": "x",
                                "claim_indices": [0],
                                "needs_user_input": False,
                            }
                        ],
                    },
                    {
                        "section_id": "asosiy_qism",
                        "subsections": [
                            {
                                "title": "Body",
                                "section_thesis": "x",
                                "claim_indices": [1],
                                "needs_user_input": False,
                            }
                        ],
                    },
                    {
                        "section_id": "xulosa",
                        "subsections": [
                            {
                                "title": "End",
                                "section_thesis": "x",
                                "claim_indices": [],
                                "needs_user_input": False,
                            }
                        ],
                    },
                ],
            }
        )
        stub = _StubLLM(responses=[body])
        gen = OutlineGenerator(llm=stub)  # type: ignore[arg-type]
        outline = await gen.generate(
            project_id=uuid4(),
            structure=ArticleStructure.REFERAT,
            thesis="Thesis.",
            target_pages=3,
            claims=_claims(["claim a", "claim b"]),
            chunks=_chunks(["x"]),
            source_metadata=[],
            language=Language.UZ,
        )
        flag_text = " ".join(outline.quality_flags)
        assert "min_citations_short" in flag_text
        assert "asosiy_qism" in flag_text

    async def test_weak_sections_flagged_in_quality_flags(self) -> None:
        # LLM omits one required section (xulosa) — expect repair attempt
        # to also fail (we feed the same JSON twice), then the section
        # appears as missing in quality_flags.
        body = json.dumps(
            {
                "title": "Partial",
                "thesis": "Thesis.",
                "sections": [
                    {
                        "section_id": "kirish",
                        "subsections": [
                            {
                                "title": "Kirish",
                                "section_thesis": "x",
                                "claim_indices": [0],
                                "needs_user_input": False,
                            }
                        ],
                    },
                    {
                        "section_id": "asosiy_qism",
                        "subsections": [
                            {
                                "title": "Asosiy",
                                "section_thesis": "x",
                                "claim_indices": [1, 2],
                                "needs_user_input": False,
                            }
                        ],
                    },
                ],
            }
        )
        # First call returns partial body; repair call also returns partial.
        stub = _StubLLM(responses=[body, body])
        gen = OutlineGenerator(llm=stub)  # type: ignore[arg-type]
        outline = await gen.generate(
            project_id=uuid4(),
            structure=ArticleStructure.REFERAT,
            thesis="Thesis.",
            target_pages=3,
            claims=_claims(["a", "b", "c"]),
            chunks=_chunks(["x"]),
            source_metadata=[],
            language=Language.UZ,
        )
        # Two calls were made (initial + repair) because xulosa was missing
        assert len(stub.calls) == 2
        flag_text = " ".join(outline.quality_flags)
        assert "missing_llm_output:xulosa" in flag_text

    async def test_user_thesis_reflected_in_outline(self) -> None:
        stub = _StubLLM(responses=[_good_referat_response(thesis="Refined thesis stmt.")])
        gen = OutlineGenerator(llm=stub)  # type: ignore[arg-type]
        outline = await gen.generate(
            project_id=uuid4(),
            structure=ArticleStructure.REFERAT,
            thesis="Original user thesis.",
            target_pages=3,
            claims=_claims(["a", "b", "c", "d"]),
            chunks=_chunks(["x"]),
            source_metadata=[],
            language=Language.UZ,
        )
        # User thesis must appear in the LLM prompt context
        assert "Original user thesis" in stub.calls[0][1]
        # Refined thesis from LLM is what ends up on the outline
        assert outline.thesis == "Refined thesis stmt."

    async def test_llm_failure_returns_fallback_outline(self) -> None:
        stub = _StubLLM(raise_on_call=RuntimeError("network down"))
        gen = OutlineGenerator(llm=stub)  # type: ignore[arg-type]
        outline = await gen.generate(
            project_id=uuid4(),
            structure=ArticleStructure.REFERAT,
            thesis="A thesis.",
            target_pages=3,
            claims=_claims(["claim a", "claim b"]),
            chunks=_chunks(["filler"]),
            source_metadata=[],
            language=Language.EN,
        )
        assert "fallback_template_only" in outline.quality_flags
        assert len(outline.sections) == len(REFERAT_TEMPLATE.sections)

    async def test_missing_section_triggers_repair_call(self) -> None:
        partial = json.dumps(
            {
                "title": "Partial",
                "thesis": "Thesis.",
                "sections": [
                    {
                        "section_id": "kirish",
                        "subsections": [
                            {
                                "title": "Kirish",
                                "section_thesis": "x",
                                "claim_indices": [0],
                                "needs_user_input": False,
                            }
                        ],
                    }
                ],
            }
        )
        full = _good_referat_response()
        stub = _StubLLM(responses=[partial, full])
        gen = OutlineGenerator(llm=stub)  # type: ignore[arg-type]
        outline = await gen.generate(
            project_id=uuid4(),
            structure=ArticleStructure.REFERAT,
            thesis="Thesis.",
            target_pages=3,
            claims=_claims(["a", "b", "c", "d"]),
            chunks=_chunks(["x"]),
            source_metadata=[],
            language=Language.UZ,
        )
        # Two LLM calls: first incomplete, second a successful repair
        assert len(stub.calls) == 2
        # Repaired outline contains all three referat sections
        ids_in_titles = " ".join(s.title for s in outline.sections)
        assert "Kirish" in ids_in_titles
        assert "Asosiy qism" in ids_in_titles
        assert "Xulosa" in ids_in_titles

    async def test_unassigned_claims_routed_by_linker(self) -> None:
        # LLM assigns claims 0, 1, 2 only — claims 3 and 4 are left over
        # and should be routed to sections by ClaimLinker via Jaccard
        # token overlap with the LLM-assigned key_claims_to_use.
        body = json.dumps(
            {
                "title": "T",
                "thesis": "Thesis.",
                "sections": [
                    {
                        "section_id": "kirish",
                        "subsections": [
                            {
                                "title": "Kirish",
                                "section_thesis": "x",
                                "claim_indices": [0],
                                "needs_user_input": False,
                            }
                        ],
                    },
                    {
                        "section_id": "asosiy_qism",
                        "subsections": [
                            {
                                "title": "Salons",
                                "section_thesis": "x",
                                "claim_indices": [1, 2],
                                "needs_user_input": False,
                            }
                        ],
                    },
                    {
                        "section_id": "xulosa",
                        "subsections": [
                            {
                                "title": "Xulosa",
                                "section_thesis": "x",
                                "claim_indices": [],
                                "needs_user_input": False,
                            }
                        ],
                    },
                ],
            }
        )
        stub = _StubLLM(responses=[body])
        gen = OutlineGenerator(llm=stub)  # type: ignore[arg-type]
        claims = _claims(
            [
                "Education was a key driver of social change in Europe.",
                "Philosophical salons spread ideas across European borders.",
                "Print culture lowered the cost of disseminating arguments.",
                "Salons hosted philosophical debates between scholars across Europe.",
                "Education shaped social hierarchy among European elites.",
            ]
        )
        outline = await gen.generate(
            project_id=uuid4(),
            structure=ArticleStructure.REFERAT,
            thesis="Thesis.",
            target_pages=4,
            claims=claims,
            chunks=_chunks(["x"]),
            source_metadata=[],
            language=Language.UZ,
        )
        all_assigned_text = " ".join(c for s in outline.sections for c in s.key_claims_to_use)
        # Claim 3 (Salons hosted...) should land in Asosiy qism via "salons"
        assert "Salons hosted philosophical debates" in all_assigned_text
        # Claim 4 (Education shaped social...) should land in Kirish via "education"+"social"
        assert "Education shaped social hierarchy" in all_assigned_text

    async def test_language_specific_section_titles(self) -> None:
        for language, expected in (
            (Language.UZ, "Kirish"),
            (Language.RU, "Введение"),
            (Language.EN, "Introduction"),
        ):
            body = json.dumps(
                {
                    "title": "Title",
                    "thesis": "Thesis.",
                    "sections": [
                        {
                            "section_id": "kirish",
                            "subsections": [
                                {
                                    "title": "",
                                    "section_thesis": "x",
                                    "claim_indices": [0],
                                    "needs_user_input": False,
                                }
                            ],
                        },
                        {
                            "section_id": "asosiy_qism",
                            "subsections": [
                                {
                                    "title": "",
                                    "section_thesis": "x",
                                    "claim_indices": [0],
                                    "needs_user_input": False,
                                }
                            ],
                        },
                        {
                            "section_id": "xulosa",
                            "subsections": [
                                {
                                    "title": "",
                                    "section_thesis": "x",
                                    "claim_indices": [],
                                    "needs_user_input": False,
                                }
                            ],
                        },
                    ],
                }
            )
            stub = _StubLLM(responses=[body])
            gen = OutlineGenerator(llm=stub)  # type: ignore[arg-type]
            outline = await gen.generate(
                project_id=uuid4(),
                structure=ArticleStructure.REFERAT,
                thesis="Thesis.",
                target_pages=3,
                claims=_claims(["x"]),
                chunks=_chunks(["x"]),
                source_metadata=[],
                language=language,
            )
            assert any(expected in s.title for s in outline.sections), (
                f"expected {expected!r} for {language.value}, got {[s.title for s in outline.sections]}"
            )


# ---------------------------------------------------------------------------
# Edge-case tests (5)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestEdgeCases:
    async def test_single_source_thin_evidence_warning(self) -> None:
        # Single claim, asosiy_qism min_citations=2 → flagged
        body = json.dumps(
            {
                "title": "Thin",
                "thesis": "Thin thesis.",
                "sections": [
                    {
                        "section_id": "kirish",
                        "subsections": [
                            {
                                "title": "Kirish",
                                "section_thesis": "x",
                                "claim_indices": [0],
                                "needs_user_input": False,
                            }
                        ],
                    },
                    {
                        "section_id": "asosiy_qism",
                        "subsections": [
                            {
                                "title": "Body",
                                "section_thesis": "x",
                                "claim_indices": [0],
                                "needs_user_input": False,
                            }
                        ],
                    },
                    {
                        "section_id": "xulosa",
                        "subsections": [
                            {
                                "title": "End",
                                "section_thesis": "x",
                                "claim_indices": [],
                                "needs_user_input": False,
                            }
                        ],
                    },
                ],
            }
        )
        stub = _StubLLM(responses=[body])
        gen = OutlineGenerator(llm=stub)  # type: ignore[arg-type]
        outline = await gen.generate(
            project_id=uuid4(),
            structure=ArticleStructure.REFERAT,
            thesis="Thin thesis.",
            target_pages=3,
            claims=_claims(["only one claim"]),
            chunks=_chunks(["x"]),
            source_metadata=[],
            language=Language.UZ,
        )
        assert any("min_citations_short" in f for f in outline.quality_flags)

    async def test_empty_evidence_uses_template_defaults(self) -> None:
        stub = _StubLLM(raise_on_call=RuntimeError("offline"))
        gen = OutlineGenerator(llm=stub)  # type: ignore[arg-type]
        outline = await gen.generate(
            project_id=uuid4(),
            structure=ArticleStructure.HISOBOT,
            thesis="Empty.",
            target_pages=5,
            claims=[],
            chunks=[],
            source_metadata=[],
            language=Language.EN,
        )
        assert "fallback_template_only" in outline.quality_flags
        assert len(outline.sections) == len(HISOBOT_TEMPLATE.sections)

    async def test_very_short_target_clamped(self) -> None:
        targets = OutlineGenerator.calculate_word_targets(
            ILMIY_MAQOLA_EMPIRICAL_TEMPLATE, target_pages=3
        )
        # Clamped up to template min_pages=6
        assert (
            sum(targets.values()) >= ILMIY_MAQOLA_EMPIRICAL_TEMPLATE.min_pages * WORDS_PER_PAGE - 5
        )

    async def test_very_long_target_capped(self) -> None:
        # Kurs ishi max_pages=25; even target_pages=30 should be clamped
        targets = OutlineGenerator.calculate_word_targets(KURS_ISHI_TEMPLATE, target_pages=30)
        assert sum(targets.values()) <= KURS_ISHI_TEMPLATE.max_pages * WORDS_PER_PAGE + 5

    async def test_outline_round_trip_serialization(self) -> None:
        stub = _StubLLM(responses=[_good_referat_response()])
        gen = OutlineGenerator(llm=stub)  # type: ignore[arg-type]
        outline = await gen.generate(
            project_id=uuid4(),
            structure=ArticleStructure.REFERAT,
            thesis="Round-trip thesis.",
            target_pages=3,
            claims=_claims(["a", "b", "c", "d"]),
            chunks=_chunks(["x"]),
            source_metadata=[],
            language=Language.UZ,
        )
        rebuilt = ArticleOutline.model_validate(outline.model_dump(mode="json"))
        assert rebuilt == outline


# ---------------------------------------------------------------------------
# Model-validation tests (2)
# ---------------------------------------------------------------------------


class TestModels:
    def test_section_requirement_construction(self) -> None:
        req = SectionRequirement(
            section_id="abc",
            internal_purpose="Purpose statement.",
            quality_checklist=["item one"],
            titles={"uz": "A", "ru": "Б", "en": "C"},
            typical_word_percentage=0.25,
        )
        assert req.is_required is True
        assert req.allows_subsections is False
        assert req.max_subsections == 1
        # extra="forbid" must reject unknown fields
        with pytest.raises(ValidationError):
            SectionRequirement(  # type: ignore[call-arg]
                section_id="abc",
                internal_purpose="Purpose.",
                quality_checklist=["q"],
                titles={"uz": "A", "ru": "Б", "en": "C"},
                typical_word_percentage=0.25,
                bogus_field="nope",
            )

    def test_template_lookup_raises_on_unknown_variant(self) -> None:
        # Lookup by structure works
        tpl = get_template(ArticleStructure.REFERAT)
        assert tpl.structure is ArticleStructure.REFERAT
        # Bad ilmiy_maqola variant raises
        with pytest.raises(ValueError):
            get_template(ArticleStructure.ILMIY_MAQOLA, variant="invalid")
        # OutlineSection round-trip with new fields
        section = OutlineSection(
            title="T",
            target_words=300,
            key_claims_to_use=["a"],
            purpose="P.",
            section_thesis="A specific thesis.",
            quality_flags=["flag1"],
            needs_user_input=True,
            min_citations=3,
        )
        rebuilt = OutlineSection.model_validate(section.model_dump(mode="json"))
        assert rebuilt == section
