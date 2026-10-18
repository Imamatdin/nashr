"""Localised fixed strings the builder writes into the DOCX, in all four languages.

These are document labels (headings like "References", title-page words like
"Performed by"), not UI copy. Every entry exists in uz, ru, kaa and en (D9).
The kaa strings have not had native-speaker review; see the lane file.
"""

from __future__ import annotations

from packages.core.enums import ArticleStructure, Language

BIBLIOGRAPHY_HEADING: dict[Language, str] = {
    Language.UZ: "FOYDALANILGAN ADABIYOTLAR RO'YXATI",
    Language.RU: "СПИСОК ИСПОЛЬЗОВАННОЙ ЛИТЕРАТУРЫ",
    Language.KAA: "PAYDALANILǴAN ÁDEBIYATLAR DIZIMI",
    Language.EN: "REFERENCES",
}

KEYWORDS_LABEL: dict[Language, str] = {
    Language.UZ: "Kalit so'zlar",
    Language.RU: "Ключевые слова",
    Language.KAA: "Gilt sózler",
    Language.EN: "Keywords",
}

TOC_HEADING: dict[Language, str] = {
    Language.UZ: "MUNDARIJA",
    Language.RU: "СОДЕРЖАНИЕ",
    Language.KAA: "MAZMUNI",
    Language.EN: "TABLE OF CONTENTS",
}

ABSTRACT_HEADING: dict[Language, str] = {
    Language.UZ: "ANNOTATSIYA",
    Language.RU: "АННОТАЦИЯ",
    Language.KAA: "ANNOTACIYA",
    Language.EN: "ABSTRACT",
}

PERFORMED_BY: dict[Language, str] = {
    Language.UZ: "Bajardi",
    Language.RU: "Выполнил",
    Language.KAA: "Orınladı",
    Language.EN: "Performed by",
}

CHECKED_BY: dict[Language, str] = {
    Language.UZ: "Tekshirdi",
    Language.RU: "Проверил",
    Language.KAA: "Tekserdi",
    Language.EN: "Checked by",
}

ARTICLE_TYPE_LABEL: dict[ArticleStructure, dict[Language, str]] = {
    ArticleStructure.REFERAT: {
        Language.UZ: "REFERAT",
        Language.RU: "РЕФЕРАТ",
        Language.KAA: "REFERAT",
        Language.EN: "REPORT",
    },
    ArticleStructure.KURS_ISHI: {
        Language.UZ: "KURS ISHI",
        Language.RU: "КУРСОВАЯ РАБОТА",
        Language.KAA: "KURS JUMISI",
        Language.EN: "COURSEWORK",
    },
    ArticleStructure.HISOBOT: {
        Language.UZ: "HISOBOT",
        Language.RU: "ОТЧЁТ",
        Language.KAA: "ESABAT",
        Language.EN: "REPORT",
    },
    ArticleStructure.ILMIY_MAQOLA: {
        Language.UZ: "ILMIY MAQOLA",
        Language.RU: "НАУЧНАЯ СТАТЬЯ",
        Language.KAA: "ILIMIY MAQALA",
        Language.EN: "ARTICLE",
    },
}


def article_type_label(article_type: ArticleStructure, language: Language) -> str:
    """The localised label for an article type, falling back to English."""

    return ARTICLE_TYPE_LABEL[article_type].get(
        language, ARTICLE_TYPE_LABEL[article_type][Language.EN]
    )


__all__ = [
    "ABSTRACT_HEADING",
    "ARTICLE_TYPE_LABEL",
    "BIBLIOGRAPHY_HEADING",
    "CHECKED_BY",
    "KEYWORDS_LABEL",
    "PERFORMED_BY",
    "TOC_HEADING",
    "article_type_label",
]
