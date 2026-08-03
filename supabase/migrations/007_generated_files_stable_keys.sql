-- ============================================================================
-- 007_generated_files_stable_keys — P2 stable R2 keys (plan C5 / deferred #2)
--
-- HUMAN-APPLIED. Do not run from code.
--
-- generated_files becomes one row per (project, file_type), upserted in
-- place, mirroring the R2 layout generated/{project_id}/presentation.{ext}
-- that overwrites in place. Existing duplicate rows (insert-only history)
-- are collapsed to the newest before the constraint lands.
-- ============================================================================

delete from generated_files gf
 using generated_files newer
 where gf.project_id = newer.project_id
   and gf.file_type = newer.file_type
   and (newer.created_at, newer.id) > (gf.created_at, gf.id);

-- A named UNIQUE constraint (not a bare index) so PostgREST upsert can target
-- it via on_conflict=project_id,file_type.
alter table generated_files
    drop constraint if exists uq_generated_files_project_type;
alter table generated_files
    add constraint uq_generated_files_project_type unique (project_id, file_type);
