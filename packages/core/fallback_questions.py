"""Pre-written fallback research questions per language.

These exist so that an LLM failure during question generation (network
outage, malformed JSON twice in a row) does not leave the user with an
empty interview. They are intentionally generic-but-safe: every fallback
covers one of the four :class:`ResearchQuestionType` values for every
supported language. They will never beat LLM-generated questions, but
they prevent total interview failure.

The structure is a flat dict from :class:`Language` to a list of
``(question_text, question_type)`` tuples. Each language carries at
least one question of every :class:`ResearchQuestionType`.
"""

from __future__ import annotations

from typing import Final

from packages.core.enums import Language, ResearchQuestionType

FallbackEntry = tuple[str, ResearchQuestionType]


_UZ: Final[list[FallbackEntry]] = [
    (
        "Maqolangizning asosiy tezisi nima va qaysi manba uni eng aniq qo'llab-quvvatlaydi?",
        ResearchQuestionType.THESIS_CLARITY,
    ),
    (
        "Yuklangan manbalardan birini tanlang: uning asosiy fikri nima va sizning ishingizga "
        "qanday bog'lanadi?",
        ResearchQuestionType.SOURCE_COVERAGE,
    ),
    (
        "Manbalardan birortasi sizning fikringizga zid keladimi? Qaysi tomonni qo'llaysiz va "
        "nima uchun?",
        ResearchQuestionType.CONTRADICTION,
    ),
    (
        "O'zbekiston kontekstida bu mavzu qanday namoyon bo'ladi? Aniq mahalliy misol keltiring.",
        ResearchQuestionType.ORIGINALITY,
    ),
    (
        "Manbalaringizdagi eng kuchli dalil qaysi va u tezisingizni qanday mustahkamlaydi?",
        ResearchQuestionType.SOURCE_COVERAGE,
    ),
]


_RU: Final[list[FallbackEntry]] = [
    (
        "Каков основной тезис вашей работы и какой источник лучше всего его подтверждает?",
        ResearchQuestionType.THESIS_CLARITY,
    ),
    (
        "Выберите один из загруженных источников: в чём его главный аргумент и как он связан с "
        "вашей темой?",
        ResearchQuestionType.SOURCE_COVERAGE,
    ),
    (
        "Есть ли среди источников такой, который противоречит вашей точке зрения? Какую сторону "
        "вы занимаете и почему?",
        ResearchQuestionType.CONTRADICTION,
    ),
    (
        "Как эта тема проявляется в контексте Узбекистана? Приведите конкретный местный пример.",
        ResearchQuestionType.ORIGINALITY,
    ),
    (
        "Какой довод из ваших источников самый сильный и как именно он поддерживает ваш тезис?",
        ResearchQuestionType.SOURCE_COVERAGE,
    ),
]


_EN: Final[list[FallbackEntry]] = [
    (
        "What is the main thesis of your article, and which source supports it most directly?",
        ResearchQuestionType.THESIS_CLARITY,
    ),
    (
        "Pick one uploaded source: what is its main argument, and how does it connect to your "
        "work?",
        ResearchQuestionType.SOURCE_COVERAGE,
    ),
    (
        "Does any of your sources contradict your view? Which side do you take, and why?",
        ResearchQuestionType.CONTRADICTION,
    ),
    (
        "How does this topic apply in the Uzbekistan context? Give a concrete local example.",
        ResearchQuestionType.ORIGINALITY,
    ),
    (
        "What is the single strongest piece of evidence in your sources, and how does it "
        "reinforce your thesis?",
        ResearchQuestionType.SOURCE_COVERAGE,
    ),
]


FALLBACK_QUESTIONS: Final[dict[Language, list[FallbackEntry]]] = {
    Language.UZ: _UZ,
    Language.RU: _RU,
    Language.EN: _EN,
}


def fallback_questions_for(language: Language) -> list[FallbackEntry]:
    """Return a fresh copy of the fallback list for ``language``.

    Falls back to English when an unrecognised language code is passed,
    matching the rest of the platform's "no silent failure" stance: a
    typo in the project record should not produce an empty interview.
    """

    return list(FALLBACK_QUESTIONS.get(language, _EN))


__all__ = [
    "FALLBACK_QUESTIONS",
    "FallbackEntry",
    "fallback_questions_for",
]
