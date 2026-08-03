-- ============================================================================
-- 008_realtime_publication — P2 UI polling/subscription surface
--
-- HUMAN-APPLIED. Do not run from code.
--
-- Adds generation_jobs and decks to the supabase_realtime publication so the
-- web UI can subscribe to job progress and deck updates (RLS owner-SELECT
-- policies already scope what each user can see). Guarded so re-running the
-- file is a no-op.
-- ============================================================================

do $$
begin
    if not exists (
        select 1 from pg_publication_tables
        where pubname = 'supabase_realtime'
          and schemaname = 'public' and tablename = 'generation_jobs'
    ) then
        alter publication supabase_realtime add table generation_jobs;
    end if;
    if not exists (
        select 1 from pg_publication_tables
        where pubname = 'supabase_realtime'
          and schemaname = 'public' and tablename = 'decks'
    ) then
        alter publication supabase_realtime add table decks;
    end if;
end;
$$;

-- Realtime UPDATE payloads need full old-row images for RLS filtering.
alter table generation_jobs replica identity full;
alter table decks replica identity full;
