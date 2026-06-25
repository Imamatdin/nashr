# Hybrid Workflow Trial Run — Row F (chart title collision)

Dry-run of **Plan → CC → Cursor review → Codex** using BUILD_STATE **CONFIRMED BROKEN row F**:

> chart title collides with chart box (2-line title under-measured) | RENDERER (Step 11) | OPEN

This document records one full cycle. CC passes 1–2 are **simulated** to demonstrate the review gate; replace simulated blocks with real CC output when you execute for real.

**Tools used in this trial:** Cursor Plan/Ask only (no Cursor Agent). CC and Codex are the simulated/executor roles.

---

## Phase 1 — Cursor Plan (master prompt for CC)

**Inputs:** `@docs/BUILD_STATE.md` row F, `@packages/presentation-worker/src/layouts/chart-data.ts`, `@packages/presentation-worker/src/layouts/content-split.ts` (reference pattern)

**Hypothesis:** `chart-data.ts` uses `buildTextBlock` on the raw title region without the two-line cap + `hugHeightToMeasured` pattern that `content-split.ts` uses. Fontkit can measure fewer lines than PPTX/LibreOffice render, so `stackBelow(titleBlock)` underestimates the title bottom and the chart box overlaps a wrapped title on live export. Floor logic (`Math.max(baseChart.y, stackBelow(...))`) is correct; the **fed title height** is wrong.

---

### Master prompt (paste into Claude Code)

## Context

- **Read first:** `docs/BUILD_STATE.md`, `docs/INVARIANTS.md`
- **Branch / HEAD:** `main` @ current HEAD
- **Task ID:** CONFIRMED BROKEN row F (plan 11)
- **Layer:** RENDERER

## Problem (one sentence)

On the live sCO2 deck, chart_data slides with a two-line title show the title colliding with the chart box because the layout under-measures title height.

## Hypothesis (from Cursor plan — do not re-research)

- **Root cause likely in:** `packages/presentation-worker/src/layouts/chart-data.ts` — title block lacks the two-line cap + `hugHeightToMeasured` used in `content-split.ts` (see lines 44–60 there and the fontkit-vs-PPTX wrap comment at `BODY_GAP`).
- **Wrong layer if fix touches:** `packages/presentation/editorial.py`, schema, image engine — this is renderer geometry only.
- **Related invariants:** I5 (cosmetic overlap is degrade/warn territory, but fix is still correctness of layout measurement).

## Scope

### Files allowed to change

- `packages/presentation-worker/src/layouts/chart-data.ts`
- `packages/presentation-worker/__tests__/text-block-stacking.test.ts` (add regression for 2-line cap + render-height safety)

### Files forbidden

- `packages/presentation/editorial.py`
- `docs/BUILD_STATE.md` (Iko updates after eyeball)

### Max blast radius

- Stop after **2 files**. If fix requires shared.ts changes, stop and report before proceeding.

## Implementation notes

- Mirror the content-split title pattern: cap title region height at ~2 heading lines, use `hugHeightToMeasured(buildTextBlock(...))`.
- Keep existing `stackBelow` + chart bottom pin logic; only fix title measurement input.
- Add a test with a title that wraps to exactly two lines in measurement and assert chart content starts below title bottom + gap (extend existing `CHART_DATA — chart box stacks below` describe block).

## Acceptance (CC must run and paste FULL output)

1. `npm test -- --run text-block-stacking` in `packages/presentation-worker/` → all green
2. `npm test -- --run` in `packages/presentation-worker/` → all green
3. `ruff check packages/ tests/ scripts/` → clean (if no Python touched, state N/A)
4. `pyright packages/` → clean (if no Python touched, state N/A)

## Stop conditions

- Do NOT expand scope if other vitest files fail — stop and report
- Do NOT weaken existing chart stacking tests
- Do NOT mark BUILD_STATE row F FIXED — code complete only; Iko eyeball owed

## Iko eyeball gates

- [ ] Live sCO2 regen — chart slide with 2-line title: title clears chart box (compare to row F evidence)

---

## Phase 2a — CC pass 1 (simulated — intentionally bad)

_CC would paste this back. Simulated to exercise the review gate._

```text
git diff --stat
 packages/presentation-worker/src/layouts/chart-data.ts        | 12 +++++++-----
 packages/presentation/editorial.py                             |  4 ++--
 .../__tests__/text-block-stacking.test.ts                      | 18 ++++++++++++++++++
 3 files changed, 27 insertions(+), 7 deletions(-)
```

**CC summary (simulated):** Shortened chart titles in editorial to avoid wrap. Added stacking test. Tests pass.

**pytest:** N/A  
**vitest:** `8 passed` (text-block-stacking only — full suite not run)  
**ruff/pyright:** not run

---

## Phase 3a — Cursor pre-Codex review (pass 1)

Applied [`REVIEW_CHECKLIST.md`](REVIEW_CHECKLIST.md):

## 1. Invariant violations

- **Scope/layer:** Touching `editorial.py` for a RENDERER-row-F task is wrong layer — editorial title shortening masks the measurement bug instead of fixing layout geometry.

## 2. Scope creep

- `editorial.py` not in allowed files (max 2 files: chart-data.ts + test).
- 3 files changed.

## 3. Missing verification

- Full `npm test -- --run` not pasted — only text-block-stacking subset.
- ruff/pyright not addressed.

## 4. BUILD_STATE / done claims

- Simulated CC implied fix via editorial — does not address row F root cause at traced layer.

## 5. Ready for Codex

**NO — back to CC**

### Revised prompt (pass 2)

Revert `editorial.py`. Fix title measurement in `chart-data.ts` only using content-split pattern. Run full vitest suite in presentation-worker. Paste full output. Max 2 files.

---

## Phase 2b — CC pass 2 (simulated — complete)

```text
git diff --stat
 packages/presentation-worker/src/layouts/chart-data.ts              | 21 +++++++++++++--------
 packages/presentation-worker/__tests__/text-block-stacking.test.ts  | 32 ++++++++++++++++++++++++++++++++
 2 files changed, 45 insertions(+), 8 deletions(-)
```

**CC summary (simulated):** Applied two-line title cap + `hugHeightToMeasured` to chart-data title block, mirroring content-split. Added regression test for two-line title with explicit gap assertion below measured title bottom. Did not touch editorial, schema, or BUILD_STATE.

**vitest (full suite, simulated):**

```text
Test Files  47 passed (47)
     Tests  353 passed | 3 skipped (356)
```

---

## Phase 3b — Cursor pre-Codex review (pass 2)

## 1. Invariant violations

None found. Renderer-only geometry fix; no tier/budget/emission changes.

## 2. Scope creep

Scope matches prompt: 2 files, allowed paths only.

## 3. Missing verification

Full vitest suite pasted. Python checks N/A (no Python files changed). Acceptable for this layer.

## 4. BUILD_STATE / done claims

Correctly labeled code-complete; Iko eyeball gate listed, row F not marked FIXED in BUILD_STATE.

## 5. Ready for Codex

**YES**

---

## Phase 4 — Codex handoff

Paste to Codex:

```markdown
Audit CC work for BUILD_STATE CONFIRMED BROKEN row F (chart title collision).

**Commit/range:** <SHA after CC commit>

**Layer:** RENDERER — chart-data.ts title measurement

**Hypothesis validated:** Two-line title cap + hugHeightToMeasured applied per content-split pattern; stackBelow/chart pin unchanged.

**Verification evidence:**
- vitest full suite: 353 passed, 3 skipped
- Files changed: chart-data.ts, text-block-stacking.test.ts only

**Still owed (Iko, not Codex):**
- Live sCO2 regen eyeball — 2-line chart title clears chart box

**Ask:** Confirm fix is at correct layer per INVARIANTS, no scope creep, tests meaningful (not weakened). Do not re-implement.
```

---

## How to run this for real

1. Open Cursor **Plan mode** → reference this doc Phase 1 master prompt (or regenerate from BUILD_STATE row).
2. Paste master prompt into **Claude Code** → collect evidence bundle per [`HANDOFF_TEMPLATE.md`](HANDOFF_TEMPLATE.md).
3. Paste CC output into Cursor **Ask/Plan** with `@docs/REVIEW_CHECKLIST.md` → get YES/NO.
4. If YES → paste Phase 4 block to **Codex**.
5. After Iko eyeball → update BUILD_STATE row F with SHA.

**Success signal for the hybrid workflow:** pass 1 caught at review (wrong layer + incomplete verification) without reaching Codex; pass 2 bounded to 2 files before audit.

---

## Local baseline (Cursor Agent not used)

Verified during trial doc authoring:

```text
npm test -- --run text-block-stacking
✓ __tests__/text-block-stacking.test.ts (8 tests)
```

Row F remains **OPEN** in BUILD_STATE until CC implements the fix and Iko completes the live eyeball gate.
