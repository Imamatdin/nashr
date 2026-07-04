"""One-off: print slides containing 40% or 44% for a project_id. Gate/probe use only."""

from __future__ import annotations

import asyncio
import json
import sys

from packages.core.models.presentation import DeckSpec
from packages.platform.config import PlatformConfig
from packages.platform.database import DatabaseClient


async def main(project_id: str) -> None:
    """Load deck and print slides mentioning 40 or 44 percent."""

    db = DatabaseClient(PlatformConfig.from_env())
    row = await db.get_deck(project_id)
    if row is None:
        print("NO DECK")
        return
    deck = DeckSpec.model_validate(row["deck_json"])
    target_id = "f5cb85e8-b49b-425c-8bbd-053b1755f2b0"
    for slide in deck.slides:
        if slide.slide_id == target_id:
            print(
                json.dumps(
                    {
                        "slide_index": slide.slide_index,
                        "slide_id": slide.slide_id,
                        "title": slide.content.title,
                        "body_text": slide.content.body_text,
                        "bullets": slide.content.bullets,
                    },
                    indent=2,
                    ensure_ascii=False,
                )
            )
            return
    # fallback: any slide with PUE / percent / improvement
    hits: list[dict[str, object]] = []
    for slide in deck.slides:
        parts = [
            slide.content.title or "",
            slide.content.subtitle or "",
            slide.content.body_text or "",
            " ".join(slide.content.bullets or []),
        ]
        blob = " ".join(parts).lower()
        if any(k in blob for k in ("44", "40", "pue", "improvement", "percent", "%")):
            hits.append(
                {
                    "slide_index": slide.slide_index,
                    "slide_id": slide.slide_id,
                    "title": slide.content.title,
                    "body_text": (slide.content.body_text or "")[:500],
                    "bullets": slide.content.bullets,
                }
            )
    print(json.dumps(hits, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
