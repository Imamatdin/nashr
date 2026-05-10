"""Behaviour tests for :class:`SuggestionEngine`.

The engine is the orchestrator: it walks an outline, decides which
sections need suggestions, fans queries out to providers, and ranks
results. All provider calls are mocked via :class:`_FakeProvider` so
no network I/O happens. Tests pin section-need analysis, composite
scoring, deduplication, and end-to-end pipeline behaviour.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from packages.core.enums import (
    ArticleStructure,
    CitationStatus,
    ClaimStrength,
    ClaimType,
)
from packages.core.models.article import ArticleOutline, OutlineSection
from packages.core.models.evidence import EvidenceMatrix, EvidenceMatrixEntry
from packages.core.models.source import SourceClaimCreate
from packages.core.models.suggestion import (
    AcademicDomain,
    SectionNeed,
    SectionNeedType,
    Suggestion,
    SuggestionSource,
)
from packages.suggestions.engine import (
    SuggestionEngine,
    _compute_composite_score,
    _dedupe,
)
from packages.suggestions.provider_registry import ProviderRegistry

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class _FakeProvider:
    """In-memory :class:`SuggestionProvider` returning canned suggestions."""

    def __init__(
        self,
        name: str,
        domains: list[AcademicDomain],
        suggestions: list[Suggestion] | None = None,
        raise_on_search: bool = False,
    ) -> None:
        self.provider_name = name
        self.supported_domains: list[AcademicDomain] = domains
        self._suggestions = suggestions if suggestions is not None else []
        self._raise = raise_on_search
        self.calls: int = 0

    async def search(
        self, query: str, section_context: str, max_results: int = 5
    ) -> list[Suggestion]:
        self.calls += 1
        if self._raise:
            raise RuntimeError(f"{self.provider_name} simulated failure for {query!r}")
        _ = section_context
        return list(self._suggestions[:max_results])

    async def close(self) -> None:
        return None


def _make_suggestion(
    title: str,
    score: float = 0.85,
    provider: SuggestionSource = SuggestionSource.PUBMED,
    doi: str | None = None,
    indicator_value: str | None = None,
    law_number: str | None = None,
    year: int | None = 2024,
    authors: list[str] | None = None,
) -> Suggestion:
    return Suggestion(
        title=title,
        description=f"Authoritative description for {title}.",
        source_provider=provider,
        relevance_score=score,
        doi=doi,
        indicator_value=indicator_value,
        law_number=law_number,
        year=year,
        authors=authors if authors is not None else ["Karimov A"],
    )


def _section(
    title: str,
    thesis: str = "",
    purpose: str = "Discuss the topic",
    needs_user_input: bool = False,
) -> OutlineSection:
    return OutlineSection(
        title=title,
        target_words=400,
        purpose=purpose,
        section_thesis=thesis,
        needs_user_input=needs_user_input,
    )


def _outline(sections: list[OutlineSection]) -> ArticleOutline:
    return ArticleOutline(
        title="Test Article",
        structure=ArticleStructure.REFERAT,
        sections=sections,
        thesis="Test thesis statement.",
        total_target_words=sum(s.target_words for s in sections),
    )


def _empty_matrix() -> EvidenceMatrix:
    return EvidenceMatrix(project_id=uuid4(), entries=[])


def _matrix_for_sections(
    project_id: UUID,
    section_ready_counts: dict[UUID, int],
    citation_status: CitationStatus = CitationStatus.READY,
) -> EvidenceMatrix:
    now = datetime.now(UTC)
    entries: list[EvidenceMatrixEntry] = []
    for section_id, count in section_ready_counts.items():
        for _ in range(count):
            entries.append(
                EvidenceMatrixEntry(
                    project_id=project_id,
                    claim_id=uuid4(),
                    source_chunk_id=uuid4(),
                    article_section_id=section_id,
                    citation_status=citation_status,
                    created_at=now,
                )
            )
    return EvidenceMatrix(project_id=project_id, entries=entries)


def _claim(
    text: str,
    strength: ClaimStrength = ClaimStrength.MODERATE,
    claim_type: ClaimType = ClaimType.GENERAL_FACT,
) -> SourceClaimCreate:
    return SourceClaimCreate(
        source_chunk_id=str(uuid4()),
        project_id=str(uuid4()),
        claim_text=text,
        strength=strength,
        claim_type=claim_type,
    )


def _registry_with(providers: list[_FakeProvider]) -> ProviderRegistry:
    """Build a registry whose only providers are the ones we inject."""

    registry = ProviderRegistry()
    registry._providers = {}  # type: ignore[reportPrivateUsage]
    for provider in providers:
        for domain in provider.supported_domains:
            registry.register(domain, provider)
    return registry


def _need(*types: SectionNeedType) -> SectionNeed:
    return SectionNeed(
        section_id=str(uuid4()),
        needs_suggestions=bool(types),
        need_types=list(types) if types else [SectionNeedType.NO_NEED],
        ready_claim_count=0,
        total_claim_count=0,
        reason="",
    )


# ---------------------------------------------------------------------------
# Section need analysis
# ---------------------------------------------------------------------------


def test_abstract_never_needs_suggestions() -> None:
    engine = SuggestionEngine()
    section = _section("Abstract", purpose="Self-contained abstract summarising the work")
    matrix = _empty_matrix()
    need = engine._should_suggest_for_section(section, matrix, [])
    assert need.needs_suggestions is False


def test_conclusion_never_needs_suggestions() -> None:
    engine = SuggestionEngine()
    for title in ("Conclusion", "Xulosa", "Заключение"):
        section = _section(title, purpose="Restate the goal")
        matrix = _empty_matrix()
        need = engine._should_suggest_for_section(section, matrix, [])
        assert need.needs_suggestions is False, title


def test_section_with_zero_claims_needs_suggestions() -> None:
    engine = SuggestionEngine()
    section = _section("Background on Banking Reform")
    matrix = _empty_matrix()
    need = engine._should_suggest_for_section(section, matrix, [])
    assert need.needs_suggestions is True
    assert SectionNeedType.THIN_EVIDENCE in need.need_types


def test_section_with_strong_evidence_no_need() -> None:
    engine = SuggestionEngine()
    section = _section("Banking Reform Outcomes")
    project_id = uuid4()
    matrix = _matrix_for_sections(project_id, {section.id: 5})
    claims = [
        _claim("Banking reform improved access to credit.", ClaimStrength.STRONG),
        _claim("Bank rate cut by central authority.", ClaimStrength.MODERATE),
        _claim("Loan growth widened across regions.", ClaimStrength.MODERATE),
    ]
    need = engine._should_suggest_for_section(section, matrix, claims)
    assert need.needs_suggestions is False


def test_section_with_one_claim_needs_suggestions() -> None:
    engine = SuggestionEngine()
    section = _section("Banking Reform Outcomes")
    project_id = uuid4()
    matrix = _matrix_for_sections(project_id, {section.id: 1})
    need = engine._should_suggest_for_section(section, matrix, [])
    assert need.needs_suggestions is True
    assert SectionNeedType.THIN_EVIDENCE in need.need_types


def test_section_with_all_weak_claims_needs_suggestions() -> None:
    engine = SuggestionEngine()
    section = _section("Banking Reform Outcomes")
    project_id = uuid4()
    matrix = _matrix_for_sections(project_id, {section.id: 3})
    claims = [
        _claim("First weak observation about reform.", ClaimStrength.WEAK),
        _claim("Second weak observation about reform.", ClaimStrength.WEAK),
        _claim("Third weak observation about reform.", ClaimStrength.WEAK),
    ]
    need = engine._should_suggest_for_section(section, matrix, claims)
    assert need.needs_suggestions is True
    assert SectionNeedType.WEAK_CLAIMS_ONLY in need.need_types


def test_literature_review_always_needs_suggestions() -> None:
    engine = SuggestionEngine()
    section = _section(
        "Literature Review of Renewable Energy",
        purpose="Survey existing scholarship on renewables",
    )
    project_id = uuid4()
    matrix = _matrix_for_sections(project_id, {section.id: 5})
    need = engine._should_suggest_for_section(section, matrix, [])
    assert need.needs_suggestions is True


def test_methodology_needs_when_user_input_required() -> None:
    engine = SuggestionEngine()
    section = _section(
        "Methodology",
        purpose="Describe the methodology",
        needs_user_input=True,
    )
    matrix = _empty_matrix()
    need = engine._should_suggest_for_section(section, matrix, [])
    assert need.needs_suggestions is True


def test_methodology_no_input_no_need_when_evidence_present() -> None:
    engine = SuggestionEngine()
    section = _section(
        "Methodology",
        purpose="Describe the methodology",
        needs_user_input=False,
    )
    project_id = uuid4()
    matrix = _matrix_for_sections(project_id, {section.id: 3})
    need = engine._should_suggest_for_section(section, matrix, [])
    assert need.needs_suggestions is False


def test_discussion_with_thin_evidence() -> None:
    engine = SuggestionEngine()
    section = _section("Discussion of Findings", purpose="Discuss findings")
    project_id = uuid4()
    matrix = _matrix_for_sections(project_id, {section.id: 2})
    need = engine._should_suggest_for_section(section, matrix, [])
    assert need.needs_suggestions is True
    assert SectionNeedType.THIN_EVIDENCE in need.need_types


def test_discussion_with_three_ready_claims_no_need() -> None:
    engine = SuggestionEngine()
    section = _section("Discussion of Findings", purpose="Discuss findings")
    project_id = uuid4()
    matrix = _matrix_for_sections(project_id, {section.id: 3})
    claims = [
        _claim("Discussion claim a about implications.", ClaimStrength.MODERATE),
        _claim("Discussion claim b about counter-evidence.", ClaimStrength.STRONG),
    ]
    need = engine._should_suggest_for_section(section, matrix, claims)
    assert need.needs_suggestions is False


def test_introduction_with_thin_evidence() -> None:
    engine = SuggestionEngine()
    section = _section("Introduction", purpose="Introduce the topic")
    project_id = uuid4()
    matrix = _matrix_for_sections(project_id, {section.id: 1})
    need = engine._should_suggest_for_section(section, matrix, [])
    assert need.needs_suggestions is True


# ---------------------------------------------------------------------------
# Relevance scoring
# ---------------------------------------------------------------------------


def test_composite_score_boosts_statistical_for_stat_need() -> None:
    section = _section("GDP Trends")
    need = _need(SectionNeedType.NO_STATISTICAL_BACKING)
    sugg = _make_suggestion("GDP indicator", score=0.6, indicator_value="56000000", year=2024)
    score = _compute_composite_score(sugg, section, need)
    plain_need = _need(SectionNeedType.THIN_EVIDENCE)
    plain_score = _compute_composite_score(sugg, section, plain_need)
    assert score > plain_score


def test_composite_score_boosts_legal_for_legal_need() -> None:
    section = _section("Banking Law")
    need = _need(SectionNeedType.NO_LEGAL_GROUNDING)
    sugg = _make_suggestion("Decree on Banking", score=0.6, law_number="DP-3456", year=2024)
    score = _compute_composite_score(sugg, section, need)
    plain_need = _need(SectionNeedType.THIN_EVIDENCE)
    plain_score = _compute_composite_score(sugg, section, plain_need)
    assert score > plain_score


def test_composite_score_boosts_recency() -> None:
    section = _section("Topic")
    need = _need(SectionNeedType.THIN_EVIDENCE)
    current_year = datetime.now().year
    recent = _make_suggestion("Recent", score=0.6, year=current_year, doi=None, authors=["A"])
    old = _make_suggestion("Old", score=0.6, year=2000, doi=None, authors=["A"])
    assert _compute_composite_score(recent, section, need) > _compute_composite_score(
        old, section, need
    )


def test_composite_score_penalizes_missing_metadata() -> None:
    section = _section("Topic")
    need = _need(SectionNeedType.THIN_EVIDENCE)
    bare = _make_suggestion("Bare", score=0.7, doi=None, year=None, authors=[])
    rich = _make_suggestion("Rich", score=0.7, doi=None, year=None, authors=["Author A"])
    bare_score = _compute_composite_score(bare, section, need)
    rich_score = _compute_composite_score(rich, section, need)
    assert bare_score < rich_score


def test_composite_score_capped_at_one() -> None:
    section = _section("Topic")
    need = _need(SectionNeedType.NO_STATISTICAL_BACKING, SectionNeedType.NO_LEGAL_GROUNDING)
    sugg = _make_suggestion(
        "Maxed",
        score=0.95,
        doi="10.1/x",
        indicator_value="100",
        law_number="L-1",
        year=datetime.now().year,
        authors=["A"],
    )
    sugg = sugg.model_copy(update={"citation_count": 500})
    score = _compute_composite_score(sugg, section, need)
    assert score <= 1.0


def test_composite_score_clamped_to_zero() -> None:
    section = _section("Topic")
    need = _need(SectionNeedType.THIN_EVIDENCE)
    sugg = _make_suggestion("Empty", score=0.05, doi=None, year=None, authors=[])
    score = _compute_composite_score(sugg, section, need)
    assert score >= 0.0


# ---------------------------------------------------------------------------
# Filtering and deduplication
# ---------------------------------------------------------------------------


def test_filter_below_threshold() -> None:
    suggs = [
        _make_suggestion("a", score=0.8),
        _make_suggestion("b", score=0.5),
        _make_suggestion("c", score=0.3),
        _make_suggestion("d", score=0.9),
    ]
    above = [s for s in suggs if s.relevance_score >= SuggestionEngine.RELEVANCE_THRESHOLD]
    assert len(above) == 2
    assert {s.title for s in above} == {"a", "d"}


def test_deduplicate_by_doi() -> None:
    a = _make_suggestion("A title", score=0.8, doi="10.1/same")
    b = _make_suggestion("Different title", score=0.9, doi="10.1/same")
    deduped = _dedupe([a, b])
    assert len(deduped) == 1
    assert deduped[0].relevance_score == 0.9


def test_deduplicate_by_title_similarity() -> None:
    a = _make_suggestion("Banking reform reduces inequality in Central Asia", score=0.7, doi=None)
    b = _make_suggestion("Banking reform reduces inequality in Asia Central", score=0.85, doi=None)
    deduped = _dedupe([a, b])
    assert len(deduped) == 1
    assert deduped[0].relevance_score == 0.85


def test_no_dedup_different_content() -> None:
    a = _make_suggestion("Banking reform in Uzbekistan", score=0.7, doi="10.1/a")
    b = _make_suggestion("Healthcare access in Tajikistan", score=0.8, doi="10.1/b")
    deduped = _dedupe([a, b])
    assert len(deduped) == 2


# ---------------------------------------------------------------------------
# End-to-end pipeline
# ---------------------------------------------------------------------------


def test_analyze_and_suggest_full_pipeline() -> None:
    pubmed_results = [
        _make_suggestion("Insulin therapy outcomes", score=0.9, doi="10.1/a"),
        _make_suggestion("Cardiac patient survival", score=0.8, doi="10.1/b"),
    ]
    fake = _FakeProvider("PubMed", [AcademicDomain.MEDICAL, AcademicDomain.GENERAL], pubmed_results)
    registry = _registry_with([fake])
    engine = SuggestionEngine(registry=registry)

    sections = [
        _section("Abstract", purpose="Self-contained abstract"),
        _section("Introduction", purpose="Introduce the medical topic"),
        _section(
            "Literature Review on Diabetes",
            purpose="Survey medical literature",
        ),
        _section("Methodology", purpose="Describe methodology", needs_user_input=True),
        _section("Conclusion", purpose="Conclude the work"),
    ]
    outline = _outline(sections)
    matrix = _empty_matrix()
    claims = [
        _claim("The patient cohort responded to insulin therapy.", ClaimStrength.MODERATE),
        _claim(
            "Hospital admissions decreased after treatment protocol changed.",
            ClaimStrength.MODERATE,
        ),
    ]

    report = asyncio.run(
        engine.analyze_and_suggest(
            outline=outline,
            evidence_matrix=matrix,
            claims=claims,
            chunks=[],
            source_metadata=[],
            language="en",
        )
    )

    assert report.sections_analyzed == 5
    assert report.sections_with_suggestions >= 2
    assert report.sections_skipped >= 2
    for section_sugg in report.section_suggestions:
        for s in section_sugg.suggestions:
            assert s.relevance_score >= SuggestionEngine.RELEVANCE_THRESHOLD


def test_analyze_and_suggest_no_providers_match() -> None:
    bridge = _FakeProvider(
        "Academic Search",
        [AcademicDomain.GENERAL],
        [_make_suggestion("Generic finding", score=0.8, doi="10.1/g")],
    )
    registry = _registry_with([bridge])
    engine = SuggestionEngine(registry=registry)

    sections = [_section("Mysterious Niche Topic", purpose="Discuss niche")]
    outline = _outline(sections)
    matrix = _empty_matrix()

    report = asyncio.run(
        engine.analyze_and_suggest(
            outline=outline,
            evidence_matrix=matrix,
            claims=[],
            chunks=[],
            source_metadata=[],
            language="en",
        )
    )
    assert "Academic Search" in report.providers_queried


def test_analyze_and_suggest_provider_failure_handled() -> None:
    good = _FakeProvider(
        "Good",
        [AcademicDomain.GENERAL],
        [_make_suggestion("Good result", score=0.85, doi="10.1/g")],
    )
    bad = _FakeProvider("Bad", [AcademicDomain.GENERAL], raise_on_search=True)
    registry = _registry_with([good, bad])
    engine = SuggestionEngine(registry=registry)

    sections = [_section("Topic")]
    outline = _outline(sections)
    matrix = _empty_matrix()

    report = asyncio.run(
        engine.analyze_and_suggest(
            outline=outline,
            evidence_matrix=matrix,
            claims=[],
            chunks=[],
            source_metadata=[],
            language="en",
        )
    )
    assert report.sections_with_suggestions == 1
    assert any("Bad" in err for err in report.errors)


def test_analyze_and_suggest_empty_outline() -> None:
    """``ArticleOutline`` schema enforces ``min_length=1`` on sections."""

    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        _outline([])


def test_analyze_and_suggest_all_sections_strong() -> None:
    fake = _FakeProvider(
        "PubMed",
        [AcademicDomain.MEDICAL, AcademicDomain.GENERAL],
        [_make_suggestion("X", score=0.9, doi="10.1/x")],
    )
    registry = _registry_with([fake])
    engine = SuggestionEngine(registry=registry)

    sections = [
        _section("Background"),
        _section("Discussion of Trade Trends", purpose="Discuss"),
    ]
    outline = _outline(sections)
    project_id = uuid4()
    matrix = _matrix_for_sections(
        project_id,
        {sections[0].id: 5, sections[1].id: 5},
    )
    matrix = matrix.model_copy(update={"project_id": project_id})

    report = asyncio.run(
        engine.analyze_and_suggest(
            outline=outline,
            evidence_matrix=matrix,
            claims=[],
            chunks=[],
            source_metadata=[],
            language="en",
        )
    )
    assert report.sections_with_suggestions == 0
    assert report.sections_skipped == 2


def test_analyze_reports_timing() -> None:
    fake = _FakeProvider(
        "PubMed",
        [AcademicDomain.MEDICAL, AcademicDomain.GENERAL],
        [_make_suggestion("X", score=0.9, doi="10.1/x")],
    )
    registry = _registry_with([fake])
    engine = SuggestionEngine(registry=registry)
    outline = _outline([_section("Topic")])

    report = asyncio.run(
        engine.analyze_and_suggest(
            outline=outline,
            evidence_matrix=_empty_matrix(),
            claims=[],
            chunks=[],
            source_metadata=[],
            language="en",
        )
    )
    assert report.search_time_ms > 0


def test_analyze_reports_providers_queried() -> None:
    a = _FakeProvider(
        "ProvA",
        [AcademicDomain.GENERAL],
        [_make_suggestion("A1", score=0.9, doi="10.1/a")],
    )
    b = _FakeProvider(
        "ProvB",
        [AcademicDomain.GENERAL],
        [_make_suggestion("B1", score=0.9, doi="10.1/b")],
    )
    registry = _registry_with([a, b])
    engine = SuggestionEngine(registry=registry)
    outline = _outline([_section("Niche topic")])

    report = asyncio.run(
        engine.analyze_and_suggest(
            outline=outline,
            evidence_matrix=_empty_matrix(),
            claims=[],
            chunks=[],
            source_metadata=[],
            language="en",
        )
    )
    assert "ProvA" in report.providers_queried
    assert "ProvB" in report.providers_queried


def test_analyze_caps_results_per_section() -> None:
    many = [_make_suggestion(f"S{i}", score=0.9, doi=f"10.1/{i}") for i in range(10)]
    fake = _FakeProvider("PubMed", [AcademicDomain.MEDICAL, AcademicDomain.GENERAL], many)
    registry = _registry_with([fake])
    engine = SuggestionEngine(registry=registry)
    outline = _outline([_section("Diabetes Care")])

    report = asyncio.run(
        engine.analyze_and_suggest(
            outline=outline,
            evidence_matrix=_empty_matrix(),
            claims=[],
            chunks=[],
            source_metadata=[],
            language="en",
        )
    )
    for section_sugg in report.section_suggestions:
        assert len(section_sugg.suggestions) <= SuggestionEngine.MAX_SUGGESTIONS_PER_SECTION


def test_analyze_skips_abstract_and_conclusion() -> None:
    fake = _FakeProvider(
        "PubMed",
        [AcademicDomain.MEDICAL, AcademicDomain.GENERAL],
        [_make_suggestion("Result", score=0.9, doi="10.1/x")],
    )
    registry = _registry_with([fake])
    engine = SuggestionEngine(registry=registry)
    outline = _outline(
        [
            _section("Abstract"),
            _section("Body"),
            _section("Conclusion"),
        ]
    )

    report = asyncio.run(
        engine.analyze_and_suggest(
            outline=outline,
            evidence_matrix=_empty_matrix(),
            claims=[],
            chunks=[],
            source_metadata=[],
            language="en",
        )
    )
    assert report.sections_skipped >= 2
