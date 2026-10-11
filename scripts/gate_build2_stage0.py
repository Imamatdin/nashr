"""Live gate for canonical deck state (ADR 0001, migration 016).

Originally the Build 2 Stage 0 gate for the single mutable ``decks`` row. That
contract is retired: ``decks`` is now a view of the presentation document's head
revision. Run against a Supabase project WITH migration 016 applied to prove,
on real PostgreSQL + PostgREST, what the unit fakes cannot:

  1. A committed revision becomes the head, and the ``decks`` view returns
     exactly its content and revision id.
  2. A second commit on that base advances the head; the view follows.
  3. A commit on a stale base conflicts and changes nothing.
  4. Committing content identical to the head is a no-op (``unchanged``).
  5. A direct INSERT into ``decks`` is refused, even with the service key.

Usage:

    SUPABASE_URL=... SUPABASE_SERVICE_KEY=... python scripts/gate_build2_stage0.py

Creates a throwaway user + project, runs the checks, deletes the user (cascading
to the project and its document), and exits 0 on PASS, 1 otherwise.
"""

from __future__ import annotations

import asyncio
import random
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from postgrest.exceptions import APIError  # noqa: E402

from packages.core.enums import (  # noqa: E402
    BackgroundTreatment,
    PresentationMood,
    SlideType,
)
from packages.core.models.presentation import (  # noqa: E402
    ColorPalette,
    DeckSpec,
    DesignDirectionSpec,
    PresentationInterviewAnswers,
    SlideContent,
    SlideSpec,
)
from packages.platform.config import PlatformConfig  # noqa: E402
from packages.platform.database import DatabaseClient  # noqa: E402
from packages.platform.document_models import (  # noqa: E402
    CommitStatus,
    DocumentKind,
    RevisionKind,
    user_actor,
)
from packages.platform.document_store import DocumentStore  # noqa: E402
from scripts._gate_documents import seed_deck_revision  # noqa: E402
from supabase import Client, create_client  # noqa: E402

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # python-dotenv is optional; env may be exported directly.
    pass


def _build_deck(project_id: str, title: str, slide_count: int) -> DeckSpec:
    """Construct a valid DeckSpec with ``slide_count`` slides for the gate."""

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
    slides = [
        SlideSpec(
            slide_index=i,
            slide_type=SlideType.TITLE_HERO if i == 0 else SlideType.CONTENT_SPLIT,
            content=SlideContent(title=f"Slide {i}"),
        )
        for i in range(slide_count)
    ]
    return DeckSpec(
        project_id=project_id,
        title=title,
        design=design,
        interview=PresentationInterviewAnswers(),
        slides=slides,
    )


class _GateReporter:
    """Collects pass/fail checks so every assertion runs and is reported."""

    def __init__(self) -> None:
        self.failures = 0

    def check(self, label: str, ok: bool, detail: str = "") -> None:
        mark = "PASS" if ok else "FAIL"
        suffix = f" — {detail}" if detail else ""
        print(f"  [{mark}] {label}{suffix}")
        if not ok:
            self.failures += 1


async def _run_gate(
    db: DatabaseClient, raw: Client, project_id: str, reporter: _GateReporter
) -> None:
    """Run the canonical-state checks against ``project_id``."""

    store = DocumentStore(db)
    deck_v1 = _build_deck(project_id, "Gate deck v1", slide_count=3)
    rev1 = await seed_deck_revision(db, project_id, deck_v1)
    head = await store.head(project_id, DocumentKind.PRESENTATION)
    reporter.check("first commit is the head", head is not None and head.revision_id == rev1)
    row1 = await db.get_deck(project_id)
    reporter.check(
        "decks view returns the head",
        row1 is not None
        and str(row1["revision_id"]) == rev1
        and DeckSpec.model_validate(row1["deck_json"]) == deck_v1,
    )

    deck_v2 = _build_deck(project_id, "Gate deck v2 EDITED", slide_count=4)
    rev2 = await seed_deck_revision(db, project_id, deck_v2)
    row2 = await db.get_deck(project_id)
    reporter.check(
        "second commit advances the head and the view",
        row2 is not None
        and str(row2["revision_id"]) == rev2
        and DeckSpec.model_validate(row2["deck_json"]) == deck_v2,
    )

    document_id = await store.document_id(project_id, DocumentKind.PRESENTATION)
    assert document_id is not None
    actor = user_actor(str((await db.get_project(project_id) or {})["user_id"]))
    stale = await store.commit(
        document_id,
        rev1,
        _build_deck(project_id, "Gate deck stale", slide_count=2).model_dump(mode="json"),
        kind=RevisionKind.MANUAL,
        actor=actor,
        idempotency_key="gate0-stale",
    )
    row3 = await db.get_deck(project_id)
    reporter.check(
        "stale base conflicts and changes nothing",
        stale.status is CommitStatus.CONFLICT
        and stale.head_revision_id == rev2
        and row3 is not None
        and str(row3["revision_id"]) == rev2,
        f"status={stale.status.value}",
    )

    same = await store.commit(
        document_id,
        rev2,
        deck_v2.model_dump(mode="json"),
        kind=RevisionKind.AUTOSAVE,
        actor=actor,
        idempotency_key="gate0-same",
    )
    reporter.check(
        "identical content is unchanged",
        same.status is CommitStatus.UNCHANGED and same.revision_id == rev2,
        f"status={same.status.value}",
    )

    try:
        await asyncio.to_thread(
            lambda: (
                raw.table("decks")
                .insert(
                    {
                        "project_id": project_id,
                        "title": "forged",
                        "language": "uz",
                        "audience": "talaba",
                        "deck_json": {},
                    }
                )
                .execute()
            )
        )
        reporter.check("direct INSERT into decks is refused", False, "insert succeeded")
    except APIError as exc:
        reporter.check("direct INSERT into decks is refused", True, str(exc.code))


async def _cleanup(raw: Client, user_id: str) -> None:
    """Delete the throwaway user; FK cascades remove the project and its deck."""

    await asyncio.to_thread(lambda: raw.table("users").delete().eq("id", user_id).execute())


async def main() -> int:
    """Provision a throwaway user+project, run the gate, clean up, report."""

    config = PlatformConfig.from_env()
    if not config.supabase_url or not config.supabase_service_key:
        print("ERROR: SUPABASE_URL and SUPABASE_SERVICE_KEY must be set.", file=sys.stderr)
        return 1

    db = DatabaseClient(config)
    raw = create_client(config.supabase_url, config.supabase_service_key)
    reporter = _GateReporter()
    user: dict[str, Any] | None = None
    try:
        user = await db.create_user(telegram_id=random.randint(10_000_000, 2_000_000_000))
        project = await db.create_project(
            user_id=user["id"],
            title="Canonical deck state gate",
            project_type="presentation",
            language="uz",
            audience="talaba",
        )
        print(f"Gate project: {project['id']}")
        await _run_gate(db, raw, project["id"], reporter)
    finally:
        if user is not None:
            await _cleanup(raw, user["id"])
            print("Cleaned up throwaway user + cascaded project/deck.")

    if reporter.failures:
        print(f"\nGATE FAILED: {reporter.failures} check(s) failed.")
        return 1
    print("\nGATE PASSED: decks is the head revision; stale and forged writes are refused.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
