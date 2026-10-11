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
from packages.platform.database import DatabaseClient
from packages.platform.document_models import (
    ExportFileFormat,
    export_storage_key,
)
from packages.platform.document_store import DocumentStore
from packages.platform.exports import renderer_version
from packages.platform.rate_limit import RateDecision
from tests.unit.fake_documents import seed_presentation
from tests.unit.test_database_client import FakeSupabaseClient

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
        self.sources_json: dict[str, Any] | None = None
        self.project_sources: list[dict[str, Any]] = [{"id": _SOURCE_ID, "filename": "manba.pdf"}]
        self.share_writes: list[tuple[str, str | None]] = []
        self.created_projects: list[dict[str, Any]] = []
        self.fake = FakeSupabaseClient()
        self.fake.seed("projects", [{"id": _PROJECT_ID, "user_id": str(_USER_ID)}])
        self.store = DocumentStore(DatabaseClient(_config(), client=cast(Any, self.fake)))

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
        documents=db.store,
    )
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test"), db, limiter


def _headers(user_id: UUID | None = None) -> dict[str, str]:
    session = mint_app_jwt(_SECRET, user_id or _USER_ID, 3600)
    return {"Authorization": f"Bearer {session.access_token}"}


def _seed_deck(db: _FakeDb, content: dict[str, Any] | None = None) -> str:
    """Commit a deck revision as the head; returns its id."""

    head = db.fake.tables.get("documents")
    if not head:
        _document_id, revision_id = seed_presentation(
            db.fake.tables, project_id=_PROJECT_ID, content=content or {"title": "deck"}
        )
        return revision_id
    from tests.unit.fake_documents import DocumentRpcEmulator

    document = head[0]
    result = DocumentRpcEmulator(db.fake.tables).commit_revision(
        {
            "p_document_id": document["id"],
            "p_base_revision_id": document["head_revision_id"],
            "p_content": content or {"title": f"deck {len(db.fake.tables['document_revisions'])}"},
            "p_kind": "import",
            "p_schema_version": 1,
            "p_actor": "system:test",
            "p_idempotency_key": f"seed-{uuid4()}",
        }
    )
    return str(result[0]["revision_id"])


def _publish(
    db: _FakeDb,
    revision_id: str,
    formats: tuple[str, ...] = ("html", "pptx", "pdf"),
    *,
    version: str | None = None,
) -> None:
    """Register exports for ``revision_id`` the way register_export would."""

    document = db.fake.tables["documents"][0]
    for name in formats:
        fmt = ExportFileFormat(name)
        sha = f"{name[0]}" * 64
        db.fake.tables.setdefault("revision_exports", []).append(
            {
                "revision_id": revision_id,
                "format": name,
                "renderer_version": version or renderer_version(),
                "storage_key": export_storage_key(
                    document["id"], revision_id, version or renderer_version(), fmt, sha
                ),
                "sha256": sha,
                "byte_size": 100,
                "page_count": None,
                "created_by_job": None,
                "created_at": f"2026-01-01T00:00:0{len(db.fake.tables['revision_exports']) % 10}+00:00",
            }
        )


def _delivered(db: _FakeDb, formats: tuple[str, ...] = ("html", "pptx", "pdf")) -> str:
    """A deck whose head has registered exports from the current renderer."""

    revision_id = _seed_deck(db)
    _publish(db, revision_id, formats)
    return revision_id


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
    _delivered(db)
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
    head = _delivered(db)
    response = await client.get(f"/projects/{_PROJECT_ID}/deck", headers=_headers())
    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "ready" and body["revision_id"] == head and body["is_head"] is True
    current = body["current"]
    assert current["html_expires_in"] == 900
    assert "ttl=900" in current["html_url"] and f"/{head}/" in current["html_url"]
    assert current["html_url"].split("?")[0].endswith(".html")
    formats = {d["format"]: d for d in current["downloads"]}
    assert set(formats) == {"pptx", "pdf"}
    assert all(d["expires_in"] == 3600 for d in current["downloads"])
    assert "ttl=3600" in formats["pdf"]["url"]
    assert body["fallback"] is None


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
    _delivered(db)
    response = await client.get(f"/public/decks/{db.share_token}")
    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "Test loyiha"
    assert body["html_url"].split("?")[0].endswith(".html") and "ttl=900" in body["html_url"]
    assert limiter.ip_calls[0]["action"] == "share_view"


async def test_public_share_unknown_or_rotated_token_is_404() -> None:
    client, db, _limiter = _client()
    db.share_token = "tok-abcdefghijklmnop"
    _delivered(db)
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
    _delivered(db)
    response = await client.get(f"/public/decks/{db.share_token}")
    assert response.status_code == 200
    body = response.json()

    assert body["expires_in"] == 900 and "ttl=900" in body["html_url"]
    formats = {download["format"]: download for download in body["downloads"]}
    assert set(formats) == {"pptx", "pdf"}
    assert formats["pptx"]["expires_in"] == 3600 and "ttl=3600" in formats["pptx"]["url"]
    assert formats["pdf"]["expires_in"] == 3600 and "ttl=3600" in formats["pdf"]["url"]
    assert formats["pptx"]["url"].split("?")[0].endswith(".pptx")


async def test_public_share_with_html_only_returns_an_empty_downloads_list() -> None:
    client, db, _limiter = _client()
    db.share_token = "tok-abcdefghijklmnop"
    _delivered(db, ("html",))
    response = await client.get(f"/public/decks/{db.share_token}")
    assert response.status_code == 200
    body = response.json()
    assert body["downloads"] == []
    assert body["html_url"].split("?")[0].endswith(".html")


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


# ----------------------------------------------------------------- decisions


def _decisions_deck(*, with_plan: bool = True) -> dict[str, Any]:
    """A deck_json row shaped like the pipeline really persists one.

    Built through the real DeckSpec so a field rename in the model breaks this
    test rather than silently changing what the route can serve.
    """

    from packages.core.enums import (
        AudienceType,
        BackgroundTreatment,
        NarrativePhase,
        PresentationMood,
        SlideType,
    )
    from packages.core.models.presentation import (
        ColorPalette,
        DeckPlan,
        DeckSpec,
        DesignDirectionSpec,
        PlannedSection,
        PresentationInterviewAnswers,
        SlideContent,
        SlideSpec,
    )

    plan = (
        DeckPlan(
            thesis="Suv olib qo'yish Orol dengizini o'lchab bo'ladigan darajada qisqartirdi.",
            audience_takeaway="Tinglovchi qisqarishning sababi va ko'lamini ayta oladi.",
            sections=[
                PlannedSection(
                    section_name="Sabab",
                    thesis="Sug'orish kanallari daryo oqimini dengizdan burdi.",
                    phase=NarrativePhase.HOOK,
                ),
                PlannedSection(
                    section_name="Oqibat",
                    thesis="Suv sathi o'nlab metrga tushdi va port shaharlar quridi.",
                    phase=NarrativePhase.CLOSE,
                ),
            ],
            image_cohesion_note="Bitta izchil hujjatli fotografiya uslubi.",
        )
        if with_plan
        else None
    )
    deck = DeckSpec(
        project_id=_PROJECT_ID,
        title="Orol dengizi qurishi",
        design=DesignDirectionSpec(
            mood=PresentationMood.WARM_HISTORICAL,
            palette=ColorPalette(
                background="#1A120B",
                surface="#D4C5A9",
                text="#F5F0E8",
                accent="#C4923A",
                text_secondary="#A89F91",
            ),
            heading_font="Playfair Display",
            body_font="EB Garamond",
            image_style_prefix="documentary photography, no text in image, ",
            background_treatment=BackgroundTreatment.DARK,
        ),
        interview=PresentationInterviewAnswers(audience=AudienceType.UNDERGRADUATE),
        plan=plan,
        slides=[
            SlideSpec(
                slide_index=0,
                slide_type=SlideType.TITLE_HERO,
                content=SlideContent(title="Orol dengizi qurishi"),
            ),
            SlideSpec(
                slide_index=1,
                slide_type=SlideType.SECTION_BREAK,
                content=SlideContent(title="Sabab"),
            ),
        ],
    )
    return {"deck_json": deck.model_dump(mode="json")}


async def test_decisions_returns_the_argument_and_the_look() -> None:
    client, db, _limiter = _client()
    _seed_deck(db, _decisions_deck()["deck_json"])

    response = await client.get(f"/projects/{_PROJECT_ID}/decisions", headers=_headers())

    assert response.status_code == 200
    body = response.json()
    # The argument the deck commits to — the thing "Jarayon tafsiloti" could
    # never show because no route returned deck_json (G14).
    assert body["thesis"].startswith("Suv olib qo'yish")
    assert [s["section_name"] for s in body["sections"]] == ["Sabab", "Oqibat"]
    assert all(s["thesis"] != s["section_name"] for s in body["sections"])
    # The look, including the palette as real colours.
    assert body["heading_font"] == "Playfair Display"
    assert body["palette"]["accent"] == "#C4923A"
    # What was decided FOR the user when they answered nothing.
    assert body["audience"] == "undergraduate"
    assert body["talk_duration_minutes"] > 0
    # The roster, 1-based for display.
    assert body["slide_count"] == 2
    assert [s["slide_number"] for s in body["slides"]] == [1, 2]


async def test_decisions_degrades_for_a_deck_that_predates_the_planner() -> None:
    # DeckSpec.plan is optional, so a deck generated before the planner became
    # binding has no argument to report. The design and the roster still exist,
    # so the route serves those rather than 404ing or inventing a thesis.
    client, db, _limiter = _client()
    _seed_deck(db, _decisions_deck(with_plan=False)["deck_json"])

    response = await client.get(f"/projects/{_PROJECT_ID}/decisions", headers=_headers())

    assert response.status_code == 200
    body = response.json()
    assert body["thesis"] is None
    assert body["audience_takeaway"] is None
    assert body["image_cohesion_note"] is None
    assert body["sections"] == []
    assert body["heading_font"] == "Playfair Display"
    assert body["slide_count"] == 2


async def test_decisions_without_a_deck_is_404() -> None:
    client, _db, _limiter = _client()

    response = await client.get(f"/projects/{_PROJECT_ID}/decisions", headers=_headers())

    assert response.status_code == 404
    assert response.json()["detail"] == "deck_not_ready"


async def test_decisions_is_owner_only() -> None:
    client, db, _limiter = _client()
    _seed_deck(db, _decisions_deck()["deck_json"])
    db.project_owner = str(uuid4())

    response = await client.get(f"/projects/{_PROJECT_ID}/decisions", headers=_headers())

    assert response.status_code == 404
    assert response.json()["detail"] == "project_not_found"


async def test_decisions_roster_is_bounded_by_the_model_not_the_route() -> None:
    # The route deliberately does NOT cap the roster: DeckSpec.slides is capped
    # at 50 by the model, so a deck carrying more cannot exist to be served. An
    # extra route-level cap would name a ceiling that is not the real one.
    from packages.core.models.presentation import DeckSpec

    field = DeckSpec.model_fields["slides"]
    bound = next(m for m in field.metadata if hasattr(m, "max_length")).max_length

    client, db, _limiter = _client()
    row = _decisions_deck()
    one = row["deck_json"]["slides"][1]
    row["deck_json"]["slides"] = [
        {**one, "slide_index": i, "slide_id": f"slide_{i:03d}"} for i in range(bound)
    ]
    _seed_deck(db, row["deck_json"])

    response = await client.get(f"/projects/{_PROJECT_ID}/decisions", headers=_headers())

    assert response.status_code == 200
    body = response.json()
    assert body["slide_count"] == bound
    assert len(body["slides"]) == bound


# ------------------------------------------------- revision-keyed downloads (ADR 0001)


async def test_head_without_exports_is_render_needed() -> None:
    client, db, _limiter = _client()
    head = _seed_deck(db)
    response = await client.get(f"/projects/{_PROJECT_ID}/deck", headers=_headers())
    assert response.status_code == 200
    body = response.json()
    assert body == {
        **body,
        "revision_id": head,
        "head_revision_id": head,
        "is_head": True,
        "state": "render_needed",
        "current": None,
        "fallback": None,
    }


async def test_a_render_of_an_older_revision_never_becomes_the_heads_download() -> None:
    # Bug (a): an older revision's render overwrote the project-keyed files the
    # head served. Exports are keyed by revision now: the head stays
    # render_needed, and the older export is offered only as a LABELLED fallback.
    client, db, _limiter = _client()
    older = _seed_deck(db, {"title": "older"})
    head = _seed_deck(db, {"title": "newer"})
    _publish(db, older)

    body = (await client.get(f"/projects/{_PROJECT_ID}/deck", headers=_headers())).json()

    assert body["revision_id"] == head and body["state"] == "render_needed"
    assert body["current"] is None
    assert body["fallback"]["reason"] == "older_revision"
    assert body["fallback"]["revision_id"] == older
    assert f"/{older}/" in body["fallback"]["html_url"]


async def test_the_same_revision_from_an_earlier_renderer_is_a_labelled_fallback() -> None:
    client, db, _limiter = _client()
    head = _seed_deck(db)
    _publish(db, head, version="pw-0000000000000000")

    body = (await client.get(f"/projects/{_PROJECT_ID}/deck", headers=_headers())).json()

    assert body["state"] == "render_needed"
    assert body["fallback"]["reason"] == "older_renderer"
    assert body["fallback"]["revision_id"] == head
    assert body["fallback"]["renderer_version"] == "pw-0000000000000000"


async def test_an_explicit_older_revision_serves_its_own_exports() -> None:
    client, db, _limiter = _client()
    older = _seed_deck(db, {"title": "older"})
    _publish(db, older)
    head = _seed_deck(db, {"title": "newer"})
    _publish(db, head)

    body = (
        await client.get(f"/projects/{_PROJECT_ID}/deck?revision_id={older}", headers=_headers())
    ).json()

    assert body["revision_id"] == older and body["is_head"] is False
    assert body["state"] == "ready"
    assert f"/{older}/" in body["current"]["html_url"]


async def test_a_revision_of_another_project_is_404() -> None:
    client, db, _limiter = _client()
    _delivered(db)
    response = await client.get(
        f"/projects/{_PROJECT_ID}/deck?revision_id={uuid4()}", headers=_headers()
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "revision_not_found"


async def test_public_share_without_head_exports_is_404() -> None:
    client, db, _limiter = _client()
    db.share_token = "tok-abcdefghijklmnop"
    _seed_deck(db)
    response = await client.get(f"/public/decks/{db.share_token}")
    assert response.status_code == 404


async def test_decisions_for_a_legacy_invalid_head_is_409() -> None:
    client, db, _limiter = _client()
    head = _seed_deck(db, {"legacy_raw": [1, 2, 3]})
    response = await client.get(f"/projects/{_PROJECT_ID}/decisions", headers=_headers())
    assert response.status_code == 409
    assert response.json()["detail"] == {"reason": "legacy_invalid", "revision_id": head}
