"""Behaviour tests for the conversational deck-editing routes (packages/api/routes/chat.py).

The contract under test is the set of disciplines the web chat inherits from the
bot path: a fix NEVER charges, one operation at a time per project, the tier's
fix allowance is a hard counter, a parked decision survives its job, and the
model's own context plumbing never leaks into the rendered conversation.

The brain is a :class:`ScriptedStubDriver` injected through ``create_app``; the
session itself round-trips through the real ``DatabaseClient`` over the
in-memory Supabase fake, so persistence is exercised rather than mocked away.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import uuid4

import httpx
import pytest
from google.genai import types as genai_types

from packages.api.app import create_app
from packages.api.services.tokens import mint_app_jwt
from packages.bot.sessions import create_session, load_session, persist_session
from packages.bot.sessions.budget import session_fix_limit
from packages.bot.sessions.driver import ScriptedStubDriver, StubResponse
from packages.bot.sessions.models import BrainSession, PendingAction, TurnAction, TurnOutcome
from packages.core.brain_loop import EDIT_SLIDES_TOOL_NAME
from packages.core.enums import AudienceType, ExportFormat, GenerationPackage
from packages.core.gemini_tools import FunctionResult, build_function_responses_content
from packages.core.models.presentation import SlideFix
from packages.platform.config import PlatformConfig
from packages.platform.database import DatabaseClient
from packages.platform.jobs import DuplicateActiveJobError, GenerationJob, JobType
from packages.platform.rate_limit import RateDecision
from packages.sessions_core.chat import has_dangling_call
from tests.unit.test_brain_session import _make_sources  # pyright: ignore[reportPrivateUsage]
from tests.unit.test_database_client import (
    FakeSupabaseClient,
    _make_db,  # pyright: ignore[reportPrivateUsage]
    _make_deck,  # pyright: ignore[reportPrivateUsage]
    _seed_project,  # pyright: ignore[reportPrivateUsage]
)

pytestmark = pytest.mark.asyncio

_SECRET = "test-jwt-secret"
_USER_ID = uuid4()
_PROJECT_ID = "proj-1"
_FORMATS = [ExportFormat.HTML]
_FIX = SlideFix(slide_id="slide-01", instruction="Cut the title to five words.")


def _config() -> PlatformConfig:
    return PlatformConfig(
        supabase_url="https://example.supabase.co",
        supabase_service_key="service",
        telegram_bot_token="123:abc",
        supabase_jwt_secret=_SECRET,
    )


def _job(job_type: JobType, status: str = "processing") -> GenerationJob:
    return GenerationJob.model_validate(
        {
            "id": str(uuid4()),
            "project_id": _PROJECT_ID,
            "user_id": str(_USER_ID),
            "job_type": job_type.value,
            "status": status,
            "payload": {},
        }
    )


class _FakeQueue:
    """A job table keyed by type: a generation and an edit are distinct blockers."""

    def __init__(self) -> None:
        self.active: dict[JobType, GenerationJob] = {}
        self.enqueued: list[dict[str, Any]] = []
        self.enqueue_raises: Exception | None = None

    async def get_active_job(self, project_id: str, job_type: JobType) -> GenerationJob | None:
        return self.active.get(job_type)

    async def enqueue(self, **kwargs: Any) -> GenerationJob:
        if self.enqueue_raises is not None:
            raise self.enqueue_raises
        self.enqueued.append(kwargs)
        return _job(cast(JobType, kwargs["job_type"]), status="queued")


class _FakeCredits:
    """Records every ledger touch so a test can prove there were none."""

    def __init__(self) -> None:
        self.deductions: list[tuple[str, str, str]] = []
        self.refunds: list[tuple[str, str, int, str]] = []

    async def deduct_for_generation(self, user_id: str, project_id: str, product_type: str) -> Any:
        self.deductions.append((user_id, project_id, product_type))
        raise AssertionError("the chat path must never deduct")

    async def refund(self, user_id: str, project_id: str, amount: int, reason: str) -> None:
        self.refunds.append((user_id, project_id, amount, reason))


class _FakeLimiter:
    def __init__(self) -> None:
        self.allowed = True
        self.calls: list[dict[str, str]] = []

    async def check(self, *, action: str, user_id: str, ip: str) -> RateDecision:
        self.calls.append({"action": action, "user_id": user_id, "ip": ip})
        return RateDecision(
            allowed=self.allowed,
            scope="user",
            action=action,
            count=201,
            limit=200,
            resets_at=datetime.now(UTC) + timedelta(hours=1),
        )


@dataclass
class _Harness:
    client: httpx.AsyncClient
    db: DatabaseClient
    fake: FakeSupabaseClient
    queue: _FakeQueue
    credits: _FakeCredits
    limiter: _FakeLimiter
    driver: ScriptedStubDriver = field(default_factory=ScriptedStubDriver)


async def _harness(
    *,
    package: GenerationPackage = GenerationPackage.PRESENTATION_PREMIUM,
    script: list[StubResponse] | None = None,
    owner: str | None = None,
    with_session: bool = True,
    driver_cls: type[ScriptedStubDriver] = ScriptedStubDriver,
) -> _Harness:
    """Seed a project (optionally deck + brain session) and wire the app to it."""

    db, fake = _make_db()
    _seed_project(fake)
    # _seed_project hardcodes user_id="u1"; ownership is checked against the JWT
    # subject, so the row's owner is rewritten unless a test wants a stranger.
    fake.tables["projects"][0]["user_id"] = owner if owner is not None else str(_USER_ID)

    if with_session:
        await db.save_deck(
            _PROJECT_ID, _make_deck(title="Cooling", audience=AudienceType.UNDERGRADUATE)
        )
        await create_session(
            db,
            project_id=_PROJECT_ID,
            sources=_make_sources(with_figure=False),
            package=package,
            formats=_FORMATS,
        )

    driver = driver_cls(script=list(script or []))
    queue = _FakeQueue()
    credits = _FakeCredits()
    limiter = _FakeLimiter()
    app = create_app(
        config=_config(),
        db=db,
        identity_service=cast(Any, object()),
        credits=cast(Any, credits),
        job_queue=cast(Any, queue),
        rate_limiter=cast(Any, limiter),
        brain_driver_factory=lambda: driver,
    )
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    return _Harness(
        client=client,
        db=db,
        fake=fake,
        queue=queue,
        credits=credits,
        limiter=limiter,
        driver=driver,
    )


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {mint_app_jwt(_SECRET, _USER_ID, 3600).access_token}"}


def _fix_script() -> list[StubResponse]:
    return [
        StubResponse(
            action=TurnAction.FIX,
            reply_text="Shortening the title now.",
            fixes=(_FIX,),
            call_count=1,
        )
    ]


async def _set_fixes_used(db: DatabaseClient, count: int) -> None:
    session = await load_session(db, _PROJECT_ID)
    assert session is not None
    session.fixes_used = count
    await persist_session(db, session)


async def _park_pending(db: DatabaseClient) -> None:
    session = await load_session(db, _PROJECT_ID)
    assert session is not None
    session.pending_action = PendingAction(fixes=[_FIX], reason="Tighten the opener.", call_count=1)
    await persist_session(db, session)


# --------------------------------------------------------------------- read side


async def test_chat_without_a_session_reports_not_editable_rather_than_erroring() -> None:
    harness = await _harness(with_session=False)
    response = await harness.client.get(f"/projects/{_PROJECT_ID}/chat", headers=_headers())

    assert response.status_code == 200
    body = response.json()
    assert body["can_edit"] is False
    assert body["messages"] == []
    assert body["slide_count"] == 0


async def test_history_hides_the_injected_context_prefix_and_all_tool_plumbing() -> None:
    harness = await _harness()
    session = await load_session(harness.db, _PROJECT_ID)
    assert session is not None
    opening = (
        "DECK ROSTER (address slides by slide_id):\n"
        "slide-01 | title_hero | Opening\n\n"
        "SOURCE CLAIMS (ground every edit only in these):\n"
        "- Radiative cooling cut water use by 94 percent."
        "\n\n---\n\n"
        "Make the opening slide shorter."
    )
    session.history = [
        genai_types.Content(role="user", parts=[genai_types.Part(text=opening)]),
        genai_types.Content(
            role="model",
            parts=[
                genai_types.Part(
                    function_call=genai_types.FunctionCall(
                        name="edit_slides", args={"fixes": [_FIX.model_dump()]}
                    )
                )
            ],
        ),
        build_function_responses_content(
            [FunctionResult(name="edit_slides", response={"delivered": True})]
        ),
        genai_types.Content(role="model", parts=[genai_types.Part(text="Done — title trimmed.")]),
    ]
    await persist_session(harness.db, session)

    response = await harness.client.get(f"/projects/{_PROJECT_ID}/chat", headers=_headers())

    assert response.status_code == 200
    messages = response.json()["messages"]
    assert messages == [
        {"role": "user", "text": "Make the opening slide shorter."},
        {"role": "assistant", "text": "Done — title trimmed."},
    ]
    assert "DECK ROSTER" not in messages[0]["text"]
    assert all("edit_slides" not in message["text"] for message in messages)


async def test_history_reports_the_edit_job_currently_re_rendering_the_deck() -> None:
    harness = await _harness()
    running = _job(JobType.PRESENTATION_EDIT)
    harness.queue.active[JobType.PRESENTATION_EDIT] = running

    response = await harness.client.get(f"/projects/{_PROJECT_ID}/chat", headers=_headers())

    assert response.status_code == 200
    assert response.json()["applying_job_id"] == running.id


# --------------------------------------------------------------------- turn side


async def test_reply_turn_answers_inline_and_enqueues_nothing() -> None:
    harness = await _harness(
        script=[StubResponse(action=TurnAction.REPLY, reply_text="Slide 3 cites Iko 2024.")]
    )

    response = await harness.client.post(
        f"/projects/{_PROJECT_ID}/chat",
        json={"message": "Which source backs slide 3?"},
        headers=_headers(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["kind"] == "reply"
    assert body["reply"] == "Slide 3 cites Iko 2024."
    assert body["job_id"] is None
    assert harness.queue.enqueued == []


async def test_user_initiated_fix_becomes_a_presentation_edit_job() -> None:
    harness = await _harness(script=_fix_script())

    response = await harness.client.post(
        f"/projects/{_PROJECT_ID}/chat",
        json={"message": "Shorten the opening title."},
        headers=_headers(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["kind"] == "fix_ready"
    assert body["job_id"]
    assert len(harness.queue.enqueued) == 1
    enqueued = harness.queue.enqueued[0]
    assert enqueued["job_type"] is JobType.PRESENTATION_EDIT
    assert enqueued["project_id"] == _PROJECT_ID
    assert enqueued["payload"]["fixes"] == [
        {"slide_id": _FIX.slide_id, "instruction": _FIX.instruction}
    ]


async def test_a_fix_turn_never_touches_the_ledger() -> None:
    harness = await _harness(script=_fix_script())

    response = await harness.client.post(
        f"/projects/{_PROJECT_ID}/chat",
        json={"message": "Shorten the opening title."},
        headers=_headers(),
    )

    assert response.status_code == 200
    # Editing a deck the user already bought is not a second sale. Two independent
    # halves of that promise are asserted: the route touches no ledger method, and
    # the queued payload carries no price for the worker's refund helper to find —
    # a payload with 'deducted_amount' would make a failed edit issue a refund for
    # a charge that never happened.
    assert harness.credits.deductions == []
    assert harness.credits.refunds == []
    payload = harness.queue.enqueued[0]["payload"]
    assert "deducted_amount" not in payload
    assert "product_type" not in payload


async def test_spent_fix_allowance_refuses_before_queueing_any_work() -> None:
    harness = await _harness(package=GenerationPackage.PRESENTATION_BASIC, script=_fix_script())
    limit = session_fix_limit(GenerationPackage.PRESENTATION_BASIC)
    await _set_fixes_used(harness.db, limit)

    response = await harness.client.post(
        f"/projects/{_PROJECT_ID}/chat",
        json={"message": "One more tweak, please."},
        headers=_headers(),
    )

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["reason"] == "fixes_exhausted"
    assert detail["fix_limit"] == limit
    assert detail["fixes_used"] == limit
    assert harness.queue.enqueued == []


async def test_an_active_generation_blocks_a_turn_as_brain_busy() -> None:
    harness = await _harness(script=_fix_script())
    running = _job(JobType.PRESENTATION_GENERATION)
    harness.queue.active[JobType.PRESENTATION_GENERATION] = running

    response = await harness.client.post(
        f"/projects/{_PROJECT_ID}/chat", json={"message": "Change slide 2."}, headers=_headers()
    )

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["reason"] == "brain_busy"
    assert detail["job_id"] == running.id
    assert detail["job_type"] == "presentation_generation"
    assert harness.queue.enqueued == []


async def test_an_active_edit_blocks_a_turn_as_brain_busy() -> None:
    harness = await _harness(script=_fix_script())
    running = _job(JobType.PRESENTATION_EDIT)
    harness.queue.active[JobType.PRESENTATION_EDIT] = running

    response = await harness.client.post(
        f"/projects/{_PROJECT_ID}/chat", json={"message": "Change slide 2."}, headers=_headers()
    )

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["reason"] == "brain_busy"
    assert detail["job_type"] == "presentation_edit"
    assert harness.queue.enqueued == []


async def test_over_cap_turn_is_rejected_before_a_single_model_token() -> None:
    harness = await _harness(script=_fix_script())
    harness.limiter.allowed = False

    response = await harness.client.post(
        f"/projects/{_PROJECT_ID}/chat", json={"message": "Change slide 2."}, headers=_headers()
    )

    assert response.status_code == 429
    detail = response.json()["detail"]
    assert detail["reason"] == "rate_limited"
    assert detail["scope"] == "user" and detail["count"] == 201 and detail["limit"] == 200
    assert "resets_at" in detail
    # The scripted turn is still unconsumed: a rejected request never reached the
    # brain, so it cost nothing.
    assert len(harness.driver.script) == 1
    assert harness.queue.enqueued == []


async def test_every_chat_route_hides_a_project_the_caller_does_not_own() -> None:
    harness = await _harness(owner="u1", script=_fix_script())
    base = f"/projects/{_PROJECT_ID}"

    responses = [
        await harness.client.get(f"{base}/chat", headers=_headers()),
        await harness.client.post(
            f"{base}/chat", json={"message": "Change slide 2."}, headers=_headers()
        ),
        await harness.client.post(f"{base}/chat/approve", headers=_headers()),
        await harness.client.post(f"{base}/chat/reject", headers=_headers()),
    ]

    assert [response.status_code for response in responses] == [404, 404, 404, 404]
    assert all(response.json()["detail"] == "project_not_found" for response in responses)
    assert harness.queue.enqueued == []
    assert len(harness.driver.script) == 1


# ------------------------------------------------------------ approval gate


async def test_approve_without_a_parked_action_is_a_conflict() -> None:
    harness = await _harness()

    response = await harness.client.post(
        f"/projects/{_PROJECT_ID}/chat/approve", headers=_headers()
    )

    assert response.status_code == 409
    assert response.json()["detail"] == {"reason": "no_pending_action"}
    assert harness.queue.enqueued == []


async def test_approve_queues_from_the_session_and_leaves_the_decision_parked() -> None:
    harness = await _harness()
    await _park_pending(harness.db)

    response = await harness.client.post(
        f"/projects/{_PROJECT_ID}/chat/approve", headers=_headers()
    )

    assert response.status_code == 200
    assert response.json()["kind"] == "fix_ready"
    assert response.json()["job_id"]
    enqueued = harness.queue.enqueued[0]
    assert enqueued["job_type"] is JobType.PRESENTATION_EDIT
    # The batch is NOT copied into the payload: a job that dies must leave the
    # decision on the session row, still re-presentable, rather than dropped.
    assert enqueued["payload"] == {"from_pending": True, "call_count": 1}
    follow_up = await harness.client.get(f"/projects/{_PROJECT_ID}/chat", headers=_headers())
    assert follow_up.json()["pending_action"] is not None


async def test_reject_discards_the_parked_action() -> None:
    harness = await _harness()
    await _park_pending(harness.db)

    response = await harness.client.post(f"/projects/{_PROJECT_ID}/chat/reject", headers=_headers())

    assert response.status_code == 200
    assert response.json()["kind"] == "reply"
    follow_up = await harness.client.get(f"/projects/{_PROJECT_ID}/chat", headers=_headers())
    assert follow_up.status_code == 200
    assert follow_up.json()["pending_action"] is None
    assert harness.queue.enqueued == []


async def test_reject_without_a_parked_action_is_a_conflict() -> None:
    harness = await _harness()

    response = await harness.client.post(f"/projects/{_PROJECT_ID}/chat/reject", headers=_headers())

    assert response.status_code == 409
    assert response.json()["detail"] == {"reason": "no_pending_action"}


# ------------------------------------------------- enqueue failure / un-parking


class _ParkingStubDriver(ScriptedStubDriver):
    """A fix turn as the REAL driver leaves it: history ending on the model's
    unanswered ``edit_slides`` call.

    ``ScriptedStubDriver`` emits text-only history, so a park driven by it would
    leave nothing dangling and every "the session was un-parked" assertion would
    hold vacuously — including against a route that repairs nothing.
    """

    async def run_turn(self, session: BrainSession, user_text: str) -> TurnOutcome:
        outcome = await super().run_turn(session, user_text)
        if not outcome.fixes:
            return outcome
        call_parts = [
            genai_types.Part(
                function_call=genai_types.FunctionCall(
                    name=EDIT_SLIDES_TOOL_NAME,
                    args={"fixes": [fix.model_dump() for fix in outcome.fixes]},
                )
            )
            for _ in range(max(1, outcome.fix_call_count))
        ]
        return replace(
            outcome,
            history=[*outcome.history, genai_types.Content(role="model", parts=call_parts)],
        )


async def _dangling_parts(db: DatabaseClient) -> int:
    session = await load_session(db, _PROJECT_ID)
    assert session is not None
    return has_dangling_call(session)


async def _parking_harness(script: list[StubResponse] | None = None) -> _Harness:
    return await _harness(script=script or _fix_script(), driver_cls=_ParkingStubDriver)


def _fix_then_reply_script() -> list[StubResponse]:
    return [*_fix_script(), StubResponse(action=TurnAction.REPLY, reply_text="Still here.")]


async def test_the_parking_driver_really_leaves_an_unanswered_call() -> None:
    """Guards every un-parking assertion below: with nothing dangling to answer
    they would hold against a route that never repairs anything."""

    harness = await _parking_harness()

    response = await harness.client.post(
        f"/projects/{_PROJECT_ID}/chat",
        json={"message": "Shorten the opening title."},
        headers=_headers(),
    )

    assert response.status_code == 200
    assert response.json()["kind"] == "fix_ready"
    assert await _dangling_parts(harness.db) == 1


async def test_duplicate_edit_job_un_parks_the_session_instead_of_wedging_it() -> None:
    harness = await _parking_harness(script=_fix_then_reply_script())
    harness.queue.enqueue_raises = DuplicateActiveJobError(_job(JobType.PRESENTATION_EDIT))

    response = await harness.client.post(
        f"/projects/{_PROJECT_ID}/chat",
        json={"message": "Shorten the opening title."},
        headers=_headers(),
    )

    assert response.status_code == 409
    assert response.json()["detail"] == {"reason": "brain_busy"}
    # The anti-wedge guarantee: the model's edit_slides call has been answered, so
    # the next turn does not resend a dangling function_call to Gemini.
    assert await _dangling_parts(harness.db) == 0

    harness.queue.enqueue_raises = None
    follow_up = await harness.client.post(
        f"/projects/{_PROJECT_ID}/chat", json={"message": "Never mind."}, headers=_headers()
    )
    assert follow_up.status_code == 200
    assert follow_up.json()["reply"] == "Still here."


async def test_an_unqueueable_edit_un_parks_and_reports_edit_not_queued() -> None:
    harness = await _parking_harness(script=_fix_then_reply_script())
    harness.queue.enqueue_raises = RuntimeError("the queue backend is gone")

    response = await harness.client.post(
        f"/projects/{_PROJECT_ID}/chat",
        json={"message": "Shorten the opening title."},
        headers=_headers(),
    )

    assert response.status_code == 503
    assert response.json()["detail"] == {"reason": "edit_not_queued"}
    assert await _dangling_parts(harness.db) == 0

    harness.queue.enqueue_raises = None
    follow_up = await harness.client.post(
        f"/projects/{_PROJECT_ID}/chat", json={"message": "Never mind."}, headers=_headers()
    )
    assert follow_up.status_code == 200
    assert follow_up.json()["reply"] == "Still here."


async def test_approve_keeps_the_decision_parked_when_the_edit_job_is_a_duplicate() -> None:
    harness = await _harness()
    await _park_pending(harness.db)
    harness.queue.enqueue_raises = DuplicateActiveJobError(_job(JobType.PRESENTATION_EDIT))

    response = await harness.client.post(
        f"/projects/{_PROJECT_ID}/chat/approve", headers=_headers()
    )

    assert response.status_code == 409
    assert response.json()["detail"] == {"reason": "brain_busy"}
    # Deliberately the OPPOSITE of the turn route's un-parking above. The turn
    # route's batch lives only in the job payload, so a lost job must release the
    # session; the approve route's batch stays on the session row, so leaving it
    # parked is what keeps the decision re-presentable.
    follow_up = await harness.client.get(f"/projects/{_PROJECT_ID}/chat", headers=_headers())
    assert follow_up.json()["pending_action"]["fixes"] == [
        {"slide_id": _FIX.slide_id, "instruction": _FIX.instruction}
    ]


async def test_approve_keeps_the_decision_parked_when_the_queue_is_unavailable() -> None:
    harness = await _harness()
    await _park_pending(harness.db)
    harness.queue.enqueue_raises = RuntimeError("the queue backend is gone")

    response = await harness.client.post(
        f"/projects/{_PROJECT_ID}/chat/approve", headers=_headers()
    )

    assert response.status_code == 503
    assert response.json()["detail"] == {"reason": "edit_not_queued"}
    follow_up = await harness.client.get(f"/projects/{_PROJECT_ID}/chat", headers=_headers())
    assert follow_up.json()["pending_action"] is not None


# ------------------------------------------------------- turn-side edge branches


async def test_a_turn_against_a_project_with_no_session_is_session_not_ready() -> None:
    harness = await _harness(with_session=False, script=_fix_script())

    response = await harness.client.post(
        f"/projects/{_PROJECT_ID}/chat", json={"message": "Shorten the title."}, headers=_headers()
    )

    assert response.status_code == 409
    assert response.json()["detail"] == {"reason": "session_not_ready"}
    assert harness.queue.enqueued == []
    assert len(harness.driver.script) == 1


async def test_a_turn_behind_a_parked_decision_re_presents_it_rather_than_erroring() -> None:
    harness = await _harness(script=_fix_script())
    await _park_pending(harness.db)

    response = await harness.client.post(
        f"/projects/{_PROJECT_ID}/chat",
        json={"message": "Actually, also fix slide 4."},
        headers=_headers(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["kind"] == "approval_required"
    assert body["job_id"] is None
    assert body["pending_action"] == {
        "reason": "Tighten the opener.",
        "fixes": [{"slide_id": _FIX.slide_id, "instruction": _FIX.instruction}],
    }
    # The gate sits upstream of the model: the parked call is unanswered, so no
    # turn may run until the user approves or rejects.
    assert len(harness.driver.script) == 1
    assert harness.queue.enqueued == []


async def test_an_empty_message_is_rejected_before_the_brain() -> None:
    harness = await _harness(script=_fix_script())

    response = await harness.client.post(
        f"/projects/{_PROJECT_ID}/chat", json={"message": ""}, headers=_headers()
    )

    assert response.status_code == 422
    assert len(harness.driver.script) == 1
    assert harness.queue.enqueued == []


async def test_an_oversized_message_is_rejected_before_the_brain() -> None:
    harness = await _harness(script=_fix_script())

    response = await harness.client.post(
        f"/projects/{_PROJECT_ID}/chat",
        json={"message": "x" * 4001},
        headers=_headers(),
    )

    assert response.status_code == 422
    assert len(harness.driver.script) == 1
    assert harness.queue.enqueued == []


# ------------------------------------------------------------- rate limit scope


async def test_over_cap_approve_is_rejected_before_the_job_is_queued() -> None:
    harness = await _harness()
    await _park_pending(harness.db)
    harness.limiter.allowed = False

    response = await harness.client.post(
        f"/projects/{_PROJECT_ID}/chat/approve", headers=_headers()
    )

    assert response.status_code == 429
    assert response.json()["detail"]["reason"] == "rate_limited"
    assert harness.queue.enqueued == []


async def test_reject_stays_available_to_a_user_who_has_hit_the_cap() -> None:
    harness = await _harness()
    await _park_pending(harness.db)
    harness.limiter.allowed = False

    response = await harness.client.post(f"/projects/{_PROJECT_ID}/chat/reject", headers=_headers())

    assert response.status_code == 200
    # Intentional asymmetry with its two siblings: rejecting spends no model tokens
    # and queues no work, so it must never be rate limited — otherwise a user at the
    # cap cannot clear the decision blocking their own conversation. The limiter is
    # not merely permissive here, it is never consulted.
    assert harness.limiter.calls == []
    follow_up = await harness.client.get(f"/projects/{_PROJECT_ID}/chat", headers=_headers())
    assert follow_up.json()["pending_action"] is None


# ----------------------------------------------------------- allowance is a fact


async def test_the_history_projects_the_allowance_from_the_tier_not_a_constant() -> None:
    harness = await _harness(package=GenerationPackage.PRESENTATION_STANDARD)
    limit = session_fix_limit(GenerationPackage.PRESENTATION_STANDARD)
    await _set_fixes_used(harness.db, limit - 1)

    response = await harness.client.get(f"/projects/{_PROJECT_ID}/chat", headers=_headers())

    assert response.status_code == 200
    body = response.json()
    assert body["fix_limit"] == limit
    assert body["fixes_used"] == limit - 1
    assert body["fixes_remaining"] == 1
