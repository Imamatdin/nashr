"""Tests for :class:`BibliographyFormatter`.

The formatter is fully deterministic (no LLM, no async, no I/O), so
every test asserts on exact substrings of the rendered output. The
rules under test are the literal style rules in
``packages/workers/article/bibliography.py`` — author abbreviation,
locator punctuation, no-year fallbacks, ordering, and per-source-type
templates.
"""

from __future__ import annotations

import pytest

from packages.core.enums import CitationFormat, SourceType
from packages.core.models.academic import DOIMetadata
from packages.core.models.bibliography import (
    CitationMetadata,
    FormattedBibliography,
)
from packages.core.models.source import SourceMetadataExtracted
from packages.workers.article.bibliography import (
    BibliographyFormatter,
    format_author_apa,
    format_author_chicago_bib,
    format_author_chicago_footnote,
    format_author_gost,
    format_author_ieee,
    format_author_vancouver,
    source_to_citation_metadata,
)

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _journal_meta(**overrides: object) -> CitationMetadata:
    base: dict[str, object] = {
        "title": "Passive radiative cooling below ambient air temperature under direct sunlight",
        "authors": ["Raman, Aaswath P."],
        "year": 2014,
        "journal": "Nature",
        "volume": "515",
        "pages": "540-544",
        "source_type": SourceType.JOURNAL_ARTICLE,
        "citation_number": 1,
    }
    base.update(overrides)
    return CitationMetadata(**base)  # type: ignore[arg-type]


def _book_meta(**overrides: object) -> CitationMetadata:
    base: dict[str, object] = {
        "title": "Foundations of Modern Optics",
        "authors": ["Smith, John A."],
        "year": 2020,
        "city": "Cambridge",
        "publisher": "Cambridge University Press",
        "total_pages": 320,
        "source_type": SourceType.BOOK,
        "citation_number": 1,
    }
    base.update(overrides)
    return CitationMetadata(**base)  # type: ignore[arg-type]


def _web_meta(**overrides: object) -> CitationMetadata:
    base: dict[str, object] = {
        "title": "Climate Adaptation Strategies",
        "authors": ["Doe, Jane"],
        "year": 2023,
        "url": "https://example.org/climate",
        "access_date": "10.05.2026",
        "source_type": SourceType.WEB_PAGE,
        "citation_number": 1,
    }
    base.update(overrides)
    return CitationMetadata(**base)  # type: ignore[arg-type]


def _conference_meta(**overrides: object) -> CitationMetadata:
    base: dict[str, object] = {
        "title": "A Reinforcement Learning Approach",
        "authors": ["Brown, Alice"],
        "year": 2022,
        "journal": "Proc. ICML",
        "city": "Vienna",
        "pages": "120-130",
        "source_type": SourceType.CONFERENCE_PAPER,
        "citation_number": 1,
    }
    base.update(overrides)
    return CitationMetadata(**base)  # type: ignore[arg-type]


def _dissertation_meta(**overrides: object) -> CitationMetadata:
    base: dict[str, object] = {
        "title": "Theoretical Aspects of Quantum Field Theory",
        "authors": ["Green, Robert"],
        "year": 2018,
        "city": "Tashkent",
        "total_pages": 220,
        "source_type": SourceType.DISSERTATION,
        "citation_number": 1,
    }
    base.update(overrides)
    return CitationMetadata(**base)  # type: ignore[arg-type]


@pytest.fixture
def formatter() -> BibliographyFormatter:
    return BibliographyFormatter()


# ---------------------------------------------------------------------------
# GOST
# ---------------------------------------------------------------------------


def test_gost_journal_article(formatter: BibliographyFormatter) -> None:
    meta = _journal_meta(authors=["Raman, Aaswath P."])
    out = formatter.format_single_reference(meta, CitationFormat.GOST, number=1, language="ru")
    for needle in ("Raman A.P.", "//", "Nature", "2014", "Т. 515", "С. 540-544"):
        assert needle in out, f"missing {needle!r} in {out!r}"


def test_gost_book(formatter: BibliographyFormatter) -> None:
    meta = _book_meta()
    out = formatter.format_single_reference(meta, CitationFormat.GOST, number=1, language="ru")
    assert "—" in out
    assert "Cambridge" in out
    assert "Cambridge University Press" in out
    assert "2020" in out
    assert "с." in out


def test_gost_multi_author_three(formatter: BibliographyFormatter) -> None:
    meta = _journal_meta(
        authors=["Raman, Aaswath P.", "Anoma, Marc Abou", "Zhu, Linxiao"],
    )
    out = formatter.format_single_reference(meta, CitationFormat.GOST, number=1, language="ru")
    assert "Raman A.P." in out
    assert "Anoma M.A." in out
    assert "Zhu L." in out
    assert "и др." not in out


def test_gost_multi_author_four_plus_russian(formatter: BibliographyFormatter) -> None:
    meta = _journal_meta(
        authors=["Raman, Aaswath P.", "Anoma, Marc Abou", "Zhu, Linxiao", "Fan, Shanhui"],
    )
    out = formatter.format_single_reference(meta, CitationFormat.GOST, number=1, language="ru")
    assert "Raman A.P." in out
    assert "и др." in out
    assert "Anoma" not in out


def test_gost_multi_author_four_plus_uzbek(formatter: BibliographyFormatter) -> None:
    meta = _journal_meta(
        authors=["Raman, Aaswath P.", "Anoma, Marc Abou", "Zhu, Linxiao", "Fan, Shanhui"],
    )
    out = formatter.format_single_reference(meta, CitationFormat.GOST, number=1, language="uz")
    assert "Raman A.P." in out
    assert "va boshq." in out


def test_gost_web_source(formatter: BibliographyFormatter) -> None:
    meta = _web_meta()
    out = formatter.format_single_reference(meta, CitationFormat.GOST, number=1, language="ru")
    assert "[Электронный ресурс]" in out
    assert "URL:" in out
    assert "https://example.org/climate" in out
    assert "дата обращения:" in out
    assert "10.05.2026" in out


def test_gost_with_doi(formatter: BibliographyFormatter) -> None:
    meta = _journal_meta(doi="10.1038/nature13883")
    out = formatter.format_single_reference(meta, CitationFormat.GOST, number=1, language="ru")
    assert "10.1038/nature13883" in out


def test_gost_ordering_by_appearance(formatter: BibliographyFormatter) -> None:
    metas = [
        _journal_meta(citation_number=n, title=f"Paper {n}", authors=[f"Author{n}, A."])
        for n in (3, 1, 5, 2, 4)
    ]
    bib = formatter.format_bibliography(metas, CitationFormat.GOST, language="ru")
    numbers = [entry.number for entry in bib.entries]
    assert numbers == [1, 2, 3, 4, 5]


def test_gost_inline_citation(formatter: BibliographyFormatter) -> None:
    meta = _journal_meta()
    assert formatter.format_inline_citation(1, meta, CitationFormat.GOST) == "[1]"


def test_gost_inline_citation_with_page_russian(formatter: BibliographyFormatter) -> None:
    meta = _journal_meta()
    out = formatter.format_inline_citation(1, meta, CitationFormat.GOST, page=45, language="ru")
    assert out == "[1, с. 45]"


def test_gost_inline_citation_with_page_uzbek(formatter: BibliographyFormatter) -> None:
    meta = _journal_meta()
    out = formatter.format_inline_citation(1, meta, CitationFormat.GOST, page=45, language="uz")
    assert out == "[1, b. 45]"


def test_gost_inline_citation_with_page_english(formatter: BibliographyFormatter) -> None:
    meta = _journal_meta()
    out = formatter.format_inline_citation(1, meta, CitationFormat.GOST, page=45, language="en")
    assert out == "[1, p. 45]"


def test_gost_no_year_uses_b_g_marker(formatter: BibliographyFormatter) -> None:
    meta = _book_meta(year=None)
    out = formatter.format_single_reference(meta, CitationFormat.GOST, number=1, language="ru")
    assert "[б.г.]" in out


def test_gost_conference_paper(formatter: BibliographyFormatter) -> None:
    meta = _conference_meta()
    out = formatter.format_single_reference(meta, CitationFormat.GOST, number=1, language="ru")
    assert "Brown A." in out
    assert "Proc. ICML" in out
    assert "Vienna" in out
    assert "С. 120-130" in out


def test_gost_dissertation(formatter: BibliographyFormatter) -> None:
    meta = _dissertation_meta()
    out = formatter.format_single_reference(meta, CitationFormat.GOST, number=1, language="ru")
    assert "Green R." in out
    assert "дис." in out
    assert "Tashkent" in out
    assert "220" in out


# ---------------------------------------------------------------------------
# APA
# ---------------------------------------------------------------------------


def test_apa_journal_article(formatter: BibliographyFormatter) -> None:
    meta = _journal_meta(
        authors=["Raman, Aaswath P."],
        doi="10.1038/nature13883",
    )
    out = formatter.format_single_reference(meta, CitationFormat.APA)
    assert "Raman, A. P." in out
    assert "(2014)" in out
    assert "Nature" in out
    assert "515" in out
    assert "540-544" in out
    assert "https://doi.org/10.1038/nature13883" in out


def test_apa_book(formatter: BibliographyFormatter) -> None:
    meta = _book_meta()
    out = formatter.format_single_reference(meta, CitationFormat.APA)
    assert "Smith, J. A." in out
    assert "(2020)" in out
    assert "Foundations of Modern Optics" in out
    assert "Cambridge University Press" in out


def test_apa_two_authors(formatter: BibliographyFormatter) -> None:
    meta = _journal_meta(authors=["Smith, John A.", "Jones, Mary B."])
    out = formatter.format_single_reference(meta, CitationFormat.APA)
    assert "Smith, J. A., & Jones, M. B." in out


def test_apa_three_plus_authors_bibliography_lists_all(formatter: BibliographyFormatter) -> None:
    meta = _journal_meta(
        authors=["Smith, John", "Jones, Mary", "Brown, Alice", "White, Bob"],
    )
    out = formatter.format_single_reference(meta, CitationFormat.APA)
    assert "Smith, J." in out
    assert "Jones, M." in out
    assert "Brown, A." in out
    assert "White, B." in out
    assert "& White, B." in out


def test_apa_inline_three_plus_uses_et_al(formatter: BibliographyFormatter) -> None:
    meta = _journal_meta(authors=["Smith, John", "Jones, Mary", "Brown, Alice"])
    out = formatter.format_inline_citation(1, meta, CitationFormat.APA)
    assert out == "(Smith et al., 2014)"


def test_apa_no_year(formatter: BibliographyFormatter) -> None:
    meta = _journal_meta(year=None)
    out = formatter.format_single_reference(meta, CitationFormat.APA)
    assert "(n.d.)" in out


def test_apa_ordering_alphabetical(formatter: BibliographyFormatter) -> None:
    metas = [
        _journal_meta(citation_number=1, title="Paper 1", authors=["Yu, Yan"]),
        _journal_meta(citation_number=2, title="Paper 2", authors=["Adams, Ada"]),
        _journal_meta(citation_number=3, title="Paper 3", authors=["Mendel, Max"]),
    ]
    bib = formatter.format_bibliography(metas, CitationFormat.APA)
    surnames_in_order = [entry.formatted_text.split(",")[0] for entry in bib.entries]
    assert surnames_in_order == ["Adams", "Mendel", "Yu"]


def test_apa_inline_single_author(formatter: BibliographyFormatter) -> None:
    meta = _journal_meta(authors=["Smith, John"])
    assert formatter.format_inline_citation(1, meta, CitationFormat.APA) == "(Smith, 2014)"


def test_apa_inline_two_authors(formatter: BibliographyFormatter) -> None:
    meta = _journal_meta(authors=["Smith, John", "Jones, Mary"])
    assert formatter.format_inline_citation(1, meta, CitationFormat.APA) == "(Smith & Jones, 2014)"


def test_apa_doi_formatted_as_url(formatter: BibliographyFormatter) -> None:
    meta = _journal_meta(doi="10.1038/nature12373")
    out = formatter.format_single_reference(meta, CitationFormat.APA)
    assert "https://doi.org/10.1038/nature12373" in out


# ---------------------------------------------------------------------------
# IEEE
# ---------------------------------------------------------------------------


def test_ieee_journal_article(formatter: BibliographyFormatter) -> None:
    meta = _journal_meta(authors=["Raman, Aaswath P."])
    out = formatter.format_single_reference(meta, CitationFormat.IEEE, number=1)
    assert out.startswith("[1] ")
    assert "A. P. Raman" in out
    assert '"Passive radiative cooling' in out
    assert "Nature" in out
    assert "vol. 515" in out
    assert "pp. 540-544" in out
    assert "2014" in out


def test_ieee_initials_before_surname(formatter: BibliographyFormatter) -> None:
    meta = _journal_meta(authors=["Raman, Aaswath P."])
    out = formatter.format_single_reference(meta, CitationFormat.IEEE, number=1)
    assert "A. P. Raman" in out
    assert "Raman, A. P." not in out


def test_ieee_article_title_in_quotes(formatter: BibliographyFormatter) -> None:
    meta = _journal_meta()
    out = formatter.format_single_reference(meta, CitationFormat.IEEE, number=1)
    assert '"Passive radiative cooling below ambient air temperature under direct sunlight,"' in out


def test_ieee_ordering_by_appearance(formatter: BibliographyFormatter) -> None:
    metas = [
        _journal_meta(citation_number=n, title=f"Paper {n}", authors=[f"Author{n}, A."])
        for n in (4, 2, 1, 3)
    ]
    bib = formatter.format_bibliography(metas, CitationFormat.IEEE)
    numbers = [entry.number for entry in bib.entries]
    assert numbers == [1, 2, 3, 4]


def test_ieee_inline(formatter: BibliographyFormatter) -> None:
    meta = _journal_meta()
    assert formatter.format_inline_citation(7, meta, CitationFormat.IEEE) == "[7]"


# ---------------------------------------------------------------------------
# Chicago
# ---------------------------------------------------------------------------


def test_chicago_footnote_first_occurrence(formatter: BibliographyFormatter) -> None:
    meta = _book_meta()
    out = formatter.format_chicago_footnote(meta, page=45, first_occurrence=True, number=1)
    assert out.startswith("¹ ")
    assert "John A. Smith" in out
    assert "Foundations of Modern Optics" in out
    assert "Cambridge: Cambridge University Press, 2020" in out
    assert out.rstrip().endswith("45.")


def test_chicago_footnote_subsequent(formatter: BibliographyFormatter) -> None:
    meta = _book_meta()
    out = formatter.format_chicago_footnote(meta, page=72, first_occurrence=False, number=2)
    assert out.startswith("² ")
    assert "Smith" in out
    assert "Foundations of Modern Optics" in out
    assert "John A." not in out  # shortened — first name dropped
    assert out.rstrip().endswith("72.")


def test_chicago_bibliography_entry(formatter: BibliographyFormatter) -> None:
    meta = _book_meta()
    out = formatter.format_single_reference(meta, CitationFormat.CHICAGO)
    assert "Smith, John A." in out
    assert "Foundations of Modern Optics." in out
    assert "Cambridge: Cambridge University Press, 2020." in out


def test_chicago_inline_is_superscript_number(formatter: BibliographyFormatter) -> None:
    meta = _book_meta()
    assert formatter.format_inline_citation(3, meta, CitationFormat.CHICAGO) == "³"
    assert formatter.format_inline_citation(12, meta, CitationFormat.CHICAGO) == "¹²"


# ---------------------------------------------------------------------------
# Vancouver
# ---------------------------------------------------------------------------


def test_vancouver_journal_article(formatter: BibliographyFormatter) -> None:
    meta = _journal_meta(authors=["Raman, Aaswath P."])
    out = formatter.format_single_reference(meta, CitationFormat.VANCOUVER, number=1)
    assert out.startswith("1. ")
    assert "Raman AP" in out
    assert "Nature" in out
    assert "2014;515:540-544" in out


def test_vancouver_no_periods_in_initials(formatter: BibliographyFormatter) -> None:
    meta = _journal_meta(authors=["Raman, Aaswath P."])
    out = formatter.format_single_reference(meta, CitationFormat.VANCOUVER, number=1)
    assert "Raman AP" in out
    assert "A.P." not in out


def test_vancouver_six_authors_listed(formatter: BibliographyFormatter) -> None:
    authors = [f"Author{i}, A." for i in range(1, 7)]
    meta = _journal_meta(authors=authors)
    out = formatter.format_single_reference(meta, CitationFormat.VANCOUVER, number=1)
    for n in range(1, 7):
        assert f"Author{n} A" in out
    assert "et al." not in out


def test_vancouver_seven_plus_et_al(formatter: BibliographyFormatter) -> None:
    authors = [f"Author{i}, A." for i in range(1, 8)]
    meta = _journal_meta(authors=authors)
    out = formatter.format_single_reference(meta, CitationFormat.VANCOUVER, number=1)
    for n in range(1, 7):
        assert f"Author{n} A" in out
    assert "Author7 A" not in out
    assert "et al." in out


# ---------------------------------------------------------------------------
# Author formatting helpers
# ---------------------------------------------------------------------------


def test_format_author_single_name_all_styles() -> None:
    assert format_author_gost("Voltaire") == "Voltaire"
    assert format_author_apa("Voltaire") == "Voltaire"
    assert format_author_ieee("Voltaire") == "Voltaire"
    assert format_author_chicago_bib("Voltaire") == "Voltaire"
    assert format_author_chicago_footnote("Voltaire") == "Voltaire"
    assert format_author_vancouver("Voltaire") == "Voltaire"


def test_format_author_organization_all_styles() -> None:
    org = "World Health Organization"
    assert format_author_gost(org) == org
    assert format_author_apa(org) == org
    assert format_author_ieee(org) == org
    assert format_author_chicago_bib(org) == org
    assert format_author_vancouver(org) == org


def test_format_author_empty_list_uses_title(formatter: BibliographyFormatter) -> None:
    meta = _book_meta(authors=[])
    out = formatter.format_single_reference(meta, CitationFormat.APA)
    assert out.startswith("Foundations of Modern Optics.")


def test_format_author_with_particle_gost() -> None:
    assert format_author_gost("van der Berg, Jan") == "van der Berg J."


def test_format_author_with_particle_apa() -> None:
    assert format_author_apa("van der Berg, Jan") == "van der Berg, J."


def test_format_author_with_particle_ieee() -> None:
    assert format_author_ieee("van der Berg, Jan") == "J. van der Berg"


def test_format_author_with_particle_vancouver() -> None:
    assert format_author_vancouver("van der Berg, Jan") == "van der Berg J"


# ---------------------------------------------------------------------------
# Metadata conversion
# ---------------------------------------------------------------------------


def test_source_to_citation_metadata_basic() -> None:
    src = SourceMetadataExtracted(
        title="Title from PDF",
        authors=["Smith, John"],
        year=2020,
        doi=None,
        page_count=120,
        word_count=42_000,
    )
    meta = source_to_citation_metadata(src, doi_meta=None)
    assert meta.title == "Title from PDF"
    assert meta.authors == ["Smith, John"]
    assert meta.year == 2020
    assert meta.total_pages == 120


def test_source_to_citation_metadata_with_doi_enrichment() -> None:
    src = SourceMetadataExtracted(
        title="Old PDF Title",
        authors=["Smith, John"],
        year=2019,
        doi="10.1038/x",
        page_count=10,
    )
    doi_meta = DOIMetadata(
        doi="10.1038/x",
        title="Canonical Title from CrossRef",
        authors=["Smith, John A.", "Jones, Mary B."],
        year=2020,
        journal="Nature",
        volume="515",
        issue="7528",
        pages="540-544",
        publisher="Springer Nature",
    )
    meta = source_to_citation_metadata(src, doi_meta=doi_meta)
    assert meta.title == "Canonical Title from CrossRef"
    assert meta.authors == ["Smith, John A.", "Jones, Mary B."]
    assert meta.year == 2020
    assert meta.journal == "Nature"
    assert meta.volume == "515"
    assert meta.pages == "540-544"


def test_source_to_citation_metadata_doi_only() -> None:
    src = SourceMetadataExtracted(title=None, authors=[], year=None)
    doi_meta = DOIMetadata(
        doi="10.1038/y",
        title="DOI-Only Title",
        authors=["Brown, Alice"],
        year=2021,
        journal="Science",
        volume="372",
        pages="100-110",
    )
    meta = source_to_citation_metadata(src, doi_meta=doi_meta)
    assert meta.title == "DOI-Only Title"
    assert meta.authors == ["Brown, Alice"]
    assert meta.year == 2021
    assert meta.journal == "Science"


def test_source_to_citation_metadata_no_authors() -> None:
    src = SourceMetadataExtracted(title="A Lone Title", authors=[], year=2024)
    meta = source_to_citation_metadata(src, doi_meta=None)
    assert meta.authors == []
    assert meta.title == "A Lone Title"


@pytest.mark.parametrize(
    ("doc_type", "expected"),
    [
        ("journal-article", SourceType.JOURNAL_ARTICLE),
        ("book", SourceType.BOOK),
        ("book-chapter", SourceType.BOOK_CHAPTER),
        ("proceedings-article", SourceType.CONFERENCE_PAPER),
        ("dissertation", SourceType.DISSERTATION),
        ("report", SourceType.REPORT),
        ("dataset", SourceType.DATASET),
        ("unknown-type", SourceType.JOURNAL_ARTICLE),
    ],
)
def test_source_to_citation_metadata_infers_type_from_doi(
    doc_type: str, expected: SourceType
) -> None:
    src = SourceMetadataExtracted(title=None, authors=[], year=None)
    doi_meta = DOIMetadata(
        doi="10.0/test",
        title="Test",
        authors=["Author, A."],
        year=2024,
        doc_type=doc_type,
    )
    meta = source_to_citation_metadata(src, doi_meta=doi_meta)
    assert meta.source_type is expected


# ---------------------------------------------------------------------------
# Full bibliography
# ---------------------------------------------------------------------------


def test_full_bibliography_gost_five_sources(formatter: BibliographyFormatter) -> None:
    sources = [
        _journal_meta(citation_number=1, title="A1", authors=["A, A."]),
        _book_meta(citation_number=2, title="B1", authors=["B, B."]),
        _web_meta(citation_number=3, title="W1", authors=["C, C."]),
        _conference_meta(citation_number=4, title="C1", authors=["D, D."]),
        _dissertation_meta(citation_number=5, title="D1", authors=["E, E."]),
    ]
    bib = formatter.format_bibliography(sources, CitationFormat.GOST, language="ru")
    assert bib.style is CitationFormat.GOST
    assert bib.total_entries == 5
    assert len(bib.entries) == 5
    assert [entry.number for entry in bib.entries] == [1, 2, 3, 4, 5]


def test_full_bibliography_apa_five_sources_alphabetical(
    formatter: BibliographyFormatter,
) -> None:
    sources = [
        _journal_meta(citation_number=1, title="A1", authors=["Yu, Y."]),
        _book_meta(citation_number=2, title="B1", authors=["Adams, A."]),
        _web_meta(citation_number=3, title="W1", authors=["Mendel, M."]),
        _conference_meta(citation_number=4, title="C1", authors=["Brown, B."]),
        _dissertation_meta(citation_number=5, title="D1", authors=["Park, P."]),
    ]
    bib = formatter.format_bibliography(sources, CitationFormat.APA)
    surnames = [entry.formatted_text.split(",")[0] for entry in bib.entries]
    assert surnames == ["Adams", "Brown", "Mendel", "Park", "Yu"]
    for entry in bib.entries:
        assert entry.number is None  # APA is unnumbered


def test_full_bibliography_model_roundtrip(formatter: BibliographyFormatter) -> None:
    sources = [_journal_meta(citation_number=1)]
    bib = formatter.format_bibliography(sources, CitationFormat.GOST, language="ru")
    dumped = bib.model_dump()
    rebuilt = FormattedBibliography.model_validate(dumped)
    assert rebuilt == bib


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_missing_year_handled_gracefully_apa(formatter: BibliographyFormatter) -> None:
    meta = _journal_meta(year=None)
    assert "(n.d.)" in formatter.format_single_reference(meta, CitationFormat.APA)


def test_missing_year_handled_gracefully_gost(formatter: BibliographyFormatter) -> None:
    meta = _journal_meta(year=None)
    out = formatter.format_single_reference(meta, CitationFormat.GOST, number=1, language="ru")
    assert "[б.г.]" in out


def test_missing_year_handled_gracefully_ieee(formatter: BibliographyFormatter) -> None:
    meta = _journal_meta(year=None)
    out = formatter.format_single_reference(meta, CitationFormat.IEEE, number=1)
    assert "n.d." in out


def test_missing_journal_handled(formatter: BibliographyFormatter) -> None:
    meta = _journal_meta(journal=None)
    out = formatter.format_single_reference(meta, CitationFormat.APA)
    assert "Raman, A. P." in out
    assert "(2014)" in out


def test_very_long_title_preserved(formatter: BibliographyFormatter) -> None:
    # CitationMetadata caps title at 500 chars; we use the largest valid value
    # to confirm the formatter does not truncate within its allowed range.
    long_title = "A " * 240 + "study"
    assert len(long_title) <= 500
    meta = _journal_meta(title=long_title)
    out = formatter.format_single_reference(meta, CitationFormat.APA)
    assert long_title in out


def test_unicode_cyrillic_authors_in_gost(formatter: BibliographyFormatter) -> None:
    meta = _journal_meta(authors=["Иванов, Иван Иванович"])
    out = formatter.format_single_reference(meta, CitationFormat.GOST, number=1, language="ru")
    assert "Иванов И.И." in out


def test_unicode_uzbek_authors_in_gost(formatter: BibliographyFormatter) -> None:
    meta = _journal_meta(authors=["Sultoniyozov, Imamatdin"])
    out = formatter.format_single_reference(meta, CitationFormat.GOST, number=1, language="uz")
    assert "Sultoniyozov I." in out
