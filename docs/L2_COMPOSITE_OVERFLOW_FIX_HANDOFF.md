# L2 Composite-Overflow Fix — Codex Handoff

**Status:** uncommitted, un-merged, on `main` working tree, layered on top of the 3a–3d migration (same combined branch). **3e (matching, categorize) is NOT in this batch.**

**Gate:** `typecheck` clean; full suite **443 passed / 4 skipped** (skips are pdf-renderer / Playwright).

**Why:** the 3a–3d adversarial review flagged (and the earlier handoff documented) that the composite-item recipe measured each sub-block against the full remaining height with `overflow:'truncate'`, so a tall multi-item stack ran off the slide bottom *silently* (`hasOverflow` stayed false). This batch fixes that pattern-level hole — including in `concept_definition`, which shipped it on `main`.

---

## What shipped

### New shared helper — `fitCompositeStack` (`src/layouts/shared.ts`)
Places "composite items" (each a short vertical sub-stack that must stay together) into a region, **scaling-to-fit**:
1. **Measure** each sub-block tall (natural height); fit the composite items with `fitMeasuredStack(overflow:'scale')`.
2. When the natural stack fits, `scale === 1` and the placement is **byte-identical** to the old `overflow:'truncate'` path (so existing tests stay green).
3. When it overflows (`scale < 1`), **rebuild** each sub-block bounded to `natural * scale` (gaps scaled by the same factor) so `buildTextBlock` shrinks the font — and truncates only as a last resort — against the **real** budget. It **rebuilds, never clamps tops** (clamping tops while blocks keep natural height would silently overlap).
4. Sets `block.overflow` when a sub still can't fit at the font floor after scaling, so `compose()`'s `hasOverflow` becomes true (genuine can't-fit is observable).

**No-silent-overlap guarantee (the cardinal property):** `buildTextBlock` sets `overflow = !fitsInBox` and always re-measures `measuredHeightPct` to the fitting (possibly truncated) text. So `measuredHeightPct > budget ⟹ overflow=true`. The helper propagates that to `hasOverflow`. Therefore **overlap ⟹ overflow ⟹ hasOverflow** — overlap can never be silent. Containment arithmetic: each rebuilt sub ≤ `natural*scale` and gaps scale identically ⇒ item content ≤ its scaled band, scaled bands+gaps sum to exactly `region.h` ⇒ last block bottom ≤ region bottom.

### Adopted in 5 composite-recipe layouts
`interactive-fill-blank`, `interactive-true-false`, `interactive-debate`, `resources-links`, `concept-definition`. Each replaced its inline two-pass loop with `fitCompositeStack`. The three interactive layouts also **reserve trigger space** (`bandRegion.h = TRIGGER_FLOOR_Y − TRIGGER_GAP − BAND_Y`) so the reveal trigger never overlaps content; `resources` and `concept_definition` use the full height (no trigger).

Byte-identical preservation confirmed (adversarial reviewer, field-by-field): every sub-block's role / groupId / dataIndex / text / colour / weight / style / tier / lineHeight / x / w is unchanged — only y/h are engine-driven. Landmines preserved: true_false verdict colour (`is_true ? accent : '#C0392B'`, x:10/w:40); debate framework's deliberate `tier:small + lineHeight:caption` mismatch; resources url=accent/desc=text_secondary/name=text with no roles; concept's hugged title (still `hugHeightToMeasured`, outside the helper) + figure + scrim.

---

## Empirical before/after (throwaway probe, removed)
Bottom-margin line = 94 (`100 − MARGIN.bottom`).

| layout | tall case | was | now | hasOverflow |
|---|---|---|---|---|
| true_false | 5 long items | 128.6 | **92.7** | true (scaled + truncated → flagged) |
| fill_blank | 5 long items | 128.7 | **92.6** | false (scaled cleanly, no data loss) |
| resources | 6 long items | 110.2 | **92.0** | true (truncated → flagged) |
| debate | 3 long items | 88.1 | 88.1 | false (already fit) |

(`maxBottom` figures include the reveal trigger in its reserved zone; content blocks are contained to ≤90/90/92 per band.) `hasOverflow` is true **exactly** when content truncates — the intended signal.

---

## Tests
Per layout, two new tripwires (pure additions; no existing test weakened):
- **`scales tall content … no block past the 94% bottom margin`** — the probed tall case; asserts `max(content bottom) ≤ 94` and (interactive) `trigger.y ≤ FLOOR` **and `trigger.y ≥ maxBottom`** (trigger below content — the real no-overlap guard). Fails on the pre-fix off-slide code.
- **`flags hasOverflow when content cannot fit even after scaling`** — extreme content; asserts still on-slide **and** `hasOverflow === true`.

Plus the fill_blank/concept fitting-case tests (and all prior 3a–3d tests) remain green, confirming scale==1 geometry is unchanged.

One agent-added resources assertion (`descs.every(!truncated)`) was **removed**: 6×30-word descriptions legitimately truncate after scaling, so the claim was incorrect; the `maxBottom ≤ 94` tripwire (the required guard) remains, and the separate hasOverflow test covers the truncation path.

---

## Verification performed
- Full typecheck + suite green (443).
- Independent read of all 5 migrated layouts + the helper; no-silent-overlap proven from the `buildTextBlock` contract + scale arithmetic.
- Empirical probe (above) confirming containment + correct `hasOverflow`.
- 3-dimension adversarial panel: adoption-fidelity returned a clean PASS; the helper-correctness and fitting-unchanged agents did not emit final reports (harness quirk), so those dimensions were verified directly (code contract, the green fitting-case suite, the probe).

## Open nits (non-blocking)
- Interactive tall-tests assert the loose `≤94` rather than each band's true bottom (90/90/92); the stricter `trigger.y ≥ content` assertion already guards the real overlap risk.
- `resources` test content filter mixes `&&`/`||` unparenthesized (correct by precedence; readability only).

## Not in scope
**3e** — `interactive_matching` (2D row-synced grid) and `interactive_categorize` (independent columns + add its missing per-column overflow guard). Different grid mechanics → separate batch.
