---
paths:
  - "packages/workers/article/**"
  - "packages/workers/presentation/**"
  - "packages/academic/**"
---

# LLM & External API Rules

- Every LLM call logs: model, input_tokens, output_tokens, latency_ms, estimated_cost_usd
- Every LLM output is validated against a pydantic model before use. If validation fails, retry once with the error message appended to the prompt. If still fails, use partial result or fail the job.
- System prompts are constants in a dedicated file, never inline strings scattered across code.
- LLM timeout: 30s. External API timeout: 10s. Retry: max 2 with exponential backoff.
- Per-job cost limits are enforced. If a job exceeds its budget cap, stop and return partial results.
- Haiku 4.5 for cheap work (parsing, scoring, verification). Sonnet 4.6 for quality work (drafting, design, layout). Never use Opus for runtime user jobs.
- Academic API rate limits: Semantic Scholar 100/5min, arXiv 3/sec. Respect them with rate limiting.
- All external API responses validated at the boundary. Never trust shape of external JSON without parsing into a model.
