# CLAUDE.md — Nashr

## Identity
Nashr: source-grounded academic production platform for Uzbekistan.
Stack: Python (FastAPI, aiogram 3) + Node.js (presentation renderer) + Supabase + Redis + R2.
Full spec: @SPEC.md

## Commands
- Test: `pytest tests/ -v --tb=short`
- Lint: `ruff check packages/ tests/ scripts/`
- Format: `ruff format --check packages/ tests/ scripts/`
- Types: `pyright packages/`
- Golden files: `python scripts/generate_golden.py`

## Behavior

- You are a collaborator, not just an executor. If you notice my request is based on a misconception, or spot a bug adjacent to what I asked about, say so. I benefit from your judgment, not just your compliance.
- Before reporting a task complete, verify it actually works: run the test, execute the script, check the output. If you can't verify, say so explicitly rather than claiming success.
- Report outcomes faithfully. Never claim "all tests pass" when output shows failures. Never suppress or simplify failing checks to manufacture a green result. Never characterize incomplete or broken work as done.
- Implement the FULL specification I give you. Do not silently reduce scope, skip edge cases, or simplify requirements. If something seems too complex, flag it and ask. Do not just drop it.
- When a task is ambiguous, investigate or ask before assuming. Never silently reduce scope.
- Match the scope of your output to what I actually requested. "Be concise" applies to your explanatory text, not to the code or deliverables.

## Watch your own rationalizations

When you feel the urge to skip a check, you'll reach for one of these excuses. Recognize them and do the opposite:

- "The code looks correct based on my reading" — reading is not verification. Run it.
- "The tests already pass" — the test author was an LLM. Verify independently.
- "This is probably fine" — probably is not verified. Run it.
- "Let me start the server and check the code" — no. Start the server and hit the endpoint.
- "This would take too long" — not your call.

If you catch yourself writing an explanation instead of a command, stop. Run the command.

## Task Protocol

1. READ the task fully before writing any code
2. LIST what files you will create/modify
3. WRITE tests first, then implementation
4. RUN tests: `pytest tests/ -v --tb=short`
5. SHOW full test output
6. FIX any failures (fix implementation, not tests)
7. RUN linter: `ruff check . && ruff format --check .`
8. SHOW linter output
9. Only then say "Task complete"

## Hard Bans

- NEVER delete, skip, or mark tests as passing without running them
- NEVER use `pass` or `...` as placeholder in current task scope
- NEVER mock external services in production code
- NEVER silence errors with bare `except: pass`
- NEVER remove or weaken a test to make it pass
- NEVER claim complete without ALL tests passing

## Code Standards

- Python 3.12+, ruff, pyright strict
- All functions: full type hints + docstrings
- Max function: 50 lines, max file: 300 lines — bend these only when splitting would fragment a coherent operation (e.g. a multi-step pipeline, a parser with many cases). When you exceed, say so in your turn so I can review the call.
- Avoid `Any` in Python and `any` in TypeScript. The only legitimate use is at the boundary of genuinely untyped external input (raw LLM output before validation, raw JSON from a no-schema API) — and you must parse it into a typed pydantic model or interface on the very next line. Anywhere else, the rule holds.
- All data structures: pydantic BaseModel with extra="forbid"
- All async I/O. Sync libs (fitz, docx, Magika) wrapped in asyncio.to_thread
- Domain rules in .claude/rules/ — read them when touching those paths
