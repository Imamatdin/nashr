# Stage 5b Recon Draft (held for Phase 1 gate delivery)

Branch `build1-content-critic`. Read-only recon; every claim carries file:line.

## Q1 — WAY 3 ORIGINATION (unrequested proposals)

### Where a proposal turn would originate
No runtime trigger today. A brain turn only ever runs from an inbound user message: `chat_turn` (`presentation_flow.py:1152`) → `_run_chat_turn(..., user_initiated=True)` (`:1186-1193`). Provenance is hardcoded at the call site; the code comment at `presentation_flow.py:1180-1185` already names the Way 3 seam: "The day the brain (Stage 5) re-delivers on its own initiative — outside a user edit request, or proactively — that path must pass `user_initiated=False` so `requires_approval()` gates it; the provenance is set HERE, never by the model's turn outcome."

An unrequested proposal originates at a NEW CALLER of `_run_chat_turn` (or a new brain invocation) that passes `user_initiated=False` — never from anything the model emits.

### What a proposal turn needs in TurnOutcome
Nothing — by explicit design. `TurnOutcome` (`models.py:69-94`) carries action/history/cost/reply_text/fixes/reason/fix_call_count. A proposal is shape-identical to a requested edit (both `kind="fix"` from `brain_loop.py:246` → `TurnOutcome.fixes` via `driver.py:172-178`). Provenance is deliberately kept OFF the object (`models.py:80-83`). `TurnAction` has no `propose` member on purpose (`models.py:33-47`): "a model that could mark its own change 'pre-approved' would defeat the gate. The machinery branches on `bool(outcome.fixes)`, not on this label." `requires_approval` (`models.py:129-155`): `if not outcome.fixes: return False` / `return not user_initiated`. The documented Stage 5 add point is the `findings_json` observable (`models.py:145-150`): "added HERE — as an additional `or` on an observable the model cannot forge."

### What PendingAction lacks
`PendingAction` (`models.py:49-66`) persists only `fixes` (1..20), `reason`, `call_count` (>=1) → `brain_sessions.pending_action_json` (`004_brain_sessions.sql:56-58`). NO origin marker, no `user_initiated`, no finding linkage — on restart, provenance is unreconstructable (only free-text `reason` survives). `findings_json` column exists but is unmapped/unwritten (`004:22-23, 71-72`).

### Approve/reject flow for parked calls — one function_response per call, both paths (confirmed)
Shared emitter `_append_fix_result` (`presentation_flow.py:955-969`): `count` response parts, never fewer (`:960-968`).
- Approve: `_apply_pending` (`:1092-1109`) → `_dispatch_fix(..., call_count=session.pending_action.call_count)` (`:1103-1108`); every `_dispatch_fix` exit answers with count parts: delivered (`:1075-1083`), exhausted (`:1004-1008`), fix_failed (`:1040-1042`), render_failed (`:1062-1066`).
- Reject: `_reject_pending` (`:1112-1125`) answers each parked call (`:1121` `{"discarded": True}` × call_count), then clears pending, state IDLE.
- No turn may run while parked: `_run_chat_turn` short-circuits to AWAITING_APPROVAL if `pending_action is not None` (`:909-915`) — parked `edit_slides` call is still unanswered in history (dangling-call 400 guard).

### Exact seams + minimal additions
- Seam A (origination): a non-user-message caller passing `user_initiated=False` (comment at `presentation_flow.py:1180-1185`).
- Seam B (authorization observable): the `or` in `requires_approval` (`models.py:145-155`), fed by populated `findings_json`.
- Seam C (persistence): `PendingAction` needs a provenance field (e.g. `origin: user_request | model_initiative | critic_finding`, optional `finding_id`); write `brain_sessions.findings_json` (currently unmapped). TurnOutcome/TurnAction unchanged by design.

## Q2 — RETRIEVAL REALITY

### sources_json vs figures_json
Split in `serialization.py:21-33`: light = everything except figures; figures = base64 raster bytes, lazy-loaded (`004:34-39`; `source.py:207`).
`SourceProcessingResult` (`article_orchestrator.py:176-195`) light half: `claims` (:187), `chunks` (:188), `metadata` (:189), `source_ids` (:190), `warnings`/`failed_sources` (:194-195).
- Claims: `claim_text` 10–500 chars, optional `quote` ≤500, `strength`, `claim_type` (`source.py:116-131`).
- Chunks: FULL parsed source text in ≤10,000-char slices (`source.py:95-113`).
- Presentation path DOES populate chunks: `presentation_orchestrator.py:287` — load-bearing for Tier 1.

### Tier 1 (zero new infra)
In-memory substring/keyword scan over `session.sources.claims[*].claim_text`/`quote` and `chunks[*].text` (+ metadata titles). Matters because the brain today sees only `_BRAIN_CLAIM_CONTEXT_LIMIT = 60` claims (`driver.py:36`, `:239-246`) and chunks are NEVER surfaced (`_context_block` renders roster + claims only, `driver.py:218-226`). Caps: claims-context 60 (display bound only, `driver.py:33-36`); producer caps `chunks max_length=10_000`, `claims max_length=50_000` (`source.py:269-274`); in-session model UNCAPPED (`article_orchestrator.py:187-188`). A search returning raw chunk text injects up to 10k chars/hit into append-only history (cost consequence in Q5).

### Tier 2 (pgvector/embeddings) — what the schema lacks
- No vector extension: only `pgcrypto` (`001_initial_schema.sql:12`).
- No embedding column / table: `source_chunks` (`001:108-119`) has text/page/is_ocr/confidence only; no ANN index.
- Code defers embeddings explicitly: `claim_linker.py:8-11`, `chunker.py:4,8`.
- Net-new needs: vector extension migration; `embedding` column (or `source_embeddings` table) + IVFFlat/HNSW; embed-on-ingest step; RLS-scoped similarity query path (owner policies pattern `001:126-132`).

## Q3 — MEMORY SCHEMA

### What exists per-user
- `users` (`001:18-27`): identity + `language`, `primary_use` enum only.
- `projects` (`001:43-59`): per-user FK; no memory.
- `brain_sessions` (`004:28-76`): per-PROJECT, `unique(project_id)` (:75); `history_json` is the single project's transcript.
Net: no per-user conversation archive, no notes store.

### Three-layer mapping (recon)
- Working session → exists: `brain_sessions.history_json` (per-project).
- Auto-captured history → NEW `user_messages(id, user_id FK, project_id FK nullable, role, text, created_at)`, per-USER, owner-RLS pattern (`001:126-132`).
- Curated notes → NEW `user_notes(id, user_id FK, note_text, category, updated_at)`, per-USER; BRAIN_memory.md: "curated notes that hold whatever turned out to matter", "not a flat row of fields per user", "A correction overwrites, it doesn't accumulate" → update-in-place.
- Keying: history/notes per-user ("A user's notes and history are theirs alone… enforced in the system"); working memory stays per-project.

### Reflection-pass hooks (no background infra — confirmed)
- End of delivery: `presentation_flow.py:495-505` (after render/stash, `_open_brain_session` :498).
- Session open: `_open_brain_session` (`:541-569`) / `create_session` (`:556-562`).
- Post-turn: `_run_chat_turn` branches `presentation_flow.py:917-941`; driver turn boundary `driver.py:127-198`.
- Gate scripts are offline harnesses, not runtime hooks (`driver.py:69-77`).
- NO background jobs: `run.py:56-112` polling/webhook only; compose has bot+redis only; no arq/celery/apscheduler in `requirements.txt`; FSM is `MemoryStorage()` (`app.py:64`); Redis unused by bot (`rate_limit.py:12`). Consequence: reflection must run INLINE in a handler.

## Q4 — PROMPT SLOTS

- `BRAIN_RETRIEVAL` placeholder at `brain_prompts.py:792`; `BRAIN_MEMORY` at `:794`; both "defined but unused in 5a" (`:21`), already in `__all__` (`:819,821`).
- Wiring: `assemble_brain_system` (`:797-813`) joins STANDARD+IDENTITY+ORCHESTRATOR+TOOL_DESCRIPTIONS; enabling 5b = add the two slots to that tuple (block stays byte-stable, grows the ~10.8k-token block).
- Drafts EXIST in `files (6).zip`: BRAIN_retrieval.md (two read-only corpora; "report what's there, not what you expected"; "An empty result is information"; meaning-match; absent-vs-derivable; binary grounding verdict; inform-don't-impose, "the deck wins"; compartmentalization "enforced in the system"; retrieve-when-assumption-would-fill-gap; don't retrieve to stall) and BRAIN_memory.md (three layers; event-driven capture on judgment; "Write the signal, not the transcript"; correction overwrites; reflection pass = end-of-session review + lighter periodic nudge; pull relevant not everything; leave out when unsure).
- Prompt-gated: all judgment/discipline behaviors (search judgment, empty-is-information, inform-don't-impose, capture/selection rules) — pure text into `assemble_brain_system`.
- Code-gated: execute-and-continue tools (loop has none — `brain_loop.py:14-16`); per-user history/notes tables + capture write path; the reflection hook (inline, no scheduler); semantic retrieval (pgvector, Tier 2); compartmentalization enforcement (per-user scoping/RLS in code).

## Q5 — WHAT BREAKS

### (a) brain_loop mixed-turn support
Current: single tool built once (`brain_loop.py:214`); no-tool → reply (`:237-238`); tool → collect fixes and RETURN "fix" immediately (`:240-246`); only malformed-args path continues (`:242-244`). To add execute-and-continue retrieval: (1) multi-tool declarations at `:214`; (2) new branch in `:239-246` dispatching by `call.name` — retrieval executes, appends its function_response to `working` (append rule `:236`), `continue`s; only `edit_slides` returns "fix"; (3) inject a retrieval executor into `run_brain_loop` (currently pure Gemini+parse); (4) `BrainLoopResult` and verbatim-append/thought-signature discipline unchanged.

### (b) Cost per retrieval round-trip
Each iteration = fresh `generate_with_tools` (`brain_loop.py:220-227`), NO caching (`gemini.py:416-430` has no cached_content param; `brain_prompts.py:9-10` defers to 5b). gemini-3.1-pro-preview $2.50/$15 per Mtok (`gemini.py:61`). Static block ≈10.8k tok uncached every iteration = $0.027/iter before history. Illustrative 4-iteration turn (3 searches → 1 fix), input ~15k→28k tok: ≈$0.22 in + $0.03 out ≈ ~$0.25/turn vs ~$0.045 single-shot — ~5-6×, dominated by re-sending the uncached system block. `cached_content` wiring is the mitigation.

### (c) Everything else
- Iteration cap: `BRAIN_LOOP_MAX_ITERATIONS=6` (`:48`) flips from backstop to live budget; 3 searches + re-asks can hit 6 → degrade to reply with `reply_text=None` (`:247-248`), silently dropping the intended fix. Cap must rise or retrieval rounds get excluded from the runaway guard.
- History growth: retrieval appends tool-call + result parts (≤10k chars/hit) permanently into `brain_sessions.history_json`; every later turn re-sends the whole row. Unbounded jsonb growth + compounding input tokens; even text-only turns load history_json (only figures_json is deferred, `004:15-18`).
- Per-project lock vs per-user memory: `_SESSION_LOCKS` per-project (`presentation_flow.py:827-837`), module-local, single-instance. Per-USER notes writes under per-PROJECT locks = racing writes across a user's concurrent projects. Inline reflection lengthens the critical section; `chat_turn` drops overlapping messages while locked (busy guard).
- thought_signature/append-only: a retrieval call must be answered by its function_response IN the same loop before persist/next user turn (400 hazard; one-response-per-call `brain_loop.py:176-191`, `_append_fix_result` `:955-969`). Retrieved context arrives as function_response parts, never by editing the signed prefix (`driver.py:206-208`).

## Consolidated UNCERTAIN list
- System-block token count (~43,150 chars ≈ 10.8k tok) taken as given, not byte-measured by this agent.
- Real per-session sources size unmeasured (in-memory model uncapped; producer caps 10k chunks / 50k claims).
- generate_with_tools caching: no cached_content in signature; full method body not read (low risk).
- Embedding mentions in claim_linker/chunker are verified deferred-comments, not implementation.
- "Gate scripts are offline-only" inferred from driver.py:69-77, not exhaustively verified.
- Redis-unused-by-bot high-confidence but not exhaustively grepped in packages/platform.
- The ~$0.25/turn figure is an illustration; method sound, absolutes depend on the unmeasured bounds.

## PRIORITY BUMP (from 2026-07-03 live probes — owner directive)
**Session re-entry after restart is now a priority 5b item.** Live-proven mechanism: the bot
restarted at deploy → `MemoryStorage` wiped the FSM → the state-scoped `edit_with_ai` handler
no longer matched → the P0-2 fallback router answered the stale-button toast (working as
designed). Consequence priced concretely: EVERY restart orphans EVERY delivered deck's Edit
button. The session data survives by design (`brain_sessions` keyed by project_id, recoverable
by `load_session(project_id)` alone — store.py); ONLY the re-entry path is missing (something
must re-associate an incoming callback/message with its project when FSM state is gone — e.g.
a stateless `edit_with_ai` handler that recovers project_id from the message/session instead
of FSM data, or FSM storage moved to Redis which is already in compose but unused).

## Notes added by coordinator (Fable)
- Line numbers for presentation_flow.py in Q1/Q3/Q5 reflect the POST-Phase-0 working tree (the busy guard shifted lines by ~+23 after :1147).
- Phase 1 prep (separate report) confirmed SDK 2.0.1 supports caches.create with system_instruction+tools in CreateCachedContentConfig (types.py:14359-14409), GenerateContentConfig.cached_content (types.py:5983-5988), and usage_metadata.cached_content_token_count (types.py:7791-7794); logging seam = _extract_usage (gemini.py:549-568) + the two gemini_call_complete extra dicts.
