-- Migration: 017_export_formats
-- B2a: one file-format table that both document kinds (presentation, article)
-- share, kind-aware render enqueue and export registration, and the
-- article_render job type. Python mirrors the table in
-- packages/platform/document_models.py; a tests/db check proves they do not drift.
--
-- Ownership (board/stages/_sql-ownership.md): nashr-decks owns _enqueue_render,
-- request_render, register_export and the revision_exports constraints. The
-- settlement core (complete_job, fail_job, _settle_failure, ...) is nashr-articles';
-- this migration does not touch it. article_render settles through those functions
-- only once nashr-articles extends their render branches (requested in the lane
-- file); B2a ships the contract that the article render pipeline builds on.

-- ---------------------------------------------------------------------------
-- 1. The file-format lookup: one row per stored export format.
-- ---------------------------------------------------------------------------
-- Immutable reference data: no write grants, so Python and SQL cannot drift
-- without the tests/db comparison catching it. file_extension is the suffix the
-- stored object carries (png renders to a zip of slide images); media_type is
-- the Content-Type a download serves; allowed_kinds names the document kinds a
-- format is valid for.

create table if not exists export_file_formats (
    format          text primary key,
    file_extension  text not null check (file_extension ~ '^[a-z0-9]{1,16}$'),
    media_type      text not null check (char_length(media_type) between 1 and 128),
    allowed_kinds   text[] not null check (
        cardinality(allowed_kinds) between 1 and 2
        and allowed_kinds <@ array['presentation', 'article']
        and array_length(allowed_kinds, 1) = cardinality(array(
            select distinct unnest(allowed_kinds)))
    )
);

insert into export_file_formats (format, file_extension, media_type, allowed_kinds) values
    ('html', 'html', 'text/html', array['presentation']),
    ('pptx', 'pptx',
        'application/vnd.openxmlformats-officedocument.presentationml.presentation',
        array['presentation']),
    ('pdf', 'pdf', 'application/pdf', array['presentation', 'article']),
    ('png', 'zip', 'application/zip', array['presentation']),
    ('docx', 'docx',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        array['article'])
on conflict (format) do update set
    file_extension = excluded.file_extension,
    media_type = excluded.media_type,
    allowed_kinds = excluded.allowed_kinds;

-- A static lookup with no per-user data: readable by the API roles, writable by
-- no one. The SECURITY DEFINER functions below read it as the migration owner.
revoke all on table export_file_formats from public, anon, authenticated, service_role;
grant select on table export_file_formats to authenticated, service_role;

-- revision_exports.format now references the lookup instead of an inline list, so
-- adding or changing a format happens in one place. Existing rows (html, pptx,
-- pdf) satisfy the key, which is seeded above before this runs.
alter table revision_exports drop constraint if exists revision_exports_format_check;
alter table revision_exports drop constraint if exists revision_exports_format_fkey;
alter table revision_exports
    add constraint revision_exports_format_fkey
    foreign key (format) references export_file_formats (format);

-- ---------------------------------------------------------------------------
-- 2. article_render joins the job-type vocabulary.
-- ---------------------------------------------------------------------------
-- Every value from 012 is kept; article_render is added with the same claim,
-- lease and (once nashr-articles extends the settlement core) settlement
-- semantics as presentation_render.
alter table generation_jobs drop constraint if exists generation_jobs_job_type_check;
alter table generation_jobs add constraint generation_jobs_job_type_check
    check (job_type in (
        'source_processing', 'article_generation', 'presentation_generation',
        'export', 'presentation_edit', 'presentation_render', 'article_render',
        'image_regen'
    ));

-- The render payload shape (revision_id, renderer_version, non-empty formats)
-- is required for both render job types, exactly as 016 required it for
-- presentation_render. NOT VALID keeps terminal legacy rows exempt while
-- enforcing every insert and update (016 section 11).
alter table generation_jobs drop constraint if exists generation_jobs_render_payload_check;
alter table generation_jobs add constraint generation_jobs_render_payload_check
    check (
        job_type not in ('presentation_render', 'article_render')
        or coalesce(jsonb_typeof(payload -> 'revision_id') = 'string'
            and (payload ->> 'revision_id') ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
            and jsonb_typeof(payload -> 'renderer_version') = 'string'
            and case when jsonb_typeof(payload -> 'formats') = 'array'
                     then jsonb_array_length(payload -> 'formats') > 0 else false end,
            false)
    ) not valid;

-- Render dedupe now covers both render job types: at most one active render per
-- (revision, renderer_version, formats), and the project-level single-active rule
-- excludes both render types (016 section 11). A revision belongs to one document
-- of one kind, so the two render types never collide on the same revision.
drop index if exists uq_generation_jobs_active;
create unique index uq_generation_jobs_active
    on generation_jobs (project_id, job_type)
    where status in ('queued', 'processing')
      and job_type not in ('presentation_render', 'article_render');

drop index if exists uq_generation_jobs_active_render;
create unique index uq_generation_jobs_active_render
    on generation_jobs (
        (payload ->> 'revision_id'), (payload ->> 'renderer_version'), (payload -> 'formats')
    )
    where status in ('queued', 'processing')
      and job_type in ('presentation_render', 'article_render');

-- ---------------------------------------------------------------------------
-- 3. _enqueue_render: kind-aware (nashr-decks owns it).
-- ---------------------------------------------------------------------------
-- The job type follows the document's kind, and every requested format must be
-- valid for that kind (export_file_formats.allowed_kinds). Everything else is
-- unchanged from 016: the revision+renderer advisory lock, the missing-format
-- recount after the lock, reuse of a covering active render, and the
-- insert-or-reuse under uq_generation_jobs_active_render.
create or replace function _enqueue_render(
    p_project_id uuid,
    p_user_id uuid,
    p_document_id uuid,
    p_revision_id uuid,
    p_renderer_version text,
    p_formats text[],
    p_max_attempts integer,
    p_requested_by uuid
)
returns table (status text, job_id uuid, formats jsonb)
language plpgsql
set search_path = public, pg_temp
as $$
#variable_conflict use_column
declare
    v_missing text[];
    v_formats jsonb;
    v_job uuid;
    v_kind text;
    v_job_type text;
begin
    if p_renderer_version is null or p_renderer_version !~ '^[a-z0-9][a-z0-9._-]{0,63}$' then
        raise exception 'invalid_renderer_version' using errcode = '22023';
    end if;

    select d.kind into v_kind from documents d where d.id = p_document_id;
    if v_kind is null then
        raise exception 'document_not_found' using errcode = 'P0002';
    end if;
    v_job_type := case when v_kind = 'article' then 'article_render' else 'presentation_render' end;

    if coalesce(cardinality(p_formats), 0) = 0
       or exists (
           select 1 from unnest(p_formats) f
            where f is null
              or not exists (
                  select 1 from export_file_formats x
                   where x.format = f and v_kind = any (x.allowed_kinds))
       )
    then
        raise exception 'invalid_render_formats' using errcode = '22023';
    end if;
    if p_max_attempts is null or p_max_attempts not between 1 and 5 then
        raise exception 'invalid_render_max_attempts' using errcode = '22023';
    end if;

    perform pg_advisory_xact_lock(
        hashtextextended('render:' || p_revision_id::text || ':' || p_renderer_version, 0)
    );

    v_missing := array(
        select distinct f from unnest(p_formats) f
         where not exists (
             select 1 from revision_exports e
              where e.revision_id = p_revision_id
                and e.renderer_version = p_renderer_version and e.format = f)
         order by f
    );
    if cardinality(v_missing) = 0 then
        return query select 'ready'::text, null::uuid, '[]'::jsonb;
        return;
    end if;

    -- Locked, so a render completing right now either finishes first (and is no
    -- longer active here) or completes after this transaction links to it.
    select j.id into v_job from generation_jobs j
     where j.job_type = v_job_type
       and j.status in ('queued', 'processing')
       and j.payload ->> 'revision_id' = p_revision_id::text
       and j.payload ->> 'renderer_version' = p_renderer_version
       and j.payload -> 'formats' @> to_jsonb(v_missing)
     order by j.created_at
     limit 1
     for update;
    if v_job is not null then
        return query select 'reused'::text, v_job, to_jsonb(v_missing);
        return;
    end if;

    -- A candidate that completed while this waited may have registered formats.
    v_missing := array(
        select distinct f from unnest(p_formats) f
         where not exists (
             select 1 from revision_exports e
              where e.revision_id = p_revision_id
                and e.renderer_version = p_renderer_version and e.format = f)
         order by f
    );
    if cardinality(v_missing) = 0 then
        return query select 'ready'::text, null::uuid, '[]'::jsonb;
        return;
    end if;
    v_formats := to_jsonb(v_missing);

    insert into generation_jobs (project_id, user_id, job_type, status, payload, max_attempts)
    values (
        p_project_id, p_user_id, v_job_type, 'queued',
        jsonb_build_object(
            'document_id', p_document_id, 'revision_id', p_revision_id,
            'renderer_version', p_renderer_version, 'formats', v_formats,
            'requested_by_job', p_requested_by),
        p_max_attempts
    )
    on conflict do nothing
    returning id into v_job;
    if v_job is null then
        -- An inline (bot) render for exactly this set holds the active slot.
        select j.id into v_job from generation_jobs j
         where j.job_type = v_job_type
           and j.status in ('queued', 'processing')
           and j.payload ->> 'revision_id' = p_revision_id::text
           and j.payload ->> 'renderer_version' = p_renderer_version
           and j.payload -> 'formats' = v_formats;
        return query select 'reused'::text, v_job, v_formats;
        return;
    end if;
    return query select 'queued'::text, v_job, v_formats;
end;
$$;

-- request_render (016) is unchanged and intentionally not redefined here: it
-- looks up the revision's document and owner, checks ownership, and delegates to
-- _enqueue_render, which is the single choke point for kind derivation and
-- per-kind format validation. Duplicating that validation in request_render
-- would create a second source of truth.

-- ---------------------------------------------------------------------------
-- 4. register_export: both render kinds, extension from the lookup (nashr-decks owns it).
-- ---------------------------------------------------------------------------
-- Changes from 016: the job may be presentation_render or article_render (no
-- other type); the registered format must be valid for the document's kind; and
-- the storage key's file extension comes from export_file_formats (png is stored
-- as a .zip of slide images). Every other guard, the first-writer-wins insert and
-- the claim fence are unchanged.
drop function if exists register_export(uuid, text, integer, uuid, text, text, text, text, bigint, integer);
create or replace function register_export(
    p_job_id uuid,
    p_worker_id text,
    p_claim_token integer,
    p_revision_id uuid,
    p_format text,
    p_renderer_version text,
    p_storage_key text,
    p_sha256 text,
    p_byte_size bigint,
    p_page_count integer
)
returns table (status text, storage_key text, sha256 text, byte_size bigint)
language plpgsql security definer
set search_path = public, pg_temp
as $$
#variable_conflict use_column
declare
    v_job generation_jobs%rowtype;
    v_document_id uuid;
    v_project uuid;
    v_owner uuid;
    v_kind text;
    v_ext text;
    v_key text;
    v_row revision_exports%rowtype;
begin
    v_job := _lock_claimed_job(p_job_id, p_worker_id, p_claim_token, false);

    if v_job.job_type is distinct from 'presentation_render'
       and v_job.job_type is distinct from 'article_render' then
        raise exception 'job_type_not_allowed' using errcode = '42501';
    end if;
    if p_revision_id is null
       or (v_job.payload ->> 'revision_id') is null
       or (v_job.payload ->> 'revision_id') is distinct from p_revision_id::text then
        raise exception 'job_revision_mismatch' using errcode = '42501';
    end if;
    if p_renderer_version is null
       or (v_job.payload ->> 'renderer_version') is distinct from p_renderer_version then
        raise exception 'renderer_version_mismatch' using errcode = '42501';
    end if;
    if p_format is null
       or jsonb_typeof(v_job.payload -> 'formats') is distinct from 'array'
       or not coalesce((v_job.payload -> 'formats') ? p_format, false) then
        raise exception 'format_not_requested' using errcode = '42501';
    end if;

    select r.document_id, d.project_id, d.kind, p.user_id
      into v_document_id, v_project, v_kind, v_owner
      from document_revisions r
      join documents d on d.id = r.document_id
      join projects p on p.id = d.project_id
     where r.id = p_revision_id;
    if v_document_id is null then
        raise exception 'revision_not_found' using errcode = 'P0002';
    end if;
    if v_project is distinct from v_job.project_id then
        raise exception 'job_revision_mismatch' using errcode = '42501';
    end if;
    if v_owner is null or v_job.user_id is null or v_job.user_id <> v_owner then
        raise exception 'not_document_owner' using errcode = '42501';
    end if;

    -- The format must exist and be valid for this document's kind; its file
    -- extension sets the storage key's suffix.
    select x.file_extension into v_ext from export_file_formats x
     where x.format = p_format and v_kind = any (x.allowed_kinds);
    if v_ext is null then
        raise exception 'invalid_render_formats' using errcode = '22023';
    end if;

    v_key := format('exports/%s/%s/%s/%s/%s.%s',
        v_document_id, p_revision_id, p_renderer_version, p_format, p_sha256, v_ext);
    if p_storage_key is null or p_sha256 is null or p_storage_key <> v_key then
        raise exception 'invalid_storage_key' using errcode = '22023';
    end if;

    insert into revision_exports (
        revision_id, format, renderer_version, storage_key, sha256,
        byte_size, page_count, created_by_job
    ) values (
        p_revision_id, p_format, p_renderer_version, p_storage_key, p_sha256,
        p_byte_size, p_page_count, p_job_id
    )
    on conflict (revision_id, format, renderer_version) do nothing;
    if found then
        return query select 'registered'::text, p_storage_key, p_sha256, p_byte_size;
        return;
    end if;

    select * into v_row from revision_exports e
     where e.revision_id = p_revision_id and e.format = p_format
       and e.renderer_version = p_renderer_version;
    return query select 'existing'::text, v_row.storage_key, v_row.sha256, v_row.byte_size;
end;
$$;

-- register_export keeps its 016 signature, so its grants (service_role only)
-- carry over; no re-grant needed.

-- DOWN
-- drop function if exists register_export(uuid, text, integer, uuid, text, text, text, text, bigint, integer);
-- drop function if exists _enqueue_render(uuid, uuid, uuid, uuid, text, text[], integer, uuid);
-- drop index if exists uq_generation_jobs_active_render;
-- drop index if exists uq_generation_jobs_active;
-- alter table generation_jobs drop constraint if exists generation_jobs_render_payload_check;
-- alter table generation_jobs drop constraint if exists generation_jobs_job_type_check;
-- alter table revision_exports drop constraint if exists revision_exports_format_fkey;
-- drop table if exists export_file_formats;
-- (Restore the 016 definitions of _enqueue_render, register_export, the indexes,
--  the payload check, and the revision_exports.format inline CHECK.)
