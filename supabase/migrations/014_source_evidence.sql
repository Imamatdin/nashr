-- Persistent, immutable page passages for the article workspace.
-- Existing source_chunks RLS remains in force; this commit RPC is worker-only.

alter table sources add column if not exists evidence_processed_at timestamptz;
alter table sources add column if not exists evidence_passage_count integer not null default 0
    check (evidence_passage_count between 0 and 2000);
alter table sources add column if not exists evidence_sha256 text
    check (evidence_sha256 is null or evidence_sha256 ~ '^[a-f0-9]{64}$');
alter table sources add column if not exists evidence_warnings jsonb not null default '[]'::jsonb
    check (jsonb_typeof(evidence_warnings) = 'array' and jsonb_array_length(evidence_warnings) <= 100);

create or replace function commit_source_evidence(
    p_job_id uuid, p_worker_id text, p_source_id uuid,
    p_chunks jsonb, p_sha256 text, p_warnings jsonb
) returns boolean
language plpgsql
set search_path = public
as $$
declare
    v_project uuid;
    v_processed timestamptz;
    v_count integer;
begin
    -- Lock the job before writing. A reaped/reclaimed worker cannot publish.
    select j.project_id into v_project from generation_jobs j
    join projects p on p.id = j.project_id and p.user_id = j.user_id
    where j.id = p_job_id and j.worker_id = p_worker_id
      and j.status = 'processing' and j.job_type = 'source_processing'
      and (j.payload->'source_ids') ? p_source_id::text
    for update of j;
    if not found then return false; end if;

    select s.evidence_processed_at into v_processed from sources s
    where s.id = p_source_id and s.project_id = v_project for update;
    if not found then raise exception 'source_not_found'; end if;
    -- A retry must not delete passages referenced by an older article revision.
    if v_processed is not null then return true; end if;
    if jsonb_typeof(p_chunks) is distinct from 'array' then
        raise exception 'invalid_source_passages';
    end if;
    v_count := jsonb_array_length(p_chunks);
    if v_count < 1 or v_count > 2000 then raise exception 'invalid_source_passages'; end if;
    if p_sha256 is null or p_sha256 !~ '^[a-f0-9]{64}$' then
        raise exception 'invalid_source_hash';
    end if;
    if exists(select 1 from source_chunks where source_id = p_source_id) then
        raise exception 'source_passages_already_exist';
    end if;

    insert into source_chunks(source_id, project_id, chunk_index, text, page, is_ocr, confidence)
    select p_source_id, v_project, c.chunk_index, c.text, c.page, c.is_ocr,
           coalesce(c.confidence, case when c.is_ocr then 0.0 else 100.0 end)
    from jsonb_to_recordset(p_chunks) as c(
        chunk_index integer, text text, page integer, is_ocr boolean, confidence real
    );
    update sources set evidence_processed_at = now(), evidence_passage_count = v_count,
        evidence_sha256 = p_sha256, evidence_warnings = p_warnings,
        ocr_used = exists(select 1 from source_chunks where source_id = p_source_id and is_ocr)
    where id = p_source_id;
    return true;
end;
$$;

revoke all on function commit_source_evidence(uuid, text, uuid, jsonb, text, jsonb) from public;
revoke all on function commit_source_evidence(uuid, text, uuid, jsonb, text, jsonb) from anon, authenticated;
grant execute on function commit_source_evidence(uuid, text, uuid, jsonb, text, jsonb) to service_role;

-- Every new revision, including restores and direct RPC writes, must resolve
-- references inside its own project. This complements API validation.
create or replace function validate_article_citations() returns trigger
language plpgsql set search_path = public, pg_temp as $$
declare
    v_project uuid;
    v_kind text;
    v_citation jsonb;
    v_source uuid;
    v_passage uuid;
    v_claim uuid;
    v_count integer := 0;
begin
    select project_id, kind into v_project, v_kind from documents where id = new.document_id;
    if v_kind <> 'article' then return new; end if;
    for v_citation in
        select c.value from jsonb_array_elements(new.content->'blocks') b,
                           jsonb_array_elements(b->'citations') c
    loop
        v_count := v_count + 1;
        if v_count > 1000 then raise exception 'invalid_citation'; end if;
        v_source := (v_citation->>'source_id')::uuid;
        v_passage := (v_citation->>'passage_id')::uuid;
        v_claim := (v_citation->>'claim_id')::uuid;
        if (v_passage is null) = (v_claim is null) then raise exception 'invalid_citation'; end if;
        if v_passage is not null then
            if not exists (select 1 from source_chunks c join sources s on s.id = c.source_id
                           where c.id = v_passage and c.source_id = v_source
                             and c.project_id = v_project and s.project_id = v_project)
            then raise exception 'invalid_citation'; end if;
        else
            if not exists (select 1 from source_claims q
                           join source_chunks c on c.id = q.source_chunk_id
                           join sources s on s.id = c.source_id
                           where q.id = v_claim and c.source_id = v_source
                             and q.project_id = v_project and c.project_id = v_project
                             and s.project_id = v_project)
            then raise exception 'invalid_citation'; end if;
        end if;
    end loop;
    return new;
end;
$$;
create trigger article_citations_before_insert before insert on document_revisions
    for each row execute function validate_article_citations();

-- DOWN (export evidence first; removing these columns does not erase passages)
-- drop trigger article_citations_before_insert on document_revisions;
-- drop function validate_article_citations();
-- drop function if exists commit_source_evidence(uuid, text, uuid, jsonb, text, jsonb);
-- alter table sources drop column if exists evidence_processed_at,
--     drop column if exists evidence_passage_count, drop column if exists evidence_sha256,
--     drop column if exists evidence_warnings;
