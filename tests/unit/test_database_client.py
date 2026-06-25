"""Behaviour tests for :class:`DatabaseClient`.

We swap the live ``supabase.Client`` for an in-memory fake that
implements the subset of the fluent query API we actually use
(``table().select().eq().limit().execute()``, plus insert / update). The
fake stores rows in dicts so each test can pre-seed data, observe
inserts and updates, and assert on the resulting state without relying
on chained ``MagicMock`` trees that break when the call shape shifts.

Per the project testing rules we do not mock supabase-py's internal
classes; we replace the whole client with a behavioural fake at the
DatabaseClient seam.
"""

from __future__ import annotations

import asyncio
import re
import uuid
from types import SimpleNamespace
from typing import Any, cast

import pytest

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
from packages.platform.config import PlatformConfig
from packages.platform.database import (
    DatabaseClient,
    generate_invoice_number,
    generate_subscriber_id,
)

# --------------------------------------------------------------- fakes


class _FakeQuery:
    """Records a single fluent query against ``FakeSupabaseClient``.

    Methods mirror the supabase-py builder shape: every chainable call
    returns ``self`` so the test client behaves like the real one.
    ``execute()`` consults the parent client to produce the response.
    """

    def __init__(self, client: FakeSupabaseClient, table: str) -> None:
        self._client = client
        self._table = table
        self._mode: str = "select"
        self._payload: dict[str, Any] | None = None
        self._filters: list[tuple[str, Any]] = []
        self._lt_filters: list[tuple[str, Any]] = []
        self._limit: int | None = None
        self._order: tuple[str, bool] | None = None
        self._select_cols: str = "*"
        self._on_conflict: str = ""

    def select(self, cols: str = "*") -> _FakeQuery:
        self._mode = "select"
        self._select_cols = cols
        return self

    def insert(self, payload: dict[str, Any]) -> _FakeQuery:
        self._mode = "insert"
        self._payload = payload
        return self

    def update(self, payload: dict[str, Any]) -> _FakeQuery:
        self._mode = "update"
        self._payload = payload
        return self

    def upsert(self, payload: dict[str, Any], *, on_conflict: str = "") -> _FakeQuery:
        self._mode = "upsert"
        self._payload = payload
        self._on_conflict = on_conflict
        return self

    def eq(self, col: str, val: Any) -> _FakeQuery:
        self._filters.append((col, val))
        return self

    def lt(self, col: str, val: Any) -> _FakeQuery:
        self._lt_filters.append((col, val))
        return self

    def limit(self, n: int) -> _FakeQuery:
        self._limit = n
        return self

    def order(self, col: str, desc: bool = False) -> _FakeQuery:
        self._order = (col, desc)
        return self

    def execute(self) -> SimpleNamespace:
        return self._client.handle(
            table=self._table,
            mode=self._mode,
            payload=self._payload,
            filters=self._filters,
            lt_filters=self._lt_filters,
            limit=self._limit,
            order=self._order,
            select_cols=self._select_cols,
            on_conflict=self._on_conflict,
        )


class FakeSupabaseClient:
    """In-memory replacement for ``supabase.Client`` used in tests.

    Stores rows per table in plain dicts and supports the small subset
    of the fluent query API the DatabaseClient actually uses. Records
    every insert and update so tests can assert on the side effects.
    """

    def __init__(self) -> None:
        self.tables: dict[str, list[dict[str, Any]]] = {}
        self.inserts: list[tuple[str, dict[str, Any]]] = []
        self.updates: list[tuple[str, dict[str, Any], list[tuple[str, Any]]]] = []

    def seed(self, table: str, rows: list[dict[str, Any]]) -> None:
        self.tables[table] = list(rows)

    def table(self, name: str) -> _FakeQuery:
        return _FakeQuery(self, name)

    def handle(
        self,
        *,
        table: str,
        mode: str,
        payload: dict[str, Any] | None,
        filters: list[tuple[str, Any]],
        lt_filters: list[tuple[str, Any]] | None = None,
        limit: int | None,
        order: tuple[str, bool] | None,
        select_cols: str,
        on_conflict: str = "",
    ) -> SimpleNamespace:
        lt_filters = lt_filters or []
        rows = self.tables.setdefault(table, [])
        if mode == "select":
            filtered = [r for r in rows if all(r.get(c) == v for c, v in filters)]
            filtered = [
                r
                for r in filtered
                if all(r.get(c) is not None and str(r.get(c)) < str(v) for c, v in lt_filters)
            ]
            if order is not None:
                col, desc = order
                filtered = sorted(filtered, key=lambda r: r.get(col) or "", reverse=desc)
            if limit is not None:
                filtered = filtered[:limit]
            if select_cols == "*":
                data = filtered
            else:
                wanted = [c.strip() for c in select_cols.split(",")]
                data = [{c: r.get(c) for c in wanted} for r in filtered]
            return SimpleNamespace(data=data)
        if mode == "insert":
            assert payload is not None
            row = dict(payload)
            row.setdefault("id", str(uuid.uuid4()))
            rows.append(row)
            self.inserts.append((table, dict(row)))
            return SimpleNamespace(data=[row])
        if mode == "update":
            assert payload is not None
            updated: list[dict[str, Any]] = []
            for r in rows:
                if all(r.get(c) == v for c, v in filters):
                    r.update(payload)
                    updated.append(r)
            self.updates.append((table, dict(payload), list(filters)))
            return SimpleNamespace(data=updated)
        if mode == "upsert":
            assert payload is not None
            conflict_col = on_conflict or "id"
            match = next(
                (r for r in rows if r.get(conflict_col) == payload.get(conflict_col)),
                None,
            )
            if match is not None:
                match.update(payload)
                self.updates.append(
                    (table, dict(payload), [(conflict_col, payload.get(conflict_col))])
                )
                return SimpleNamespace(data=[match])
            row = dict(payload)
            row.setdefault("id", str(uuid.uuid4()))
            rows.append(row)
            self.inserts.append((table, dict(row)))
            return SimpleNamespace(data=[row])
        return SimpleNamespace(data=[])


def _make_db() -> tuple[DatabaseClient, FakeSupabaseClient]:
    """Build a DatabaseClient wired to a fresh fake Supabase client."""

    cfg = PlatformConfig(
        supabase_url="https://test.supabase.co",
        supabase_service_key="test-service-key",
        telegram_bot_token="test-token",
    )
    fake = FakeSupabaseClient()
    db = DatabaseClient(cfg, client=cast(Any, fake))
    return db, fake


# --------------------------------------------------------------- users


async def test_create_user_generates_subscriber_id_and_inserts() -> None:
    db, fake = _make_db()
    user = await db.create_user(telegram_id=12345, language="uz")

    sid = user["subscriber_id"]
    assert isinstance(sid, str)
    assert re.match(r"^[1-9]\d{5}$", sid), sid
    assert len(fake.inserts) == 1
    table, row = fake.inserts[0]
    assert table == "users"
    assert row["telegram_id"] == 12345
    assert row["language"] == "uz"
    assert row["calibration_level"] == "bakalavr"
    assert row["subscriber_id"] == sid


async def test_create_user_assigns_unique_subscriber_id_when_some_exist() -> None:
    db, fake = _make_db()
    fake.seed(
        "users",
        [
            {"id": "u1", "telegram_id": 1, "subscriber_id": "100000"},
            {"id": "u2", "telegram_id": 2, "subscriber_id": "200000"},
        ],
    )

    user = await db.create_user(telegram_id=42)
    assert user["subscriber_id"] not in {"100000", "200000"}


async def test_create_user_persists_full_name_when_provided() -> None:
    db, fake = _make_db()
    await db.create_user(telegram_id=99, full_name="Iko Suleyman")
    _, row = fake.inserts[0]
    assert row["full_name"] == "Iko Suleyman"


async def test_create_user_omits_full_name_when_none() -> None:
    db, fake = _make_db()
    await db.create_user(telegram_id=99)
    _, row = fake.inserts[0]
    assert "full_name" not in row


async def test_get_user_by_telegram_id_returns_matching_row() -> None:
    db, fake = _make_db()
    fake.seed(
        "users",
        [
            {"id": "a", "telegram_id": 10, "subscriber_id": "100001"},
            {"id": "b", "telegram_id": 20, "subscriber_id": "100002"},
        ],
    )
    row = await db.get_user_by_telegram_id(20)
    assert row is not None
    assert row["id"] == "b"


async def test_get_user_by_telegram_id_returns_none_when_absent() -> None:
    db, _ = _make_db()
    assert await db.get_user_by_telegram_id(999) is None


async def test_get_user_by_subscriber_id_returns_matching_row() -> None:
    db, fake = _make_db()
    fake.seed(
        "users",
        [
            {"id": "a", "telegram_id": 10, "subscriber_id": "847291"},
            {"id": "b", "telegram_id": 20, "subscriber_id": "200000"},
        ],
    )
    row = await db.get_user_by_subscriber_id("847291")
    assert row is not None
    assert row["id"] == "a"


async def test_update_user_language_records_update() -> None:
    db, fake = _make_db()
    fake.seed(
        "users",
        [{"id": "u1", "telegram_id": 1, "language": "uz", "subscriber_id": "100000"}],
    )
    await db.update_user_language("u1", "en")
    assert any(
        t == "users" and p == {"language": "en"} and ("id", "u1") in f for t, p, f in fake.updates
    )
    assert fake.tables["users"][0]["language"] == "en"


async def test_update_user_calibration_records_update() -> None:
    db, fake = _make_db()
    fake.seed(
        "users",
        [
            {
                "id": "u1",
                "telegram_id": 1,
                "calibration_level": "bakalavr",
                "subscriber_id": "100000",
            }
        ],
    )
    await db.update_user_calibration("u1", "magistr")
    assert fake.tables["users"][0]["calibration_level"] == "magistr"


# ------------------------------------------------------------ projects


async def test_create_project_inserts_with_user_id_and_type() -> None:
    db, fake = _make_db()
    await db.create_project(
        user_id="u1",
        title="Ag'artıwshılıq",
        project_type="presentation",
        language="uz",
    )
    _, row = fake.inserts[0]
    assert row["user_id"] == "u1"
    assert row["type"] == "presentation"
    assert row["title"] == "Ag'artıwshılıq"
    assert row["language"] == "uz"


async def test_get_user_projects_returns_newest_first_and_filters_by_user() -> None:
    db, fake = _make_db()
    fake.seed(
        "projects",
        [
            {"id": "p1", "user_id": "u1", "title": "A", "created_at": "2026-05-01T00:00:00Z"},
            {"id": "p2", "user_id": "u1", "title": "B", "created_at": "2026-05-08T00:00:00Z"},
            {"id": "p3", "user_id": "u2", "title": "C", "created_at": "2026-05-09T00:00:00Z"},
        ],
    )
    rows = await db.get_user_projects("u1", limit=20)
    assert [r["id"] for r in rows] == ["p2", "p1"]


async def test_update_project_status_changes_status_field() -> None:
    db, fake = _make_db()
    fake.seed("projects", [{"id": "p1", "status": "draft"}])
    await db.update_project_status("p1", "generating")
    assert fake.tables["projects"][0]["status"] == "generating"


# ------------------------------------------------------------ invoices


async def test_create_invoice_uses_subscriber_id_and_sets_expiry() -> None:
    db, fake = _make_db()
    fake.seed(
        "users",
        [{"id": "u1", "telegram_id": 1, "subscriber_id": "847291"}],
    )
    invoice = await db.create_invoice(
        user_id="u1",
        project_id="p1",
        amount_uzs=60000,
        product_type="article_basic",
    )

    assert re.match(r"^847291-\d{4}$", invoice["invoice_number"]), invoice["invoice_number"]
    assert invoice["status"] == "pending"
    assert invoice["amount_uzs"] == 60000
    assert invoice["product_type"] == "article_basic"
    assert invoice.get("expires_at")


async def test_create_invoice_raises_when_user_has_no_subscriber_id() -> None:
    db, fake = _make_db()
    fake.seed("users", [{"id": "u1", "telegram_id": 1}])
    with pytest.raises(ValueError):
        await db.create_invoice(
            user_id="u1",
            project_id="p1",
            amount_uzs=60000,
            product_type="article_basic",
        )


async def test_mark_invoice_paid_sets_status_and_provider_reference() -> None:
    db, fake = _make_db()
    fake.seed(
        "invoices",
        [
            {
                "id": "inv1",
                "user_id": "u1",
                "status": "pending",
                "payment_provider": None,
                "payment_reference": None,
            }
        ],
    )
    await db.mark_invoice_paid("inv1", "payme", "TXN-1234")

    inv = fake.tables["invoices"][0]
    assert inv["status"] == "paid"
    assert inv["payment_provider"] == "payme"
    assert inv["payment_reference"] == "TXN-1234"
    assert inv["paid_at"]


async def test_get_pending_invoice_returns_most_recent_pending() -> None:
    db, fake = _make_db()
    fake.seed(
        "invoices",
        [
            {
                "id": "inv1",
                "user_id": "u1",
                "project_id": "p1",
                "status": "pending",
                "created_at": "2026-05-01T00:00:00Z",
            },
            {
                "id": "inv2",
                "user_id": "u1",
                "project_id": "p1",
                "status": "pending",
                "created_at": "2026-05-09T00:00:00Z",
            },
            {
                "id": "inv3",
                "user_id": "u1",
                "project_id": "p1",
                "status": "paid",
                "created_at": "2026-05-10T00:00:00Z",
            },
        ],
    )
    row = await db.get_pending_invoice("u1", "p1")
    assert row is not None
    assert row["id"] == "inv2"


async def test_mark_invoice_expired_transitions_to_expired() -> None:
    db, fake = _make_db()
    fake.seed("invoices", [{"id": "inv1", "status": "pending"}])
    await db.mark_invoice_expired("inv1")
    assert fake.tables["invoices"][0]["status"] == "expired"


async def test_get_invoice_by_number_returns_matching_row() -> None:
    db, fake = _make_db()
    fake.seed(
        "invoices",
        [
            {"id": "inv1", "invoice_number": "847291-1001", "status": "pending"},
            {"id": "inv2", "invoice_number": "847291-1002", "status": "paid"},
        ],
    )
    row = await db.get_invoice_by_number("847291-1002")
    assert row is not None
    assert row["id"] == "inv2"
    assert row["status"] == "paid"


async def test_get_invoice_by_number_returns_none_when_absent() -> None:
    db, _ = _make_db()
    assert await db.get_invoice_by_number("000000-0000") is None


async def test_expire_old_invoices_only_touches_past_pending() -> None:
    from datetime import UTC, datetime, timedelta

    db, fake = _make_db()
    now = datetime.now(UTC)
    past = (now - timedelta(hours=1)).isoformat()
    future = (now + timedelta(hours=1)).isoformat()
    fake.seed(
        "invoices",
        [
            {"id": "inv_past_pending", "status": "pending", "expires_at": past},
            {"id": "inv_future_pending", "status": "pending", "expires_at": future},
            {"id": "inv_past_paid", "status": "paid", "expires_at": past},
        ],
    )

    count = await db.expire_old_invoices()

    assert count == 1
    rows_by_id = {r["id"]: r for r in fake.tables["invoices"]}
    assert rows_by_id["inv_past_pending"]["status"] == "expired"
    assert rows_by_id["inv_future_pending"]["status"] == "pending"
    assert rows_by_id["inv_past_paid"]["status"] == "paid"


async def test_expire_old_invoices_returns_zero_when_nothing_to_expire() -> None:
    db, fake = _make_db()
    fake.seed("invoices", [])
    assert await db.expire_old_invoices() == 0


# ------------------------------------------------ subscriber/invoice IDs


def test_subscriber_id_format_is_six_digits_no_leading_zero() -> None:
    seen: set[str] = set()
    for _ in range(200):
        sid = generate_subscriber_id(seen)
        assert re.match(r"^[1-9]\d{5}$", sid), sid
        seen.add(sid)


def test_subscriber_id_avoids_existing_collisions() -> None:
    existing = {"123456", "234567", "345678"}
    for _ in range(500):
        sid = generate_subscriber_id(existing)
        assert sid not in existing


def test_subscriber_id_uniqueness_when_generating_in_sequence() -> None:
    seen: set[str] = set()
    for _ in range(100):
        sid = generate_subscriber_id(seen)
        assert sid not in seen
        seen.add(sid)


def test_invoice_number_format() -> None:
    inv = generate_invoice_number("847291")
    assert re.match(r"^847291-\d{4}$", inv), inv


# ---------------------------------------------------- sources / files


async def test_create_source_persists_metadata() -> None:
    db, fake = _make_db()
    await db.create_source(
        project_id="p1",
        filename="paper.pdf",
        file_type="pdf",
        file_size=1024,
        storage_path="r2://bucket/key",
    )
    _, row = fake.inserts[0]
    assert row["project_id"] == "p1"
    assert row["filename"] == "paper.pdf"
    assert row["file_type"] == "pdf"
    assert row["file_size_bytes"] == 1024
    assert row["storage_key"] == "r2://bucket/key"


async def test_create_generated_file_persists_type() -> None:
    db, fake = _make_db()
    await db.create_generated_file(
        project_id="p1",
        file_type="docx",
        storage_path="r2://out/article.docx",
        file_size=2048,
    )
    _, row = fake.inserts[0]
    assert row["project_id"] == "p1"
    assert row["file_type"] == "docx"
    assert row["storage_path"] == "r2://out/article.docx"
    assert row["file_size"] == 2048


# ---------------------------------------------------------------- decks


def _make_deck(*, title: str, audience: AudienceType) -> DeckSpec:
    """Build a minimal but fully valid DeckSpec for persistence tests.

    ``title`` and the interview ``audience`` are parameterised so a test can
    make them DIFFER from the project row's denormalised values and prove
    save_deck sources the columns from the project, never the spec.
    """

    palette = ColorPalette(
        background="#1A120B",
        surface="#D4C5A9",
        text="#F5F0E8",
        accent="#C4923A",
        text_secondary="#A89F91",
    )
    design = DesignDirectionSpec(
        mood=PresentationMood.WARM_HISTORICAL,
        palette=palette,
        heading_font="Playfair Display",
        body_font="EB Garamond",
        image_style_prefix="period oil painting, no text in image, ",
        background_treatment=BackgroundTreatment.DARK,
    )
    plan = DeckPlan(
        thesis="The deck makes one specific, concrete argument grounded in the source.",
        audience_takeaway="The audience leaves able to state the core argument and its support.",
        sections=[
            PlannedSection(
                section_name="Origins",
                thesis="The movement began as a specific reaction to a concrete cause.",
                phase=NarrativePhase.HOOK,
            ),
            PlannedSection(
                section_name="Legacy",
                thesis="Its ideas reshaped institutions that still stand today.",
                phase=NarrativePhase.CLOSE,
            ),
        ],
        image_cohesion_note="A single coherent visual treatment shared across every slide.",
    )
    slides = [
        SlideSpec(
            slide_index=0,
            slide_type=SlideType.TITLE_HERO,
            content=SlideContent(title="Opening"),
        ),
        SlideSpec(
            slide_index=1,
            slide_type=SlideType.SECTION_BREAK,
            content=SlideContent(title="A section divider"),
        ),
    ]
    return DeckSpec(
        project_id="proj-1",
        title=title,
        design=design,
        interview=PresentationInterviewAnswers(audience=audience),
        plan=plan,
        slides=slides,
    )


def _seed_project(
    fake: FakeSupabaseClient,
    *,
    project_id: str = "proj-1",
    title: str = "Project row title",
    language: str = "uz",
    audience: str = "talaba",
) -> None:
    fake.seed(
        "projects",
        [
            {
                "id": project_id,
                "user_id": "u1",
                "type": "presentation",
                "title": title,
                "language": language,
                "audience": audience,
            }
        ],
    )


async def test_save_deck_sources_denormalised_columns_from_project() -> None:
    db, fake = _make_db()
    # All THREE denormalised columns are seeded to differ from the deck's own
    # value, so a regression that reads any of them from the spec fails here.
    # The deck's language is the uz default, so the project's ru can only come
    # from the project row; its 300-char title and undergraduate audience would
    # each violate a decks CHECK if they ever reached a column.
    _seed_project(fake, title="Project row title", language="ru", audience="talaba")
    deck = _make_deck(title="A" * 300, audience=AudienceType.UNDERGRADUATE)

    saved = await db.save_deck("proj-1", deck)

    assert saved["project_id"] == "proj-1"
    assert saved["title"] == "Project row title"  # project, not the 300-char deck title
    assert saved["language"] == "ru"  # project ru, not the deck's default uz
    assert saved["audience"] == "talaba"  # NOT "undergraduate" (AudienceType has no DB mapping)


async def test_save_deck_round_trips_spec_through_deck_json() -> None:
    db, fake = _make_db()
    _seed_project(fake)
    deck = _make_deck(title="A" * 300, audience=AudienceType.UNDERGRADUATE)

    await db.save_deck("proj-1", deck)
    row = await db.get_deck("proj-1")

    assert row is not None
    restored = DeckSpec.model_validate(row["deck_json"])
    # The spec's own values survive intact inside deck_json, distinct from the
    # denormalised columns sourced from the project.
    assert restored == deck
    assert restored.title == "A" * 300
    assert restored.interview.audience is AudienceType.UNDERGRADUATE
    assert restored.plan is not None
    assert [s.section_name for s in restored.plan.sections] == ["Origins", "Legacy"]
    assert [s.slide_id for s in restored.slides] == [s.slide_id for s in deck.slides]


async def test_save_deck_upserts_one_row_per_project() -> None:
    db, fake = _make_db()
    _seed_project(fake)

    await db.save_deck(
        "proj-1", _make_deck(title="First generation", audience=AudienceType.UNDERGRADUATE)
    )
    await db.save_deck(
        "proj-1", _make_deck(title="Second generation", audience=AudienceType.GRADUATE)
    )

    # Current-state, not history: the second save updates the same row in place.
    assert len(fake.tables["decks"]) == 1
    row = await db.get_deck("proj-1")
    assert row is not None
    assert DeckSpec.model_validate(row["deck_json"]).title == "Second generation"


async def test_save_deck_raises_when_project_missing() -> None:
    db, _ = _make_db()
    with pytest.raises(ValueError):
        await db.save_deck("ghost", _make_deck(title="x", audience=AudienceType.UNDERGRADUATE))


async def test_get_deck_returns_none_when_absent() -> None:
    db, _ = _make_db()
    assert await db.get_deck("no-such-project") is None


if __name__ == "__main__":
    asyncio.run(test_create_user_generates_subscriber_id_and_inserts())
