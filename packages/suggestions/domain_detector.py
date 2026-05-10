"""Heuristic detector that maps an article's content to academic domain(s).

Pure keyword analysis — no LLM call. The detector concatenates every claim
text, source-chunk text, outline section title, and uploaded source title
into a single lower-cased blob, then for each domain counts how many of its
keywords (English / Uzbek / Russian) appear as substrings. The fraction of
keywords matched per domain becomes the raw score, and the highest-scoring
domain has its score normalised to 1.0 with the rest scaled proportionally.

Output rules:

* ``primary_domain`` is the top scorer after normalisation.
* ``all_domains`` keeps every domain whose normalised score is strictly
  greater than ``MIN_CONFIDENCE`` (0.1).
* If no domain's raw score exceeds 0.0, ``primary_domain`` falls back to
  :attr:`AcademicDomain.GENERAL` with an empty ``all_domains`` list.

The detector treats *substrings* as matches: a keyword "machine learning"
fires when the blob contains that exact 16-character run. Single-word
keywords are also substring matches by design — "law" will match inside
"lawyer" — because at this stage we want recall, not precision; the
provider that ultimately runs the search is the precision filter.
"""

from __future__ import annotations

from packages.core.models.article import ArticleOutline
from packages.core.models.source import (
    SourceChunkCreate,
    SourceClaimCreate,
    SourceMetadataExtracted,
)
from packages.core.models.suggestion import (
    AcademicDomain,
    DomainDetectionResult,
    DomainScore,
)
from packages.suggestions._keywords import DOMAIN_KEYWORDS

_MIN_CONFIDENCE: float = 0.1
_MAX_MATCHED_KEYWORDS_PER_DOMAIN: int = 50


class DomainDetector:
    """Detects academic domains from article content to route to data providers.

    Stateless: callers may share a single instance across all projects. No
    network I/O, no LLM calls — just keyword scanning and arithmetic.
    """

    def detect_domains(
        self,
        claims: list[SourceClaimCreate],
        chunks: list[SourceChunkCreate],
        outline: ArticleOutline | None,
        source_metadata: list[SourceMetadataExtracted],
    ) -> DomainDetectionResult:
        """Analyse article content and return the ranked list of relevant domains."""

        blob = _build_text_blob(claims, chunks, outline, source_metadata)
        if not blob:
            return DomainDetectionResult(
                primary_domain=AcademicDomain.GENERAL,
                all_domains=[],
            )

        raw_scores = _raw_scores(blob)

        max_raw = max((score for score, _ in raw_scores.values()), default=0.0)
        if max_raw <= 0.0:
            return DomainDetectionResult(
                primary_domain=AcademicDomain.GENERAL,
                all_domains=[],
            )

        normalised: list[DomainScore] = []
        for domain, (raw, matches) in raw_scores.items():
            confidence = raw / max_raw
            if confidence <= _MIN_CONFIDENCE:
                continue
            normalised.append(
                DomainScore(
                    domain=domain,
                    confidence=round(confidence, 4),
                    matched_keywords=sorted(matches)[:_MAX_MATCHED_KEYWORDS_PER_DOMAIN],
                )
            )

        normalised.sort(key=lambda s: (-s.confidence, s.domain.value))
        primary = normalised[0].domain if normalised else AcademicDomain.GENERAL
        return DomainDetectionResult(primary_domain=primary, all_domains=normalised)


def _build_text_blob(
    claims: list[SourceClaimCreate],
    chunks: list[SourceChunkCreate],
    outline: ArticleOutline | None,
    source_metadata: list[SourceMetadataExtracted],
) -> str:
    """Concatenate every text input into a single lower-cased blob."""

    parts: list[str] = []
    for claim in claims:
        parts.append(claim.claim_text)
        if claim.quote:
            parts.append(claim.quote)
    for chunk in chunks:
        parts.append(chunk.text)
    if outline is not None:
        parts.append(outline.title)
        parts.append(outline.thesis)
        for section in outline.sections:
            parts.append(section.title)
            if section.section_thesis:
                parts.append(section.section_thesis)
    for meta in source_metadata:
        if meta.title:
            parts.append(meta.title)
    blob = " ".join(parts).lower()
    return blob


def _raw_scores(blob: str) -> dict[AcademicDomain, tuple[float, list[str]]]:
    """For each domain return (raw fraction matched, list of matched keywords)."""

    out: dict[AcademicDomain, tuple[float, list[str]]] = {}
    for domain, keywords in DOMAIN_KEYWORDS.items():
        matches: list[str] = [kw for kw in keywords if kw in blob]
        raw = len(matches) / len(keywords) if keywords else 0.0
        out[domain] = (raw, matches)
    return out
