---
paths:
  - "packages/core/**"
---

# Core Models Rules

- Every model uses `model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)`
- Every field that has a finite set of values uses a StrEnum from enums.py, never a raw str
- Every list field that stores user or LLM output has a max length constraint
- Every str field that stores user or LLM output has max_length in Field()
- No dict[str, Any] or dict[str, str]. If you need a map, define a typed BaseModel.
- Database row models must have: id (uuid), created_at (datetime)
- Validators test actual constraints, not just type coercion
- When adding a new enum value, also update the CHECK constraint in the SQL migration
- Round-trip test: every model must serialize to dict and reconstruct without data loss
