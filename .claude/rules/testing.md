---
paths:
  - "tests/**"
---

# Testing Rules

- Tests test BEHAVIOR, not implementation. Assert on outputs and effects, not internal state.
- Every test must assert something meaningful. `assert result is not None` tests nothing.
- No conditional assertions. `if result.pages: assert ...` hides whether the condition was met. Pin expected values.
- Do not mock Magika, fitz, python-docx, or other local libraries. Use real libraries with real files.
- Mock only: external HTTP APIs (Semantic Scholar, arXiv, CrossRef, OpenAlex), LLM APIs (Anthropic, Google), payment providers (Payme, Click).
- Golden files in tests/golden/ are permanent fixtures. Do not delete or modify them without discussion.
- Integration tests must exercise the real code path, not just unit-level functions.
- Every new parser or service must have tests that use golden files.
- For PDF/DOCX/PPTX tests that need custom fixtures, create them inline in the test using reportlab/python-docx/python-pptx. Do not add to golden/ unless they serve as permanent fixtures.
- When testing LLM-dependent code, test the validation/parsing of LLM output, not the LLM call itself. Use fixture JSON that represents realistic LLM responses.
