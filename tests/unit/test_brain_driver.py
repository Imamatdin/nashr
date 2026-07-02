"""Behaviour tests for the real conversational brain (Build 2, Stage 5a, Way 2).

Drives :class:`GeminiBrainDriver.run_turn` against a fake Gemini boundary. The
behaviours locked here: a requested edit leaves the turn ONLY as
``TurnOutcome.fixes`` (never applied — the driver has no orchestrator), a plain
answer becomes a REPLY, the first turn injects the deck roster + source claims
into the (append-only) history, later turns append only the user's text, and any
transport failure degrades to a reply instead of crashing the turn.
"""

from __future__ import annotations

import pytest
from google.genai import types as genai_types

from packages.bot.orchestrators.article_orchestrator import SourceProcessingResult
from packages.bot.sessions.driver import GeminiBrainDriver
from packages.bot.sessions.models import BrainSession, TurnAction
from packages.core.enums import (
    AudienceType,
    ClaimStrength,
    ClaimType,
    ExportFormat,
    GenerationPackage,
)
from packages.core.models.source import SourceClaimCreate
from tests.unit.test_brain_loop import _fix_turn, _reply_turn
from tests.unit.test_database_client import _make_deck


class _FakeGemini:
    """A fake GeminiClient that returns queued tool-turns and records sent contents."""

    def __init__(self, outcomes: list[object]) -> None:
        self._outcomes = list(outcomes)
        self.captured: list[list[genai_types.Content]] = []

    async def generate_with_tools(
        self,
        contents: list[genai_types.Content],
        tools: list[genai_types.Tool],
        *,
        system: str | None = None,
        tool_mode: object = None,
        allowed_function_names: list[str] | None = None,
        max_tokens: int | None = None,
        **_: object,
    ) -> object:
        self.captured.append(list(contents))
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _sources() -> SourceProcessingResult:
    return SourceProcessingResult(
        claims=[
            SourceClaimCreate(
                source_chunk_id="c1",
                project_id="proj-1",
                claim_text="Radiative cooling cut water use by 94 percent.",
                strength=ClaimStrength.STRONG,
                claim_type=ClaimType.STATISTICAL_RESULT,
            )
        ]
    )


def _session(*, history: list[genai_types.Content] | None = None) -> BrainSession:
    return BrainSession(
        project_id="proj-1",
        history=history or [],
        sources=_sources(),
        deck=_make_deck(title="Cooling", audience=AudienceType.UNDERGRADUATE),
        package=GenerationPackage.PRESENTATION_STANDARD,
        formats=[ExportFormat.HTML, ExportFormat.PPTX_EDITABLE],
    )


def _text_of(content: genai_types.Content) -> str:
    return "".join(part.text or "" for part in (content.parts or []))


@pytest.mark.asyncio
async def test_fix_turn_returns_fixes_without_applying() -> None:
    gemini = _FakeGemini(
        [_fix_turn([{"slide_id": "slide_02", "instruction": "drop the fake stat"}])]
    )
    driver = GeminiBrainDriver(gemini=gemini)  # type: ignore[arg-type]

    outcome = await driver.run_turn(_session(), "fix slide 2")

    assert outcome.action is TurnAction.FIX
    assert len(outcome.fixes) == 1
    assert outcome.fixes[0].slide_id == "slide_02"
    assert outcome.fix_call_count == 1  # carried through so dispatch answers each call
    # The fix-exit discipline is structural: the driver holds no orchestrator, so
    # a fix can only leave the turn as data, never be applied here.
    assert not hasattr(driver, "apply_fixes_and_render")
    assert not hasattr(driver, "orchestrator")
    assert outcome.history[-1].role == "model"


@pytest.mark.asyncio
async def test_reply_turn_returns_reply() -> None:
    gemini = _FakeGemini([_reply_turn("Slide 3 already cites the source.")])
    driver = GeminiBrainDriver(gemini=gemini)  # type: ignore[arg-type]

    outcome = await driver.run_turn(_session(), "does slide 3 cite anything?")

    assert outcome.action is TurnAction.REPLY
    assert outcome.reply_text == "Slide 3 already cites the source."
    assert outcome.fixes == ()


@pytest.mark.asyncio
async def test_first_turn_injects_roster_and_claims() -> None:
    gemini = _FakeGemini([_reply_turn("ok")])
    driver = GeminiBrainDriver(gemini=gemini)  # type: ignore[arg-type]
    session = _session()
    assert session.deck is not None
    first_slide_id = session.deck.slides[0].slide_id

    await driver.run_turn(session, "hello")

    sent = _text_of(gemini.captured[0][0])
    assert "DECK ROSTER" in sent
    assert first_slide_id in sent  # slides are addressable by stable id
    assert "Opening" in sent  # a slide title from _make_deck
    assert "Radiative cooling cut water use by 94 percent." in sent  # a source claim
    assert "hello" in sent  # the user's message rides the same first turn


@pytest.mark.asyncio
async def test_later_turn_appends_only_user_text() -> None:
    gemini = _FakeGemini([_reply_turn("ok")])
    driver = GeminiBrainDriver(gemini=gemini)  # type: ignore[arg-type]
    prior = [
        genai_types.Content(role="user", parts=[genai_types.Part(text="earlier")]),
        genai_types.Content(role="model", parts=[genai_types.Part(text="earlier reply")]),
    ]
    session = _session(history=prior)

    await driver.run_turn(session, "second message")

    sent = gemini.captured[0]
    # Prior history preserved verbatim, plus one plain user turn — no re-injected context.
    assert len(sent) == 3
    last = _text_of(sent[-1])
    assert last == "second message"
    assert "DECK ROSTER" not in last


@pytest.mark.asyncio
async def test_turn_failure_degrades_to_reply() -> None:
    gemini = _FakeGemini([RuntimeError("transport exploded")])
    driver = GeminiBrainDriver(gemini=gemini)  # type: ignore[arg-type]
    session = _session()

    outcome = await driver.run_turn(session, "fix it")

    assert outcome.action is TurnAction.REPLY
    assert outcome.reply_text is None
    # A failed turn leaves no trace — history is unchanged so the user can retry.
    assert outcome.history == session.history
