"""Nightly pg_dump → R2 ``backups/`` prefix, 14-day retention (plan amendment 3).

Modes::

    python scripts/backup_db.py            # one dump now, then exit
    python scripts/backup_db.py --loop     # compose service: dump nightly at 02:00 UTC

Requires ``SUPABASE_DB_URL`` (the direct Postgres connection string — the
Supabase REST URL cannot drive pg_dump) and the R2 credentials the platform
already uses. ``pg_dump`` must be on PATH (Dockerfile installs
``postgresql-client``). Dumps are custom-format (``-Fc``) so
``scripts/backup_restore_verify.py`` can pg_restore them into a scratch DB.

The product and the money live in Postgres (decks, brain_sessions,
credit_ledger, orders); Supabase free tier has minimal recovery — this is the
recovery path.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import subprocess
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from packages.platform.config import PlatformConfig
from packages.platform.storage import FileStorage

logger = logging.getLogger("nashr.backup")

BACKUP_PREFIX = "backups/"
RETENTION_DAYS = 14
NIGHTLY_HOUR_UTC = 2
DUMP_TIMEOUT_SECONDS = 1800


def _dump_key(now: datetime) -> str:
    return f"{BACKUP_PREFIX}nashr_{now.strftime('%Y%m%dT%H%M%SZ')}.dump"


def run_pg_dump(db_url: str, target: Path) -> None:
    """Run ``pg_dump -Fc`` to ``target``; raises on non-zero exit."""

    completed = subprocess.run(
        [
            "pg_dump",
            "--format=custom",
            "--no-owner",
            "--no-privileges",
            "--file",
            str(target),
            db_url,
        ],
        capture_output=True,
        text=True,
        timeout=DUMP_TIMEOUT_SECONDS,
        check=False,
    )
    if completed.returncode != 0:
        tail = (completed.stderr or "").strip()[-1000:]
        raise RuntimeError(f"pg_dump exited {completed.returncode}: {tail}")
    if not target.exists() or target.stat().st_size == 0:
        raise RuntimeError("pg_dump reported success but produced no file")


async def prune_old_backups(storage: FileStorage, now: datetime) -> int:
    """Delete backups/ objects older than RETENTION_DAYS; returns count deleted."""

    if not storage.available:
        return 0
    cutoff = now - timedelta(days=RETENTION_DAYS)

    def list_keys() -> list[tuple[str, datetime]]:
        client = storage._client  # pyright: ignore[reportPrivateUsage]
        paginator = client.get_paginator("list_objects_v2")
        out: list[tuple[str, datetime]] = []
        for page in paginator.paginate(Bucket=storage.bucket, Prefix=BACKUP_PREFIX):
            for obj in page.get("Contents", []):
                out.append((str(obj["Key"]), obj["LastModified"]))
        return out

    keys = await asyncio.to_thread(list_keys)
    deleted = 0
    for key, modified in keys:
        if modified < cutoff:
            await storage.delete(key)
            deleted += 1
    return deleted


async def backup_once(config: PlatformConfig, db_url: str) -> str:
    """Dump the database, upload to R2, prune the retention window; return the key."""

    storage = FileStorage(config)
    now = datetime.now(UTC)
    key = _dump_key(now)
    tmpdir = Path(tempfile.mkdtemp(prefix="nashr_backup_"))
    dump_path = tmpdir / "nashr.dump"
    try:
        await asyncio.to_thread(run_pg_dump, db_url, dump_path)
        await storage.upload(dump_path, key, content_type="application/octet-stream")
        pruned = await prune_old_backups(storage, now)
        logger.info(
            "backup_complete %s",
            json.dumps({"key": key, "size_bytes": dump_path.stat().st_size, "pruned": pruned}),
        )
        return key
    finally:
        dump_path.unlink(missing_ok=True)


def _seconds_until_nightly(now: datetime) -> float:
    target = now.replace(hour=NIGHTLY_HOUR_UTC, minute=0, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


async def _amain(args: argparse.Namespace) -> int:
    db_url = os.environ.get("SUPABASE_DB_URL", "").strip()
    if not db_url:
        logger.error("backup_missing_db_url SUPABASE_DB_URL is not set")
        return 1
    config = PlatformConfig.from_env()

    if not args.loop:
        await backup_once(config, db_url)
        return 0

    while True:
        delay = _seconds_until_nightly(datetime.now(UTC))
        logger.info("backup_sleeping %s", json.dumps({"seconds": int(delay)}))
        await asyncio.sleep(delay)
        try:
            await backup_once(config, db_url)
        except Exception as exc:
            # Log and keep the service alive: one failed night must not stop
            # the next; the operator greps backup_failed.
            logger.exception("backup_failed %s", json.dumps({"error_type": type(exc).__name__}))


def main() -> int:
    parser = argparse.ArgumentParser(description="Nightly pg_dump → R2 backups/")
    parser.add_argument("--loop", action="store_true", help="run as the nightly compose service")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    return asyncio.run(_amain(args))


if __name__ == "__main__":
    raise SystemExit(main())
