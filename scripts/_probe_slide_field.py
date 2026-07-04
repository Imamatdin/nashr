"""Forensic: print one slide field subset by slide_index."""

from __future__ import annotations

import asyncio
import json
import sys

from packages.core.models.presentation import DeckSpec
from packages.platform.config import PlatformConfig
from packages.platform.database import DatabaseClient


async def main(project_id: str, target: str) -> None:
    """Load deck; dump one slide or list all non-null captions."""

    db = DatabaseClient(PlatformConfig.from_env())
    row = await db.get_deck(project_id)
    if row is None:
        print("NO DECK")
        return
    deck = DeckSpec.model_validate(row["deck_json"])
    if target == "captions":
        for s in deck.slides:
            if s.content.caption:
                print(
                    json.dumps(
                        {"slide_index": s.slide_index, "slide_id": s.slide_id, "caption": s.content.caption},
                        ensure_ascii=False,
                    )
                )
        return
    if target.isdigit():
        slide = next((s for s in deck.slides if s.slide_index == int(target)), None)
    else:
        slide = next((s for s in deck.slides if s.slide_id == target), None)
    if slide is None:
        print(f"NO SLIDE target={target}")
        return
    print(
        json.dumps(
            {
                "slide_id": slide.slide_id,
                "slide_index": slide.slide_index,
                "slide_type": slide.slide_type.value,
                "title": slide.content.title,
                "caption": slide.content.caption,
                "body_text": slide.content.body_text,
                "bullets": slide.content.bullets,
            },
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], sys.argv[2]))
