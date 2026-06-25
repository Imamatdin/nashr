"""Live droplet gate for Build 2, Stage 0 — deck persistence.

Run against the REAL Supabase (with migration 003 applied) to prove the
guarantees the unit suite structurally cannot, because ``FakeSupabaseClient``
models neither the ``decks_project_id_key`` UNIQUE constraint nor the
``trg_decks_updated_at`` trigger:

  1. save_deck inserts exactly ONE deck row for a project, and get_deck
     reloads a DeckSpec equal to the one persisted (real jsonb round-trip).
  2. A SECOND save_deck for the same project UPDATES that row in place
     (still one row) rather than appending history.
  3. The update advances ``updated_at`` (trigger) while leaving ``created_at``
     untouched — the on-conflict-DO-UPDATE path behaving as designed.

The behaviour under test goes through the public DatabaseClient API
(create_user / create_project / save_deck / get_deck); a separate raw Supabase
client is used only for test scaffolding (counting rows, cleanup) the public
API does not expose.

Usage (on the droplet, after `supabase db push` has applied migration 003):

    SUPABASE_URL=... SUPABASE_SERVICE_KEY=... python scripts/gate_build2_stage0.py

Creates a throwaway user + project, runs the checks, and deletes the user
(cascading to the project and its deck) so the gate leaves no residue. Exits
0 on PASS, 1 on any failed check or setup error.
"""

from __future__ import annotations

import asyncio
import random
import sys
from datetime import datetime
from typing import Any

from packages.core.enums import (
    BackgroundTreatment,
    PresentationMood,
    SlideType,
)
from packages.core.models.presentation import (
    ColorPalette,
    DeckSpec,
    DesignDirectionSpec,
    PresentationInterviewAnswers,
    SlideContent,
    SlideSpec,
)
from packages.platform.config import PlatformConfig
from packages.platform.database import DatabaseClient
from supabase import Client, create_client

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


async def _count_deck_rows(raw: Client, project_id: str) -> int:
    """Count every deck row for a project (not just the current one)."""

    result = await asyncio.to_thread(
        lambda: raw.table("decks").select("id").eq("project_id", project_id).execute()
    )
    return len(list(result.data))


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
    """Run the three persistence checks against ``project_id``."""

    deck_v1 = _build_deck(project_id, "Gate deck v1", slide_count=3)
    await db.save_deck(project_id, deck_v1)

    reporter.check("one row after first save", await _count_deck_rows(raw, project_id) == 1)
    row1 = await db.get_deck(project_id)
    if row1 is None:
        reporter.check("get_deck returns the persisted row", False, "got None")
        return
    restored1 = DeckSpec.model_validate(row1["deck_json"])
    reporter.check("reloaded DeckSpec round-trips equal", restored1 == deck_v1)
    created_at_1 = str(row1["created_at"])
    updated_at_1 = str(row1["updated_at"])

    # A visible wall-clock gap so the trigger's updated_at is unambiguously
    # later than the original created_at when we re-save below.
    await asyncio.sleep(1.1)

    deck_v2 = _build_deck(project_id, "Gate deck v2 EDITED", slide_count=4)
    await db.save_deck(project_id, deck_v2)

    reporter.check("still one row after second save", await _count_deck_rows(raw, project_id) == 1)
    row2 = await db.get_deck(project_id)
    if row2 is None:
        reporter.check("get_deck returns the updated row", False, "got None")
        return
    restored2 = DeckSpec.model_validate(row2["deck_json"])
    reporter.check("update replaced deck_json", restored2 == deck_v2)
    reporter.check(
        "created_at unchanged across update",
        str(row2["created_at"]) == created_at_1,
        f"{created_at_1} -> {row2['created_at']}",
    )
    reporter.check(
        "updated_at advanced (trg_decks_updated_at fired)",
        datetime.fromisoformat(str(row2["updated_at"])) > datetime.fromisoformat(updated_at_1),
        f"{updated_at_1} -> {row2['updated_at']}",
    )


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
            title="Build2 Stage0 gate",
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
    print("\nGATE PASSED: one current deck row per project, trigger-maintained updated_at.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
