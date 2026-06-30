-- Migration: 004_brain_sessions
-- Author: nashr platform
-- Description: DB-backed conversational "brain" session for the presentation
-- editing loop (Build 2, Stage 4). One row per project (the conversation layer
-- migration 003 referred to). Holds the serialized tool-calling history, the
-- live SourceProcessingResult the fix tool re-grounds against, the code-side
-- approval state, and the per-session editing budget counters — so the session
-- survives a bot restart and is recoverable from project_id ALONE (the FSM only
-- ever holds the project_id pointer, which a restart may wipe).
--
-- One session per project is a DATABASE invariant (unique(project_id)), exactly
-- like decks: it makes the session recoverable by project_id and forbids
-- proliferation. save_brain_session upserts on this constraint.
--
-- The heavy raster figure bytes live in their OWN column (figures_json), split
-- from the light source text (sources_json): most chat turns are text-only and
-- never need the megabytes of base64 image data, so the common per-turn load
-- selects everything EXCEPT figures_json, and the fix path fetches figures_json
-- on demand. SourceFigure.data is base64 in jsonb (ser/val_json_bytes='base64'
-- on the model) — pydantic's default utf8 mode raises on real PNG/JPEG bytes.
--
-- findings_json is RESERVED for Stage 5's content-critic findings; Stage 4
-- creates the column and never writes it.
--
-- The brain_sessions table is greenfield (zero writers before Stage 4), so this
-- migration is zero-risk: no backfill, no deduplication.

create table if not exists brain_sessions (
    id                      uuid primary key default gen_random_uuid(),
    project_id              uuid not null references projects(id) on delete cascade,
    -- Serialized list[google.genai.types.Content] (serialize_history): the
    -- tool-calling conversation, with thought_signature bytes base64-encoded.
    history_json            jsonb not null default '[]'::jsonb,
    -- The SourceProcessingResult WITHOUT its figures (claims/chunks/metadata/
    -- source_ids/warnings/failed_sources) — the light, text-only half.
    sources_json            jsonb not null default '{}'::jsonb,
    -- The heavy half: list[SourceFigure] with base64 raster bytes, loaded only
    -- when the fix tool fires.
    figures_json            jsonb not null default '[]'::jsonb,
    -- The tier the deck was generated under: drives the editing budget cap and
    -- the image budget apply_fixes_and_render spends. Persisted (not re-derived)
    -- so a restart recovers it from project_id alone.
    package                 text not null
                             check (package in (
                                 'presentation_basic',
                                 'presentation_standard',
                                 'presentation_premium'
                             )),
    -- The export formats originally delivered (ExportFormat values). The fix
    -- tool re-delivers exactly this set, so the session remembers it.
    formats_json            jsonb not null default '[]'::jsonb,
    -- Code-side approval gate state. 'awaiting_approval' means a proposed change
    -- in pending_action_json is blocking the chat loop until a button is pressed.
    approval_state          text not null default 'idle'
                             check (approval_state in ('idle', 'awaiting_approval')),
    -- The proposed fix batch awaiting the user's button press (null when idle).
    -- Durable so the approve callback fires the RIGHT change across a restart.
    pending_action_json     jsonb,
    -- The per-session EDITING CAP is a fix COUNTER, not a dollar budget: a tier
    -- grants a fixed NUMBER of edits (premium 3 / standard 2 / basic 1 — see
    -- SESSION_FIX_LIMITS). fixes_used is incremented only after a fix SUCCEEDS,
    -- so a refused/failed fix never consumes one. An integer the model cannot
    -- influence — no projection to be wrong.
    fixes_used              integer not null default 0 check (fixes_used >= 0),
    -- ACTUAL spend, recorded for billing/analytics ONLY — it does NOT gate the
    -- session (the fix counter does). Both start at zero.
    accumulated_cost_usd    numeric(12, 6) not null default 0
                             check (accumulated_cost_usd >= 0),
    accumulated_image_count integer not null default 0
                             check (accumulated_image_count >= 0),
    -- RESERVED for Stage 5 content-critic findings; unused in Stage 4.
    findings_json           jsonb,
    created_at              timestamptz not null default now(),
    updated_at              timestamptz not null default now(),
    constraint brain_sessions_project_id_key unique (project_id)
);

-- The unique(project_id) constraint's implicit index serves project_id lookups
-- (the recovery path), so no standalone index is created (cf. migration 003).

alter table brain_sessions enable row level security;

create policy brain_sessions_owner_all on brain_sessions
    for all using (
        exists (
            select 1 from projects p
            where p.id = brain_sessions.project_id and p.user_id = auth.uid()::uuid
        )
    );

drop trigger if exists trg_brain_sessions_updated_at on brain_sessions;
create trigger trg_brain_sessions_updated_at before update on brain_sessions
for each row execute function set_updated_at();

-- ===========================================================================
-- DOWN MIGRATION (commented for reference; run manually to revert)
-- ===========================================================================
-- drop trigger if exists trg_brain_sessions_updated_at on brain_sessions;
-- drop policy if exists brain_sessions_owner_all on brain_sessions;
-- drop table if exists brain_sessions;
