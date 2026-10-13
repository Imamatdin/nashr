-- Migration: 016_canonical_document_state
-- ADR: docs/adr/0001-canonical-document-state.md
--
-- One database-enforced write path for presentation and article state:
--   * document_revisions gain provenance (kind, schema_version, actor) and are
--     written only by commit_revision / accept_proposal (SECURITY DEFINER);
--   * a stale AI or regeneration write becomes a revision_proposals row;
--   * exports are immutable rows keyed by (revision, format, renderer_version),
--     registered only by the worker that still holds the rendering job's claim;
--   * decks becomes a view of the document head, so it cannot drift;
--   * legacy decks are imported through commit_revision (divergent ones become
--     proposals, so nothing is dropped).
-- Safe on an empty database and on legacy data; re-runnable. Runs in one
-- transaction when applied with psql --single-transaction or the Supabase CLI.
-- Exceeds the 300-line guideline: it is one coherent schema change whose parts
-- (tables, functions, privileges, backfill, view swap) only make sense together.

do $$
begin
    if current_setting('server_version_num')::int < 150000 then
        raise exception '016 requires PostgreSQL 15+ (security_invoker views); found %',
            current_setting('server_version');
    end if;
end;
$$;

-- ---------------------------------------------------------------------------
-- 1. Content schema registry
-- ---------------------------------------------------------------------------

create table if not exists document_schema_versions (
    kind     text not null check (kind in ('article', 'presentation')),
    version  integer not null check (version between 1 and 1000),
    primary key (kind, version)
);

insert into document_schema_versions (kind, version)
values ('presentation', 1), ('article', 1)
on conflict do nothing;

-- ---------------------------------------------------------------------------
-- 2. Revision provenance
-- ---------------------------------------------------------------------------

do $$
begin
    if exists (
        select 1 from information_schema.columns
        where table_schema = 'public' and table_name = 'document_revisions'
          and column_name = 'content_hash'
    ) then
        alter table document_revisions rename column content_hash to content_sha256;
    end if;
end;
$$;

alter table document_revisions add column if not exists kind text;
alter table document_revisions add column if not exists schema_version integer;
alter table document_revisions add column if not exists actor text;
alter table document_revisions add column if not exists accepted_from_proposal_id uuid;

update document_revisions set kind = 'import' where kind is null;
update document_revisions r
   set schema_version = d.schema_version
  from documents d
 where d.id = r.document_id and r.schema_version is null;
update document_revisions set schema_version = 1 where schema_version is null;
update document_revisions
   set actor = coalesce(created_by::text, 'system:legacy')
 where actor is null;

alter table document_revisions
    alter column kind set not null,
    alter column schema_version set not null,
    alter column actor set not null;

alter table document_revisions drop constraint if exists document_revisions_kind_check;
alter table document_revisions add constraint document_revisions_kind_check
    check (kind in (
        'generation', 'regeneration', 'manual', 'autosave',
        'ai_edit', 'bot_edit', 'import', 'restore'
    ));

alter table document_revisions drop constraint if exists document_revisions_actor_check;
alter table document_revisions add constraint document_revisions_actor_check
    check (actor ~ '^([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|worker:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|bot:[0-9]{1,20}|system:[a-z0-9_.:-]{1,64})$');

-- ---------------------------------------------------------------------------
-- 3. Proposals, exports, validations, bot session revision
-- ---------------------------------------------------------------------------

create table if not exists revision_proposals (
    id                    uuid primary key default gen_random_uuid(),
    document_id           uuid not null references documents(id) on delete cascade,
    base_revision_id      uuid references document_revisions(id) on delete set null,
    content               jsonb not null check (jsonb_typeof(content) = 'object'),
    content_sha256        text not null check (content_sha256 ~ '^[0-9a-f]{64}$'),
    schema_version        integer not null check (schema_version between 1 and 1000),
    kind                  text not null check (kind in ('ai_edit', 'regeneration', 'import')),
    actor                 text not null check (actor ~ '^(worker:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|bot:[0-9]{1,20}|system:[a-z0-9_.:-]{1,64})$'),
    source_job_id         uuid references generation_jobs(id) on delete set null,
    idempotency_key       text not null check (char_length(idempotency_key) between 1 and 128),
    status                text not null default 'pending'
                           check (status in ('pending', 'accepted', 'rejected', 'superseded')),
    created_at            timestamptz not null default now(),
    resolved_at           timestamptz,
    resolved_by           uuid references users(id) on delete set null,
    accepted_revision_id  uuid references document_revisions(id) on delete set null,
    unique (document_id, idempotency_key),
    check ((status = 'pending') = (resolved_at is null))
);

create index if not exists idx_revision_proposals_document
    on revision_proposals (document_id, status, created_at desc);

alter table document_revisions
    drop constraint if exists document_revisions_accepted_from_proposal_fk;
alter table document_revisions
    add constraint document_revisions_accepted_from_proposal_fk
    foreign key (accepted_from_proposal_id) references revision_proposals(id) on delete set null;

create table if not exists revision_exports (
    revision_id       uuid not null references document_revisions(id) on delete cascade,
    format            text not null check (format in ('html', 'pptx', 'pdf')),
    renderer_version  text not null check (renderer_version ~ '^[a-z0-9][a-z0-9._-]{0,63}$'),
    storage_key       text not null unique check (char_length(storage_key) between 1 and 512),
    sha256            text not null check (sha256 ~ '^[0-9a-f]{64}$'),
    byte_size         bigint not null check (byte_size > 0),
    page_count        integer check (page_count is null or page_count >= 0),
    created_by_job    uuid references generation_jobs(id) on delete set null,
    created_at        timestamptz not null default now(),
    primary key (revision_id, format, renderer_version)
);

-- A successful operation that wrote no revision or proposal (an identical
-- commit, accepting a proposal equal to the head) still consumes its idempotency
-- key: the receipt records the key, the content hash and the result, so a retry
-- after the head moved replays that result instead of conflicting, and the key
-- cannot be reused for other content (Codex B1 finding 6).
create table if not exists document_operation_receipts (
    id                uuid primary key default gen_random_uuid(),
    document_id       uuid not null references documents(id) on delete cascade,
    idempotency_key   text not null check (char_length(idempotency_key) between 1 and 128),
    operation         text not null check (operation in ('commit', 'accept')),
    content_sha256    text not null check (content_sha256 ~ '^[0-9a-f]{64}$'),
    kind              text not null check (char_length(kind) between 1 and 32),
    schema_version    integer not null check (schema_version between 1 and 1000),
    result_status     text not null check (result_status = 'unchanged'),
    revision_id       uuid references document_revisions(id) on delete set null,
    proposal_id       uuid references revision_proposals(id) on delete set null,
    created_at        timestamptz not null default now(),
    unique (document_id, idempotency_key)
);

create table if not exists migration_reports (
    id          uuid primary key default gen_random_uuid(),
    migration   text not null check (char_length(migration) between 1 and 64),
    item        text not null check (char_length(item) between 1 and 128),
    value       bigint not null,
    recorded_at timestamptz not null default now(),
    unique (migration, item)
);
alter table migration_reports enable row level security;
revoke all on table migration_reports from public, anon, authenticated, service_role;
grant select on table migration_reports to service_role;

create table if not exists proposal_validations (
    proposal_id  uuid primary key references revision_proposals(id) on delete cascade,
    validator    text not null check (char_length(validator) between 1 and 64),
    status       text not null check (status in ('valid', 'legacy_invalid')),
    detail       text check (detail is null or char_length(detail) <= 4000),
    created_at   timestamptz not null default now()
);

create table if not exists revision_validations (
    revision_id  uuid primary key references document_revisions(id) on delete cascade,
    validator    text not null check (char_length(validator) between 1 and 64),
    status       text not null check (status in ('valid', 'legacy_invalid')),
    detail       text check (detail is null or char_length(detail) <= 4000),
    created_at   timestamptz not null default now()
);

alter table brain_sessions add column if not exists revision_id uuid;
-- AI edits committed but not yet published (their render is running): each holds
-- one fix of the allowance until its job is delivered or its delivery fails.
alter table brain_sessions add column if not exists pending_deliveries_json jsonb
    not null default '[]'::jsonb check (jsonb_typeof(pending_deliveries_json) = 'array');
-- What the chat tells the user about those deliveries, in the session language.
alter table brain_sessions add column if not exists delivery_notes_json jsonb
    not null default '[]'::jsonb check (jsonb_typeof(delivery_notes_json) = 'array');
alter table brain_sessions drop constraint if exists brain_sessions_revision_fk;
alter table brain_sessions add constraint brain_sessions_revision_fk
    foreign key (revision_id) references document_revisions(id) on delete set null;

-- ---------------------------------------------------------------------------
-- 4. Row security: owners read; nobody writes directly
-- ---------------------------------------------------------------------------

alter table document_schema_versions enable row level security;
alter table revision_proposals enable row level security;
alter table revision_exports enable row level security;
alter table revision_validations enable row level security;
alter table document_operation_receipts enable row level security;
alter table proposal_validations enable row level security;

drop policy if exists document_schema_versions_read on document_schema_versions;
create policy document_schema_versions_read on document_schema_versions
    for select using (true);

drop policy if exists documents_owner_all on documents;
drop policy if exists documents_owner_select on documents;
create policy documents_owner_select on documents
    for select using (
        exists (select 1 from projects p
                where p.id = documents.project_id and p.user_id = app_uid())
    );

drop policy if exists document_revisions_owner_all on document_revisions;
drop policy if exists document_revisions_owner_select on document_revisions;
create policy document_revisions_owner_select on document_revisions
    for select using (
        exists (select 1 from documents d join projects p on p.id = d.project_id
                where d.id = document_revisions.document_id and p.user_id = app_uid())
    );

drop policy if exists revision_proposals_owner_select on revision_proposals;
create policy revision_proposals_owner_select on revision_proposals
    for select using (
        exists (select 1 from documents d join projects p on p.id = d.project_id
                where d.id = revision_proposals.document_id and p.user_id = app_uid())
    );

drop policy if exists revision_exports_owner_select on revision_exports;
create policy revision_exports_owner_select on revision_exports
    for select using (
        exists (select 1 from document_revisions r
                join documents d on d.id = r.document_id
                join projects p on p.id = d.project_id
                where r.id = revision_exports.revision_id and p.user_id = app_uid())
    );

drop policy if exists document_operation_receipts_owner_select on document_operation_receipts;
create policy document_operation_receipts_owner_select on document_operation_receipts
    for select using (
        exists (select 1 from documents d join projects p on p.id = d.project_id
                where d.id = document_operation_receipts.document_id and p.user_id = app_uid())
    );

drop policy if exists proposal_validations_owner_select on proposal_validations;
create policy proposal_validations_owner_select on proposal_validations
    for select using (
        exists (select 1 from revision_proposals q
                join documents d on d.id = q.document_id
                join projects p on p.id = d.project_id
                where q.id = proposal_validations.proposal_id and p.user_id = app_uid())
    );

drop policy if exists revision_validations_owner_select on revision_validations;
create policy revision_validations_owner_select on revision_validations
    for select using (
        exists (select 1 from document_revisions r
                join documents d on d.id = r.document_id
                join projects p on p.id = d.project_id
                where r.id = revision_validations.revision_id and p.user_id = app_uid())
    );

revoke all on table documents, document_revisions, revision_proposals, revision_exports,
    revision_validations, document_schema_versions, document_operation_receipts,
    proposal_validations
    from public, anon, authenticated, service_role;
grant select on table documents, document_revisions, revision_proposals, revision_exports,
    revision_validations, document_schema_versions, document_operation_receipts,
    proposal_validations
    to authenticated, service_role;

-- ---------------------------------------------------------------------------
-- 5. Caller resolution
-- ---------------------------------------------------------------------------

-- An API end user reaches the database through PostgREST as `authenticated`
-- (SET LOCAL ROLE plus request.jwt.claims). SECURITY DEFINER changes the
-- effective user, not the `role` setting, so both signals stay readable here.
create or replace function _caller_is_end_user() returns boolean
language sql stable
set search_path = public, pg_temp
as $$
    select coalesce(
               nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'role', ''
           ) in ('authenticated', 'anon')
        or coalesce(current_setting('role', true), 'none') in ('authenticated', 'anon')
$$;

-- Resolve who is writing and return the project owner, or raise. End users may
-- only write as themselves, and only manual/autosave/restore. Privileged callers
-- (service role, migrations) must name an actor that resolves to the owner,
-- and each actor type is limited to the kinds it can legitimately produce.
create or replace function _document_write_owner(
    p_project_id uuid, p_actor text, p_kind text
) returns uuid
language plpgsql stable
set search_path = public, pg_temp
as $$
declare
    v_owner uuid;
    v_uid uuid;
    v_mapped uuid;
    v_uuid constant text := '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}';
begin
    select p.user_id into v_owner from projects p where p.id = p_project_id;
    if v_owner is null then
        raise exception 'document_not_found' using errcode = 'P0002';
    end if;
    if p_actor is null then
        raise exception 'invalid_actor' using errcode = '22023';
    end if;

    if _caller_is_end_user() then
        v_uid := app_uid();
        if v_uid is null or v_uid <> v_owner then
            raise exception 'not_document_owner' using errcode = '42501';
        end if;
        if p_actor <> v_uid::text then
            raise exception 'actor_mismatch' using errcode = '42501';
        end if;
        if p_kind is null or p_kind not in ('manual', 'autosave', 'restore') then
            raise exception 'kind_not_allowed' using errcode = '42501';
        end if;
        return v_owner;
    end if;

    if p_actor ~ ('^' || v_uuid || '$') then
        if p_actor::uuid <> v_owner then
            raise exception 'not_document_owner' using errcode = '42501';
        end if;
        if p_kind is null or p_kind not in ('manual', 'autosave', 'restore') then
            raise exception 'kind_not_allowed' using errcode = '42501';
        end if;
    elsif p_actor ~ ('^worker:' || v_uuid || '$') then
        -- A queue worker writes only through finish_generation_job, which fences
        -- its claim and completes the job in the same transaction (ADR §6.1).
        raise exception 'worker_must_finish_job' using errcode = '42501';
    elsif p_actor ~ '^bot:[0-9]{1,20}$' then
        select u.id into v_mapped from users u where u.telegram_id = substr(p_actor, 5)::bigint;
        if v_mapped is null then
            select i.user_id into v_mapped from user_auth_identities i
             where i.provider = 'telegram' and i.external_id = substr(p_actor, 5);
        end if;
        if v_mapped is distinct from v_owner then
            raise exception 'not_document_owner' using errcode = '42501';
        end if;
        if p_kind is null or p_kind not in ('bot_edit', 'generation', 'regeneration') then
            raise exception 'kind_not_allowed' using errcode = '42501';
        end if;
    elsif p_actor ~ '^system:migration-[0-9]{3}$' then
        -- A system actor is a migration's identity, for its backfill imports only;
        -- it is reachable solely by privileged (non end-user) callers.
        if p_kind is distinct from 'import' then
            raise exception 'kind_not_allowed' using errcode = '42501';
        end if;
    else
        raise exception 'invalid_actor' using errcode = '22023';
    end if;
    return v_owner;
end;
$$;

create or replace function _content_sha256(p_content jsonb) returns text
language sql immutable
set search_path = public, pg_temp
as $$
    select encode(sha256(convert_to(p_content::text, 'UTF8')), 'hex')
$$;

-- ---------------------------------------------------------------------------
-- 6. ensure_document
-- ---------------------------------------------------------------------------

create or replace function ensure_document(p_project_id uuid, p_kind text, p_actor text)
returns uuid
language plpgsql security definer
set search_path = public, pg_temp
as $$
#variable_conflict use_column
declare
    v_type text;
    v_id uuid;
    v_probe_kind text;
begin
    if p_kind is null or p_kind not in ('article', 'presentation') then
        raise exception 'invalid_document_kind' using errcode = '22023';
    end if;
    v_probe_kind := case
        when p_actor like 'worker:%' or p_actor like 'bot:%' then 'generation'
        when p_actor like 'system:%' then 'import'
        else 'manual'
    end;
    perform _document_write_owner(p_project_id, p_actor, v_probe_kind);

    select p.type into v_type from projects p where p.id = p_project_id;
    if v_type <> 'research_package' and v_type <> p_kind then
        raise exception 'document_kind_mismatch' using errcode = '22023';
    end if;

    insert into documents (project_id, kind, schema_version)
    values (
        p_project_id, p_kind,
        (select max(v.version) from document_schema_versions v where v.kind = p_kind)
    )
    on conflict (project_id, kind) do nothing;

    select d.id into v_id from documents d where d.project_id = p_project_id and d.kind = p_kind;
    return v_id;
end;
$$;

-- ---------------------------------------------------------------------------
-- 7. commit_revision
-- ---------------------------------------------------------------------------

-- The compare-and-swap itself. The caller has already locked the document row
-- (FOR UPDATE) and resolved the owner; this function takes no locks, so every
-- entry point keeps the global order job -> document -> proposal (ADR §4.6).
create or replace function _commit_core(
    p_document_id uuid,
    p_base_revision_id uuid,
    p_content jsonb,
    p_kind text,
    p_schema_version integer,
    p_actor text,
    p_owner uuid,
    p_idempotency_key text,
    p_source_job uuid
)
returns table (
    status text, document_id uuid, revision_id uuid,
    head_revision_id uuid, proposal_id uuid
)
language plpgsql
set search_path = public, pg_temp
as $$
#variable_conflict use_column
declare
    v_doc documents%rowtype;
    v_owner uuid := p_owner;
    v_hash text;
    v_existing_id uuid;
    v_existing_hash text;
    v_head_hash text;
    v_new uuid;
    v_job uuid := p_source_job;
begin
    select * into v_doc from documents d where d.id = p_document_id;
    if not found then
        raise exception 'document_not_found' using errcode = 'P0002';
    end if;
    if p_idempotency_key is null or char_length(p_idempotency_key) not between 1 and 128 then
        raise exception 'invalid_idempotency_key' using errcode = '22023';
    end if;
    if not exists (
        select 1 from document_schema_versions v
        where v.kind = v_doc.kind and v.version = p_schema_version
    ) then
        raise exception 'unsupported_schema_version' using errcode = '22023';
    end if;
    if p_content is null or jsonb_typeof(p_content) <> 'object' then
        raise exception 'invalid_content' using errcode = '22023';
    end if;
    if octet_length(p_content::text) > 2097152 then
        raise exception 'content_too_large' using errcode = '54000';
    end if;
    v_hash := _content_sha256(p_content);

    -- Idempotency: one key per document across revisions and proposals.
    select r.id, r.content_sha256 into v_existing_id, v_existing_hash
      from document_revisions r
     where r.document_id = p_document_id and r.idempotency_key = p_idempotency_key;
    if v_existing_id is not null then
        if v_existing_hash <> v_hash then
            raise exception 'idempotency_key_reused' using errcode = '23505';
        end if;
        return query select 'duplicate'::text, p_document_id, v_existing_id,
                            v_doc.head_revision_id, null::uuid;
        return;
    end if;
    select q.id, q.content_sha256 into v_existing_id, v_existing_hash
      from revision_proposals q
     where q.document_id = p_document_id and q.idempotency_key = p_idempotency_key;
    if v_existing_id is not null then
        if v_existing_hash <> v_hash then
            raise exception 'idempotency_key_reused' using errcode = '23505';
        end if;
        return query select 'proposed'::text, p_document_id, null::uuid,
                            v_doc.head_revision_id, v_existing_id;
        return;
    end if;
    select o.revision_id, o.content_sha256 into v_existing_id, v_existing_hash
      from document_operation_receipts o
     where o.document_id = p_document_id and o.idempotency_key = p_idempotency_key;
    if v_existing_hash is not null then
        if v_existing_hash <> v_hash then
            raise exception 'idempotency_key_reused' using errcode = '23505';
        end if;
        return query select 'unchanged'::text, p_document_id, v_existing_id,
                            v_doc.head_revision_id, null::uuid;
        return;
    end if;

    -- No-op: identical content never advances the head, whatever the base. The
    -- receipt keeps the key and the result.
    if v_doc.head_revision_id is not null then
        select r.content_sha256 into v_head_hash
          from document_revisions r where r.id = v_doc.head_revision_id;
        if v_head_hash = v_hash then
            insert into document_operation_receipts (
                document_id, idempotency_key, operation, content_sha256,
                kind, schema_version, result_status, revision_id
            ) values (
                p_document_id, p_idempotency_key, 'commit', v_hash,
                p_kind, p_schema_version, 'unchanged', v_doc.head_revision_id
            );
            return query select 'unchanged'::text, p_document_id, v_doc.head_revision_id,
                                v_doc.head_revision_id, null::uuid;
            return;
        end if;
    end if;

    if p_base_revision_id is not distinct from v_doc.head_revision_id then
        insert into document_revisions (
            document_id, parent_revision_id, created_by, idempotency_key, content,
            content_sha256, kind, schema_version, actor
        ) values (
            p_document_id, v_doc.head_revision_id, v_owner, p_idempotency_key, p_content,
            v_hash, p_kind, p_schema_version, p_actor
        ) returning id into v_new;
        update documents set head_revision_id = v_new where id = p_document_id;
        return query select 'committed'::text, p_document_id, v_new, v_new, null::uuid;
        return;
    end if;

    if p_kind in ('ai_edit', 'regeneration', 'import') then
        insert into revision_proposals (
            document_id, base_revision_id, content, content_sha256, schema_version,
            kind, actor, source_job_id, idempotency_key
        ) values (
            p_document_id, p_base_revision_id, p_content, v_hash, p_schema_version,
            p_kind, p_actor, v_job, p_idempotency_key
        ) returning id into v_new;
        return query select 'proposed'::text, p_document_id, null::uuid,
                            v_doc.head_revision_id, v_new;
        return;
    end if;

    return query select 'conflict'::text, p_document_id, null::uuid,
                        v_doc.head_revision_id, null::uuid;
end;
$$;

create or replace function commit_revision(
    p_document_id uuid,
    p_base_revision_id uuid,
    p_content jsonb,
    p_kind text,
    p_schema_version integer,
    p_actor text,
    p_idempotency_key text
)
returns table (
    status text, document_id uuid, revision_id uuid,
    head_revision_id uuid, proposal_id uuid
)
language plpgsql security definer
set search_path = public, pg_temp
as $$
#variable_conflict use_column
declare
    v_project uuid;
    v_owner uuid;
begin
    select d.project_id into v_project from documents d where d.id = p_document_id for update;
    if not found then
        raise exception 'document_not_found' using errcode = 'P0002';
    end if;
    if p_kind is null or p_kind not in (
        'generation', 'regeneration', 'manual', 'autosave',
        'ai_edit', 'bot_edit', 'import', 'restore'
    ) then
        raise exception 'invalid_revision_kind' using errcode = '22023';
    end if;
    v_owner := _document_write_owner(v_project, p_actor, p_kind);
    return query select * from _commit_core(
        p_document_id, p_base_revision_id, p_content, p_kind, p_schema_version,
        p_actor, v_owner, p_idempotency_key, null
    );
end;
$$;

-- ---------------------------------------------------------------------------
-- 7b. Job claims: claim, heartbeat, finish (commit + complete), complete
-- ---------------------------------------------------------------------------
-- A claim is (worker_id, attempts): every claim increments attempts, so the
-- attempt number is a monotonic claim token. A claim is live while the job is
-- processing under that worker and token and its heartbeat is younger than
-- _claim_ttl(); the reaper uses the same window by default.

-- Paid delivery (B1-FIX2). A generation or AI-edit job that commits a revision
-- is 'committed' until the render it queued publishes every requested format;
-- then it is 'completed' (delivered). If that render fails for good, the parent
-- is 'delivery_failed' and refunded exactly once, through the same settlement as
-- fail_job. render_job_id links the parent to the render that delivers it.
alter table generation_jobs drop constraint if exists generation_jobs_status_check;
alter table generation_jobs add constraint generation_jobs_status_check
    check (status in (
        'queued', 'processing', 'committed', 'completed', 'failed', 'delivery_failed',
        'cancelled'
    ));
alter table generation_jobs add column if not exists render_job_id uuid
    references generation_jobs(id) on delete set null;
create index if not exists idx_generation_jobs_render_job
    on generation_jobs (render_job_id) where render_job_id is not null;
create index if not exists idx_generation_jobs_committed
    on generation_jobs (created_at) where status = 'committed';

create or replace function _claim_ttl() returns interval
language sql immutable
set search_path = public, pg_temp
as $$ select interval '120 seconds' $$;

-- Lock the job and require the caller's live claim; raises claim_lost otherwise.
create or replace function _lock_claimed_job(
    p_job_id uuid, p_worker_id text, p_claim_token integer, p_require_fresh boolean
) returns generation_jobs
language plpgsql
set search_path = public, pg_temp
as $$
declare
    v_job generation_jobs%rowtype;
begin
    select * into v_job from generation_jobs j where j.id = p_job_id for update;
    if not found
       or v_job.status is distinct from 'processing'
       or p_worker_id is null or v_job.worker_id is null or v_job.worker_id <> p_worker_id
       or p_claim_token is null or v_job.attempts <> p_claim_token then
        raise exception 'claim_lost' using errcode = '55000';
    end if;
    -- clock_timestamp(), not now(): now() is the transaction's start, and a
    -- finish that waited on locks must be judged at the moment it decides.
    if p_require_fresh
       and (v_job.heartbeat_at is null
            or v_job.heartbeat_at < clock_timestamp() - _claim_ttl()) then
        raise exception 'claim_expired' using errcode = '55000';
    end if;
    return v_job;
end;
$$;

create or replace function claim_job(p_job_id uuid, p_worker_id text)
returns setof generation_jobs
language sql security definer
set search_path = public, pg_temp
as $$
    update generation_jobs
       set status       = 'processing',
           worker_id    = p_worker_id,
           claimed_at   = now(),
           heartbeat_at = now(),
           started_at   = coalesce(started_at, now()),
           attempts     = attempts + 1
     where id = p_job_id and status = 'queued' and p_worker_id is not null
    returning *;
$$;

drop function if exists heartbeat_job(uuid, text);
create or replace function heartbeat_job(p_job_id uuid, p_worker_id text, p_claim_token integer)
returns boolean
language sql security definer
set search_path = public, pg_temp
as $$
    with bumped as (
        update generation_jobs
           set heartbeat_at = now()
         where id = p_job_id
           and worker_id = p_worker_id
           and attempts = p_claim_token
           and status = 'processing'
        returning id
    )
    select exists (select 1 from bumped);
$$;

-- Queue the render of one revision, or reuse one already running (B1-FIX2).
-- Formats already registered for the revision and renderer are never rendered
-- again (first writer wins), so only the missing ones are requested. An active
-- render whose formats cover the missing ones is reused (superset match), so
-- overlapping requests share one job instead of rendering twice. Decisions for one
-- revision and renderer are serialized by a transaction-scoped advisory lock, so
-- two requests cannot both miss each other's job. Returns 'ready' (nothing left
-- to render), 'reused' or 'queued'. The caller has verified ownership.
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
begin
    if p_renderer_version is null or p_renderer_version !~ '^[a-z0-9][a-z0-9._-]{0,63}$' then
        raise exception 'invalid_renderer_version' using errcode = '22023';
    end if;
    if coalesce(cardinality(p_formats), 0) = 0
       or exists (select 1 from unnest(p_formats) f where f is null or f not in ('html', 'pptx', 'pdf'))
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
     where j.job_type = 'presentation_render'
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
        p_project_id, p_user_id, 'presentation_render', 'queued',
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
         where j.job_type = 'presentation_render'
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

-- "Update exports" (API, service role): render the missing formats of a revision
-- the caller owns, reusing a covering active render.
create or replace function request_render(
    p_project_id uuid,
    p_user_id uuid,
    p_revision_id uuid,
    p_renderer_version text,
    p_formats text[],
    p_max_attempts integer
)
returns table (status text, job_id uuid, formats jsonb)
language plpgsql security definer
set search_path = public, pg_temp
as $$
#variable_conflict use_column
declare
    v_doc uuid;
    v_owner uuid;
begin
    select r.document_id, p.user_id into v_doc, v_owner
      from document_revisions r
      join documents d on d.id = r.document_id
      join projects p on p.id = d.project_id
     where r.id = p_revision_id and d.project_id = p_project_id;
    if v_doc is null then
        raise exception 'revision_not_found' using errcode = 'P0002';
    end if;
    if p_user_id is null or v_owner is distinct from p_user_id then
        raise exception 'not_document_owner' using errcode = '42501';
    end if;
    return query select * from _enqueue_render(
        p_project_id, v_owner, v_doc, p_revision_id, p_renderer_version, p_formats,
        p_max_attempts, null
    );
end;
$$;

-- The only way a queue worker changes canonical document state. Locks the job,
-- proves the caller's live claim, commits through the same compare-and-swap as
-- commit_revision, and settles the job, all in one transaction: a revision or
-- proposal from a job exists only if that job left 'processing', and a worker
-- whose claim lapsed writes nothing.
--
-- Delivery (B1-FIX2): a committed revision must be rendered, so a renderer and a
-- non-empty format list are required, never silently skipped. When something is
-- left to render the job becomes 'committed' and records its render job; that
-- render completing or failing for good settles it (completed, or
-- delivery_failed and refunded). When every format already exists, or the result
-- is a proposal (nothing to render until the owner accepts it), the job completes.
drop function if exists finish_generation_job(
    uuid, text, integer, uuid, jsonb, text, integer, text, text, text[]
);
create or replace function finish_generation_job(
    p_job_id uuid,
    p_worker_id text,
    p_claim_token integer,
    p_base_revision_id uuid,
    p_content jsonb,
    p_kind text,
    p_schema_version integer,
    p_idempotency_key text,
    p_renderer_version text,
    p_render_formats text[],
    p_render_max_attempts integer
)
returns table (
    status text, document_id uuid, revision_id uuid,
    head_revision_id uuid, proposal_id uuid, job_status text, render_job_id uuid
)
language plpgsql security definer
set search_path = public, pg_temp
as $$
#variable_conflict use_column
declare
    v_job generation_jobs%rowtype;
    v_owner uuid;
    v_type text;
    v_doc uuid;
    v_head uuid;
    v_actor text;
    v_result record;
    v_hash text;
    v_status text;
    v_rev uuid;
    v_prop uuid;
    v_stored_hash text;
    v_stored_schema integer;
    v_stored_kind text;
    v_render_status text;
    v_render_job uuid;
    v_job_status text;
begin
    if p_renderer_version is null or coalesce(cardinality(p_render_formats), 0) = 0 then
        raise exception 'render_required' using errcode = '22023';
    end if;
    if exists (
        select 1 from unnest(p_render_formats) f where f is null or f not in ('html', 'pptx', 'pdf')
    ) then
        raise exception 'invalid_render_formats' using errcode = '22023';
    end if;
    if p_render_max_attempts is null or p_render_max_attempts not between 1 and 5 then
        raise exception 'invalid_render_max_attempts' using errcode = '22023';
    end if;

    select * into v_job from generation_jobs j where j.id = p_job_id for update;
    -- A retry of a finish whose response was lost: same claim, job already
    -- settled. It replays the stored result only for the same content, schema and
    -- kind; anything else under that key is idempotency_key_reused.
    if found and v_job.status in ('committed', 'completed', 'delivery_failed')
       and v_job.worker_id = p_worker_id and v_job.attempts = p_claim_token then
        select d.id, d.head_revision_id into v_doc, v_head from documents d
         where d.project_id = v_job.project_id and d.kind = 'presentation';
        v_hash := _content_sha256(p_content);
        select 'duplicate', r.id, null::uuid, r.content_sha256, r.schema_version, r.kind
          into v_status, v_rev, v_prop, v_stored_hash, v_stored_schema, v_stored_kind
          from document_revisions r
         where r.document_id = v_doc and r.idempotency_key = p_idempotency_key;
        if v_status is null then
            select 'proposed', null::uuid, q.id, q.content_sha256, q.schema_version, q.kind
              into v_status, v_rev, v_prop, v_stored_hash, v_stored_schema, v_stored_kind
              from revision_proposals q
             where q.document_id = v_doc
               and q.idempotency_key in (p_idempotency_key, p_idempotency_key || ':proposal')
             order by (q.idempotency_key = p_idempotency_key) desc
             limit 1;
        end if;
        if v_status is null then
            select 'unchanged', o.revision_id, null::uuid, o.content_sha256, o.schema_version,
                   o.kind
              into v_status, v_rev, v_prop, v_stored_hash, v_stored_schema, v_stored_kind
              from document_operation_receipts o
             where o.document_id = v_doc and o.idempotency_key = p_idempotency_key;
        end if;
        if v_status is not null then
            if v_stored_hash is distinct from v_hash
               or v_stored_schema is distinct from p_schema_version
               or not coalesce(
                   v_stored_kind = p_kind
                   -- a lost first generation is kept as a regeneration proposal
                   or (p_kind = 'generation' and v_stored_kind = 'regeneration'
                       and v_status = 'proposed'),
                   false)
            then
                raise exception 'idempotency_key_reused' using errcode = '23505';
            end if;
            return query select v_status, v_doc, v_rev, v_head, v_prop,
                                v_job.status, v_job.render_job_id;
            return;
        end if;
    end if;
    v_job := _lock_claimed_job(p_job_id, p_worker_id, p_claim_token, true);

    if not coalesce(
        (v_job.job_type = 'presentation_generation' and p_kind in ('generation', 'regeneration'))
        or (v_job.job_type = 'presentation_edit' and p_kind = 'ai_edit'),
        false
    ) then
        raise exception 'kind_not_allowed' using errcode = '42501';
    end if;
    select p.user_id, p.type into v_owner, v_type from projects p where p.id = v_job.project_id;
    if v_owner is null then
        raise exception 'document_not_found' using errcode = 'P0002';
    end if;
    if v_job.user_id is null or v_job.user_id <> v_owner then
        raise exception 'not_document_owner' using errcode = '42501';
    end if;
    if v_type not in ('presentation', 'research_package') then
        raise exception 'document_kind_mismatch' using errcode = '22023';
    end if;

    insert into documents (project_id, kind, schema_version)
    values (
        v_job.project_id, 'presentation',
        (select max(v.version) from document_schema_versions v where v.kind = 'presentation')
    )
    on conflict (project_id, kind) do nothing;
    select d.id into v_doc from documents d
     where d.project_id = v_job.project_id and d.kind = 'presentation' for update;

    v_actor := 'worker:' || p_job_id::text;
    select * into v_result from _commit_core(
        v_doc, p_base_revision_id, p_content, p_kind, p_schema_version,
        v_actor, v_owner, p_idempotency_key, p_job_id
    );
    -- A first generation that lost the race to another head is kept as a
    -- regeneration proposal, never dropped: the owner paid for it.
    if v_result.status = 'conflict' and p_kind = 'generation' then
        select * into v_result from _commit_core(
            v_doc, null, p_content, 'regeneration', p_schema_version,
            v_actor, v_owner, p_idempotency_key || ':proposal', p_job_id
        );
    end if;
    if v_result.status not in ('committed', 'duplicate', 'unchanged', 'proposed') then
        raise exception 'finish_unexpected_status %', v_result.status using errcode = 'XX000';
    end if;

    if v_result.revision_id is not null then
        select r.status, r.job_id into v_render_status, v_render_job
          from _enqueue_render(
              v_job.project_id, v_owner, v_doc, v_result.revision_id, p_renderer_version,
              p_render_formats, p_render_max_attempts, p_job_id
          ) r;
    end if;
    v_job_status := case when v_render_job is null then 'completed' else 'committed' end;

    update generation_jobs
       set status = v_job_status,
           render_job_id = v_render_job,
           completed_at = case when v_render_job is null then now() end,
           progress = progress || jsonb_build_object(
               'step', case when v_render_job is null then 'done' else 'rendering' end,
               'outcome', v_result.status,
               'revision_id', v_result.revision_id, 'proposal_id', v_result.proposal_id,
               'render_job_id', v_render_job,
               'delivery', case
                   when v_render_job is not null then 'rendering'
                   when v_result.revision_id is null then 'proposal'
                   else 'ready' end)
     where id = p_job_id;

    return query select v_result.status, v_doc, v_result.revision_id,
                        v_result.head_revision_id, v_result.proposal_id,
                        v_job_status, v_render_job;
end;
$$;

-- The caller holds the render job's lock and the render just completed: every
-- parent it was delivering is now delivered.
create or replace function _deliver_parents(p_render_job uuid)
returns void
language sql
set search_path = public, pg_temp
as $$
    update generation_jobs p
       set status = 'completed',
           completed_at = now(),
           progress = p.progress || jsonb_build_object('step', 'done', 'delivery', 'delivered')
     where p.render_job_id = p_render_job and p.status = 'committed';
$$;

-- Complete a job that commits nothing (render, source processing). Jobs that
-- produce a revision complete only through finish_generation_job. A render
-- completes only when every format it was asked for is registered, and in the
-- same transaction the jobs it was delivering become completed (B1-FIX2).
-- Publication requires the caller's current claim token but not a fresh
-- heartbeat: a slow upload that outlived its heartbeat may still publish until
-- the reaper actually takes the job away (ADR §6.2).
create or replace function complete_job(
    p_job_id uuid, p_worker_id text, p_claim_token integer, p_progress jsonb
) returns boolean
language plpgsql security definer
set search_path = public, pg_temp
as $$
declare
    v_job generation_jobs%rowtype;
begin
    begin
        v_job := _lock_claimed_job(p_job_id, p_worker_id, p_claim_token, false);
    exception when sqlstate '55000' then
        return false;
    end;
    if v_job.job_type in ('presentation_generation', 'presentation_edit') then
        raise exception 'job_must_finish_with_revision' using errcode = '55000';
    end if;
    if v_job.job_type = 'presentation_render' and exists (
        select 1 from jsonb_array_elements_text(v_job.payload -> 'formats') f
         where not exists (
             select 1 from revision_exports e
              where e.revision_id = (v_job.payload ->> 'revision_id')::uuid
                and e.renderer_version = v_job.payload ->> 'renderer_version'
                and e.format = f)
    ) then
        raise exception 'render_incomplete' using errcode = '22023';
    end if;
    update generation_jobs
       set status = 'completed', completed_at = now(),
           progress = progress || coalesce(p_progress, '{}'::jsonb)
     where id = p_job_id;
    if v_job.job_type = 'presentation_render' then
        perform _deliver_parents(p_job_id);
    end if;
    return true;
end;
$$;

-- ---------------------------------------------------------------------------
-- 7c. Failure and refund: one transaction, exactly once (Codex B1 finding 4)
-- ---------------------------------------------------------------------------
-- A job that charged credits (payload.deducted_amount > 0) is refunded in the
-- same transaction that marks it failed or delivery_failed, so a crash can never
-- leave a failed, charged job without its refund. The job row lock serializes
-- every settler (worker fail_job, render failure, the reaper), and
-- uq_credit_ledger_refund_per_job is the safety net under it. A job that took
-- money therefore ends completed (delivered) or refunded exactly once.

-- Refund what the job charged, once. The caller holds the job row lock.
create or replace function _refund_job(p_job generation_jobs)
returns void
language plpgsql
set search_path = public, pg_temp
as $$
declare
    v_amount integer;
begin
    if jsonb_typeof(p_job.payload -> 'deducted_amount') = 'number' then
        v_amount := (p_job.payload ->> 'deducted_amount')::numeric::integer;
    end if;
    if v_amount is not null and v_amount > 0 and p_job.user_id is not null
       and not exists (
           select 1 from credit_ledger l
            where l.generation_job_id = p_job.id and l.action = 'refund'
       ) then
        insert into credit_ledger (
            user_id, project_id, amount, reason, action, generation_job_id, status
        ) values (
            p_job.user_id, p_job.project_id, v_amount, 'refund', 'refund', p_job.id, 'confirmed'
        );
    end if;
end;
$$;

-- A committed job whose delivery cannot happen: delivery_failed and refunded. Its
-- revision stays (it is canonical history); only the charge is returned. The
-- caller holds the job row lock.
create or replace function _fail_delivery(p_job generation_jobs, p_error text)
returns generation_jobs
language plpgsql
set search_path = public, pg_temp
as $$
declare
    v_row generation_jobs%rowtype;
begin
    update generation_jobs
       set status = 'delivery_failed', completed_at = now(),
           error_message = left(p_error, 4000),
           progress = progress || jsonb_build_object('step', 'done', 'delivery', 'failed')
     where id = p_job.id
    returning * into v_row;
    perform _refund_job(p_job);
    return v_row;
end;
$$;

-- The caller holds the job row lock. A render that fails for good takes every
-- job it was delivering with it: each becomes delivery_failed and is refunded.
create or replace function _settle_failure(p_job generation_jobs, p_error text)
returns generation_jobs
language plpgsql
set search_path = public, pg_temp
as $$
declare
    v_row generation_jobs%rowtype;
    v_parent generation_jobs%rowtype;
begin
    update generation_jobs
       set status = 'failed', completed_at = now(), error_message = left(p_error, 4000)
     where id = p_job.id
    returning * into v_row;
    perform _refund_job(p_job);

    if p_job.job_type = 'presentation_render' then
        for v_parent in
            select * from generation_jobs p
             where p.render_job_id = p_job.id and p.status = 'committed'
             order by p.created_at
             for update
        loop
            perform _fail_delivery(v_parent, 'render failed: ' || left(p_error, 3900));
        end loop;
    end if;
    return v_row;
end;
$$;

-- A worker gives up on its job. False when the claim is no longer the caller's
-- (reaped, re-queued or claimed again): then whoever holds the job settles it.
-- A render with attempts left goes back to the queue instead (its retries are
-- the render_max_attempts the job was queued with); its last error is kept.
create or replace function fail_job(
    p_job_id uuid, p_worker_id text, p_claim_token integer, p_step text, p_message text
) returns boolean
language plpgsql security definer
set search_path = public, pg_temp
as $$
declare
    v_job generation_jobs%rowtype;
    v_error text;
begin
    begin
        v_job := _lock_claimed_job(p_job_id, p_worker_id, p_claim_token, false);
    exception when sqlstate '55000' then
        return false;
    end;
    v_error := coalesce(p_step, 'unknown') || ': ' || coalesce(p_message, '');
    if v_job.job_type = 'presentation_render' and v_job.attempts < v_job.max_attempts then
        update generation_jobs
           set status = 'queued', worker_id = null, claimed_at = null, heartbeat_at = null,
               error_message = left(v_error, 4000),
               progress = progress || jsonb_build_object(
                   'step', 'retry_queued', 'failed_attempt', v_job.attempts)
         where id = p_job_id;
        return true;
    end if;
    perform _settle_failure(v_job, v_error);
    return true;
end;
$$;

-- The reaper (replaces 006's): stale processing jobs go back to the queue while
-- attempts remain, otherwise they are failed and refunded through the same
-- settlement. A job whose heartbeat is missing is as stale as an old one. Rows
-- another transaction holds (a worker mid-finish or mid-fail) are skipped this
-- round: that transaction decides them.
--
-- It also settles committed jobs whose render is gone or already terminal (B1-FIX2):
-- a render row that was deleted, failed or cancelled without settling its parent
-- makes the parent delivery_failed and refunded; one that completed makes it
-- completed. The render row is only read, never locked, so the reaper cannot
-- deadlock with a render completing (render lock, then parent locks): if that
-- render is still active here, the parent is left for its completion.
create or replace function reap_stale_jobs(p_stale_seconds integer default 120)
returns setof generation_jobs
language plpgsql security definer
set search_path = public, pg_temp
as $$
declare
    v_job generation_jobs%rowtype;
    v_child_status text;
begin
    for v_job in
        select * from generation_jobs j
         where j.status = 'processing'
           and (j.heartbeat_at is null
                or j.heartbeat_at < now() - make_interval(secs => p_stale_seconds))
         order by j.created_at
         for update skip locked
    loop
        if v_job.attempts < v_job.max_attempts then
            update generation_jobs
               set status = 'queued', worker_id = null, claimed_at = null, heartbeat_at = null
             where id = v_job.id;
        else
            return next _settle_failure(
                v_job,
                'reaped: worker heartbeat lost at step '
                    || coalesce(v_job.progress ->> 'step', 'unknown')
            );
        end if;
    end loop;

    for v_job in
        select * from generation_jobs j
         where j.status = 'committed'
         order by j.created_at
         for update skip locked
    loop
        v_child_status := null;
        if v_job.render_job_id is not null then
            select c.status into v_child_status from generation_jobs c
             where c.id = v_job.render_job_id;
        end if;
        if v_child_status is null then
            return next _fail_delivery(v_job, 'reaped: the render job for this delivery is gone');
        elsif v_child_status = 'completed' then
            update generation_jobs
               set status = 'completed', completed_at = now(),
                   progress = progress || jsonb_build_object('step', 'done', 'delivery', 'delivered')
             where id = v_job.id;
        elsif v_child_status in ('failed', 'cancelled', 'delivery_failed') then
            return next _fail_delivery(v_job, 'reaped: its render job ' || v_child_status);
        end if;
    end loop;
end;
$$;

-- Jobs enqueued before deducted_amount was stamped carry only product_type. The
-- settlement refunds exactly the stamped amount, so active legacy jobs get it now
-- from the price list in force when they were charged (CreditLedger.PRICING).
update generation_jobs j
   set payload = j.payload || jsonb_build_object('deducted_amount', price.amount)
  from (values
      ('article_basic', 60000), ('article_standard', 90000), ('article_premium', 150000),
      ('presentation_basic', 5000), ('presentation_standard', 10000),
      ('presentation_premium', 15000)
  ) as price(product_type, amount)
 where j.status in ('queued', 'processing')
   and j.payload ->> 'product_type' = price.product_type
   and not (j.payload ? 'deducted_amount');

-- ---------------------------------------------------------------------------
-- 8. accept_proposal / reject_proposal (replace-head-with-consent)
-- ---------------------------------------------------------------------------

create or replace function accept_proposal(
    p_proposal_id uuid,
    p_expected_head_revision_id uuid,
    p_actor text,
    p_idempotency_key text
)
returns table (
    status text, document_id uuid, revision_id uuid,
    head_revision_id uuid, proposal_id uuid
)
language plpgsql security definer
set search_path = public, pg_temp
as $$
#variable_conflict use_column
declare
    v_document_id uuid;
    v_doc documents%rowtype;
    v_prop revision_proposals%rowtype;
    v_owner uuid;
    v_existing_id uuid;
    v_existing_from uuid;
    v_existing_hash text;
    v_head_schema integer;
    v_head_hash text;
    v_new uuid;
begin
    select q.document_id into v_document_id from revision_proposals q where q.id = p_proposal_id;
    if v_document_id is null then
        raise exception 'proposal_not_found' using errcode = 'P0002';
    end if;
    select * into v_doc from documents d where d.id = v_document_id for update;
    select * into v_prop from revision_proposals q where q.id = p_proposal_id for update;

    -- Consent is a human action: only the owner (end user, or API on their behalf).
    v_owner := _document_write_owner(v_doc.project_id, p_actor, 'manual');

    if p_idempotency_key is null or char_length(p_idempotency_key) not between 1 and 128 then
        raise exception 'invalid_idempotency_key' using errcode = '22023';
    end if;
    select r.id, r.accepted_from_proposal_id, r.content_sha256
      into v_existing_id, v_existing_from, v_existing_hash
      from document_revisions r
     where r.document_id = v_document_id and r.idempotency_key = p_idempotency_key;
    if v_existing_id is not null then
        if v_existing_from is distinct from p_proposal_id or v_existing_hash <> v_prop.content_sha256 then
            raise exception 'idempotency_key_reused' using errcode = '23505';
        end if;
        return query select 'duplicate'::text, v_document_id, v_existing_id,
                            v_doc.head_revision_id, p_proposal_id;
        return;
    end if;
    if exists (
        select 1 from revision_proposals q
        where q.document_id = v_document_id and q.idempotency_key = p_idempotency_key
    ) then
        raise exception 'idempotency_key_reused' using errcode = '23505';
    end if;
    select o.revision_id, o.proposal_id, o.content_sha256
      into v_existing_id, v_existing_from, v_existing_hash
      from document_operation_receipts o
     where o.document_id = v_document_id and o.idempotency_key = p_idempotency_key;
    if v_existing_hash is not null then
        if v_existing_from is distinct from p_proposal_id
           or v_existing_hash <> v_prop.content_sha256 then
            raise exception 'idempotency_key_reused' using errcode = '23505';
        end if;
        return query select 'unchanged'::text, v_document_id, v_existing_id,
                            v_doc.head_revision_id, p_proposal_id;
        return;
    end if;

    if v_prop.status <> 'pending' then
        raise exception 'proposal_not_pending' using errcode = '55000';
    end if;
    if v_doc.head_revision_id is not null then
        select r.schema_version, r.content_sha256 into v_head_schema, v_head_hash
          from document_revisions r where r.id = v_doc.head_revision_id;
        if v_head_schema <> v_prop.schema_version then
            raise exception 'proposal_schema_mismatch' using errcode = '55000';
        end if;
    end if;
    if p_expected_head_revision_id is distinct from v_doc.head_revision_id then
        return query select 'conflict'::text, v_document_id, null::uuid,
                            v_doc.head_revision_id, p_proposal_id;
        return;
    end if;

    if v_head_hash = v_prop.content_sha256 then
        update revision_proposals
           set status = 'accepted', resolved_at = now(), resolved_by = v_owner,
               accepted_revision_id = v_doc.head_revision_id
         where id = p_proposal_id;
        insert into document_operation_receipts (
            document_id, idempotency_key, operation, content_sha256,
            kind, schema_version, result_status, revision_id, proposal_id
        ) values (
            v_document_id, p_idempotency_key, 'accept', v_prop.content_sha256,
            v_prop.kind, v_prop.schema_version, 'unchanged', v_doc.head_revision_id, p_proposal_id
        );
        return query select 'unchanged'::text, v_document_id, v_doc.head_revision_id,
                            v_doc.head_revision_id, p_proposal_id;
        return;
    end if;

    insert into document_revisions (
        document_id, parent_revision_id, created_by, idempotency_key, content,
        content_sha256, kind, schema_version, actor, accepted_from_proposal_id
    ) values (
        v_document_id, v_doc.head_revision_id, v_owner, p_idempotency_key, v_prop.content,
        v_prop.content_sha256, v_prop.kind, v_prop.schema_version, p_actor, p_proposal_id
    ) returning id into v_new;
    update documents set head_revision_id = v_new where id = v_document_id;
    update revision_proposals
       set status = 'accepted', resolved_at = now(), resolved_by = v_owner,
           accepted_revision_id = v_new
     where id = p_proposal_id;
    return query select 'committed'::text, v_document_id, v_new, v_new, p_proposal_id;
end;
$$;

create or replace function reject_proposal(p_proposal_id uuid, p_actor text)
returns text
language plpgsql security definer
set search_path = public, pg_temp
as $$
#variable_conflict use_column
declare
    v_document_id uuid;
    v_project uuid;
    v_owner uuid;
    v_status text;
begin
    select q.document_id into v_document_id from revision_proposals q where q.id = p_proposal_id;
    if v_document_id is null then
        raise exception 'proposal_not_found' using errcode = 'P0002';
    end if;
    select d.project_id into v_project from documents d where d.id = v_document_id for update;
    v_owner := _document_write_owner(v_project, p_actor, 'manual');
    select q.status into v_status from revision_proposals q where q.id = p_proposal_id for update;
    if v_status = 'rejected' then
        return 'rejected';
    end if;
    if v_status <> 'pending' then
        raise exception 'proposal_not_pending' using errcode = '55000';
    end if;
    update revision_proposals
       set status = 'rejected', resolved_at = now(), resolved_by = v_owner
     where id = p_proposal_id;
    return 'rejected';
end;
$$;

-- ---------------------------------------------------------------------------
-- 9. register_export (claim-fenced, first writer wins)
-- ---------------------------------------------------------------------------

-- The caller's render job must hold its live claim (worker and attempt token) and
-- must be a presentation_render job owned by the project's owner whose payload
-- names exactly this revision, this renderer version and this format. Every
-- comparison is written so that a NULL on either side refuses (Codex B1 finding
-- 2): PL/pgSQL skips an IF whose condition is NULL, so each test is phrased as
-- "refuse unless provably equal".
--
-- First writer wins (finding 3): the export for (revision, format, renderer) is
-- immutable once registered. A later registration of the same identity returns
-- status 'existing' with the stored row; the caller treats its own upload as an
-- orphan (scripts/gc_orphan_exports.py reclaims it). Retries and recovery renders
-- therefore succeed even when a re-render produced different bytes.
drop function if exists register_export(uuid, text, uuid, text, text, text, text, bigint, integer);
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
    v_key text;
    v_row revision_exports%rowtype;
begin
    v_job := _lock_claimed_job(p_job_id, p_worker_id, p_claim_token, false);

    if v_job.job_type is distinct from 'presentation_render' then
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

    select r.document_id, d.project_id, p.user_id
      into v_document_id, v_project, v_owner
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

    v_key := format('exports/%s/%s/%s/%s/%s.%s',
        v_document_id, p_revision_id, p_renderer_version, p_format, p_sha256, p_format);
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

-- Pending import proposals (divergent legacy decks) get a verdict too, so the
-- owner never accepts one blind.
create or replace function record_proposal_validation(
    p_proposal_id uuid, p_validator text, p_status text, p_detail text
) returns text
language plpgsql security definer
set search_path = public, pg_temp
as $$
begin
    insert into proposal_validations (proposal_id, validator, status, detail)
    values (p_proposal_id, p_validator, p_status, left(p_detail, 4000))
    on conflict (proposal_id) do nothing;
    return case when found then 'recorded' else 'exists' end;
end;
$$;

create or replace function record_revision_validation(
    p_revision_id uuid, p_validator text, p_status text, p_detail text
) returns text
language plpgsql security definer
set search_path = public, pg_temp
as $$
begin
    insert into revision_validations (revision_id, validator, status, detail)
    values (p_revision_id, p_validator, p_status, left(p_detail, 4000))
    on conflict (revision_id) do nothing;
    return case when found then 'recorded' else 'exists' end;
end;
$$;

-- ---------------------------------------------------------------------------
-- 10. Superseded write paths and function privileges
-- ---------------------------------------------------------------------------

drop function if exists create_document_if_missing(uuid, text, integer, jsonb, uuid, text);
drop function if exists commit_document_revision(uuid, uuid, jsonb, uuid, text);
drop function if exists commit_presentation_revision_and_deck(uuid, uuid, jsonb, uuid, text);

revoke all on function _caller_is_end_user() from public, anon, authenticated, service_role;
revoke all on function _document_write_owner(uuid, text, text)
    from public, anon, authenticated, service_role;
revoke all on function _content_sha256(jsonb) from public, anon, authenticated, service_role;
revoke all on function _commit_core(uuid, uuid, jsonb, text, integer, text, uuid, text, uuid)
    from public, anon, authenticated, service_role;
revoke all on function _claim_ttl() from public, anon, authenticated, service_role;
revoke all on function _lock_claimed_job(uuid, text, integer, boolean)
    from public, anon, authenticated, service_role;
revoke all on function claim_job(uuid, text) from public, anon, authenticated;
revoke all on function heartbeat_job(uuid, text, integer) from public, anon, authenticated;
revoke all on function finish_generation_job(
    uuid, text, integer, uuid, jsonb, text, integer, text, text, text[], integer
) from public, anon, authenticated;
revoke all on function _enqueue_render(uuid, uuid, uuid, uuid, text, text[], integer, uuid)
    from public, anon, authenticated, service_role;
revoke all on function _refund_job(generation_jobs) from public, anon, authenticated, service_role;
revoke all on function _fail_delivery(generation_jobs, text)
    from public, anon, authenticated, service_role;
revoke all on function _deliver_parents(uuid) from public, anon, authenticated, service_role;
revoke all on function request_render(uuid, uuid, uuid, text, text[], integer)
    from public, anon, authenticated;
grant execute on function request_render(uuid, uuid, uuid, text, text[], integer) to service_role;
revoke all on function complete_job(uuid, text, integer, jsonb) from public, anon, authenticated;
grant execute on function claim_job(uuid, text) to service_role;
grant execute on function heartbeat_job(uuid, text, integer) to service_role;
grant execute on function finish_generation_job(
    uuid, text, integer, uuid, jsonb, text, integer, text, text, text[], integer
) to service_role;
grant execute on function complete_job(uuid, text, integer, jsonb) to service_role;
revoke all on function _settle_failure(generation_jobs, text)
    from public, anon, authenticated, service_role;
revoke all on function fail_job(uuid, text, integer, text, text) from public, anon, authenticated;
revoke all on function reap_stale_jobs(integer) from public, anon, authenticated;
grant execute on function fail_job(uuid, text, integer, text, text) to service_role;
grant execute on function reap_stale_jobs(integer) to service_role;
revoke all on function ensure_document(uuid, text, text) from public, anon;
revoke all on function commit_revision(uuid, uuid, jsonb, text, integer, text, text)
    from public, anon;
revoke all on function accept_proposal(uuid, uuid, text, text) from public, anon;
revoke all on function reject_proposal(uuid, text) from public, anon;
revoke all on function register_export(
    uuid, text, integer, uuid, text, text, text, text, bigint, integer
) from public, anon, authenticated;
revoke all on function record_revision_validation(uuid, text, text, text)
    from public, anon, authenticated;

grant execute on function ensure_document(uuid, text, text) to authenticated, service_role;
grant execute on function commit_revision(uuid, uuid, jsonb, text, integer, text, text)
    to authenticated, service_role;
grant execute on function accept_proposal(uuid, uuid, text, text) to authenticated, service_role;
grant execute on function reject_proposal(uuid, text) to authenticated, service_role;
grant execute on function register_export(
    uuid, text, integer, uuid, text, text, text, text, bigint, integer
) to service_role;
grant execute on function record_revision_validation(uuid, text, text, text) to service_role;
revoke all on function record_proposal_validation(uuid, text, text, text)
    from public, anon, authenticated;
grant execute on function record_proposal_validation(uuid, text, text, text) to service_role;

-- ---------------------------------------------------------------------------
-- 10b. Schema hardening (Codex B1 review: SECURITY DEFINER search_path)
-- ---------------------------------------------------------------------------
-- Every SECURITY DEFINER function resolves names through `public, pg_temp`. That
-- is only safe if no untrusted role can create objects in public: PostgreSQL 15
-- removed PUBLIC's CREATE for new databases but keeps it on upgraded or restored
-- ones. 016 takes CREATE away from the API roles and refuses to finish otherwise.
-- The queue functions kept from 006 get the same fixed search_path.

alter function claim_next_job(text) set search_path = public, pg_temp;
alter function consume_rate_limit(text, text, text, timestamptz) set search_path = public, pg_temp;

revoke create on schema public from public, anon, authenticated;
do $$
declare
    v_role text;
begin
    if exists (select 1 from pg_roles where rolname = 'authenticator') then
        execute 'revoke create on schema public from authenticator';
    end if;
    foreach v_role in array array['public', 'anon', 'authenticated', 'authenticator'] loop
        if (v_role = 'public' or exists (select 1 from pg_roles where rolname = v_role))
           and has_schema_privilege(v_role, 'public', 'CREATE') then
            raise exception '016: role % can still create objects in schema public', v_role;
        end if;
    end loop;
end;
$$;

-- ---------------------------------------------------------------------------
-- 11. Render-job dedupe on the revision, not the project
-- ---------------------------------------------------------------------------

drop index if exists uq_generation_jobs_active;
create unique index uq_generation_jobs_active
    on generation_jobs (project_id, job_type)
    where status in ('queued', 'processing') and job_type <> 'presentation_render';

create unique index if not exists uq_generation_jobs_active_render
    on generation_jobs (
        (payload ->> 'revision_id'), (payload ->> 'renderer_version'), (payload -> 'formats')
    )
    where status in ('queued', 'processing') and job_type = 'presentation_render';

-- The CHECK below is NOT VALID (terminal legacy rows from 012 keep whatever they
-- had) but it is enforced on every insert and update. An active legacy render job
-- without a target could then never be updated by the reaper, so it is failed here,
-- honestly, before the constraint exists. Render jobs are never charged.
update generation_jobs
   set status = 'failed', completed_at = now(),
       error_message = '016: render job has no target revision; re-request the render'
 where job_type = 'presentation_render'
   and status in ('queued', 'processing')
   and not coalesce(
       jsonb_typeof(payload -> 'revision_id') = 'string'
       and (payload ->> 'revision_id') ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
       and jsonb_typeof(payload -> 'renderer_version') = 'string'
       and case when jsonb_typeof(payload -> 'formats') = 'array'
                then jsonb_array_length(payload -> 'formats') > 0 else false end,
       false);

alter table generation_jobs drop constraint if exists generation_jobs_render_payload_check;
alter table generation_jobs add constraint generation_jobs_render_payload_check
    check (
        job_type <> 'presentation_render'
        or coalesce(jsonb_typeof(payload -> 'revision_id') = 'string'
            and (payload ->> 'revision_id') ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
            and jsonb_typeof(payload -> 'renderer_version') = 'string'
            and case when jsonb_typeof(payload -> 'formats') = 'array'
                     then jsonb_array_length(payload -> 'formats') > 0 else false end,
            false)
    ) not valid;

-- ---------------------------------------------------------------------------
-- 12. One refund per job, installed unconditionally (fail closed)
-- ---------------------------------------------------------------------------
-- Legacy data may already hold several refund rows for one job. The ledger is
-- append-only, so they are neither deleted nor rewritten: every row after the
-- first per job is recorded in credit_ledger_legacy_duplicate_refunds, and the
-- unique index excludes exactly those row ids. Every other refund row, and every
-- future one, is covered. 016 never finishes without the index.

create table if not exists credit_ledger_legacy_duplicate_refunds (
    ledger_id          uuid primary key references credit_ledger(id) on delete cascade,
    generation_job_id  uuid not null,
    kept_ledger_id     uuid not null references credit_ledger(id) on delete cascade,
    recorded_at        timestamptz not null default now()
);
alter table credit_ledger_legacy_duplicate_refunds enable row level security;
revoke all on table credit_ledger_legacy_duplicate_refunds
    from public, anon, authenticated, service_role;
grant select on table credit_ledger_legacy_duplicate_refunds to service_role;

do $$
declare
    v_ids text;
    v_predicate text := 'action = ''refund'' and generation_job_id is not null';
    v_count integer;
begin
    if to_regclass('public.uq_credit_ledger_refund_per_job') is null then
        insert into credit_ledger_legacy_duplicate_refunds (ledger_id, generation_job_id, kept_ledger_id)
        select r.id, r.generation_job_id, r.first_id
          from (
              select l.id, l.generation_job_id,
                     first_value(l.id) over w as first_id,
                     row_number() over w as n
                from credit_ledger l
               where l.action = 'refund' and l.generation_job_id is not null
              window w as (partition by l.generation_job_id order by l.created_at, l.id)
          ) r
         where r.n > 1
        on conflict (ledger_id) do nothing;

        select count(*), string_agg(ledger_id::text, ',' order by ledger_id)
          into v_count, v_ids
          from credit_ledger_legacy_duplicate_refunds;
        if v_count > 0 then
            v_predicate := v_predicate || format(' and id <> all (%L::uuid[])', '{' || v_ids || '}');
            raise warning '016: % legacy duplicate refund rows kept and recorded in credit_ledger_legacy_duplicate_refunds; the refund index excludes exactly them',
                v_count;
        end if;
        execute format(
            'create unique index uq_credit_ledger_refund_per_job on credit_ledger (generation_job_id) where %s',
            v_predicate
        );
    end if;
    if to_regclass('public.uq_credit_ledger_refund_per_job') is null then
        raise exception '016: uq_credit_ledger_refund_per_job is missing; refusing to finish';
    end if;
end;
$$;

-- ---------------------------------------------------------------------------
-- 13. Legacy decks: retire the table, import every row, replace with a view
-- ---------------------------------------------------------------------------

do $$
begin
    if exists (
        select 1 from pg_class c join pg_namespace n on n.oid = c.relnamespace
        where n.nspname = 'public' and c.relname = 'decks' and c.relkind = 'r'
    ) then
        if exists (
            select 1 from pg_publication_tables t join pg_publication p on p.pubname = t.pubname
            where t.pubname = 'supabase_realtime' and not p.puballtables
              and t.schemaname = 'public' and t.tablename = 'decks'
        ) then
            alter publication supabase_realtime drop table decks;
        end if;
        alter table decks rename to decks_legacy;
    end if;
end;
$$;

do $$
begin
    if to_regclass('public.decks_legacy') is not null then
        execute 'revoke all on table decks_legacy from public, anon, authenticated, service_role';
    end if;
end;
$$;

do $$
declare
    v_row record;
    v_doc uuid;
    v_result record;
    v_content jsonb;
    v_total integer := 0;
    v_imported integer := 0;
    v_already integer := 0;
    v_in_sync integer := 0;
    v_diverged integer := 0;
    v_wrapped integer := 0;
    v_type_mismatch integer := 0;
begin
    if to_regclass('public.decks_legacy') is null then
        return;
    end if;
    for v_row in
        select l.id, l.project_id, l.deck_json, p.type
          from decks_legacy l join projects p on p.id = l.project_id
         order by l.created_at, l.id
    loop
        v_total := v_total + 1;
        if v_row.type not in ('presentation', 'research_package') then
            v_type_mismatch := v_type_mismatch + 1;
            continue;
        end if;
        if jsonb_typeof(v_row.deck_json) = 'object' then
            v_content := v_row.deck_json;
        else
            v_content := jsonb_build_object('legacy_raw', v_row.deck_json);
            v_wrapped := v_wrapped + 1;
        end if;
        v_doc := ensure_document(v_row.project_id, 'presentation', 'system:migration-016');
        select * into v_result from commit_revision(
            v_doc, null, v_content, 'import', 1, 'system:migration-016',
            'import:legacy-deck:' || v_row.id
        );
        case v_result.status
            when 'committed' then v_imported := v_imported + 1;
            when 'duplicate' then v_already := v_already + 1;
            when 'unchanged' then v_in_sync := v_in_sync + 1;
            when 'proposed' then v_diverged := v_diverged + 1;
            else raise exception '016 backfill: deck % returned status %', v_row.id, v_result.status;
        end case;
    end loop;
    raise notice '016 backfill: legacy decks=%, imported as head=%, already imported (re-run)=%, equal to existing head=%, divergent kept as proposals=%, non-object wrapped=%, skipped (non-presentation project)=%',
        v_total, v_imported, v_already, v_in_sync, v_diverged, v_wrapped, v_type_mismatch;
    insert into migration_reports (migration, item, value)
    values ('016', 'legacy_decks', v_total),
           ('016', 'imported_as_head', v_imported),
           ('016', 'already_imported', v_already),
           ('016', 'equal_to_existing_head', v_in_sync),
           ('016', 'divergent_kept_as_proposals', v_diverged),
           ('016', 'non_object_wrapped', v_wrapped),
           ('016', 'skipped_non_presentation_project', v_type_mismatch)
    on conflict (migration, item) do update set value = excluded.value, recorded_at = now();
end;
$$;

-- Inventory of revision content versions, and how many are not in the registry
-- (such a revision is kept and readable; new writes of that version are refused).
do $$
declare
    v_row record;
    v_unregistered bigint := 0;
begin
    for v_row in
        select d.kind, r.schema_version, count(*) as n,
               bool_or(not exists (
                   select 1 from document_schema_versions v
                    where v.kind = d.kind and v.version = r.schema_version)) as unregistered
          from document_revisions r join documents d on d.id = r.document_id
         group by d.kind, r.schema_version
    loop
        insert into migration_reports (migration, item, value)
        values ('016', format('revisions:%s:v%s', v_row.kind, v_row.schema_version), v_row.n)
        on conflict (migration, item) do update set value = excluded.value, recorded_at = now();
        if v_row.unregistered then
            v_unregistered := v_unregistered + v_row.n;
        end if;
    end loop;
    insert into migration_reports (migration, item, value)
    values ('016', 'revisions_with_unregistered_schema_version', v_unregistered)
    on conflict (migration, item) do update set value = excluded.value, recorded_at = now();
    if v_unregistered > 0 then
        raise warning '016: % revisions carry a schema_version that is not registered', v_unregistered;
    end if;
end;
$$;

create or replace view decks with (security_invoker = true) as
select d.id,
       d.project_id,
       p.title,
       p.language,
       p.audience,
       r.content     as deck_json,
       d.created_at,
       r.created_at  as updated_at,
       r.id          as revision_id
  from documents d
  join projects p on p.id = d.project_id
  join document_revisions r on r.id = d.head_revision_id
 where d.kind = 'presentation';

revoke all on table decks from public, anon, authenticated, service_role;
grant select on table decks to authenticated, service_role;

-- A join view is not updatable, so without a trigger PostgreSQL refuses a write
-- in the rewriter (SQLSTATE 55000, which PostgREST reports as HTTP 500) before it
-- ever checks privileges. With this trigger the executor's privilege check runs
-- and refuses with 42501 (HTTP 403); a caller that does hold privileges (the
-- table owner) still reaches the trigger, which refuses with the same code. It
-- has no other logic and runs as the caller.
create or replace function decks_refuse_writes() returns trigger
language plpgsql security invoker
set search_path = public, pg_temp
as $$
begin
    raise exception 'decks is a read-only view of the document head; write through commit_revision'
        using errcode = '42501';
end;
$$;
revoke all on function decks_refuse_writes() from public, anon, authenticated, service_role;
drop trigger if exists decks_refuse_writes on decks;
create trigger decks_refuse_writes
    instead of insert or update or delete on decks
    for each row execute function decks_refuse_writes();

-- Realtime: the web listened on decks; a view cannot be published. documents
-- changes exactly when a head moves.
do $$
begin
    if exists (select 1 from pg_publication where pubname = 'supabase_realtime' and not puballtables)
       and not exists (
           select 1 from pg_publication_tables
           where pubname = 'supabase_realtime' and schemaname = 'public' and tablename = 'documents'
       ) then
        alter publication supabase_realtime add table documents;
    end if;
end;
$$;
alter table documents replica identity full;

-- ===========================================================================
-- DOWN MIGRATION (run manually, in one transaction). Additive objects
-- (revision_proposals, revision_exports, revision_validations,
-- document_schema_versions, brain_sessions.revision_id, the refund index)
-- are left in place: pre-016 code ignores them, and proposals are kept.
-- ===========================================================================
-- begin;
-- -- decks back to a table, re-projected from the current heads (rows edited
-- -- after 016 exist only as revisions; this copies the head of each).
-- drop view if exists decks;  -- drops its trigger with it
-- drop function if exists decks_refuse_writes();
-- alter table decks_legacy rename to decks;
-- insert into decks (project_id, title, language, audience, deck_json)
-- select d.project_id, p.title, p.language, p.audience, r.content
--   from documents d
--   join projects p on p.id = d.project_id
--   join document_revisions r on r.id = d.head_revision_id
--  where d.kind = 'presentation'
-- on conflict (project_id) do update set deck_json = excluded.deck_json;
-- grant select, insert, update, delete on decks to authenticated, service_role;
-- alter publication supabase_realtime drop table documents;
-- alter publication supabase_realtime add table decks;
-- -- pre-016 privileges and policies
-- grant select, insert, update, delete on documents, document_revisions
--     to authenticated, service_role;
-- drop policy if exists documents_owner_select on documents;
-- create policy documents_owner_all on documents for all using (
--     exists (select 1 from projects p
--             where p.id = documents.project_id and p.user_id = app_uid()));
-- drop policy if exists document_revisions_owner_select on document_revisions;
-- create policy document_revisions_owner_all on document_revisions for all using (
--     exists (select 1 from documents d join projects p on p.id = d.project_id
--             where d.id = document_revisions.document_id and p.user_id = app_uid()));
-- -- the 011/013/015 functions insert without kind/actor/schema_version
-- alter table document_revisions rename column content_sha256 to content_hash;
-- alter table document_revisions
--     alter column kind drop not null,
--     alter column schema_version drop not null,
--     alter column actor drop not null;
-- -- then re-apply the function bodies of 011 (commit_document_revision),
-- -- 013 (commit_presentation_revision_and_deck) and 015 (create_document_if_missing)
-- -- job indexes (cancel any second active render job of a project first)
-- drop index if exists uq_generation_jobs_active_render;
-- drop index if exists uq_generation_jobs_active;
-- create unique index uq_generation_jobs_active on generation_jobs (project_id, job_type)
--     where status in ('queued', 'processing');
-- alter table generation_jobs drop constraint if exists generation_jobs_render_payload_check;
-- drop function if exists commit_revision(uuid, uuid, jsonb, text, integer, text, text);
-- drop function if exists accept_proposal(uuid, uuid, text, text);
-- drop function if exists reject_proposal(uuid, text);
-- drop function if exists register_export(uuid, text, integer, uuid, text, text, text, text, bigint, integer);
-- drop function if exists record_revision_validation(uuid, text, text, text);
-- drop function if exists record_proposal_validation(uuid, text, text, text);
-- drop function if exists fail_job(uuid, text, integer, text, text);
-- drop function if exists _settle_failure(generation_jobs, text);
-- -- then re-apply 006's reap_stale_jobs(integer) body (refunds move back to Python)
-- -- credit_ledger_legacy_duplicate_refunds and the refund index stay (ledger history)
-- -- schema hardening is kept on rollback (CREATE on public is not re-granted)
-- drop function if exists finish_generation_job(uuid, text, integer, uuid, jsonb, text, integer, text, text, text[]);
-- drop function if exists complete_job(uuid, text, integer, jsonb);
-- drop function if exists claim_job(uuid, text);
-- drop function if exists heartbeat_job(uuid, text, integer);
-- -- then re-apply 006's heartbeat_job(uuid, text) body (pre-016 workers call it)
-- drop function if exists _lock_claimed_job(uuid, text, integer, boolean);
-- drop function if exists _claim_ttl();
-- drop function if exists _commit_core(uuid, uuid, jsonb, text, integer, text, uuid, text, uuid);
-- drop function if exists ensure_document(uuid, text, text);
-- drop function if exists _document_write_owner(uuid, text, text);
-- drop function if exists _caller_is_end_user();
-- drop function if exists _content_sha256(jsonb);
-- commit;
-- After rollback, exports live under exports/ keys the old code does not read:
-- every deck needs one render to repopulate generated/{project}/presentation.*.
