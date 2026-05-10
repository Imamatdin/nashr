"""Article structure templates: international quality baseline, then localize.

Five article structures live here as data: REFERAT and KURS_ISHI for the
local Uzbek academic formats, ILMIY_MAQOLA in two variants (empirical
IMRAD and theoretical AIMRAD) for international standards, and HISOBOT
for professional reports. Every section carries an ``internal_purpose``
(used as English LLM instruction), a ``quality_checklist`` of structural
expectations, trilingual section titles, and a ``min_citations`` floor.

Layer 1 (this module) enforces structure. Layer 2 (DOCX/PDF exporters)
applies localisation — language, citation format, font, margins — and
must never weaken Layer 1.

This file exceeds the 300-line CLAUDE.md budget intentionally. Five
structurally-identical templates × ~7 sections × (trilingual title +
quality_checklist + multiple flags) is irreducible static data; splitting
across files would just fragment a lookup table without separating any
logic. Per CLAUDE.md the bend is allowed when explicitly flagged — this
is the flag.
"""

from __future__ import annotations

from typing import Final

from pydantic import BaseModel, ConfigDict, Field

from packages.core.enums import ArticleStructure, Language

EMPIRICAL_VARIANT: Final[str] = "empirical"
THEORETICAL_VARIANT: Final[str] = "theoretical"

WORDS_PER_PAGE: Final[int] = 275
ABSTRACT_MIN_WORDS: Final[int] = 150
ABSTRACT_MAX_WORDS: Final[int] = 250


class SectionRequirement(BaseModel):
    """One structural section in an article template.

    ``section_id`` is a stable identifier ("introduction", "methodology",
    "asosiy_qism") used as a key in template lookups and as a
    machine-readable label in LLM prompts. ``internal_purpose`` is the
    English instruction handed to the LLM regardless of output language —
    international quality first, localise the rendered title second.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    section_id: str = Field(min_length=1, max_length=64)
    internal_purpose: str = Field(min_length=1, max_length=1_000)
    quality_checklist: list[str] = Field(min_length=1, max_length=10)
    titles: dict[str, str] = Field(min_length=3, max_length=3)
    is_required: bool = True
    needs_user_input: bool = False
    typical_word_percentage: float = Field(gt=0.0, le=1.0)
    allows_subsections: bool = False
    max_subsections: int = Field(default=1, ge=1, le=10)
    min_citations: int = Field(default=0, ge=0, le=100)


class ArticleStructureTemplate(BaseModel):
    """Complete blueprint for one article kind.

    ``variant`` is non-empty only for :attr:`ArticleStructure.ILMIY_MAQOLA`,
    where it disambiguates IMRAD (``"empirical"``) from AIMRAD
    (``"theoretical"``). For all other structures it is ``None``.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    structure: ArticleStructure
    variant: str | None = Field(default=None, max_length=16)
    sections: list[SectionRequirement] = Field(min_length=1, max_length=20)
    min_pages: int = Field(ge=1, le=60)
    max_pages: int = Field(ge=1, le=60)
    min_references: int = Field(ge=0, le=100)
    max_references: int = Field(ge=0, le=200)


def _titles(uz: str, ru: str, en: str) -> dict[str, str]:
    """Return a trilingual title map keyed by :class:`Language` values."""

    return {Language.UZ.value: uz, Language.RU.value: ru, Language.EN.value: en}


REFERAT_TEMPLATE: Final[ArticleStructureTemplate] = ArticleStructureTemplate(
    structure=ArticleStructure.REFERAT,
    variant=None,
    min_pages=3,
    max_pages=5,
    min_references=5,
    max_references=15,
    sections=[
        SectionRequirement(
            section_id="kirish",
            internal_purpose=(
                "Introduce the topic. State the specific purpose of this report, "
                "explain why the topic is currently relevant, and preview the "
                "structure of the body sections."
            ),
            quality_checklist=[
                "States the specific purpose of the report",
                "Explains why the topic is currently relevant",
                "Previews the structure of the body sections",
            ],
            titles=_titles("Kirish", "Введение", "Introduction"),
            typical_word_percentage=0.15,
            allows_subsections=False,
            min_citations=1,
        ),
        SectionRequirement(
            section_id="asosiy_qism",
            internal_purpose=(
                "Develop the core argument across two to four named sub-sections. "
                "Each sub-section must have a clear analytical question, cite "
                "sources for every factual claim, and connect back to the overall "
                "topic of the report."
            ),
            quality_checklist=[
                "Each sub-section has a clear analytical question",
                "Cites sources for every factual claim",
                "Connects back to the overall topic",
            ],
            titles=_titles("Asosiy qism", "Основная часть", "Main Body"),
            typical_word_percentage=0.70,
            allows_subsections=True,
            max_subsections=4,
            min_citations=2,
        ),
        SectionRequirement(
            section_id="xulosa",
            internal_purpose=(
                "Restate the goal and the outcome. Make no new claims. Keep the "
                "section concise and tied to the introduction."
            ),
            quality_checklist=[
                "Introduces no new factual claims",
                "Restates the goal and the outcome",
                "Stays concise and tied to the introduction",
            ],
            titles=_titles("Xulosa", "Заключение", "Conclusion"),
            typical_word_percentage=0.15,
            allows_subsections=False,
            min_citations=0,
        ),
    ],
)


KURS_ISHI_TEMPLATE: Final[ArticleStructureTemplate] = ArticleStructureTemplate(
    structure=ArticleStructure.KURS_ISHI,
    variant=None,
    min_pages=15,
    max_pages=25,
    min_references=15,
    max_references=30,
    sections=[
        SectionRequirement(
            section_id="kirish",
            internal_purpose=(
                "Introduce the coursework. Ground relevance (dolzarblik) in the "
                "current Uzbek context, state the specific goal (maqsad), break "
                "the goal into concrete tasks (vazifalar), and distinguish "
                "subject (predmet) from object (ob'ekt)."
            ),
            quality_checklist=[
                "Relevance is grounded in current context",
                "Goal is specific, not generic",
                "Tasks are concrete actions",
                "Subject and object are distinguished",
            ],
            titles=_titles("Kirish", "Введение", "Introduction"),
            typical_word_percentage=0.10,
            allows_subsections=False,
            min_citations=2,
        ),
        SectionRequirement(
            section_id="nazariy_asos",
            internal_purpose=(
                "First chapter: theoretical foundation. Group sources thematically "
                "rather than by author, identify at least one gap in prior work, "
                "and give every sub-section its own clear thesis."
            ),
            quality_checklist=[
                "Sources grouped thematically, not by author",
                "Identifies at least one gap in prior work",
                "Each sub-section has its own clear thesis",
            ],
            titles=_titles(
                "1-bob: Nazariy asos",
                "Глава 1: Теоретические основы",
                "Chapter 1: Theoretical Foundation",
            ),
            typical_word_percentage=0.40,
            allows_subsections=True,
            max_subsections=3,
            min_citations=8,
        ),
        SectionRequirement(
            section_id="amaliy_qism",
            internal_purpose=(
                "Second chapter: practical/applied analysis. Use specific examples "
                "rather than abstractions, connect every claim back to the theory "
                "of Chapter 1, and incorporate local evidence where available."
            ),
            quality_checklist=[
                "Contains specific examples, not abstractions",
                "Connects every claim back to Chapter 1 theory",
                "Includes local evidence where available",
            ],
            titles=_titles(
                "2-bob: Amaliy qism", "Глава 2: Практическая часть", "Chapter 2: Practical Analysis"
            ),
            typical_word_percentage=0.40,
            allows_subsections=True,
            max_subsections=3,
            needs_user_input=True,
            min_citations=5,
        ),
        SectionRequirement(
            section_id="xulosa",
            internal_purpose=(
                "Conclusion. Reference each task from the introduction, state "
                "what was achieved, and suggest implications for further work."
            ),
            quality_checklist=[
                "References each task from the introduction",
                "States what was achieved",
                "Suggests implications for further work",
            ],
            titles=_titles("Xulosa", "Заключение", "Conclusion"),
            typical_word_percentage=0.10,
            allows_subsections=False,
            min_citations=0,
        ),
    ],
)


def _ilmiy_common_head() -> list[SectionRequirement]:
    """Sections shared by both empirical and theoretical research articles."""

    return [
        SectionRequirement(
            section_id="abstract",
            internal_purpose=(
                "Self-contained abstract: background, objective, method, key "
                "quantitative or analytical result, and conclusion. 150-250 words. "
                "No citations. Must stand alone."
            ),
            quality_checklist=[
                "150-250 words exactly",
                "Contains background, objective, method, key result, conclusion",
                "Self-contained: no citations, no abbreviations defined elsewhere",
            ],
            titles=_titles("Annotatsiya", "Аннотация", "Abstract"),
            typical_word_percentage=0.05,
            allows_subsections=False,
            min_citations=0,
        ),
        SectionRequirement(
            section_id="keywords",
            internal_purpose=(
                "Five to ten keywords. Include at least one methodology keyword. "
                "Avoid single generic words; prefer two-word noun phrases."
            ),
            quality_checklist=[
                "Five to ten keywords",
                "Includes at least one methodology keyword",
                "No single generic words",
            ],
            titles=_titles("Kalit so'zlar", "Ключевые слова", "Keywords"),
            typical_word_percentage=0.01,
            allows_subsections=False,
            min_citations=0,
        ),
        SectionRequirement(
            section_id="introduction",
            internal_purpose=(
                "Identify the research gap (what is NOT yet known), state an "
                "explicit research question or hypothesis, preview the paper's "
                "contribution, and funnel from broad context to the specific "
                "problem."
            ),
            quality_checklist=[
                "Identifies an explicit research gap",
                "States a research question or hypothesis explicitly",
                "Previews the paper's contribution",
                "Funnels from broad to specific",
            ],
            titles=_titles("Kirish", "Введение", "Introduction"),
            typical_word_percentage=0.12,
            allows_subsections=False,
            min_citations=8,
        ),
        SectionRequirement(
            section_id="literature_review",
            internal_purpose=(
                "Thematic synthesis of prior work. Identify debates, agreements, "
                "and gaps. Position this paper relative to the existing "
                "literature; do not summarise paper by paper."
            ),
            quality_checklist=[
                "Synthesises thematically, not paper-by-paper",
                "Identifies debates, agreements, and gaps",
                "Positions this paper relative to prior work",
            ],
            titles=_titles("Adabiyotlar tahlili", "Обзор литературы", "Literature Review"),
            typical_word_percentage=0.20,
            allows_subsections=False,
            min_citations=10,
        ),
    ]


def _ilmiy_common_tail() -> list[SectionRequirement]:
    """Discussion + Conclusion shared by both research-article variants."""

    return [
        SectionRequirement(
            section_id="discussion",
            internal_purpose=(
                "Interpret each key result. Compare with at least two prior "
                "studies. Address limitations of the work. Discuss practical "
                "and theoretical implications."
            ),
            quality_checklist=[
                "Interprets each key result",
                "Compares with at least two prior studies",
                "Addresses limitations explicitly",
                "Discusses implications",
            ],
            titles=_titles("Muhokama", "Обсуждение", "Discussion"),
            typical_word_percentage=0.18,
            allows_subsections=False,
            min_citations=5,
        ),
        SectionRequirement(
            section_id="conclusion",
            internal_purpose=(
                "Restate the research question and the answer. State the "
                "contribution. Suggest concrete future work. No new arguments."
            ),
            quality_checklist=[
                "Restates research question and answer",
                "States the contribution",
                "Suggests concrete future work",
                "Introduces no new arguments",
            ],
            titles=_titles("Xulosa", "Заключение", "Conclusion"),
            typical_word_percentage=0.09,
            allows_subsections=False,
            min_citations=0,
        ),
    ]


ILMIY_MAQOLA_EMPIRICAL_TEMPLATE: Final[ArticleStructureTemplate] = ArticleStructureTemplate(
    structure=ArticleStructure.ILMIY_MAQOLA,
    variant=EMPIRICAL_VARIANT,
    min_pages=6,
    max_pages=12,
    min_references=20,
    max_references=40,
    sections=[
        *_ilmiy_common_head(),
        SectionRequirement(
            section_id="methodology",
            internal_purpose=(
                "Methodology. Describe data source, sample, instruments, "
                "procedures, and analysis techniques. Justify choices and "
                "acknowledge methodological limitations."
            ),
            quality_checklist=[
                "Names data source and sample",
                "Describes instruments and procedures",
                "Justifies analysis techniques",
                "Acknowledges methodological limitations",
            ],
            titles=_titles("Metodologiya", "Методология", "Methodology"),
            typical_word_percentage=0.15,
            allows_subsections=False,
            needs_user_input=True,
            min_citations=3,
        ),
        SectionRequirement(
            section_id="results",
            internal_purpose=(
                "Results only. Present findings without interpretation. Use "
                "specific numbers, data, and observations. Organise by research "
                "question or hypothesis."
            ),
            quality_checklist=[
                "Presents findings without interpretation",
                "Uses specific numbers, data, observations",
                "Organised by research question",
            ],
            titles=_titles("Natijalar", "Результаты", "Results"),
            typical_word_percentage=0.20,
            allows_subsections=False,
            needs_user_input=True,
            min_citations=0,
        ),
        *_ilmiy_common_tail(),
    ],
)


ILMIY_MAQOLA_THEORETICAL_TEMPLATE: Final[ArticleStructureTemplate] = ArticleStructureTemplate(
    structure=ArticleStructure.ILMIY_MAQOLA,
    variant=THEORETICAL_VARIANT,
    min_pages=6,
    max_pages=12,
    min_references=20,
    max_references=40,
    sections=[
        *_ilmiy_common_head(),
        SectionRequirement(
            section_id="theoretical_framework",
            internal_purpose=(
                "Theoretical framework. Name the theoretical lens, define key "
                "concepts, justify why this framework was chosen, and "
                "distinguish it from alternative frameworks."
            ),
            quality_checklist=[
                "Names the theoretical lens",
                "Defines key concepts",
                "Justifies framework choice",
                "Distinguishes from alternative frameworks",
            ],
            titles=_titles("Nazariy asos", "Теоретическая основа", "Theoretical Framework"),
            typical_word_percentage=0.15,
            allows_subsections=False,
            min_citations=5,
        ),
        SectionRequirement(
            section_id="analysis",
            internal_purpose=(
                "Analysis. Apply the theoretical framework systematically to "
                "the material. Present analytical observations organised by "
                "theme or by framework component."
            ),
            quality_checklist=[
                "Applies the framework systematically",
                "Presents analytical observations",
                "Organised by theme or framework component",
            ],
            titles=_titles("Tahlil", "Анализ", "Analysis"),
            typical_word_percentage=0.20,
            allows_subsections=True,
            max_subsections=3,
            min_citations=3,
        ),
        *_ilmiy_common_tail(),
    ],
)


HISOBOT_TEMPLATE: Final[ArticleStructureTemplate] = ArticleStructureTemplate(
    structure=ArticleStructure.HISOBOT,
    variant=None,
    min_pages=5,
    max_pages=10,
    min_references=10,
    max_references=25,
    sections=[
        SectionRequirement(
            section_id="executive_summary",
            internal_purpose=(
                "Executive summary. Actionable. Contains the key numbers and "
                "states the recommendations upfront so a busy reader can act "
                "on the report without finishing it."
            ),
            quality_checklist=[
                "Actionable for a busy reader",
                "Contains key numbers",
                "States recommendations upfront",
            ],
            titles=_titles("Qisqacha xulosa", "Краткое резюме", "Executive Summary"),
            typical_word_percentage=0.10,
            allows_subsections=False,
            min_citations=0,
        ),
        SectionRequirement(
            section_id="introduction",
            internal_purpose=(
                "Introduce the report's scope, the question it answers, and the "
                "audience for whom it was written."
            ),
            quality_checklist=[
                "States scope of the report",
                "Names the audience",
                "States the question the report answers",
            ],
            titles=_titles("Kirish", "Введение", "Introduction"),
            typical_word_percentage=0.10,
            allows_subsections=False,
            min_citations=1,
        ),
        SectionRequirement(
            section_id="background",
            internal_purpose=(
                "Background. Sufficient context for a reader unfamiliar with "
                "the situation to understand the analysis that follows."
            ),
            quality_checklist=[
                "Provides enough context for an unfamiliar reader",
                "Cites prior work or prior reports where relevant",
            ],
            titles=_titles("Asosiy ma'lumot", "Предыстория", "Background"),
            typical_word_percentage=0.15,
            allows_subsections=False,
            min_citations=2,
        ),
        SectionRequirement(
            section_id="analysis",
            internal_purpose=(
                "Analysis. Each sub-section has a clear analytical question, "
                "uses data or evidence, and produces specific findings."
            ),
            quality_checklist=[
                "Each sub-section has a clear analytical question",
                "Uses data or evidence",
                "Findings are specific, not generic",
            ],
            titles=_titles("Tahlil", "Анализ", "Analysis"),
            typical_word_percentage=0.30,
            allows_subsections=True,
            max_subsections=4,
            min_citations=4,
        ),
        SectionRequirement(
            section_id="findings",
            internal_purpose=(
                "Findings. Distil the analysis into a numbered or bulleted list "
                "of concrete findings each tied to its supporting evidence."
            ),
            quality_checklist=[
                "Findings are numbered or bulleted",
                "Each finding tied to supporting evidence",
            ],
            titles=_titles("Topilmalar", "Выводы", "Findings"),
            typical_word_percentage=0.13,
            allows_subsections=False,
            min_citations=2,
        ),
        SectionRequirement(
            section_id="recommendations",
            internal_purpose=(
                "Recommendations. Each recommendation is linked to a specific "
                "finding, is actionable (verb-led), and is prioritised."
            ),
            quality_checklist=[
                "Each recommendation links to a specific finding",
                "Each recommendation is actionable",
                "Recommendations are prioritised",
            ],
            titles=_titles("Tavsiyalar", "Рекомендации", "Recommendations"),
            typical_word_percentage=0.15,
            allows_subsections=False,
            min_citations=0,
        ),
        SectionRequirement(
            section_id="conclusion",
            internal_purpose=(
                "Conclusion. Restate the question, summarise the findings, and "
                "close with the highest-priority recommendation."
            ),
            quality_checklist=[
                "Restates the question",
                "Summarises findings",
                "Closes with the top recommendation",
            ],
            titles=_titles("Xulosa", "Заключение", "Conclusion"),
            typical_word_percentage=0.07,
            allows_subsections=False,
            min_citations=0,
        ),
    ],
)


_ALL_TEMPLATES: Final[tuple[ArticleStructureTemplate, ...]] = (
    REFERAT_TEMPLATE,
    KURS_ISHI_TEMPLATE,
    ILMIY_MAQOLA_EMPIRICAL_TEMPLATE,
    ILMIY_MAQOLA_THEORETICAL_TEMPLATE,
    HISOBOT_TEMPLATE,
)


def all_templates() -> tuple[ArticleStructureTemplate, ...]:
    """Return every defined template in declaration order."""

    return _ALL_TEMPLATES


def get_template(
    structure: ArticleStructure, variant: str | None = None
) -> ArticleStructureTemplate:
    """Resolve a template by structure and (for ilmiy_maqola) variant.

    For :attr:`ArticleStructure.ILMIY_MAQOLA` ``variant`` must be either
    :data:`EMPIRICAL_VARIANT` or :data:`THEORETICAL_VARIANT`. For every
    other structure ``variant`` is ignored.
    """

    if structure is ArticleStructure.ILMIY_MAQOLA:
        chosen_variant = variant or THEORETICAL_VARIANT
        for tpl in _ALL_TEMPLATES:
            if tpl.structure is structure and tpl.variant == chosen_variant:
                return tpl
        raise ValueError(
            f"Unknown ilmiy_maqola variant: {variant!r}. "
            f"Expected {EMPIRICAL_VARIANT!r} or {THEORETICAL_VARIANT!r}."
        )

    for tpl in _ALL_TEMPLATES:
        if tpl.structure is structure and tpl.variant is None:
            return tpl
    raise ValueError(f"No template registered for structure {structure!r}")


def title_for(section: SectionRequirement, language: Language) -> str:
    """Return the section title in ``language``, falling back to English."""

    return section.titles.get(language.value, section.titles[Language.EN.value])


__all__ = [
    "ABSTRACT_MAX_WORDS",
    "ABSTRACT_MIN_WORDS",
    "EMPIRICAL_VARIANT",
    "HISOBOT_TEMPLATE",
    "ILMIY_MAQOLA_EMPIRICAL_TEMPLATE",
    "ILMIY_MAQOLA_THEORETICAL_TEMPLATE",
    "KURS_ISHI_TEMPLATE",
    "REFERAT_TEMPLATE",
    "THEORETICAL_VARIANT",
    "WORDS_PER_PAGE",
    "ArticleStructureTemplate",
    "SectionRequirement",
    "all_templates",
    "get_template",
    "title_for",
]
