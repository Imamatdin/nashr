# Runbook — nightly backup & restore-verify drill

## What runs automatically

- `backup` compose service: `scripts/backup_db.py --loop` — nightly 02:00 UTC
  `pg_dump -Fc` of the Supabase database (`SUPABASE_DB_URL`, the DIRECT
  Postgres URL) to R2 `backups/`, 14-day retention prune.

## Restore-verify drill (human-run)

Scratch target: **postgres:17 or newer** (pinned — pg_dump on the VM comes
from PostgreSQL 17's client tools; an older scratch server can refuse the
dump format). Example:

```bash
docker run -d --name nashr-scratch -e POSTGRES_PASSWORD=scratch -p 5433:5432 postgres:17
python scripts/backup_restore_verify.py \
    --target-url postgresql://postgres:scratch@localhost:5433/postgres
```

- `--target-url` is mandatory and must NEVER be the production URL.
- The target's `public` schema must be empty; re-using a scratch DB requires
  `--clean` (pg_restore `--clean --if-exists`).
- Only `--schema=public` is restored. Supabase-managed schemas
  (`auth`, `vault`, `storage`, `realtime`, …) are intentionally OUT OF SCOPE
  of this drill: they are provider furniture recreated by Supabase itself,
  and restoring them into a plain Postgres fails on missing roles/extensions
  (2026-08-08 drill finding). Our data — users, projects, decks, ledger,
  jobs — all lives in `public`.
- Success = script exits 0 and prints per-table row counts for
  `users, projects, decks, brain_sessions, credit_ledger, orders`; eyeball
  them against production expectations.

Optional: `--key backups/<name>.dump` restores a specific dump instead of the
newest.
