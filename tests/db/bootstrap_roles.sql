-- Cluster-wide Supabase roles for the real-PostgreSQL test suite (CI only).
-- Idempotent: safe to run against a cluster that already has them.
do $$
begin
    if not exists (select 1 from pg_roles where rolname = 'anon') then
        create role anon nologin noinherit;
    end if;
    if not exists (select 1 from pg_roles where rolname = 'authenticated') then
        create role authenticated nologin noinherit;
    end if;
    if not exists (select 1 from pg_roles where rolname = 'service_role') then
        create role service_role nologin noinherit bypassrls;
    end if;
    if not exists (select 1 from pg_roles where rolname = 'authenticator') then
        create role authenticator login noinherit password 'local-authenticator';
    end if;
end;
$$;
grant anon, authenticated, service_role to authenticator;
