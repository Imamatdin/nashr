# Pre-Codex Review Checklist

Use this when Cursor audits a **Claude Code evidence bundle** before Codex.
Paste the CC handoff (see bottom of [`HANDOFF_TEMPLATE.md`](HANDOFF_TEMPLATE.md)) into Cursor Plan/Ask with:

> Review this CC handoff against INVARIANTS and BUILD_STATE using REVIEW_CHECKLIST.

Cursor reads repo context via `@docs/INVARIANTS.md`, `@docs/BUILD_STATE.md`, `@CLAUDE.md`.
**Do not switch to Agent mode** — review from pasted evidence + file references only.

---

## 1. Invariant violations

Check each load-bearing rule in [`INVARIANTS.md`](INVARIANTS.md):

| ID | Question | Fail if |
|----|----------|---------|
| **I1** | Does the change derive tier/budget/image count from `GenerationPackage`, not literals? | Hardcoded tier defaults on paid/visible paths |
| **I2** | Does every emitted slide carry real content weight? | Hollow dividers, stat-echo breathers enabled without model content |
| **I3** | Text over image has scrim; hero within budget; basic tier = zero AI images? | Missing scrim, hero bypassing budget |
| **I4** | Any TODO/stub/interim on tier/budget/emission/contrast paths? | Unapproved deferrals (only those named in INVARIANTS § authorized deferrals) |
| **I5** | Audit blocks export only on correctness failures, not cosmetic? | Q1/Q4-style cosmetic checks upgraded to `fail` without INVARIANTS amendment |

Also check BUILD_STATE **CONFIRMED BROKEN** row: fix is at the **traced layer**, not a symptom patch at the wrong layer.

**Output:** List each violation with file:line reference, or "none found".

---

## 2. Scope creep

Compare `git diff --stat` to the master prompt's **allowed files**:

- [ ] Every changed file was listed in "Files allowed to change"
- [ ] No forbidden paths touched (editorial when task was renderer-only, etc.)
- [ ] File count within "Max blast radius"
- [ ] No unrelated refactors, renames, or formatting-only sweeps
- [ ] BUILD_STATE not updated by CC unless the prompt explicitly authorized it

**Output:** List creep items, or "scope matches prompt".

---

## 3. Missing verification

Per [`CLAUDE.md`](../CLAUDE.md) Task Protocol — CC must show **full output**, not summaries:

- [ ] `pytest` — full output pasted, all green (or CC stopped per stop conditions)
- [ ] `ruff check` — full output pasted, clean
- [ ] `pyright packages/` — full output pasted, clean
- [ ] Gate-specific commands from the prompt (vitest, proof scripts) — output pasted
- [ ] No "tests pass" claim without pasted output
- [ ] No weakened/deleted tests to force green
- [ ] CC summary states what was **not** touched

If any check is missing: **not ready for Codex** — send back to CC with the exact command to run.

**Output:** List missing items, or "verification complete".

---

## 4. BUILD_STATE / done claims

- [ ] CC did not mark task DONE in BUILD_STATE without Iko eyeball gates
- [ ] Any "FIXED" claim cites a commit SHA or is labeled "code complete, gate owed"
- [ ] Live/server gates from the prompt are listed as still owed, not silently dropped
- [ ] Layer assignment matches BUILD_STATE CONFIRMED BROKEN tracing notes

**Output:** List false done-claims, or "done-claims honest".

---

## 5. Ready for Codex

| Verdict | When |
|---------|------|
| **YES** | No invariant violations, scope matches, full verification pasted, done-claims honest |
| **NO — back to CC** | Any failure in sections 1–4; include revised bounded prompt |
| **NO — back to Cursor Plan** | Wrong layer traced; need new hypothesis before another CC pass |

### Codex handoff (when YES)

Give Codex:

1. Link to commit or `git diff` range
2. Master prompt Task ID + hypothesis
3. Pasted verification output (pytest/ruff/pyright/gates)
4. Explicit eyeball gates still owed to Iko
5. Ask Codex to audit against INVARIANTS + BUILD_STATE row, not re-implement

---

## Cursor response format

Always reply in this structure:

```markdown
## 1. Invariant violations
...

## 2. Scope creep
...

## 3. Missing verification
...

## 4. BUILD_STATE / done claims
...

## 5. Ready for Codex
YES | NO — <reason>

### If NO: next CC prompt revision
<bounded changes only>
```
