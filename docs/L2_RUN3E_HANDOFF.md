# L2 Run 3e — Codex Handoff (matching + categorize) — FINAL batch

**Status:** uncommitted, un-merged, on `main` working tree, layered on top of 3a–3d + the composite-overflow fix. This is the **last batch**; the whole branch (3a + 3b + 3c + 3d + composite-overflow fix + 3e) deploys & renders with Iko in one pass before any merge.

**Gate:** `typecheck` clean; full suite **447 passed / 4 skipped** (skips are pdf-renderer / Playwright).

---

## What shipped

### `interactive_matching` — row-synced measured rows + scale-to-fit
Replaced the fixed `PAIR_BLOCK_H=12` pitch with measured rows. Each row's height is the taller of its two columns (`max(left, right)` measured); **one `bandTop` per row is reused for the left block, the right block, and the dashed connector** (placed at `bandTop + rowH/2`), so `left_i.y === right_i.y` and the connector always reads as their shared row. The two columns' x/w (5/28, 64/31), the connector geometry (34/28, dashArray `'4 4'`, stroke/opacity), roles (`match_left`/`match_right`), groupId (`m{i}`), dataIndex, and text are **frozen** — only the shared vertical position is engine-driven. The row stack **scales-to-fit** (`fitMeasuredStack(overflow:'scale')` + bounded rebuild of both columns) so long terms can't run off the slide; the reveal trigger is recomputed from the last row bottom (clamped to 88). A scaling-forced truncation is promoted to `overflow` for **parity with `fitCompositeStack`** (see review note below).

### `interactive_categorize` — per-column overflow guard (the real payoff)
Each column's items are now fit **independently** on their own vertical axis via `fitCompositeStack` over `{x:col.x+1, y:ITEMS_START_Y, w:col.w-2, h:availableHeightBelow(ITEMS_START_Y)}`. This adds the **previously-missing per-column overflow guard**: a tall column scales-to-fit (and flags `hasOverflow` if it still can't) instead of running its items off the slide on the old fixed `ITEM_STEP=5` pitch. The category-label header band (`LABEL_Y`) and every column's x/w stay frozen; columns are independent (one tall column never shifts or rescales another — all columns' first item starts at `ITEMS_START_Y`). Roles (`category_label`/`category_item`), groupId (`cat{i}`), dataIndex, text, colours preserved.

---

## Tests (tripwires landed first, per instruction)
- **matching:** `row-syncs left, right, and the connector on one bandTop per pair` (left.y===right.y + connector at row mid + non-overlap), `scales tall pairs to fit on-slide` (≤94, row-sync asserted in the scaled regime too), `flags hasOverflow when a pair cannot fit even after scaling`.
- **categorize:** `fits each column independently — a tall column stays on-slide and does not desync the others` (20-item column ≤94; both columns' first item at the same band top; short column not shrunk by the tall one's overflow).

---

## Adversarial review (this batch)
opus panel on the 4 focus areas. The matching-row-sync reviewer returned a full **PASS on the mechanics** — proved mathematically that left.y===right.y in both paths, the connector is always in-row, rows can't overlap (band 16→86, scaled bands+gaps sum to region.h), geometry frozen, and the tripwire is non-vacuous. It caught one legitimate **parity gap which I then fixed**: matching's `scale<1` rebuild wasn't promoting a scaling-forced truncation to `overflow` (so it would degrade silently, unlike the shared helper). Now fixed (`if (truncated && !naturalTruncated) overflow = true`) + covered by the new `hasOverflow` matching test. (The other three reviewer agents didn't emit final reports — a harness quirk seen repeatedly this branch — so those dimensions were verified directly: the helper no-silent-overlap proof from the `buildTextBlock` contract, concept_definition byte-identical via the earlier overflow-fix review PASS + green fitting tests, and categorize independence via its tripwire.)

## Independent Codex review (gpt-5.5, xhigh) — verdict: FIX-FIRST
Run via `codex exec -s read-only -m gpt-5.5 -c model_reasoning_effort=xhigh` on a **path-scoped patch of only `packages/presentation-worker`** (NOT `--uncommitted`, which would have swept the untracked SSH key — see security note).

Codex confirmed the requested checks (no top-clamping; concept_definition scale===1 byte-identical; matching row-sync holds; categorize columns independent; frozen layouts comment-only + intended getPortraitPositions) and found **two real bugs — both independently verified against the code:**

1. **High — `fitCompositeStack` doesn't surface ALL final truncation as overflow.** The `scale<1` branch flags overflow only when `truncated && !naturalTruncated`; the `scale===1` path never converts `truncated`→`overflow`. So a sub-block too tall even in the natural/full-band pass stays truncated without `compose()` seeing `hasOverflow` — violates the no-silent-overflow contract. **Verified:** the `scale===1` branch reuses `s.block` and never inspects `.truncated`; the `naturalTruncated` exclusion drops the both-passes-truncated case.
2. **Medium — matching scaled rebuild over-shrinks the short side.** Each side is rebuilt against its OWN `measuredHeightPct*scale` instead of the shared row budget `r.natural*scale`. In an asymmetric row (one tall, one short), the short side is over-constrained even though the row band has room. **Verified:** lines rebuild `left` at `r.left.measuredHeightPct*scale` and `right` at `r.right.measuredHeightPct*scale` — should both be `r.natural*scale`.

**Fixes applied (both Codex findings closed):**
- **High** — `fitCompositeStack` now sets `block.overflow = true` whenever the FINAL emitted block is `truncated`, in BOTH the scale===1 and scale<1 paths (the `naturalTruncated` exclusion is removed). Invariant: *final emitted truncation ⟹ hasOverflow*, no exception for origin. New tripwire (`layout-concept-definition.test.ts`): a single item truncated at the natural/full pass (scale===1) → `hasOverflow === true` (the exact case the old proof missed).
- **Medium** — matching rebuilds BOTH sides against the shared scaled row height `r.natural*scale` (not each side's own), so the short side of an asymmetric row isn't over-shrunk; and final truncation is flagged as overflow in both paths (parity with the helper, applied unconditionally — slightly beyond the literal ask, to keep the invariant uniform). New tripwire (`interactive-matching.test.ts`): tall-left/short-right ×6 in the scaled regime → short side at full tier size + row-synced.

Re-gate after fixes: full suite **449 passed / 4 skipped**, typecheck clean.

**Codex confirmation pass (gpt-5.5, xhigh, path-scoped delta): Issue 1 CLOSED, Issue 2 CLOSED.** Codex verified the unconditional final-truncation→overflow funnel in both helper paths and the shared `r.natural*scale` row budget + both-sided truncation flag in matching, and judged both new tripwires non-vacuous. It offered two OPTIONAL test-sharpenings, **both now applied**: the concept scale===1 test asserts `def.overflow === true` directly, and the matching overflow test asserts `content.some(b => b.truncated && b.overflow)`. Both assert the block-level `overflow` flag, not just the downstream `hasOverflow`. Re-gate after sharpenings: full suite **449 passed / 4 skipped**, typecheck clean. Verbatim output of both Codex passes is in the chat replies for this batch.

## ⚠ Security note (unrelated to this branch, but flagged)
`git status` shows an **untracked private SSH key `nashr-droplet`** (+ `.pub`) and a `files (5).zip` sitting in the repo working tree, plus `.review-build/` compiled output. The private key should be moved out of the repo or `.gitignore`d — and it must never be swept into an external review (this is why the Codex pass used a scoped patch, not `--uncommitted`).

## Not in scope
Nothing further in the L2 Run-3 sequence — 3e is the last batch. Next is the whole-branch Iko deploy+render pass before merge.
