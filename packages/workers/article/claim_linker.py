"""Bag-of-words claim → outline-section linker.

When the editorial pass produces an outline whose ``key_claims_to_use``
fields are short prose descriptors rather than exact claim identifiers,
this linker resolves the descriptors to concrete claim indices via
Jaccard overlap of stop-word-stripped tokens.

Embeddings are deliberately *not* used in v1: the threshold has to be
explainable to non-engineers (the article worker surfaces "we couldn't
match this claim to any section" warnings), and Jaccard on tokens is
trivially auditable. If/when we add a vector backend it slots in here
without changing the public contract.
"""

from __future__ import annotations

import re
from typing import Final

from packages.core.models.article import ArticleOutline
from packages.core.models.source import SourceClaimCreate

OVERLAP_THRESHOLD: Final[float] = 0.15

_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"[\w']+", re.UNICODE)

_STOPWORDS_EN: Final[frozenset[str]] = frozenset(
    {
        "the",
        "and",
        "of",
        "is",
        "in",
        "to",
        "for",
        "a",
        "an",
        "on",
        "at",
        "by",
        "with",
        "from",
        "as",
        "that",
        "this",
        "are",
        "was",
        "were",
        "be",
        "or",
        "it",
        "its",
        "into",
        "but",
        "not",
    }
)
_STOPWORDS_UZ: Final[frozenset[str]] = frozenset(
    {
        "va",
        "bir",
        "bu",
        "bilan",
        "uchun",
        "boʻlgan",
        "bolgan",
        "bo'lgan",
        "ham",
        "lekin",
        "yoki",
        "agar",
        "qachon",
        "shu",
        "har",
        "ko'p",
        "kop",
        "kop'",
        "u",
    }
)
_STOPWORDS_RU: Final[frozenset[str]] = frozenset(
    {
        "и",
        "в",
        "на",
        "с",
        "по",
        "для",
        "не",
        "что",
        "это",
        "как",
        "к",
        "из",
        "от",
        "о",
        "а",
        "но",
        "же",
        "у",
        "за",
        "до",
        "при",
        "так",
    }
)
_STOPWORDS: Final[frozenset[str]] = _STOPWORDS_EN | _STOPWORDS_UZ | _STOPWORDS_RU


class ClaimLinker:
    """Links claims to article sections using Jaccard token overlap."""

    def link_claims_to_sections(
        self,
        claims: list[SourceClaimCreate],
        outline: ArticleOutline,
    ) -> dict[str, list[int]]:
        """Map outline section IDs to the indices of claims that best fit them.

        Returns ``{section_id: [claim_index, ...]}``. Each claim appears
        in at most one section's list (the highest-scoring one above
        ``OVERLAP_THRESHOLD``); unmatched claims are silently dropped so
        callers can compute the unmatched set themselves.
        """

        section_tokens: list[tuple[str, set[str]]] = [
            (str(section.id), _section_tokens(section.key_claims_to_use))
            for section in outline.sections
        ]
        result: dict[str, list[int]] = {sid: [] for sid, _ in section_tokens}

        for index, claim in enumerate(claims):
            claim_tokens = _tokenize(claim.claim_text)
            best_section: str | None = None
            best_score = OVERLAP_THRESHOLD
            for section_id, tokens in section_tokens:
                if not tokens:
                    continue
                score = _jaccard(claim_tokens, tokens)
                if score > best_score:
                    best_score = score
                    best_section = section_id
            if best_section is not None:
                result[best_section].append(index)

        return result


def _section_tokens(key_claims: list[str]) -> set[str]:
    """Tokenize all key-claim descriptors into one bag for the section."""

    tokens: set[str] = set()
    for entry in key_claims:
        tokens.update(_tokenize(entry))
    return tokens


def _tokenize(text: str) -> set[str]:
    """Lowercase, regex-tokenize, and strip stopwords from ``text``."""

    return {
        match.group(0).lower()
        for match in _TOKEN_RE.finditer(text)
        if match.group(0).lower() not in _STOPWORDS and len(match.group(0)) > 1
    }


def _jaccard(a: set[str], b: set[str]) -> float:
    """Jaccard similarity of two token sets; ``0.0`` if either is empty."""

    if not a or not b:
        return 0.0
    intersection = len(a & b)
    union = len(a | b)
    return intersection / union if union else 0.0


__all__ = ["OVERLAP_THRESHOLD", "ClaimLinker"]
