-- Migration: 003_decks_unique_project
-- Author: nashr platform
-- Description: Enforce one deck row per project for current-state deck
-- persistence (Build 2, Stage 0). save_deck upserts the project's single
-- current deck on this constraint; a regeneration or a later brain edit
-- updates the same row in place rather than appending history (row history
-- is served by the conversation layer, not the decks table).
--
-- The decks table is greenfield at this point (zero writers before Stage 0),
-- so the unique constraint adds with no deduplication or backfill. The
-- constraint's implicit index supersedes idx_decks_project for project_id
-- lookups, so the standalone index is dropped to avoid a redundant second
-- index on the same column.

alter table decks add constraint decks_project_id_key unique (project_id);

drop index if exists idx_decks_project;

-- ===========================================================================
-- DOWN MIGRATION (commented for reference; run manually to revert)
-- ===========================================================================
-- create index if not exists idx_decks_project on decks (project_id);
-- alter table decks drop constraint if exists decks_project_id_key;
