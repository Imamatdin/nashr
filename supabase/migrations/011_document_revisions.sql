-- Migration: 011_document_revisions
-- Durable, conflict-safe documents for manual and AI-assisted authoring.

create table if not exists documents (
    id                  uuid primary key default gen_random_uuid(),
    project_id          uuid not null references projects(id) on delete cascade,
    kind                text not null check (kind in ('article', 'presentation')),
    schema_version      integer not null default 1 check (schema_version between 1 and 1000),
    head_revision_id    uuid,
    created_at          timestamptz not null default now(),
    updated_at          timestamptz not null default now(),
    unique (project_id, kind)
);

create table if not exists document_revisions (
    id                  uuid primary key default gen_random_uuid(),
    document_id         uuid not null references documents(id) on delete cascade,
    parent_revision_id  uuid references document_revisions(id) on delete set null,
    created_by          uuid references users(id) on delete set null,
    idempotency_key     text not null check (char_length(idempotency_key) between 1 and 128),
    content             jsonb not null check (jsonb_typeof(content) = 'object'),
    content_hash        text not null check (char_length(content_hash) = 64),
    created_at          timestamptz not null default now(),
    unique (document_id, idempotency_key)
);

alter table documents
    add constraint documents_head_revision_fk
    foreign key (head_revision_id) references document_revisions(id) on delete set null;

create index if not exists idx_documents_project on documents (project_id);
create index if not exists idx_document_revisions_document
    on document_revisions (document_id, created_at desc);

alter table documents enable row level security;
alter table document_revisions enable row level security;

create policy documents_owner_all on documents
    for all using (
        exists (
            select 1 from projects p
            where p.id = documents.project_id and p.user_id = app_uid()
        )
    );

create policy document_revisions_owner_all on document_revisions
    for all using (
        exists (
            select 1 from documents d
            join projects p on p.id = d.project_id
            where d.id = document_revisions.document_id and p.user_id = app_uid()
        )
    );

drop trigger if exists trg_documents_updated_at on documents;
create trigger trg_documents_updated_at before update on documents
for each row execute function set_updated_at();

create or replace function create_document_if_missing(
    p_project_id uuid,
    p_kind text,
    p_schema_version integer,
    p_content jsonb,
    p_created_by uuid,
    p_idempotency_key text
)
returns table(document_id uuid, revision_id uuid, content jsonb, updated_at timestamptz)
language plpgsql
as $$
declare
    v_document_id uuid;
    v_revision_id uuid;
begin
    insert into documents (project_id, kind, schema_version)
    values (p_project_id, p_kind, p_schema_version)
    on conflict (project_id, kind) do nothing
    returning id into v_document_id;

    if v_document_id is null then
        select d.id into v_document_id
        from documents d
        where d.project_id = p_project_id and d.kind = p_kind;
    end if;

    perform 1 from documents where id = v_document_id for update;
    select head_revision_id into v_revision_id from documents where id = v_document_id;

    if v_revision_id is null then
        insert into document_revisions (
            document_id, parent_revision_id, created_by, idempotency_key, content, content_hash
        ) values (
            v_document_id, null, p_created_by, p_idempotency_key, p_content,
            encode(digest(p_content::text, 'sha256'), 'hex')
        )
        on conflict (document_id, idempotency_key) do update
            set idempotency_key = excluded.idempotency_key
        returning id into v_revision_id;

        update documents set head_revision_id = v_revision_id where id = v_document_id;
    end if;

    return query
    select d.id, r.id, r.content, d.updated_at
    from documents d join document_revisions r on r.id = d.head_revision_id
    where d.id = v_document_id;
end;
$$;

create or replace function commit_document_revision(
    p_document_id uuid,
    p_base_revision_id uuid,
    p_content jsonb,
    p_created_by uuid,
    p_idempotency_key text
)
returns table(document_id uuid, revision_id uuid, content jsonb, updated_at timestamptz)
language plpgsql
as $$
declare
    v_head uuid;
    v_revision_id uuid;
begin
    select head_revision_id into v_head
    from documents where id = p_document_id for update;
    if not found then raise exception 'document_not_found'; end if;

    select id into v_revision_id from document_revisions
    where document_revisions.document_id = p_document_id
      and idempotency_key = p_idempotency_key;
    if v_revision_id is null then
        if v_head is distinct from p_base_revision_id then
            raise exception 'stale_revision';
        end if;
        insert into document_revisions (
            document_id, parent_revision_id, created_by, idempotency_key, content, content_hash
        ) values (
            p_document_id, v_head, p_created_by, p_idempotency_key, p_content,
            encode(digest(p_content::text, 'sha256'), 'hex')
        ) returning id into v_revision_id;
        update documents set head_revision_id = v_revision_id where id = p_document_id;
    end if;

    return query
    select d.id, r.id, r.content, d.updated_at
    from documents d join document_revisions r on r.id = v_revision_id
    where d.id = p_document_id;
end;
$$;

-- DOWN
-- drop function if exists commit_document_revision(uuid, uuid, jsonb, uuid, text);
-- drop function if exists create_document_if_missing(uuid, text, integer, jsonb, uuid, text);
-- drop trigger if exists trg_documents_updated_at on documents;
-- drop table if exists document_revisions;
-- drop table if exists documents;
