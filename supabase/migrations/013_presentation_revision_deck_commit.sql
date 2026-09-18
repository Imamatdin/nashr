-- Migration: 013_presentation_revision_deck_commit
-- Keep the presentation document head and the legacy current-deck read model
-- in one transaction when an AI edit is accepted.

create or replace function commit_presentation_revision_and_deck(
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
    v_project_id uuid;
    v_revision_id uuid;
begin
    select d.head_revision_id, d.project_id
      into v_head, v_project_id
    from documents d
    where d.id = p_document_id and d.kind = 'presentation'
    for update;

    if not found then raise exception 'document_not_found'; end if;

    select r.id into v_revision_id
    from document_revisions r
    where r.document_id = p_document_id
      and r.idempotency_key = p_idempotency_key;

    if v_revision_id is null then
        if v_head is distinct from p_base_revision_id then
            raise exception 'stale_revision';
        end if;

        insert into document_revisions (
            document_id, parent_revision_id, created_by,
            idempotency_key, content, content_hash
        ) values (
            p_document_id, v_head, p_created_by,
            p_idempotency_key, p_content,
            encode(digest(p_content::text, 'sha256'), 'hex')
        ) returning id into v_revision_id;

        update documents
        set head_revision_id = v_revision_id
        where id = p_document_id;

        insert into decks (project_id, title, language, audience, deck_json)
        select p.id, p.title, p.language, p.audience, p_content
        from projects p
        where p.id = v_project_id
        on conflict (project_id) do update
        set deck_json = excluded.deck_json;
    end if;

    return query
    select d.id, r.id, r.content, d.updated_at
    from documents d
    join document_revisions r on r.id = v_revision_id
    where d.id = p_document_id;
end;
$$;

-- DOWN
-- drop function if exists commit_presentation_revision_and_deck(
--     uuid, uuid, jsonb, uuid, text
-- );
