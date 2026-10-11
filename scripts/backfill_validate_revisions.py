"""Flag imported revisions whose content fails today's content models (ADR 0001).

Migration 016 imports every legacy deck through ``commit_revision`` and never
drops content, valid or not. DeckSpec / ArticleDocumentContent validation is
Python, so it runs here, after the migration: every ``import`` revision without a
``revision_validations`` row is validated and a write-once verdict is recorded
(``valid`` or ``legacy_invalid`` with the first errors). Keyset-paginated, so it
resumes where it stopped; already-validated revisions are skipped, so a second
run changes nothing. Dry-run by default; ``--apply`` records verdicts.

    python scripts/backfill_validate_revisions.py           # report counts
    python scripts/backfill_validate_revisions.py --apply   # record verdicts
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any, cast

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pydantic import BaseModel, ConfigDict, ValidationError

from packages.core.models.document import ArticleDocumentContent
from packages.core.models.presentation import DeckSpec
from packages.platform.config import PlatformConfig
from packages.platform.database import DatabaseClient
from packages.platform.document_models import DocumentKind
from packages.platform.document_store import DocumentStore

VALIDATOR = "content-models-v1"
_PAGE = 200


class Verdict(BaseModel):
    """One revision's validation result."""

    model_config = ConfigDict(extra="forbid")

    revision_id: str
    valid: bool
    detail: str | None


def judge(revision_id: str, kind: DocumentKind, content: Any) -> Verdict:
    """Validate ``content`` against the current model for its document kind."""

    model = DeckSpec if kind is DocumentKind.PRESENTATION else ArticleDocumentContent
    try:
        model.model_validate(content)
    except ValidationError as exc:
        errors = "; ".join(
            f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in exc.errors()[:5]
        )
        return Verdict(revision_id=revision_id, valid=False, detail=errors[:4000])
    return Verdict(revision_id=revision_id, valid=True, detail=None)


async def _page(db: DatabaseClient, after: str) -> list[dict[str, Any]]:
    def run() -> Any:
        return (
            db._query("document_revisions")  # pyright: ignore[reportPrivateUsage]
            .select("id,document_id,content")
            .eq("kind", "import")
            .gt("id", after)
            .order("id")
            .limit(_PAGE)
            .execute()
        )

    result = await asyncio.to_thread(run)
    return cast(list[dict[str, Any]], list(result.data or []))


async def _lookup(
    db: DatabaseClient, table: str, column: str, ids: list[str]
) -> list[dict[str, Any]]:
    def run() -> Any:
        return (
            db._query(table)  # pyright: ignore[reportPrivateUsage]
            .select("*")
            .in_(column, ids)
            .execute()
        )

    result = await asyncio.to_thread(run)
    return cast(list[dict[str, Any]], list(result.data or []))


async def backfill(db: DatabaseClient, *, apply: bool) -> dict[str, int]:
    """Validate every unvalidated import revision; record verdicts when ``apply``."""

    store = DocumentStore(db)
    counts = {"scanned": 0, "already_validated": 0, "valid": 0, "legacy_invalid": 0}
    after = "00000000-0000-0000-0000-000000000000"
    while rows := await _page(db, after):
        after = str(rows[-1]["id"])
        ids = [str(row["id"]) for row in rows]
        done = {
            str(r["revision_id"])
            for r in await _lookup(db, "revision_validations", "revision_id", ids)
        }
        documents = {
            str(d["id"]): DocumentKind(str(d["kind"]))
            for d in await _lookup(
                db, "documents", "id", sorted({str(r["document_id"]) for r in rows})
            )
        }
        for row in rows:
            counts["scanned"] += 1
            if str(row["id"]) in done:
                counts["already_validated"] += 1
                continue
            verdict = judge(str(row["id"]), documents[str(row["document_id"])], row["content"])
            counts["valid" if verdict.valid else "legacy_invalid"] += 1
            if not verdict.valid:
                print(json.dumps({"legacy_invalid": verdict.revision_id, "detail": verdict.detail}))
            if apply:
                await store.record_validation(
                    verdict.revision_id, VALIDATOR, verdict.valid, verdict.detail
                )
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="record verdicts (default: report)")
    args = parser.parse_args()
    counts = asyncio.run(backfill(DatabaseClient(PlatformConfig.from_env()), apply=args.apply))
    print(json.dumps({"mode": "apply" if args.apply else "dry-run", **counts}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
