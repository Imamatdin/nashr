-- ============================================================================
-- 010_project_package_tier.sql — persist the chosen package tier on a project
--
-- PREREQUISITES: 001..009 applied, in order. HUMAN-APPLIED; never auto-run.
--
-- The tier the user picks on /new was only ever a request-body field, so any
-- later enqueue for the same project (the workspace "re-generate" button) fell
-- back to the server default and charged presentation_standard regardless of
-- what was actually bought. The tier now lives on the project and drives
-- re-enqueue pricing.
--
-- NULL means legacy / pre-migration: rows created before this column existed
-- carry no tier, and the enqueue route falls back to presentation_standard for
-- exactly those. The route reads the column defensively (dict.get) so the API
-- keeps working in the window between deploy and this migration being applied.
--
-- Values mirror the presentation members of GenerationPackage
-- (packages/core/enums.py). Article/bundle packages are deliberately absent:
-- projects.type already separates those pipelines and no article tier is
-- enqueueable through POST /jobs today.
--
-- No RLS change: the column rides the existing owner-only projects policy.
-- ============================================================================

alter table projects
    add column if not exists package_tier text
        check (package_tier is null or package_tier in (
            'presentation_basic', 'presentation_standard', 'presentation_premium'
        ));

comment on column projects.package_tier is
    'Package tier the user paid for, stamped on the first successful enqueue. '
    'NULL = legacy row created before migration 010; the enqueue route treats '
    'NULL as presentation_standard for backward compatibility only.';

-- ----------------------------------------------------------------------- DOWN
-- Dropping the column also drops its CHECK constraint and comment. The route
-- degrades to the legacy fallback on its own (it reads the field with .get),
-- so a rollback needs no code deploy — every project simply re-quotes at
-- presentation_standard again, which is the pre-010 behaviour.
--
-- alter table projects drop column if exists package_tier;
-- ----------------------------------------------------------------------------
