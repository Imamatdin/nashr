-- Real-PostgreSQL checks for document RPCs. Run inside the local stack:
--   docker exec -i nashr-local-pg psql -v ON_ERROR_STOP=1 -U postgres < tests/sql/document_functions.sql
-- Rolls back; raises on the first failed expectation.
begin;
do $$
declare
    v_user uuid := gen_random_uuid();
    v_project uuid := gen_random_uuid();
    v_first record;
    v_again record;
    v_saved record;
    v_replay record;
    v_count int;
begin
    insert into users (id, telegram_id) values (v_user, 8000000000 + (random() * 1000000)::int);
    insert into projects (id, user_id, type, title, language, audience)
    values (v_project, v_user, 'article', 'SQL check', 'uz', 'akademik');

    select * into v_first from create_document_if_missing(
        v_project, 'article', 1, '{"kind":"article","title":"A","blocks":[]}', v_user, 'init-1');
    if v_first.document_id is null then raise exception 'init returned no document'; end if;

    select * into v_again from create_document_if_missing(
        v_project, 'article', 1, '{"kind":"article","title":"B","blocks":[]}', v_user, 'init-2');
    if v_again.revision_id <> v_first.revision_id then raise exception 'second init created a revision'; end if;

    select * into v_saved from commit_document_revision(
        v_first.document_id, v_first.revision_id, '{"kind":"article","title":"C","blocks":[]}', v_user, 'save-1');
    select * into v_replay from commit_document_revision(
        v_first.document_id, v_first.revision_id, '{"kind":"article","title":"C","blocks":[]}', v_user, 'save-1');
    if v_replay.revision_id <> v_saved.revision_id then raise exception 'idempotent replay made a new revision'; end if;

    begin
        perform commit_document_revision(
            v_first.document_id, v_first.revision_id, '{"kind":"article","title":"D","blocks":[]}', v_user, 'save-2');
        raise exception 'stale base was accepted';
    exception when others then
        if sqlerrm <> 'stale_revision' then raise; end if;
    end;

    select count(*) into v_count from document_revisions where document_id = v_first.document_id;
    if v_count <> 2 then raise exception 'expected 2 revisions, found %', v_count; end if;
    raise notice 'document function checks passed';
end $$;
rollback;
