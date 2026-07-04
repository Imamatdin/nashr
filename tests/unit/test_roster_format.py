"""Tests for human-facing deck roster display numbers (1-based labels)."""

from __future__ import annotations

import pytest
from google.genai import types as genai_types

from packages.bot.handlers import presentation_flow as pf
from packages.bot.orchestrators.article_orchestrator import SourceProcessingResult
from packages.bot.sessions.driver import (
    GeminiBrainDriver,
    ScriptedStubDriver,
    StubResponse,
    _context_block,
)
from packages.bot.sessions.models import BrainSession, TurnAction
from packages.bot.sessions.roster_format import (
    display_slide_number,
    format_roster_line,
    render_roster_payload,
    render_roster_text,
)
from packages.bot.sessions.store import load_session
from packages.core.enums import AudienceType, ExportFormat, GenerationPackage
from packages.core.models.presentation import SlideFix
from tests.unit.test_brain_loop import _reply_turn
from tests.unit.test_brain_session import _FakeOrchestrator, _provision
from tests.unit.test_database_client import _make_deck


def test_display_slide_number_is_one_based() -> None:
    assert display_slide_number(0) == 1
    assert display_slide_number(4) == 5


def test_roster_line_for_index_zero_renders_as_one() -> None:
    deck = _make_deck(title="Cooling", audience=AudienceType.UNDERGRADUATE)
    first = deck.slides[0]

    line = format_roster_line(first)

    assert line.startswith(f"[1] slide_id={first.slide_id}")
    assert "[0]" not in line


def test_render_roster_text_and_payload_share_display_numbers() -> None:
    deck = _make_deck(title="Cooling", audience=AudienceType.UNDERGRADUATE)

    text = render_roster_text(deck)
    payload = render_roster_payload(deck)

    assert len(payload) == len(deck.slides)
    for slide, entry in zip(deck.slides, payload, strict=True):
        number = display_slide_number(slide.slide_index)
        assert f"[{number}] slide_id={slide.slide_id}" in text
        assert entry["slide_number"] == number
        assert entry["slide_id"] == slide.slide_id
        assert entry["slide_type"] == slide.slide_type.value
        assert entry["title"] == slide.content.title


def test_context_block_uses_one_based_roster() -> None:
    deck = _make_deck(title="Cooling", audience=AudienceType.UNDERGRADUATE)
    session = BrainSession(
        project_id="proj-1",
        history=[],
        sources=SourceProcessingResult(claims=[]),
        deck=deck,
        package=GenerationPackage.PRESENTATION_STANDARD,
        formats=[ExportFormat.HTML],
    )

    block = _context_block(session)

    assert f"[1] slide_id={deck.slides[0].slide_id}" in block
    assert "[0]" not in block.split("SOURCE CLAIMS", maxsplit=1)[0]


@pytest.mark.asyncio
async def test_delivered_fix_function_response_roster_matches_text_numbers() -> None:
    db, _fake, deck, _sources = await _provision()
    driver = ScriptedStubDriver()
    driver.queue(
        StubResponse(
            action=TurnAction.FIX,
            fixes=(SlideFix(slide_id="s0", instruction="tighten the title"),),
        )
    )
    orch = _FakeOrchestrator(deck)

    await pf._run_chat_turn(
        driver=driver,
        orchestrator=orch,
        db=db,
        project_id="proj-1",
        user_text="fix slide",
        user_initiated=True,
    )

    reloaded = await load_session(db, "proj-1")
    assert reloaded is not None
    last = reloaded.history[-1]
    assert last.parts is not None
    response = last.parts[0].function_response
    assert response is not None
    roster = response.response["roster"]
    assert isinstance(roster, list)
    for slide, entry in zip(deck.slides, roster, strict=True):
        assert entry["slide_number"] == display_slide_number(slide.slide_index)


@pytest.mark.asyncio
async def test_first_turn_injected_roster_is_one_based() -> None:
    class _FakeGemini:
        def __init__(self) -> None:
            self.captured: list[list[genai_types.Content]] = []

        async def generate_with_tools(
            self,
            contents: list[genai_types.Content],
            *_: object,
            **__: object,
        ) -> object:
            self.captured.append(list(contents))
            return _reply_turn("ok")

    gemini = _FakeGemini()
    driver = GeminiBrainDriver(gemini=gemini)  # type: ignore[arg-type]
    deck = _make_deck(title="Cooling", audience=AudienceType.UNDERGRADUATE)
    session = BrainSession(
        project_id="proj-1",
        history=[],
        sources=SourceProcessingResult(claims=[]),
        deck=deck,
        package=GenerationPackage.PRESENTATION_STANDARD,
        formats=[ExportFormat.HTML],
    )

    await driver.run_turn(session, "hello")

    sent = "".join(part.text or "" for part in (gemini.captured[0][0].parts or []))
    assert f"[1] slide_id={deck.slides[0].slide_id}" in sent
    assert "[0]" not in sent.split("SOURCE CLAIMS", maxsplit=1)[0]
