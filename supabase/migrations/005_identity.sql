-- ============================================================================
-- 005_identity — web-platform identity anchor (plan §5, checkpoint 2)
--
-- HUMAN-APPLIED. Do not run from code. Written 2026-07-06 (autorun); apply
-- AFTER the P1 preflight (scripts/preflight_identity_path.py) has decided the
-- identity path:
--
--   * Path A (preflight exit 0): apply THIS FILE ONLY. The web backend mints
--     Supabase-compatible HS256 JWTs with sub = users.id, so every existing
--     auth.uid()-keyed policy works unchanged.
--   * Path B (preflight exit 2): apply this file AND 005b_identity_path_b.sql
--     (app_uid() + mechanical policy rewrite).
--
-- Three changes:
--   1. users.telegram_id becomes NULLABLE — the browser/email door creates
--      users with no Telegram identity; UNIQUE still holds for non-nulls, and
--      every bot path always has a telegram_id, so bot behaviour is unchanged.
--   2. user_auth_identities maps external login identities (Telegram, email)
--      onto the canonical app identity users.id — the uuid every FK and RLS
--      policy already keys on.
--   3. merge_users(): the dual-door merge repoints every user-owned row in ONE
--      server-side transaction (PostgREST cannot span statements client-side).
-- ============================================================================

-- 1. Email-first users have no Telegram identity.
alter table users alter column telegram_id drop not null;

-- 2. Identity mapping table.
create table if not exists user_auth_identities (
    id uuid primary key default gen_random_uuid(),
    provider text not null check (provider in ('telegram', 'email')),
    external_id text not null,
    user_id uuid not null references users(id) on delete cascade,
    -- Nullable: Path A Telegram-door rows have no Supabase auth user at all.
    -- SET NULL (not cascade): deleting an auth.users row must never delete the
    -- app identity mapping — the app user and their data outlive it.
    auth_user_id uuid references auth.users(id) on delete set null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (provider, external_id),
    -- Emails are normalized to lowercase BEFORE insert (the API does it);
    -- the check makes case-duplicate identities structurally impossible.
    constraint user_auth_identities_email_lowercase
        check (provider <> 'email' or external_id = lower(external_id)),
    constraint user_auth_identities_telegram_digits
        check (provider <> 'telegram' or external_id ~ '^[0-9]+$'),
    -- User-supplied text gets a length bound (.claude/rules/database.md);
    -- 254 = RFC 5321 maximum email length, telegram ids are far shorter.
    constraint user_auth_identities_external_id_length
        check (char_length(external_id) between 1 and 254)
);

comment on table user_auth_identities is
    'Maps external login identities (telegram id / email) to the canonical app '
    'identity users.id. One row per (provider, external_id). Dual-door merge '
    'repoints user_id; auth_user_id ties to auth.users where a Supabase auth '
    'user exists (email door always; telegram door only under Path B).';

create index if not exists idx_user_auth_identities_user_id
    on user_auth_identities (user_id);

-- One Supabase auth user may anchor at most ONE app identity row — this is
-- what makes the Path B app_uid() lookup unambiguous, and it prevents a single
-- auth.users row from ever resolving to two different app users.
create unique index if not exists uq_user_auth_identities_auth_user
    on user_auth_identities (auth_user_id)
    where auth_user_id is not null;

alter table user_auth_identities enable row level security;

-- Owner may LIST their linked identities (the "linked accounts" screen).
-- The first disjunct serves Path A (auth.uid() = users.id); the second serves
-- Path B / email-door sessions (auth.uid() = auth.users.id). Writes are
-- deliberately service-role-only: linking, merging, and unlinking are API
-- operations with their own proofs, never direct client writes.
-- drop-if-exists first (panel finding): a partially-applied run via an
-- autocommit client must be safely re-runnable.
drop policy if exists user_auth_identities_owner_select on user_auth_identities;
create policy user_auth_identities_owner_select on user_auth_identities
    for select using (
        auth.uid()::uuid = user_id or auth.uid()::uuid = auth_user_id
    );

drop trigger if exists trg_user_auth_identities_updated_at on user_auth_identities;
create trigger trg_user_auth_identities_updated_at
    before update on user_auth_identities
    for each row execute function set_updated_at();

-- 3. Dual-door merge: repoint everything the orphan owns to the canonical
-- user, then delete the orphan row, atomically. SECURITY DEFINER, invoked with
-- the SERVICE key via RPC from the API after it has verified ownership proofs
-- for BOTH doors. search_path pins pg_temp LAST (implicit pg_temp is searched
-- FIRST — temp-shadowing hazard on definer functions).
create or replace function merge_users(canonical uuid, orphan uuid)
returns void
language plpgsql security definer
set search_path = public, pg_temp
as $$
declare
    orphan_telegram_id bigint;
    canonical_telegram_id bigint;
    locked_count int;
begin
    if canonical = orphan then
        raise exception 'merge_users: canonical and orphan are the same user';
    end if;

    -- Lock BOTH rows in deterministic (id) order before any check or write
    -- (panel finding): without locks, two parallel merges of the same orphan
    -- into different canonicals can both report success while one moved the
    -- rows and the other silently updated nothing.
    select count(*) into locked_count from (
        select id from users where id in (canonical, orphan)
        order by id for update
    ) locked;
    if locked_count <> 2 then
        raise exception 'merge_users: canonical % or orphan % not found',
            canonical, orphan;
    end if;

    select telegram_id into canonical_telegram_id from users where id = canonical;
    select telegram_id into orphan_telegram_id from users where id = orphan;

    update projects set user_id = canonical where user_id = orphan;
    update orders set user_id = canonical where user_id = orphan;
    update invoices set user_id = canonical where user_id = orphan;
    update credit_ledger set user_id = canonical where user_id = orphan;
    update user_auth_identities set user_id = canonical where user_id = orphan;

    -- The orphan users row is now unreferenced (project-scoped tables hang off
    -- projects, which were repointed above). Hard-delete rather than soft:
    -- a lingering users row with a live telegram_id UNIQUE value would block
    -- the canonical user from ever linking that Telegram account.
    delete from users where id = orphan;

    -- Carry the bot identity over (panel finding, 3 lenses): the bot resolves
    -- users ONLY via users.telegram_id, so merging a bot user into an
    -- email-first canonical (telegram_id NULL) without this write would make
    -- the bot re-register the same person as a brand-new user. When the
    -- canonical already has its own telegram_id, it is kept: the orphan's
    -- telegram identity still maps through user_auth_identities (web door),
    -- and a users row holds at most one bot identity by schema.
    if canonical_telegram_id is null and orphan_telegram_id is not null then
        update users set telegram_id = orphan_telegram_id where id = canonical;
    end if;
end;
$$;

-- EXECUTE grants (panel finding, 4 lenses): revoking PUBLIC removes the
-- default grant from EVERY non-owner role INCLUDING service_role — BYPASSRLS
-- does not bypass ACLs. The API's service-role RPC is the one intended caller,
-- so it must be granted back explicitly.
revoke all on function merge_users(uuid, uuid) from public, anon, authenticated;
grant execute on function merge_users(uuid, uuid) to service_role;

comment on function merge_users(uuid, uuid) is
    'Dual-door identity merge: locks both users rows, repoints projects/orders/'
    'invoices/credit_ledger/user_auth_identities from orphan to canonical, '
    'carries the orphan telegram_id onto an email-first canonical, and deletes '
    'the orphan row — one transaction. Service-role RPC only, after the API has '
    'verified ownership proofs for both doors.';

-- ============================================================================
-- DOWN (manual rollback, per .claude/rules/database.md — apply in this order):
--
--   drop function if exists merge_users(uuid, uuid);
--   drop trigger if exists trg_user_auth_identities_updated_at
--       on user_auth_identities;
--   drop policy if exists user_auth_identities_owner_select
--       on user_auth_identities;
--   drop table if exists user_auth_identities;
--   -- Only safe while every users row still has a telegram_id (i.e. no
--   -- email-first users were created after applying 005):
--   alter table users alter column telegram_id set not null;
-- ============================================================================
