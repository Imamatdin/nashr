"""Shared text-normalization helpers for source-grounding checks.

The content critic — and any other matcher that compares LLM-emitted slide text
against source claims — needs a normalizer robust to the three ways the same
fact is written differently across a deck and its sources: case, whitespace, and
diacritics/compatibility forms (Turkic dotted/dotless I, Karakalpak accents,
subscript digits like U+2082 in chemical formulae such as ``sCO₂``).

This is deliberately distinct from two existing normalizers that must NOT be
reused for grounding:

* ``packages.presentation.plan_validator._normalize`` strips per-token
  surrounding punctuation and is tuned for thesis/section-label *equality*;
  mutating token boundaries makes it wrong for faithful substring grounding.
* The TypeScript ``normaliseForMatch`` in the chart guard strips *all*
  non-alphanumerics (including spaces) for chart-label matching — too aggressive
  for claim grounding, where dropping spaces would over-match.

Grounding keeps internal punctuation and single spaces so a substring check
stays faithful to the claim text; it only folds away case, accents, and
whitespace runs.
"""

from __future__ import annotations

import unicodedata


def normalize_for_grounding(value: str) -> str:
    """Fold case, diacritics, and whitespace for source-grounding comparison.

    Applies NFKD compatibility decomposition (so a subscript ``₂`` becomes
    ``2`` and an accented ``é`` becomes ``e`` plus a combining mark), drops the
    combining marks, casefolds (Unicode-aware lowercasing that also handles the
    Turkic dotted/dotless I without an explicit table), and collapses every run
    of whitespace to a single space. Internal punctuation is preserved, so the
    result stays a faithful substring of the original text modulo the three
    folded dimensions.
    """

    decomposed = unicodedata.normalize("NFKD", value)
    without_marks = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return " ".join(without_marks.casefold().split())


def grounded_in(needle: str, haystack: str) -> bool:
    """True when ``needle`` occurs in ``haystack`` after grounding normalization.

    Both sides pass through :func:`normalize_for_grounding` before a substring
    test, so a match survives differences of case, diacritics, and whitespace.
    Empty input on either side never matches: an empty needle would spuriously
    match everything, and an empty haystack can contain nothing.
    """

    normalized_needle = normalize_for_grounding(needle)
    normalized_haystack = normalize_for_grounding(haystack)
    if not normalized_needle or not normalized_haystack:
        return False
    return normalized_needle in normalized_haystack
