"""Behaviour tests for :class:`PlannerPass`.

The real Sonnet call lives in ``scripts/proof_planner_phase1.py`` per
``.claude/rules/testing.md`` (no real LLM calls from pytest). These tests
mock the LLM client with scripted JSON responses to verify:

* a valid response yields a :class:`DeckPlan`
* a malformed response is retried once
* two malformed responses raise :class:`PlannerError`
* the source view fed to the prompt actually contains the chunk text
  (the structural bug the planner exists to fix)
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from packages.core.enums import (
    AudienceType,
    ClaimStrength,
    ClaimType,
    Language,
    NarrativeEmphasis,
    NarrativePhase,
)
from packages.core.llm import LLMResponse
from packages.core.models.presentation import (
    DeckPlan,
    PresentationInterviewAnswers,
)
from packages.core.models.source import (
    SourceChunkCreate,
    SourceClaimCreate,
    SourceMetadataExtracted,
)
from packages.presentation.planner import (
    SONNET_MODEL,
    PlannerError,
    PlannerPass,
)


class _StubLLM:
    """Replays scripted text responses in order."""

    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, str]] = []

    async def complete(
        self,
        system: str,
        user: str,
        model: str = SONNET_MODEL,
        max_tokens: int = 2000,
        temperature: float = 0.0,
    ) -> LLMResponse:
        self.calls.append((system, user))
        if not self.responses:
            raise RuntimeError("LLM stub exhausted")
        return LLMResponse(
            content=self.responses.pop(0),
            model=model,
            input_tokens=100,
            output_tokens=80,
            latency_ms=5,
            estimated_cost_usd=0.0,
        )


def _interview() -> PresentationInterviewAnswers:
    return PresentationInterviewAnswers(
        audience=AudienceType.UNDERGRADUATE,
        language=Language.KAA,
        narrative_emphasis=NarrativeEmphasis.BALANCED,
        include_interactive=False,
    )


def _chunk(text: str, index: int = 0, page: int | None = 1) -> SourceChunkCreate:
    return SourceChunkCreate(chunk_index=index, page=page, text=text)


def _claim(text: str, *, strength: ClaimStrength = ClaimStrength.STRONG) -> SourceClaimCreate:
    if len(text) < 10:
        text = text.ljust(10, ".")
    return SourceClaimCreate(
        claim_text=text,
        strength=strength,
        claim_type=ClaimType.THEORETICAL_ARGUMENT,
    )


def _valid_plan_payload() -> dict[str, Any]:
    return {
        "thesis": "Enlightenment thinkers redistributed cultural authority across Europe.",
        "audience_takeaway": "Students name two debates that shaped constitutional thought.",
        "sections": [
            {
                "section_name": "Salon culture",
                "thesis": "Salons turned private hospitality into a public political venue.",
                "phase": NarrativePhase.HOOK.value,
                "figure_names": ["Voltaire"],
                "planned_slide_types": ["content_split"],
            },
            {
                "section_name": "Legacy",
                "thesis": "Revolutions translated salon arguments into founding documents.",
                "phase": NarrativePhase.CLOSE.value,
                "figure_names": [],
                "planned_slide_types": ["summary_takeaway"],
            },
        ],
        "figures": [
            {
                "name": "Voltaire",
                "years": "1694-1778",
                "why_in_source": "Source names Voltaire as the leading Enlightenment polemicist.",
                "source_claim_ids": [],
            }
        ],
        "image_cohesion_note": "Warm oil-paint portraits in candlelit interiors.",
    }


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


async def test_plan_deck_returns_validated_deck_plan() -> None:
    stub = _StubLLM([json.dumps(_valid_plan_payload())])
    planner = PlannerPass(llm=stub)  # type: ignore[arg-type]
    plan = await planner.plan_deck(
        interview=_interview(),
        claims=[_claim("Voltaire defended freedom of conscience.")],
        chunks=[_chunk("Volter (1694-1778) din erkinligi ushın gúresken.")],
        source_metadata=[],
    )
    assert isinstance(plan, DeckPlan)
    assert plan.figures[0].name == "Voltaire"
    assert len(stub.calls) == 1


async def test_plan_deck_strips_code_fence_around_json() -> None:
    payload = json.dumps(_valid_plan_payload())
    fenced = f"```json\n{payload}\n```"
    stub = _StubLLM([fenced])
    planner = PlannerPass(llm=stub)  # type: ignore[arg-type]
    plan = await planner.plan_deck(
        interview=_interview(),
        claims=[],
        chunks=[_chunk("Volter (1694-1778) din erkinligi ushın gúresken.")],
        source_metadata=[],
    )
    assert isinstance(plan, DeckPlan)


# ---------------------------------------------------------------------------
# Retry behaviour
# ---------------------------------------------------------------------------


async def test_plan_deck_retries_once_on_malformed_json() -> None:
    stub = _StubLLM(["not json at all", json.dumps(_valid_plan_payload())])
    planner = PlannerPass(llm=stub)  # type: ignore[arg-type]
    plan = await planner.plan_deck(
        interview=_interview(),
        claims=[],
        chunks=[_chunk("Volter (1694-1778) din erkinligi ushın gúresken.")],
        source_metadata=[],
    )
    assert isinstance(plan, DeckPlan)
    assert len(stub.calls) == 2
    # Retry's user prompt must carry the stricter suffix.
    assert stub.calls[1][1] != stub.calls[0][1]


async def test_plan_deck_retries_once_on_schema_mismatch() -> None:
    bad_payload = _valid_plan_payload()
    bad_payload["sections"] = [bad_payload["sections"][0]]  # only 1 section
    stub = _StubLLM([json.dumps(bad_payload), json.dumps(_valid_plan_payload())])
    planner = PlannerPass(llm=stub)  # type: ignore[arg-type]
    plan = await planner.plan_deck(
        interview=_interview(),
        claims=[],
        chunks=[_chunk("Volter (1694-1778) din erkinligi ushın gúresken.")],
        source_metadata=[],
    )
    assert isinstance(plan, DeckPlan)
    assert len(stub.calls) == 2


async def test_plan_deck_raises_planner_error_after_two_failures() -> None:
    stub = _StubLLM(["{", "still not valid"])
    planner = PlannerPass(llm=stub)  # type: ignore[arg-type]
    with pytest.raises(PlannerError):
        await planner.plan_deck(
            interview=_interview(),
            claims=[],
            chunks=[_chunk("Volter (1694-1778).")],
            source_metadata=[],
        )
    assert len(stub.calls) == 2


# ---------------------------------------------------------------------------
# Source view content — the structural bug fix
# ---------------------------------------------------------------------------


async def test_source_view_contains_chunk_text_verbatim() -> None:
    """The planner's whole point: chunks are NOT discarded.

    Editorial's bug (the line ``del evidence_matrix, chunks, ...``) is
    that the model never sees the source text. This test pins that the
    planner pass DOES send the chunk text to the LLM in the user prompt.
    """

    chunk_text = "Bach (1685-1750) hám Mozart (1756-1791) klassikalıq musikanın simvolları."
    stub = _StubLLM([json.dumps(_valid_plan_payload())])
    planner = PlannerPass(llm=stub)  # type: ignore[arg-type]
    await planner.plan_deck(
        interview=_interview(),
        claims=[],
        chunks=[_chunk(chunk_text)],
        source_metadata=[],
    )
    _system, user_prompt = stub.calls[0]
    assert chunk_text in user_prompt
    assert "Bach" in user_prompt
    assert "Mozart" in user_prompt


async def test_source_view_includes_extracted_claims() -> None:
    stub = _StubLLM([json.dumps(_valid_plan_payload())])
    planner = PlannerPass(llm=stub)  # type: ignore[arg-type]
    claim_text = "Voltaire defended freedom of conscience throughout his life."
    await planner.plan_deck(
        interview=_interview(),
        claims=[_claim(claim_text)],
        chunks=[_chunk("Volter erkinlik ushın gúresken.")],
        source_metadata=[],
    )
    _system, user_prompt = stub.calls[0]
    assert claim_text in user_prompt


async def test_source_view_includes_metadata_when_present() -> None:
    stub = _StubLLM([json.dumps(_valid_plan_payload())])
    planner = PlannerPass(llm=stub)  # type: ignore[arg-type]
    metadata = SourceMetadataExtracted(
        title="Ag'artıwshılıq dáwiri",
        authors=["Pedagogika klassi"],
        year=2024,
        doi=None,
    )
    await planner.plan_deck(
        interview=_interview(),
        claims=[],
        chunks=[_chunk("Volter erkinlik ushın gúresken.")],
        source_metadata=[metadata],
    )
    _system, user_prompt = stub.calls[0]
    assert "Ag'artıwshılıq dáwiri" in user_prompt
    assert "2024" in user_prompt
