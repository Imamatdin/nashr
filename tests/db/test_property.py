"""Random interleavings of 2–6 writers on real PostgreSQL (test n).

Each writer holds the revision it last read as its base. A step either
refreshes a writer's base from the head or commits as that writer with its
kind. Invariants checked after every step:

* the head is the last committed revision;
* no committed revision is ever lost (every one is still stored);
* every losing ai_edit / regeneration write exists as a proposal;
* the decks view equals the head content.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

pytest.importorskip("hypothesis", reason="hypothesis runs in the CI database job")

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from tests.db.conftest import CURRENT
from tests.db.support import Db, commit, ensure_document, head

pytestmark = pytest.mark.skipif(
    not CURRENT, reason="exercises migration 016's functions (current schema only)"
)

KINDS = ["manual", "autosave", "ai_edit", "regeneration", "bot_edit", "restore"]
PROPOSING = {"ai_edit", "regeneration"}


@st.composite
def plans(draw: Any) -> tuple[list[str], list[tuple[int, str]]]:
    writers = draw(st.lists(st.sampled_from(KINDS), min_size=2, max_size=6))
    steps = draw(
        st.lists(
            st.tuples(st.integers(0, len(writers) - 1), st.sampled_from(["refresh", "commit"])),
            min_size=40,
            max_size=60,
        )
    )
    return writers, steps


def _actor(kind: str, owner: str, job: str, telegram: int) -> str:
    if kind in ("manual", "autosave", "restore"):
        return owner
    if kind == "bot_edit":
        return f"bot:{telegram}"
    return f"worker:{job}"


@settings(
    max_examples=6,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow],
)
@given(plan=plans())
async def test_n_interleaved_writers_never_lose_work(
    db: Db, plan: tuple[list[str], list[tuple[int, str]]]
) -> None:
    writers, steps = plan
    owner = await db.user()  # a fresh Telegram id per example
    admin = await db.admin()
    project = await db.project(owner)
    job = await db.job(project, owner, job_type="presentation_edit")
    conn = await db.as_role("service_role")
    telegram = await admin.fetchval("select telegram_id from users where id = $1", uuid.UUID(owner))
    document = await ensure_document(conn, project, owner)
    first = await commit(conn, document, None, {"step": -1}, kind="manual", actor=owner, key="seed")

    model_head = str(first["revision_id"])
    committed = [model_head]
    proposals: list[str] = []
    bases = [model_head for _ in writers]

    for index, (writer, action) in enumerate(steps):
        if action == "refresh":
            bases[writer] = model_head
            continue
        kind = writers[writer]
        actor = _actor(kind, owner, job, telegram)
        result = await commit(
            conn,
            document,
            bases[writer],
            {"step": index, "writer": writer},
            kind=kind,
            actor=actor,
            key=f"op-{index}",
        )
        if bases[writer] == model_head:
            assert result["status"] == "committed", (index, result)
            model_head = str(result["revision_id"])
            committed.append(model_head)
            bases[writer] = model_head
        elif kind in PROPOSING:
            assert result["status"] == "proposed", (index, result)
            proposals.append(f"op-{index}")
        else:
            assert result["status"] == "conflict", (index, result)

        assert await head(conn, document) == model_head
        stored = await conn.fetchval(
            "select count(*) from document_revisions where id = any($1::uuid[])",
            [uuid.UUID(r) for r in committed],
        )
        assert stored == len(committed)
        keys = {
            row["idempotency_key"]
            for row in await conn.fetch(
                "select idempotency_key from revision_proposals where document_id = $1",
                uuid.UUID(document),
            )
        }
        assert keys == set(proposals)
        view = await conn.fetchval(
            "select deck_json from decks where project_id = $1", uuid.UUID(project)
        )
        content = await conn.fetchval(
            "select content from document_revisions where id = $1", uuid.UUID(model_head)
        )
        assert view == content
