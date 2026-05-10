"""Behaviour tests for :class:`SuggestionQueryBuilder`.

The builder is pure — no I/O — so each test constructs a section
plus optional claims and pins one property of the emitted query
list (count cap, primary keyword extraction, stopword stripping,
trilingual translation, statistical-suffix path, length truncation).
"""

from __future__ import annotations

from uuid import uuid4

from packages.core.enums import ClaimStrength, ClaimType
from packages.core.models.article import OutlineSection
from packages.core.models.source import SourceClaimCreate
from packages.suggestions.query_builder import SuggestionQueryBuilder


def _section(
    title: str,
    thesis: str = "",
    purpose: str = "test",
) -> OutlineSection:
    return OutlineSection(
        title=title,
        target_words=400,
        purpose=purpose,
        section_thesis=thesis,
    )


def _claim(text: str, strength: ClaimStrength = ClaimStrength.MODERATE) -> SourceClaimCreate:
    return SourceClaimCreate(
        source_chunk_id=str(uuid4()),
        project_id=str(uuid4()),
        claim_text=text,
        strength=strength,
        claim_type=ClaimType.GENERAL_FACT,
    )


def test_build_from_section_title() -> None:
    builder = SuggestionQueryBuilder()
    section = _section("Environmental Regulation in Uzbekistan")
    queries = builder.build_queries(section, [], language="en")
    assert len(queries) >= 1
    primary = queries[0]
    assert "environmental" in primary
    assert "regulation" in primary
    assert "uzbekistan" in primary


def test_build_removes_uzbek_stopwords() -> None:
    builder = SuggestionQueryBuilder()
    section = _section("Iqtisodiyot va bozor bilan bo'lgan munosabatlar")
    queries = builder.build_queries(section, [], language="uz")
    primary = queries[0].split()
    assert "va" not in primary
    assert "bilan" not in primary
    assert "bu" not in primary


def test_build_removes_russian_stopwords() -> None:
    builder = SuggestionQueryBuilder()
    section = _section("Экономика и торговля в современном мире")
    queries = builder.build_queries(section, [], language="ru")
    primary = queries[0].split()
    assert "и" not in primary
    assert "в" not in primary


def test_build_translates_common_uzbek_terms() -> None:
    builder = SuggestionQueryBuilder()
    section = _section("Iqtisodiyot va savdo")
    queries = builder.build_queries(section, [], language="uz")
    primary = queries[0]
    assert "economics" in primary or "economic" in primary
    assert "trade" in primary


def test_build_translates_common_russian_terms() -> None:
    builder = SuggestionQueryBuilder()
    section = _section("Экономика страны")
    queries = builder.build_queries(section, [], language="ru")
    primary = queries[0]
    assert "economics" in primary or "economic" in primary


def test_build_empty_section_uses_title() -> None:
    builder = SuggestionQueryBuilder()
    section = _section("Renewable Energy", thesis="", purpose="t")
    queries = builder.build_queries(section, [], language="en")
    assert len(queries) >= 1
    assert "renewable" in queries[0]
    assert "energy" in queries[0]


def test_build_limits_query_length() -> None:
    builder = SuggestionQueryBuilder()
    long_thesis = "Carbon emissions trade global market policy " * 20
    section = _section("Climate Policy", thesis=long_thesis)
    queries = builder.build_queries(section, [], language="en")
    for q in queries:
        assert len(q) <= 100, f"query too long: {q}"


def test_build_returns_at_most_three_queries() -> None:
    builder = SuggestionQueryBuilder()
    section = _section(
        "Inflation Trends in Central Asia",
        thesis="Examines how inflation shapes household consumption in Uzbekistan",
    )
    claims = [
        _claim(
            "Annual inflation in Uzbekistan reached 12 percent in 2023.",
            ClaimStrength.STRONG,
        ),
    ]
    queries = builder.build_queries(section, claims, language="en", needs_statistical=True)
    assert len(queries) <= 3
    assert len(queries) >= 1


def test_build_returns_at_least_one_query() -> None:
    builder = SuggestionQueryBuilder()
    section = _section("X", purpose="t")
    queries = builder.build_queries(section, [], language="en")
    assert len(queries) >= 1


def test_build_uses_strong_claim_for_secondary_query() -> None:
    builder = SuggestionQueryBuilder()
    section = _section("Banking Reform", thesis="On the modernisation of Uzbek banking")
    weak = _claim("Some banks have updated their websites recently.", ClaimStrength.WEAK)
    strong = _claim(
        "Central Bank reform reduced lending costs and increased fintech adoption.",
        ClaimStrength.STRONG,
    )
    queries = builder.build_queries(section, [weak, strong], language="en")
    if len(queries) >= 2:
        secondary = queries[1]
        assert "central" in secondary or "bank" in secondary or "fintech" in secondary


def test_build_statistical_query_appends_data_keywords() -> None:
    builder = SuggestionQueryBuilder()
    section = _section("Health Expenditure Analysis", thesis="Per-capita spending trends")
    queries = builder.build_queries(section, [], language="en", needs_statistical=True)
    joined = " ".join(queries)
    assert "data" in joined or "statistics" in joined


def test_build_no_statistical_when_flag_off() -> None:
    builder = SuggestionQueryBuilder()
    section = _section("History of Modernism", thesis="Cultural shifts in 20th century art")
    queries = builder.build_queries(section, [], language="en", needs_statistical=False)
    joined = " ".join(queries)
    assert "statistics" not in joined


def test_build_query_lowercases_output() -> None:
    builder = SuggestionQueryBuilder()
    section = _section("MACHINE Learning Applications")
    queries = builder.build_queries(section, [], language="en")
    primary = queries[0]
    assert primary == primary.lower()


def test_build_dedupes_repeated_keywords() -> None:
    builder = SuggestionQueryBuilder()
    section = _section(
        "Economy Economy Economy",
        thesis="Economy Economy Economy",
    )
    queries = builder.build_queries(section, [], language="en")
    tokens = queries[0].split()
    assert tokens.count("economy") == 1
