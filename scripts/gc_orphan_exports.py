"""List (and optionally delete) export objects that no revision_exports row references.

An export is uploaded before ``register_export`` accepts it (ADR 0001), so a
worker that lost its claim, or a project deleted mid-render, can leave bytes in
``exports/`` that nothing points at. This sweep finds them. It only considers
objects older than ``--min-age-hours`` (default 24), so an upload that is about
to be registered is never touched. Dry-run by default; ``--delete`` removes.

    python scripts/gc_orphan_exports.py              # list orphans
    python scripts/gc_orphan_exports.py --delete     # delete them
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from packages.platform.config import PlatformConfig
from packages.platform.database import DatabaseClient
from packages.platform.storage import FileStorage, StoredObject

EXPORT_PREFIX = "exports/"
_BATCH = 200


def find_orphans(
    objects: Iterable[StoredObject],
    registered: set[str],
    *,
    now: datetime,
    min_age: timedelta,
) -> list[StoredObject]:
    """Objects under ``exports/`` older than ``min_age`` that no row references."""

    cutoff = now - min_age
    return [
        item
        for item in objects
        if item.key.startswith(EXPORT_PREFIX)
        and item.key not in registered
        and item.last_modified <= cutoff
    ]


async def registered_keys(db: DatabaseClient, keys: list[str]) -> set[str]:
    """Which of ``keys`` a revision_exports row references (batched lookups)."""

    found: set[str] = set()
    for start in range(0, len(keys), _BATCH):
        batch = keys[start : start + _BATCH]

        def run(batch: list[str] = batch) -> Any:
            return (
                db._query("revision_exports")  # pyright: ignore[reportPrivateUsage]
                .select("storage_key")
                .in_("storage_key", batch)
                .execute()
            )

        result = await asyncio.to_thread(run)
        rows = cast(list[dict[str, Any]], list(result.data or []))
        found.update(str(row["storage_key"]) for row in rows)
    return found


async def sweep(
    db: DatabaseClient, storage: FileStorage, *, min_age: timedelta, delete: bool
) -> dict[str, int]:
    """List orphans; delete them only when ``delete`` is set. Returns counts."""

    objects = await storage.list_objects(EXPORT_PREFIX)
    registered = await registered_keys(db, [item.key for item in objects])
    orphans = find_orphans(objects, registered, now=datetime.now(UTC), min_age=min_age)
    for item in orphans:
        print(
            json.dumps(
                {"orphan": item.key, "bytes": item.size, "modified": item.last_modified.isoformat()}
            )
        )
        if delete:
            await storage.delete(item.key)
    return {
        "objects": len(objects),
        "registered": len(registered),
        "orphans": len(orphans),
        "deleted": len(orphans) if delete else 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--delete", action="store_true", help="delete the orphans (default: list)")
    parser.add_argument("--min-age-hours", type=float, default=24.0)
    args = parser.parse_args()
    config = PlatformConfig.from_env()
    counts = asyncio.run(
        sweep(
            DatabaseClient(config),
            FileStorage(config),
            min_age=timedelta(hours=args.min_age_hours),
            delete=args.delete,
        )
    )
    print(json.dumps({"mode": "delete" if args.delete else "dry-run", **counts}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
