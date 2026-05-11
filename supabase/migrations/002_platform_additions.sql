-- Migration: 002_platform_additions
-- Author: nashr platform
-- Description: Adds platform-layer columns and tables required by the
-- DatabaseClient / CreditLedger / Invoice subsystem.
--
-- Additive only: every change is guarded with IF NOT EXISTS / IF NULL
-- so the migration can be re-run idempotently against either a fresh
-- 001 schema or an existing partially-migrated database.
--
-- Conventions match 001:
--   * uuid primary keys with gen_random_uuid()
--   * timestamptz default now()
--   * RLS enabled on user-data tables
--   * credit_ledger stays append-only (no UPDATE / DELETE policy)

-- ---------------------------------------------------------------------------
-- users: payment subscriber id, full name, calibration level
-- ---------------------------------------------------------------------------

alter table users
    add column if not exists subscriber_id varchar(6) unique
        check (subscriber_id is null or subscriber_id ~ '^[1-9][0-9]{5}$');

alter table users
    add column if not exists full_name text
        check (full_name is null or char_length(full_name) <= 200);

alter table users
    add column if not exists calibration_level varchar(20) not null default 'bakalavr'
        check (calibration_level in (
            'bakalavr', 'magistr', 'doktor',
            'school', 'undergraduate', 'masters', 'doctoral', 'professional'
        ));

create index if not exists idx_users_subscriber_id on users (subscriber_id);

-- ---------------------------------------------------------------------------
-- credit_ledger: project scoping + action enum (parallel to existing reason)
-- ---------------------------------------------------------------------------

alter table credit_ledger
    add column if not exists project_id uuid references projects(id) on delete set null;

alter table credit_ledger
    add column if not exists action varchar(30)
        check (action is null or action in (
            'grant_free', 'grant_paid', 'deduct_article',
            'deduct_presentation', 'refund'
        ));

create index if not exists idx_credit_ledger_user_created
    on credit_ledger (user_id, created_at);

create index if not exists idx_credit_ledger_user_action
    on credit_ledger (user_id, action);

create index if not exists idx_credit_ledger_project
    on credit_ledger (project_id);

-- ---------------------------------------------------------------------------
-- invoices: payment requests issued to a user for a specific project/product
-- ---------------------------------------------------------------------------

create table if not exists invoices (
    id                  uuid primary key default gen_random_uuid(),
    user_id             uuid not null references users(id) on delete cascade,
    project_id          uuid references projects(id) on delete set null,
    invoice_number      varchar(20) unique not null
                         check (char_length(invoice_number) between 1 and 20),
    amount_uzs          integer not null check (amount_uzs > 0),
    product_type        varchar(30) not null check (product_type in (
        'article_basic', 'article_standard', 'article_premium',
        'presentation_basic', 'presentation_standard', 'presentation_premium',
        'research_package', 'bundle_article_presentation'
    )),
    status              varchar(20) not null default 'pending'
                         check (status in ('pending', 'paid', 'expired', 'cancelled')),
    payment_provider    varchar(20)
                         check (payment_provider is null or payment_provider in (
                             'payme', 'click', 'uzum'
                         )),
    payment_reference   varchar(100),
    created_at          timestamptz not null default now(),
    paid_at             timestamptz,
    expires_at          timestamptz not null default (now() + interval '24 hours')
);

create index if not exists idx_invoices_user on invoices (user_id);
create index if not exists idx_invoices_status on invoices (status);
create index if not exists idx_invoices_number on invoices (invoice_number);

alter table invoices enable row level security;

drop policy if exists invoices_owner_select on invoices;
create policy invoices_owner_select on invoices
    for select using (auth.uid()::uuid = user_id);

-- ---------------------------------------------------------------------------
-- generated_files: outputs of a project (docx / pdf / html / pptx)
-- ---------------------------------------------------------------------------

create table if not exists generated_files (
    id              uuid primary key default gen_random_uuid(),
    project_id      uuid not null references projects(id) on delete cascade,
    file_type       varchar(10) not null
                     check (file_type in ('docx', 'pdf', 'html', 'pptx')),
    storage_path    text not null check (char_length(storage_path) between 1 and 512),
    file_size       integer not null default 0 check (file_size >= 0),
    created_at      timestamptz not null default now()
);

create index if not exists idx_generated_files_project on generated_files (project_id);

alter table generated_files enable row level security;

drop policy if exists generated_files_owner_select on generated_files;
create policy generated_files_owner_select on generated_files
    for select using (
        exists (
            select 1 from projects p
            where p.id = generated_files.project_id and p.user_id = auth.uid()::uuid
        )
    );

-- ===========================================================================
-- DOWN MIGRATION (commented for reference; run manually to revert)
-- ===========================================================================
-- drop policy if exists generated_files_owner_select on generated_files;
-- drop table if exists generated_files;
-- drop policy if exists invoices_owner_select on invoices;
-- drop table if exists invoices;
-- drop index if exists idx_credit_ledger_project;
-- drop index if exists idx_credit_ledger_user_action;
-- drop index if exists idx_credit_ledger_user_created;
-- alter table credit_ledger drop column if exists action;
-- alter table credit_ledger drop column if exists project_id;
-- drop index if exists idx_users_subscriber_id;
-- alter table users drop column if exists calibration_level;
-- alter table users drop column if exists full_name;
-- alter table users drop column if exists subscriber_id;
