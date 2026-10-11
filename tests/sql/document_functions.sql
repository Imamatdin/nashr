-- Real-PostgreSQL checks for the migration-016 document functions.
--   psql -v ON_ERROR_STOP=1 -U postgres -d <db> < tests/sql/document_functions.sql
-- Runs as the migration owner (the privileged caller path). Rolls back; raises on
-- the first failed expectation.
begin;
do $$
declare
    v_user uuid := gen_random_uuid();
    v_project uuid := gen_random_uuid();
    v_doc uuid;
    v_again uuid;
    v_first record;
    v_saved record;
    v_replay record;
    v_stale record;
    v_same record;
    v_count int;
begin
    insert into users (id, telegram_id) values (v_user, 8000000000 + (random() * 1000000)::int);
    insert into projects (id, user_id, type, title, language, audience)
    values (v_project, v_user, 'article', 'SQL check', 'uz', 'akademik');

    v_doc := ensure_document(v_project, 'article', v_user::text);
    v_again := ensure_document(v_project, 'article', v_user::text);
    if v_again <> v_doc then raise exception 'ensure_document created a second document'; end if;

    select * into v_first from commit_revision(
        v_doc, null, '{"kind":"article","title":"A","blocks":[]}', 'manual', 1, v_user::text, 'init-1');
    if v_first.status <> 'committed' then raise exception 'first commit: %', v_first.status; end if;

    select * into v_saved from commit_revision(
        v_doc, v_first.revision_id, '{"kind":"article","title":"C","blocks":[]}', 'manual', 1, v_user::text, 'save-1');
    select * into v_replay from commit_revision(
        v_doc, v_first.revision_id, '{"kind":"article","title":"C","blocks":[]}', 'manual', 1, v_user::text, 'save-1');
    if v_replay.status <> 'duplicate' or v_replay.revision_id <> v_saved.revision_id then
        raise exception 'idempotent replay made a new revision';
    end if;

    select * into v_stale from commit_revision(
        v_doc, v_first.revision_id, '{"kind":"article","title":"D","blocks":[]}', 'manual', 1, v_user::text, 'save-2');
    if v_stale.status <> 'conflict' or v_stale.head_revision_id <> v_saved.revision_id then
        raise exception 'stale base was not a conflict naming the head';
    end if;

    select * into v_same from commit_revision(
        v_doc, v_saved.revision_id, '{"kind":"article","title":"C","blocks":[]}', 'autosave', 1, v_user::text, 'save-3');
    if v_same.status <> 'unchanged' then raise exception 'identical content was not a no-op'; end if;

    begin
        perform commit_revision(
            v_doc, v_saved.revision_id, '{"kind":"article","title":"E","blocks":[]}', 'manual', 1, v_user::text, 'save-1');
        raise exception 'key reuse with other content was accepted';
    exception when others then
        if sqlerrm <> 'idempotency_key_reused' then raise; end if;
    end;

    select count(*) into v_count from document_revisions where document_id = v_doc;
    if v_count <> 2 then raise exception 'expected 2 revisions, found %', v_count; end if;
    raise notice 'document function checks passed';
end $$;
rollback;
