# ADR 0001 — Canonical document state

- Status: proposed (2026-10-11)
- Scope: presentation decks and article documents; their revisions, AI proposals
  and rendered exports
- Supersedes: the write paths of migrations 011, 013, 015 (`create_document_if_missing`,
  `commit_document_revision`, `commit_presentation_revision_and_deck`), migration
  007's stable export keys, and `DatabaseClient.save_deck`

## 1. Problem

The canonical state of a presentation exists in two tables with seven writers that
disagree about which one is authoritative (full inventory in Appendix A).

1. **Two sources of truth.** `documents`/`document_revisions` (011) is the versioned
   store; `decks` (001/003) is a single mutable row per project. Generation, the bot
   edit and the render job write `decks` directly through `save_deck`
   (`database.py:590`). Only the web AI-edit job (`worker_run_job.py:338`, migration
   013) writes both, atomically. The web manual save (`design.py:154`) and restore
   (`design.py:198`) write only revisions, so `decks` goes stale.
2. **Readers pick different truths.** The bot loads the document head and falls back
   to `decks` (`store.py:157-166`). `/decisions` reads `decks` (`projects.py:392`).
   Web Realtime listens on `decks` (`use-live-job.ts:149`). A web manual edit is
   therefore invisible to `/decisions`. A bot edit after a web import writes `decks`
   while the head stays put, so the web keeps showing the pre-edit deck and the
   bot's next turn reloads the old head and silently discards the bot edit (§7, test b).
3. **Exports are keyed by project, not by content.** `generated/{project_id}/presentation.{ext}`
   (`storage.py:318`) is overwritten in place and registered in `generated_files`
   by `(project_id, file_type)`. A render job for an older revision overwrites what
   downloads return for the head (`worker_run_job.py:242-253`), then also overwrites
   `decks` with the old content (test a).
4. **Failures are swallowed.** Upload failure (`presentation_orchestrator.py:891`),
   registration failure (`:915`) and deck-persist failure (`:942`) are logged and
   dropped. `render()` turns each failed format into a warning (`:812-839`), so a job
   that delivered one of three requested formats reports success (test i).
5. **No fencing on exports.** Nothing checks that the worker registering an export
   still holds its job claim, or that the export belongs to the revision the job
   targeted (tests f, g).
6. **Concurrent AI writes are thrown away.** A web AI edit whose base went stale is
   abandoned before running (`worker_run_job.py:329-335`); a stale edit discovered
   after the LLM ran would raise `stale_revision` and lose the paid output (test c).
7. **Invariants live in application code.** RLS policies on `decks` and
   `document_revisions` are `for all`, so an authenticated PostgREST client can write
   either table directly, bypassing hashing, idempotency and compare-and-swap (test k).

## 2. Invariants (enforced by the database)

| # | Invariant | Mechanism |
|---|---|---|
| I1 | A revision row never changes after insert | INSERT/UPDATE/DELETE/TRUNCATE revoked from `anon`, `authenticated`, `service_role`; only `commit_revision` (SECURITY DEFINER) inserts |
| I2 | `documents.head_revision_id` advances only by compare-and-swap from the caller's base | head moved only inside `commit_revision` under `SELECT … FOR UPDATE` on the document row; direct writes to `documents` revoked |
| I3 | Head is the last committed revision; parent of every new revision is the head it replaced | same transaction sets `parent_revision_id = head` and `head = new` |
| I4 | Retrying an operation with the same idempotency key never duplicates; reusing a key for different content is an error | key unique per document across revisions **and** proposals, checked under the document lock; hash compared |
| I5 | A losing AI, regeneration or import write is stored, not discarded | `kind in (ai_edit, regeneration, import)` with stale base inserts a `revision_proposals` row |
| I6 | The deck read model always equals head content | `decks` becomes a VIEW over the head (§4.4); it cannot diverge |
| I7 | An export belongs to exactly one (revision, format, renderer_version) and is never overwritten | PK on that triple; the first registration wins and a later one returns `existing` with the stored row (B1-FIX; previously a different hash raised) |
| I8 | Only the worker currently holding a render job's claim can register that job's exports, only for the revision, renderer and formats the job names, for the project's owner | `register_export` locks the job row and checks every field NULL-safely (§4.3) |
| I9 | Only known content schema versions are stored; content size is bounded | `document_schema_versions` registry; `octet_length(content::text) <= 2 MiB` |
| I10 | A user can read and commit only their own documents | owner-only SELECT RLS; `commit_revision` resolves the caller (`app_uid()` or the actor) to the project owner |
| I12 | A queue worker's revision or proposal exists only if its job left `processing` through its finish (committed, completed or delivery_failed), under the claim that produced it | workers cannot use `commit_revision`; `finish_generation_job` locks the job, checks the live claim (worker, attempt token, heartbeat fresh at decision time), commits and settles the job in one transaction (§4.3, §4.6) |
| I11 | **A queued job that took money ends `completed` (delivered) or refunded exactly once** (`failed` or `delivery_failed`). Scope: jobs in `generation_jobs` charged through `payload.deducted_amount`; bot generation and its refunds are not queued jobs and are outside it (B8, §10) | `fail_job`, render failure and the reaper settle the job and insert its refund in one transaction under the job row lock (§6.6, §6.7); a committed job is delivered only by its render's completion; partial unique index on `credit_ledger(generation_job_id) where action = 'refund'`, always installed (§8) |

## 3. Decision summary

1. Keep `documents` + `document_revisions` as the only canonical store, extended
   with provenance columns.
2. Replace the three write functions with one `commit_revision`, plus
   `ensure_document`, `accept_proposal`, `reject_proposal`, `register_export`.
3. Turn `decks` into a security-invoker VIEW of the head (§4.4, Appendix B).
4. Replace `generated_files` (for presentations) with immutable `revision_exports`
   keyed by `(revision_id, format, renderer_version)` and content-addressed storage
   keys.
5. Every writer, including the bot, goes through these functions; every render runs
   under a job claim (the bot claims an inline job, §6.4).

## 4. Schema (migration 016)

### 4.1 `document_revisions` (altered)

| Column | Change | Notes |
|---|---|---|
| `kind` | add, `text not null` | `generation, regeneration, manual, autosave, ai_edit, bot_edit, import, restore`; legacy rows backfilled to `import` |
| `schema_version` | add, `int not null` | checked against `document_schema_versions` for the document's kind inside `commit_revision`; legacy rows inherit their document's `schema_version` (B1-FIX: 011 allowed other versions; they were labelled 1), and 016 inventories versions in `migration_reports` |
| `content_sha256` | rename of `content_hash` | DB-computed `sha256(content::text)` (jsonb text is canonical: keys sorted, whitespace normalized) |
| `actor` | add, `text not null` | `<user uuid>`, `worker:<job uuid>`, `bot:<telegram id>`, or `system:<name>` (import only); legacy = `created_by` or `system:legacy` |
| `created_by` | kept | the resolved owning user, so history can show a person even for worker/bot actors |
| `parent_revision_id`, `idempotency_key` | kept (011) | `unique (document_id, idempotency_key)` already exists |
| `accepted_from_proposal_id` | add, nullable | set when the revision came from accepting a proposal |

`documents.head_revision_id` already exists (011); it is not re-added.

### 4.2 New tables

- `document_schema_versions(kind, version)`: registry, seeded with
  `(presentation, 1)` and `(article, 1)`. `DeckSpec` has no version field today, so the
  presentation version is 1 by definition; `ArticleDocumentContent.schema_version` is
  `Literal[1]`.
- `revision_proposals(id, document_id, base_revision_id null, content, content_sha256,
  schema_version, kind, actor, source_job_id, idempotency_key, status pending|accepted|rejected|superseded,
  created_at, resolved_at, resolved_by, accepted_revision_id)`. The brief's column list
  gains `idempotency_key`, `content_sha256` and `actor`: without them a retried
  AI commit that became a proposal would create a second proposal (breaks I4 / test e).
  `base_revision_id` is nullable for the one case in §6.1.
- `revision_exports(revision_id, format, renderer_version, storage_key, sha256,
  byte_size, page_count, created_by_job, created_at)`, PK `(revision_id, format,
  renderer_version)`, owner-only SELECT RLS.
- `revision_validations(revision_id pk, validator, status valid|legacy_invalid,
  detail, created_at)`: insert-once validation result per revision, written by the
  backfill flagger (§8). A separate keyed table instead of a mutable flag column on
  the revision keeps I1 literal.

Deviation from `.claude/rules/database.md` (uuid PK on every table): `revision_exports`,
`document_schema_versions` and `revision_validations` use natural keys. The export PK
`(revision_id, format, renderer_version)` *is* the invariant (I7), the registry is a
lookup set, and a validation is one row per revision.

### 4.3 Functions (SECURITY DEFINER, `search_path = public, pg_temp`)

`commit_revision(document_id, base_revision_id, content, kind, schema_version, actor,
idempotency_key) → (status, document_id, revision_id, head_revision_id, proposal_id)`

1. Lock the document row (`FOR UPDATE`); `document_not_found` if absent.
2. Resolve the caller. If the session role is `authenticated`, the owner must be
   `app_uid()`, the actor must equal it, and kind is limited to
   `manual, autosave, restore`. Otherwise (service role, or the migration owner) the
   actor is parsed: a user uuid must own the project; a `worker:<job>` actor is
   refused (`worker_must_finish_job`, B1-FIX): queue workers write only through
   `finish_generation_job` below. The remaining rule text is the pre-fix design:
   `worker:<job>` had to name a
   `processing` job of the same project whose `user_id` owns it; `bot:<telegram id>`
   must map through `users.telegram_id` to the owner; `system:migration-NNN` only
   for `import` (B1-FIX: narrowed from any `system:*`; it is a migration's identity,
   reachable only by privileged callers, and is not independently authenticated).
3. Validate kind, `schema_version` against the registry, content is a JSON object,
   size ≤ 2 MiB (real decks are 20–55 KB; see Appendix B).
4. Idempotency: same key with same hash on a revision → `duplicate` (original id);
   on a proposal → `proposed` (original proposal id); same key with different hash →
   `idempotency_key_reused` error.
5. No-op: content hash equals the head's → `unchanged` with the head id; no revision
   is written, whatever the base, but a `document_operation_receipts` row records the
   key, hash and result (B1-FIX, Codex finding 6), so a retry after the head moved
   replays `unchanged` instead of conflicting and the key cannot be reused for other
   content. Step 4 consults receipts too. An identical autosave would otherwise advance the head
   and turn every in-flight AI edit on that head into a proposal.
6. `base = head` → insert revision (`parent = head`), advance head, `committed`.
7. `base ≠ head` → for `ai_edit`/`regeneration`/`import` insert a proposal, `proposed`; for any
   other kind, `conflict` with the current head id. Nothing is written on conflict.

`finish_generation_job(job_id, worker_id, claim_token, base_revision_id, content, kind,
schema_version, idempotency_key, renderer_version, render_formats, render_max_attempts)`
(B1-FIX, Codex finding 1; delivery from B1-FIX2): the only way a queue worker changes
canonical state.

0. A committed revision must be rendered: a NULL renderer, an empty or NULL-holding
   format list, or `render_max_attempts` outside 1–5 is refused (`render_required`,
   `invalid_render_formats`, `invalid_render_max_attempts`) before anything is read.
   It is never silently skipped (B1-FIX2).
1. Lock the job row. A claim is `(worker_id, attempts)`: every claim increments
   `attempts`, so the attempt number is a monotonic claim token. The claim is live when
   the job is `processing` under that worker and token and `heartbeat_at` is younger
   than `_claim_ttl()` (120 s, the reaper's default window), judged with
   `clock_timestamp()` at the moment of the check, not `now()` (the transaction's start:
   a finish that waited on locks would otherwise pass a check it fails in wall time).
   Otherwise `claim_lost` or `claim_expired`, and nothing is written.
2. The job type fixes the allowed kinds (`presentation_generation`: generation or
   regeneration; `presentation_edit`: ai_edit); the job's user must own the project.
3. Ensure and lock the presentation document, then run the same compare-and-swap as
   `commit_revision` with actor `worker:<job>`. A first `generation` that conflicts is
   stored as a `regeneration` proposal (key `<key>:proposal`), so paid output is kept.
4. Settle the job (`progress.outcome` = the status). For a committed, duplicate or
   unchanged revision, `_enqueue_render` queues (or reuses, §6.5) the render of exactly
   that revision. When something is left to render the job becomes **`committed`** and
   `render_job_id` names the render that delivers it; when every format already exists,
   or the result is a proposal (nothing to render until the owner accepts it), the job
   is `completed`.
5. A retry with the same claim after a lost response finds the job settled
   (`committed`, `completed` or `delivery_failed`) and replays the stored outcome
   (`duplicate` / `proposed` / `unchanged`) **only for the same content hash, schema
   version and kind**; anything else under that key is `idempotency_key_reused`
   (B1-FIX2). Receipts store kind and schema version for this comparison.

So a revision or proposal from a job never coexists with a failed, refunded or
re-queued job: a fault anywhere in the transaction rolls all of it back. Jobs that
commit nothing (render, source processing) complete through `complete_job(job_id,
worker_id, claim_token, progress)`, which refuses generation and edit jobs. A render
completes only when every format it names is registered (`render_incomplete`), and in
the same transaction every `committed` job whose `render_job_id` is that render
becomes `completed` (§6.7).

**Publication and freshness (decided, B1-FIX2).** `finish_generation_job` requires a
fresh claim: it writes canonical state, so a worker whose heartbeat lapsed must not.
`register_export` and `complete_job` require the caller's *current* claim token but
not a fresh heartbeat: a slow upload that outlived its heartbeat may still publish
until the reaper actually takes the job away. Once the reaper re-queues or fails the
job the token no longer matches and publication is refused, so a stale worker can
never publish against a later claim. Uploads are immutable and first-writer-wins, so
nothing a late publisher writes can be wrong, only wasted.
`claim_job` and `heartbeat_job(job_id, worker_id, claim_token)` carry the same token.

`ensure_document(project_id, kind) → document_id`: creates the row with a null head
if missing (ownership-checked the same way). Replaces the creation half of
`create_document_if_missing`; the first revision is then an ordinary
`commit_revision` with `base = null`.

`accept_proposal(proposal_id, expected_head_revision_id, actor, idempotency_key)`:
**replace-head-with-consent, not rebase.** A proposal exists because its base was no
longer the head, so "accept only if base = head" would make every proposal
unacceptable. Instead the caller states which head it showed the user:

1. Lock the document; same caller resolution and ownership checks as `commit_revision`.
2. Same idempotency rules (`duplicate` on retry, error on key reuse with other content).
3. Proposal not `pending` → `proposal_not_pending`.
4. Proposal `schema_version` ≠ head revision's → `proposal_schema_mismatch`. There is no
   silent migration.
5. `expected_head ≠ head` → `conflict` with the current head id. The UI re-fetches the
   diff and asks again.
6. Otherwise commit the proposal content as a new revision: kind = the proposal's kind
   (`ai_edit` or `regeneration`), `parent_revision_id = expected_head`,
   `accepted_from_proposal_id` set. The proposal becomes `accepted` with
   `resolved_at`/`resolved_by`. Other pending proposals stay pending. Nothing is lost,
   because the replaced head stays in history and can be restored.

Accepting a proposal whose content already equals the head marks it accepted and
returns `unchanged`; that no-op writes an `accept` receipt under the same lock, so a
retried accept with the same key returns `unchanged` again rather than
`proposal_not_pending`.

`reject_proposal(proposal_id, actor)`: pending → rejected. `superseded` is kept in the
status domain for the element-level rebase work; nothing sets it yet.

Informed consent: `GET /projects/{id}/proposals/{proposal_id}/diff` returns (a) the
diff from the proposal's base to its content (what the AI changed) and (b) the diff
from the **current head** to its content (what accepting will actually change,
including user edits made after the base that accepting would revert), plus the head
id the diff was computed against. That id is what the accept call must send. Diffs
are slide-level for presentations (by `slide_id`: added, removed, changed, moved)
and block-level for articles (by block id). Element-level rebase arrives with the
scene-graph editor (B3/B4) and will reuse this API.

`register_export(job_id, worker_id, claim_token, revision_id, format, renderer_version,
storage_key, sha256, byte_size, page_count) → (status, storage_key, sha256, byte_size)`
(B1-FIX, Codex findings 2 and 3):

1. Lock the job and require its live claim (status `processing`, same worker, same
   attempt token; NULL on either side is a lost claim, never a match).
2. The job must be a `presentation_render` job whose payload names exactly this
   revision (`job_revision_mismatch`), this renderer version
   (`renderer_version_mismatch`) and a format list containing this format
   (`format_not_requested`). Generation and edit jobs never register exports: they
   complete when they commit, and their render is a render job (§6.1).
3. The revision must belong to the job's project, and the job's user must own it.
4. The storage key must have the canonical shape for the revision.

Every check is phrased as "refuse unless provably equal": the reviewed version
compared `payload->>'revision_id' = …` inside `NOT (… OR …)`, which is NULL for a
payload without a target, and PL/pgSQL skips an `IF` whose condition is NULL, so a
generation job could register any revision of its project. The render-job CHECK now
requires a UUID-shaped string target, a string renderer version and a non-empty
format array (`NOT VALID` for terminal legacy rows; active legacy render jobs that
fail it are failed by 016 before the constraint is added).

**First writer wins.** If `(revision, format, renderer_version)` is already
registered, the call returns `existing` and the stored row; the caller's upload is
an orphan for `scripts/gc_orphan_exports.py`. A retry or a recovery render after a
crash between upload and registration therefore succeeds even though PPTX output is
not byte-stable (PptxGenJS 4.0.1 writes wall-clock timestamps into
`docProps/core.xml`). Correctness does not depend on determinism. The publisher
also reuses formats already registered for the revision and renderer without
uploading them, and a render job renders only the formats still missing (§6.5).

Grants: `commit_revision`, `ensure_document`, `accept_proposal`, `reject_proposal` to
`service_role` and `authenticated`; `register_export`, `finish_generation_job`,
`complete_job`, `claim_job` and `heartbeat_job` to `service_role` only.
`PUBLIC` and `anon` revoked on all.

### 4.4 `decks`: VIEW, not a locked projection

Evidence (Appendix B):

- Only `deck_json` comes from revision content. `title`, `language`, `audience` were
  always copied from the **project row** at save time (`database.py:582-587`); a view
  joins `projects` and returns the same values, current rather than snapshotted.
- `decks.id` has no reader in any code path. Its only dependent is the
  `design_directions.deck_id` FK, and `design_directions` has zero readers or writers
  in `packages/`.
- The design principle forbids mutating derived data in place. A projection table
  is updated in place on every head move; a view is computed from the revision.
- A view cannot diverge from the head, so invariant I6 needs no maintenance code and
  test n's "read model equals head" holds by construction (it is still tested).

Costs and how each is paid:

- **Realtime.** A view cannot be added to a publication. The one subscriber
  (`use-live-job.ts:149`) moves to `documents` (filter `project_id`), whose row
  changes exactly when the head moves (`updated_at` trigger). `documents` is added to
  `supabase_realtime` with replica identity full.
- **`design_directions` FK.** Nothing to do: foreign keys bind to the table, not the
  name, so after the rename `design_directions.deck_id` points at `decks_legacy.id`
  and keeps its rows valid. Note the mapping (Codex review): a `design_directions`
  row refers to a *legacy* deck id, while `decks.id` in the new view is the document
  id, so the two ids are not interchangeable. No code reads or writes
  `design_directions` today; a future reader must join through `decks_legacy`.
- **Row security on a view** needs `security_invoker = true` (PostgreSQL ≥ 15). The
  migration asserts `server_version_num >= 150000` and aborts otherwise. Production's
  version is **unverified** from here.
- **Writes.** INSERT/UPDATE/DELETE are revoked (test k). A join view is not
  auto-updatable, so on its own PostgreSQL refused a write in the rewriter
  (SQLSTATE 55000, HTTP 500 through PostgREST) before checking privileges. An
  `INSTEAD OF INSERT OR UPDATE OR DELETE` trigger (`decks_refuse_writes`, security
  invoker, fixed `search_path`, no other logic) makes the privilege check run first,
  so an API caller gets 42501 / HTTP 403, and even a caller holding every privilege
  reaches the trigger, which raises the same 42501. Test k accepts exactly that, and a
  catalog test pins that no API role (`authenticated`, `anon`, `PUBLIC`) holds table
  or column INSERT/UPDATE/DELETE/TRUNCATE on any canonical table.

Legacy rows: `decks` is renamed `decks_legacy` (privileges revoked, kept for audit
and rollback) after the backfill imports every row.

Alternatives for the read model:

- *Locked projection table maintained by `commit_revision`*: keeps Realtime as is, but
  stores derived data mutated in place, needs a second invariant (I6) maintained by
  code, and still needs the privilege lockdown. Rejected.
- *Fenced pointer* (`decks.revision_id` pointing at the head, content read through it):
  still a mutable row that must be kept equal to `documents.head_revision_id`, which
  duplicates the head pointer. Rejected; the view is that pointer, without a copy.

### 4.5 Storage

Key: `exports/{document_id}/{revision_id}/{renderer_version}/{format}/{sha256}.{ext}`.
Uploads send `ChecksumSHA256` so the object store verifies the bytes. A HEAD request
(`ChecksumMode=ENABLED`) must then report the same size and SHA-256 before
`register_export` is called. Local-disk storage mode re-hashes the file.

`renderer_version` is `pw-` plus the first 16 hex characters of a SHA-256 over the
renderer's source tree and lockfile (`packages/presentation-worker/src/**`,
`package-lock.json`). The package version is `0.1.0` and has never been bumped, so it
can't identify a renderer. A source hash changes exactly when output can change, and
the API, worker and bot all ship `packages/`, so they compute the same value.

### 4.5b Schema hardening (B1-FIX)

Every SECURITY DEFINER function runs with `search_path = public, pg_temp`, including
the queue functions kept from 006 (`claim_next_job`, `consume_rate_limit`;
`heartbeat_job` and `reap_stale_jobs` are redefined by 016). A fixed search path is
only safe if untrusted roles cannot create objects in `public`: PostgreSQL 15 dropped
PUBLIC's CREATE for new databases but keeps it on upgraded or restored ones. 016
revokes CREATE on `public` from PUBLIC, `anon`, `authenticated` and `authenticator`
and aborts if any of them can still create there. `system:` actors are narrowed to
`system:migration-NNN`, the backfill's identity.

### 4.6 Lock order (B1-FIX)

Every function that takes more than one row lock takes them in the order
**job → document → proposal**: `finish_generation_job` and `register_export` lock the
job first; `commit_revision`, `accept_proposal` and `reject_proposal` lock the document
(then the proposal) and never a job; `_commit_core` takes no locks of its own. The
reaper locks only job rows (`SKIP LOCKED`). With one order there is no lock cycle.

### 4.7 NULL-comparison audit (B1-FIX)

PL/pgSQL skips an `IF` whose condition is NULL, and a `CHECK` passes when its
expression is NULL, so every comparison that can see NULL must be written to fail
closed. Every function and constraint in 016 was checked (2026-10-12):

| Object | Verdict |
|---|---|
| `register_export` | was the reported hole; rewritten so each test refuses unless provably true (§4.3) |
| render-job `CHECK` | fixed: an absent `revision_id` key made the expression NULL and passed; now `coalesce(…, false)` |
| `finish_generation_job` | fixed: a NULL kind made the allowed-kinds test NULL (skipped); a NULL format passed the format filter |
| `ensure_document` | fixed: a NULL kind skipped the kind check (then failed later on NOT NULL) |
| `_document_write_owner` | fixed defensively: a NULL kind skipped the kind-allowed checks (callers validate first) |
| `_lock_claimed_job`, `claim_job`, `heartbeat_job`, `complete_job`, `fail_job` | already explicit: NULL worker or token is a lost claim; WHERE clauses treat NULL as no match |
| `_commit_core`, `commit_revision` | already explicit (`is null` checks, `is not distinct from` for the base); a NULL head hash correctly means "no no-op" |
| `accept_proposal`, `reject_proposal` | already explicit (`is distinct from` for expected head and receipt proposal; compared columns are NOT NULL) |
| `_settle_failure`, `reap_stale_jobs` | written NULL-safe: amount parsed only from a JSON number; a NULL heartbeat counts as stale |
| `record_revision_validation`, `_content_sha256`, `_caller_is_end_user` | no NULL-sensitive branch (`coalesce` in the caller test; NULL status fails the column CHECK) |
| backfill and view `DO` blocks | NULL `deck_json` is wrapped as `{"legacy_raw": null}`; other comparisons read NOT NULL columns |

## 5. Read paths

- Design/article GET return the head revision. A head that fails current model
  validation (legacy import) returns `409 {reason: "legacy_invalid", revision_id}`
  instead of a 500.
- Downloads (`GET /projects/{id}/deck?revision_id=`, default head):
  exact `(revision, current renderer)` exports exist → signed URLs. The view states
  `required_formats` (html, pdf, pptx), `available_formats` and `missing_formats`, and
  `state` is `ready` only when nothing is missing, `partial` when some formats are
  registered (a render that failed part-way, or a bot render of fewer formats; Codex
  B1 finding 7), `render_needed` when none are. The UI names the missing formats;
  `POST /design/render` queues only the missing ones and answers `ready` with no job
  when nothing is missing.
  Otherwise `state: render_needed`, plus an optional `fallback` (the same revision
  rendered by an earlier renderer, or the newest older revision with exports),
  flagged so the UI must label it as older.
- Share links serve the head's HTML export only; no export → 404.

## 6. Write paths after the change

### 6.1 Generation (worker and bot)

At job start the runner reads the head `H0`. With no head the commit is
`kind=generation, base=null`; otherwise `kind=regeneration, base=H0`. The worker calls
`finish_generation_job` with its claim (B1-FIX): the deck is committed (or stored as a
proposal when the head moved), the job completes, and a `presentation_render` job for
the committed revision is queued, all in one transaction. A worker whose claim lapsed
writes nothing and the job's next claim (or the reaper) owns the outcome. A committed
deck leaves the job **`committed`** until its render publishes the files; it is then
`completed` (delivered) or, when the render fails for good, `delivery_failed` and
refunded (§6.7). On `proposed` the job completes without a render and without a refund
(the output was delivered as a proposal). Rendering is always a render job (§6.5),
never part of the generation job.

The bot still commits through `commit_revision` as `bot:<telegram id>` and renders
in-process (§6.4); it has no queue claim to fence.

### 6.2 Manual, autosave, restore (web)

`ensure_document` + `commit_revision`. `conflict` → `409 {reason: "stale_revision",
head_revision_id}` (the existing `detail` string is kept inside a structured body).
The design import path (`design.py:96-113`) is deleted: after the backfill every deck
already has a document.

### 6.3 AI edit (web chat → worker)

Base stamped at enqueue (`chat.py:243`). The worker no longer abandons on a stale base
before running. It runs the fix and commits through `finish_generation_job`
(`kind=ai_edit`, key `chat-edit:<job>`): committed, proposed or unchanged, the job is
settled in the same transaction, and a committed edit's render (html, pdf, pptx) is a
queued render job; the edit job stays `committed` until that render settles it, like a
generation (§6.7). A chat edit on a project without a document is no longer possible
(backfill), which removes the `save_deck` fallback.

The edit allowance is consumed only by a **delivered** edit (B1-FIX2). Since
B1-FIX3 (Codex Review A, A1) the hold is a database row, not session JSON:

* **`edit_deliveries`** (job_id PK, project, session, revision, slides_changed, status
  `reserved | delivered | released`, `notice_acknowledged`, timestamps). RLS lets the
  owner read; no application role may insert, update or delete (privilege matrix).
* `finish_generation_job` writes the row in its own transaction for a
  `presentation_edit` that committed a revision: `reserved` while its render runs,
  `delivered` when every format already existed. The session is the one the API
  stamped on the job (`session_id`), else the project's session; with none (or a
  replaced one) the row is kept unattached and never blocks the commit; `slides_changed` and
  `history_len` are stamped too. A worker that dies right after the commit therefore
  loses nothing: the hold and the commit are one transaction.
* The render's completion (`_deliver_parents`), its final failure (`_fail_delivery`)
  and the reaper settle the row to `delivered` / `released` in the same transaction
  that settles the parent job.
* The allowance is **computed**: `brain_sessions.fixes_used` (the bot's inline counter,
  §6.4) plus this session's delivered rows; reserved rows are holds. A regeneration
  replaces the session row (new id), so its allowance starts from zero; the old rows
  stay, unattached (`session_id` set null).
* **Notices.** A settled row's chat notice (uz/ru/kaa/en) is derived on read. The next
  session write folds it into `delivery_notes_json` at its place in the conversation
  and acknowledges the row (`acknowledge_edit_notices`); readers dedupe by job id, so
  a notice is shown exactly once even if the acknowledgement is lost.
* **Answer recovery.** If the session's history ends in an unanswered `edit_slides`
  call and the project's latest edit job carries a finish receipt (committed,
  completed or delivery_failed, with `progress.outcome`) and the job's stamped
  `history_len` equals the conversation length, the load answers the call from the
  receipt, in memory; the next write persists it. A job that failed without a receipt
  is left to the dangling-call repair (an honest error answer).

### 6.3b Session writes (B1-FIX3, Codex Review A, A2/A3)

* **Reads never write.** `GET /chat` loads, projects the delivery rows and answers from
  receipts in memory; nothing is persisted.
* **Every write is a compare-and-swap** on `brain_sessions.version`: the writer names
  the version it read and sets the next. A trigger refuses any update that does not
  advance the version by exactly one (referential actions excepted), so a blind upsert
  fails instead of overwriting. Only columns the writer changed are written.
* **Conflict → reload and merge.** A lost CAS reloads the row and three-way merges
  (base = what the writer read): unchanged-by-us columns take theirs; spend counters
  add deltas; notices union by job; the conversation merges when one side's tail
  extends the other's, or when both answered the same parked call (theirs, already
  continued, wins). Two genuinely diverging conversations raise `SessionConflictError`
  (409 `session_busy`). A replaced session (regeneration) is never merged into.
* **Corrupt persisted state is 409, never 500.** A session row that does not parse
  raises `SessionDataInvalidError` naming the column (409 `session_invalid`); a job row
  whose payload or progress is not an object raises `JobDataInvalidError` (409
  `job_data_invalid`). Both log a structured line; neither repairs or rewrites the row,
  so no allowance is reset and no receipt dropped. A worker that claims a malformed
  job fails it under its own claim instead of looping. Job payloads are validated as
  JSON objects at enqueue.
* **One export-format mapping** (`packages/core/export_formats.py`): session/job
  formats are `ExportFormat` (`pptx_editable`, …); render jobs and exports use wire
  names (`html`, `pptx`, `pdf`); every conversion goes through this module, tested
  against `ExportFileFormat` and the 016 CHECK lists. Session formats are parsed
  strictly: a wire name stored as a session format is invalid state.

### 6.4 Bot

`brain_sessions` gains `revision_id`: the revision the user is editing. The deck is
loaded **from that revision**, not from the head. A bot edit commits
`kind=bot_edit, base=session.revision_id, actor=bot:<telegram id>`. On `conflict` the
bot replies in the user's language (uz/ru/kaa/en) that the deck changed elsewhere,
with a Reload button that sets `revision_id` to the head.

Bot generation and bot edits render in-process (Telegram delivers the local files
at once) and had **no job row**, so their exports could not satisfy I8. After a
committed revision is rendered, the bot inserts a `presentation_render` job already
claimed by itself (`status = processing`, `worker_id = bot:<host>-<pid>-<rand>`,
`payload.revision_id` = the committed revision), heartbeats it while publishing,
registers the exports under that claim, and lands the guarded `complete`/`fail`
(`packages/bot/orchestrators/inline_publish.py`). Inserting it pre-claimed means the
queue worker can never pick it up. A publishing failure fails that job but never
blocks Telegram delivery; the web then shows "render needed" for the revision.

### 6.5 Render jobs

Payload carries `document_id, revision_id, renderer_version, formats` (sorted).
Active-job dedupe moves from `(project_id, job_type)` to `(revision_id,
renderer_version, formats)` for `presentation_render` (a new partial unique index),
because the per-project index would hand a request for the head an already-running
render of an older revision. Every render is queued through `_enqueue_render`
(`finish_generation_job`, and `request_render` behind "Update exports"), which
serializes decisions per (revision, renderer) with a transaction-scoped advisory lock,
skips formats already registered, and **reuses an active render whose formats cover
the rest** (superset match, B1-FIX2), so overlapping requests share one job instead of
rendering twice. A render job gets `render_max_attempts` attempts
(`PlatformConfig.render_max_attempts`, env `RENDER_MAX_ATTEMPTS`, default 3 = 2
automatic retries): `fail_job` on a render with attempts left re-queues it; render
failures are mostly transient (a Chromium crash, an OOM on the 4 GB VM, an upload
error), a retry is free (renders are never charged) and cheap (it renders only what is
missing), and three attempts bound the user's wait for a refund to about three render
times. A render job first reads which requested formats are
already registered for its (revision, renderer) and renders only the missing ones; if
none are missing it completes at once. Every rendered format must upload, verify and
register (or find its first writer), or the job fails. A worker whose code is a
different renderer than the payload names refuses before rendering. A lost claim
aborts without registering and without completing; the reaper owns that job's
outcome.

### 6.6 Failure and refund (B1-FIX, Codex finding 4)

A refund used to be a second write after the failure: `JobQueue.fail()` committed
`failed`, then the worker inserted the ledger row. A crash or insert error between
them left a failed, charged job with no refund, and the reaper never revisits a
terminal row. Now the database settles both in one transaction:

- `fail_job(job_id, worker_id, claim_token, step, message)` locks the job, requires
  the caller's claim (returns false otherwise: the job's holder settles it), marks it
  `failed` and, if `payload.deducted_amount` is a positive amount, inserts the
  `refund` row stamped with the job, unless one exists.
- `reap_stale_jobs` re-queues stale jobs with attempts left and settles the rest
  through the same internal `_settle_failure`, skipping rows another transaction
  holds (a worker mid-finish or mid-fail). A missing heartbeat counts as stale.
- The job row lock serializes every settler, and the unique index backs it up.
- The worker no longer refunds anything. Application refunds left: the enqueue
  route's undo of a losing duplicate deduction (it belongs to no job), and the bot's
  presentation and article failure refunds, which have no job row (B8, §10).

### 6.7 Paid delivery (B1-FIX2, Codex B1-FIX review blocker 1)

Separating render from generation (§6.1) made a paid generation `completed` before
its files existed, so a render that failed for good left the job completed and
charged. A job that commits now ends one of two ways, each settled exactly once:

- **Delivered.** The render registers every format and completes; `complete_job`
  moves every `committed` job whose `render_job_id` is that render to `completed` in
  the same transaction. No refund.
- **Undeliverable.** The render fails on its last attempt (`fail_job`, or the reaper
  on a dead worker); `_settle_failure` fails it and moves each `committed` job it was
  delivering to **`delivery_failed`**, refunding its charge through the same
  `_refund_job` as `fail_job`, keyed on that job's id, in the same transaction. The
  committed revision stays: it is canonical history, editable, and its exports can be
  requested again.

The reaper also settles a `committed` job whose render row is gone or already
terminal: gone, failed or cancelled → `delivery_failed` and refunded; completed →
`completed`. It reads the render row without locking it, so it cannot deadlock with a
render completing (render lock, then parent locks): a render still active is left to
settle its parents itself. Lock order stays job → document → proposal; a render is
locked before the jobs it delivers.

The web follows the job: the jobs API returns the job's status with its render job's
id, status and progress, and the workspace shows "deck saved — preparing your files"
while `committed`. Every change in that delivery fingerprint re-reads the exports,
polling from 3 s backing off to 30 s whether or not Realtime is connected and whether
or not a deck response exists yet. `delivery_failed` shows the refund and the kept
deck.

## 7. Bugs this fixes (each gets a test that fails before the change)

| Test | Today | After |
|---|---|---|
| a | render of revision Y overwrites `generated/{p}/presentation.*` and `decks` | exports keyed by revision; downloads for head unaffected |
| b | bot edit writes `decks`, head unchanged; web and the next bot turn read the old head | bot commits a revision; head advances |
| c/d | manual save vs AI edit: AI raises or is pre-abandoned | manual commits, AI stored as proposal; two manual saves: one commits, one conflicts |
| e | `create_document_if_missing` on an existing key silently returns; key reuse with other content returns the old revision | duplicate/proposed on true retry, error on reuse |
| f/g | no claim or revision check on export registration | `register_export` fences both |
| h | upload failure swallowed, job completes | job fails; refund once (I11) |
| i | 1 of 3 formats → completed | failed |
| j/k | `for all` RLS lets a client write `decks`/`document_revisions` directly | writes revoked; RLS select-only; ownership checked in functions |
| accept | no proposals exist | accept against the head the user saw commits; a moved head conflicts; retry is idempotent; another user is denied; schema mismatch is rejected; the replaced head stays restorable; both diffs are correct after user edits past the base |
| no-op | an identical autosave appends a revision | `unchanged`, no revision, and a concurrent AI edit on that head still commits instead of becoming a proposal |

## 8. Migration and backfill plan

016 runs in one transaction and is re-runnable (`if not exists`, guarded renames, `do`
blocks that check catalog state):

1. Assert PostgreSQL ≥ 15.
2. Alter `document_revisions` (add columns nullable, backfill legacy rows, then
   `set not null`), rename `content_hash`.
3. Create registry, proposals, exports, validations tables; RLS; revoke privileges.
4. Create functions; drop the three superseded functions.
5. Rename `decks` → `decks_legacy` (its Realtime publication membership is dropped
   first) and revoke every application privilege on it.
6. **Backfill** (inside 016, through `commit_revision`): for every `decks_legacy` row,
   in `(created_at, id)` order, `ensure_document`, then `commit_revision(kind=import,
   base=null, actor='system:migration-016', idempotency_key='import:legacy-deck:<deck
   id>')`. A project with no head gets the deck as its head. A project whose head
   already equals the deck returns `unchanged`. A project whose head differs (bug b:
   bot edits that only reached `decks`) gets the deck as a pending **import proposal**,
   because the base (null) is not the head and `import` is one of the kinds that propose
   on conflict. The user can diff and accept it, so nothing is dropped. Non-object
   `deck_json` is wrapped as `{"legacy_raw": …}`. Rows of non-presentation projects are
   counted and left in `decks_legacy`. Counts are emitted with `raise notice`.
   Re-running returns `duplicate` / `proposed` by idempotency key and adds nothing.
   Then the `decks` view is created and `documents` is published instead.
7. Create `uq_credit_ledger_refund_per_job`, failing closed (B1-FIX, Codex finding 5):
   legacy duplicate refund rows are kept (the ledger is append-only) and every row
   after the first per job is recorded in `credit_ledger_legacy_duplicate_refunds`;
   the index predicate excludes exactly those row ids, so all other and all future
   refunds are covered. 016 raises rather than finish without the index. Active
   legacy jobs without `deducted_amount` get it stamped from the price list in force,
   so the database can settle their refund.

016 persists what it found in `migration_reports` (B1-FIX): every backfill count,
including legacy rows skipped because their project is not a presentation (they stay
in `decks_legacy`), the revision count per (kind, schema_version), and how many
revisions carry an unregistered version (kept and readable; new writes of that
version are refused).

`scripts/backfill_validate_revisions.py` then validates every `import` revision
against `DeckSpec` / `ArticleDocumentContent` in keyset-paginated batches, inserting a
`revision_validations` row (`valid` or `legacy_invalid` with the first errors), and
every pending `import` proposal (a divergent legacy deck) into `proposal_validations`
(B1-FIX), so an owner never accepts a legacy proposal blind. It
skips revisions already validated (resumable, idempotent), defaults to dry-run, and
prints counts. DeckSpec validation is Python; it cannot run inside the migration,
which is why flagging is a separate pass and why the import itself never depends on
validity.

### Rollback

The DOWN block at the end of migration 016: drop the view; rename `decks_legacy` → `decks`;
**re-project** every presentation head into it (it will be stale for revisions
committed after 016); restore the publication; restore 011/013/015
functions; re-grant the old privileges. New columns and tables are left in place
(additive and harmless to old code, which ignores them). Exports written under
`exports/` remain valid objects; old code serves `generated/` keys again, so a render
is needed after rollback. Rollback is lossy only for proposals (old code cannot see
them); they are kept in the table.

## 9. Alternatives considered (overall approach)

- **Keep two tables and harden each writer.** It doesn't scale: seven writers,
  three of them in the bot, each one a chance to drift again. Rejected.
- **Make `decks` canonical and drop revisions.** It loses history, conflict detection
  and proposals. Rejected.
- **Application-level CAS through PostgREST filters** (`update … where head = base`).
  PostgREST cannot do the multi-statement insert-revision + move-head + maybe-propose
  atomically, and any role with table privileges could bypass it. Rejected.
- **Event sourcing with a separate projector process.** Correct, but it adds a moving
  part this scale doesn't need; the view gives the same guarantee synchronously.
  Rejected.

## 10. Decisions taken and open questions

Decided 2026-10-11: `accept_proposal` is replace-head-with-consent (§4.3). The
brief's literal rule (accept only while the proposal's base is the head) would make
every conflict-born proposal unacceptable, because head ids only move forward.

Open:

1. **Bot article outputs** (`article_flow.py:689-701`) write `generated_files` rows that
   contain local filesystem paths, and on a second export they hit the
   `(project_id, file_type)` unique constraint, which is swallowed. That pipeline has
   no documents or revisions at all. Proposal: stop writing those rows (they have no
   correct reader) and leave the legacy article pipeline outside this ADR.
2. **Production PostgreSQL version** must be ≥ 15 for the view. Unverified.
3. **R2 SHA-256 checksum support** on PutObject/HEAD is unverified without R2 access
   (MinIO in CI proves nothing about R2). Since B1-FIX, a store that rejects either
   option (`NotImplemented`, `InvalidArgument`, `InvalidRequest`, `UnsupportedArgument`,
   HTTP 501) gets a plain PUT / plain HEAD and verification falls back to a full GET and
   re-hash (one extra download per export); a rejected digest (`BadDigest`) still fails.
   A real R2 canary is on the handover checklist.
4. **CI S3 stand-in.** S3 stand-in is a community MinIO rebuild because upstream stopped
   publishing images; replace with an official-publisher image (e.g. Chainguard) if one
   is adopted. It is pinned by digest and used only by the CI journey job, with
   throwaway credentials.
5. **B8 — bot generation and refunds.** Bot presentation and article failures still
   refund through `credits.refund` in the bot process (`presentation_flow.py`,
   `article_flow.py`), with no job row and therefore no exactly-once settlement; the bot
   can commit a revision, fail its render and refund. I11 is scoped to queued jobs and
   does not cover them. Moving bot generation onto queued jobs (or giving it job-stamped
   settlement) is B8.
6. **`brain_sessions.fixes_used` (decided 2026-10-15).** Queued (web) edits count only
   from `edit_deliveries`; nothing about them is stored on the session, and a unit test
   asserts no web or worker path writes `fixes_used`. The column remains the counter of
   the bot's inline edit path (which has no job to key a row on) and of pre-016
   history. B8 moves bot edits onto the queue so they create `edit_deliveries` rows;
   after B8 the column becomes read-only legacy history (no new writes).

## 11. Verification

The workstation runs unit tests, pyright and the web typecheck only (8 GB RAM; the
last local stack froze it). Everything that needs PostgreSQL, PostgREST, a browser or
a production Next build runs in GitHub Actions (`.github/workflows/ci.yml`) on pushes
to `ci/**` branches and on manual dispatch, never on `main`:

1. Unit tests, pyright, web unit tests, typecheck, `next build`.
2. SQL tests: a Postgres 16 service container bootstrapped with the Supabase roles
   and grants the migrations expect (`scripts/local_stack/bootstrap.sql`), all
   migrations applied in order from a clean database, then the multi-connection
   pytest suite (`tests/db/`) and PostgREST-token tests against a PostgREST
   container on the same database.
3. Browser journey: API, worker and `next build && next start` (not `next dev`),
   headless Playwright with one worker. Providers are stubbed, R2 is replaced by
   local-disk storage, and no production secrets are used.
4. Pre-change gates (B1-FIX2). Each regression module runs against the schema it
   exists to catch and must fail there for its stated reason, gated by full test id
   (`tests/db/expect_failures.py`): legacy 001–015, baseline 016 (blob e2863406),
   fix1 016 (blob 1d38a9cc, `inventory_fix1.json`). The concurrent property test runs
   once more with every document row lock removed (`NASHR_TEST_MUTATION=no_document_lock`)
   and must fail its linearizability oracle (`inventory_mutation.json`). The journey's
   delivery steps run once against the app as of 8cc000b and must fail
   (`scripts/webshots/journey_inventory_fix1.json`).
   B1-FIX3 adds the fdb14bc tier: `tests/db/test_b1_fix3_regressions.py` on 016 as of
   fdb14bc (blob 07b3809c, `tests/db/inventory_fix2.json`); the `prefix-fdb14bc` job
   runs the unit regressions (`tests/unit/test_b1_fix3_regressions.py`), the web hook
   tests (`packages/web/lib/use-live-job.test.ts`) and the journey console classifier
   tests (against a verbatim copy of fdb14bc's rules) against fdb14bc's application
   (`tests/prefix/*.json`); and the journey's first-sight step runs against fdb14bc
   (`journey_inventory_fix2.json`). Codex A4 (web): the first observed terminal job
   refreshes the deck, and a missing-deck retry (3 s → 30 s) runs whenever a job says
   a revision exists and the page has no deck, independent of fingerprints and
   Realtime. Codex N1: the journey refuses Realtime with `routeWebSocket` (route()
   never intercepted sockets) and accepts a Realtime console error only in a context
   that blocked it and only as the exact handshake-404 refusal; 500 and auth failures
   are defects.
5. The presentation-worker suite, including PPTX determinism and the Chromium PDF
   tests, and its typecheck.

Each run uploads traces, videos, screenshots and logs as short-retention artifacts
and reports the minutes it used.

## Appendix A — inventory (2026-10-11, tree at `a1ab4dc` + uncommitted work)

### A.1 Writers

| Target | Writer | Caller(s) |
|---|---|---|
| `decks` (upsert) | `database.py:553-592` `save_deck` | `presentation_orchestrator.py:942` `_persist_deck` ← `run_full_pipeline:1007` ← bot `presentation_flow.py:448` (in-process generation) and worker `worker_run_job.py:454`; `presentation_orchestrator.py:737` (edit with `persist=None`) ← bot edit `presentation_flow.py:1014` and web chat edit without a document `sessions_core/chat.py:502-512`; render job `worker_run_job.py:253` |
| `decks` (insert/upsert in SQL) | migration 013 `commit_presentation_revision_and_deck` | `database.py:293` ← web AI edit `worker_run_job.py:338` |
| `documents` + first revision | migration 011/015 `create_document_if_missing` | `database.py:216` ← article init `documents.py:122`, design import `design.py:107` |
| `document_revisions` + head | migration 011 `commit_document_revision` | `database.py:270` ← article save `documents.py:194`, article restore `:238`, design save `design.py:154`, design restore `:198` |
| `generated_files` (insert) | `database.py:517` | bot article flow `article_flow.py:689,696` (local paths) |
| `generated_files` (upsert) | `database.py:901` | `presentation_orchestrator.py:914` ← `_upload_rendered:890` |
| R2 `generated/{p}/presentation.{ext}` | `storage.py:318` + `upload` | `presentation_orchestrator.py:885-888` (`generated_key` fallback `:887`) |
| Scripts | `save_deck` | `gate_build2_stage0.py:126,143`, `gate_build2_stage3.py:200`, `gate_build2_stage4.py:139`, `gate_build2_stage5a.py:177`; in-memory stub `wire_stub_api.py:316` |
| Tests (fakes or SQL) | `save_deck` | `test_database_client.py:692-741`, `test_chat_routes.py:156`, `test_brain_session.py:179,829`, `test_presentation_flow_handlers.py:464`; SQL `tests/sql/document_functions.sql`; direct inserts in a private PGlite schema `tests/sql/source-evidence.mjs` |

The web client writes nothing directly; its only direct table read is `projects`
(`chrome.tsx:178`).

### A.2 Readers

| Source | Reader |
|---|---|
| `decks` | `database.py:594` `get_deck` ← bot `store.py:161` (fallback), `design.py:103` (import), `/decisions` `projects.py:392`; Realtime `use-live-job.ts:149`; `backup_restore_verify.py:43`; `gate_build2_stage0.py:101`; probes `_probe_slide_field.py:18`, `_probe_deck_numbers.py:18`, `_forensic_slide11.py:36`, `_forensic_9330c308.py:23,56` |
| document head | `database.py:240` `get_document` ← `documents.py:139,152,189,213,227`, `design.py:99`, `chat.py:247`, `store.py:157`, `worker_run_job.py:323` |
| revisions | `database.py:316` (list) ← `documents.py:216`, `design.py:175`; `database.py:335` (one) ← `documents.py:157,230`, `design.py:189`, `worker_run_job.py:219` |
| `generated_files` | `database.py:537` ← downloads `projects.py:147-166`, share `public.py:90-116` |
| storage keys | signed URLs `projects.py:153,161`, `public.py:98,113`; bot delivers local paths `presentation_flow.py:513,647` (no storage read) |

## Appendix B — `decks` column map

| `decks` column | Source today | Source in the view |
|---|---|---|
| `id` | random at first save; read by nothing except the unused `design_directions` FK | `documents.id` |
| `project_id` | caller | `documents.project_id` |
| `title`, `language`, `audience` | **project row** at save time (`database.py:582-587`) | `projects` row (current) |
| `deck_json` | `DeckSpec.model_dump` | head `document_revisions.content` |
| `created_at` | first save | `documents.created_at` |
| `updated_at` | trigger | head revision `created_at` |

Measured deck sizes (`debug/*.json`, `gate_b_regen_deck.json`): 1–55 KB; images are
URLs. The 2 MiB cap leaves about 40× headroom; the 200 KB latency probe is 4× a real deck.
