"""Export publishing: content-addressed keys, claim fencing, first writer wins."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest

from packages.platform.config import PlatformConfig
from packages.platform.database import DatabaseClient
from packages.platform.document_models import DocumentStoreError, ExportFileFormat
from packages.platform.document_store import DocumentStore
from packages.platform.exports import ExportPublisher, file_format, renderer_version
from tests.unit.fake_documents import DocumentRpcEmulator, seed_presentation
from tests.unit.test_database_client import FakeSupabaseClient

pytestmark = pytest.mark.asyncio

_JOB = "aaaaaaaa-0000-4000-8000-000000000001"


class _Storage:
    def __init__(self) -> None:
        self.uploads: list[str] = []

    async def put_verified(self, path: Path, key: str, sha256: str, size: int) -> None:
        self.uploads.append(key)


class _World:
    def __init__(self, tmp_path: Path) -> None:
        self.fake = FakeSupabaseClient()
        self.fake.seed("projects", [{"id": "p1", "user_id": "u1"}])
        cfg = PlatformConfig(
            supabase_url="https://x.supabase.co", supabase_service_key="k", telegram_bot_token="t"
        )
        self.store = DocumentStore(DatabaseClient(cfg, client=cast(Any, self.fake)))
        self.storage = _Storage()
        self.publisher = ExportPublisher(self.store, cast(Any, self.storage))
        self.document_id, self.revision_id = seed_presentation(
            self.fake.tables, project_id="p1", content={"title": "one"}
        )
        self.html = tmp_path / "deck.html"
        self.html.write_text("<h1>one</h1>", encoding="utf-8")

    def job(
        self,
        *,
        worker: str | None = "w1",
        status: str = "processing",
        payload: dict[str, Any] | None = None,
    ) -> None:
        self.fake.tables["generation_jobs"] = [
            {
                "id": _JOB,
                "project_id": "p1",
                "user_id": "u1",
                "job_type": "presentation_render",
                "worker_id": worker,
                "status": status,
                "attempts": 1,
                "payload": payload
                if payload is not None
                else {
                    "revision_id": self.revision_id,
                    "renderer_version": renderer_version(),
                    "formats": ["html"],
                },
            }
        ]

    async def publish(self, revision_id: str | None = None, *, worker: str = "w1") -> Any:
        return await self.publisher.publish(
            job_id=_JOB,
            worker_id=worker,
            claim_token=1,
            document_id=self.document_id,
            revision_id=revision_id or self.revision_id,
            files={ExportFileFormat.HTML: self.html},
        )


async def test_publish_uploads_to_the_content_addressed_key_and_registers(
    tmp_path: Path,
) -> None:
    world = _World(tmp_path)
    world.job()

    published = await world.publish()

    key = published[0].storage_key
    assert key.startswith(f"exports/{world.document_id}/{world.revision_id}/{renderer_version()}/")
    assert key.endswith(f"/html/{published[0].sha256}.html")
    assert world.storage.uploads == [key]
    assert published[0].newly_registered is True and published[0].orphaned_upload is None
    assert world.fake.tables["revision_exports"][0]["storage_key"] == key


async def test_a_registered_format_is_reused_not_uploaded_again(tmp_path: Path) -> None:
    # A retry or recovery render after the first registration: even different
    # bytes (PPTX carries timestamps) never replace the export or re-upload.
    world = _World(tmp_path)
    world.job()
    first = await world.publish()
    world.html.write_text("<h1>changed</h1>", encoding="utf-8")

    again = await world.publish()

    assert again[0].newly_registered is False
    assert again[0].storage_key == first[0].storage_key
    assert world.storage.uploads == [first[0].storage_key]
    rows = world.fake.tables["revision_exports"]
    assert len(rows) == 1 and rows[0]["sha256"] == first[0].sha256


async def test_losing_a_registration_race_returns_the_first_export_and_names_the_orphan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = _World(tmp_path)
    world.job()
    first = await world.publish()
    world.html.write_text("<h1>rendered again</h1>", encoding="utf-8")

    async def nothing_registered_yet(*_args: Any, **_kwargs: Any) -> dict[Any, Any]:
        return {}  # the other render registered between our check and our call

    monkeypatch.setattr(world.publisher, "registered_formats", nothing_registered_yet)
    raced = await world.publish()

    assert raced[0].newly_registered is False
    assert raced[0].storage_key == first[0].storage_key
    assert raced[0].orphaned_upload is not None
    assert raced[0].orphaned_upload != first[0].storage_key
    assert world.storage.uploads == [first[0].storage_key, raced[0].orphaned_upload]
    assert len(world.fake.tables["revision_exports"]) == 1


async def test_a_worker_that_lost_its_claim_cannot_register(tmp_path: Path) -> None:
    # (f) the job was reaped and re-claimed by another worker
    world = _World(tmp_path)
    world.job(worker="someone-else")

    with pytest.raises(DocumentStoreError) as info:
        await world.publish(worker="w1")

    assert info.value.code == "claim_lost"
    assert world.fake.tables.get("revision_exports", []) == []


async def test_a_job_without_a_worker_cannot_register(tmp_path: Path) -> None:
    # SQL NULL never equals anything: a claimless job does not match a caller
    # that also sends no worker.
    world = _World(tmp_path)
    world.job(worker=None)

    with pytest.raises(DocumentStoreError) as info:
        await world.publisher.publish(
            job_id=_JOB,
            worker_id=cast(Any, None),
            claim_token=1,
            document_id=world.document_id,
            revision_id=world.revision_id,
            files={ExportFileFormat.HTML: world.html},
        )

    assert info.value.code == "claim_lost"


async def test_a_finished_job_cannot_register(tmp_path: Path) -> None:
    world = _World(tmp_path)
    world.job(status="completed")

    with pytest.raises(DocumentStoreError) as info:
        await world.publish()

    assert info.value.code == "claim_lost"


@pytest.mark.parametrize(
    "target",
    [{}, {"revision_id": None}],
    ids=["absent target", "JSON-null target"],
)
async def test_a_render_job_without_a_target_cannot_register(
    tmp_path: Path, target: dict[str, Any]
) -> None:
    world = _World(tmp_path)
    world.job(payload={**target, "renderer_version": renderer_version(), "formats": ["html"]})

    with pytest.raises(DocumentStoreError) as info:
        await world.publish()

    assert info.value.code == "job_revision_mismatch"
    assert world.fake.tables.get("revision_exports", []) == []


async def test_a_job_for_revision_x_cannot_register_revision_y(tmp_path: Path) -> None:
    # (g) the job targets the first revision; a second revision exists
    world = _World(tmp_path)
    second = DocumentRpcEmulator(world.fake.tables).commit_revision(
        {
            "p_document_id": world.document_id,
            "p_base_revision_id": world.revision_id,
            "p_content": {"title": "two"},
            "p_kind": "import",
            "p_schema_version": 1,
            "p_actor": "system:migration-016",
            "p_idempotency_key": "second",
        }
    )[0]["revision_id"]
    world.job()

    with pytest.raises(DocumentStoreError) as info:
        await world.publish(second)

    assert info.value.code == "job_revision_mismatch"
    assert world.fake.tables.get("revision_exports", []) == []


def test_file_format_maps_renderer_extensions() -> None:
    assert file_format("html") is ExportFileFormat.HTML
    assert file_format(".PPTX") is ExportFileFormat.PPTX
    # "zip" is the stored extension of the png export, not a format name, so the
    # helper (which maps a renderer output's format name) refuses it.
    with pytest.raises(ValueError):
        file_format("zip")


def test_renderer_version_is_a_stable_source_hash() -> None:
    version = renderer_version()
    assert version.startswith("pw-") and len(version) == 19
    assert renderer_version() == version
