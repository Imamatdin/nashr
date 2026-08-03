# P2 JOB PIPELINE — review package (branch build1-content-critic, 3 commits on top of edafee8)

Commits: `f3d2610` (F1 audit events) · `342d8dc` (queue core + migrations 006-008) ·
`f390776` (worker entrypoint + compose + backups).
Full diff: `p2_pipeline.diff`. New tests copied alongside (`test_job_queue.py`,
`test_rate_limit_persisted.py`, `test_jobs_routes.py`, `test_worker_and_backup.py`;
plus 3 new tests inside `test_presentation_orchestrator.py` and 1 in
`test_identity_service.py` — see the diff).

Status: CODE-COMPLETE, NOT GATED. Migrations 006/007/008 are WRITTEN, never applied.
Nothing deployed. Suite: `python -m pytest tests/` = 1650 passed / 32 skipped
(baseline 1609; the known timing flake passed this run). ruff + format clean on every
changed file (LF); pyright 0 errors on the changed set (the one repo error,
`arxiv.py getattr`, is pre-existing on clean HEAD — local pyright version drift).

## The three riskiest decisions

1. **Refund authority moved into the worker, keyed off `payload.product_type`.**
   The enqueue route deducts via the existing balance path and stamps
   `product_type` into the job payload; on failure (or reap) the worker refunds
   `CreditLedger.PRICING[product_type]`. Risk: a price change between enqueue and
   failure refunds the NEW price, not the deducted amount; and a hand-inserted job
   row with a bogus product_type is silently skipped (logged
   `worker_refund_skipped`). I judged this acceptable because prices change by
   deploy, jobs live minutes — but the strictly-correct alternative is storing the
   deduction ledger id (or amount) in the payload and refunding exactly that.
   Cheap to change if you want it.

2. **Reaper refund exactly-once rests on the SQL function's RETURNING set.**
   `reap_stale_jobs` fails exhausted zombies in one UPDATE and returns those rows
   only to the caller whose UPDATE won; every loop-worker calls it each tick.
   Two workers reaping concurrently should partition rows via row-level locking on
   the UPDATE — but this is exactly the kind of concurrency claim that must be
   proven on the VM gate (kill a worker mid-run with two loop workers running and
   count refund ledger rows for the job: must be 1). Also note the reaper cannot
   distinguish "worker died" from "worker alive but DB unreachable for
   >stale_seconds" — the guarded terminal transitions (`WHERE worker_id = me AND
   status = 'processing'`) make the surviving worker's late writes no-ops, so the
   failure mode is an unnecessary refund + honest failed row, never a double
   delivery or zombie.

3. **The bot's Telegram delivery path is untouched; queue jobs deliver via R2 +
   generated_files only.** A queue-run job uploads to the stable keys and upserts
   `generated_files`, marks the job `completed` — but sends nothing to Telegram
   (there is no chat context on the worker). The P2 gate item "browser/bot-initiated
   job delivers via the queue" therefore means: browser polls GET /jobs/{id} then
   downloads from the stable keys; the bot still generates in-process (per plan:
   "bot keeps its in-process generation path, converges later"). If you expected
   the bot to enqueue instead of running in-process, that is NOT built — flagging
   so the gate is run against the right expectation.

## Smaller flags

- **Stable-key switch changes live behavior of the BOT path too**: uploads now land
  on `generated/{pid}/presentation.{ext}` instead of title-derived names, and every
  render upserts `generated_files`. Old title-keyed R2 objects are orphaned (never
  deleted). This is the plan's C5 fix, deliberately at the one chokepoint.
- **Enqueue idempotency is check-then-insert plus a constraint backstop**: the
  pre-check avoids double deduction in the common case; the 006 partial unique
  index catches the race, and the route refunds and returns the winner. The
  DuplicateActiveJobError detection treats ANY insert failure + existing active row
  as a duplicate — a genuine network error concurrent with an active job returns
  the existing job after refund, which is safe (no spend, no dup execution).
- **Rate counters count attempts, including rejected ones** (deliberate: an abuse
  cap measures pressure). Both scopes are always bumped.
- **`consume_rate_limit` / claim fns are SECURITY DEFINER with anon/authenticated
  REVOKEd** — service-role only, same trust model as the rest of the platform layer.
- **Backups need `SUPABASE_DB_URL`** (direct Postgres URL) added to the VM .env;
  compose fails fast (`:?`) if missing. pg_dump ships in the image via
  postgresql-client (Debian bookworm = pg 15 client, matching Supabase pg 15;
  verify major version on the VM).
- **Realtime migration 008** sets `replica identity full` on generation_jobs and
  decks — required for RLS-filtered UPDATE payloads; slight WAL cost.

## Human gates (do NOT self-mark)

1. Browser/bot-initiated job delivers via the queue (see flag 3 for expectation).
2. Kill worker mid-run → reaper fails the job honestly, no zombie, single refund.
3. Double dispatch executes once (concurrent POST /jobs + two loop workers).
4. Over-cap enqueue rejected visibly (429 body carries scope/count/limit/resets_at),
   zero model tokens.
5. One backup restored into a scratch database via `backup_restore_verify.py`.
