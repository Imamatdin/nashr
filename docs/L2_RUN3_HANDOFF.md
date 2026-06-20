# L2 Run 3 — Codex Handoff (3a + 3b + 3c + 3d)

> **UPDATE:** the "KNOWN ISSUE — vertical overflow" flagged below has since been FIXED in a follow-up batch on this same branch — see `docs/L2_COMPOSITE_OVERFLOW_FIX_HANDOFF.md` (shared `fitCompositeStack` scale-to-fit helper, adopted across the composite layouts incl. `concept_definition`). Suite is now 443 green.

**Status:** uncommitted, un-merged, on `main` working tree. One combined branch for a single deploy+render pass with Iko. **3e (matching, categorize) is intentionally NOT in this run.**

**Gate:** `npm --prefix packages/presentation-worker run typecheck` clean; `npm … run test` → **433 passed / 4 skipped** (skips are `pdf-renderer` — Playwright only).

---

## What shipped

### 3a — keep-frozen + re-document (the 4 layouts that should NOT migrate)
The recon found `timeline`, `gallery_people`, `team_credits`, `interactive_quiz` encode geometry a vertical fit cannot reconstruct (horizontal armatures, a reserved portrait band + shared caption baseline, co-located feedback overlays). They were **re-documented as frozen-by-design** (comment-only), with **zero `fitMeasuredStack`/hug/stack/availableHeightBelow calls** — verified by grep and confirmed clean by an independent reviewer.

One real fix landed inside the shared allocator:
- **`constants.ts getPortraitPositions`**: false docstring corrected; **counts 1 & 2 now centre about x=50** (count1 → x:43; count2 → x:34.5/51.5) instead of left-clustering at the 5-slot x:5/x:22 fall-through. **Only `x` changed — `y:15` and band `h` are frozen.** Propagates to both `gallery_people` and `team_credits` (shared allocator). Centring is test-covered for both consumers (team_credits in `layout-team-credits.test.ts`; gallery_people in `layout-pass.test.ts`).

Tripwires added (3a): quiz feedback overlay co-location (two feedback blocks share a y), gallery/team shared caption baseline + small-count centring. All proven to bite (stash-revert → red).

### 3b — clean-migrate pilot: `interactive_fill_blank`
Migrated to the **composite-item `fitMeasuredStack` recipe** (mirrors the shipped `concept-definition.ts`/`content-split.ts`): each item is a composite of its sub-blocks hugged + inner-stacked; items placed top-down by `fitMeasuredStack(anchor:'start', overflow:'truncate')`; title/subtitle stay frozen chrome; `reveal_trigger` Y recomputed from the last fitted item's measured bottom; `MAX_ITEMS=5` cap + silent overflow preserved; role/groupId/dataIndex/text/colours byte-identical. The "wraps-a-long-statement-instead-of-truncating" tripwire was proven to bite (stash-revert → red: old fixed-slot code truncated the statement).

### 3c — synthetic fixture for the dark layouts
`__tests__/fixtures/run3-coverage.json` + `__tests__/run3-coverage.test.ts` render-verify the 5 layouts no other deck fixture exercised (`team_credits`, `resources_links`, `interactive_categorize`, `interactive_true_false`, `interactive_debate`). 6/6 green.

### 3d — clean-migrate (same recipe): `resources_links`, `interactive_true_false`, `interactive_debate`
Three independent layouts migrated on the proven recipe. Independently diff-reviewed: roles/groupId/dataIndex/text/colours (incl. `FALSE_VERDICT_COLOR='#C0392B'` and the `is_true ? accent : red` logic), x/w, and frozen chrome (title/subtitle/`debate_prompt`) are all preserved; only vertical geometry is engine-driven; triggers recomputed from the last fitted bottom; `MAX_*` caps + silent overflow preserved. No shared-file drift (`shared.ts`/`fit.ts`/`types.ts`/`labels.ts`/renderers untouched).

---

## Files changed
- **Layouts (migrated):** `interactive-fill-blank.ts`, `resources-links.ts`, `interactive-true-false.ts`, `interactive-debate.ts`
- **Layouts (frozen, comment-only):** `timeline.ts`, `gallery-people.ts`, `team-credits.ts`, `interactive-quiz.ts`
- **Shared (1 real change):** `constants.ts` (getPortraitPositions centring + docstring) — *the only non-comment change outside the 4 migrated layouts*
- **Tests:** added tripwires to the 8 test files above; new `run3-coverage.test.ts` + `fixtures/run3-coverage.json`. **All test diffs are pure additions — no existing test weakened or deleted.**

---

## Adversarial review outcome (4 reviewers)
- **Byte-identical preservation:** PASS (only nit: `tIdx → i` loop rename in true_false — value-preserving, same emitted ids).
- **Family-A frozen + shared-file integrity:** PASS (zero fit calls in frozen layouts; constants.ts isolated to getPortraitPositions; no shared/renderer drift; centring math correct).
- **Regressions / tripwire quality:** one corroborated **known issue** (below) + minor test-hardening notes.

### KNOWN ISSUE (deferred, flagged for your decision) — vertical overflow of tall multi-item content
**What:** The composite recipe measures each sub-block against an unbounded band (`region.h = availableHeightBelow(BAND_Y)`, ~60–78%) and fits with `overflow:'truncate'` (scale stays 1, no bottom clamp). So when the summed measured heights of the capped items exceed the band, later items run **past the slide bottom**, and because each block individually fits its huge measuring box, `block.overflow` is false → **`layout.hasOverflow` stays false (silent to the Q1 audit)**.

**Empirically confirmed** (throwaway probe, since removed — bottom-margin line = 94):
- `true_false` 5 long items → maxBottom **128.6**
- `fill_blank` 5 long items → maxBottom **128.7**
- `resources` 6 long items → maxBottom **110.2**
- `debate` 3 long items → maxBottom **88.1 (fits — only 3 positions)**

**Faithful framing (not "strictly worse"):** the migration is **better in the common, editorially-bounded case** (short content no longer truncated/clipped — the whole point) and **worse only in the tall edge case** (old fixed slots truncated *on-slide* and set `truncated=true`; the new path spills *off-slide* silently). The reveal-trigger clamp (`Math.min(lastBottom+gap, FLOOR)`) is the **same root cause**: in the tall case the trigger snaps to the floor while content runs below it → overlap.

**This is a pattern-level risk, not a defect unique to this migration:** the recipe faithfully mirrors the *shipped, reviewed* `concept-definition.ts`. But `concept_definition`'s items are one-liners, whereas interactive statements/positions wrap long — **the migration extends a latent pattern risk into a higher-risk context.**

**Recommended fix (its own scoped task, not a bolt-on here):** a shared composite-fit helper using the `overflow:'scale'` + per-cell-rebuild contract (the `table_compact`/`emitBandCell` pattern) so an overflowing stack scales/truncates *on-slide* and re-sets the audit breadcrumb — and apply it to `concept_definition` too. **Deliberately not rushed in this run:** a wrong proportional split across composite sub-blocks would ship *silent overlap*, which is worse than a documented overflow, and the structural tests can't catch a bad split. Two gates remain (this Codex pass + the Iko render+eyeball) to catch visual cases meanwhile.

**Fixed in response to review:** the `interactive-debate.test.ts` reveal-trigger assertion was unconditional (`trigger.y >= lastFrameworkBottom`) and would have failed if the clamp ever fired — now guarded with `if (trigger.y < 94)`, matching the fill_blank/true_false tests.

---

## Verification performed
- Independent line-by-line diff review of all 4 migrated layouts (not trusting agent self-reports).
- Full typecheck + full suite green (433 passed).
- Tripwire bite proofs via stash-revert (3a centring; 3b/3d wrap-not-truncate).
- 4-dimension adversarial review; the one substantive finding empirically confirmed with a probe.

## Not in scope (next run)
**3e** — `interactive_matching` (2D row-synced grid; keep x/w + connector frozen, one band per row) and `interactive_categorize` (independent columns + add the missing per-column overflow guard). Different grid mechanics → separate batch.
