"""Multilingual classifier deciding whether a (section_name, thesis) pair has
a thesis that is a real predication or a label restating the section name.

Phase 1.5 of the planner re-architecture. Phase 1 shipped two structural
arc checks in :mod:`packages.presentation.plan_validator` that were
nominally "language-agnostic" but were in fact tuned to English prose
length:

* a minimum of 4 whitespace-separated tokens per thesis,
* at least 3 thesis tokens not present in the ``section_name``.

Both produce false rejections on Karakalpak / Uzbek / Turkish / Kazakh /
Hungarian theses, where a real predication packs into 3 tokens because
tense, person, and case are encoded as suffixes. A plan validator that
rejects "Ilim bilikti sındıradı" ("science breaks authority") because it
has only 3 tokens is the same class of bias as a hardcoded English-only
keyword list — just expressed as numbers.

This module replaces those structural checks with a single Gemini Flash
call per plan. The classifier judges each (section_name, thesis) pair in
its actual language and returns one :class:`ThesisVerdict` per pair, in
section order. The validator's async path appends a ``P-A3`` failing
finding for each verdict where ``is_thesis is False``.

Design choices:

* **One call per plan, not per section.** A 7-section plan costs one
  Gemini call, not seven. Latency and cost are O(plan), not O(section).
* **Gemini 3.5 Flash (opt-in).** Passes
  :data:`packages.core.gemini.GEMINI_FLASH_3_5_MODEL` explicitly on
  every :meth:`GeminiClient.complete` call. The classifier is the only
  caller wired to 3.5 Flash today; editorial's existing interactive
  pass stays on 2.5 Flash unchanged. The cost entry for 3.5 Flash lives
  in :data:`packages.core.gemini.GEMINI_COSTS` so per-call cost
  accounting picks it up automatically.
* **No silent degradation.** A classifier that can't classify must fail
  loud — :class:`ThesisClassifierError` raises through
  :meth:`ThesisClassifier.classify` and the validator's async path. The
  planner-bug that this whole subsystem exists to prevent (substituting
  fabricated content) is exactly the failure a silent fallback would
  reintroduce.
* **Length-mismatch is a parse failure.** If the model returns a
  verdicts list of the wrong length, we treat the response as malformed
  and retry. After one retry, we raise.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Final

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from packages.core.enums import Language
from packages.core.gemini import GEMINI_FLASH_3_5_MODEL, GeminiClient
from packages.core.models.presentation import ThesisVerdict
from packages.core.prompts import (
    THESIS_CLASSIFIER_RETRY_SUFFIX,
    THESIS_CLASSIFIER_SYSTEM,
    THESIS_CLASSIFIER_USER,
)

logger = logging.getLogger(__name__)


# Per-call output budget. Each verdict is a small JSON object
# (``is_thesis`` bool plus ~25-word reason). The visible output is at
# most ~600 tokens for the 8-section DeckPlan ceiling, but Gemini 3.x
# Flash spends "thoughts" tokens before emitting visible output (the
# Vertex usageMetadata.thoughtsTokenCount line item, separately
# accounted but charged against the same max_output_tokens budget).
# A "PONG" probe consumed 100 thinking tokens; the multi-section
# classification task can plausibly spend several thousand. 8_000
# gives generous headroom without blowing context.
CLASSIFIER_MAX_TOKENS: Final[int] = 8_000


class ThesisClassifierError(RuntimeError):
    """Raised when the classifier cannot produce a usable verdict list.

    Distinct from a generic :class:`RuntimeError` so callers (the
    validator's async path, Phase 2's orchestrator) can branch on it.
    A classifier failure is a hard stop, not a transient API error.
    """


class _VerdictsPayload(BaseModel):
    """Permissive wrapper around the Gemini response's ``verdicts`` array."""

    model_config = ConfigDict(extra="ignore")

    verdicts: list[ThesisVerdict] = Field(default_factory=list[ThesisVerdict], max_length=64)


class ThesisClassifier:
    """Multilingual predication classifier for plan-validation Phase 1.5.

    One Gemini Flash call per plan classifies every section at once, so
    cost and latency are O(plan), not O(section). The validator's async
    path calls this; the sync :func:`validate_plan` path keeps working
    for callers that have no LLM access.
    """

    def __init__(self, gemini: GeminiClient | None = None) -> None:
        self._gemini = gemini

    def _get_gemini(self) -> GeminiClient:
        if self._gemini is None:
            self._gemini = GeminiClient()
        return self._gemini

    async def classify(
        self,
        items: list[tuple[str, str]],
        language: Language,
    ) -> list[ThesisVerdict]:
        """Return one :class:`ThesisVerdict` per (section_name, thesis) pair.

        ``items`` is consumed in order; the returned list preserves that
        order. Raises :class:`ThesisClassifierError` after two malformed
        responses (bad JSON, schema failure, or length mismatch). An
        empty ``items`` returns an empty list without an LLM call — a
        plan with no sections has nothing to classify.
        """

        if not items:
            return []

        system = THESIS_CLASSIFIER_SYSTEM
        user = THESIS_CLASSIFIER_USER.format(
            language=language.value,
            pairs=_format_pairs(items),
        )
        return await self._call_with_retry(system, user, expected=len(items))

    async def _call_with_retry(
        self,
        system: str,
        user: str,
        *,
        expected: int,
    ) -> list[ThesisVerdict]:
        """One Gemini call; on malformed output, retry once with the suffix.

        ``expected`` is the number of input items — a verdict list of any
        other length is treated as a parse failure (the planner's whole
        contract is one verdict per input pair, in input order, and a
        length mismatch makes the section-to-verdict mapping ambiguous).
        """

        first = await self._get_gemini().complete(
            system=system,
            user=user,
            model=GEMINI_FLASH_3_5_MODEL,
            max_tokens=CLASSIFIER_MAX_TOKENS,
        )
        parsed = _parse_verdicts(first.content, expected=expected)
        if parsed is not None:
            return parsed

        logger.warning(
            "thesis_classifier_first_attempt_unparseable",
            extra={"response_length": len(first.content), "expected": expected},
        )
        retry = await self._get_gemini().complete(
            system=system,
            user=user + THESIS_CLASSIFIER_RETRY_SUFFIX,
            model=GEMINI_FLASH_3_5_MODEL,
            max_tokens=CLASSIFIER_MAX_TOKENS,
        )
        parsed = _parse_verdicts(retry.content, expected=expected)
        if parsed is None:
            raise ThesisClassifierError(
                "Thesis classifier failed to return a usable verdicts list "
                f"of length {expected} after one retry."
            )
        return parsed


# ---------------------------------------------------------------------------
# Prompt assembly
# ---------------------------------------------------------------------------


def _format_pairs(items: list[tuple[str, str]]) -> str:
    """Render the (section_name, thesis) pairs as a numbered block.

    Empty fields are rendered as ``(empty)`` so the model never sees a
    bare-colon line that could be mistaken for the response template.
    The classifier prompt explicitly demands one verdict per pair, so
    pairs are numbered 1-indexed for human readability of the response.
    """

    lines: list[str] = []
    for index, (section_name, thesis) in enumerate(items, start=1):
        clean_name = (section_name or "").strip() or "(empty)"
        clean_thesis = (thesis or "").strip() or "(empty)"
        lines.append(f"{index}. section_name: {clean_name!r}")
        lines.append(f"   thesis:       {clean_thesis!r}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# JSON parsing
# ---------------------------------------------------------------------------


def _parse_verdicts(text: str, *, expected: int) -> list[ThesisVerdict] | None:
    """Decode a classifier response into a verdict list, or ``None`` on failure.

    Returns ``None`` on any of: malformed JSON, schema-validation failure
    on the wrapper, or a verdicts-list length that does not match
    ``expected``. The caller then retries once and raises.
    """

    obj = _try_parse_object(text)
    if obj is None:
        return None
    try:
        payload = _VerdictsPayload.model_validate(obj)
    except ValidationError as exc:
        logger.warning(
            "thesis_classifier_schema_validation_failed",
            extra={"error": str(exc)[:1000]},
        )
        return None
    if len(payload.verdicts) != expected:
        logger.warning(
            "thesis_classifier_length_mismatch",
            extra={"expected": expected, "got": len(payload.verdicts)},
        )
        return None
    return list(payload.verdicts)


def _try_parse_object(text: str) -> dict[str, Any] | None:
    """Parse a JSON object from a model response that may include code fences."""

    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.lower().startswith("json"):
            stripped = stripped[4:].lstrip()
    try:
        loaded: Any = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    if isinstance(loaded, dict):
        return {str(k): v for k, v in loaded.items()}  # type: ignore[misc]
    return None


__all__ = ["CLASSIFIER_MAX_TOKENS", "ThesisClassifier", "ThesisClassifierError"]
