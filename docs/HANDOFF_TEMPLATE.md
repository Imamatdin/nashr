# Handoff Template — Cursor Plan → Claude Code

Copy this skeleton when Cursor Plan mode produces a master prompt for CC.
Fill every section before pasting into Claude Code. Do not paste partial handoffs.

---

## Context

- **Read first:** `docs/BUILD_STATE.md`, `docs/INVARIANTS.md`
- **Branch / HEAD:** `main` @ `<git rev-parse --short HEAD>`
- **Task ID:** `<BUILD_STATE row, plan item, or ticket>`
- **Layer:** `<RENDERER | EDITORIAL | SCHEMA | IMAGE-ENGINE | ORCHESTRATOR>`

## Problem (one sentence)

`<What is broken, for whom, and where it shows up — e.g. "sCO2 slide 7 chart title overlaps plot on live render">`

## Hypothesis (from Cursor plan — CC must NOT re-research)

- **Root cause likely in:** `<path/to/file>` because `<evidence>`
- **Wrong layer if fix touches:** `<paths or layers that would violate INVARIANTS>`
- **Related invariants:** `<I1–I5 sections that constrain the fix>`

## Scope

### Files allowed to change

- `<path/to/file1>`
- `<path/to/file2>`

### Files forbidden

- `<editorial.py, schema, etc. — anything outside layer>`
- `docs/BUILD_STATE.md` (Iko updates after eyeball gate, not CC)

### Max blast radius

- Stop after **N files** changed. If fix requires more, stop and report — do not expand.

## Implementation notes

`<Optional: specific function names, test names, grep targets, screenshots under docs/screens/>`

## Acceptance (CC must run and paste FULL output)

1. `pytest tests/<relevant> -v --tb=short` → all green
2. `ruff check packages/ tests/ scripts/` → clean
3. `pyright packages/` → clean
4. `<gate-specific>` e.g. `npm test -- --run` in `packages/presentation-worker/`
5. `<optional live gate>` e.g. `python scripts/proof_planner_phase2.py`

## Evidence bundle (required in CC's final message)

CC must end with:

```text
git diff --stat
<full pytest output>
<full ruff output>
<full pyright output>
<gate output if applicable>
```

Plus one paragraph:

- What changed and why
- What was explicitly **not** touched
- Any eyeball gates still owed to Iko (list by name)

## Stop conditions

- Do **NOT** expand scope if tests reveal adjacent failures — stop and report with traceback
- Do **NOT** weaken or delete tests to make green
- Do **NOT** mark BUILD_STATE done without Iko eyeball gates listed below
- Do **NOT** fix at the wrong layer (see Hypothesis)

## Iko eyeball gates (if any)

- [ ] `<e.g. live sCO2 regen slide 7 — confirm title clears chart box>`
- [ ] `<e.g. grep slide 18 in /app/debug/last_deck.json>`

---

## CC evidence bundle template (paste back into Cursor for pre-Codex review)

When CC finishes, paste this block into Cursor Plan/Ask with `@docs/REVIEW_CHECKLIST.md`:

```markdown
## CC handoff for review

### Task ID
<same as above>

### git diff --stat
<paste>

### Key hunks
<paste or summarize>

### pytest
<paste full output>

### ruff
<paste full output>

### pyright
<paste full output>

### CC summary
<paste CC's one-paragraph summary>
```
