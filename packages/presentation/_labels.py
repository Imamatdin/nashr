"""Trilingual (uz/ru/en) text for every interview question and option.

Separated from :mod:`packages.presentation.interview` because the localised
copy is bulky and the engine logic is easier to read without it. The
question identifiers, option values, and ordering live here so the engine
can iterate the structure once and emit a localised
:class:`PresentationInterviewQuestions`.
"""

from __future__ import annotations

from typing import Final, TypedDict


class Tri(TypedDict):
    """Trilingual string keyed by Nashr's supported language codes."""

    uz: str
    ru: str
    en: str


class OptionSpec(TypedDict):
    """One selectable option in an interview question."""

    value: str
    label: Tri
    is_default: bool


AUDIENCE_OPTIONS: Final[list[OptionSpec]] = [
    {
        "value": "school",
        "label": {
            "uz": "Maktab o'quvchilari (9-11 sinf)",
            "ru": "Школьники (9-11 класс)",
            "en": "School students (9th-11th grade)",
        },
        "is_default": False,
    },
    {
        "value": "undergraduate",
        "label": {
            "uz": "Bakalavr talabalari",
            "ru": "Студенты бакалавриата",
            "en": "University undergraduates",
        },
        "is_default": False,
    },
    {
        "value": "graduate",
        "label": {
            "uz": "Magistratura talabalari",
            "ru": "Студенты магистратуры",
            "en": "Graduate students",
        },
        "is_default": False,
    },
    {
        "value": "academic_conference",
        "label": {
            "uz": "Akademik konferentsiya",
            "ru": "Академическая конференция",
            "en": "Academic conference",
        },
        "is_default": False,
    },
    {
        "value": "mixed_academic_industry",
        "label": {
            "uz": "Akademik va sanoat aralash",
            "ru": "Академия и индустрия",
            "en": "Mixed academic + industry",
        },
        "is_default": False,
    },
    {
        "value": "professional",
        "label": {
            "uz": "Mutaxassis / biznes",
            "ru": "Профессиональная аудитория / бизнес",
            "en": "Professional / business",
        },
        "is_default": False,
    },
    {
        "value": "general_public",
        "label": {
            "uz": "Keng jamoatchilik",
            "ru": "Широкая аудитория",
            "en": "General public",
        },
        "is_default": False,
    },
    {
        "value": "decide_for_me",
        "label": {
            "uz": "O'zingiz tanlang",
            "ru": "Решите за меня",
            "en": "Decide for me",
        },
        "is_default": True,
    },
]


EMPHASIS_OPTIONS: Final[list[OptionSpec]] = [
    {
        "value": "problem_framing",
        "label": {
            "uz": "Muammoni shakllantirish",
            "ru": "Постановка проблемы",
            "en": "Problem framing",
        },
        "is_default": False,
    },
    {
        "value": "technical_mechanism",
        "label": {
            "uz": "Texnik mexanizm",
            "ru": "Технический механизм",
            "en": "Technical mechanism",
        },
        "is_default": False,
    },
    {
        "value": "methodology",
        "label": {
            "uz": "Metodologiya",
            "ru": "Методология",
            "en": "Methodology",
        },
        "is_default": False,
    },
    {
        "value": "results_numbers",
        "label": {
            "uz": "Natijalar / raqamlar",
            "ru": "Результаты / цифры",
            "en": "Results / numbers",
        },
        "is_default": False,
    },
    {
        "value": "roadmap_scalability",
        "label": {
            "uz": "Yo'l xaritasi / miqyoslash",
            "ru": "План развития / масштабируемость",
            "en": "Roadmap / scalability",
        },
        "is_default": False,
    },
    {
        "value": "decide_for_me",
        "label": {
            "uz": "O'zingiz tanlang",
            "ru": "Решите за меня",
            "en": "Decide for me",
        },
        "is_default": True,
    },
]


TITLE_STYLE_OPTIONS: Final[list[OptionSpec]] = [
    {
        "value": "topic",
        "label": {
            "uz": "Qisqa mavzu sarlavhalari ('Metodologiya', 'Natijalar')",
            "ru": "Краткие тематические заголовки ('Методология', 'Результаты')",
            "en": "Short topic noun-phrases ('Methodology', 'Results')",
        },
        "is_default": False,
    },
    {
        "value": "takeaway",
        "label": {
            "uz": "Xulosa sarlavhalari ('Sietlda 94% suv tejaldi')",
            "ru": "Заголовки-выводы ('94% экономии воды в Сиэтле')",
            "en": "Takeaway titles ('94% water savings in Seattle')",
        },
        "is_default": False,
    },
    {
        "value": "decide_for_me",
        "label": {
            "uz": "O'zingiz tanlang",
            "ru": "Решите за меня",
            "en": "Decide for me",
        },
        "is_default": True,
    },
]


INTERACTIVE_OPTIONS: Final[list[OptionSpec]] = [
    {
        "value": "yes",
        "label": {
            "uz": "Ha — viktorina, juftlash, mashqlar",
            "ru": "Да — викторины, сопоставления, упражнения",
            "en": "Yes — quizzes, matching, exercises",
        },
        "is_default": False,
    },
    {
        "value": "no",
        "label": {
            "uz": "Yo'q — faqat kontent",
            "ru": "Нет — только контент",
            "en": "No — content only",
        },
        "is_default": False,
    },
    {
        "value": "decide_for_me",
        "label": {
            "uz": "O'zingiz tanlang",
            "ru": "Решите за меня",
            "en": "Decide for me",
        },
        "is_default": True,
    },
]


THEME_OPTIONS: Final[list[OptionSpec]] = [
    {
        "value": "light",
        "label": {
            "uz": "Yorug' fon",
            "ru": "Светлый фон",
            "en": "Light backgrounds",
        },
        "is_default": False,
    },
    {
        "value": "dark",
        "label": {
            "uz": "Qora fon",
            "ru": "Тёмный фон",
            "en": "Dark backgrounds",
        },
        "is_default": False,
    },
    {
        "value": "decide_for_me",
        "label": {
            "uz": "O'zingiz tanlang",
            "ru": "Решите за меня",
            "en": "Decide for me",
        },
        "is_default": True,
    },
]


SPEAKER_NOTES_OPTIONS: Final[list[OptionSpec]] = [
    {
        "value": "full_script",
        "label": {
            "uz": "Ha — har slaydga to'liq matn",
            "ru": "Да — полный скрипт к каждому слайду",
            "en": "Yes — full script per slide",
        },
        "is_default": False,
    },
    {
        "value": "brief_talking_points",
        "label": {
            "uz": "Qisqacha tezislar",
            "ru": "Краткие тезисы",
            "en": "Brief talking points only",
        },
        "is_default": False,
    },
    {
        "value": "no_notes",
        "label": {
            "uz": "Yo'q",
            "ru": "Без заметок",
            "en": "No notes",
        },
        "is_default": False,
    },
    {
        "value": "decide_for_me",
        "label": {
            "uz": "O'zingiz tanlang",
            "ru": "Решите за меня",
            "en": "Decide for me",
        },
        "is_default": True,
    },
]


DIAGRAM_OPTIONS: Final[list[OptionSpec]] = [
    {
        "value": "build_svg",
        "label": {
            "uz": "Ha — SVG diagramma yaratish",
            "ru": "Да — собирать диаграммы в SVG",
            "en": "Yes — build diagrams in SVG",
        },
        "is_default": False,
    },
    {
        "value": "placeholder",
        "label": {
            "uz": "Keyin men beradigan joy qoldirish",
            "ru": "Оставить место для моих диаграмм",
            "en": "Use placeholder slots for diagrams I'll provide later",
        },
        "is_default": False,
    },
    {
        "value": "minimal_text",
        "label": {
            "uz": "Minimal diagramma, asosan matn va raqamlar",
            "ru": "Минимум диаграмм, в основном текст и числа",
            "en": "Minimal diagrams, mostly text + numbers",
        },
        "is_default": False,
    },
    {
        "value": "decide_for_me",
        "label": {
            "uz": "O'zingiz tanlang",
            "ru": "Решите за меня",
            "en": "Decide for me",
        },
        "is_default": True,
    },
]


QUESTION_TEXT: Final[dict[str, Tri]] = {
    "audience": {
        "uz": "Kim uchun tayyorlanmoqda?",
        "ru": "Для кого готовится?",
        "en": "Who is the audience?",
    },
    "duration": {
        "uz": "Taqdimot davomiyligi (daqiqalarda)?",
        "ru": "Длительность доклада (минут)?",
        "en": "How long is the talk (minutes)?",
    },
    "emphasis": {
        "uz": "Taqdimot nimaga ko'proq urg'u bersin?",
        "ru": "На чём презентация должна сделать акцент?",
        "en": "What should the deck emphasise most?",
    },
    "title_style": {
        "uz": "Sarlavha uslubi",
        "ru": "Стиль заголовков",
        "en": "Title style",
    },
    "include_interactive": {
        "uz": "Interaktiv o'quv elementlarini qo'shasizmi?",
        "ru": "Включить интерактивные элементы?",
        "en": "Include interactive learning elements?",
    },
    "theme": {
        "uz": "Vizual mavzu",
        "ru": "Визуальная тема",
        "en": "Visual theme",
    },
    "speaker_notes": {
        "uz": "Notiq uchun izohlar qo'shilsinmi?",
        "ru": "Включить заметки докладчика?",
        "en": "Include speaker notes?",
    },
    "headline_numbers": {
        "uz": "Ajratib ko'rsatmoqchi bo'lgan asosiy raqamlar bormi?",
        "ru": "Какие конкретные ключевые цифры выделить?",
        "en": "Any specific headline numbers you want to feature?",
    },
    "closing_ask": {
        "uz": "Yakuniy taklif yoki call-to-action nima?",
        "ru": "Какой финальный призыв или CTA?",
        "en": "What's the closing ask or call-to-action?",
    },
    "diagrams": {
        "uz": "Diagrammalar",
        "ru": "Диаграммы",
        "en": "Diagrams",
    },
}


HELP_TEXT: Final[dict[str, Tri]] = {
    "duration": {
        "uz": "Bir daqiqaga bir slayd — yaxshi qoida",
        "ru": "Один слайд в минуту — хорошее правило",
        "en": "1 slide per minute is a good rule of thumb",
    },
    "headline_numbers": {
        "uz": "Katta slaydlarga aylanadigan raqamlarni yozing",
        "ru": "Перечислите цифры, которые станут крупными слайдами",
        "en": "Paste the numbers that should become big hero slides",
    },
    "closing_ask": {
        "uz": "CTA bo'lmasa bo'sh qoldiring",
        "ru": "Оставьте пустым, если CTA не нужно",
        "en": "Leave blank for no CTA",
    },
}


PLACEHOLDER_TEXT: Final[dict[str, Tri]] = {
    "headline_numbers": {
        "uz": "masalan, 94.4% suv tejandi, PUE=4055, $1.04M",
        "ru": "например, 94.4% экономии воды, PUE=4055, $1.04M",
        "en": "e.g. 94.4% water saved, PUE=4055, $1.04M cost",
    },
    "closing_ask": {
        "uz": "masalan, hyperscaler X bilan pilot, hammuallif taklifi",
        "ru": "например, пилот с гиперскейлером X, соавторство",
        "en": "e.g. 'pilot site at hyperscaler X', 'co-author invitation'",
    },
}
