"""Emphasis fallback + provenance for the presentation pipeline.

The editorial executor AUTHORS slide emphasis as it writes each slide — it holds
the deck thesis and the slide's argument, so it is the only stage that can decide
which table column is the subject, which row is dominant, and which statistic is
the headline (see :data:`packages.core.prompts.EDITORIAL_SYSTEM`). A string-
matching scorer deciding the subject of a slide would be a frozen-rule abdication
in the same family as a hardcoded row-band cap; the thing that understands the
argument must author the emphasis.

This module is therefore the LAST-RESORT GUARANTEE, never the primary path. It
fires only when the executor left a *structurally-emphasis-bearing* slide
unmarked — a DATA_EMPHASIS slide with stats but no highlighted one is the case
that must never ship flat — and it records, per field, whether the value was set
by the ``executor`` or filled by the ``fallback``. That provenance cannot be
re-derived from the final deck (an executor index and a fallback index are
indistinguishable post-hoc), so it is captured here and surfaced by the GATE A
script. Provenance is a sidecar; it is never written onto :class:`DeckSpec`
(which is ``extra="forbid"``).
"""

from __future__ import annotations

import re
from collections import Counter
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from packages.core.enums import SlideType
from packages.core.models.presentation import DeckSpec, SlideContent, SlideSpec, StatItem, TableRow


class EmphasisSource(StrEnum):
    """Where an emphasis field's value came from (provenance, never persisted).

    ``EXECUTOR_INVALID`` is distinct from ``FALLBACK``: the executor DID emit an
    index but it was out of range (discarded, then the fallback may refill the
    value for the visual). The gate must see this as an executor failure, not as
    clean abstention — otherwise a prompt that consistently emits bad indices
    reads identically to one that correctly leaves a neutral table unmarked.
    """

    EXECUTOR = "executor"
    EXECUTOR_INVALID = "executor_invalid"
    FALLBACK = "fallback"
    ABSENT = "absent"
    PLAN = "plan"


# ---------------------------------------------------------------------------
# Tokenisation (fallback-only — never the path that ships when the executor marks)
# ---------------------------------------------------------------------------

# Map subscript digits to ASCII so "sCO₂"/"CO₂" tokenise to "sco2"/"co2" — the
# disambiguator between an Air/Liquid/sCO2 table's columns lives in that formula.
_SUBSCRIPTS = str.maketrans("₀₁₂₃₄₅₆₇₈₉", "0123456789")

# A token is a run of letters/digits, keeping internal decimals so a headline
# number ("1.08", "3.2") survives as one token instead of splitting at the dot.
_TOKEN_RE = re.compile(r"[a-z0-9]+(?:[.,][0-9]+)*")

# Function/comparison words that carry no subject signal. Generic table words
# (e.g. "cooling" repeated across every column header) are dropped DYNAMICALLY by
# the discriminative-frequency filter below, not enumerated here.
_STOPWORDS = frozenset(
    {
        "the",
        "a",
        "an",
        "of",
        "to",
        "and",
        "or",
        "vs",
        "per",
        "for",
        "is",
        "are",
        "on",
        "in",
        "by",
        "with",
        "how",
        "that",
        "this",
        "its",
        "it",
        "as",
        "at",
        "from",
        "into",
        "more",
        "less",
        "than",
        "every",
        "which",
        "but",
        "not",
        "now",
        "both",
        "all",
        "each",
        "via",
        "over",
        "under",
    }
)


def _tokens(text: str | None) -> set[str]:
    """Normalised token set: lowercased, subscripts folded, stopwords dropped."""

    if not text:
        return set()
    lowered = text.translate(_SUBSCRIPTS).lower()
    return {t for t in _TOKEN_RE.findall(lowered) if t not in _STOPWORDS and len(t) > 1}


def _token_match(a: str, b: str) -> bool:
    """True when two tokens denote the same subject.

    Exact equality, or one is a short prefix/suffix of the other (length ≥ 3,
    differing by ≤ 2 chars) so "co2" matches "sco2" but "air" does NOT match
    "repair".
    """

    if a == b:
        return True
    short, long = (a, b) if len(a) <= len(b) else (b, a)
    return len(short) >= 3 and short in long and len(long) - len(short) <= 2


def _overlap(subject: set[str], target: set[str]) -> int:
    """How many ``target`` tokens any ``subject`` token matches."""

    return sum(1 for t in target if any(_token_match(s, t) for s in subject))


# ---------------------------------------------------------------------------
# Signals + provenance models
# ---------------------------------------------------------------------------


class EmphasisSignals(BaseModel):
    """The deck-level intent signals the fallback reads to break a tie.

    Built from fields present BOTH in-pipeline and in a dumped deck so the gate
    exercises the same logic that ships: deck title/subtitle, the slide title,
    the planner's carried section thesis, and the user's headline numbers.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    deck_title: str = ""
    deck_subtitle: str = ""
    slide_title: str = ""
    section_thesis: str = ""
    headline_numbers: tuple[str, ...] = ()

    def subject_tokens(self) -> set[str]:
        """Tokens naming the deck's/slide's subject (title, subtitle, thesis)."""

        bag: set[str] = set()
        for part in (self.slide_title, self.deck_subtitle, self.deck_title, self.section_thesis):
            bag |= _tokens(part)
        return bag

    def headline_tokens(self) -> set[str]:
        """Tokens from the user's declared headline numbers."""

        bag: set[str] = set()
        for number in self.headline_numbers:
            bag |= _tokens(number)
        return bag


class SlideEmphasisProvenance(BaseModel):
    """Per-slide source tags. A field is ``None`` when it does not apply."""

    model_config = ConfigDict(extra="forbid")

    slide_index: int = Field(ge=0)
    slide_type: str
    table_preferred_column: EmphasisSource | None = None
    table_hero_row: EmphasisSource | None = None
    hero_stat: EmphasisSource | None = None
    section_thesis: EmphasisSource | None = None


class EmphasisProvenance(BaseModel):
    """Roll-up of where every emphasis field came from across the deck."""

    model_config = ConfigDict(extra="forbid")

    slides: list[SlideEmphasisProvenance] = Field(default_factory=list[SlideEmphasisProvenance])

    def _emphasis_sources(self) -> list[EmphasisSource]:
        out: list[EmphasisSource] = []
        for slide in self.slides:
            for value in (slide.table_preferred_column, slide.table_hero_row, slide.hero_stat):
                if value is not None and value is not EmphasisSource.ABSENT:
                    out.append(value)
        return out

    @property
    def executor_count(self) -> int:
        """Emphasis fields the EXECUTOR authored (the gate's headline number)."""

        return sum(1 for s in self._emphasis_sources() if s is EmphasisSource.EXECUTOR)

    @property
    def fallback_count(self) -> int:
        """Emphasis fields the FALLBACK had to fill (non-zero ⇒ prompt under-took)."""

        return sum(1 for s in self._emphasis_sources() if s is EmphasisSource.FALLBACK)

    @property
    def invalid_count(self) -> int:
        """Emphasis fields where the EXECUTOR emitted an out-of-range index."""

        return sum(1 for s in self._emphasis_sources() if s is EmphasisSource.EXECUTOR_INVALID)


# ---------------------------------------------------------------------------
# Fallback deciders (pure; used only when the executor left a field unmarked)
# ---------------------------------------------------------------------------


def fallback_hero_stat(stats: list[StatItem], signals: EmphasisSignals) -> int:
    """Index of the stat to highlight when the executor highlighted none.

    The stat whose value/label best matches the headline numbers or subject;
    when nothing matches, the lead stat (index 0). Always returns a valid index
    so a DATA_EMPHASIS slide never ships flat.
    """

    cues = signals.subject_tokens() | signals.headline_tokens()
    if cues:
        best_index, best_score = 0, 0
        for index, stat in enumerate(stats):
            target = _tokens(stat.value) | _tokens(stat.unit) | _tokens(stat.label)
            score = _overlap(cues, target)
            if score > best_score:
                best_index, best_score = index, score
        if best_score > 0:
            return best_index
    return 0


def fallback_preferred_column(
    headers: list[str], rows: list[TableRow], signals: EmphasisSignals
) -> int | None:
    """Winning/subject column index, or None when there is no clear subject.

    Column 0 is the row-label column and is never the subject. A column scores by
    how many of its DISCRIMINATIVE header tokens (those not shared with another
    column — "cooling" repeated across columns is not a signal) the subject
    names. Returns the unique top scorer; ``None`` on a tie, a zero score, or a
    table with no subject signal — a neutral reference table has no winner.
    """

    del rows  # column subject comes from the headers + deck signals, not the cells
    if len(headers) < 2:
        return None
    data_columns = list(range(1, len(headers)))
    header_tokens = {j: _tokens(headers[j]) for j in data_columns}
    frequency = Counter(token for j in data_columns for token in header_tokens[j])

    subject = signals.subject_tokens()
    if not subject:
        return None

    scores = {
        j: _overlap(subject, {t for t in header_tokens[j] if frequency[t] == 1})
        for j in data_columns
    }
    best = max(scores.values())
    if best == 0:
        return None
    winners = [j for j, score in scores.items() if score == best]
    return winners[0] if len(winners) == 1 else None


def fallback_hero_row(rows: list[TableRow], signals: EmphasisSignals) -> int | None:
    """Dominant row index, or None when no row clearly dominates.

    A row scores by how many headline/subject tokens its cells carry. Returns
    the unique top scorer; ``None`` on a tie or a zero score (e.g. when no
    headline numbers were supplied, the honest outcome is "no dominant row").
    """

    cues = signals.headline_tokens() | signals.subject_tokens()
    if not cues:
        return None
    scores: list[int] = []
    for row in rows:
        target: set[str] = set()
        for cell in row.cells:
            target |= _tokens(cell)
        scores.append(_overlap(cues, target))
    best = max(scores, default=0)
    if best == 0:
        return None
    winners = [i for i, score in enumerate(scores) if score == best]
    return winners[0] if len(winners) == 1 else None


# ---------------------------------------------------------------------------
# Post-pass: fill what the executor left unmarked, recording provenance
# ---------------------------------------------------------------------------


def apply_emphasis_fallback(deck: DeckSpec) -> EmphasisProvenance:
    """Fill any unmarked emphasis field and return where every field came from.

    Runs over the ASSEMBLED deck (title/subtitle/interview present). Slides the
    executor already marked are left untouched; the return value is the gate's
    evidence that the executor — not this fallback — authored the emphasis.
    """

    return EmphasisProvenance(
        slides=[_process_slide(slide, _build_signals(deck, slide)) for slide in deck.slides]
    )


def _build_signals(deck: DeckSpec, slide: SlideSpec) -> EmphasisSignals:
    return EmphasisSignals(
        deck_title=deck.title,
        deck_subtitle=deck.subtitle or "",
        slide_title=slide.content.title,
        section_thesis=slide.section_thesis or "",
        headline_numbers=tuple(deck.interview.headline_numbers),
    )


def _process_slide(slide: SlideSpec, signals: EmphasisSignals) -> SlideEmphasisProvenance:
    content = slide.content
    provenance = SlideEmphasisProvenance(
        slide_index=slide.slide_index,
        slide_type=slide.slide_type.value,
        section_thesis=EmphasisSource.PLAN if slide.section_thesis else EmphasisSource.ABSENT,
    )
    if slide.slide_type is SlideType.TABLE_COMPACT and content.table_headers and content.table_rows:
        provenance.table_preferred_column = _resolve_preferred_column(content, signals)
        provenance.table_hero_row = _resolve_hero_row(content, signals)
    if slide.slide_type is SlideType.DATA_EMPHASIS and content.stats:
        provenance.hero_stat = _resolve_hero_stat(content, signals)
    return provenance


def _resolve_preferred_column(content: SlideContent, signals: EmphasisSignals) -> EmphasisSource:
    headers = content.table_headers or []
    rows = content.table_rows or []
    current = content.table_preferred_column
    if current is not None and current < len(headers):
        return EmphasisSource.EXECUTOR
    invalid = current is not None  # executor emitted an out-of-range index
    content.table_preferred_column = None
    pick = fallback_preferred_column(headers, rows, signals)
    if pick is not None:
        content.table_preferred_column = pick  # refill the value for the visual
    if invalid:
        return EmphasisSource.EXECUTOR_INVALID
    return EmphasisSource.FALLBACK if pick is not None else EmphasisSource.ABSENT


def _resolve_hero_row(content: SlideContent, signals: EmphasisSignals) -> EmphasisSource:
    rows = content.table_rows or []
    current = content.table_hero_row
    if current is not None and current < len(rows):
        return EmphasisSource.EXECUTOR
    invalid = current is not None  # executor emitted an out-of-range index
    content.table_hero_row = None
    pick = fallback_hero_row(rows, signals)
    if pick is not None:
        content.table_hero_row = pick  # refill the value for the visual
    if invalid:
        return EmphasisSource.EXECUTOR_INVALID
    return EmphasisSource.FALLBACK if pick is not None else EmphasisSource.ABSENT


def _resolve_hero_stat(content: SlideContent, signals: EmphasisSignals) -> EmphasisSource:
    stats = content.stats or []
    if any(stat.highlight for stat in stats):
        return EmphasisSource.EXECUTOR
    index = fallback_hero_stat(stats, signals)
    stats[index].highlight = True
    return EmphasisSource.FALLBACK
