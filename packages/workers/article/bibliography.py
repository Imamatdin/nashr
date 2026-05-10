"""Bibliography formatter for the article worker.

Pure-deterministic string formatting: takes a list of
:class:`CitationMetadata` and a :class:`CitationFormat`, returns a
:class:`FormattedBibliography`. No LLM calls, no async. The DOCX exporter
consumes the rendered entries directly.

The 300-line CLAUDE.md budget is exceeded here because five academic
styles (GOST, APA, IEEE, Chicago, Vancouver) each need per-source-type
rendering (journal article, book, conference paper, dissertation, web
page) plus per-style author formatting. Splitting across files would
fragment the per-style logic so readers cannot compare two styles
side-by-side; the module is intentionally consolidated and dispatched
through a single :class:`BibliographyFormatter` facade.
"""

from __future__ import annotations

from typing import Final

from packages.core.enums import CitationFormat, SourceType
from packages.core.models.academic import DOIMetadata
from packages.core.models.bibliography import (
    CitationMetadata,
    FormattedBibliography,
    FormattedEntry,
)
from packages.core.models.source import SourceMetadataExtracted

_NO_YEAR_GOST_RU: Final[str] = "[б.г.]"
_NO_YEAR_GOST_EN: Final[str] = "[n.d.]"
_NO_YEAR_APA: Final[str] = "n.d."
_NO_YEAR_IEEE: Final[str] = "n.d."

_GOST_LABELS: Final[dict[str, dict[str, str]]] = {
    "ru": {
        "et_al": "и др.",
        "page": "с.",
        "page_range": "С.",
        "volume": "Т.",
        "issue": "№",
        "electronic": "[Электронный ресурс]",
        "url": "URL:",
        "access": "дата обращения:",
        "diss": "дис. ... канд. наук",
        "no_year": _NO_YEAR_GOST_RU,
    },
    "uz": {
        "et_al": "va boshq.",
        "page": "b.",
        "page_range": "B.",
        "volume": "T.",
        "issue": "№",
        "electronic": "[Elektron resurs]",
        "url": "URL:",
        "access": "murojaat sanasi:",
        "diss": "diss. ... fan nomzodi",
        "no_year": _NO_YEAR_GOST_RU,
    },
    "en": {
        "et_al": "et al.",
        "page": "p.",
        "page_range": "pp.",
        "volume": "vol.",
        "issue": "no.",
        "electronic": "[Electronic resource]",
        "url": "URL:",
        "access": "accessed:",
        "diss": "PhD diss.",
        "no_year": _NO_YEAR_GOST_EN,
    },
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


class BibliographyFormatter:
    """Deterministic citation/bibliography formatter for five academic styles.

    Stateless — every call is a pure function of its arguments. The class
    exists only to give callers a single dispatcher object instead of
    forcing them to learn the module-level helpers.
    """

    def format_bibliography(
        self,
        citations: list[CitationMetadata],
        style: CitationFormat,
        language: str = "en",
    ) -> FormattedBibliography:
        """Render a complete bibliography.

        Numbered styles (GOST, IEEE, Vancouver) use ``citation_number``
        from each metadata to order entries; alphabetical styles (APA,
        Chicago) sort by the first author's surname (or by title when
        no authors are listed).
        """

        ordered = _order_citations(citations, style)
        entries: list[FormattedEntry] = []
        for index, meta in enumerate(ordered, start=1):
            number = meta.citation_number or index
            text = self.format_single_reference(meta, style, number=number, language=language)
            entries.append(
                FormattedEntry(
                    number=number if _is_numbered(style) else None,
                    formatted_text=text,
                    source_id=meta.source_id,
                    doi=meta.doi,
                )
            )
        return FormattedBibliography(
            entries=entries,
            style=style,
            language=language,
            total_entries=len(entries),
        )

    def format_inline_citation(
        self,
        citation_number: int,
        metadata: CitationMetadata,
        style: CitationFormat,
        page: int | None = None,
        language: str = "en",
    ) -> str:
        """Render the marker that appears in the article body.

        ``language`` only affects GOST (page-marker label: ``с.``, ``b.``,
        ``p.``); the other styles ignore it. The default matches
        :meth:`format_bibliography` and :meth:`format_single_reference`
        so callers do not have to remember which method threads the
        language and which does not.
        """

        if style is CitationFormat.GOST:
            return _gost_inline(citation_number, page, _lang_or_default(language))
        if style is CitationFormat.IEEE:
            return f"[{citation_number}]"
        if style is CitationFormat.VANCOUVER:
            return f"({citation_number})"
        if style is CitationFormat.CHICAGO:
            return _superscript(citation_number)
        return _apa_inline(metadata, page)

    def format_single_reference(
        self,
        metadata: CitationMetadata,
        style: CitationFormat,
        number: int | None = None,
        language: str = "en",
    ) -> str:
        """Render one bibliography entry."""

        if style is CitationFormat.GOST:
            return _format_gost(metadata, language)
        if style is CitationFormat.APA:
            return _format_apa(metadata)
        if style is CitationFormat.IEEE:
            return _format_ieee(metadata, number)
        if style is CitationFormat.CHICAGO:
            return _format_chicago_bibliography(metadata)
        return _format_vancouver(metadata, number)

    def format_chicago_footnote(
        self,
        metadata: CitationMetadata,
        page: int | None = None,
        first_occurrence: bool = True,
        number: int = 1,
    ) -> str:
        """Render a Chicago-style footnote (first occurrence or shortened)."""

        marker = _superscript(number)
        if first_occurrence:
            body = _chicago_footnote_full(metadata, page)
        else:
            body = _chicago_footnote_short(metadata, page)
        return f"{marker} {body}"


# ---------------------------------------------------------------------------
# Inline-citation helpers
# ---------------------------------------------------------------------------


def _gost_inline(number: int, page: int | None, language: str) -> str:
    if page is None:
        return f"[{number}]"
    label = _GOST_LABELS[language]["page"]
    return f"[{number}, {label} {page}]"


def _apa_inline(metadata: CitationMetadata, page: int | None) -> str:
    year = metadata.year if metadata.year is not None else _NO_YEAR_APA
    surnames = _apa_inline_surnames(metadata.authors)
    suffix = f", p. {page}" if page is not None else ""
    if surnames:
        return f"({surnames}, {year}{suffix})"
    return f"({_short_title(metadata.title)}, {year}{suffix})"


def _apa_inline_surnames(authors: list[str]) -> str:
    if not authors:
        return ""
    surnames = [_split_name(a)[0] for a in authors]
    if len(surnames) == 1:
        return surnames[0]
    if len(surnames) == 2:
        return f"{surnames[0]} & {surnames[1]}"
    return f"{surnames[0]} et al."


_SUPERSCRIPT_DIGITS: Final[dict[str, str]] = {
    "0": "⁰",
    "1": "¹",
    "2": "²",
    "3": "³",
    "4": "⁴",
    "5": "⁵",
    "6": "⁶",
    "7": "⁷",
    "8": "⁸",
    "9": "⁹",
}


def _superscript(number: int) -> str:
    return "".join(_SUPERSCRIPT_DIGITS[d] for d in str(number))


# ---------------------------------------------------------------------------
# Author parsing / formatting
# ---------------------------------------------------------------------------


def _split_name(name: str) -> tuple[str, str | None]:
    """Split ``"Last, First A."`` into ``("Last", "First A.")``.

    Single-name authors and organisations have no comma, so we return
    ``(name, None)`` and every per-style helper short-circuits to
    output the name verbatim.
    """

    if "," not in name:
        return (name.strip(), None)
    last, _, first = name.partition(",")
    last = last.strip()
    first = first.strip()
    if not first:
        return (last, None)
    return (last, first)


def _initials_with_dots(first: str) -> str:
    """``"John A."`` → ``"J. A."``"""

    parts = first.replace(".", "").split()
    return " ".join(f"{p[0]}." for p in parts if p)


def _initials_compact(first: str) -> str:
    """``"John A."`` → ``"J.A."``"""

    parts = first.replace(".", "").split()
    return "".join(f"{p[0]}." for p in parts if p)


def _initials_no_dots(first: str) -> str:
    """``"John A."`` → ``"JA"``"""

    parts = first.replace(".", "").split()
    return "".join(p[0] for p in parts if p)


def format_author_gost(name: str) -> str:
    """``"Smith, John A."`` → ``"Smith J.A."`` (GOST: surname + compact initials)."""

    last, first = _split_name(name)
    if first is None:
        return last
    return f"{last} {_initials_compact(first)}"


def format_author_apa(name: str) -> str:
    """``"Smith, John A."`` → ``"Smith, J. A."`` (APA: surname, comma, spaced initials)."""

    last, first = _split_name(name)
    if first is None:
        return last
    return f"{last}, {_initials_with_dots(first)}"


def format_author_ieee(name: str) -> str:
    """``"Smith, John A."`` → ``"J. A. Smith"`` (IEEE: initials precede surname)."""

    last, first = _split_name(name)
    if first is None:
        return last
    return f"{_initials_with_dots(first)} {last}"


def format_author_chicago_footnote(name: str) -> str:
    """``"Smith, John A."`` → ``"John A. Smith"`` (Chicago footnote: full given name first)."""

    last, first = _split_name(name)
    if first is None:
        return last
    return f"{first} {last}"


def format_author_chicago_bib(name: str) -> str:
    """``"Smith, John A."`` → ``"Smith, John A."`` (Chicago bibliography: inverted full name)."""

    last, first = _split_name(name)
    if first is None:
        return last
    return f"{last}, {first}"


def format_author_vancouver(name: str) -> str:
    """``"Smith, John A."`` → ``"Smith JA"`` (Vancouver: surname + initials, no spaces or dots)."""

    last, first = _split_name(name)
    if first is None:
        return last
    return f"{last} {_initials_no_dots(first)}"


# ---------------------------------------------------------------------------
# Author-list formatting (per-style truncation rules)
# ---------------------------------------------------------------------------


def _gost_author_list(authors: list[str], language: str) -> str:
    if not authors:
        return ""
    label = _GOST_LABELS[language]["et_al"]
    if len(authors) >= 4:
        return f"{format_author_gost(authors[0])} {label}"
    return ", ".join(format_author_gost(a) for a in authors)


def _apa_author_list(authors: list[str]) -> str:
    if not authors:
        return ""
    formatted = [format_author_apa(a) for a in authors]
    if len(formatted) == 1:
        return formatted[0]
    if len(formatted) == 2:
        return f"{formatted[0]}, & {formatted[1]}"
    if len(formatted) <= 20:
        return ", ".join(formatted[:-1]) + f", & {formatted[-1]}"
    truncated = [*formatted[:19], "...", formatted[-1]]
    return ", ".join(truncated)


def _ieee_author_list(authors: list[str]) -> str:
    if not authors:
        return ""
    formatted = [format_author_ieee(a) for a in authors]
    if len(formatted) == 1:
        return formatted[0]
    if len(formatted) == 2:
        return f"{formatted[0]} and {formatted[1]}"
    if len(formatted) <= 6:
        return ", ".join(formatted[:-1]) + f", and {formatted[-1]}"
    return f"{formatted[0]} et al."


def _vancouver_author_list(authors: list[str]) -> str:
    if not authors:
        return ""
    formatted = [format_author_vancouver(a) for a in authors]
    if len(formatted) > 6:
        return ", ".join(formatted[:6]) + ", et al."
    return ", ".join(formatted)


def _chicago_bib_author_list(authors: list[str]) -> str:
    if not authors:
        return ""
    if len(authors) >= 4:
        return f"{format_author_chicago_bib(authors[0])} et al."
    formatted = [format_author_chicago_bib(authors[0])]
    formatted.extend(format_author_chicago_footnote(a) for a in authors[1:])
    if len(formatted) == 1:
        return formatted[0]
    if len(formatted) == 2:
        return f"{formatted[0]}, and {formatted[1]}"
    return ", ".join(formatted[:-1]) + f", and {formatted[-1]}"


def _chicago_footnote_author_list(authors: list[str]) -> str:
    if not authors:
        return ""
    formatted = [format_author_chicago_footnote(a) for a in authors]
    if len(formatted) >= 4:
        return f"{formatted[0]} et al."
    if len(formatted) == 1:
        return formatted[0]
    if len(formatted) == 2:
        return f"{formatted[0]} and {formatted[1]}"
    return ", ".join(formatted[:-1]) + f", and {formatted[-1]}"


# ---------------------------------------------------------------------------
# GOST formatter
# ---------------------------------------------------------------------------


def _format_gost(metadata: CitationMetadata, language: str) -> str:
    lang = _lang_or_default(language)
    if metadata.source_type is SourceType.WEB_PAGE:
        return _format_gost_web(metadata, lang)
    if metadata.source_type is SourceType.BOOK:
        return _format_gost_book(metadata, lang)
    if metadata.source_type is SourceType.CONFERENCE_PAPER:
        return _format_gost_conference(metadata, lang)
    if metadata.source_type is SourceType.DISSERTATION:
        return _format_gost_dissertation(metadata, lang)
    return _format_gost_journal(metadata, lang)


def _format_gost_journal(metadata: CitationMetadata, language: str) -> str:
    labels = _GOST_LABELS[language]
    authors = _gost_author_list(metadata.authors, language)
    title = metadata.title.rstrip(".")
    parts: list[str] = []
    if authors:
        parts.append(authors)
    parts.append(f"{title} //")
    journal = metadata.journal or ""
    if journal:
        parts.append(f"{journal}.")
    parts.append(f"— {metadata.year if metadata.year else labels['no_year']}.")
    if metadata.volume:
        parts.append(f"— {labels['volume']} {metadata.volume}.")
    if metadata.issue:
        parts.append(f"— {labels['issue']} {metadata.issue}.")
    if metadata.pages:
        parts.append(f"— {labels['page_range']} {metadata.pages}.")
    if metadata.doi:
        parts.append(f"— DOI: {metadata.doi}.")
    return " ".join(parts).strip()


def _format_gost_book(metadata: CitationMetadata, language: str) -> str:
    labels = _GOST_LABELS[language]
    authors = _gost_author_list(metadata.authors, language)
    title = metadata.title.rstrip(".")
    parts: list[str] = []
    if authors:
        parts.append(f"{authors} {title}.")
    else:
        parts.append(f"{title}.")
    locale = _gost_locale(metadata, language)
    if locale:
        parts.append(f"— {locale}.")
    if metadata.total_pages:
        parts.append(f"— {metadata.total_pages} {labels['page']}")
    return " ".join(parts).strip()


def _format_gost_web(metadata: CitationMetadata, language: str) -> str:
    labels = _GOST_LABELS[language]
    title = metadata.title.rstrip(".")
    authors = _gost_author_list(metadata.authors, language)
    head = f"{authors} {title}" if authors else title
    parts = [f"{head} {labels['electronic']}."]
    if metadata.url:
        parts.append(f"— {labels['url']} {metadata.url}")
    if metadata.access_date:
        parts.append(f"({labels['access']} {metadata.access_date}).")
    elif metadata.url:
        parts[-1] = parts[-1] + "."
    return " ".join(parts).strip()


def _format_gost_conference(metadata: CitationMetadata, language: str) -> str:
    labels = _GOST_LABELS[language]
    authors = _gost_author_list(metadata.authors, language)
    title = metadata.title.rstrip(".")
    parts: list[str] = []
    if authors:
        parts.append(authors)
    parts.append(f"{title} //")
    if metadata.journal:
        parts.append(f"{metadata.journal}.")
    locale = _gost_locale(metadata, language)
    if locale:
        parts.append(f"— {locale}.")
    if metadata.pages:
        parts.append(f"— {labels['page_range']} {metadata.pages}.")
    return " ".join(parts).strip()


def _format_gost_dissertation(metadata: CitationMetadata, language: str) -> str:
    labels = _GOST_LABELS[language]
    authors = _gost_author_list(metadata.authors, language)
    title = metadata.title.rstrip(".")
    head = f"{authors} {title}" if authors else title
    parts = [f"{head}: {labels['diss']}."]
    locale = _gost_locale(metadata, language)
    if locale:
        parts.append(f"— {locale}.")
    if metadata.total_pages:
        parts.append(f"— {metadata.total_pages} {labels['page']}")
    return " ".join(parts).strip()


def _gost_locale(metadata: CitationMetadata, language: str) -> str:
    labels = _GOST_LABELS[language]
    year_text = str(metadata.year) if metadata.year else labels["no_year"]
    if metadata.city and metadata.publisher:
        return f"{metadata.city}: {metadata.publisher}, {year_text}"
    if metadata.city:
        return f"{metadata.city}, {year_text}"
    if metadata.publisher:
        return f"{metadata.publisher}, {year_text}"
    return year_text


# ---------------------------------------------------------------------------
# APA formatter
# ---------------------------------------------------------------------------


def _format_apa(metadata: CitationMetadata) -> str:
    year = f"({metadata.year})" if metadata.year else f"({_NO_YEAR_APA})"
    authors = _apa_author_list(metadata.authors)
    head = f"{authors} {year}." if authors else f"{metadata.title}. {year}."
    if metadata.source_type is SourceType.WEB_PAGE:
        return _apa_web(metadata, head)
    if metadata.source_type is SourceType.BOOK:
        return _apa_book(metadata, head, has_authors=bool(authors))
    if metadata.source_type is SourceType.CONFERENCE_PAPER:
        return _apa_conference(metadata, head, has_authors=bool(authors))
    if metadata.source_type is SourceType.DISSERTATION:
        return _apa_dissertation(metadata, head, has_authors=bool(authors))
    return _apa_journal(metadata, head, has_authors=bool(authors))


def _apa_journal(metadata: CitationMetadata, head: str, has_authors: bool) -> str:
    title = metadata.title.rstrip(".")
    parts: list[str] = [head]
    if has_authors:
        parts.append(f"{title}.")
    journal = metadata.journal or ""
    locator = _apa_journal_locator(metadata, journal)
    if locator:
        parts.append(f"{locator}.")
    if metadata.doi:
        parts.append(_apa_doi(metadata.doi))
    return " ".join(parts).strip()


def _apa_journal_locator(metadata: CitationMetadata, journal: str) -> str:
    if not journal:
        return ""
    head = journal
    if metadata.volume:
        head += f", {metadata.volume}"
        if metadata.issue:
            head += f"({metadata.issue})"
    if metadata.pages:
        head += f", {metadata.pages}"
    return head


def _apa_book(metadata: CitationMetadata, head: str, has_authors: bool) -> str:
    title = metadata.title.rstrip(".")
    parts = [head]
    if has_authors:
        parts.append(f"{title}.")
    if metadata.publisher:
        parts.append(f"{metadata.publisher}.")
    if metadata.doi:
        parts.append(_apa_doi(metadata.doi))
    return " ".join(parts).strip()


def _apa_web(metadata: CitationMetadata, head: str) -> str:
    title = metadata.title.rstrip(".")
    parts = [head, f"{title}."] if metadata.authors else [head]
    if metadata.publisher:
        parts.append(f"{metadata.publisher}.")
    if metadata.url:
        parts.append(metadata.url)
    return " ".join(parts).strip()


def _apa_conference(metadata: CitationMetadata, head: str, has_authors: bool) -> str:
    title = metadata.title.rstrip(".")
    parts = [head]
    if has_authors:
        parts.append(f"{title}.")
    if metadata.journal:
        parts.append(f"{metadata.journal}.")
    if metadata.city:
        parts.append(f"{metadata.city}.")
    return " ".join(parts).strip()


def _apa_dissertation(metadata: CitationMetadata, head: str, has_authors: bool) -> str:
    title = metadata.title.rstrip(".")
    parts = [head]
    if has_authors:
        parts.append(f"{title} [Doctoral dissertation].")
    if metadata.publisher:
        parts.append(f"{metadata.publisher}.")
    return " ".join(parts).strip()


def _apa_doi(doi: str) -> str:
    if doi.startswith("http"):
        return doi
    cleaned = doi.removeprefix("doi:").strip()
    return f"https://doi.org/{cleaned}"


# ---------------------------------------------------------------------------
# IEEE formatter
# ---------------------------------------------------------------------------


def _format_ieee(metadata: CitationMetadata, number: int | None) -> str:
    prefix = f"[{number}] " if number is not None else ""
    if metadata.source_type is SourceType.BOOK:
        return prefix + _ieee_book(metadata)
    if metadata.source_type is SourceType.CONFERENCE_PAPER:
        return prefix + _ieee_conference(metadata)
    if metadata.source_type is SourceType.WEB_PAGE:
        return prefix + _ieee_web(metadata)
    return prefix + _ieee_journal(metadata)


def _ieee_journal(metadata: CitationMetadata) -> str:
    authors = _ieee_author_list(metadata.authors)
    title = metadata.title.rstrip(".")
    year = str(metadata.year) if metadata.year else _NO_YEAR_IEEE
    parts = [f'{authors}, "{title},"' if authors else f'"{title},"']
    if metadata.journal:
        parts.append(f"{metadata.journal},")
    if metadata.volume:
        parts.append(f"vol. {metadata.volume},")
    if metadata.issue:
        parts.append(f"no. {metadata.issue},")
    if metadata.pages:
        parts.append(f"pp. {metadata.pages},")
    parts.append(f"{year}.")
    return " ".join(parts).strip()


def _ieee_book(metadata: CitationMetadata) -> str:
    authors = _ieee_author_list(metadata.authors)
    title = metadata.title.rstrip(".")
    year = str(metadata.year) if metadata.year else _NO_YEAR_IEEE
    parts = [f"{authors}, {title}." if authors else f"{title}."]
    if metadata.city and metadata.publisher:
        parts.append(f"{metadata.city}: {metadata.publisher},")
    elif metadata.publisher:
        parts.append(f"{metadata.publisher},")
    parts.append(f"{year}.")
    return " ".join(parts).strip()


def _ieee_conference(metadata: CitationMetadata) -> str:
    authors = _ieee_author_list(metadata.authors)
    title = metadata.title.rstrip(".")
    year = str(metadata.year) if metadata.year else _NO_YEAR_IEEE
    parts = [f'{authors}, "{title},"' if authors else f'"{title},"']
    if metadata.journal:
        parts.append(f"in Proc. {metadata.journal},")
    if metadata.city:
        parts.append(f"{metadata.city},")
    parts.append(f"{year},")
    if metadata.pages:
        parts.append(f"pp. {metadata.pages}.")
    else:
        parts[-1] = parts[-1].rstrip(",") + "."
    return " ".join(parts).strip()


def _ieee_web(metadata: CitationMetadata) -> str:
    authors = _ieee_author_list(metadata.authors)
    title = metadata.title.rstrip(".")
    parts = [f'{authors}. "{title}."' if authors else f'"{title}."']
    if metadata.publisher:
        parts.append(f"{metadata.publisher}.")
    if metadata.url:
        parts.append(metadata.url)
    if metadata.access_date:
        parts.append(f"(accessed {metadata.access_date}).")
    return " ".join(parts).strip()


# ---------------------------------------------------------------------------
# Chicago formatter
# ---------------------------------------------------------------------------


def _format_chicago_bibliography(metadata: CitationMetadata) -> str:
    if metadata.source_type is SourceType.JOURNAL_ARTICLE:
        return _chicago_bib_journal(metadata)
    if metadata.source_type is SourceType.WEB_PAGE:
        return _chicago_bib_web(metadata)
    return _chicago_bib_book(metadata)


def _chicago_bib_book(metadata: CitationMetadata) -> str:
    authors = _terminate(_chicago_bib_author_list(metadata.authors))
    title = metadata.title.rstrip(".")
    year = str(metadata.year) if metadata.year else _NO_YEAR_APA
    head = f"{authors} {title}." if authors else f"{title}."
    if metadata.city and metadata.publisher:
        return f"{head} {metadata.city}: {metadata.publisher}, {year}."
    if metadata.publisher:
        return f"{head} {metadata.publisher}, {year}."
    return f"{head} {year}."


def _chicago_bib_journal(metadata: CitationMetadata) -> str:
    authors = _terminate(_chicago_bib_author_list(metadata.authors))
    title = metadata.title.rstrip(".")
    year = str(metadata.year) if metadata.year else _NO_YEAR_APA
    journal = metadata.journal or ""
    head = f'{authors} "{title}."' if authors else f'"{title}."'
    locator = _chicago_journal_locator(metadata)
    suffix = f" {journal} {locator} ({year})" if locator else f" {journal} ({year})"
    out = head + suffix.rstrip() + "."
    if metadata.doi:
        out += f" {_apa_doi(metadata.doi)}."
    return out


def _chicago_journal_locator(metadata: CitationMetadata) -> str:
    parts: list[str] = []
    if metadata.volume:
        parts.append(metadata.volume)
        if metadata.issue:
            parts.append(f"no. {metadata.issue}")
    if metadata.pages:
        joined = ", ".join(parts)
        return f"{joined}: {metadata.pages}" if joined else f": {metadata.pages}"
    return ", ".join(parts)


def _chicago_bib_web(metadata: CitationMetadata) -> str:
    authors = _terminate(_chicago_bib_author_list(metadata.authors))
    title = metadata.title.rstrip(".")
    head = f'{authors} "{title}."' if authors else f'"{title}."'
    parts = [head]
    if metadata.publisher:
        parts.append(f"{metadata.publisher}.")
    if metadata.access_date:
        parts.append(f"Accessed {metadata.access_date}.")
    if metadata.url:
        parts.append(f"{metadata.url}.")
    return " ".join(parts).strip()


def _chicago_footnote_full(metadata: CitationMetadata, page: int | None) -> str:
    authors = _chicago_footnote_author_list(metadata.authors)
    title = metadata.title.rstrip(".")
    year = str(metadata.year) if metadata.year else _NO_YEAR_APA
    locale_parts: list[str] = []
    if metadata.city:
        locale_parts.append(metadata.city)
    if metadata.publisher:
        if locale_parts:
            locale_parts[-1] = f"{locale_parts[-1]}: {metadata.publisher}"
        else:
            locale_parts.append(metadata.publisher)
    locale_parts.append(year)
    locale = ", ".join(locale_parts)
    head = f"{authors}, {title} ({locale})" if authors else f"{title} ({locale})"
    if page is not None:
        return f"{head}, {page}."
    return f"{head}."


def _chicago_footnote_short(metadata: CitationMetadata, page: int | None) -> str:
    short_title = _short_title(metadata.title)
    if metadata.authors:
        last = _split_name(metadata.authors[0])[0]
        head = f"{last}, {short_title}"
    else:
        head = short_title
    if page is not None:
        return f"{head}, {page}."
    return f"{head}."


def _short_title(title: str) -> str:
    cleaned = title.rstrip(".").strip()
    words = cleaned.split()
    if len(words) <= 4:
        return cleaned
    return " ".join(words[:4])


def _terminate(text: str) -> str:
    """Ensure ``text`` ends with exactly one period (or is empty).

    Author lists, titles, and locator fragments often already end in a
    period — ``"P. et al."`` or ``"J. A."`` — so naively appending
    another would produce ``".."`` joins. This helper centralises the
    rule so each style's per-source-type formatter does not have to.
    """

    if not text:
        return ""
    return text if text.endswith(".") else text + "."


# ---------------------------------------------------------------------------
# Vancouver formatter
# ---------------------------------------------------------------------------


def _format_vancouver(metadata: CitationMetadata, number: int | None) -> str:
    prefix = f"{number}. " if number is not None else ""
    if metadata.source_type is SourceType.BOOK:
        return prefix + _vancouver_book(metadata)
    if metadata.source_type is SourceType.WEB_PAGE:
        return prefix + _vancouver_web(metadata)
    return prefix + _vancouver_journal(metadata)


def _vancouver_journal(metadata: CitationMetadata) -> str:
    authors = _vancouver_author_list(metadata.authors)
    title = metadata.title.rstrip(".")
    year = str(metadata.year) if metadata.year else _NO_YEAR_IEEE
    journal = metadata.journal or ""
    head = f"{authors}. {title}." if authors else f"{title}."
    parts = [head]
    if journal:
        parts.append(f"{journal}.")
    locator = _vancouver_locator(metadata, year)
    parts.append(locator + ".")
    return " ".join(parts).strip()


def _vancouver_locator(metadata: CitationMetadata, year: str) -> str:
    head = year
    if metadata.volume:
        head += f";{metadata.volume}"
        if metadata.issue:
            head += f"({metadata.issue})"
    if metadata.pages:
        head += f":{metadata.pages}"
    return head


def _vancouver_book(metadata: CitationMetadata) -> str:
    authors = _vancouver_author_list(metadata.authors)
    title = metadata.title.rstrip(".")
    year = str(metadata.year) if metadata.year else _NO_YEAR_IEEE
    head = f"{authors}. {title}." if authors else f"{title}."
    parts = [head]
    if metadata.edition:
        parts.append(f"{metadata.edition}.")
    if metadata.city and metadata.publisher:
        parts.append(f"{metadata.city}: {metadata.publisher}; {year}.")
    elif metadata.publisher:
        parts.append(f"{metadata.publisher}; {year}.")
    else:
        parts.append(f"{year}.")
    return " ".join(parts).strip()


def _vancouver_web(metadata: CitationMetadata) -> str:
    authors = _vancouver_author_list(metadata.authors)
    title = metadata.title.rstrip(".")
    year = str(metadata.year) if metadata.year else _NO_YEAR_IEEE
    head = f"{authors}. {title} [Internet]." if authors else f"{title} [Internet]."
    parts = [head]
    if metadata.publisher:
        parts.append(f"{metadata.publisher};")
    parts.append(f"{year}")
    if metadata.access_date:
        parts.append(f"[cited {metadata.access_date}].")
    if metadata.url:
        parts.append(f"Available from: {metadata.url}")
    return " ".join(parts).strip()


# ---------------------------------------------------------------------------
# Ordering / utilities
# ---------------------------------------------------------------------------


def _is_numbered(style: CitationFormat) -> bool:
    return style in (CitationFormat.GOST, CitationFormat.IEEE, CitationFormat.VANCOUVER)


def _order_citations(
    citations: list[CitationMetadata],
    style: CitationFormat,
) -> list[CitationMetadata]:
    if _is_numbered(style):
        return sorted(citations, key=lambda c: c.citation_number or 10_000)
    return sorted(citations, key=_alphabetical_key)


def _alphabetical_key(meta: CitationMetadata) -> tuple[str, int]:
    if meta.authors:
        last, _ = _split_name(meta.authors[0])
        return (last.lower(), meta.year or 0)
    return (meta.title.lower(), meta.year or 0)


def _lang_or_default(language: str | None) -> str:
    if language in _GOST_LABELS:
        return language
    return "ru"


# ---------------------------------------------------------------------------
# Metadata conversion
# ---------------------------------------------------------------------------


def source_to_citation_metadata(
    source_meta: SourceMetadataExtracted,
    doi_meta: DOIMetadata | None = None,
) -> CitationMetadata:
    """Merge parser-extracted metadata with optional CrossRef enrichment.

    DOI fields take priority on conflict because CrossRef data is
    standardised (e.g. its title is the journal-of-record title rather
    than whatever the PDF metadata happens to expose). Any field absent
    from both inputs simply stays unset.
    """

    title = (doi_meta.title if doi_meta else None) or source_meta.title or "Untitled"
    authors = list(doi_meta.authors) if doi_meta and doi_meta.authors else list(source_meta.authors)
    year = (doi_meta.year if doi_meta else None) or source_meta.year
    doi = (doi_meta.doi if doi_meta else None) or source_meta.doi
    return CitationMetadata(
        title=title,
        authors=authors,
        year=year,
        journal=doi_meta.journal if doi_meta else None,
        volume=doi_meta.volume if doi_meta else None,
        issue=doi_meta.issue if doi_meta else None,
        pages=doi_meta.pages if doi_meta else None,
        publisher=doi_meta.publisher if doi_meta else None,
        doi=doi,
        url=doi_meta.url if doi_meta else None,
        total_pages=source_meta.page_count if source_meta.page_count > 0 else None,
        source_type=_infer_source_type(doi_meta),
    )


def _infer_source_type(doi_meta: DOIMetadata | None) -> SourceType:
    if doi_meta is None or not doi_meta.doc_type:
        return SourceType.JOURNAL_ARTICLE
    doc_type = doi_meta.doc_type.lower()
    # Order matters: "book-chapter" must match BOOK_CHAPTER, not BOOK.
    if "chapter" in doc_type:
        return SourceType.BOOK_CHAPTER
    if "book" in doc_type:
        return SourceType.BOOK
    if "conference" in doc_type or "proceedings" in doc_type:
        return SourceType.CONFERENCE_PAPER
    if "dissertation" in doc_type or "thesis" in doc_type:
        return SourceType.DISSERTATION
    if "report" in doc_type:
        return SourceType.REPORT
    if "dataset" in doc_type:
        return SourceType.DATASET
    return SourceType.JOURNAL_ARTICLE


__all__ = [
    "BibliographyFormatter",
    "format_author_apa",
    "format_author_chicago_bib",
    "format_author_chicago_footnote",
    "format_author_gost",
    "format_author_ieee",
    "format_author_vancouver",
    "source_to_citation_metadata",
]
