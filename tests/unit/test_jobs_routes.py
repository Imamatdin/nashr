"""Behaviour tests for the P2 enqueue/poll routes (packages/api/routes/jobs.py).

The route's gate ORDER is the contract under test: rate limit → ownership →
idempotency → entitlement → insert. Fakes record every call so tests can
assert what was (and crucially was NOT) reached — e.g. an over-cap request
must never touch the ledger, and a lost enqueue race must refund.

The same fakes cover the workspace's state-discovery read (``GET /jobs``):
which job type it asks for, the timestamps and authoritative charge the view
carries, and the refund fact — resolved from the job-stamped ledger row, and
only ever probed for a job that actually failed.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar, cast
from uuid import UUID, uuid4

import httpx
import pytest
from postgrest.exceptions import APIError

from packages.api.app import create_app
from packages.api.services.tokens import mint_app_jwt
from packages.platform.config import PlatformConfig
from packages.platform.jobs import (
    DuplicateActiveJobError,
    GenerationJob,
    JobType,
)
from packages.platform.rate_limit import RateDecision

pytestmark = pytest.mark.asyncio

_SECRET = "test-jwt-secret"
_USER_ID = uuid4()
_PROJECT_ID = str(uuid4())


def _config() -> PlatformConfig:
    return PlatformConfig(
        supabase_url="https://example.supabase.co",
        supabase_service_key="service",
        telegram_bot_token="123:abc",
        supabase_jwt_secret=_SECRET,
    )


def _job(status: str = "queued", user_id: UUID | None = None) -> GenerationJob:
    return GenerationJob.model_validate(
        {
            "id": str(uuid4()),
            "project_id": _PROJECT_ID,
            "user_id": str(user_id or _USER_ID),
            "job_type": "presentation_generation",
            "status": status,
            "payload": {},
            "progress": {"step": "Rendering", "current": 7, "total": 7},
        }
    )


_SOURCE_ID = str(uuid4())


class _FakeDb:
    def __init__(self) -> None:
        self.project_owner: str = str(_USER_ID)
        self.project_exists = True
        # None = the row carries no package_tier key at all, which is both the
        # pre-migration-010 shape and a legacy row's shape after it.
        self.project_tier: str | None = None
        self.stamps: list[tuple[str, str]] = []
        self.stamp_raises: Exception | None = None
        self.sources: list[dict[str, Any]] = [
            {
                "id": _SOURCE_ID,
                "project_id": _PROJECT_ID,
                "filename": "a.pdf",
                "storage_key": f"sources/{_PROJECT_ID}/a.pdf",
            }
        ]

    async def get_project(self, project_id: str) -> dict[str, Any] | None:
        if not self.project_exists:
            return None
        row: dict[str, Any] = {"id": project_id, "user_id": self.project_owner}
        if self.project_tier is not None:
            row["package_tier"] = self.project_tier
        return row

    async def set_project_package_tier(self, project_id: str, package_tier: str) -> None:
        if self.stamp_raises is not None:
            raise self.stamp_raises
        self.stamps.append((project_id, package_tier))

    async def get_project_sources(self, project_id: str) -> list[dict[str, Any]]:
        return self.sources


class _FakeCredits:
    PRICING: ClassVar[dict[str, int]] = {
        "presentation_basic": 5_000,
        "presentation_standard": 10_000,
        "presentation_premium": 15_000,
    }

    def __init__(self) -> None:
        self.sufficient = True
        self.deductions: list[tuple[str, str, str]] = []
        self.refunds: list[tuple[str, str, int, str]] = []
        # Parallel to `refunds`: the job id each refund was stamped with. A
        # separate list so the tuple shape above stays what it always was.
        self.refund_job_ids: list[str | None] = []
        self.refund_exists = False
        self.refund_probes: list[tuple[str, str]] = []

    async def has_sufficient_credits(self, user_id: str, product_type: str) -> bool:
        return self.sufficient

    async def get_balance(self, user_id: str) -> int:
        return 3_000

    async def deduct_for_generation(self, user_id: str, project_id: str, product_type: str) -> Any:
        self.deductions.append((user_id, project_id, product_type))
        from types import SimpleNamespace

        return SimpleNamespace(amount=-self.PRICING[product_type])

    async def refund(
        self,
        user_id: str,
        project_id: str,
        amount: int,
        reason: str,
        *,
        generation_job_id: str | None = None,
    ) -> None:
        self.refunds.append((user_id, project_id, amount, reason))
        self.refund_job_ids.append(generation_job_id)

    async def has_refund_for_job(self, user_id: str, generation_job_id: str) -> bool:
        self.refund_probes.append((user_id, generation_job_id))
        return self.refund_exists


class _FakeQueue:
    def __init__(self) -> None:
        self.active: GenerationJob | None = None
        self.jobs: dict[str, GenerationJob] = {}
        self.enqueue_raises: DuplicateActiveJobError | None = None
        self.enqueued: list[dict[str, Any]] = []
        self.latest: GenerationJob | None = None
        self.latest_calls: list[tuple[str, str]] = []

    async def get_active_job(self, project_id: str, job_type: JobType) -> GenerationJob | None:
        return self.active

    async def get_latest_job(self, project_id: str, job_type: JobType) -> GenerationJob | None:
        self.latest_calls.append((project_id, job_type.value))
        return self.latest

    async def get_job(self, job_id: str) -> GenerationJob | None:
        return self.jobs.get(job_id)

    async def enqueue(self, **kwargs: Any) -> GenerationJob:
        if self.enqueue_raises is not None:
            raise self.enqueue_raises
        self.enqueued.append(kwargs)
        job = _job()
        self.jobs[job.id] = job
        return job


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
            count=11,
            limit=10,
            resets_at=datetime.now(UTC) + timedelta(hours=1),
        )


def _client() -> tuple[httpx.AsyncClient, _FakeDb, _FakeCredits, _FakeQueue, _FakeLimiter]:
    db = _FakeDb()
    credits = _FakeCredits()
    queue = _FakeQueue()
    limiter = _FakeLimiter()
    app = create_app(
        config=_config(),
        db=cast(Any, db),
        identity_service=cast(Any, object()),
        credits=cast(Any, credits),
        job_queue=cast(Any, queue),
        rate_limiter=cast(Any, limiter),
    )
    transport = httpx.ASGITransport(app=app)
    client = httpx.AsyncClient(transport=transport, base_url="http://test")
    return client, db, credits, queue, limiter


def _headers() -> dict[str, str]:
    session = mint_app_jwt(_SECRET, _USER_ID, 3600)
    return {"Authorization": f"Bearer {session.access_token}"}


def _body(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "project_id": _PROJECT_ID,
        "package": "presentation_standard",
        "sources": [{"storage_key": f"sources/{_PROJECT_ID}/a.pdf", "filename": "a.pdf"}],
        "language": "uz",
    }
    body.update(overrides)
    # An override of None means "the web client omitted this key entirely",
    # which is the shape the workspace re-enqueue now posts.
    return {key: value for key, value in body.items() if value is not None}


async def test_enqueue_requires_auth() -> None:
    client, *_ = _client()
    response = await client.post("/jobs", json=_body())
    assert response.status_code == 401


async def test_over_cap_rejected_visibly_before_any_spend() -> None:
    client, _db, credits, queue, limiter = _client()
    limiter.allowed = False
    response = await client.post("/jobs", json=_body(), headers=_headers())
    assert response.status_code == 429
    detail = response.json()["detail"]
    assert detail["reason"] == "rate_limited"
    assert detail["scope"] == "user" and detail["count"] == 11 and detail["limit"] == 10
    assert "resets_at" in detail
    # Zero spend of any kind: no deduction, no enqueue.
    assert credits.deductions == [] and queue.enqueued == []


async def test_non_owner_project_is_404_before_entitlement() -> None:
    client, db, credits, _queue, _limiter = _client()
    db.project_owner = str(uuid4())
    response = await client.post("/jobs", json=_body(), headers=_headers())
    assert response.status_code == 404
    assert credits.deductions == []


async def test_active_job_returned_idempotently_without_deduction() -> None:
    client, _db, credits, queue, _limiter = _client()
    queue.active = _job(status="processing")
    response = await client.post("/jobs", json=_body(), headers=_headers())
    assert response.status_code == 200
    assert response.json()["existing"] is True
    assert credits.deductions == []


async def test_insufficient_balance_is_402_pre_spend() -> None:
    client, _db, credits, queue, _limiter = _client()
    credits.sufficient = False
    response = await client.post("/jobs", json=_body(), headers=_headers())
    assert response.status_code == 402
    detail = response.json()["detail"]
    assert detail == {"reason": "insufficient_balance", "balance": 3_000, "required": 10_000}
    assert credits.deductions == [] and queue.enqueued == []


async def test_happy_path_deducts_then_enqueues_with_payload() -> None:
    client, _db, credits, queue, _limiter = _client()
    response = await client.post("/jobs", json=_body(), headers=_headers())
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "queued" and body["existing"] is False
    assert credits.deductions == [(str(_USER_ID), _PROJECT_ID, "presentation_standard")]
    payload = queue.enqueued[0]["payload"]
    assert payload["product_type"] == "presentation_standard"
    # Sources are resolved against the registered rows: the persisted source
    # id rides along for provenance stamping.
    assert payload["sources"][0]["filename"] == "a.pdf"
    assert payload["sources"][0]["source_id"] == _SOURCE_ID
    # P2 gate defect 3: web delivery defaults to ALL THREE primary formats.
    assert payload["formats"] == ["html", "pptx_editable", "pdf"]
    # F3: the exact deducted amount rides the payload so the refund matches
    # the charge even if PRICING changes later.
    assert payload["deducted_amount"] == 10_000


async def test_spoofed_xff_cannot_dodge_the_ip_cap() -> None:
    # F2: Caddy APPENDS the peer address, so only the LAST entry is
    # trustworthy; client-stuffed leading entries must be ignored.
    client, _db, _credits, _queue, limiter = _client()
    response = await client.post(
        "/jobs",
        json=_body(),
        headers={**_headers(), "X-Forwarded-For": "6.6.6.6, 203.0.113.9"},
    )
    assert response.status_code == 200
    assert limiter.calls[0]["ip"] == "203.0.113.9"


async def test_lost_enqueue_race_refunds_and_returns_winner() -> None:
    client, _db, credits, queue, _limiter = _client()
    winner = _job(status="queued")
    queue.enqueue_raises = DuplicateActiveJobError(winner)
    response = await client.post("/jobs", json=_body(), headers=_headers())
    assert response.status_code == 200
    assert response.json()["id"] == winner.id and response.json()["existing"] is True
    assert len(credits.refunds) == 1
    _user_id, _project_id, amount, reason = credits.refunds[0]
    assert amount == 10_000 and "duplicate_enqueue" in reason


async def test_unregistered_source_rejected_pre_spend() -> None:
    client, db, credits, queue, _limiter = _client()
    db.sources = []
    response = await client.post("/jobs", json=_body(), headers=_headers())
    assert response.status_code == 422
    assert response.json()["detail"]["reason"] == "unregistered_source"
    assert credits.deductions == [] and queue.enqueued == []


async def test_explicit_formats_pass_through_unchanged() -> None:
    client, _db, _credits, queue, _limiter = _client()
    response = await client.post("/jobs", json=_body(formats=["html"]), headers=_headers())
    assert response.status_code == 200
    assert queue.enqueued[0]["payload"]["formats"] == ["html"]


# ------------------------------------------------------- tier persistence (f)
#
# The frozen finding: re-enqueueing from the workspace always charged
# presentation_standard because the tier chosen on /new was never persisted.
# The tier now rides the project row and drives every later enqueue.


async def test_explicit_package_is_charged_and_stamped_after_enqueue() -> None:
    client, db, credits, queue, _limiter = _client()
    response = await client.post(
        "/jobs", json=_body(package="presentation_premium"), headers=_headers()
    )
    assert response.status_code == 200
    assert credits.deductions == [(str(_USER_ID), _PROJECT_ID, "presentation_premium")]
    payload = queue.enqueued[0]["payload"]
    assert payload["package"] == "presentation_premium"
    assert payload["product_type"] == "presentation_premium"
    # Stamped only AFTER the queue insert succeeded.
    assert db.stamps == [(_PROJECT_ID, "presentation_premium")]


async def test_omitted_package_uses_the_projects_persisted_tier() -> None:
    client, db, credits, queue, _limiter = _client()
    db.project_tier = "presentation_premium"
    response = await client.post("/jobs", json=_body(package=None), headers=_headers())
    assert response.status_code == 200
    assert credits.deductions == [(str(_USER_ID), _PROJECT_ID, "presentation_premium")]
    assert queue.enqueued[0]["payload"]["product_type"] == "presentation_premium"
    assert queue.enqueued[0]["payload"]["deducted_amount"] == 15_000
    # The resolved tier is NOT re-stamped: only an explicit choice writes it.
    assert db.stamps == []


async def test_omitted_package_short_balance_quotes_the_persisted_tier_price() -> None:
    client, db, credits, queue, _limiter = _client()
    db.project_tier = "presentation_premium"
    credits.sufficient = False
    response = await client.post("/jobs", json=_body(package=None), headers=_headers())
    assert response.status_code == 402
    assert response.json()["detail"] == {
        "reason": "insufficient_balance",
        "balance": 3_000,
        "required": 15_000,
    }
    assert credits.deductions == [] and queue.enqueued == []


async def test_omitted_package_on_legacy_row_falls_back_to_standard() -> None:
    client, db, credits, queue, _limiter = _client()
    assert db.project_tier is None  # row has no package_tier key at all
    response = await client.post("/jobs", json=_body(package=None), headers=_headers())
    assert response.status_code == 200
    assert credits.deductions == [(str(_USER_ID), _PROJECT_ID, "presentation_standard")]
    assert queue.enqueued[0]["payload"]["product_type"] == "presentation_standard"
    assert db.stamps == []


async def test_unenqueueable_persisted_tier_falls_back_rather_than_crashing() -> None:
    client, db, _credits, queue, _limiter = _client()
    db.project_tier = "article_short"  # impossible post-010, possible pre-010
    response = await client.post("/jobs", json=_body(package=None), headers=_headers())
    assert response.status_code == 200
    assert queue.enqueued[0]["payload"]["product_type"] == "presentation_standard"


async def test_explicit_unenqueueable_package_is_still_422() -> None:
    client, _db, credits, queue, _limiter = _client()
    response = await client.post("/jobs", json=_body(package="article_short"), headers=_headers())
    assert response.status_code == 422
    assert credits.deductions == [] and queue.enqueued == []


async def test_failed_stamp_does_not_fail_an_already_charged_enqueue() -> None:
    # The prod window where migration 010 is deployed in code but not applied:
    # the column is missing, the stamp errors, the user keeps their job.
    client, db, credits, queue, _limiter = _client()
    db.stamp_raises = APIError(
        {"message": 'column "package_tier" of relation "projects" does not exist', "code": "42703"}
    )
    response = await client.post(
        "/jobs", json=_body(package="presentation_premium"), headers=_headers()
    )
    assert response.status_code == 200
    assert response.json()["existing"] is False
    assert len(queue.enqueued) == 1
    # Charged once, refunded never: the stamp is provenance, not the payment.
    assert credits.deductions == [(str(_USER_ID), _PROJECT_ID, "presentation_premium")]
    assert credits.refunds == []


async def test_poll_returns_progress_to_owner_only() -> None:
    client, _db, _credits, queue, _limiter = _client()
    mine = _job(status="processing")
    theirs = _job(status="processing", user_id=uuid4())
    queue.jobs = {mine.id: mine, theirs.id: theirs}
    ok = await client.get(f"/jobs/{mine.id}", headers=_headers())
    assert ok.status_code == 200
    assert ok.json()["progress"]["step"] == "Rendering"
    denied = await client.get(f"/jobs/{theirs.id}", headers=_headers())
    assert denied.status_code == 404


# ------------------------------------------------- workspace state discovery
#
# GET /jobs?project_id= is how a returning user's workspace learns what the
# project's run is doing without holding the ?job= URL.

_CREATED_AT = datetime(2026, 8, 23, 9, 0, tzinfo=UTC)
_STARTED_AT = datetime(2026, 8, 23, 9, 0, 12, tzinfo=UTC)
_HEARTBEAT_AT = datetime(2026, 8, 23, 9, 3, 30, tzinfo=UTC)
_COMPLETED_AT = datetime(2026, 8, 23, 9, 4, tzinfo=UTC)


def _stamped_job(
    *,
    status: str = "completed",
    payload: dict[str, Any] | None = None,
    user_id: UUID | None = None,
) -> GenerationJob:
    """A row carrying every timestamp and a real enqueue payload."""

    return GenerationJob.model_validate(
        {
            "id": str(uuid4()),
            "project_id": _PROJECT_ID,
            "user_id": str(user_id or _USER_ID),
            "job_type": "presentation_generation",
            "status": status,
            "payload": payload if payload is not None else {},
            "progress": {"step": "Yakunlandi", "current": 7, "total": 7},
            "created_at": _CREATED_AT.isoformat(),
            "started_at": _STARTED_AT.isoformat(),
            "heartbeat_at": _HEARTBEAT_AT.isoformat(),
            "completed_at": _COMPLETED_AT.isoformat(),
        }
    )


def _at(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


async def test_latest_project_job_is_returned_in_job_view_shape() -> None:
    client, _db, _credits, queue, _limiter = _client()
    queue.latest = _stamped_job(status="processing")
    response = await client.get(f"/jobs?project_id={_PROJECT_ID}", headers=_headers())
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == queue.latest.id
    assert body["project_id"] == _PROJECT_ID
    assert body["job_type"] == "presentation_generation"
    assert body["status"] == "processing"
    assert body["progress"]["step"] == "Yakunlandi"
    assert body["existing"] is False


async def test_latest_project_job_for_non_owner_is_404() -> None:
    client, db, _credits, queue, _limiter = _client()
    db.project_owner = str(uuid4())
    queue.latest = _stamped_job()
    response = await client.get(f"/jobs?project_id={_PROJECT_ID}", headers=_headers())
    assert response.status_code == 404
    assert response.json()["detail"] == "project_not_found"
    # The queue is never even asked: ownership gates the lookup.
    assert queue.latest_calls == []


async def test_latest_project_job_absent_is_404_job_not_found() -> None:
    client, _db, _credits, queue, _limiter = _client()
    queue.latest = None
    response = await client.get(f"/jobs?project_id={_PROJECT_ID}", headers=_headers())
    assert response.status_code == 404
    assert response.json()["detail"] == "job_not_found"


async def test_latest_project_job_defaults_to_the_generation_job_type() -> None:
    # An edit job carries no charge and does not change deck readiness, so it
    # must not displace the workspace's view of the deck's own run.
    client, _db, _credits, queue, _limiter = _client()
    queue.latest = _stamped_job()
    response = await client.get(f"/jobs?project_id={_PROJECT_ID}", headers=_headers())
    assert response.status_code == 200
    assert queue.latest_calls == [(_PROJECT_ID, "presentation_generation")]


async def test_latest_project_job_honours_an_explicit_job_type() -> None:
    client, _db, _credits, queue, _limiter = _client()
    queue.latest = _stamped_job()
    response = await client.get(
        f"/jobs?project_id={_PROJECT_ID}&job_type=presentation_edit", headers=_headers()
    )
    assert response.status_code == 200
    assert queue.latest_calls == [(_PROJECT_ID, "presentation_edit")]


async def test_job_view_carries_timestamps_and_the_authoritative_charge() -> None:
    client, db, _credits, queue, _limiter = _client()
    # The project row disagrees with what was actually charged; the payload is
    # the record of the transaction and wins.
    db.project_tier = "presentation_basic"
    queue.latest = _stamped_job(
        payload={"package": "presentation_premium", "deducted_amount": 15_000}
    )
    response = await client.get(f"/jobs?project_id={_PROJECT_ID}", headers=_headers())
    assert response.status_code == 200
    body = response.json()
    assert _at(body["created_at"]) == _CREATED_AT
    assert _at(body["started_at"]) == _STARTED_AT
    assert _at(body["heartbeat_at"]) == _HEARTBEAT_AT
    assert _at(body["completed_at"]) == _COMPLETED_AT
    assert body["package"] == "presentation_premium"
    assert body["deducted_amount"] == 15_000


async def test_job_view_omits_package_and_amount_for_a_bot_era_payload() -> None:
    client, _db, _credits, queue, _limiter = _client()
    queue.latest = _stamped_job(payload={})
    response = await client.get(f"/jobs?project_id={_PROJECT_ID}", headers=_headers())
    body = response.json()
    assert body["package"] is None and body["deducted_amount"] is None


# -------------------------------------------------------------- refund fact


async def test_failed_job_with_a_stamped_ledger_refund_reports_refunded() -> None:
    client, _db, credits, queue, _limiter = _client()
    credits.refund_exists = True
    queue.latest = _stamped_job(status="failed")
    response = await client.get(f"/jobs?project_id={_PROJECT_ID}", headers=_headers())
    assert response.status_code == 200
    assert response.json()["refunded"] is True
    assert credits.refund_probes == [(str(_USER_ID), queue.latest.id)]


async def test_failed_job_without_a_stamped_refund_reports_not_refunded() -> None:
    client, _db, credits, queue, _limiter = _client()
    credits.refund_exists = False
    queue.latest = _stamped_job(status="failed")
    response = await client.get(f"/jobs?project_id={_PROJECT_ID}", headers=_headers())
    assert response.json()["refunded"] is False
    assert len(credits.refund_probes) == 1


@pytest.mark.parametrize("job_status", ["queued", "processing", "completed"])
async def test_ledger_is_never_probed_for_a_non_failed_job(job_status: str) -> None:
    # The web polls this shape every few seconds; only a failure can have been
    # refunded, so a live poll must not cost a ledger query per tick.
    client, _db, credits, queue, _limiter = _client()
    credits.refund_exists = True
    queue.latest = _stamped_job(status=job_status)
    response = await client.get(f"/jobs?project_id={_PROJECT_ID}", headers=_headers())
    assert response.status_code == 200
    assert response.json()["refunded"] is False
    assert credits.refund_probes == []


async def test_single_job_poll_also_resolves_the_refund_fact() -> None:
    client, _db, credits, queue, _limiter = _client()
    credits.refund_exists = True
    failed = _stamped_job(status="failed")
    queue.jobs = {failed.id: failed}
    response = await client.get(f"/jobs/{failed.id}", headers=_headers())
    assert response.status_code == 200
    assert response.json()["refunded"] is True


# -------------------------------------------------------------------- topic


async def test_topic_rides_into_the_payload_verbatim() -> None:
    client, _db, _credits, queue, _limiter = _client()
    topic = "Suv tejash texnologiyalari: Sietl tajribasi"
    response = await client.post("/jobs", json=_body(topic=topic), headers=_headers())
    assert response.status_code == 200
    assert queue.enqueued[0]["payload"]["topic"] == topic


async def test_omitted_topic_lands_as_none() -> None:
    client, _db, _credits, queue, _limiter = _client()
    response = await client.post("/jobs", json=_body(topic=None), headers=_headers())
    assert response.status_code == 200
    assert queue.enqueued[0]["payload"]["topic"] is None


async def test_blank_topic_lands_as_none_not_an_empty_string() -> None:
    client, _db, _credits, queue, _limiter = _client()
    response = await client.post("/jobs", json=_body(topic="   "), headers=_headers())
    assert response.status_code == 200
    assert queue.enqueued[0]["payload"]["topic"] is None


async def test_lost_race_refund_is_not_stamped_with_the_winning_job_id() -> None:
    # The refund undoes the LOSING deduction, but the winner's own charge
    # stands. Stamping the winner's id would make has_refund_for_job answer
    # True for a live job, i.e. a running deck reporting itself refunded.
    client, _db, credits, queue, _limiter = _client()
    winner = _job(status="queued")
    queue.enqueue_raises = DuplicateActiveJobError(winner)
    response = await client.post("/jobs", json=_body(), headers=_headers())
    assert response.status_code == 200
    assert response.json()["id"] == winner.id
    assert credits.refund_job_ids == [None]
