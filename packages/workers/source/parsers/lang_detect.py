"""Heuristic language detector for the three Nashr-supported languages.

We deliberately avoid pulling in a full language-detection library (cld3,
langdetect, lingua) — they are heavy, slow on cold starts, and overkill for
a 3-class problem with strong character-level signals:

* Cyrillic block (U+0400–U+04FF) is a near-perfect Russian signal because we
  do not currently support Mongolian/Bulgarian/etc.
* Uzbek Latin uses a small set of two-character markers that English never
  produces in normal prose: ``o'``, ``g'``, ``sh``, ``ch``, ``ng``, plus
  diacritic dotless-i and acute vowels (``ı``, ``ó``, ``á``, ``ú``).
* Anything else with a clear Latin majority is treated as English.
"""

from __future__ import annotations

import re
from typing import Final

CYRILLIC_RE: Final[re.Pattern[str]] = re.compile(r"[Ѐ-ӿ]")
LATIN_RE: Final[re.Pattern[str]] = re.compile(r"[A-Za-z]")
UZBEK_DIACRITIC_RE: Final[re.Pattern[str]] = re.compile(r"[ıóáúńğǵşçÁÓÚŃİ]")

UZBEK_MARKER_RE: Final[re.Pattern[str]] = re.compile(
    r"(o['’])|(g['’])|\bsh\w|\bch\w|\bng\w",
    re.IGNORECASE,
)

CYRILLIC_THRESHOLD: Final[float] = 0.30
LATIN_THRESHOLD: Final[float] = 0.50


def detect_language(text: str) -> str | None:
    """Return ``"uz"``, ``"ru"``, ``"en"``, or ``None`` for an empty/unclear sample.

    The heuristic counts alphabetic characters (Cyrillic + Latin) and
    classifies in this order: Cyrillic majority → ``ru``; Uzbek markers in
    a Latin-majority text → ``uz``; pure Latin majority → ``en``; otherwise
    ``None``.
    """

    if not text:
        return None

    cyrillic_count = len(CYRILLIC_RE.findall(text))
    latin_count = len(LATIN_RE.findall(text))
    alpha_total = cyrillic_count + latin_count

    if alpha_total == 0:
        return None

    cyrillic_ratio = cyrillic_count / alpha_total
    latin_ratio = latin_count / alpha_total

    if cyrillic_ratio > CYRILLIC_THRESHOLD:
        return "ru"

    if latin_ratio >= LATIN_THRESHOLD:
        if UZBEK_MARKER_RE.search(text) or UZBEK_DIACRITIC_RE.search(text):
            return "uz"
        return "en"

    return None
