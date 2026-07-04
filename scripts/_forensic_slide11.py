"""Forensic dump: slide 11 full JSON + substring search for probe 9330c308."""

from __future__ import annotations

import asyncio
import json
import sys

from packages.core.models.presentation import DeckSpec
from packages.platform.config import PlatformConfig
from packages.platform.database import DatabaseClient

TARGET_SLIDE = "f5cb85e8-b49b-425c-8bbd-053b1755f2b0"
PROJECT = "9330c308-6e78-4a73-8ed0-6aa2d8f790b2"


def _search_44(obj: object, path: str = "") -> list[str]:
    """Return JSON paths where '44' appears in string values."""

    hits: list[str] = []
    if isinstance(obj, dict):
        for key, val in obj.items():
            hits.extend(_search_44(val, f"{path}.{key}" if path else str(key)))
    elif isinstance(obj, list):
        for i, val in enumerate(obj):
            hits.extend(_search_44(val, f"{path}[{i}]"))
    elif isinstance(obj, str) and "44" in obj:
        hits.append(f"{path}: {obj[:200]!r}")
    return hits


async def main() -> None:
    """Dump slide 11 and report any field containing '44'."""

    db = DatabaseClient(PlatformConfig.from_env())
    row = await db.get_deck(PROJECT)
    if row is None:
        print("NO DECK")
        return
    deck = DeckSpec.model_validate(row["deck_json"])
    slide = next((s for s in deck.slides if s.slide_id == TARGET_SLIDE), None)
    if slide is None:
        print("SLIDE NOT FOUND")
        return
    payload = slide.model_dump(mode="json")
    print("=== FULL SLIDE JSON ===")
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    print("\n=== '44' SUBSTRING HITS ===")
    hits = _search_44(payload)
    if hits:
        for h in hits:
            print(h)
    else:
        print("(none)")


if __name__ == "__main__":
    asyncio.run(main())
