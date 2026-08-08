-- ============================================================================
-- 009_share_tokens.sql — public share links for delivered decks (P3 item 5)
--
-- PREREQUISITES: 001..008 applied, in order. Human-applied; never auto-run.
--
-- One nullable unguessable token per project. NULL = sharing disabled.
-- Rotation (write a fresh token) is revocation: the old token stops
-- resolving on the next lookup. The UNIQUE constraint's btree index makes
-- resolution an indexed equality probe — no prefix matching, no scans.
--
-- No RLS change: the public route resolves tokens server-side with the
-- service role; anon/authenticated clients still cannot read other users'
-- projects, and the token column rides the existing owner-only policy.
-- ============================================================================

alter table projects
    add column if not exists share_token text
        check (share_token is null or char_length(share_token) between 16 and 64);

alter table projects
    add constraint uq_projects_share_token unique (share_token);
