"""Localised (uz/ru/en/kaa) text for every interview question and option.

Separated from :mod:`packages.presentation.interview` because the
copy is bulky and the engine logic is easier to read without it. The
question identifiers, option values, and ordering live here so the
engine can iterate the structure once and emit a localised
:class:`PresentationInterviewQuestions`.

Karakalpak (``kaa``) is a peer of Uzbek, not a dialect. Vocabulary,
phonology, and orthography diverge enough that a kaa speaker should
see ``Kelesi`` rather than ``Keyingi`` for "next", and ``Qáte`` rather
than ``Noto'g'ri`` for "wrong". Every translation entry therefore
provides a kaa string in addition to uz/ru/en.
"""

from __future__ import annotations

from typing import Final, TypedDict


class Tri(TypedDict):
    """Localised string keyed by Nashr's supported language codes."""

    uz: str
    ru: str
    en: str
    kaa: str


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
            "kaa": "Mektep oqıwshıları (9-11 klass)",
        },
        "is_default": False,
    },
    {
        "value": "undergraduate",
        "label": {
            "uz": "Bakalavr talabalari",
            "ru": "Студенты бакалавриата",
            "en": "University undergraduates",
            "kaa": "Bakalavr studentleri",
        },
        "is_default": False,
    },
    {
        "value": "graduate",
        "label": {
            "uz": "Magistratura talabalari",
            "ru": "Студенты магистратуры",
            "en": "Graduate students",
            "kaa": "Magistratura studentleri",
        },
        "is_default": False,
    },
    {
        "value": "academic_conference",
        "label": {
            "uz": "Akademik konferentsiya",
            "ru": "Академическая конференция",
            "en": "Academic conference",
            "kaa": "Akademiyalıq konferenciya",
        },
        "is_default": False,
    },
    {
        "value": "mixed_academic_industry",
        "label": {
            "uz": "Akademik va sanoat aralash",
            "ru": "Академия и индустрия",
            "en": "Mixed academic + industry",
            "kaa": "Akademiya hám sanaat aralas",
        },
        "is_default": False,
    },
    {
        "value": "professional",
        "label": {
            "uz": "Mutaxassis / biznes",
            "ru": "Профессиональная аудитория / бизнес",
            "en": "Professional / business",
            "kaa": "Qánige / biznes",
        },
        "is_default": False,
    },
    {
        "value": "general_public",
        "label": {
            "uz": "Keng jamoatchilik",
            "ru": "Широкая аудитория",
            "en": "General public",
            "kaa": "Keń jámiyetshilik",
        },
        "is_default": False,
    },
    {
        "value": "decide_for_me",
        "label": {
            "uz": "O'zingiz tanlang",
            "ru": "Решите за меня",
            "en": "Decide for me",
            "kaa": "Ózińiz tańlań",
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
            "kaa": "Máselediń qoyılıwı",
        },
        "is_default": False,
    },
    {
        "value": "technical_mechanism",
        "label": {
            "uz": "Texnik mexanizm",
            "ru": "Технический механизм",
            "en": "Technical mechanism",
            "kaa": "Texnikalıq mexanizm",
        },
        "is_default": False,
    },
    {
        "value": "methodology",
        "label": {
            "uz": "Metodologiya",
            "ru": "Методология",
            "en": "Methodology",
            "kaa": "Metodologiya",
        },
        "is_default": False,
    },
    {
        "value": "results_numbers",
        "label": {
            "uz": "Natijalar / raqamlar",
            "ru": "Результаты / цифры",
            "en": "Results / numbers",
            "kaa": "Nátiyjeler / sanlar",
        },
        "is_default": False,
    },
    {
        "value": "roadmap_scalability",
        "label": {
            "uz": "Yo'l xaritasi / miqyoslash",
            "ru": "План развития / масштабируемость",
            "en": "Roadmap / scalability",
            "kaa": "Jol kartası / kólemlestiriw",
        },
        "is_default": False,
    },
    {
        "value": "decide_for_me",
        "label": {
            "uz": "O'zingiz tanlang",
            "ru": "Решите за меня",
            "en": "Decide for me",
            "kaa": "Ózińiz tańlań",
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
            "kaa": "Qısqa temalı baslıqlar ('Metodologiya', 'Nátiyjeler')",
        },
        "is_default": False,
    },
    {
        "value": "takeaway",
        "label": {
            "uz": "Xulosa sarlavhalari ('Sietlda 94% suv tejaldi')",
            "ru": "Заголовки-выводы ('94% экономии воды в Сиэтле')",
            "en": "Takeaway titles ('94% water savings in Seattle')",
            "kaa": "Juwmaq baslıqlar ('Sietlde 94% suw únemlendi')",
        },
        "is_default": False,
    },
    {
        "value": "decide_for_me",
        "label": {
            "uz": "O'zingiz tanlang",
            "ru": "Решите за меня",
            "en": "Decide for me",
            "kaa": "Ózińiz tańlań",
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
            "kaa": "Awa — viktorinalar, juplastırıw, shınıǵıwlar",
        },
        "is_default": False,
    },
    {
        "value": "no",
        "label": {
            "uz": "Yo'q — faqat kontent",
            "ru": "Нет — только контент",
            "en": "No — content only",
            "kaa": "Yaq — tek kontent",
        },
        "is_default": False,
    },
    {
        "value": "decide_for_me",
        "label": {
            "uz": "O'zingiz tanlang",
            "ru": "Решите за меня",
            "en": "Decide for me",
            "kaa": "Ózińiz tańlań",
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
            "kaa": "Jaqtı fon",
        },
        "is_default": False,
    },
    {
        "value": "dark",
        "label": {
            "uz": "Qora fon",
            "ru": "Тёмный фон",
            "en": "Dark backgrounds",
            "kaa": "Qarańǵı fon",
        },
        "is_default": False,
    },
    {
        "value": "decide_for_me",
        "label": {
            "uz": "O'zingiz tanlang",
            "ru": "Решите за меня",
            "en": "Decide for me",
            "kaa": "Ózińiz tańlań",
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
            "kaa": "Awa — hár slaydqa tolıq tekst",
        },
        "is_default": False,
    },
    {
        "value": "brief_talking_points",
        "label": {
            "uz": "Qisqacha tezislar",
            "ru": "Краткие тезисы",
            "en": "Brief talking points only",
            "kaa": "Qısqa tezisler",
        },
        "is_default": False,
    },
    {
        "value": "no_notes",
        "label": {
            "uz": "Yo'q",
            "ru": "Без заметок",
            "en": "No notes",
            "kaa": "Yaq",
        },
        "is_default": False,
    },
    {
        "value": "decide_for_me",
        "label": {
            "uz": "O'zingiz tanlang",
            "ru": "Решите за меня",
            "en": "Decide for me",
            "kaa": "Ózińiz tańlań",
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
            "kaa": "Awa — SVG diagrammalardı qurastırıw",
        },
        "is_default": False,
    },
    {
        "value": "placeholder",
        "label": {
            "uz": "Keyin men beradigan joy qoldirish",
            "ru": "Оставить место для моих диаграмм",
            "en": "Use placeholder slots for diagrams I'll provide later",
            "kaa": "Keyin men beretuǵın orın qaldırıw",
        },
        "is_default": False,
    },
    {
        "value": "minimal_text",
        "label": {
            "uz": "Minimal diagramma, asosan matn va raqamlar",
            "ru": "Минимум диаграмм, в основном текст и числа",
            "en": "Minimal diagrams, mostly text + numbers",
            "kaa": "Minimal diagramma, tiykarınan tekst hám sanlar",
        },
        "is_default": False,
    },
    {
        "value": "decide_for_me",
        "label": {
            "uz": "O'zingiz tanlang",
            "ru": "Решите за меня",
            "en": "Decide for me",
            "kaa": "Ózińiz tańlań",
        },
        "is_default": True,
    },
]


QUESTION_TEXT: Final[dict[str, Tri]] = {
    "audience": {
        "uz": "Kim uchun tayyorlanmoqda?",
        "ru": "Для кого готовится?",
        "en": "Who is the audience?",
        "kaa": "Kim ushın tayarlanbaqta?",
    },
    "duration": {
        "uz": "Taqdimot davomiyligi (daqiqalarda)?",
        "ru": "Длительность доклада (минут)?",
        "en": "How long is the talk (minutes)?",
        "kaa": "Bayanlaw uzaqlıǵı (minutlarda)?",
    },
    "emphasis": {
        "uz": "Taqdimot nimaga ko'proq urg'u bersin?",
        "ru": "На чём презентация должна сделать акцент?",
        "en": "What should the deck emphasise most?",
        "kaa": "Prezentaciya nege kóbirek itibar bersin?",
    },
    "title_style": {
        "uz": "Sarlavha uslubi",
        "ru": "Стиль заголовков",
        "en": "Title style",
        "kaa": "Baslıq usılı",
    },
    "include_interactive": {
        "uz": "Interaktiv o'quv elementlarini qo'shasizmi?",
        "ru": "Включить интерактивные элементы?",
        "en": "Include interactive learning elements?",
        "kaa": "Interaktiv úyreniw elementlerin qosasız ba?",
    },
    "theme": {
        "uz": "Vizual mavzu",
        "ru": "Визуальная тема",
        "en": "Visual theme",
        "kaa": "Vizual tema",
    },
    "speaker_notes": {
        "uz": "Notiq uchun izohlar qo'shilsinmi?",
        "ru": "Включить заметки докладчика?",
        "en": "Include speaker notes?",
        "kaa": "Bayanlawshı ushın eskertpeler qosılsın ba?",
    },
    "headline_numbers": {
        "uz": "Ajratib ko'rsatmoqchi bo'lgan asosiy raqamlar bormi?",
        "ru": "Какие конкретные ключевые цифры выделить?",
        "en": "Any specific headline numbers you want to feature?",
        "kaa": "Ajıratıp kórsetkińiz kelgen tiykarǵı sanlar bar ma?",
    },
    "closing_ask": {
        "uz": "Yakuniy taklif yoki call-to-action nima?",
        "ru": "Какой финальный призыв или CTA?",
        "en": "What's the closing ask or call-to-action?",
        "kaa": "Juwmaqlawshı usınıs yamasa CTA ne?",
    },
    "diagrams": {
        "uz": "Diagrammalar",
        "ru": "Диаграммы",
        "en": "Diagrams",
        "kaa": "Diagrammalar",
    },
}


HELP_TEXT: Final[dict[str, Tri]] = {
    "duration": {
        "uz": "Bir daqiqaga bir slayd — yaxshi qoida",
        "ru": "Один слайд в минуту — хорошее правило",
        "en": "1 slide per minute is a good rule of thumb",
        "kaa": "Bir minutqa bir slayd — jaqsı qaǵıyda",
    },
    "headline_numbers": {
        "uz": "Katta slaydlarga aylanadigan raqamlarni yozing",
        "ru": "Перечислите цифры, которые станут крупными слайдами",
        "en": "Paste the numbers that should become big hero slides",
        "kaa": "Úlken slaydlarǵa aylanatuǵın sanlardı jazıń",
    },
    "closing_ask": {
        "uz": "CTA bo'lmasa bo'sh qoldiring",
        "ru": "Оставьте пустым, если CTA не нужно",
        "en": "Leave blank for no CTA",
        "kaa": "CTA bolmasa bos qaldırıń",
    },
}


PLACEHOLDER_TEXT: Final[dict[str, Tri]] = {
    "headline_numbers": {
        "uz": "masalan, 94.4% suv tejandi, PUE=4055, $1.04M",
        "ru": "например, 94.4% экономии воды, PUE=4055, $1.04M",
        "en": "e.g. 94.4% water saved, PUE=4055, $1.04M cost",
        "kaa": "máselen, 94.4% suw únemlendi, PUE=4055, $1.04M",
    },
    "closing_ask": {
        "uz": "masalan, hyperscaler X bilan pilot, hammuallif taklifi",
        "ru": "например, пилот с гиперскейлером X, соавторство",
        "en": "e.g. 'pilot site at hyperscaler X', 'co-author invitation'",
        "kaa": "máselen, hyperscaler X menen pilot, birge avtor usınıs",
    },
}
