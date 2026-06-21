"""Behaviour tests for :class:`PlannerPass`.

The real Sonnet call lives in ``scripts/proof_planner_phase1.py`` per
``.claude/rules/testing.md`` (no real LLM calls from pytest). These tests
mock the LLM client with scripted JSON responses to verify:

* a valid response yields a :class:`DeckPlan`
* a malformed response is retried once
* two malformed responses raise :class:`PlannerError`
* a schema-invalid response drives an INFORMED retry that names the failing
  fields (not a blind resample), and that failure is logged with field paths
* an empty figures roster — the correct plan for a people-free source — is
  valid, both at the schema layer and through ``plan_deck``
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
        cache: bool | str = False,
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


async def test_plan_deck_informed_retry_carries_the_schema_error() -> None:
    """The schema-failure retry is INFORMED, not blind — it names the bad field.

    A response that parses as JSON but violates the schema (here an extra
    top-level field, which ``extra="forbid"`` rejects) must drive a retry whose
    prompt names the offending field and the fix. At temperature 0 a blind
    resample re-rolls the same near-boundary output, so the field path reaching
    the model is what makes recovery possible. The pre-existing
    ``test_plan_deck_retries_once_on_schema_mismatch`` cannot pin this: its stub
    replays a valid second response regardless of what the retry prompt says, so
    it passes whether the retry is informed or blind. This one fails if the
    retry goes back to the generic suffix.
    """

    bad_payload = _valid_plan_payload()
    bad_payload["unexpected_field"] = "the model added a field outside the schema"
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
    retry_prompt = stub.calls[1][1]
    assert "unexpected_field" in retry_prompt
    assert "Remove the field" in retry_prompt
    # It must be the schema nudge, not the malformed-JSON one.
    assert "FAILED schema validation" in retry_prompt


async def test_plan_deck_logs_schema_error_field_paths(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A schema failure logs WHICH fields failed, in the message itself.

    The Phase-2 gate console showed only ``planner_schema_validation_failed``
    with no detail because the error was stashed in a logging ``extra`` field
    that the default formatter drops. The field path + rule must live in the
    rendered MESSAGE so they surface regardless of the consumer's formatter.
    """

    bad_payload = _valid_plan_payload()
    bad_payload["sections"] = [bad_payload["sections"][0]]  # 1 section -> too_short (min 2)
    stub = _StubLLM([json.dumps(bad_payload), json.dumps(_valid_plan_payload())])
    planner = PlannerPass(llm=stub)  # type: ignore[arg-type]
    with caplog.at_level("WARNING", logger="packages.presentation.planner"):
        plan = await planner.plan_deck(
            interview=_interview(),
            claims=[],
            chunks=[_chunk("Volter (1694-1778).")],
            source_metadata=[],
        )
    assert isinstance(plan, DeckPlan)
    rendered = [
        record.getMessage()
        for record in caplog.records
        if "planner_schema_validation_failed" in record.getMessage()
    ]
    assert rendered, "expected a schema-validation warning to be logged"
    assert "sections" in rendered[0]
    assert "too_short" in rendered[0]


def test_empty_figure_roster_is_schema_valid() -> None:
    """Regression GUARD (not a reproduction): an empty figures roster validates.

    A source that names no biographical people — a technical paper citing only
    authors in its references — must produce a :class:`DeckPlan` with
    ``figures: []`` and sections that name no one. This already validates today;
    the run-3 sCO2 crash was NOT the schema rejecting an empty roster, it was the
    blind-retry gap. This test exists to keep the no-minimum-people guarantee at
    the schema layer: it fails the day someone adds a ``min_length`` to
    ``figures`` or a cross-field rule that assumes people exist.
    """

    plan = DeckPlan.model_validate(
        {
            "thesis": (
                "Supercritical CO2 cooling redesigns the data center as one thermodynamic system."
            ),
            "audience_takeaway": "sCO2 cooling is the credible path past the air/liquid wall.",
            "sections": [
                {
                    "section_name": "The cooling bottleneck",
                    "thesis": "Cooling, not computation, is the real ceiling on data-center scale.",
                    "phase": NarrativePhase.HOOK.value,
                    "figure_names": [],
                    "planned_slide_types": ["title_hero"],
                },
                {
                    "section_name": "Results",
                    "thesis": "Supercritical CO2 cuts PUE to 1.08 and recovers waste heat.",
                    "phase": NarrativePhase.CLOSE.value,
                    "figure_names": [],
                    "planned_slide_types": ["chart_data"],
                },
            ],
            "figures": [],
            "image_cohesion_note": "Clean engineering schematics, cool slate palette, even lighting.",
        }
    )
    assert plan.figures == []
    assert all(section.figure_names == [] for section in plan.sections)


async def test_plan_deck_accepts_people_free_response() -> None:
    """A people-free response is accepted first try — no retry, no error.

    The pass-level companion to the schema guard: when the model correctly
    returns ``figures: []`` for a source that names nobody, ``plan_deck`` accepts
    it on the FIRST attempt. The Phase-1 tests never had this case — the
    Enlightenment fixture is people-rich — which is why a people-free regression
    had no unit-level guard.
    """

    payload = _valid_plan_payload()
    payload["figures"] = []
    for section in payload["sections"]:
        section["figure_names"] = []
    stub = _StubLLM([json.dumps(payload)])
    planner = PlannerPass(llm=stub)  # type: ignore[arg-type]
    plan = await planner.plan_deck(
        interview=_interview(),
        claims=[],
        chunks=[_chunk("A technical paper that cites only Ahn, Y. et al. in its references.")],
        source_metadata=[],
    )
    assert isinstance(plan, DeckPlan)
    assert plan.figures == []
    assert len(stub.calls) == 1


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
