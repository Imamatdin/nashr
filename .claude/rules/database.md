---
paths:
  - "supabase/**"
---

# Database Rules

- Every table has uuid primary key with DEFAULT gen_random_uuid()
- Every table with user data has RLS enabled AND a policy defined
- Every foreign key specifies ON DELETE CASCADE or ON DELETE SET NULL
- credit_ledger is append-only: no UPDATE or DELETE allowed
- Every enum-shaped column has a CHECK constraint matching the Python StrEnum values
- All timestamps use timestamptz (not timestamp) with DEFAULT now()
- All text columns storing user/LLM input have length CHECK constraints
- Every migration is reversible (include DOWN migration as comment block)
- Indexes on: users.telegram_id, projects.user_id, sources.project_id, generation_jobs.project_id, credit_ledger.user_id
- When adding enum values in Python, also add them to the SQL CHECK constraint in the same commit
