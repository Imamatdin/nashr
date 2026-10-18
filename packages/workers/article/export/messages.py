"""Four-language copy for compliance results (D9).

The checker returns a language-neutral ``rule_key`` and a status; this module
turns a check into human text in uz, ru, kaa or en. kaa strings have not had
native-speaker review (see the lane file). Keeping the copy here (not in the web
copy files) lets the API serve compliance reports without the web layer and lets
B6 tests assert every key has all four languages.
"""

from __future__ import annotations

from packages.core.enums import Language
from packages.workers.article.export.models import ComplianceStatus

RULE_LABEL: dict[str, dict[Language, str]] = {
    "page_size": {
        Language.UZ: "Sahifa o'lchami",
        Language.RU: "Размер страницы",
        Language.KAA: "Bet ólshemi",
        Language.EN: "Page size",
    },
    "margins": {
        Language.UZ: "Chet maydonlari",
        Language.RU: "Поля",
        Language.KAA: "Shetler",
        Language.EN: "Margins",
    },
    "body_font": {
        Language.UZ: "Asosiy shrift",
        Language.RU: "Основной шрифт",
        Language.KAA: "Tiykarǵı shrift",
        Language.EN: "Body font",
    },
    "body_size": {
        Language.UZ: "Shrift o'lchami",
        Language.RU: "Размер шрифта",
        Language.KAA: "Shrift ólshemi",
        Language.EN: "Font size",
    },
    "line_spacing": {
        Language.UZ: "Qatorlar oralig'i",
        Language.RU: "Межстрочный интервал",
        Language.KAA: "Qatarlar aralıǵı",
        Language.EN: "Line spacing",
    },
    "first_line_indent": {
        Language.UZ: "Birinchi qator abzatsi",
        Language.RU: "Отступ первой строки",
        Language.KAA: "Birinshi qatar shegirisi",
        Language.EN: "First-line indent",
    },
    "heading_1": {
        Language.UZ: "1-darajali sarlavha",
        Language.RU: "Заголовок 1 уровня",
        Language.KAA: "1-dárejeli sarlawha",
        Language.EN: "Heading level 1",
    },
    "heading_2": {
        Language.UZ: "2-darajali sarlavha",
        Language.RU: "Заголовок 2 уровня",
        Language.KAA: "2-dárejeli sarlawha",
        Language.EN: "Heading level 2",
    },
    "heading_3": {
        Language.UZ: "3-darajali sarlavha",
        Language.RU: "Заголовок 3 уровня",
        Language.KAA: "3-dárejeli sarlawha",
        Language.EN: "Heading level 3",
    },
    "page_numbers": {
        Language.UZ: "Sahifa raqamlari",
        Language.RU: "Нумерация страниц",
        Language.KAA: "Bet nomerleri",
        Language.EN: "Page numbers",
    },
    "title_page": {
        Language.UZ: "Sarlavha sahifasi",
        Language.RU: "Титульный лист",
        Language.KAA: "Titul beti",
        Language.EN: "Title page",
    },
    "abstract_word_count": {
        Language.UZ: "Annotatsiya hajmi",
        Language.RU: "Объём аннотации",
        Language.KAA: "Annotaciya kólemi",
        Language.EN: "Abstract length",
    },
}

STATUS_LABEL: dict[ComplianceStatus, dict[Language, str]] = {
    "pass": {
        Language.UZ: "Mos keladi",
        Language.RU: "Соответствует",
        Language.KAA: "Sáykes keledi",
        Language.EN: "Pass",
    },
    "fail": {
        Language.UZ: "Mos kelmaydi",
        Language.RU: "Не соответствует",
        Language.KAA: "Sáykes kelmeydi",
        Language.EN: "Fail",
    },
    "unknown": {
        Language.UZ: "Aniqlanmadi",
        Language.RU: "Не определено",
        Language.KAA: "Anıqlanbadı",
        Language.EN: "Unknown",
    },
}


def rule_label(rule_key: str, language: Language) -> str:
    """Localised label for a rule, falling back to English then the raw key."""

    labels = RULE_LABEL.get(rule_key)
    if labels is None:
        return rule_key
    return labels.get(language, labels[Language.EN])


def status_label(status: ComplianceStatus, language: Language) -> str:
    """Localised label for a compliance status."""

    return STATUS_LABEL[status].get(language, STATUS_LABEL[status][Language.EN])


__all__ = ["RULE_LABEL", "STATUS_LABEL", "rule_label", "status_label"]
