"""Behaviour tests for :class:`DomainDetector`.

The detector is a pure heuristic — no I/O, no LLM — so the tests build
realistic inputs (claim/chunk/outline/source-metadata bundles) and assert
on the resulting :class:`DomainDetectionResult`. Each test pins one
property of the contract used by the orchestrator: which domain wins,
which keywords matched, how multilingual content is handled, and how
empty input degrades to ``GENERAL``.
"""

from __future__ import annotations

from uuid import uuid4

from packages.core.enums import (
    ArticleStructure,
    ClaimStrength,
    ClaimType,
)
from packages.core.models import (
    ArticleOutline,
    OutlineSection,
    SourceChunkCreate,
    SourceClaimCreate,
    SourceMetadataExtracted,
)
from packages.core.models.suggestion import AcademicDomain
from packages.suggestions.domain_detector import DomainDetector


def _claim(text: str) -> SourceClaimCreate:
    return SourceClaimCreate(
        source_chunk_id=str(uuid4()),
        project_id=str(uuid4()),
        claim_text=text,
        strength=ClaimStrength.MODERATE,
        claim_type=ClaimType.GENERAL_FACT,
    )


def _chunk(text: str) -> SourceChunkCreate:
    return SourceChunkCreate(
        source_id=str(uuid4()),
        project_id=str(uuid4()),
        chunk_index=0,
        text=text,
    )


def _outline(title: str, section_titles: list[str]) -> ArticleOutline:
    sections = [
        OutlineSection(
            title=t,
            target_words=400,
            purpose="test",
            section_thesis="",
        )
        for t in section_titles
    ]
    return ArticleOutline(
        title=title,
        structure=ArticleStructure.REFERAT,
        sections=sections,
        thesis="x" * 5,
        total_target_words=400 * max(len(sections), 1),
    )


def test_detect_medical_from_claims() -> None:
    detector = DomainDetector()
    claims = [
        _claim("The patient underwent clinical evaluation for chronic disease."),
        _claim(
            "A randomized treatment trial showed reduced mortality among the cohort under therapy."
        ),
        _claim("Diagnosis was confirmed via biomarker analysis at the hospital."),
    ]
    result = detector.detect_domains(claims, [], None, [])

    assert result.primary_domain == AcademicDomain.MEDICAL
    medical = next(s for s in result.all_domains if s.domain == AcademicDomain.MEDICAL)
    assert medical.confidence > 0.5
    assert "patient" in medical.matched_keywords
    assert "clinical" in medical.matched_keywords


def test_detect_economics_from_claims() -> None:
    detector = DomainDetector()
    claims = [
        _claim("GDP growth in 2023 reached 5.6 percent driven by rising export volumes."),
        _claim("Inflation pressures forced a tighter monetary stance and higher interest rate."),
        _claim("Trade balance widened on stronger demand and lower import tariff revenue."),
    ]
    result = detector.detect_domains(claims, [], None, [])
    assert result.primary_domain == AcademicDomain.ECONOMICS
    economics = next(s for s in result.all_domains if s.domain == AcademicDomain.ECONOMICS)
    assert economics.confidence > 0.5


def test_detect_legal_from_uzbek_claims() -> None:
    detector = DomainDetector()
    claims = [
        _claim("Konstitusiya asosida qonun ijrosi sud orqali ta'minlanadi."),
        _claim("Yangi farmon huquq sohasidagi muhim qaror bo'lib hisoblanadi."),
        _claim("Jinoyat va fuqarolik ishlari kodeks bilan tartibga solinadi."),
    ]
    result = detector.detect_domains(claims, [], None, [])
    assert result.primary_domain == AcademicDomain.LEGAL


def test_detect_engineering_or_cs_from_claims() -> None:
    detector = DomainDetector()
    claims = [
        _claim("The proposed algorithm achieves better optimization than prior methods."),
        _claim("Simulation of the control system demonstrates improved sensor response."),
        _claim("Finite element analysis revealed new stress distributions in the structure."),
    ]
    result = detector.detect_domains(claims, [], None, [])
    assert result.primary_domain in {
        AcademicDomain.ENGINEERING,
        AcademicDomain.COMPUTER_SCIENCE,
    }


def test_detect_medical_uzbek_keywords() -> None:
    detector = DomainDetector()
    claims = [
        _claim("Bemor kasallik belgilarini ko'rsatdi va davolash boshlandi."),
        _claim("Shifoxona statistikasi tibbiyot tizimi sifatini aniqlaydi."),
        _claim("Diagnostika natijalari jarrohlik aralashuvini taqozo etdi."),
    ]
    result = detector.detect_domains(claims, [], None, [])
    assert result.primary_domain == AcademicDomain.MEDICAL


def test_detect_economics_russian_keywords() -> None:
    detector = DomainDetector()
    claims = [
        _claim("Экономика страны столкнулась с ростом инфляции и безработицы."),
        _claim("Бюджет на следующий год учитывает повышение налог на инвестиции."),
        _claim("Торговля и рынок укрепились после стабилизации курса."),
    ]
    result = detector.detect_domains(claims, [], None, [])
    assert result.primary_domain == AcademicDomain.ECONOMICS


def test_detect_general_when_no_domain_matches() -> None:
    detector = DomainDetector()
    claims = [
        _claim("The sky was blue and the wind was steady."),
        _claim("She wrote a letter to her friend describing the journey."),
    ]
    result = detector.detect_domains(claims, [], None, [])
    assert result.primary_domain == AcademicDomain.GENERAL
    assert result.all_domains == []


def test_detect_multiple_domains_when_text_spans_them() -> None:
    detector = DomainDetector()
    claims = [
        _claim("Government health expenditure covered 4% of GDP, a fiscal anchor."),
        _claim(
            "Inflation eroded patient access to pharmaceutical treatment, raising mortality risk."
        ),
        _claim("The clinical trial measured both treatment cost and patient outcome."),
        _claim("A new monetary stance lowered interest rate pressures on hospital budgets."),
    ]
    result = detector.detect_domains(claims, [], None, [])
    domains = {s.domain for s in result.all_domains}
    assert AcademicDomain.MEDICAL in domains
    assert AcademicDomain.ECONOMICS in domains


def test_detect_returns_matched_keywords_actually_in_text() -> None:
    detector = DomainDetector()
    claim = _claim(
        "The clinical patient showed acute symptoms requiring immediate hospital therapy."
    )
    result = detector.detect_domains([claim], [], None, [])
    assert result.primary_domain == AcademicDomain.MEDICAL
    medical = next(s for s in result.all_domains if s.domain == AcademicDomain.MEDICAL)
    text = claim.claim_text.lower()
    for kw in medical.matched_keywords:
        assert kw in text, f"matched keyword {kw!r} not actually in source text"


def test_detect_from_outline_titles() -> None:
    detector = DomainDetector()
    outline = _outline(
        "Environmental Policy in Central Asia",
        [
            "Climate Change and Biodiversity Loss",
            "Air Quality and Pollution Trends",
            "Renewable Energy Adoption",
        ],
    )
    result = detector.detect_domains([], [], outline, [])
    assert result.primary_domain == AcademicDomain.ENVIRONMENTAL


def test_detect_from_source_metadata_titles() -> None:
    detector = DomainDetector()
    metas = [
        SourceMetadataExtracted(title="Journal of Clinical Medicine"),
        SourceMetadataExtracted(title="Patient Care Quarterly"),
    ]
    result = detector.detect_domains([], [], None, metas)
    assert result.primary_domain == AcademicDomain.MEDICAL


def test_detect_empty_input_returns_general() -> None:
    detector = DomainDetector()
    result = detector.detect_domains([], [], None, [])
    assert result.primary_domain == AcademicDomain.GENERAL
    assert result.all_domains == []


def test_detection_method_is_keyword_analysis() -> None:
    detector = DomainDetector()
    result = detector.detect_domains(
        [_claim("clinical patient hospital treatment therapy")], [], None, []
    )
    assert result.detection_method == "keyword_analysis"


def test_detect_chunks_contribute_to_score() -> None:
    detector = DomainDetector()
    chunks = [
        _chunk(
            "Crop yield improved through better irrigation. The harvest of livestock"
            " feed grain in the region grew despite soil constraints. Fertilizer use"
            " was optimised under the agriculture programme."
        ),
    ]
    result = detector.detect_domains([], chunks, None, [])
    assert result.primary_domain == AcademicDomain.AGRICULTURE


def test_detection_result_round_trip() -> None:
    detector = DomainDetector()
    result = detector.detect_domains([_claim("clinical patient hospital treatment")], [], None, [])
    rebuilt = type(result).model_validate(result.model_dump())
    assert rebuilt == result
