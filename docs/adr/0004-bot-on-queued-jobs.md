# ADR 0004 — Bot on queued jobs (approvals, edits, generation, articles)

- Status: accepted (2026-10-18)
- Scope: the Telegram bot's write paths (approvals, chat edits, generation,
  articles) move onto the same queued jobs the web uses, so every charged job and
  every canonical write is settled exactly once (ADR 0001 I11) and no write bypasses
  `commit_revision` / `finish_generation_job`.
- Builds on: ADR 0001 (canonical document state). This ADR records the delivery
  design ADR 0001 §10 items 1, 5 and 6 defer to B8.

## 1. B8.1 — bot approvals through the operation-bound job

### Problem
The bot's Approve button applied a parked decision inline (`_apply_pending`),
committing through `commit_revision` with no operation fencing, unlike a web
approval's operation-bound queued `presentation_edit` job (ADR 0001 §10 item 5).
Since B1 closed without it, the button applied nothing and pointed the user at the
web.

### Decision
One shared, transport-neutral enqueue function,
`packages.sessions_core.chat.enqueue_approved_edit`, is the single path the web
approve route (`packages/api/routes/chat.py`) and the bot Approve button
(`packages/bot/handlers/presentation_flow.py:approve_redeliver`) both take. It
confirms the parked decision the caller named is still parked
(`pending_for_approval`), stamps the job with that call's identity (`session_id`,
`operation_id`) and the revision the brain saw (`base_revision_id`), and enqueues a
`presentation_edit` job with no deduction (an edit spends the fix allowance, not
money). It raises typed errors the caller maps to its transport
(`DecisionStaleError`, `NoPendingActionError`, `SessionNotReadyError`, and the
enqueue's own `DuplicateActiveJobError` / `EditIdentityRefusedError`). Neither caller
un-parks the decision on failure: it stays re-presentable, exactly as the web turn
route never un-parks an approval.

The "one active edit job per project" guarantee (a double tap, or a bot approve
racing a web approve of the same parked call) is **not** new bot code: it is the
shared `uq_generation_jobs_active` partial unique index plus the
`generation_jobs_require_edit_identity` trigger (migration 016, B1-FIX4), already
exercised against real Postgres by the web edit path's tests/db suite. The bot
submits through the identical `JobQueue.enqueue`, so the second submission loses to
the index and surfaces as `DuplicateActiveJobError`, which the bot answers with
`brain_busy` and leaves the decision parked.

### Delivery: who sends the files to Telegram (the decision this ADR owes)

**The worker sends, at the moment the edit job becomes `completed`, best-effort.**
The bot's approve enqueue stamps a Telegram delivery block on the job payload
(`delivery.telegram = {chat_id, language}`); web jobs carry none and are skipped.
Delivery fires at the single transition where the files first exist and the job is
delivered:

- When the commit found every requested format already registered,
  `finish_generation_job` completes the edit job immediately; the worker
  (`_run_presentation_edit`) delivers then, while its Bot is still open.
- Otherwise the edit job stays `committed` until its render job publishes the
  formats; the render's `complete_job` flips each committed parent it delivers to
  `completed` in one transaction, and the render worker
  (`_run_presentation_render._deliver_render_parents`) then pushes the files to the
  Telegram parents it just completed.

A send failure (a transient Telegram error, a missing export, a bot restart) never
fails the job, never refunds (there is nothing to refund: an edit is unpaid), and
never re-runs the edit. It is logged once with context and no secrets. The committed
revision and its `edit_deliveries` row are the durable record that the edit
succeeded; the bot offers a "send files" button (`send_files_keyboard`) that
re-pulls the committed revision's registered exports from storage on demand, so the
user recovers the files without paying for the edit again.

**Why worker-sends over a bot-side poller.** The worker owns the durable job
lifecycle, so delivery survives a bot restart and needs no in-memory per-chat task
to track outstanding jobs; the bot is offline in production and a long-lived poller
would be fragile and non-deterministic to test. Delivery fires exactly once per
delivered job because `complete_job` returns true to exactly one caller, so the
normal path sends no duplicates; the rare crash-after-complete-before-send gap is
covered by the user-driven "send files" button rather than by an at-least-once retry
that could double-send. The worker already constructs an aiogram Bot for every
presentation job and has storage access, so no new process or dependency is added.

**Why not thread delivery through the settlement SQL.** Enqueuing a dedicated
delivery job transactionally from inside `_deliver_parents` / `complete_job` would be
the most durable option, but those functions are owned by the article/settlement lane
(see `_sql-ownership.md`); the bot lane redefines nothing there. Application-level
delivery keyed off the job payload keeps the fence (ADR 0001 I8/I12) and the money
path (I11) untouched.

### Compatibility
No schema change (migration 019 is reserved for B8.2's `fixes_used` lock). Web
approvals are unchanged behaviourally: the route now calls the shared function
instead of its own inline copy, producing the identical job payload. Existing
`presentation_edit` jobs without a delivery block (every web job) are delivered the
way they always were, by the web client polling the job and reading exports.

## 2. B8.2 — bot edits through the queue; fixes_used read-only
(To be recorded when built.)

## 3. B8.3 — bot generation onto queued jobs
(To be recorded when built; design review required.)

## 4. B8.4 — bot articles through the B5 service and B6 exporter
(To be recorded when built, after B5/B6 land in integration.)
