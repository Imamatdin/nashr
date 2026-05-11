-- Migration: 001_initial_schema
-- Author: nashr platform
-- Description: Initial schema for users, projects, sources, evidence matrix,
-- articles, decks, billing, and supporting indexes/RLS policies.
--
-- Conventions:
--   * Every table uses uuid primary keys with gen_random_uuid().
--   * Every timestamp column is timestamptz default now().
--   * All user-data tables have RLS enabled with a "user owns row" policy.
--   * credit_ledger is append-only: no UPDATE / no DELETE policy is granted.

create extension if not exists "pgcrypto";

-- ---------------------------------------------------------------------------
-- users
-- ---------------------------------------------------------------------------

create table if not exists users (
    id              uuid primary key default gen_random_uuid(),
    telegram_id     bigint unique not null check (telegram_id > 0),
    username        text check (char_length(username) <= 64),
    first_name      text check (char_length(first_name) <= 128),
    language        text not null default 'uz' check (language in ('uz', 'ru', 'en', 'kaa')),
    primary_use     text not null default 'study'
                     check (primary_use in ('study', 'teaching', 'research', 'business', 'other')),
    created_at      timestamptz not null default now()
);

create index if not exists idx_users_telegram_id on users (telegram_id);

alter table users enable row level security;

create policy users_self_select on users
    for select using (auth.uid()::uuid = id);

create policy users_self_update on users
    for update using (auth.uid()::uuid = id);

-- ---------------------------------------------------------------------------
-- projects
-- ---------------------------------------------------------------------------

create table if not exists projects (
    id              uuid primary key default gen_random_uuid(),
    user_id         uuid not null references users(id) on delete cascade,
    type            text not null
                     check (type in ('presentation', 'article', 'research_package')),
    title           text not null check (char_length(title) between 1 and 200),
    language        text not null check (language in ('uz', 'ru', 'en', 'kaa')),
    audience        text not null
                     check (audience in ('talaba', 'oqituvchi', 'akademik', 'biznes')),
    status          text not null default 'draft'
                     check (status in (
                         'draft', 'sourcing', 'interview',
                         'generating', 'ready', 'failed', 'archived'
                     )),
    created_at      timestamptz not null default now(),
    updated_at      timestamptz not null default now()
);

create index if not exists idx_projects_user_id on projects (user_id);

alter table projects enable row level security;

create policy projects_owner_all on projects
    for all using (auth.uid()::uuid = user_id);

-- ---------------------------------------------------------------------------
-- sources
-- ---------------------------------------------------------------------------

create table if not exists sources (
    id                  uuid primary key default gen_random_uuid(),
    project_id          uuid not null references projects(id) on delete cascade,
    filename            text not null check (char_length(filename) between 1 and 255),
    file_type           text not null
                         check (file_type in (
                             'pdf', 'docx', 'pptx', 'xlsx',
                             'png', 'jpeg', 'webp', 'gif',
                             'txt', 'markdown', 'csv'
                         )),
    file_size_bytes     bigint not null check (file_size_bytes > 0 and file_size_bytes <= 20971520),
    storage_key         text not null check (char_length(storage_key) between 1 and 512),
    quality             text not null default 'medium'
                         check (quality in ('strong', 'medium', 'weak', 'invalid')),
    metadata            jsonb not null default '{}'::jsonb,
    parsed_text         text,
    ocr_used            boolean not null default false,
    created_at          timestamptz not null default now()
);

create index if not exists idx_sources_project_id on sources (project_id);

alter table sources enable row level security;

create policy sources_owner_all on sources
    for all using (
        exists (
            select 1 from projects p
            where p.id = sources.project_id and p.user_id = auth.uid()::uuid
        )
    );

-- ---------------------------------------------------------------------------
-- source_chunks
-- ---------------------------------------------------------------------------

create table if not exists source_chunks (
    id              uuid primary key default gen_random_uuid(),
    source_id       uuid not null references sources(id) on delete cascade,
    project_id      uuid not null references projects(id) on delete cascade,
    chunk_index     integer not null check (chunk_index >= 0),
    text            text not null check (char_length(text) between 1 and 10000),
    page            integer check (page is null or page >= 1),
    is_ocr          boolean not null default false,
    confidence      real not null default 100.0 check (confidence >= 0.0 and confidence <= 100.0),
    created_at      timestamptz not null default now(),
    unique (source_id, chunk_index)
);

create index if not exists idx_source_chunks_source_id on source_chunks (source_id);
create index if not exists idx_source_chunks_project_id on source_chunks (project_id);

alter table source_chunks enable row level security;

create policy source_chunks_owner_all on source_chunks
    for all using (
        exists (
            select 1 from projects p
            where p.id = source_chunks.project_id and p.user_id = auth.uid()::uuid
        )
    );

-- ---------------------------------------------------------------------------
-- source_claims
-- ---------------------------------------------------------------------------

create table if not exists source_claims (
    id                  uuid primary key default gen_random_uuid(),
    source_chunk_id     uuid not null references source_chunks(id) on delete cascade,
    project_id          uuid not null references projects(id) on delete cascade,
    claim_text          text not null check (char_length(claim_text) between 1 and 2000),
    quote               text check (quote is null or char_length(quote) between 1 and 500),
    strength            text not null check (strength in ('strong', 'moderate', 'weak')),
    claim_type          text not null default 'general_fact' check (claim_type in (
        'empirical_finding',
        'statistical_result',
        'theoretical_argument',
        'methodological',
        'definition',
        'recommendation',
        'comparison',
        'limitation',
        'general_fact'
    )),
    created_at          timestamptz not null default now()
);

create index if not exists idx_source_claims_chunk on source_claims (source_chunk_id);
create index if not exists idx_source_claims_project on source_claims (project_id);

alter table source_claims enable row level security;

create policy source_claims_owner_all on source_claims
    for all using (
        exists (
            select 1 from projects p
            where p.id = source_claims.project_id and p.user_id = auth.uid()::uuid
        )
    );

-- ---------------------------------------------------------------------------
-- research_questions
-- ---------------------------------------------------------------------------

create table if not exists research_questions (
    id                  uuid primary key default gen_random_uuid(),
    project_id          uuid not null references projects(id) on delete cascade,
    question_text       text not null check (char_length(question_text) between 1 and 2000),
    question_type       text not null
                         check (question_type in (
                             'thesis_clarity', 'source_coverage',
                             'originality', 'contradiction'
                         )),
    related_source_ids  uuid[] not null default array[]::uuid[],
    created_at          timestamptz not null default now()
);

create index if not exists idx_research_questions_project on research_questions (project_id);

alter table research_questions enable row level security;

create policy research_questions_owner_all on research_questions
    for all using (
        exists (
            select 1 from projects p
            where p.id = research_questions.project_id and p.user_id = auth.uid()::uuid
        )
    );

-- ---------------------------------------------------------------------------
-- research_answers
-- ---------------------------------------------------------------------------

create table if not exists research_answers (
    id                          uuid primary key default gen_random_uuid(),
    project_id                  uuid not null references projects(id) on delete cascade,
    question_id                 uuid not null references research_questions(id) on delete cascade,
    answer_text                 text not null check (char_length(answer_text) between 1 and 10000),
    source_references_used      uuid[] not null default array[]::uuid[],
    score_specificity           smallint not null check (score_specificity between 0 and 5),
    score_source_grounding      smallint not null check (score_source_grounding between 0 and 5),
    score_usefulness            smallint not null check (score_usefulness between 0 and 5),
    credits_earned              smallint not null default 0 check (credits_earned between 0 and 10),
    created_at                  timestamptz not null default now()
);

create index if not exists idx_research_answers_project on research_answers (project_id);

alter table research_answers enable row level security;

create policy research_answers_owner_all on research_answers
    for all using (
        exists (
            select 1 from projects p
            where p.id = research_answers.project_id and p.user_id = auth.uid()::uuid
        )
    );

-- ---------------------------------------------------------------------------
-- articles
-- ---------------------------------------------------------------------------

create table if not exists articles (
    id                  uuid primary key default gen_random_uuid(),
    project_id          uuid not null references projects(id) on delete cascade,
    structure_type      text not null
                         check (structure_type in (
                             'referat', 'kurs_ishi', 'ilmiy_maqola', 'hisobot'
                         )),
    thesis              text not null check (char_length(thesis) between 1 and 2000),
    outline             jsonb not null,
    citation_format     text not null check (citation_format in ('gost', 'apa', 'ieee', 'chicago', 'vancouver')),
    target_pages        integer not null check (target_pages between 1 and 30),
    status              text not null default 'draft'
                         check (status in ('draft', 'verified', 'revised', 'final')),
    created_at          timestamptz not null default now(),
    updated_at          timestamptz not null default now()
);

create index if not exists idx_articles_project on articles (project_id);

alter table articles enable row level security;

create policy articles_owner_all on articles
    for all using (
        exists (
            select 1 from projects p
            where p.id = articles.project_id and p.user_id = auth.uid()::uuid
        )
    );

-- ---------------------------------------------------------------------------
-- article_sections
-- ---------------------------------------------------------------------------

create table if not exists article_sections (
    id              uuid primary key default gen_random_uuid(),
    article_id      uuid not null references articles(id) on delete cascade,
    section_index   integer not null check (section_index >= 0),
    title           text not null check (char_length(title) between 1 and 200),
    paragraphs      jsonb not null default '[]'::jsonb,
    word_count      integer not null default 0 check (word_count >= 0),
    status          text not null default 'draft'
                     check (status in ('draft', 'verified', 'revised', 'final')),
    created_at      timestamptz not null default now(),
    unique (article_id, section_index)
);

create index if not exists idx_article_sections_article on article_sections (article_id);

alter table article_sections enable row level security;

create policy article_sections_owner_all on article_sections
    for all using (
        exists (
            select 1 from articles a
            join projects p on p.id = a.project_id
            where a.id = article_sections.article_id and p.user_id = auth.uid()::uuid
        )
    );

-- ---------------------------------------------------------------------------
-- decks + design_directions
-- ---------------------------------------------------------------------------

create table if not exists decks (
    id              uuid primary key default gen_random_uuid(),
    project_id      uuid not null references projects(id) on delete cascade,
    title           text not null check (char_length(title) between 1 and 200),
    language        text not null check (language in ('uz', 'ru', 'en', 'kaa')),
    audience        text not null
                     check (audience in ('talaba', 'oqituvchi', 'akademik', 'biznes')),
    deck_json       jsonb not null,
    created_at      timestamptz not null default now(),
    updated_at      timestamptz not null default now()
);

create index if not exists idx_decks_project on decks (project_id);

alter table decks enable row level security;

create policy decks_owner_all on decks
    for all using (
        exists (
            select 1 from projects p
            where p.id = decks.project_id and p.user_id = auth.uid()::uuid
        )
    );

create table if not exists design_directions (
    id              uuid primary key default gen_random_uuid(),
    deck_id         uuid not null references decks(id) on delete cascade,
    direction_json  jsonb not null,
    created_at      timestamptz not null default now()
);

create index if not exists idx_design_directions_deck on design_directions (deck_id);

alter table design_directions enable row level security;

create policy design_directions_owner_all on design_directions
    for all using (
        exists (
            select 1 from decks d
            join projects p on p.id = d.project_id
            where d.id = design_directions.deck_id and p.user_id = auth.uid()::uuid
        )
    );

-- ---------------------------------------------------------------------------
-- evidence_matrix
-- ---------------------------------------------------------------------------

create table if not exists evidence_matrix (
    id                  uuid primary key default gen_random_uuid(),
    project_id          uuid not null references projects(id) on delete cascade,
    claim_id            uuid not null references source_claims(id) on delete cascade,
    source_chunk_id     uuid not null references source_chunks(id) on delete cascade,
    user_answer_id      uuid references research_answers(id) on delete set null,
    article_section_id  uuid references article_sections(id) on delete set null,
    citation_status     text not null
                         check (citation_status in (
                             'ready', 'needs_user_input', 'unsupported', 'verified'
                         )),
    created_at          timestamptz not null default now()
);

create index if not exists idx_evidence_project on evidence_matrix (project_id);

alter table evidence_matrix enable row level security;

create policy evidence_owner_all on evidence_matrix
    for all using (
        exists (
            select 1 from projects p
            where p.id = evidence_matrix.project_id and p.user_id = auth.uid()::uuid
        )
    );

-- ---------------------------------------------------------------------------
-- orders
-- ---------------------------------------------------------------------------

create table if not exists orders (
    id                  uuid primary key default gen_random_uuid(),
    user_id             uuid not null references users(id) on delete cascade,
    amount_uzs          bigint not null check (amount_uzs > 0 and amount_uzs <= 100000000),
    package_type        text not null
                         check (package_type in (
                             'presentation_basic', 'presentation_standard',
                             'presentation_premium', 'article_short',
                             'article_standard', 'research_package',
                             'bundle_article_presentation'
                         )),
    payment_provider    text not null check (payment_provider in ('payme', 'click')),
    payment_id          text check (payment_id is null or char_length(payment_id) <= 200),
    status              text not null default 'pending'
                         check (status in ('pending', 'paid', 'failed', 'refunded')),
    created_at          timestamptz not null default now(),
    paid_at             timestamptz
);

create index if not exists idx_orders_user on orders (user_id);

alter table orders enable row level security;

create policy orders_owner_select on orders
    for select using (auth.uid()::uuid = user_id);

-- ---------------------------------------------------------------------------
-- generation_jobs
-- ---------------------------------------------------------------------------

create table if not exists generation_jobs (
    id                      uuid primary key default gen_random_uuid(),
    project_id              uuid not null references projects(id) on delete cascade,
    job_type                text not null
                             check (job_type in (
                                 'source_processing', 'article_generation',
                                 'presentation_generation', 'export'
                             )),
    status                  text not null default 'queued'
                             check (status in ('queued', 'processing', 'completed', 'failed')),
    estimated_cost_uzs      bigint not null default 0 check (estimated_cost_uzs >= 0),
    actual_cost_uzs         bigint not null default 0 check (actual_cost_uzs >= 0),
    model_calls_count       integer not null default 0 check (model_calls_count >= 0),
    image_count             integer not null default 0 check (image_count >= 0),
    input_tokens_total      bigint not null default 0 check (input_tokens_total >= 0),
    output_tokens_total     bigint not null default 0 check (output_tokens_total >= 0),
    error_message           text check (error_message is null or char_length(error_message) <= 4000),
    started_at              timestamptz,
    completed_at            timestamptz,
    created_at              timestamptz not null default now()
);

create index if not exists idx_generation_jobs_project on generation_jobs (project_id);

alter table generation_jobs enable row level security;

create policy generation_jobs_owner_select on generation_jobs
    for select using (
        exists (
            select 1 from projects p
            where p.id = generation_jobs.project_id and p.user_id = auth.uid()::uuid
        )
    );

-- ---------------------------------------------------------------------------
-- credit_ledger (append-only)
-- ---------------------------------------------------------------------------

create table if not exists credit_ledger (
    id                  uuid primary key default gen_random_uuid(),
    user_id             uuid not null references users(id) on delete cascade,
    amount              integer not null,
    reason              text not null
                         check (reason in (
                             'payment', 'presentation_generation',
                             'article_generation', 'learning_reward', 'refund'
                         )),
    order_id            uuid references orders(id) on delete set null,
    generation_job_id   uuid references generation_jobs(id) on delete set null,
    status              text not null default 'confirmed'
                         check (status in ('confirmed', 'reserved', 'refunded')),
    created_at          timestamptz not null default now()
);

create index if not exists idx_credit_ledger_user on credit_ledger (user_id);
create index if not exists idx_credit_ledger_user_status on credit_ledger (user_id, status);

alter table credit_ledger enable row level security;

create policy credit_ledger_owner_select on credit_ledger
    for select using (auth.uid()::uuid = user_id);

create policy credit_ledger_insert on credit_ledger
    for insert with check (auth.uid()::uuid = user_id);

-- Append-only: deliberately no UPDATE / DELETE policies for normal users.

-- ---------------------------------------------------------------------------
-- balance helpers
-- ---------------------------------------------------------------------------

create or replace function user_credit_balance(p_user_id uuid)
returns bigint
language sql
stable
as $$
    select coalesce(sum(amount), 0)::bigint
    from credit_ledger
    where user_id = p_user_id and status = 'confirmed';
$$;

create or replace function assert_non_negative_balance()
returns trigger
language plpgsql
as $$
declare
    new_balance bigint;
begin
    if new.status = 'confirmed' then
        select user_credit_balance(new.user_id) + new.amount into new_balance;
        if new_balance < 0 then
            raise exception 'credit_ledger insert would yield negative balance for user %', new.user_id;
        end if;
    end if;
    return new;
end;
$$;

drop trigger if exists trg_credit_ledger_balance on credit_ledger;
create trigger trg_credit_ledger_balance
before insert on credit_ledger
for each row execute function assert_non_negative_balance();

-- ---------------------------------------------------------------------------
-- updated_at maintenance
-- ---------------------------------------------------------------------------

create or replace function set_updated_at()
returns trigger
language plpgsql
as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

drop trigger if exists trg_projects_updated_at on projects;
create trigger trg_projects_updated_at before update on projects
for each row execute function set_updated_at();

drop trigger if exists trg_articles_updated_at on articles;
create trigger trg_articles_updated_at before update on articles
for each row execute function set_updated_at();

drop trigger if exists trg_decks_updated_at on decks;
create trigger trg_decks_updated_at before update on decks
for each row execute function set_updated_at();

-- ===========================================================================
-- DOWN MIGRATION (commented for reference; run manually to revert)
-- ===========================================================================
-- drop trigger if exists trg_decks_updated_at on decks;
-- drop trigger if exists trg_articles_updated_at on articles;
-- drop trigger if exists trg_projects_updated_at on projects;
-- drop trigger if exists trg_credit_ledger_balance on credit_ledger;
-- drop function if exists set_updated_at;
-- drop function if exists assert_non_negative_balance;
-- drop function if exists user_credit_balance;
-- drop table if exists credit_ledger;
-- drop table if exists generation_jobs;
-- drop table if exists orders;
-- drop table if exists evidence_matrix;
-- drop table if exists design_directions;
-- drop table if exists decks;
-- drop table if exists article_sections;
-- drop table if exists articles;
-- drop table if exists research_answers;
-- drop table if exists research_questions;
-- drop table if exists source_claims;
-- drop table if exists source_chunks;
-- drop table if exists sources;
-- drop table if exists projects;
-- drop table if exists users;
