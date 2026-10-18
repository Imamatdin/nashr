-- 019 (nashr-bot, B8.2): brain_sessions.fixes_used becomes read-only legacy history.
--
-- fixes_used was the bot's inline edit counter: the inline fix path bumped it in the
-- same session write that delivered the edit (packages/sessions_core/apply.py). B8.2
-- moves bot edits onto the queue, so every delivered edit now creates an
-- edit_deliveries row and nothing increments fixes_used. The allowance is computed as
-- the legacy fixes_used value plus this session's delivered edit_deliveries rows
-- (ADR 0001 §10 item 6), so the column must keep its historical value but never
-- change again, on any surface or role.
--
-- This trigger enforces that in the database: no update may change fixes_used, and no
-- insert may set it to a non-zero value (every live insert, create_brain_session,
-- leaves it at the column default 0; a non-zero insert would reintroduce the counter
-- the queue replaced). Legacy rows already in the table keep whatever value they had;
-- they are never re-inserted. A referential action that rewrites other columns
-- (revision_id set null on project delete) leaves fixes_used unchanged and so is
-- allowed. The trigger fires for every role including service_role, like the CAS
-- trigger beside it (016).

create or replace function brain_sessions_fixes_used_readonly() returns trigger
language plpgsql
set search_path = public, pg_temp
as $$
begin
    if tg_op = 'INSERT' then
        if new.fixes_used <> 0 then
            raise exception 'fixes_used_read_only' using errcode = '23514',
                detail = format(
                    'brain_sessions.fixes_used must be inserted as 0'
                    ' (legacy inline counter; queued edits create edit_deliveries rows), got %s',
                    new.fixes_used
                );
        end if;
        return new;
    end if;
    if new.fixes_used is distinct from old.fixes_used then
        raise exception 'fixes_used_read_only' using errcode = '23514',
            detail = format(
                'brain_sessions.fixes_used is read-only legacy history (%s -> %s)',
                old.fixes_used, new.fixes_used
            );
    end if;
    return new;
end;
$$;

drop trigger if exists brain_sessions_fixes_used_readonly on brain_sessions;
create trigger brain_sessions_fixes_used_readonly
    before insert or update on brain_sessions
    for each row execute function brain_sessions_fixes_used_readonly();
