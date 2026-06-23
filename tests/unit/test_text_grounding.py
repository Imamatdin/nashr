"""Tests for the shared source-grounding normalizer (``packages.core.text``)."""

from __future__ import annotations

from packages.core.text import grounded_in, normalize_for_grounding


def test_normalize_collapses_case_and_whitespace() -> None:
    assert normalize_for_grounding("  Hello   WORLD\t\n ") == "hello world"


def test_normalize_decomposes_subscript_digit() -> None:
    # U+2082 (subscript two) decomposes to ASCII "2" under NFKD — sCO₂ -> sco2.
    assert normalize_for_grounding("sCO₂") == "sco2"


def test_normalize_strips_diacritics() -> None:
    assert normalize_for_grounding("café") == "cafe"
    assert normalize_for_grounding("idée") == "idee"


def test_normalize_folds_turkic_dotted_i() -> None:
    # İ (U+0130) -> NFKD "I" + combining dot -> drop mark -> casefold -> "i".
    assert normalize_for_grounding("İstanbul") == "istanbul"


def test_grounded_in_matches_identical_text() -> None:
    assert grounded_in("separation of powers", "Montesquieu argued for the separation of powers.")


def test_grounded_in_bug_killer_case_whitespace_diacritic_subscript() -> None:
    """The test that matters: an excerpt differing ONLY by case, whitespace,
    diacritics, and a subscript digit must still ground against its source claim.

    Without normalization on BOTH sides the critic would silently drop a real
    finding (or fail to confirm a real fabrication) on a cosmetic mismatch.
    """

    source_claim = "L'idée de Montesquieu sur sCO₂ atteint 50%."
    slide_excerpt = "  l'idee  de montesquieu sur sco2 atteint 50%  "  # case + ws + é→e + ₂→2

    assert grounded_in(slide_excerpt, source_claim) is True


def test_grounded_in_rejects_absent_text() -> None:
    assert grounded_in("Beethoven", "Voltaire and Montesquieu shaped the Enlightenment.") is False


def test_grounded_in_empty_inputs_never_match() -> None:
    assert grounded_in("", "anything at all") is False
    assert grounded_in("anything at all", "") is False
    assert grounded_in("   ", "anything at all") is False
