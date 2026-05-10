"""Heuristic validators that check a drafted section against its checklist.

These validators are intentionally regex/keyword-based, not LLM-based: a
fast deterministic gate that catches the obvious failures (an introduction
that never mentions a research gap, a results section with no numbers, a
conclusion that introduces brand-new claims) so the drafter can decide
whether to spend an LLM call on a revision pass.

A few false positives or false negatives are acceptable. The point is to
flag failures cheaply — the revision prompt addresses the rest, and any
quality bar that requires real semantic judgement is left to a later
verification pass.

Each validator takes a section's plain text and returns ``bool``. Names
should map to the checklist strings declared by the
:mod:`packages.workers.article.article_structures` templates; the
:func:`run_checks` driver matches checklist items to validators by
substring on the checklist phrasing, with a permissive default of PASSED
for items we cannot reliably detect.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Final

from packages.core.models.article import QualityCheckResult

# ---------------------------------------------------------------------------
# Universal validators (apply to every article structure)
# ---------------------------------------------------------------------------


_PURPOSE_KEYWORDS: Final[tuple[str, ...]] = (
    "purpose",
    "aim",
    "goal",
    "objective",
    "this paper",
    "this report",
    "this article",
    "maqsad",
    "vazifa",
    "цель",
    "задача",
)


def has_specific_purpose(text: str) -> bool:
    """Detect any phrasing that names the section's purpose explicitly."""

    lower = text.lower()
    return any(kw in lower for kw in _PURPOSE_KEYWORDS)


_CITATION_RE: Final[re.Pattern[str]] = re.compile(r"\[[A-Za-z0-9_\-]{1,64}\]")


def has_citations(text: str, min_count: int = 1) -> bool:
    """Return True when at least ``min_count`` ``[source_id]`` markers are present."""

    return len(_CITATION_RE.findall(text)) >= min_count


def within_word_target(text: str, target: int, tolerance: float = 0.2) -> bool:
    """Check whether ``text``'s word count lies within ``target ± tolerance*target``."""

    words = len(text.split())
    if target <= 0:
        return True
    low = round(target * (1 - tolerance))
    high = round(target * (1 + tolerance))
    return low <= words <= high


_NEW_CLAIM_PATTERNS: Final[tuple[str, ...]] = (
    "for the first time",
    "we now report",
    "this paper reveals for the first time",
    "ushbu maqolada birinchi marta",
    "впервые в данной работе",
)


def no_new_claims_in_conclusion(text: str) -> bool:
    """Heuristic: a conclusion should not announce brand-new findings."""

    lower = text.lower()
    return not any(pat in lower for pat in _NEW_CLAIM_PATTERNS)


# ---------------------------------------------------------------------------
# Research-article validators (ilmiy_maqola)
# ---------------------------------------------------------------------------


_GAP_KEYWORDS: Final[tuple[str, ...]] = (
    "gap in the literature",
    "research gap",
    "is lacking",
    "remains lacking",
    "remains understudied",
    "understudied",
    "unexplored",
    "underexplored",
    "insufficient attention",
    "has not been",
    "yetarli emas",
    "etarli emas",
    "kam o'rganilgan",
    "kam organilgan",
    "yetarlicha o'rganilmagan",
    "недостаточно",
    "малоизучен",
    "недостаточно изучен",
    "пробел в литературе",
)


def has_research_gap(text: str) -> bool:
    """Detect language naming a gap, lacuna, or under-studied area."""

    lower = text.lower()
    return any(kw in lower for kw in _GAP_KEYWORDS)


_QUESTION_KEYWORDS: Final[tuple[str, ...]] = (
    "research question",
    "this paper asks",
    "we ask whether",
    "hypothesis",
    "we hypothesise",
    "we hypothesize",
    "tadqiqot savoli",
    "gipoteza",
    "исследовательский вопрос",
    "гипотеза",
)


def has_research_question(text: str) -> bool:
    """Detect an explicit research question or stated hypothesis."""

    lower = text.lower()
    if "?" in text and any(
        marker in lower
        for marker in (
            "how ",
            "why ",
            "what ",
            "to what extent",
            "qanday",
            "nima uchun",
            "как ",
            "почему ",
            "что ",
        )
    ):
        return True
    return any(kw in lower for kw in _QUESTION_KEYWORDS)


_QUANT_RE: Final[re.Pattern[str]] = re.compile(
    r"\d+\.?\d*\s*%|\d+\.?\d*\s*±|p\s*[<>=]|\bn\s*=\s*\d+|\bм\s*=\s*\d+",
    re.IGNORECASE,
)


def has_quantitative_result(text: str) -> bool:
    """Look for any number-with-unit, p-value, or sample-size marker."""

    return bool(_QUANT_RE.search(text))


_LIMITATION_KEYWORDS: Final[tuple[str, ...]] = (
    "limitation",
    "constraint",
    "however, this study",
    "this study is limited",
    "we did not",
    "could not be addressed",
    "cheklov",
    "kamchilik",
    "ограничен",
    "ограничение",
    "недостаток",
)


def has_limitations(text: str) -> bool:
    """Detect language acknowledging the work's limits."""

    lower = text.lower()
    return any(kw in lower for kw in _LIMITATION_KEYWORDS)


_CONTRIBUTION_KEYWORDS: Final[tuple[str, ...]] = (
    "this paper contributes",
    "our contribution",
    "we contribute",
    "the contribution of this",
    "this study contributes",
    "ushbu maqolaning hissasi",
    "tadqiqotning hissasi",
    "вклад данной работы",
    "вклад настоящей работы",
)


def has_contribution_statement(text: str) -> bool:
    """Detect an explicit contribution statement."""

    lower = text.lower()
    return any(kw in lower for kw in _CONTRIBUTION_KEYWORDS)


_THEMATIC_KEYWORDS: Final[tuple[str, ...]] = (
    "broadly",
    "first strand",
    "second strand",
    "two main strands",
    "thematic",
    "in this thread",
    "another body of work",
    "another line of research",
    "scholars who",
    "scholars argue",
    "literature converges on",
    "yo'nalishlar",
    "tadqiqot yo'nalishlari",
    "направления",
    "линия исследований",
)


def has_thematic_grouping(text: str) -> bool:
    """Detect language that groups prior work thematically rather than serially."""

    lower = text.lower()
    return any(kw in lower for kw in _THEMATIC_KEYWORDS)


_INTERPRET_KEYWORDS: Final[tuple[str, ...]] = (
    "this suggests",
    "this indicates",
    "the implication",
    "we interpret",
    "we argue",
    "this means that",
    "ma'no kasb etadi",
    "это означает",
    "это указывает",
)


def separates_results_from_interpretation(text: str) -> bool:
    """Heuristic: a Results section should NOT contain interpretive verbs.

    Returns True (passed) when no interpretation cues are detected — i.e.
    the writer kept Results purely descriptive. Returns False if "this
    suggests" / "we argue" etc. appear, which generally belong in
    Discussion rather than Results.
    """

    lower = text.lower()
    return not any(kw in lower for kw in _INTERPRET_KEYWORDS)


# ---------------------------------------------------------------------------
# Kurs ishi validators (Uzbek coursework)
# ---------------------------------------------------------------------------


_DOLZARBLIK_KEYWORDS: Final[tuple[str, ...]] = (
    "dolzarb",
    "dolzarbligi",
    "dolzarblik",
    "relevance",
    "relevant today",
    "currently relevant",
    "актуальн",
)


def has_dolzarblik(text: str) -> bool:
    """Detect grounding in current relevance ("dolzarblik")."""

    lower = text.lower()
    return any(kw in lower for kw in _DOLZARBLIK_KEYWORDS)


_MAQSAD_KEYWORDS: Final[tuple[str, ...]] = ("maqsad", "goal", "objective", "цель")
_VAZIFALAR_KEYWORDS: Final[tuple[str, ...]] = (
    "vazifa",
    "vazifalar",
    "task",
    "tasks",
    "objectives",
    "задача",
    "задачи",
)


def has_maqsad_and_vazifalar(text: str) -> bool:
    """Detect that BOTH the goal and the concrete tasks are stated."""

    lower = text.lower()
    has_maqsad = any(kw in lower for kw in _MAQSAD_KEYWORDS)
    has_vazifalar = any(kw in lower for kw in _VAZIFALAR_KEYWORDS)
    return has_maqsad and has_vazifalar


_LOCAL_KEYWORDS: Final[tuple[str, ...]] = (
    "uzbekistan",
    "uzbek",
    "tashkent",
    "samarkand",
    "bukhara",
    "o'zbekiston",
    "ozbekiston",
    "toshkent",
    "samarqand",
    "buxoro",
    "узбекистан",
    "узбекск",
    "ташкент",
    "самарканд",
    "бухара",
)


def has_local_examples(text: str) -> bool:
    """Detect at least one local (Uzbek) example or named locale."""

    lower = text.lower()
    return any(kw in lower for kw in _LOCAL_KEYWORDS)


# ---------------------------------------------------------------------------
# Hisobot / report validators
# ---------------------------------------------------------------------------


_RECOMMENDATION_VERBS: Final[tuple[str, ...]] = (
    "recommend",
    "should",
    "must",
    "we propose",
    "implement",
    "establish",
    "prioritise",
    "prioritize",
    "tavsiya",
    "joriy etish",
    "рекомендуется",
    "необходимо",
    "следует",
)


def has_actionable_recommendations(text: str) -> bool:
    """Detect verb-led, actionable recommendation language."""

    lower = text.lower()
    return any(kw in lower for kw in _RECOMMENDATION_VERBS)


_NUMBERED_LIST_RE: Final[re.Pattern[str]] = re.compile(
    r"(?m)^\s*(?:[0-9]+[.)]|[-*•])\s+\S",
)


def has_numbered_or_bulleted_list(text: str) -> bool:
    """Detect that the section presents at least one numbered/bulleted item."""

    return bool(_NUMBERED_LIST_RE.search(text))


# ---------------------------------------------------------------------------
# Checklist driver
# ---------------------------------------------------------------------------


_VALIDATORS: Final[tuple[tuple[tuple[str, ...], Callable[[str], bool]], ...]] = (
    # research gap
    (
        (
            "research gap",
            "explicit research gap",
            "identifies an explicit research gap",
            "gap in prior work",
        ),
        has_research_gap,
    ),
    # research question
    (
        ("research question", "states a research question", "research question or hypothesis"),
        has_research_question,
    ),
    # quantitative result
    (
        (
            "quantitative",
            "specific numbers",
            "uses specific numbers",
            "key numbers",
            "specific numbers, data",
        ),
        has_quantitative_result,
    ),
    # limitations
    (
        ("limitation", "addresses limitations", "acknowledges methodological limitations"),
        has_limitations,
    ),
    # contribution
    (
        (
            "contribution",
            "states the contribution",
            "previews the paper's contribution",
            "previews the paper",
            "the paper's contribution",
        ),
        has_contribution_statement,
    ),
    # thematic grouping
    (
        (
            "thematic",
            "thematically",
            "group sources thematically",
            "synthesises thematically",
            "synthesizes thematically",
            "grouped thematically",
        ),
        has_thematic_grouping,
    ),
    # results vs interpretation
    (
        ("without interpretation", "presents findings without interpretation", "results only"),
        separates_results_from_interpretation,
    ),
    # dolzarblik
    (
        (
            "relevance is grounded",
            "relevance",
            "currently relevant",
            "ground relevance",
            "dolzarblik",
        ),
        has_dolzarblik,
    ),
    # maqsad/vazifalar
    (
        ("goal is specific", "tasks are concrete", "goal and the tasks", "maqsad", "vazifalar"),
        has_maqsad_and_vazifalar,
    ),
    # local examples
    (
        ("local examples", "local evidence", "uzbek context", "current uzbek context"),
        has_local_examples,
    ),
    # actionable recommendations
    (
        ("actionable", "each recommendation is actionable", "recommendations"),
        has_actionable_recommendations,
    ),
    # numbered/bulleted findings
    (("numbered", "bulleted", "numbered or bulleted"), has_numbered_or_bulleted_list),
    # specific purpose
    (("purpose", "specific purpose", "states the specific purpose"), has_specific_purpose),
    # no new claims
    (
        ("introduces no new", "introduces no new factual claims", "no new arguments"),
        no_new_claims_in_conclusion,
    ),
)


def _select_validator(
    checklist_item: str,
) -> Callable[[str], bool] | None:
    """Pick the validator whose key phrases best match ``checklist_item``."""

    lower = checklist_item.lower()
    for keys, fn in _VALIDATORS:
        if any(key in lower for key in keys):
            return fn
    return None


def run_checks(
    text: str,
    checklist: list[str],
    *,
    target_word_count: int | None = None,
    word_tolerance: float = 0.2,
    min_citations: int = 0,
) -> QualityCheckResult:
    """Run every applicable validator in ``checklist`` against ``text``.

    Items that do not map to a registered validator default to PASSED —
    we'd rather miss a check than block on regex limitations. The
    ``target_word_count`` and ``min_citations`` args, when supplied, add
    structural checks on top of the checklist.
    """

    passed: list[str] = []
    failed: list[str] = []

    for item in checklist:
        fn = _select_validator(item)
        if fn is None:
            passed.append(item)
            continue
        if fn(text):
            passed.append(item)
        else:
            failed.append(item)

    if target_word_count is not None and target_word_count > 0:
        word_check = f"Within {int(word_tolerance * 100)}% of {target_word_count} words"
        if within_word_target(text, target_word_count, word_tolerance):
            passed.append(word_check)
        else:
            failed.append(word_check)

    if min_citations > 0:
        citation_check = f"At least {min_citations} citation marker(s)"
        if has_citations(text, min_citations):
            passed.append(citation_check)
        else:
            failed.append(citation_check)

    total = len(passed) + len(failed)
    score = (len(passed) / total) if total else 1.0
    return QualityCheckResult(
        passed=not failed,
        checks_passed=passed,
        checks_failed=failed,
        overall_score=round(score, 4),
    )


__all__ = [
    "has_actionable_recommendations",
    "has_citations",
    "has_contribution_statement",
    "has_dolzarblik",
    "has_limitations",
    "has_local_examples",
    "has_maqsad_and_vazifalar",
    "has_numbered_or_bulleted_list",
    "has_quantitative_result",
    "has_research_gap",
    "has_research_question",
    "has_specific_purpose",
    "has_thematic_grouping",
    "no_new_claims_in_conclusion",
    "run_checks",
    "separates_results_from_interpretation",
    "within_word_target",
]
