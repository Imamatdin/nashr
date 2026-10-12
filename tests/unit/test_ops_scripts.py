"""The orphan-export sweep and the legacy-import validation backfill (ADR 0001)."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pytest

from packages.core.enums import AudienceType
from packages.platform.config import PlatformConfig
from packages.platform.database import DatabaseClient
from packages.platform.storage import FileStorage, StoredObject
from scripts.backfill_validate_revisions import backfill
from scripts.gc_orphan_exports import find_orphans, sweep
from tests.unit.fake_documents import seed_presentation
from tests.unit.test_database_client import FakeSupabaseClient, _make_deck

pytestmark = pytest.mark.asyncio

_NOW = datetime(2026, 10, 11, tzinfo=UTC)


def _config() -> PlatformConfig:
    return PlatformConfig(
        supabase_url="https://x.supabase.co", supabase_service_key="k", telegram_bot_token="t"
    )


def _obj(key: str, hours_old: float) -> StoredObject:
    return StoredObject(
        key=key, size=1, sha256_b64=None, last_modified=_NOW - timedelta(hours=hours_old)
    )


@pytest.fixture(autouse=True)
def _isolate_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    return tmp_path


def test_orphans_are_unregistered_old_export_objects_only() -> None:
    objects = [
        _obj("exports/d/r/v/html/registered.html", 48),
        _obj("exports/d/r/v/html/orphan.html", 48),
        _obj("exports/d/r/v/html/young.html", 1),
        _obj("uploads/u/1/source.pdf", 48),
    ]

    orphans = find_orphans(
        objects,
        {"exports/d/r/v/html/registered.html"},
        now=_NOW,
        min_age=timedelta(hours=24),
    )

    assert [item.key for item in orphans] == ["exports/d/r/v/html/orphan.html"]


def _put(home: Path, key: str, hours_old: float) -> None:
    path = home / ".nashr" / "storage" / key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x")
    stamp = (datetime.now(UTC) - timedelta(hours=hours_old)).timestamp()
    os.utime(path, (stamp, stamp))


async def test_sweep_lists_by_default_and_deletes_only_with_the_flag(_isolate_home: Path) -> None:
    # (m) a project deleted mid-render leaves an uploaded but unregistered export:
    # its row cascaded away, its bytes did not. The sweep finds it.
    fake = FakeSupabaseClient()
    fake.seed("revision_exports", [{"storage_key": "exports/d/r/v/html/kept.html"}])
    db = DatabaseClient(_config(), client=cast(Any, fake))
    storage = FileStorage(_config())
    _put(_isolate_home, "exports/d/r/v/html/kept.html", 48)
    _put(_isolate_home, "exports/gone/r/v/html/orphan.html", 48)

    listed = await sweep(db, storage, min_age=timedelta(hours=24), delete=False)

    assert listed == {"objects": 2, "registered": 1, "orphans": 1, "deleted": 0}
    assert await storage.exists("exports/gone/r/v/html/orphan.html")

    deleted = await sweep(db, storage, min_age=timedelta(hours=24), delete=True)

    assert deleted["deleted"] == 1
    assert not await storage.exists("exports/gone/r/v/html/orphan.html")
    assert await storage.exists("exports/d/r/v/html/kept.html")


async def test_validation_backfill_flags_invalid_imports_and_resumes() -> None:
    fake = FakeSupabaseClient()
    fake.seed("projects", [{"id": "p1", "user_id": "u1"}, {"id": "p2", "user_id": "u1"}])
    deck = _make_deck(title="Valid", audience=AudienceType.UNDERGRADUATE)
    _d1, valid = seed_presentation(
        fake.tables, project_id="p1", content=deck.model_dump(mode="json")
    )
    _d2, invalid = seed_presentation(fake.tables, project_id="p2", content={"legacy_raw": [1, 2]})
    db = DatabaseClient(_config(), client=cast(Any, fake))

    no_proposals = {
        "proposals_scanned": 0,
        "proposals_already_validated": 0,
        "proposals_valid": 0,
        "proposals_legacy_invalid": 0,
    }
    dry = await backfill(db, apply=False)
    assert dry == {
        "scanned": 2,
        "already_validated": 0,
        "valid": 1,
        "legacy_invalid": 1,
        **no_proposals,
    }
    assert fake.tables.get("revision_validations", []) == []

    applied = await backfill(db, apply=True)
    verdicts = {row["revision_id"]: row["status"] for row in fake.tables["revision_validations"]}
    assert applied["legacy_invalid"] == 1
    assert verdicts == {valid: "valid", invalid: "legacy_invalid"}

    again = await backfill(db, apply=True)
    assert again == {
        "scanned": 2,
        "already_validated": 2,
        "valid": 0,
        "legacy_invalid": 0,
        **no_proposals,
    }
    assert len(fake.tables["revision_validations"]) == 2


async def test_validation_backfill_also_judges_pending_import_proposals() -> None:
    # A divergent legacy deck became a pending import proposal: it gets a verdict
    # before the owner is asked to accept it; resolved proposals are skipped.
    fake = FakeSupabaseClient()
    fake.seed("projects", [{"id": "p1", "user_id": "u1"}])
    document, _head = seed_presentation(
        fake.tables,
        project_id="p1",
        content=_make_deck(title="Head", audience=AudienceType.UNDERGRADUATE).model_dump(
            mode="json"
        ),
    )
    base = {"document_id": document, "kind": "import", "content_sha256": "0" * 64}
    fake.seed(
        "revision_proposals",
        [
            {
                **base,
                "id": "00000000-0000-4000-8000-000000000001",
                "status": "pending",
                "content": {"legacy_raw": "broken"},
            },
            {
                **base,
                "id": "00000000-0000-4000-8000-000000000002",
                "status": "rejected",
                "content": {"legacy_raw": "old"},
            },
        ],
    )
    db = DatabaseClient(_config(), client=cast(Any, fake))

    counts = await backfill(db, apply=True)

    assert counts["proposals_scanned"] == 1 and counts["proposals_legacy_invalid"] == 1
    assert [(r["proposal_id"], r["status"]) for r in fake.tables["proposal_validations"]] == [
        ("00000000-0000-4000-8000-000000000001", "legacy_invalid")
    ]
    again = await backfill(db, apply=True)
    assert again["proposals_already_validated"] == 1
    assert len(fake.tables["proposal_validations"]) == 1
