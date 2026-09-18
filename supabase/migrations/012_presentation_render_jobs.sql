-- Migration: 012_presentation_render_jobs
-- Manual design edits render asynchronously without consuming generation credits.

alter table generation_jobs drop constraint if exists generation_jobs_job_type_check;
alter table generation_jobs add constraint generation_jobs_job_type_check
    check (job_type in (
        'source_processing', 'article_generation', 'presentation_generation',
        'export', 'presentation_edit', 'presentation_render', 'image_regen'
    ));

-- DOWN
-- alter table generation_jobs drop constraint if exists generation_jobs_job_type_check;
-- alter table generation_jobs add constraint generation_jobs_job_type_check
--     check (job_type in ('source_processing', 'article_generation',
--         'presentation_generation', 'export', 'presentation_edit', 'image_regen'));
