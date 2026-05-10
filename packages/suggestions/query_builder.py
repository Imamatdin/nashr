"""Builds search queries for suggestion providers from outline sections.

Given one outline section plus the claims assigned to it, this module
emits 1-3 plain-text queries targeting the providers in the registry.
The first query is always derived from the section title and thesis;
subsequent queries are added when the section has a strong assigned
claim (key noun extraction) or when the section needs statistical
backing (a "data" / "statistics" suffix is appended).

All queries are emitted in English regardless of the article language
because the upstream APIs (PubMed, World Bank, OpenAlex, etc.) are
English-first. Common Uzbek and Russian academic terms are translated
via a small built-in dictionary; everything else is passed through
lower-cased.
"""

from __future__ import annotations

import re
from typing import Final

from packages.core.enums import ClaimStrength
from packages.core.models.article import OutlineSection
from packages.core.models.source import SourceClaimCreate

_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"[\w']+", re.UNICODE)
_MAX_QUERY_CHARS: Final[int] = 100
_MAX_KEYWORDS_PRIMARY: Final[int] = 5
_MAX_KEYWORDS_CLAIM: Final[int] = 4

_STOPWORDS_EN: Final[frozenset[str]] = frozenset(
    {
        "the",
        "and",
        "of",
        "is",
        "in",
        "to",
        "for",
        "a",
        "an",
        "on",
        "at",
        "by",
        "with",
        "from",
        "as",
        "that",
        "this",
        "are",
        "was",
        "were",
        "be",
        "or",
        "it",
        "its",
        "into",
        "but",
        "not",
        "have",
        "has",
        "had",
        "we",
        "our",
        "their",
        "these",
        "those",
        "between",
        "about",
        "than",
        "then",
        "also",
        "such",
        "via",
    }
)
_STOPWORDS_UZ: Final[frozenset[str]] = frozenset(
    {
        "va",
        "bir",
        "bu",
        "bilan",
        "uchun",
        "boʻlgan",
        "bolgan",
        "bo'lgan",
        "ham",
        "lekin",
        "yoki",
        "agar",
        "qachon",
        "shu",
        "har",
        "ko'p",
        "kop",
        "u",
        "ular",
        "men",
        "biz",
        "siz",
        "ushbu",
        "uning",
        "ya'ni",
        "yani",
    }
)
_STOPWORDS_RU: Final[frozenset[str]] = frozenset(
    {
        "и",
        "в",
        "на",
        "с",
        "по",
        "для",
        "не",
        "что",
        "это",
        "как",
        "к",
        "из",
        "от",
        "о",
        "а",
        "но",
        "же",
        "у",
        "за",
        "до",
        "при",
        "так",
        "или",
        "его",
        "её",
        "их",
        "мы",
        "вы",
        "они",
    }
)
_STOPWORDS: Final[frozenset[str]] = _STOPWORDS_EN | _STOPWORDS_UZ | _STOPWORDS_RU

_UZ_TO_EN: Final[dict[str, str]] = {
    "iqtisodiyot": "economics",
    "iqtisod": "economic",
    "iqtisodiy": "economic",
    "savdo": "trade",
    "bozor": "market",
    "investitsiya": "investment",
    "eksport": "export",
    "import": "import",
    "soliq": "tax",
    "byudjet": "budget",
    "daromad": "income",
    "inflyatsiya": "inflation",
    "ishsizlik": "unemployment",
    "qonun": "law",
    "huquq": "right",
    "sud": "court",
    "farmon": "decree",
    "qaror": "regulation",
    "kodeks": "code",
    "konstitusiya": "constitution",
    "javobgarlik": "liability",
    "bemor": "patient",
    "kasallik": "disease",
    "davolash": "treatment",
    "shifoxona": "hospital",
    "tibbiyot": "medicine",
    "dori": "drug",
    "diagnostika": "diagnosis",
    "jarrohlik": "surgery",
    "talaba": "student",
    "o'qituvchi": "teacher",
    "oqituvchi": "teacher",
    "ta'lim": "education",
    "talim": "education",
    "o'quv": "study",
    "oquv": "study",
    "maktab": "school",
    "universitet": "university",
    "iqlim": "climate",
    "ifloslanish": "pollution",
    "ekologiya": "ecology",
    "barqaror": "sustainable",
    "qishloq": "rural",
    "ekin": "crop",
    "tuproq": "soil",
    "sug'orish": "irrigation",
    "sugorish": "irrigation",
    "hosil": "harvest",
    "tizim": "system",
    "loyihalash": "design",
    "algoritm": "algorithm",
    "dasturlash": "programming",
    "tarmoq": "network",
    "jamiyat": "society",
    "madaniyat": "culture",
    "migratsiya": "migration",
    "sotsiologiya": "sociology",
    "siyosat": "policy",
    "boshqaruv": "governance",
    "rivojlanish": "development",
    "mintaqa": "region",
    "ozbekiston": "uzbekistan",
    "o'zbekiston": "uzbekistan",
}
_RU_TO_EN: Final[dict[str, str]] = {
    "экономика": "economics",
    "экономический": "economic",
    "торговля": "trade",
    "рынок": "market",
    "инвестиции": "investment",
    "экспорт": "export",
    "импорт": "import",
    "налог": "tax",
    "бюджет": "budget",
    "доход": "income",
    "инфляция": "inflation",
    "безработица": "unemployment",
    "закон": "law",
    "право": "right",
    "суд": "court",
    "указ": "decree",
    "постановление": "regulation",
    "кодекс": "code",
    "конституция": "constitution",
    "юридический": "legal",
    "пациент": "patient",
    "болезнь": "disease",
    "лечение": "treatment",
    "больница": "hospital",
    "медицина": "medicine",
    "лекарство": "drug",
    "диагноз": "diagnosis",
    "хирургия": "surgery",
    "клинический": "clinical",
    "терапия": "therapy",
    "студент": "student",
    "преподаватель": "teacher",
    "образование": "education",
    "обучение": "study",
    "школа": "school",
    "университет": "university",
    "климат": "climate",
    "загрязнение": "pollution",
    "экология": "ecology",
    "устойчивый": "sustainable",
    "сельское": "rural",
    "урожай": "harvest",
    "орошение": "irrigation",
    "почва": "soil",
    "система": "system",
    "проектирование": "design",
    "алгоритм": "algorithm",
    "программирование": "programming",
    "сеть": "network",
    "общество": "society",
    "культура": "culture",
    "миграция": "migration",
    "социология": "sociology",
    "политика": "policy",
    "управление": "governance",
    "развитие": "development",
    "регион": "region",
    "узбекистан": "uzbekistan",
}


class SuggestionQueryBuilder:
    """Build 1-3 search queries per article section for the suggestion engine.

    Stateless — share a single instance across all sections. Returns at
    least one query (the section title, fallback) so providers always
    have something to search.
    """

    def build_queries(
        self,
        section: OutlineSection,
        claims: list[SourceClaimCreate],
        language: str,
        needs_statistical: bool = False,
    ) -> list[str]:
        """Build 1-3 queries for ``section``.

        ``language`` selects which translation dictionary applies. ``claims``
        should be the subset already assigned to this section (the engine
        filters before calling). ``needs_statistical`` triggers a third
        query that targets quantitative sources for the country.
        """

        queries: list[str] = []

        primary = _build_primary_query(section, language)
        if primary:
            queries.append(primary)
        else:
            queries.append(_truncate(_translate(section.title.lower(), language)))

        claim_query = _build_claim_query(claims, language)
        if claim_query and claim_query not in queries:
            queries.append(claim_query)

        if needs_statistical:
            stat_query = _build_statistical_query(primary or section.title, language)
            if stat_query and stat_query not in queries:
                queries.append(stat_query)

        return queries[:3]


def _build_primary_query(section: OutlineSection, language: str) -> str:
    """Top keywords from the title plus thesis, translated and stop-word-stripped."""

    raw = f"{section.title} {section.section_thesis}".strip()
    if not raw:
        return ""
    keywords = _extract_keywords(raw, language, _MAX_KEYWORDS_PRIMARY)
    return _truncate(" ".join(keywords))


def _build_claim_query(claims: list[SourceClaimCreate], language: str) -> str:
    """Top keywords from the highest-strength claim assigned to the section."""

    if not claims:
        return ""
    best = max(claims, key=_claim_priority)
    keywords = _extract_keywords(best.claim_text, language, _MAX_KEYWORDS_CLAIM)
    return _truncate(" ".join(keywords))


def _build_statistical_query(seed: str, language: str) -> str:
    """Append a country-statistics modifier so the query targets data sources."""

    keywords = _extract_keywords(seed, language, _MAX_KEYWORDS_PRIMARY - 2)
    if not keywords:
        return ""
    return _truncate(" ".join([*keywords, "Uzbekistan", "data", "statistics"]))


def _claim_priority(claim: SourceClaimCreate) -> int:
    """STRONG > MODERATE > WEAK; ties broken by length."""

    rank = {ClaimStrength.STRONG: 2, ClaimStrength.MODERATE: 1, ClaimStrength.WEAK: 0}
    return rank.get(claim.strength, 0) * 1000 + len(claim.claim_text)


def _extract_keywords(text: str, language: str, limit: int) -> list[str]:
    """Tokenise, translate, strip stopwords, dedupe, keep insertion order."""

    seen: set[str] = set()
    out: list[str] = []
    for match in _TOKEN_RE.finditer(text.lower()):
        token = match.group(0)
        if not token or token in _STOPWORDS or len(token) < 2:
            continue
        translated = _translate_token(token, language)
        if translated in _STOPWORDS or len(translated) < 2:
            continue
        if translated in seen:
            continue
        seen.add(translated)
        out.append(translated)
        if len(out) >= limit:
            break
    return out


def _translate(text: str, language: str) -> str:
    """Translate every token in ``text`` according to ``language``."""

    parts: list[str] = []
    for match in _TOKEN_RE.finditer(text.lower()):
        token = match.group(0)
        if token in _STOPWORDS:
            continue
        parts.append(_translate_token(token, language))
    return " ".join(parts)


def _translate_token(token: str, language: str) -> str:
    """Look up ``token`` in the language-specific dictionary, else passthrough."""

    if language == "uz":
        return _UZ_TO_EN.get(token, token)
    if language == "ru":
        return _RU_TO_EN.get(token, token)
    return token


def _truncate(text: str) -> str:
    """Cap query length at :data:`_MAX_QUERY_CHARS` on a word boundary."""

    cleaned = text.strip()
    if len(cleaned) <= _MAX_QUERY_CHARS:
        return cleaned
    cut = cleaned[:_MAX_QUERY_CHARS].rsplit(" ", 1)[0]
    return cut.strip()


__all__ = ["SuggestionQueryBuilder"]
