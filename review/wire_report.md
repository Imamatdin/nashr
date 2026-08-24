# Session W — coherence wiring (P1 → P2 → P3)

Branch `wire/coherence`, off `main` @ `c9a84cd`.
Ground truth for every G-number: `review/coherence_audit.md`.

**⚠ MERGE ORDER WAS REVERSED MID-RUN.** The brief said Session W merges to
`main` first and Session L rebases after. That is no longer what happened:
Session L relayed a founder decision that `site/landing` merged **first**, and
Session W verified it independently rather than taking the relay on trust —
`origin/main` moved from `c9a84cd` to **`7c1d35f`** (a `--no-ff` merge of the
marketing site), with `c9a84cd` still an ancestor, so main moved forward and was
not rewritten.

Consequence for this run: **Session W rebases onto `origin/main` before its
final push**, instead of the other way round. Merge to `main` remains
human-gated — the builder does not merge.

The predicted conflict surface (`packages/web/package.json` /
`package-lock.json`, where the marketing site added `three` and `@types/three`
for one lazily-loaded scene on `/maqola`) turns out to be **empty**. Measured,
not assumed:

```
git diff --name-only c9a84cd..origin/main      -> 33 files
git diff --name-only c9a84cd..wire/coherence   -> 54 files
comm -12 (both, sorted)                        -> 0 files
```

The two branches touch entirely disjoint paths — Session W never opened
`package.json` — so the rebase should replay without a single conflict. If one
appears anyway, that is new information and the rule is to stop and look, not to
resolve it by reflex.

**⚠ OPERATIONAL CONSTRAINT — do not run `npm ci` in this checkout.**
`packages/web/node_modules` in Session L's worktree (`../nashr-landing`) is a
Windows junction to **this** tree's install. `npm ci` prunes it and would delete
`three`, breaking the landing branch's build until an install is re-run there.
`npm install` is safe; `npm ci` is the one to avoid.

### ⚠ Shared working tree — read before reviewing any commit

Session L ran in the **same working directory**, sharing one `HEAD`. Two
incidents, both resolved, both relevant to how these commits must be read.

**Incident 1 — L's commit landed on Session W's branch.** During the P1 build,
`HEAD` was on `wire/coherence` when Session L committed `a2426ad`
("feat(site): marketing shell and sitemap", 18 files, +2591, **100 %
`packages/web/**`**). Branch layout that resulted:

```
site/landing              -> c9a84cd   L's own branch — does NOT carry their commit
wire/coherence            -> a2426ad   Session W's branch — DOES carry it
session-l-rescue/a2426ad  -> a2426ad   safety ref created by W; purely additive
```

Consequences for the reviewer and the merge:

* **`a2426ad` is not Session W's work and must not be read as such.** Nothing
  of W's is inside it; W's phase commits sit *on top of* it.
* **RESOLVED by the founder at the P1 gate.** `wire/coherence` was reset to
  `c9a84cd` and Session W's two commits cherry-picked onto it, so the pushed
  branch contains W's work ONLY and the stated merge order holds. L's commit
  is preserved on `wire-backup-p1` and `session-l-rescue/a2426ad`, and Session
  L has since moved to its own git worktree (`../nashr-landing` on
  `site/landing`), which ends the shared-HEAD collision structurally.
  Historical note, since it explains the branch's shape: before that fix,
  **the merge order could not be achieved by merging this branch as-is** — merging `wire/coherence` into `main` would drag L's
  unreviewed marketing commit in first. The clean resolution at the human gate
  is to **cherry-pick Session W's phase commits onto `main`**, or to
  fast-forward `site/landing` to `a2426ad` and reset `wire/coherence` back to
  `c9a84cd` before W's commits are replayed. W deliberately did **not** do
  either: rewriting a live session's branch state is what caused this.
* `session-l-rescue/a2426ad` exists so L's commit is reachable no matter what
  happens to `wire/coherence`. It is safe to delete once `site/landing` carries
  the commit.

**Incident 2 — a tree-clearing accident in Session L, since restored.**
Verified from Session W's side after the restore: all 18 files of `a2426ad`
present (16 byte-identical to the commit, 2 carrying ongoing edits),
`packages/web/app/page.tsx` back, index clean. Session W's own work was
unaffected — re-proven by re-running `scripts/wire_p1_curl.sh` end to end
against the real routers (26/26 calls, status codes unchanged, zero 500s).

**Standing rules W followed throughout:**

* **Every commit is path-scoped to an explicit file list**
  (`scripts/wire_commit_paths.txt`). No `git add -A`, no `git commit -a`. If a
  `packages/web/**` marketing file ever appears in a Session W commit, that is
  a defect — check the commit's file list, not just its diff.
* W ran **no destructive git command** at any point: no reset, checkout,
  clean, stash, or restore. The only ref W created is the additive rescue
  branch above.
* Off-repo backups were taken so neither session depends on the working tree
  surviving: W's own work (13 created files + a patch of every modification)
  and a point-in-time snapshot of L's untracked files.

Session W's P2/P3 web work touches `app/projects/[id]/**`, `app/new/**`,
`app/p/**`, `app/login/**`, `app/auth/**`, `lib/**`, `components/bui/**`,
`components/chrome.tsx`, `components/ui.tsx` — disjoint from L's `app/page.tsx`,
`app/(marketing)/**`, `components/marketing/**`. If that stops being true, the
rule is STOP and report, not merge by hand.

---

## PHASE 1 — BACKEND SEAMS

Commit: **`fd38073`** — `feat(api): wire (P1) — backend seams for job discovery,
chat editing, credits` (30 files, **0** under `packages/web`)
Commit: **`0842ec4`** — `docs(review): wire (P1) gate report, architect bundle,
route transcript`
Remote ref (verified with `git ls-remote origin wire/coherence`):
`0842ec484bd2a17146f2db4902466d7c4d7348c9  refs/heads/wire/coherence` —
identical to the local tip.
Bundle for the architect: `review/wire_p1_bundle.txt` (30 files, 14 556 lines)
Curl transcript: `review/wire_p1_curl.txt` (26 calls, every new/changed route,
success **and** failure)

### 1.0 Route table

| # | Method / path | Handler | Tests |
|---|---|---|---|
| 1.1 | `GET /jobs?project_id=&job_type=` | `packages/api/routes/jobs.py:324` `get_latest_project_job` | `tests/unit/test_jobs_routes.py` |
| 1.1 | `GET /jobs/{job_id}` (extended `JobView`) | `packages/api/routes/jobs.py:360` `get_job` | `tests/unit/test_jobs_routes.py` |
| 1.2 | `GET /projects/{id}/chat` | `packages/api/routes/chat.py:200` `get_chat` | `tests/unit/test_chat_routes.py` |
| 1.2 | `POST /projects/{id}/chat` | `packages/api/routes/chat.py:240` `post_chat` | `tests/unit/test_chat_routes.py` |
| 1.2 | `POST /projects/{id}/chat/approve` | `packages/api/routes/chat.py:333` `approve_pending` | `tests/unit/test_chat_routes.py` |
| 1.2 | `POST /projects/{id}/chat/reject` | `packages/api/routes/chat.py:378` `reject_pending_action` | `tests/unit/test_chat_routes.py` |
| 1.3 | `GET /credits` | `packages/api/routes/credits.py:95` `get_credits` | `tests/unit/test_credits_routes.py` |
| 1.3 | `GET /credits/ledger?limit=` | `packages/api/routes/credits.py:103` `get_credit_ledger` | `tests/unit/test_credits_routes.py` |
| 1.3 | `GET /pricing` | `packages/api/routes/credits.py:135` `get_pricing` | `tests/unit/test_credits_routes.py` |
| 1.4 | `POST /jobs` (+ `topic`) | `packages/api/routes/jobs.py:191` `enqueue_job` | `tests/unit/test_jobs_routes.py` |
| 1.4 | `POST /projects/{id}/interview` | `packages/api/routes/projects.py:281` `get_interview` | `tests/unit/test_projects_routes.py` |
| 1.5 | `POST /auth/refresh` | `packages/api/routes/auth.py:109` `refresh_session` | `tests/unit/test_api_auth_routes.py` |
| G19 | `GET /public/decks/{token}` (+ `downloads[]`) | `packages/api/routes/public.py:63` `resolve_shared_deck` | `tests/unit/test_projects_routes.py` |

Supporting code (no route of its own):

| File | What it adds |
|---|---|
| `packages/sessions_core/chat.py` | the Way-2 turn machinery, split turn-side / apply-side |
| `packages/platform/jobs.py` | `GenerationJob.started_at`, `JobQueue.get_latest_job` |
| `packages/platform/credits.py` | `CreditEntry.generation_job_id`, `refund(generation_job_id=)`, `has_refund_for_job` |
| `scripts/worker_run_job.py` | `presentation_edit` executor; job-stamped refunds; `topic` threading |
| `packages/bot/orchestrators/presentation_orchestrator.py` | `run_full_pipeline(topic=)` → `apply_interview(topic=)` |
| `packages/presentation/editorial.py` | renders `user_brief` into the editorial content summary |
| `scripts/wire_stub_api.py`, `scripts/wire_p1_curl.sh`, `scripts/wire_bundle.py` | evidence tooling |

### 1.1 Job discovery (R1 → G3 / G5 / G23 / G11 / G17 / G22)

`GET /jobs?project_id=` returns the project's latest job of `job_type`
(default `presentation_generation`), in the same `JobView` shape as
`GET /jobs/{id}`, 404 when there is none.

**Deviation from the literal spec, deliberate:** the spec says "latest job for
the project (any status)". It is scoped to a job TYPE, defaulting to the
generation job. Once edit jobs exist (1.2), "latest job of any type" would let
a two-second chat edit displace the workspace's whole state machine — P2.0
derives `no_job | queued | processing | failed | ready | …` from this row. The
chat pane tracks its own edit job from the id `POST /chat` hands back, and
`GET /chat` reports `applying_job_id` for a returning user.

`JobView` gained `created_at`, `started_at`, `heartbeat_at`, `completed_at`,
`package`, `deducted_amount`, `refunded`.

`refunded` is a **fact, not an inference.** `credit_ledger.generation_job_id`
has existed unused since migration 001; `CreditLedger.refund()` now stamps it
and `has_refund_for_job` reads it back by exact match. Two consequences worth
the architect's attention:

* The probe fires **only for a failed job** — a queued/processing/completed row
  cannot have been refunded by the worker's failure path, and the web polls
  this shape every few seconds. Pinned by a test that asserts the ledger is
  never touched for the other statuses.
* The enqueue route's **lost-race refund is deliberately NOT stamped.** That
  refund undoes the LOSING deduction while the winning job's charge stands;
  stamping it with the winner's id would make a live, correctly-charged job
  report itself refunded. Pinned by a test.
* **Jobs that failed before this deploy carry a NULL `generation_job_id` and so
  report `refunded: false`.** They were refunded; the evidence just is not
  linkable. The web copy must therefore never say "not refunded" — it says the
  refund fact when it has it, and stays silent when it does not.

### 1.2 Conversational editing (R2 → G4, and 5A/5B/5C/5D inventory)

The whole Way-2 engine existed and was reachable only from Telegram. It is now
an HTTP surface, with the turn and the apply split across processes:

```
POST /projects/{id}/chat
  → gate: owner → CHAT_ACTION limiter → active generation/edit job? → 409 brain_busy
  → sessions_core.run_web_turn:  load session → one brain turn
       ├─ no fixes                 → 200 {kind:"reply"}
       ├─ model-initiated fixes    → park pending_action → 200 {kind:"approval_required"}
       ├─ allowance spent          → 409 {reason:"fixes_exhausted", fix_limit}
       └─ user-asked-for fixes     → PARK (call left unanswered) + persist
  → enqueue presentation_edit job carrying the batch → 200 {kind:"fix_ready", job_id}

worker: JobType.PRESENTATION_EDIT → sessions_core.dispatch_fix
  → orchestrator.apply_fixes_and_render → persist deck → render → R2 stable keys
  → answer the parked call → consume ONE fix allowance iff a file was delivered
```

**The interlock is the unanswered tool call.** Gemini refuses a turn that
resends a dangling `function_call`, so a session whose history ends in one
cannot run another turn. That is already how the approval gate blocks input;
the fix park reuses it. It is durable (`brain_sessions.history_json`), so it
survives a restart of either process — an in-process lock could not, since the
API and the worker are different containers.

What an unanswered call cannot notice is that the job carrying its answer died.
Three things close that:

1. the worker's own failure path answers the call before failing the job;
2. `repair_dangling_call` heals a session that has a dangling call while **no**
   edit job is active — checked at the top of every turn;
3. `abandon_parked_fix` un-parks immediately when the enqueue itself fails.

**Money contract, evidenced:** a fix turn's edit job payload carries no
`product_type` and no `deducted_amount`, so the worker's refund helper finds
nothing to refund and the ledger is never touched. Pinned two ways — a route
test asserting the ledger fake recorded zero calls and the payload carries
neither key, and `_execute`'s explicit `refundable = job_type is
PRESENTATION_GENERATION`. The allowance decrement is pinned separately in
`tests/unit/test_sessions_core_chat.py`: `+1` on a delivered fix, `+0` on a
render that produced no files, `+0` on a raising fix chain, and a spent
allowance refuses **before** the runner is called at all.

**Layering.** `packages/sessions_core` holds the machinery; the orchestrator
arrives as an injected `FixRunner` Protocol, so nothing in the package imports
it at module scope. The API imports `sessions_core` and
`packages.bot.sessions` (typed session objects + store) — never
`packages.bot.handlers`. The transitive `aiogram` import (via
`SourceProcessingResult`, which lives in `article_orchestrator`) is inherited,
not introduced: `scripts/worker_run_job.py` already crossed that line.

**Known debt, deliberately unpaid:** the bot's own `_dispatch_fix` was left
untouched, so the apply logic now exists twice (the bot's copy additionally
stashes local files for Telegram delivery, which the web has no use for).
Rewiring the bot onto the shared core needs its own gate and its own bot-side
regression run; doing it inside this phase would have put the live Telegram
edit path at risk for no web gain.

### 1.3 Credits visibility (R4, read half)

`GET /credits`, `GET /credits/ledger?limit=` (1–100), `GET /pricing`.
No top-up, invoice or order route — the merchant question is open, so the web
gains a way to SEE money and no way to spend it.

`GET /pricing` is unauthenticated (prices are public, and the approval card
needs them before a first-time user has done anything) and joins the three
facts the card has to state from their real owners: `CreditLedger.PRICING`
(what the enqueue route actually charges), `image_budget_for_package`
(SPEC §8), `session_fix_limit` (the post-delivery edit allowance). Free-credit
caps ride along so the reward copy can state real limits.

The ledger's `balance` is computed over the FULL history, never the returned
page — a truncated list must not imply a smaller balance. Pinned by a test
whose fake returns a 2-row page and a balance those rows cannot produce.

Note for the architect: `packages/core/constants.PRICING_UZS` is a THIRD price
table. It has no reader outside `tests/unit/test_constants.py` and different
keys; it was left alone rather than half-merged, and is logged here as debt.

### 1.4 Intent threading (R3, backend half → G1 / G2)

`EnqueueRequest.topic` → payload → worker → `run_full_pipeline(topic=)` →
`apply_interview(topic=)` → `PresentationInterviewAnswers.user_brief` →
`EditorialPass._build_content_summary`.

The brief is folded on **after** the interview engine has resolved everything
else, so it cannot become an answer or change a default. In the prompt it is
framed as steering only: choose emphasis, ordering and framing; never assert
anything it says unless a source claim carries it; if it asks for material the
sources do not support, cover what they do and leave the rest out. The
grounding hard stop downstream is untouched — a brief the sources cannot
support still refuses and refunds rather than being fabricated to.

**`POST /projects/{id}/interview` has a contract limit the founder should
decide on before P2.3 is built.** The only place processed sources
(claims/chunks/metadata) are persisted today is the brain session the WORKER
writes **after** a run. Nothing processes sources before enqueue on the web
path. So on a first-ever run this route always answers
`409 {"reason":"sources_not_ready"}`, exactly as specified — the questions
become available for a re-run, not for the first one.

The alternatives are (a) build pre-enqueue source processing (new backend
capability, explicitly out of scope for this run), (b) run the interview
against the raw uploaded text without claim extraction (cheaper questions, no
domain detection), or (c) accept it: P2.3 offers "Decide for me" as the
first-run path and the questions appear on the second. **This run implements
the spec literally (c) and flags it here.** P2.3 will be designed so the 409
routes to "Decide for me" rather than dead-ending.

### 1.5 Session refresh (R5, backend half → G6 / G15)

`POST /auth/refresh` re-mints the 1 h JWT from a still-valid one. A **sliding
session**, not a refresh-token scheme: no second credential is introduced, so
the stored-credential surface stays exactly one short-lived JWT.

The consequence, stated rather than papered over: it **cannot rescue an
already-expired token** — `Authenticated` rejects it first. P2 therefore
refreshes PROACTIVELY (a timer that fires ~5 minutes before `expires_at`) and
treats a 401-triggered attempt as a fallback that will usually fail. Pinned by
a test that asserts the 401/`expired` behaviour on purpose.

### 1.6 Error contract

Every route added or changed here answers 4xx/5xx with
`detail={"reason": <machine_code>, …}`. Reason codes introduced:
`brain_busy`, `session_not_ready`, `fixes_exhausted`, `no_pending_action`,
`edit_not_queued`, `sources_not_ready`. Pre-existing bare-string details
(`project_not_found`, `job_not_found`, `deck_not_ready`, `not_found`, the auth
reasons) were left stable rather than churned; P2's `lib/errors.ts` normalises
both shapes.

### Adjacent defect found and fixed (NOT in the original scope)

`docker-compose.yml`'s `api` service carried **no R2 environment**, while
`POST /sources/presign` and `GET /projects/{id}/deck` have signed R2 objects
since P3. Without those vars `FileStorage` silently falls back to local
filesystem — presigned uploads and deck URLs pointing inside the container.
The R2 block is added. Session W also makes the API run a real Gemini turn, so
the LLM/Vertex env and the `vertex-key.json` mount are added too (the comment
that said the auth tier deliberately carries no Google credential is now
obsolete and was replaced, not deleted silently).

**HUMAN-GATED / operator action:** compose changes need `docker compose up -d`
on the VM, and the `api` container now needs `vertex-key.json` present at the
repo root on the host (the worker already mounts it). No migration is required
by this phase — `credit_ledger.generation_job_id` and `generation_jobs.started_at`
both already exist (migrations 001 and 006).

### P1 verification

| Check | Result |
|---|---|
| `python -m pytest tests/unit` | **1797 passed, 9 skipped** (baseline before this phase: 1672) |
| `ruff check` (every file this commit touches) | All checks passed |
| `ruff format --check` (same set) | 26 files already formatted |
| `pyright packages/` + every changed file | **0 errors** in the changed set |
| Route transcript | 26/26 calls; 16×200, 2×401, 4×404, 3×409, 1×422, **zero 5xx** |
| Credentials in transcript | none — bearer redacted in the echoed command, minted JWTs redacted in bodies |
| Files under `packages/web` in this commit | **0** |

The one pyright error the repo reports (`packages/academic/providers/arxiv.py:73`)
is pre-existing local drift on a file this run never opened; `docs/BUILD_STATE.md`
already records it as confirmed on clean HEAD via a stash round-trip.

**How the P1 test suite was built.** Four parallel agents wrote it against a
written contract list, then an adversarial verifier was asked to refute it. That
verifier found **ten** places where a test passed without proving anything — a
`hasattr` standing in for the "no pipeline re-run" guarantee, an entirely
untested worker executor, `except` branches no fake could reach, a tautological
ordering assertion, and a "localised" test that only ever posted the default
language. A second round closed all ten. Two of the closures were confirmed by
*mutation*: flipping `refundable = True` in the worker and deleting
`abandon_parked_fix` from the route each made exactly the intended test fail
before the source was restored byte-for-byte.

The first verifier's own report is worth quoting as the standard applied here:
a green suite that proves nothing is worse than a red one.

### Bug found by the test round, and fixed

`_run_presentation_edit` filtered malformed entries out of `payload["fixes"]`
instead of rejecting the batch. A payload of `[{valid}, "junk"]` would apply
*half* of an approved batch, consume the tier's fix allowance for it, and report
success — the user pays an edit for a change they never fully got.
`apply_fixes_and_render` documents ATOMIC batch semantics, so its input parsing
now matches: one bad entry fails the whole job. The mixed-batch case (the one
that actually slipped through) is pinned by a test.

### Contracts a reviewer should try to break

| Contract | Guarded by |
|---|---|
| a fix turn never charges | `test_chat_routes.py` (ledger untouched, payload unpriced) + `test_worker_and_backup.py::test_failed_edit_refunds_nothing_but_failed_generation_does` |
| the allowance decrements iff a file was delivered | `test_sessions_core_chat.py` — +1 delivered, +0 render-failed, +0 raised, refuses before calling the runner when spent |
| no failure path wedges the conversation | `test_sessions_core_chat.py` (repair/abandon) + `test_chat_routes.py` (both enqueue-failure branches assert `has_dangling_call == 0`) |
| `refunded` is read, never inferred | `test_credit_ledger.py::has_refund_for_job` (cross-user, wrong-action, NULL-id cases) + `test_jobs_routes.py` (ledger never probed for non-failed jobs) |

### What P1 does NOT prove

The stub server exercises the real routers, models and gate order over
in-memory Supabase/R2/ledger/queue. It does **not** prove: a real Gemini turn
through `GeminiBrainDriver`, a real `presentation_edit` job running
`apply_fixes_and_render` end to end on the VM, a real refund row, or the
compose changes taking effect. Those stay human gates — the same boundary every
prior phase drew.

---

## PHASE 2 — WORKSPACE REBUILT ON TRUTH

### 2.0 State model (designed at the P1 gate, built in P2)

`/projects/[id]` derives its state from **PROJECT + LATEST JOB** (`GET /jobs?project_id=`),
never from `?job=`. `?job=` degrades to an optional focus hint.

| State | Entered when | Screen | Enqueue CTA |
|---|---|---|---|
| `article_project` | `project.type != "presentation"` | "Maqola — tez kunda", correct copy, **no price** (G13) | never |
| `archived` | `project.status == "archived"` | read-only, restore action (G37) | never |
| `no_job` | 404 `job_not_found` | sources + composer + priced start | **yes** (only here) |
| `queued` | job `queued` | LoadingState + `startedAt` from `created_at` (G17) | no |
| `processing(step)` | job `processing` | TaskRows honouring `progress.total`, tolerant of unknown steps (G39); stalled banner when `heartbeat_at` > 45 s (G17) | no |
| `failed(reason, refunded)` | job `failed` | mapped reason + refund fact from `JobView.refunded` (G11) | separate, explicitly-worded regenerate with the price shown |
| `completed_no_deck` | job `completed`, `/deck` 404 | "fayllar tayyorlanmoqda" **and keeps listening** for the deck row (G7) | no |
| `ready` | deck present | split-view workspace | separate regenerate, price shown |

The invariant the audit's G3/G5 exist to kill: **the idle pay button cannot
render over a generating, failed or ready project.** It renders in `no_job`
only; `ready`/`failed` get a differently-worded regenerate that states the
charge. `existing: true` on enqueue → "charge refunded, joined the running
job" (G23).

Two states can be true at once and are composed, not switched: an `applying`
edit job (from `GET /chat.applying_job_id`) overlays `ready` — the deck stays
on screen while a fix re-renders. That is why 1.1's discovery route is scoped
to the generation job type.

### Founder decisions taken at the P1 gate

**Interview (2.3) — decided: ship the current behaviour.** First run offers
"Decide for me", honestly labelled with what was decided; the interview appears
on subsequent runs, when the brain session holds processed sources.
`SOURCE_PROCESSING` pre-enqueue wiring is **deferred to the next run and must
not be built here.** The 409 `sources_not_ready` path is therefore a designed
state, not a failure: P2.3 routes it into "Decide for me" rather than an error.

### 2.x commits

| Commit | Scope |
|---|---|
| `d15ccf6` | 2.0 foundation — state model, error map, session refresh, API client |
| `154cde0` | 2.1 workspace — split view, chat spine, Realtime, live state |
| `8092f73` | 2.3 + G19 — clarification turn on `/new`, share view that gives |
| _(pending)_ | 2.4 money visibility · 2.6 folio resilience · shot matrix |

### What P2 changed, against the audit's own framing

**The enqueue CTA is now unreachable from the wrong states.** Not "fixed" —
unreachable. `deriveWorkspaceState` returns `canEnqueue` true in exactly one
state, and the page has no other path to a priced button. G3 and G5 were one
defect with two symptoms; both close here.

**The conversation exists.** The audit's bar B2 ("conversation is the spine")
scored zero: no chat on web at all, while the entire Way-2 engine shipped
bot-side. `/projects/[id]` is now a split view with the thread beside the
artifact, and a fix is a message. G4 closes; 5A/5B/5C/5D's inventory becomes
reachable.

**Errors stopped being machine output.** The §4 ledger's 22 sites route through
`lib/errors.ts`. The rule the tests enforce is that a raw string can never reach
a title or message, even for a reason code the catalog has never seen.

**Two honesty corrections that were not on the gap list**, both found while
building and both worth naming because they are the kind of thing a green build
hides:

* `{someUnknownError && <JSX/>}` renders `unknown`, which React rejects. It was
  in all four of the workspace's error guards. tsc caught one; the other three
  were the same bug waiting for a different state.
* An `<iframe onError>` was commented as recovering a rotted signed URL. It does
  not — an iframe does not fire `onError` for an HTTP error inside it, because
  R2 serves its own body and the frame counts as loaded. The comment was wrong
  on two surfaces. Both are corrected, and the share view gained the visible
  "Yangilash" control the recovery actually needs. The agent that built that
  surface flagged its own work here rather than letting the comment stand.

### P2 gate

Commits: `d15ccf6` · `154cde0` · `8092f73` · `c1d4811` · `2d02df7`

| Check | Result |
|---|---|
| `npx vitest run` (packages/web) | **169 passed** |
| `python -m pytest tests/unit` | **1797 passed, 9 skipped** |
| `npx tsc --noEmit` | clean (filtered of `.next/types` cache for routes that live in the other worktree) |
| Shot matrix | **62 shots, 62 OK**, `review/wire_shots/` |
| `packages/web` marketing files touched | **0** |

Shots are untracked, matching every prior run's convention
(`review/coherence_shots/`, `review/redesign_shots/` are likewise local).

**Matrix contents.** All eight workspace states × light/dark × 1440/390
(`no_job`, `queued`, `processing`, `failed`+refund, `completed_no_deck`,
`ready`, plus `article_project` and `archived`); the chat thread, the inline
approval card, an applying edit, the locked-no-deck state, a fix-turn
round-trip and a spent allowance; `/hisob` in four combinations plus empty and
unreachable; `/new` empty and with the clarification turn, plus the
first-run "decide for me" path; 402, 429, an unreachable folio, and
session-expiry; the share view with downloads and its 404.

### What the shot matrix caught that the tests could not

All four were disagreements *between parts of a screen*, which is precisely
what a value-level test cannot see:

1. **The mobile default pane hid the work.** Below 1024px the deck tab was the
   default, so a phone user opening a running or failed project saw an empty
   deck placeholder while the run panel sat behind an unpressed tab.
2. **The header contradicted the body** — "Tayyor" above "order a
   presentation", because the badge read the denormalised `projects.status`
   column instead of the derived state.
3. **The failure copy discarded its one useful fact.** A grounding hard stop at
   the design step read as generic "our fault, try again"; the step name was
   available and thrown away.
4. **The balance chip wrapped onto three lines at 390px.** The agent that built
   it reported honestly that it had run `tsc` and `vitest` but never rendered
   the surface.

### What P2 does NOT prove

* **Realtime was never exercised end to end.** The stub environment has no
  websocket, so every shot's live state arrived via the polling fallback. The
  channel idiom, the payload mapping and the fallback's backoff are unit-tested
  and structurally identical to the proven pattern, but the socket path is
  verified by construction, not by observation. The brief asks for a recording
  of a step transition arriving without a poll; that needs a real Supabase and
  is a **human gate**.
* **No real model turn, no real edit job, no real refund row.** The chat
  surface is shot against a scripted driver.
* **Deck iframes point at `about:blank`** in every fixture, so the black frames
  in deck shots are fixture artifacts, not findings — the same caveat the
  original audit recorded.

---

## PHASE 3 — COHERENCE SWEEP

Audit long tail in severity order, excluding the standing deferrals (G16 cancel
backend, i18n G27, payments purchase flow, article surface beyond the guard,
and now `SOURCE_PROCESSING` pre-enqueue).

**Added to P3 by the founder at the P1 gate:**

* Scope `ThemeProvider` and the theme no-flash script to **app routes only** —
  the `(marketing)` route group must ship **zero theme JS**.
* Audit root-layout font loading: subsetting and `display: swap`.
* Re-measure `/maxfiylik` LCP; **target < 2.5 s**.

These touch `app/layout.tsx` and the theme module, which are shared with the
marketing route group Session L owns. Sequencing note: L now lives in its own
worktree on `site/landing`, so this work lands on `wire/coherence` and L rebases
onto it — the same order as the rest of the run.

---

## PHASE 3 — COHERENCE SWEEP

_(not started)_
