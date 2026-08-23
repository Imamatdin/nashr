"""Behaviour tests for the P3 project routes: create, deck access, share,
provenance, the source-derived pre-generation interview, and the
unauthenticated public share resolution."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

import httpx
import pytest

from packages.api.app import create_app
from packages.api.services.tokens import mint_app_jwt
from packages.platform.config import PlatformConfig
from packages.platform.rate_limit import RateDecision

pytestmark = pytest.mark.asyncio

_SECRET = "test-jwt-secret"
_USER_ID = uuid4()
_PROJECT_ID = str(uuid4())
_SOURCE_ID = str(uuid4())


def _config() -> PlatformConfig:
    return PlatformConfig(
        supabase_url="https://example.supabase.co",
        supabase_service_key="service",
        telegram_bot_token="123:abc",
        supabase_jwt_secret=_SECRET,
    )


class _FakeDb:
    def __init__(self) -> None:
        self.project_owner: str = str(_USER_ID)
        self.share_token: str | None = None
        self.files: list[dict[str, Any]] = []
        self.sources_json: dict[str, Any] | None = None
        self.project_sources: list[dict[str, Any]] = [{"id": _SOURCE_ID, "filename": "manba.pdf"}]
        self.share_writes: list[tuple[str, str | None]] = []
        self.created_projects: list[dict[str, Any]] = []

    async def get_project(self, project_id: str) -> dict[str, Any] | None:
        return {
            "id": project_id,
            "user_id": self.project_owner,
            "title": "Test loyiha",
            "share_token": self.share_token,
        }

    async def create_project(self, **kwargs: Any) -> dict[str, Any]:
        row = {
            "id": str(uuid4()),
            "title": kwargs["title"],
            "type": kwargs["project_type"],
            "status": "draft",
        }
        self.created_projects.append({**kwargs, **row})
        return row

    async def get_project_files(self, project_id: str) -> list[dict[str, Any]]:
        return self.files

    async def get_project_sources(self, project_id: str) -> list[dict[str, Any]]:
        return self.project_sources

    async def set_project_share_token(self, project_id: str, token: str | None) -> None:
        self.share_writes.append((project_id, token))
        self.share_token = token

    async def get_project_by_share_token(self, token: str) -> dict[str, Any] | None:
        if self.share_token is not None and token == self.share_token:
            return {"id": _PROJECT_ID, "title": "Test loyiha"}
        return None

    async def get_brain_session_sources(self, project_id: str) -> dict[str, Any] | None:
        return self.sources_json


class _FakeStorage:
    async def signed_url(self, key: str, expires_in: int = 3600) -> str:
        return f"https://r2.example/{key}?sig=get&ttl={expires_in}"


class _FakeLimiter:
    def __init__(self) -> None:
        self.allowed = True
        self.ip_calls: list[dict[str, str]] = []

    async def check(self, *, action: str, user_id: str, ip: str) -> RateDecision:
        return self._decision(action)

    async def check_ip(self, *, action: str, ip: str) -> RateDecision:
        self.ip_calls.append({"action": action, "ip": ip})
        return self._decision(action)

    def _decision(self, action: str) -> RateDecision:
        return RateDecision(
            allowed=self.allowed,
            scope="ip",
            action=action,
            count=601,
            limit=600,
            resets_at=datetime.now(UTC) + timedelta(hours=1),
        )


def _client() -> tuple[httpx.AsyncClient, _FakeDb, _FakeLimiter]:
    db = _FakeDb()
    limiter = _FakeLimiter()
    app = create_app(
        config=_config(),
        db=cast(Any, db),
        identity_service=cast(Any, object()),
        credits=cast(Any, object()),
        job_queue=cast(Any, object()),
        rate_limiter=cast(Any, limiter),
        storage=cast(Any, _FakeStorage()),
    )
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test"), db, limiter


def _headers(user_id: UUID | None = None) -> dict[str, str]:
    session = mint_app_jwt(_SECRET, user_id or _USER_ID, 3600)
    return {"Authorization": f"Bearer {session.access_token}"}


def _delivered_files() -> list[dict[str, Any]]:
    return [
        {"file_type": "html", "storage_path": f"generated/{_PROJECT_ID}/presentation.html"},
        {"file_type": "pptx", "storage_path": f"generated/{_PROJECT_ID}/presentation.pptx"},
        {"file_type": "pdf", "storage_path": f"generated/{_PROJECT_ID}/presentation.pdf"},
    ]


# ------------------------------------------------------------------- create


async def test_create_project_requires_auth() -> None:
    client, *_ = _client()
    response = await client.post("/projects", json={"title": "Yangi"})
    assert response.status_code == 401


async def test_create_project_returns_row_for_caller() -> None:
    client, db, _limiter = _client()
    response = await client.post("/projects", json={"title": "Yangi loyiha"}, headers=_headers())
    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "Yangi loyiha"
    assert body["project_type"] == "presentation" and body["status"] == "draft"
    assert db.created_projects[0]["user_id"] == str(_USER_ID)


# --------------------------------------------------------------------- deck


async def test_deck_access_is_owner_only_404() -> None:
    client, db, _limiter = _client()
    db.files = _delivered_files()
    db.project_owner = str(uuid4())
    response = await client.get(f"/projects/{_PROJECT_ID}/deck", headers=_headers())
    assert response.status_code == 404


async def test_deck_not_ready_is_404() -> None:
    client, _db, _limiter = _client()
    response = await client.get(f"/projects/{_PROJECT_ID}/deck", headers=_headers())
    assert response.status_code == 404
    assert response.json()["detail"] == "deck_not_ready"


async def test_deck_access_returns_short_html_ttl_and_hour_downloads() -> None:
    client, db, _limiter = _client()
    db.files = _delivered_files()
    response = await client.get(f"/projects/{_PROJECT_ID}/deck", headers=_headers())
    assert response.status_code == 200
    body = response.json()
    assert body["html_expires_in"] == 900
    assert "ttl=900" in body["html_url"] and "presentation.html" in body["html_url"]
    formats = {d["format"]: d for d in body["downloads"]}
    assert set(formats) == {"pptx", "pdf"}
    assert all(d["expires_in"] == 3600 for d in body["downloads"])
    assert "ttl=3600" in formats["pdf"]["url"]


# -------------------------------------------------------------------- share


async def test_share_enable_mints_token_and_enable_is_idempotent() -> None:
    client, db, _limiter = _client()
    first = await client.post(
        f"/projects/{_PROJECT_ID}/share", json={"action": "enable"}, headers=_headers()
    )
    assert first.status_code == 200
    token = first.json()["share_token"]
    assert isinstance(token, str) and 16 <= len(token) <= 64

    second = await client.post(
        f"/projects/{_PROJECT_ID}/share", json={"action": "enable"}, headers=_headers()
    )
    assert second.json()["share_token"] == token
    assert len(db.share_writes) == 1


async def test_share_rotate_replaces_token() -> None:
    client, db, _limiter = _client()
    db.share_token = "old-token-1234567890"
    response = await client.post(
        f"/projects/{_PROJECT_ID}/share", json={"action": "rotate"}, headers=_headers()
    )
    new_token = response.json()["share_token"]
    assert new_token is not None and new_token != "old-token-1234567890"


async def test_share_disable_clears_token() -> None:
    client, db, _limiter = _client()
    db.share_token = "old-token-1234567890"
    response = await client.post(
        f"/projects/{_PROJECT_ID}/share", json={"action": "disable"}, headers=_headers()
    )
    assert response.json()["share_token"] is None
    assert db.share_writes == [(_PROJECT_ID, None)]


async def test_share_management_is_owner_only() -> None:
    client, db, _limiter = _client()
    db.project_owner = str(uuid4())
    response = await client.post(
        f"/projects/{_PROJECT_ID}/share", json={"action": "enable"}, headers=_headers()
    )
    assert response.status_code == 404
    assert db.share_writes == []


# -------------------------------------------------------------- provenance


async def test_provenance_without_session_is_empty() -> None:
    client, _db, _limiter = _client()
    response = await client.get(f"/projects/{_PROJECT_ID}/provenance", headers=_headers())
    assert response.status_code == 200
    assert response.json() == {"rows": [], "total_claims": 0}


async def test_provenance_resolves_stamped_refs_to_filenames() -> None:
    client, db, _limiter = _client()
    db.sources_json = {
        "claims": [
            {
                "source_chunk_id": f"{_SOURCE_ID}:3",
                "claim_text": "Suv tejash 94.4% ga yetdi.",
                "quote": "94.4% savings",
                "strength": "strong",
            },
            {
                "source_chunk_id": "7",
                "claim_text": "Bot-era claim without a bound source.",
                "quote": None,
                "strength": "moderate",
            },
            {
                "source_chunk_id": "",
                "claim_text": "Legacy claim with no ref at all.",
                "quote": None,
                "strength": "weak",
            },
        ]
    }
    response = await client.get(f"/projects/{_PROJECT_ID}/provenance", headers=_headers())
    assert response.status_code == 200
    body = response.json()
    assert body["total_claims"] == 3
    linked, bare, legacy = body["rows"]
    assert linked["source_filename"] == "manba.pdf" and linked["chunk_index"] == 3
    assert bare["source_filename"] is None and bare["chunk_index"] == 7
    assert legacy["source_filename"] is None and legacy["chunk_index"] is None


async def test_provenance_is_owner_only() -> None:
    client, db, _limiter = _client()
    db.project_owner = str(uuid4())
    response = await client.get(f"/projects/{_PROJECT_ID}/provenance", headers=_headers())
    assert response.status_code == 404


# ------------------------------------------------------------------- public


async def test_public_share_resolves_without_auth() -> None:
    client, db, limiter = _client()
    db.share_token = "tok-abcdefghijklmnop"
    db.files = _delivered_files()
    response = await client.get(f"/public/decks/{db.share_token}")
    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "Test loyiha"
    assert "presentation.html" in body["html_url"] and "ttl=900" in body["html_url"]
    assert limiter.ip_calls[0]["action"] == "share_view"


async def test_public_share_unknown_or_rotated_token_is_404() -> None:
    client, db, _limiter = _client()
    db.share_token = "tok-abcdefghijklmnop"
    db.files = _delivered_files()
    response = await client.get("/public/decks/tok-wrongwrongwrongwrong")
    assert response.status_code == 404


async def test_public_share_rate_limited_per_ip() -> None:
    client, db, limiter = _client()
    db.share_token = "tok-abcdefghijklmnop"
    limiter.allowed = False
    response = await client.get(f"/public/decks/{db.share_token}")
    assert response.status_code == 429


async def test_public_share_disabled_project_is_404() -> None:
    client, db, _limiter = _client()
    db.share_token = None
    response = await client.get("/public/decks/tok-abcdefghijklmnop")
    assert response.status_code == 404


# ---------------------------------------------------------------- interview
#
# The interview is derived from PROCESSED sources only — never from the user's
# text. With nothing processed the route says so rather than inventing a
# question set, which is what lets the caller offer the "decide for me" exit.


def _processed_sources_json() -> dict[str, Any]:
    """The light half of a real serialized SourceProcessingResult."""

    from packages.bot.orchestrators.article_orchestrator import SourceProcessingResult
    from packages.bot.sessions.serialization import serialize_sources
    from packages.core.enums import ClaimStrength, ClaimType
    from packages.core.models.source import SourceChunkCreate, SourceClaimCreate

    claims = [
        SourceClaimCreate(
            source_chunk_id=f"{_SOURCE_ID}:0",
            claim_text="Suv tejash Sietlda 94.4% ga yetdi va energiya sarfi kamaydi.",
            quote="94.4% savings",
            strength=ClaimStrength.STRONG,
            claim_type=ClaimType.STATISTICAL_RESULT,
        ),
        SourceClaimCreate(
            source_chunk_id=f"{_SOURCE_ID}:1",
            claim_text="Newton fizika qonunlarini shakllantirdi va mexanikani asosladi.",
            strength=ClaimStrength.MODERATE,
        ),
    ]
    chunks = [
        SourceChunkCreate(
            chunk_index=0,
            text="Radiative cooling reduces energy demand by 30% in arid climates.",
        ),
        SourceChunkCreate(
            chunk_index=1,
            text="The study measured 94.4% water savings across three climate zones.",
        ),
    ]
    light, _figures = serialize_sources(SourceProcessingResult(claims=claims, chunks=chunks))
    return light


async def test_interview_without_a_brain_session_is_409_sources_not_ready() -> None:
    client, db, _limiter = _client()
    assert db.sources_json is None
    response = await client.post(f"/projects/{_PROJECT_ID}/interview", json={}, headers=_headers())
    assert response.status_code == 409
    assert response.json()["detail"]["reason"] == "sources_not_ready"


async def test_interview_with_an_empty_session_is_409_sources_not_ready() -> None:
    from packages.bot.orchestrators.article_orchestrator import SourceProcessingResult
    from packages.bot.sessions.serialization import serialize_sources

    client, db, _limiter = _client()
    light, _figures = serialize_sources(SourceProcessingResult())
    db.sources_json = light
    response = await client.post(f"/projects/{_PROJECT_ID}/interview", json={}, headers=_headers())
    assert response.status_code == 409
    assert response.json()["detail"]["reason"] == "sources_not_ready"


async def test_interview_from_processed_sources_returns_a_localised_question_set() -> None:
    client, db, _limiter = _client()
    db.sources_json = _processed_sources_json()
    response = await client.post(
        f"/projects/{_PROJECT_ID}/interview", json={"language": "uz"}, headers=_headers()
    )
    assert response.status_code == 200
    body = response.json()

    ids = [question["question_id"] for question in body["questions"]]
    assert ids == [
        "audience",
        "duration",
        "emphasis",
        "title_style",
        "include_interactive",
        "theme",
        "speaker_notes",
        "headline_numbers",
        "closing_ask",
    ]
    assert all(question["question_text"] for question in body["questions"])
    types = {question["question_id"]: question["question_type"] for question in body["questions"]}
    assert types["audience"] == "single_select"
    assert types["duration"] == "slider"
    assert types["emphasis"] == "multi_select"

    # Content analysis, not a preset: the chunks read as environmental, one
    # claim is a statistic (which is what adds `headline_numbers`) and one
    # names a person.
    assert body["detected_domain"] == "environmental"
    assert body["estimated_slide_count"] == 6
    assert body["available_stats_count"] == 1
    assert body["available_people_count"] == 1


async def test_interview_is_owner_only() -> None:
    client, db, _limiter = _client()
    db.sources_json = _processed_sources_json()
    db.project_owner = str(uuid4())
    response = await client.post(f"/projects/{_PROJECT_ID}/interview", json={}, headers=_headers())
    assert response.status_code == 404


# ------------------------------------------------------------ share payload


async def test_public_share_hands_over_downloads_at_an_hour_ttl() -> None:
    # The token is already the whole capability, so withholding the PPTX/PDF
    # protected nothing and only made the share view useless to students.
    client, db, _limiter = _client()
    db.share_token = "tok-abcdefghijklmnop"
    db.files = _delivered_files()
    response = await client.get(f"/public/decks/{db.share_token}")
    assert response.status_code == 200
    body = response.json()

    assert body["expires_in"] == 900 and "ttl=900" in body["html_url"]
    formats = {download["format"]: download for download in body["downloads"]}
    assert set(formats) == {"pptx", "pdf"}
    assert formats["pptx"]["expires_in"] == 3600 and "ttl=3600" in formats["pptx"]["url"]
    assert formats["pdf"]["expires_in"] == 3600 and "ttl=3600" in formats["pdf"]["url"]
    assert "presentation.pptx" in formats["pptx"]["url"]


async def test_public_share_with_html_only_returns_an_empty_downloads_list() -> None:
    client, db, _limiter = _client()
    db.share_token = "tok-abcdefghijklmnop"
    db.files = [{"file_type": "html", "storage_path": f"generated/{_PROJECT_ID}/presentation.html"}]
    response = await client.get(f"/public/decks/{db.share_token}")
    assert response.status_code == 200
    body = response.json()
    assert body["downloads"] == []
    assert "presentation.html" in body["html_url"]


# ------------------------------------------------------- interview localisation


async def test_interview_threads_the_requested_language_to_the_engine() -> None:
    # The uz case alone proves nothing: uz is InterviewRequest's default, so a
    # route that dropped body.language entirely would still answer in Uzbek.
    # Asking for ru over the SAME sources is what pins the thread-through.
    client, db, _limiter = _client()
    db.sources_json = _processed_sources_json()
    uz = await client.post(
        f"/projects/{_PROJECT_ID}/interview", json={"language": "uz"}, headers=_headers()
    )
    ru = await client.post(
        f"/projects/{_PROJECT_ID}/interview", json={"language": "ru"}, headers=_headers()
    )
    assert uz.status_code == 200 and ru.status_code == 200

    uz_text = {q["question_id"]: q["question_text"] for q in uz.json()["questions"]}
    ru_text = {q["question_id"]: q["question_text"] for q in ru.json()["questions"]}

    assert ru_text.keys() == uz_text.keys()
    # Pinned literally, not merely "different from uz": any other localisation
    # would also differ, and only the Russian string proves ru was honoured.
    assert ru_text["audience"] == "Для кого готовится?"
    assert uz_text["audience"] == "Kim uchun tayyorlanmoqda?"
    assert all(ru_text[question_id] != uz_text[question_id] for question_id in uz_text)
