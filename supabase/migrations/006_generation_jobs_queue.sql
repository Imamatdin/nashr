-- ============================================================================
-- 006_generation_jobs_queue — P2 job pipeline (plan §5 "Job queue")
--
-- HUMAN-APPLIED. Do not run from code.
--
-- Extends the dormant generation_jobs table (001) into a real queue:
--   1. Queue columns: payload, user_id, worker_id, claimed_at, heartbeat_at,
--      attempts, max_attempts, progress.
--   2. job_type gains presentation_edit / image_regen; status gains cancelled.
--   3. Partial unique index (project_id, job_type) over active rows so a
--      double enqueue is a constraint violation, not a duplicate execution.
--   4. claim_next_job(): atomic claim via FOR UPDATE SKIP LOCKED
--      (SECURITY DEFINER so supabase-py can call it over PostgREST rpc).
--   5. reap_stale_jobs(): zombie 'processing' rows whose heartbeat went stale
--      are re-queued while attempts < max_attempts, else failed HONESTLY with
--      a step-named error_message. Returns the rows it FAILED so exactly one
--      caller refunds each.
--   6. rate_limit_counters + consume_rate_limit(): persisted per-user AND
--      per-IP fixed-window request counters (abuse caps, plan amendment 2).
-- ============================================================================

-- 1. Queue columns -----------------------------------------------------------

alter table generation_jobs
    add column if not exists payload       jsonb not null default '{}'::jsonb,
    add column if not exists user_id       uuid references users(id) on delete cascade,
    add column if not exists worker_id     text,
    add column if not exists claimed_at    timestamptz,
    add column if not exists heartbeat_at  timestamptz,
    add column if not exists attempts      integer not null default 0 check (attempts >= 0),
    add column if not exists max_attempts  integer not null default 1 check (max_attempts >= 1),
    add column if not exists progress      jsonb not null default '{}'::jsonb;

-- 2. Widen the CHECK constraints (drop + re-add; names from 001 defaults).

alter table generation_jobs drop constraint if exists generation_jobs_job_type_check;
alter table generation_jobs add constraint generation_jobs_job_type_check
    check (job_type in (
        'source_processing', 'article_generation',
        'presentation_generation', 'export',
        'presentation_edit', 'image_regen'
    ));

alter table generation_jobs drop constraint if exists generation_jobs_status_check;
alter table generation_jobs add constraint generation_jobs_status_check
    check (status in ('queued', 'processing', 'completed', 'failed', 'cancelled'));

-- 3. Idempotent enqueue: one ACTIVE job per (project, job_type).

create unique index if not exists uq_generation_jobs_active
    on generation_jobs (project_id, job_type)
    where status in ('queued', 'processing');

create index if not exists idx_generation_jobs_status_created
    on generation_jobs (status, created_at);

-- 4. Atomic claim ------------------------------------------------------------
-- SKIP LOCKED so N workers never double-claim; oldest queued row first.

create or replace function claim_next_job(p_worker_id text)
returns setof generation_jobs
language sql
security definer
set search_path = public
as $$
    update generation_jobs
       set status       = 'processing',
           worker_id    = p_worker_id,
           claimed_at   = now(),
           heartbeat_at = now(),
           started_at   = coalesce(started_at, now()),
           attempts     = attempts + 1
     where id = (
        select id from generation_jobs
         where status = 'queued'
         order by created_at
         for update skip locked
         limit 1
     )
    returning *;
$$;

-- Heartbeat guarded by worker identity so a reaped-and-reclaimed job can
-- never be touched by the old (zombie) worker.
create or replace function heartbeat_job(p_job_id uuid, p_worker_id text)
returns boolean
language sql
security definer
set search_path = public
as $$
    with bumped as (
        update generation_jobs
           set heartbeat_at = now()
         where id = p_job_id
           and worker_id = p_worker_id
           and status = 'processing'
        returning id
    )
    select exists (select 1 from bumped);
$$;

-- 5. Reaper ------------------------------------------------------------------
-- The transition is atomic per row; only the caller whose UPDATE won gets the
-- failed rows back, so the refund fires exactly once.

create or replace function reap_stale_jobs(p_stale_seconds integer default 120)
returns setof generation_jobs
language plpgsql
security definer
set search_path = public
as $$
begin
    -- Retryable zombies go back to the queue.
    update generation_jobs
       set status = 'queued', worker_id = null, claimed_at = null, heartbeat_at = null
     where status = 'processing'
       and heartbeat_at < now() - make_interval(secs => p_stale_seconds)
       and attempts < max_attempts;

    -- Exhausted zombies fail honestly, naming the last reported step.
    return query
    update generation_jobs
       set status = 'failed',
           completed_at = now(),
           error_message = left(
               'reaped: worker heartbeat lost at step '
               || coalesce(progress->>'step', 'unknown'), 4000)
     where status = 'processing'
       and heartbeat_at < now() - make_interval(secs => p_stale_seconds)
       and attempts >= max_attempts
    returning *;
end;
$$;

-- 6. Abuse caps: persisted fixed-window counters ------------------------------
-- scope 'user' keys on users.id; scope 'ip' keys on the caller address.
-- action distinguishes surfaces ('enqueue' now; 'chat' pre-wired for P4).

create table if not exists rate_limit_counters (
    scope        text not null check (scope in ('user', 'ip')),
    action       text not null check (char_length(action) <= 40),
    key          text not null check (char_length(key) <= 128),
    window_start timestamptz not null,
    count        integer not null default 0 check (count >= 0),
    primary key (scope, action, key, window_start)
);

alter table rate_limit_counters enable row level security;
-- Service-role only: no policies on purpose — anon/authenticated see nothing.

-- Atomically count this request and report the running total. The counter
-- increments even on rejected requests (it counts attempts, which is what an
-- abuse cap must measure).
create or replace function consume_rate_limit(
    p_scope text,
    p_action text,
    p_key text,
    p_window_start timestamptz
)
returns integer
language sql
security definer
set search_path = public
as $$
    insert into rate_limit_counters (scope, action, key, window_start, count)
    values (p_scope, p_action, p_key, p_window_start, 1)
    on conflict (scope, action, key, window_start)
    do update set count = rate_limit_counters.count + 1
    returning count;
$$;

revoke all on function claim_next_job(text) from public, anon, authenticated;
revoke all on function heartbeat_job(uuid, text) from public, anon, authenticated;
revoke all on function reap_stale_jobs(integer) from public, anon, authenticated;
revoke all on function consume_rate_limit(text, text, text, timestamptz)
    from public, anon, authenticated;
