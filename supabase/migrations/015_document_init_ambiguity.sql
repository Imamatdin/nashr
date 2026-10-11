-- Migration: 015_document_init_ambiguity
-- 011's create_document_if_missing fails on every call in real PostgreSQL:
-- its RETURNS TABLE output column `document_id` makes the unqualified
-- `on conflict (document_id, idempotency_key)` target ambiguous (SQLSTATE 42702).
-- No article or presentation document could ever be initialized. Same body;
-- column names win the ambiguity because every variable is p_/v_ prefixed.

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
#variable_conflict use_column
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

-- DOWN
-- Re-apply the 011 definition (without the #variable_conflict directive).
