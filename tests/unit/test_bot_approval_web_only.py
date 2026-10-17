"""The bot's Approve button applies nothing until B8 item 1 (bot approvals queued like web ones).

The inline apply committed through commit_revision without operation fencing, so
for now the button answers that edits are applied from the web, and the decision
stays parked for the web's approval or the bot's Reject.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from packages.bot.labels import get_bot_labels
from packages.bot.sessions import load_session
from tests.unit.test_b1_fix5_regressions import (
    _bot_decision,  # pyright: ignore[reportPrivateUsage]
    _button,  # pyright: ignore[reportPrivateUsage]
    _press,  # pyright: ignore[reportPrivateUsage]
)
from tests.unit.test_brain_session import (
    _FakeOrchestrator,  # pyright: ignore[reportPrivateUsage]
    _provision,  # pyright: ignore[reportPrivateUsage]
)

pytestmark = pytest.mark.asyncio


def _snapshot(fake: Any) -> dict[str, Any]:
    return copy.deepcopy(
        {
            table: fake.tables.get(table, [])
            for table in (
                "brain_sessions",
                "document_revisions",
                "revision_proposals",
                "edit_deliveries",
                "generation_jobs",
                "documents",
            )
        }
    )


async def test_bot_approve_commits_delivers_and_counts_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db, fake, deck, _sources = await _provision()
    decision = await _bot_decision(db, deck, "make it warmer")
    orchestrator = _FakeOrchestrator(deck)
    before = _snapshot(fake)

    sent = await _press(monkeypatch, db, _button("apr", decision), orchestrator, approve=True)

    assert sent == [get_bot_labels("uz").approval_web_only]
    assert orchestrator.calls == [], "the bot applied the edit"
    # No revision, proposal, delivery, job or allowance change: nothing was written.
    assert _snapshot(fake) == before
    session = await load_session(db, "proj-1")
    assert session is not None and session.pending_action is not None
    assert session.parked_operation_id == decision["operation_id"]
    assert session.fixes_used == 0


async def test_bot_reject_still_discards_the_decision(monkeypatch: pytest.MonkeyPatch) -> None:
    db, _fake, deck, _sources = await _provision()
    decision = await _bot_decision(db, deck, "make it warmer")

    await _press(monkeypatch, db, _button("rej", decision), _FakeOrchestrator(deck), approve=False)

    session = await load_session(db, "proj-1")
    assert session is not None
    assert session.pending_action is None and session.parked_operation_id is None


async def test_the_web_only_message_exists_in_every_bot_language() -> None:
    texts = [get_bot_labels(lang).approval_web_only for lang in ("uz", "ru", "kaa", "en")]
    assert all(texts) and len(set(texts)) == 4
