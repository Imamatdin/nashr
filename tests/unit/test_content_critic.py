"""Tests for the adversarial content critic (``packages.presentation.content_critic``).

These exercise the code-side grounding + severity gating with a stubbed Gemini
client; the editorial-orchestration tests (routing, one-round re-judge, residual
hard-stop, emergency/empty-claims skip) live in ``test_editorial_pass``.
"""

from __future__ import annotations

import json

from packages.core.enums import (
    AuditSeverity,
    ClaimStrength,
    NarrativePhase,
    SlideType,
)
from packages.core.llm import LLMResponse
from packages.core.models.presentation import (
    ChartSeriesPoint,
    DeckPlan,
    PlannedFigure,
    PlannedSection,
    SlideContent,
    SlideSpec,
)
from packages.core.models.source import SourceClaimCreate
from packages.presentation.content_critic import (
    HARD_STOP_CHECK_IDS,
    ROUTABLE_CHECK_IDS,
    _message_carrying_token,
    critique_deck_adversarially,
)

# ---------------------------------------------------------------------------
# Fixtures + stub Gemini
# ---------------------------------------------------------------------------


class _FakeGemini:
    """Duck-typed GeminiClient returning scripted JSON response bodies."""

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.calls = 0

    async def complete(
        self,
        *,
        system: str,
        user: str,
        model: str,
        max_tokens: int = 2000,
        temperature: float = 0.0,
    ) -> LLMResponse:
        self.calls += 1
        if not self._responses:
            raise AssertionError("FakeGemini ran out of scripted responses")
        text = self._responses.pop(0)
        return LLMResponse(
            content=text,
            model=model,
            input_tokens=1,
            output_tokens=1,
            latency_ms=1,
            estimated_cost_usd=0.0,
        )


def _claim(text: str) -> SourceClaimCreate:
    return SourceClaimCreate(claim_text=text, strength=ClaimStrength.STRONG)


def _content(title: str, **kwargs: object) -> SlideContent:
    return SlideContent(title=title, **kwargs)  # type: ignore[arg-type]


def _slide(index: int, slide_type: SlideType, content: SlideContent) -> SlideSpec:
    return SlideSpec(slide_index=index, slide_type=slide_type, content=content)


def _plan(figures: list[PlannedFigure] | None = None) -> DeckPlan:
    return DeckPlan(
        thesis="Source-grounded decks must never assert facts the source omits.",
        audience_takeaway="Ground every claim in the source.",
        sections=[
            PlannedSection(
                section_name="Background",
                thesis="The reactor programme began under tight constraints.",
                phase=NarrativePhase.CONTEXT,
            ),
            PlannedSection(
                section_name="Results",
                thesis="The system met its efficiency target in evaluation.",
                phase=NarrativePhase.EVIDENCE,
            ),
        ],
        figures=figures or [],
        image_cohesion_note="Consistent technical-diagram aesthetic across the deck.",
    )


def _response(findings: list[dict[str, object]]) -> str:
    return json.dumps({"findings": findings})


def _finding(
    handle: int,
    category: str,
    *,
    slide_quote: str,
    unsupported_token: str | None = None,
    second_quote: str | None = None,
    message: str = "defect",
) -> dict[str, object]:
    return {
        "slide_handle": handle,
        "category": category,
        "message": message,
        "evidence": {
            "slide_quote": slide_quote,
            "unsupported_token": unsupported_token,
            "second_quote": second_quote,
        },
    }


# ---------------------------------------------------------------------------
# Grounding + severity gating
# ---------------------------------------------------------------------------


async def test_grounded_fabrication_with_absent_token_is_fail() -> None:
    slide = _slide(
        0,
        SlideType.CONCEPT_DEFINITION,
        _content("Background", body_text="The reactor reached 1200 degrees in 1987."),
    )
    claims = [_claim("The system operated at elevated temperature during testing.")]
    gemini = _FakeGemini(
        [
            _response(
                [
                    _finding(
                        1,
                        "fabrication",
                        slide_quote="The reactor reached 1200 degrees in 1987.",
                        unsupported_token="1987",
                    )
                ]
            )
        ]
    )

    result = (
        await critique_deck_adversarially([slide], _plan(), claims=claims, gemini=gemini)
    ).result

    assert len(result.failures) == 1
    finding = result.failures[0]
    assert finding.check_id == "C-FB"
    assert finding.severity is AuditSeverity.FAIL
    assert finding.slide_id == slide.slide_id
    assert finding.slide_index == slide.slide_index


async def test_off_slide_quote_is_dropped() -> None:
    slide = _slide(
        0,
        SlideType.CONCEPT_DEFINITION,
        _content("Background", body_text="The reactor reached 1200 degrees in 1987."),
    )
    claims = [_claim("The system operated at elevated temperature during testing.")]
    gemini = _FakeGemini(
        [
            _response(
                [
                    _finding(
                        1,
                        "fabrication",
                        slide_quote="The reactor exploded catastrophically in 1991.",
                        unsupported_token="1991",
                    )
                ]
            )
        ]
    )

    result = (
        await critique_deck_adversarially([slide], _plan(), claims=claims, gemini=gemini)
    ).result

    # The quote is not on the slide -> dropped; the slide has a body so no C-HL.
    assert result.findings == []


async def test_token_present_in_claims_degrades_to_warn() -> None:
    slide = _slide(
        0,
        SlideType.CONCEPT_DEFINITION,
        _content("Era", body_text="The Enlightenment reshaped European thought."),
    )
    # Claim contains the token in a different case — the normalized absence check
    # must see it as PRESENT and degrade the finding to WARN, never a false FAIL.
    claims = [_claim("the enlightenment transformed europe over a century.")]
    gemini = _FakeGemini(
        [
            _response(
                [
                    _finding(
                        1,
                        "claim_unsupported",
                        slide_quote="The Enlightenment reshaped European thought.",
                        unsupported_token="Enlightenment",
                    )
                ]
            )
        ]
    )

    result = (
        await critique_deck_adversarially([slide], _plan(), claims=claims, gemini=gemini)
    ).result

    assert result.failures == []
    assert len(result.warnings) == 1
    assert result.warnings[0].check_id == "C-US"
    assert result.passed is True


async def test_absence_check_reads_full_claims_not_capped_pool() -> None:
    slide = _slide(
        0,
        SlideType.CONCEPT_DEFINITION,
        _content("Process", body_text="The Zorblax process yields 42 units."),
    )
    # 70 claims; the supporting one sits beyond the 60-claim prompt cap. The
    # model never sees it, but the code absence check reads the FULL list, so the
    # token is PRESENT -> WARN, not a false fabrication.
    claims = [_claim(f"Filler claim number {i} about unrelated topics here.") for i in range(64)]
    claims.append(_claim("The Zorblax process is documented in the appendix."))
    claims.extend(_claim(f"More filler claim {i} with padding text here.") for i in range(5))
    assert len(claims) > 60
    gemini = _FakeGemini(
        [
            _response(
                [
                    _finding(
                        1,
                        "fabrication",
                        slide_quote="The Zorblax process yields 42 units.",
                        unsupported_token="Zorblax",
                    )
                ]
            )
        ]
    )

    result = (
        await critique_deck_adversarially([slide], _plan(), claims=claims, gemini=gemini)
    ).result

    assert result.failures == []
    assert any(w.check_id == "C-FB" and w.severity is AuditSeverity.WARN for w in result.warnings)


async def test_fabrication_token_matching_roster_person_is_dropped() -> None:
    slide = _slide(
        0,
        SlideType.CONCEPT_DEFINITION,
        _content("Thinkers", body_text="Voltaire championed reason and tolerance."),
    )
    claims = [_claim("The era emphasised reason, tolerance, and free inquiry above all.")]
    plan = _plan(
        figures=[
            PlannedFigure(name="Voltaire", why_in_source="Named in the source as a key figure.")
        ]
    )
    gemini = _FakeGemini(
        [
            _response(
                [
                    _finding(
                        1,
                        "fabrication",
                        slide_quote="Voltaire championed reason and tolerance.",
                        unsupported_token="Voltaire",
                    )
                ]
            )
        ]
    )

    result = (await critique_deck_adversarially([slide], plan, claims=claims, gemini=gemini)).result

    # People are owned by the upstream D-X1 gate; critic fabrication is non-person.
    assert result.findings == []


async def test_chart_encoding_wrong_with_two_on_slide_quotes_is_fail() -> None:
    slide = _slide(
        0,
        SlideType.CHART_DATA,
        _content(
            "Efficiency by climate zone",
            chart_series=[
                ChartSeriesPoint(label="Cost in Seattle", value=1.0),
                ChartSeriesPoint(label="Cost in Phoenix", value=2.0),
            ],
        ),
    )
    claims = [_claim("Efficiency and cost were both evaluated across several climate zones.")]
    gemini = _FakeGemini(
        [
            _response(
                [
                    _finding(
                        1,
                        "chart_encoding_wrong",
                        slide_quote="Efficiency by climate zone",
                        second_quote="Cost in Seattle",
                    )
                ]
            )
        ]
    )

    result = (
        await critique_deck_adversarially([slide], _plan(), claims=claims, gemini=gemini)
    ).result

    assert len(result.failures) == 1
    finding = result.failures[0]
    assert finding.check_id == "C-CE"
    assert finding.slide_id == slide.slide_id


async def test_structural_finding_is_emit_only_warning() -> None:
    slide = _slide(
        0,
        SlideType.CONCEPT_DEFINITION,
        _content("Background", body_text="A paragraph about the reactor programme history."),
    )
    claims = [_claim("The reactor programme has a documented multi-decade history.")]
    gemini = _FakeGemini(
        [
            _response(
                [
                    _finding(
                        1,
                        "section_off_thesis",
                        slide_quote="A paragraph about the reactor programme history.",
                        message="Section drifts from its thesis.",
                    )
                ]
            )
        ]
    )

    result = (
        await critique_deck_adversarially([slide], _plan(), claims=claims, gemini=gemini)
    ).result

    assert result.failures == []
    assert len(result.warnings) == 1
    assert result.warnings[0].check_id == "C-SO"
    assert result.passed is True


async def test_cosmetic_finding_does_not_flip_passed() -> None:
    slide = _slide(
        0,
        SlideType.CONCEPT_DEFINITION,
        _content("Background", body_text="Some generic filler prose about the topic here."),
    )
    claims = [_claim("The topic is introduced with appropriate background material here.")]
    gemini = _FakeGemini(
        [
            _response(
                [
                    _finding(
                        1,
                        "weak_craft",
                        slide_quote="Some generic filler prose about the topic here.",
                        message="Weak, generic writing.",
                    )
                ]
            )
        ]
    )

    result = (
        await critique_deck_adversarially([slide], _plan(), claims=claims, gemini=gemini)
    ).result

    assert result.passed is True
    assert all(w.severity is AuditSeverity.WARN for w in result.warnings)


async def test_handle_maps_to_durable_slide_id() -> None:
    first = _slide(
        0, SlideType.CONCEPT_DEFINITION, _content("First", body_text="First slide body text here.")
    )
    second = _slide(
        1,
        SlideType.CONCEPT_DEFINITION,
        _content("Second", body_text="The output doubled to 84 percent overnight."),
    )
    claims = [_claim("The output improved noticeably over the evaluation period overall.")]
    gemini = _FakeGemini(
        [
            _response(
                [
                    _finding(
                        2,
                        "fabrication",
                        slide_quote="The output doubled to 84 percent overnight.",
                        unsupported_token="84 percent",
                    )
                ]
            )
        ]
    )

    result = (
        await critique_deck_adversarially([first, second], _plan(), claims=claims, gemini=gemini)
    ).result

    assert len(result.failures) == 1
    assert result.failures[0].slide_id == second.slide_id
    assert result.failures[0].slide_index == second.slide_index


# ---------------------------------------------------------------------------
# Code-detected hollow slides + degrade paths
# ---------------------------------------------------------------------------


async def test_hollow_slide_detected_in_code_without_llm_finding() -> None:
    hollow = _slide(0, SlideType.CONCEPT_DEFINITION, _content("Just a title"))
    full = _slide(
        1, SlideType.CONCEPT_DEFINITION, _content("Real", body_text="This slide has real content.")
    )
    claims = [_claim("The deck covers a topic with at least one substantive slide here.")]
    gemini = _FakeGemini([_response([])])  # model reports nothing

    outcome = await critique_deck_adversarially(
        [hollow, full], _plan(), claims=claims, gemini=gemini
    )
    result = outcome.result

    # A parsed, empty findings list is a real "clean" verdict, not a degrade.
    assert outcome.llm_verified is True
    # Hollow slides are emit-only WARN (visibility), never a routable FAIL.
    hollow_findings = [f for f in result.warnings if f.check_id == "C-HL"]
    assert len(hollow_findings) == 1
    assert hollow_findings[0].slide_id == hollow.slide_id
    assert result.failures == []


async def test_title_hero_only_title_is_not_hollow() -> None:
    title = _slide(0, SlideType.TITLE_HERO, _content("Deck Title"))
    claims = [_claim("The deck opens with a title slide and then develops its argument.")]
    gemini = _FakeGemini([_response([])])

    result = (
        await critique_deck_adversarially([title], _plan(), claims=claims, gemini=gemini)
    ).result

    assert result.findings == []


async def test_empty_claims_skips_llm_call() -> None:
    slide = _slide(
        0, SlideType.CONCEPT_DEFINITION, _content("Background", body_text="Body text present.")
    )
    gemini = _FakeGemini([])  # must not be called

    outcome = await critique_deck_adversarially([slide], _plan(), claims=[], gemini=gemini)

    assert gemini.calls == 0
    # No claims to ground against -> vacuously clean, NOT a degrade.
    assert outcome.llm_verified is True
    assert outcome.result.findings == []


async def test_unparseable_response_degrades_to_hollow_only() -> None:
    hollow = _slide(0, SlideType.CONCEPT_DEFINITION, _content("Empty"))
    claims = [_claim("The deck has at least one source claim to ground against here.")]
    gemini = _FakeGemini(["not json at all", "still not json"])

    outcome = await critique_deck_adversarially([hollow], _plan(), claims=claims, gemini=gemini)

    assert gemini.calls == 2  # first + one retry
    # Unparseable after retry: the source-grounding verdict could NOT be
    # established. The caller must not read these empty failures as "clean".
    assert outcome.llm_verified is False
    assert [f.check_id for f in outcome.result.findings] == ["C-HL"]


async def test_parseable_finding_is_verified() -> None:
    """A parsed response that PRODUCES a finding is a real verdict (llm_verified)."""
    slide = _slide(
        0,
        SlideType.CONCEPT_DEFINITION,
        _content("Background", body_text="The reactor reached 1200 degrees in 1987."),
    )
    claims = [_claim("The system operated at elevated temperature during testing.")]
    gemini = _FakeGemini(
        [
            _response(
                [
                    _finding(
                        1,
                        "fabrication",
                        slide_quote="The reactor reached 1200 degrees in 1987.",
                        unsupported_token="1987",
                    )
                ]
            )
        ]
    )

    outcome = await critique_deck_adversarially([slide], _plan(), claims=claims, gemini=gemini)

    assert outcome.llm_verified is True
    assert len(outcome.result.failures) == 1


def test_routable_and_hard_stop_check_id_membership() -> None:
    assert frozenset({"C-FB", "C-US", "C-CE", "C-TS"}) == ROUTABLE_CHECK_IDS
    assert frozenset({"C-FB", "C-US"}) == HARD_STOP_CHECK_IDS
    # Hollow is emit-only WARN: code-detected for visibility, never routed.
    assert "C-HL" not in ROUTABLE_CHECK_IDS
    assert "C-HL" not in HARD_STOP_CHECK_IDS


def test_message_carrying_token_always_appends_token() -> None:
    appended = _message_carrying_token("Generic defect.", "73.8 bar")
    assert appended.endswith('[unsupported: "73.8 bar"]')
    assert appended.startswith("Generic defect.")
    capped = _message_carrying_token("x" * 500, "1987")
    assert len(capped) <= 500
    assert capped.endswith('[unsupported: "1987"]')
    # The append is UNCONDITIONAL: a containment check would let a short token
    # hide inside a longer one already in the message and collapse two distinct
    # defects in the verification union.
    shared = "The range 1987-1991 is not supported by the source."
    short = _message_carrying_token(shared, "1987")
    long = _message_carrying_token(shared, "1987-1991")
    assert short != long
    assert short.endswith('[unsupported: "1987"]')
    assert long.endswith('[unsupported: "1987-1991"]')


async def test_two_generic_message_fabrications_on_one_slide_stay_distinct() -> None:
    """The grounding token is a finding's true discriminator: two same-slide
    fabrications sharing one generic model message must yield DISTINCT finding
    messages (each carrying its token), so the verification union — whose dedupe
    key reads only the message — cannot collapse them into one."""

    slide = _slide(
        0,
        SlideType.CONCEPT_DEFINITION,
        _content("Background", body_text="The reactor reached 1200 degrees in 1987."),
    )
    claims = [_claim("The system operated at elevated temperature during testing.")]
    generic = "Slide asserts a value the source does not support."
    gemini = _FakeGemini(
        [
            _response(
                [
                    _finding(
                        1,
                        "fabrication",
                        slide_quote="The reactor reached 1200 degrees in 1987.",
                        unsupported_token="1200 degrees",
                        message=generic,
                    ),
                    _finding(
                        1,
                        "fabrication",
                        slide_quote="The reactor reached 1200 degrees in 1987.",
                        unsupported_token="1987",
                        message=generic,
                    ),
                ]
            )
        ]
    )

    result = (
        await critique_deck_adversarially([slide], _plan(), claims=claims, gemini=gemini)
    ).result

    assert len(result.failures) == 2
    messages = {f.message for f in result.failures}
    assert len(messages) == 2
    assert any("1200 degrees" in m for m in messages)
    assert any("1987" in m for m in messages)
