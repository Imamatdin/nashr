"""Behaviour tests for the shared web-chat machinery (Session W, P1.2).

Drives ``packages.sessions_core.chat`` directly — below the HTTP layer — against
the same in-memory Supabase fake the session-store tests use, so every durability
claim goes through a real serialize → row → deserialize round trip.

The contract under test is the parked-fix interlock: a turn that asks for edits
persists the model's ``edit_slides`` call UNANSWERED, no further turn may run
until a worker answers it, and the tier's fix allowance is consumed if and only
if the apply actually delivered a file.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, cast

from google.genai import types as genai_types

from packages.bot.sessions.models import BrainSession, PendingAction, TurnAction, TurnOutcome
from packages.bot.sessions.store import load_session, persist_session
from packages.core.brain_loop import EDIT_SLIDES_TOOL_NAME
from packages.core.enums import GenerationPackage
from packages.core.models.presentation import SlideFix
from packages.platform.database import DatabaseClient
from packages.sessions_core.chat import (
    TurnKind,
    abandon_parked_fix,
    append_fix_result,
    dispatch_fix,
    has_dangling_call,
    history_for_wire,
    repair_dangling_call,
    run_web_turn,
)
from tests.unit.test_brain_session import (
    _FakeOrchestrator,  # pyright: ignore[reportPrivateUsage]
    _provision,  # pyright: ignore[reportPrivateUsage]
    _RaisingOrchestrator,  # pyright: ignore[reportPrivateUsage]
)
from tests.unit.test_database_client import _make_db  # pyright: ignore[reportPrivateUsage]


async def _no_edit_job() -> bool:
    """The queue probe ``run_web_turn`` awaits when it finds a dangling call.

    A callable, not a flag: the repair decision is only safe if it is made
    against the queue AT THE MOMENT the dangling call is found.
    """

    return False


async def _live_edit_job() -> bool:
    """A worker is mid-apply: the parked call is its to answer, not ours."""

    return True


_CONTEXT_BLOCK = (
    "DECK ROSTER (address slides by slide_id):\n"
    "- s0: Opening\n\n"
    "SOURCE CLAIMS (ground every edit only in these):\n"
    "- Radiative cooling cut water use by 94 percent."
)
_SEPARATOR = "\n\n---\n\n"

_Progress = Callable[[str, int, int], Awaitable[None]]


async def _noop_progress(stage: str, done: int, total: int) -> None:
    """The progress sink dispatch_fix hands to the runner."""

    del stage, done, total


def _progress() -> _Progress:
    return cast(_Progress, _noop_progress)


def _call_part(instruction: str) -> genai_types.Part:
    """One real ``edit_slides`` function_call part, as the brain emits it."""

    return genai_types.Part.from_function_call(
        name=EDIT_SLIDES_TOOL_NAME,
        args={"fixes": [{"slide_id": "s0", "instruction": instruction}]},
    )


def _model_turn(text: str, *, calls: int = 0) -> genai_types.Content:
    parts = [genai_types.Part(text=text)] if text else []
    parts.extend(_call_part(f"edit {index}") for index in range(calls))
    return genai_types.Content(role="model", parts=parts)


def _user_turn(text: str) -> genai_types.Content:
    return genai_types.Content(role="user", parts=[genai_types.Part(text=text)])


class _FakeDriver:
    """A ``BrainDriver`` stand-in that emits REAL function_call parts.

    ``ScriptedStubDriver`` appends text-only turns, which cannot express the
    unanswered-call interlock these tests exist to prove, so a fix turn here
    appends a model Content carrying ``call_count`` genuine ``edit_slides`` call
    parts — exactly the history shape that must survive persistence.
    """

    def __init__(
        self,
        *,
        reply_text: str | None = "ok",
        fixes: tuple[SlideFix, ...] = (),
        call_count: int = 0,
        cost: float = 0.0,
    ) -> None:
        self._reply_text = reply_text
        self._fixes = fixes
        self._call_count = call_count
        self._cost = cost
        self.calls: list[str] = []

    async def run_turn(self, session: BrainSession, user_text: str) -> TurnOutcome:
        self.calls.append(user_text)
        history = [
            *session.history,
            _user_turn(user_text),
            _model_turn(self._reply_text or "", calls=self._call_count),
        ]
        return TurnOutcome(
            action=TurnAction.FIX if self._fixes else TurnAction.REPLY,
            history=history,
            estimated_cost_usd=self._cost,
            reply_text=self._reply_text,
            fixes=self._fixes,
            fix_call_count=self._call_count,
        )


class _ExplodingDriver:
    """Any run_turn call is a contract violation."""

    async def run_turn(self, *_args: Any, **_kwargs: Any) -> TurnOutcome:
        raise AssertionError("a brain turn must NOT run against an unanswered call")


async def _session(db: DatabaseClient) -> BrainSession:
    session = await load_session(db, "proj-1")
    assert session is not None
    return session


def _response_parts(content: genai_types.Content) -> list[genai_types.FunctionResponse]:
    return [
        part.function_response
        for part in (content.parts or [])
        if part.function_response is not None
    ]


def _response_payload(content: genai_types.Content, index: int = 0) -> dict[str, Any]:
    responses = _response_parts(content)
    payload = responses[index].response
    assert payload is not None
    return payload


async def _park_a_dangling_call(db: DatabaseClient, *, calls: int = 1) -> None:
    """Persist a session whose history ends with an unanswered edit_slides call."""

    session = await _session(db)
    session.history = [_user_turn("tighten slide one"), _model_turn("on it", calls=calls)]
    await persist_session(db, session)


# ---------------------------------------------------------------- wire history


async def test_history_for_wire_strips_injected_context_only_on_the_first_turn() -> None:
    db, _fake, _deck, _sources = await _provision()
    session = await _session(db)
    echoed = f"{_CONTEXT_BLOCK}{_SEPARATOR}why did you keep this text?"
    session.history = [
        _user_turn(f"{_CONTEXT_BLOCK}{_SEPARATOR}make slide two shorter"),
        _model_turn("", calls=1),
        genai_types.Content(
            role="user",
            parts=[
                genai_types.Part.from_function_response(
                    name=EDIT_SLIDES_TOOL_NAME, response={"delivered": True}
                )
            ],
        ),
        _model_turn("Done — slide two is tighter."),
        _user_turn(echoed),
    ]

    wire = history_for_wire(session)

    assert wire == [
        {"role": "user", "text": "make slide two shorter"},
        {"role": "assistant", "text": "Done — slide two is tighter."},
        # A LATER user message quoting the same literal block is the user's own
        # words: only index 0 carries the injected prefix.
        {"role": "user", "text": echoed},
    ]


# -------------------------------------------------------------- dangling calls


async def test_has_dangling_call_counts_parts_and_clears_on_the_answer() -> None:
    db, _fake, _deck, _sources = await _provision()
    session = await _session(db)
    session.history = [_user_turn("two edits"), _model_turn("on it", calls=2)]

    assert has_dangling_call(session) == 2

    append_fix_result(session, {"delivered": True}, count=2)
    assert has_dangling_call(session) == 0


async def test_repair_dangling_call_answers_every_part_and_persists() -> None:
    db, _fake, _deck, _sources = await _provision()
    await _park_a_dangling_call(db, calls=2)
    session = await _session(db)

    assert await repair_dangling_call(db, session) is True

    reloaded = await _session(db)
    assert has_dangling_call(reloaded) == 0
    assert len(_response_parts(reloaded.history[-1])) == 2
    assert _response_payload(reloaded.history[-1])["error"] == "fix_failed"


async def test_repair_dangling_call_is_a_noop_without_one() -> None:
    db, _fake, _deck, _sources = await _provision()
    session = await _session(db)
    session.history = [_user_turn("hi"), _model_turn("hello")]

    assert await repair_dangling_call(db, session) is False
    assert len(session.history) == 2


# ------------------------------------------------------------------ turn side


async def test_turn_without_a_session_is_no_session() -> None:
    db, _fake = _make_db()
    driver = _FakeDriver()

    result = await run_web_turn(
        db, cast(Any, driver), project_id="ghost", user_text="hi", edit_job_active=_no_edit_job
    )

    assert result.kind is TurnKind.NO_SESSION
    assert driver.calls == []


async def test_turn_without_a_deck_is_no_session() -> None:
    db, fake, _deck, _sources = await _provision()
    fake.seed("decks", [])  # the deck row is gone; the session cannot edit
    driver = _FakeDriver()

    result = await run_web_turn(
        db, cast(Any, driver), project_id="proj-1", user_text="hi", edit_job_active=_no_edit_job
    )

    assert result.kind is TurnKind.NO_SESSION
    assert driver.calls == []


async def test_parked_pending_action_routes_back_without_running_the_driver() -> None:
    db, _fake, _deck, _sources = await _provision()
    session = await _session(db)
    session.pending_action = PendingAction(
        fixes=[SlideFix(slide_id="s0", instruction="a big rewrite")],
        reason="significant",
        call_count=1,
    )
    session.history = [_user_turn("ok"), _model_turn("proposing", calls=1)]
    await persist_session(db, session)

    result = await run_web_turn(
        db,
        cast(Any, _ExplodingDriver()),
        project_id="proj-1",
        user_text="something else",
        edit_job_active=_no_edit_job,
    )

    assert result.kind is TurnKind.AWAITING_APPROVAL
    assert result.pending is not None
    assert result.pending.reason == "significant"
    assert result.pending.call_count == 1


async def test_plain_reply_turn_persists_and_asks_for_no_fixes() -> None:
    db, _fake, _deck, _sources = await _provision()
    driver = _FakeDriver(reply_text="the deck opens with the thesis", cost=0.04)

    result = await run_web_turn(
        db,
        cast(Any, driver),
        project_id="proj-1",
        user_text="what is slide one?",
        edit_job_active=_no_edit_job,
    )

    assert result.kind is TurnKind.REPLY
    assert result.reply_text == "the deck opens with the thesis"
    assert result.fixes == ()
    reloaded = await _session(db)
    assert len(reloaded.history) == 2
    assert has_dangling_call(reloaded) == 0
    assert reloaded.accumulated_cost_usd == 0.04


async def test_user_fix_turn_parks_the_unanswered_call_durably() -> None:
    # THE interlock: the PERSISTED history still ends with the model's unanswered
    # edit_slides call, so nothing may run against this session until a worker
    # answers it — across a process restart, because it lives in the row.
    db, _fake, _deck, _sources = await _provision()
    fixes = (
        SlideFix(slide_id="s0", instruction="tighten the title"),
        SlideFix(slide_id="s1", instruction="cut a bullet"),
    )
    driver = _FakeDriver(reply_text="on it", fixes=fixes, call_count=2)

    result = await run_web_turn(
        db,
        cast(Any, driver),
        project_id="proj-1",
        user_text="tighten slide one and two",
        edit_job_active=_no_edit_job,
    )

    assert result.kind is TurnKind.FIX_READY
    assert result.fixes == fixes
    assert result.fix_call_count == 2
    assert result.fixes_used == 0

    reloaded = await _session(db)
    assert has_dangling_call(reloaded) == 2
    assert (reloaded.history[-1].role or "") == "model"


async def test_fix_turn_with_the_allowance_spent_answers_the_call() -> None:
    db, _fake, _deck, _sources = await _provision(package=GenerationPackage.PRESENTATION_BASIC)
    session = await _session(db)
    session.fixes_used = 1  # basic's single edit is gone
    await persist_session(db, session)
    driver = _FakeDriver(
        reply_text="on it",
        fixes=(SlideFix(slide_id="s0", instruction="tighten"),),
        call_count=2,
    )

    result = await run_web_turn(
        db,
        cast(Any, driver),
        project_id="proj-1",
        user_text="one more edit",
        edit_job_active=_no_edit_job,
    )

    assert result.kind is TurnKind.FIXES_EXHAUSTED
    assert result.fixes == ()
    assert result.fix_limit == 1

    reloaded = await _session(db)
    assert reloaded.fixes_used == 1  # refusing consumed nothing
    assert has_dangling_call(reloaded) == 0  # the conversation is not wedged
    assert len(_response_parts(reloaded.history[-1])) == 2  # one per call part
    assert _response_payload(reloaded.history[-1])["error"] == "fixes_exhausted"


async def test_lost_edit_job_self_heals_then_the_turn_runs() -> None:
    db, _fake, _deck, _sources = await _provision()
    await _park_a_dangling_call(db)
    driver = _FakeDriver(reply_text="still here")

    result = await run_web_turn(
        db,
        cast(Any, driver),
        project_id="proj-1",
        user_text="are you there?",
        edit_job_active=_no_edit_job,
    )

    assert result.kind is TurnKind.REPLY
    assert driver.calls == ["are you there?"]
    reloaded = await _session(db)
    assert has_dangling_call(reloaded) == 0
    assert _response_payload(reloaded.history[2])["detail"] == "edit_job_lost"


async def test_live_edit_job_refuses_the_turn_instead_of_repairing() -> None:
    db, _fake, _deck, _sources = await _provision()
    await _park_a_dangling_call(db)

    result = await run_web_turn(
        db,
        cast(Any, _ExplodingDriver()),
        project_id="proj-1",
        user_text="are you there?",
        edit_job_active=_live_edit_job,
    )

    assert result.kind is TurnKind.AWAITING_APPROVAL
    # No parked decision to re-present — the worker owns the call, not the gate.
    assert result.pending is None
    reloaded = await _session(db)
    assert has_dangling_call(reloaded) == 1  # untouched; the worker will answer it


async def test_abandon_parked_fix_unwedges_a_failed_enqueue() -> None:
    db, _fake, _deck, _sources = await _provision()
    await _park_a_dangling_call(db)

    await abandon_parked_fix(db, "proj-1", call_count=1)

    reloaded = await _session(db)
    assert has_dangling_call(reloaded) == 0
    assert _response_payload(reloaded.history[-1])["detail"] == "enqueue_failed"


async def test_abandon_parked_fix_is_a_noop_without_a_dangling_call() -> None:
    db, _fake, _deck, _sources = await _provision()
    session = await _session(db)
    session.history = [_user_turn("hi"), _model_turn("hello")]
    await persist_session(db, session)

    await abandon_parked_fix(db, "proj-1", call_count=1)

    reloaded = await _session(db)
    assert len(reloaded.history) == 2


# ---------------------------------------------------------- allowance contract


async def test_delivered_fix_consumes_exactly_one_edit_and_answers_the_call() -> None:
    db, _fake, deck, _sources = await _provision()
    await _park_a_dangling_call(db)
    runner = _FakeOrchestrator(deck, cost=0.25, images=1)

    result = await dispatch_fix(
        runner=cast(Any, runner),
        db=db,
        project_id="proj-1",
        fixes=[SlideFix(slide_id="s0", instruction="tighten")],
        call_count=1,
        progress=_progress(),
    )

    assert result.delivered is True
    assert result.slides_changed == 1
    assert len(runner.calls) == 1
    assert runner.calls[0]["figures_seen"] == 1  # figures hydrated before grounding
    reloaded = await _session(db)
    assert reloaded.fixes_used == 1
    assert reloaded.accumulated_cost_usd == 0.25
    assert reloaded.accumulated_image_count == 1
    assert _response_payload(reloaded.history[-1])["delivered"] is True


async def test_multi_call_dispatch_answers_every_parked_call_part() -> None:
    db, _fake, deck, _sources = await _provision()
    await _park_a_dangling_call(db, calls=2)
    runner = _FakeOrchestrator(deck)

    result = await dispatch_fix(
        runner=cast(Any, runner),
        db=db,
        project_id="proj-1",
        fixes=[
            SlideFix(slide_id="s0", instruction="one"),
            SlideFix(slide_id="s1", instruction="two"),
        ],
        call_count=2,
        progress=_progress(),
    )

    assert result.delivered is True
    reloaded = await _session(db)
    assert len(_response_parts(reloaded.history[-1])) == 2
    assert reloaded.fixes_used == 1  # one BATCH, one edit


async def test_zero_file_render_does_not_consume_an_edit() -> None:
    db, _fake, deck, _sources = await _provision()
    await _park_a_dangling_call(db)
    runner = _FakeOrchestrator(deck, deliver=False)  # every format failed to render

    result = await dispatch_fix(
        runner=cast(Any, runner),
        db=db,
        project_id="proj-1",
        fixes=[SlideFix(slide_id="s0", instruction="tighten")],
        call_count=1,
        progress=_progress(),
    )

    assert result.delivered is False
    assert result.reason == "render_failed"
    assert len(runner.calls) == 1  # the chain ran; it just delivered nothing
    reloaded = await _session(db)
    assert reloaded.fixes_used == 0
    assert _response_payload(reloaded.history[-1])["error"] == "render_failed"


async def test_raising_runner_does_not_consume_an_edit() -> None:
    db, _fake, _deck, _sources = await _provision()
    await _park_a_dangling_call(db)

    result = await dispatch_fix(
        runner=cast(Any, _RaisingOrchestrator()),
        db=db,
        project_id="proj-1",
        fixes=[SlideFix(slide_id="s0", instruction="tighten")],
        call_count=1,
        progress=_progress(),
    )

    assert result.delivered is False
    assert result.reason is not None and result.reason.startswith("fix_failed")
    reloaded = await _session(db)
    assert reloaded.fixes_used == 0
    assert _response_payload(reloaded.history[-1])["error"] == "fix_failed"


async def test_dispatch_refuses_before_calling_the_runner_when_exhausted() -> None:
    db, _fake, deck, _sources = await _provision(package=GenerationPackage.PRESENTATION_BASIC)
    await _park_a_dangling_call(db)
    session = await _session(db)
    session.fixes_used = 1
    await persist_session(db, session)
    runner = _FakeOrchestrator(deck)

    result = await dispatch_fix(
        runner=cast(Any, runner),
        db=db,
        project_id="proj-1",
        fixes=[SlideFix(slide_id="s0", instruction="tighten")],
        call_count=1,
        progress=_progress(),
    )

    assert result.delivered is False
    assert result.reason == "fixes_exhausted"
    assert runner.calls == []  # the expensive chain never fired
    reloaded = await _session(db)
    assert reloaded.fixes_used == 1
    assert _response_payload(reloaded.history[-1])["error"] == "fixes_exhausted"


class _PipelineExposingOrchestrator(_FakeOrchestrator):
    """A runner that ALSO offers ``run_full_pipeline`` — and tells on itself.

    The real orchestrator has both capabilities; the Protocol narrowing them to
    one is a claim about dispatch_fix, not a fact the type system enforces at
    runtime. Reading the attribute at all is recorded, so a `getattr` that never
    even gets awaited is still caught.
    """

    def __init__(self, deck: Any) -> None:
        super().__init__(deck)
        self.pipeline_touches: list[str] = []

    @property
    def run_full_pipeline(self) -> Callable[..., Awaitable[Any]]:
        self.pipeline_touches.append("attribute_read")

        async def _never(*_args: Any, **_kwargs: Any) -> Any:
            raise AssertionError("dispatch_fix re-ran the full pipeline")

        return _never


async def test_the_fix_runner_seam_cannot_rerun_the_pipeline() -> None:
    # The "a fix re-renders WITHOUT re-running the pipeline" guarantee, driven
    # rather than asserted: the runner handed to dispatch_fix DOES expose
    # run_full_pipeline, and a normal delivered fix must still reach only the
    # apply seam.
    db, _fake, deck, _sources = await _provision()
    await _park_a_dangling_call(db)
    runner = _PipelineExposingOrchestrator(deck)

    result = await dispatch_fix(
        runner=cast(Any, runner),
        db=db,
        project_id="proj-1",
        fixes=[SlideFix(slide_id="s0", instruction="tighten")],
        call_count=1,
        progress=_progress(),
    )

    assert result.delivered is True
    assert len(runner.calls) == 1  # the apply seam ran
    assert runner.pipeline_touches == []  # the pipeline was never even read
