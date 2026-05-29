"""Behaviour tests for :class:`ThesisClassifier`.

The real Gemini call is exercised only by the harness; pytest mocks the
network per ``.claude/rules/testing.md``. These tests pin:

* one Gemini call per ``classify()`` invocation on the happy path,
* a malformed first response retries once,
* a length-mismatch on first response retries once,
* a length-mismatch on BOTH responses raises
  :class:`ThesisClassifierError`,
* the per-pair input shows up in the user prompt in order.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from packages.core.enums import Language
from packages.core.gemini import GEMINI_FLASH_3_5_MODEL
from packages.core.llm import LLMResponse
from packages.core.models.presentation import ThesisVerdict
from packages.presentation.thesis_classifier import (
    ThesisClassifier,
    ThesisClassifierError,
)


class _StubGemini:
    """Replays scripted text responses in order."""

    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, str, str]] = []  # (system, user, model)

    async def complete(
        self,
        system: str,
        user: str,
        model: str = GEMINI_FLASH_3_5_MODEL,
        max_tokens: int = 2000,
        temperature: float = 0.0,
    ) -> LLMResponse:
        del max_tokens, temperature
        self.calls.append((system, user, model))
        if not self.responses:
            raise RuntimeError("Gemini stub exhausted")
        return LLMResponse(
            content=self.responses.pop(0),
            model=model,
            input_tokens=80,
            output_tokens=40,
            latency_ms=5,
            estimated_cost_usd=0.0,
        )


def _payload(verdicts: list[dict[str, Any]]) -> str:
    return json.dumps({"verdicts": verdicts})


_PAIRS = [
    ("Salon culture", "Salons turned hospitality into political work in Paris."),
    ("Constitutional ideas", "Montesquieu reshaped how a legitimate state was imagined."),
    ("Ilim", "Ilim bilikti sındıradı"),
]


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


async def test_classify_returns_verdicts_in_input_order() -> None:
    payload = _payload(
        [
            {"is_thesis": True, "reason": "Salons predicates redistribution."},
            {"is_thesis": True, "reason": "Montesquieu predicates reshaping."},
            {"is_thesis": True, "reason": "Predication in three tokens."},
        ]
    )
    stub = _StubGemini([payload])
    classifier = ThesisClassifier(gemini=stub)  # type: ignore[arg-type]
    verdicts = await classifier.classify(_PAIRS, Language.KAA)
    assert len(verdicts) == 3
    assert all(isinstance(v, ThesisVerdict) for v in verdicts)
    assert [v.is_thesis for v in verdicts] == [True, True, True]
    assert "three tokens" in verdicts[2].reason
    assert len(stub.calls) == 1
    _system, user_prompt, model = stub.calls[0]
    assert model == GEMINI_FLASH_3_5_MODEL
    # Per-pair content appears in the user prompt.
    assert "Salon culture" in user_prompt
    assert "Ilim bilikti sındıradı" in user_prompt
    assert "kaa" in user_prompt  # the Language enum value


async def test_classify_returns_empty_list_without_calling_gemini() -> None:
    stub = _StubGemini([])
    classifier = ThesisClassifier(gemini=stub)  # type: ignore[arg-type]
    verdicts = await classifier.classify([], Language.EN)
    assert verdicts == []
    assert stub.calls == []


async def test_classify_strips_code_fence_around_json() -> None:
    payload = _payload(
        [
            {"is_thesis": True, "reason": "ok"},
            {"is_thesis": True, "reason": "ok"},
            {"is_thesis": True, "reason": "ok"},
        ]
    )
    fenced = f"```json\n{payload}\n```"
    stub = _StubGemini([fenced])
    classifier = ThesisClassifier(gemini=stub)  # type: ignore[arg-type]
    verdicts = await classifier.classify(_PAIRS, Language.EN)
    assert len(verdicts) == 3


# ---------------------------------------------------------------------------
# Retry behaviour
# ---------------------------------------------------------------------------


async def test_classify_retries_once_on_malformed_first_response() -> None:
    good = _payload(
        [
            {"is_thesis": True, "reason": "ok"},
            {"is_thesis": True, "reason": "ok"},
            {"is_thesis": True, "reason": "ok"},
        ]
    )
    stub = _StubGemini(["not json", good])
    classifier = ThesisClassifier(gemini=stub)  # type: ignore[arg-type]
    verdicts = await classifier.classify(_PAIRS, Language.EN)
    assert len(verdicts) == 3
    assert len(stub.calls) == 2
    # Retry prompt carries the stricter suffix.
    assert stub.calls[1][1] != stub.calls[0][1]


async def test_classify_retries_once_on_length_mismatch_first_response() -> None:
    """A one-shot mismatch retries and recovers — does NOT raise.

    Per advisor sharpening 3: only a mismatch on BOTH calls raises.
    """

    short = _payload(
        [
            {"is_thesis": True, "reason": "ok"},
            {"is_thesis": True, "reason": "ok"},
        ]
    )
    good = _payload(
        [
            {"is_thesis": True, "reason": "ok"},
            {"is_thesis": True, "reason": "ok"},
            {"is_thesis": True, "reason": "ok"},
        ]
    )
    stub = _StubGemini([short, good])
    classifier = ThesisClassifier(gemini=stub)  # type: ignore[arg-type]
    verdicts = await classifier.classify(_PAIRS, Language.EN)
    assert len(verdicts) == 3
    assert len(stub.calls) == 2


async def test_classify_raises_on_length_mismatch_after_retry() -> None:
    """A length mismatch on BOTH calls raises ThesisClassifierError."""

    short = _payload(
        [
            {"is_thesis": True, "reason": "ok"},
            {"is_thesis": True, "reason": "ok"},
        ]
    )
    too_long = _payload(
        [
            {"is_thesis": True, "reason": "ok"},
            {"is_thesis": True, "reason": "ok"},
            {"is_thesis": True, "reason": "ok"},
            {"is_thesis": True, "reason": "ok"},
        ]
    )
    stub = _StubGemini([short, too_long])
    classifier = ThesisClassifier(gemini=stub)  # type: ignore[arg-type]
    with pytest.raises(ThesisClassifierError):
        await classifier.classify(_PAIRS, Language.EN)
    assert len(stub.calls) == 2


async def test_classify_raises_after_two_malformed_responses() -> None:
    stub = _StubGemini(["{", "still not json"])
    classifier = ThesisClassifier(gemini=stub)  # type: ignore[arg-type]
    with pytest.raises(ThesisClassifierError):
        await classifier.classify(_PAIRS, Language.EN)
    assert len(stub.calls) == 2
