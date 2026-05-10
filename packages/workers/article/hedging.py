"""Hedging-language reference and post-draft alignment checker.

The drafter's prompt tells the LLM to match its language to claim
strength: confident verbs near STRONG evidence, measured verbs near
MODERATE evidence, cautious verbs near WEAK evidence. The constants here
make that vocabulary auditable, and :func:`check_hedging_alignment` runs
a cheap post-draft scan that produces advisory warnings when the drafted
text uses confident language too close to a weak claim.

The check is deliberately advisory, never blocking. False positives are
acceptable: the warnings flow into :class:`DraftResult.warnings` so a
human (or downstream verification pass) can review them without the
drafter aborting on every borderline phrasing.
"""

from __future__ import annotations

import re
from typing import Final

from packages.core.enums import ClaimStrength
from packages.core.models.source import SourceClaimCreate

CONFIDENT_LANGUAGE: Final[dict[str, tuple[str, ...]]] = {
    "en": (
        "demonstrates",
        "demonstrate",
        "establishes",
        "establish",
        "confirms",
        "confirm",
        "proves",
        "prove",
        "shows clearly",
        "definitively",
        "unambiguously",
    ),
    "uz": (
        "ko'rsatadi",
        "korsatadi",
        "tasdiqlaydi",
        "isbotlaydi",
        "aniq ko'rsatadi",
        "aniq korsatadi",
    ),
    "ru": (
        "демонстрирует",
        "подтверждает",
        "доказывает",
        "убедительно показывает",
        "однозначно",
    ),
}

MEASURED_LANGUAGE: Final[dict[str, tuple[str, ...]]] = {
    "en": (
        "suggests",
        "suggest",
        "indicates",
        "indicate",
        "points to",
        "evidence supports",
        "findings show",
        "findings support",
    ),
    "uz": (
        "ko'rsatishi mumkin",
        "korsatishi mumkin",
        "dalolat qiladi",
        "natijalar ko'rsatadiki",
        "natijalar korsatadiki",
    ),
    "ru": (
        "указывает",
        "свидетельствует",
        "результаты показывают",
        "результаты свидетельствуют",
    ),
}

CAUTIOUS_LANGUAGE: Final[dict[str, tuple[str, ...]]] = {
    "en": (
        "may indicate",
        "preliminary evidence suggests",
        "it is possible that",
        "appears to",
        "appears that",
        "possibly",
        "tentatively",
    ),
    "uz": (
        "ehtimol",
        "dastlabki ma'lumotlarga ko'ra",
        "dastlabki malumotlarga kora",
        "mumkin",
    ),
    "ru": (
        "возможно",
        "предварительные данные указывают",
        "по-видимому",
        "вероятно",
    ),
}


_CITATION_RE: Final[re.Pattern[str]] = re.compile(r"\[([A-Za-z0-9_\-]{1,64})\]")
_PROXIMITY_CHARS: Final[int] = 200


def _all_phrases(table: dict[str, tuple[str, ...]], language: str) -> tuple[str, ...]:
    """Return phrases for the requested language, falling back to English."""

    return table.get(language, table["en"])


def check_hedging_alignment(
    text: str,
    claims: list[SourceClaimCreate],
    language: str,
) -> list[str]:
    """Return warnings when confident phrasing sits near weak-claim citations.

    Scans every ``[source_id]`` marker in ``text`` and looks at the
    ~200 characters of context that immediately precede it. If that
    window contains a confident verb and the cited chunk's claims
    include any ``WEAK`` claim, a warning is emitted naming the offending
    phrase.

    The check is one-directional (over-claiming weak evidence is the
    real failure mode); we do not warn when measured language is used
    near strong evidence.
    """

    if not text or not claims:
        return []

    confident_phrases = _all_phrases(CONFIDENT_LANGUAGE, language)
    weak_chunk_ids = {
        claim.source_chunk_id for claim in claims if claim.strength is ClaimStrength.WEAK
    }
    if not weak_chunk_ids:
        return []

    warnings: list[str] = []
    seen: set[tuple[str, str]] = set()
    lower = text.lower()
    for match in _CITATION_RE.finditer(text):
        chunk_id = match.group(1)
        if chunk_id not in weak_chunk_ids:
            continue
        window_start = max(0, match.start() - _PROXIMITY_CHARS)
        window = lower[window_start : match.start()]
        for phrase in confident_phrases:
            if phrase in window:
                key = (phrase, chunk_id)
                if key in seen:
                    continue
                seen.add(key)
                warnings.append(
                    f'Confident language "{phrase}" used near weak claim '
                    f"[{chunk_id}]. Consider softer phrasing."
                )
    return warnings


__all__ = [
    "CAUTIOUS_LANGUAGE",
    "CONFIDENT_LANGUAGE",
    "MEASURED_LANGUAGE",
    "check_hedging_alignment",
]
