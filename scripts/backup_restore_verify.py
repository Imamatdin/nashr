"""Restore-verify a nightly backup into a SCRATCH database (P2 gate item).

Usage::

    python scripts/backup_restore_verify.py --target-url postgresql://.../scratch_db
    python scripts/backup_restore_verify.py --target-url ... --key backups/nashr_x.dump

Downloads the newest ``backups/`` dump from R2 (or the named one), runs
``pg_restore`` into the target database (which must be an EMPTY scratch DB —
this script refuses to guess and never touches the production URL), then
counts rows in the load-bearing tables and prints them so a human can eyeball
the restore against expectations.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from packages.platform.config import PlatformConfig
from packages.platform.storage import FileStorage
from scripts.backup_db import BACKUP_PREFIX

logger = logging.getLogger("nashr.restore_verify")

VERIFY_TABLES = ("users", "projects", "decks", "brain_sessions", "credit_ledger", "orders")
RESTORE_TIMEOUT_SECONDS = 1800


async def latest_backup_key(storage: FileStorage) -> str | None:
    """Newest backups/ object key by last-modified, or None when none exist."""

    def run() -> str | None:
        client = storage._client  # pyright: ignore[reportPrivateUsage]
        paginator = client.get_paginator("list_objects_v2")
        best: tuple[str, object] | None = None
        for page in paginator.paginate(Bucket=storage.bucket, Prefix=BACKUP_PREFIX):
            for obj in page.get("Contents", []):
                if best is None or obj["LastModified"] > best[1]:  # pyright: ignore[reportOperatorIssue]
                    best = (str(obj["Key"]), obj["LastModified"])
        return best[0] if best else None

    return await asyncio.to_thread(run)


def run_pg_restore(dump_path: Path, target_url: str) -> None:
    """pg_restore the custom-format dump into the scratch database."""

    completed = subprocess.run(
        [
            "pg_restore",
            "--no-owner",
            "--no-privileges",
            "--exit-on-error",
            "--dbname",
            target_url,
            str(dump_path),
        ],
        capture_output=True,
        text=True,
        timeout=RESTORE_TIMEOUT_SECONDS,
        check=False,
    )
    if completed.returncode != 0:
        tail = (completed.stderr or "").strip()[-2000:]
        raise RuntimeError(f"pg_restore exited {completed.returncode}: {tail}")


def count_rows(target_url: str) -> dict[str, str]:
    """Row counts per verify table via psql (present in postgresql-client)."""

    counts: dict[str, str] = {}
    for table in VERIFY_TABLES:
        completed = subprocess.run(
            ["psql", target_url, "-tAc", f"select count(*) from {table}"],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        counts[table] = (
            completed.stdout.strip()
            if completed.returncode == 0
            else f"ERROR: {completed.stderr.strip()[:200]}"
        )
    return counts


async def _amain(args: argparse.Namespace) -> int:
    config = PlatformConfig.from_env()
    storage = FileStorage(config)
    key = args.key or await latest_backup_key(storage)
    if key is None:
        logger.error("restore_verify_no_backups no objects under %s", BACKUP_PREFIX)
        return 1

    tmpdir = Path(tempfile.mkdtemp(prefix="nashr_restore_"))
    dump_path = tmpdir / "restore.dump"
    await storage.download(key, dump_path)
    logger.info(
        "restore_verify_downloaded %s",
        json.dumps({"key": key, "size_bytes": dump_path.stat().st_size}),
    )
    await asyncio.to_thread(run_pg_restore, dump_path, args.target_url)
    counts = await asyncio.to_thread(count_rows, args.target_url)
    print(json.dumps({"backup_key": key, "row_counts": counts}, indent=2))
    failed = [t for t, v in counts.items() if v.startswith("ERROR")]
    if failed:
        logger.error("restore_verify_failed %s", json.dumps({"tables": failed}))
        return 1
    logger.info("restore_verify_ok %s", json.dumps({"key": key}))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Restore a backup into a scratch DB and verify")
    parser.add_argument("--target-url", required=True, help="EMPTY scratch database URL")
    parser.add_argument("--key", help="specific backups/ key (default: newest)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    return asyncio.run(_amain(args))


if __name__ == "__main__":
    raise SystemExit(main())
