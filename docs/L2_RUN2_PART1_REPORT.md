# L2 Layout Engine — Run 2 of 4 (part 1): handoff report

**For:** Claude on the web (the author of the original Run-2 brief)
**From:** Claude Code (local, Opus 4.8) working in `C:\Users\imama\Projects\nashr`
**Status:** code complete, local gate GREEN, **not committed**. Independent Codex review appended at the bottom (§5).
**Scope shipped:** migrate `comparison`, `concept_definition`, `typographic_keywords` onto the shared `fitMeasuredStack` engine. `data_emphasis` remains out of scope (Run 2b).

---

## 1. What happened (narrative)

The brief was directionally correct but had three points that needed a senior pass against the real source. They were resolved before coding:

1. **`typographic_keywords` anchor.** The brief asked for both *"rows centered"* and *"dead gap between title and first row gone."* These conflict: with `anchor:'center'`, 3 keywords land mid-slide and strand a ~30% gap under the title. The human owner was asked and chose **`anchor:'start'` (rows hug the title; whitespace pools at the bottom)**. This made all three layouts uniformly `anchor:'start'`.

2. **No `emitBandCell` anywhere.** For keyword rows the term + explanation share a row top but **each hugs its own measured height** (top-aligned, like a `<dl>`). `rowHeight = max(term, explain)` is used **only** as the fit item's `measure()` so the *next* row clears the taller cell. The human owner confirmed top-align over middle-align (`emitBandCell` stays table-only). **This is the exact mechanism you flagged — §3 shows the literal code.**

3. **`concept_definition` title stays OUTSIDE the engine call** (refinement over the brief's literal "items `[title, definition, …bullets]`"). The title is built + hugged + pushed exactly as before; only `[definition?, …bullets]` go through one `fitMeasuredStack`. This keeps the title's geometry provably byte-identical and is lower risk.

**Engine fact that makes the migration clean:** `fitMeasuredStack` uses **only `region.y` and `region.h`** for vertical math — `region.x`/`region.w` are ignored. So every pre-built block keeps its own `x`/`w`; the region handed to the engine is purely a vertical box. (That is why `concept_definition`'s title at `w=50` and body at `w=48` coexist under one region, and why comparison's left `x=5` / right `x=52` survive untouched.)

**Tests** were delegated to a small multi-agent workflow (Opus-only sub-agents): one agent rewrote the typographic test, one created a new `layout-comparison.test.ts`, and a third was meant to adversarially verify. The verifier **aborted on a structured-output technicality** (it finished its reasoning but didn't emit the required JSON schema), so its pass never landed — which is why an independent Codex review is being run instead (§5). The two authoring agents completed and their files are in the tree.

**Local gate (run by Claude Code, authoritative):**
```
npm --prefix packages/presentation-worker run build       # tsc — clean
npm --prefix packages/presentation-worker run typecheck   # tsc --noEmit (src + tsconfig.test.json) — clean
npm --prefix packages/presentation-worker run test        # vitest run — 399 passed, 4 skipped
```
The 4 skips are pre-existing (pdf-renderer Playwright env ×3, one text-measure case) — unrelated to this change. New/changed test files: `layout-comparison.test.ts` 8/8, `layout-typographic-keywords.test.ts` 3/3, `layout-concept-definition.test.ts` 9/9 (tripwire, untouched), `layout-pass.test.ts` 24/24 (comparison `is_preferred` + concept figure tripwires).

---

## 2. The keyword row mechanism, proven by code (your specific concern)

You wrote: *"the report describes the keyword row mechanism correctly in prose but I haven't seen whether the code does the max-only-for-spacing, hug-each-cell thing it claims."* Here are the exact lines from `src/layouts/typographic-keywords.ts` (full diff in §3):

```ts
const rows = keywords.map((kw) => {
  const term = buildTextBlock({ /* x:TERM_X, w:TERM_W, h:contentH, accent, bold */ });
  const explain = buildTextBlock({ /* x:EXPLAIN_X, w:EXPLAIN_W, h:contentH, text_secondary */ });
  return {
    term,
    explain,
    rowHeight: Math.max(term.measuredHeightPct, explain.measuredHeightPct),  // <-- max computed here
  };
});

const fit = fitMeasuredStack({
  region: { x: TERM_X, y: contentTop, w: 90, h: contentH },
  items: rows.map((r) => ({ measure: () => r.rowHeight, gapAfter: ROW_GAP })),  // <-- max used ONLY as the item measure (spaces the next row)
  overflow: 'truncate',
  anchor: 'start',
});

rows.forEach((r, i) => {
  r.term.y = fit.tops[i]!;       // shared row top
  r.explain.y = fit.tops[i]!;    // shared row top
  hugHeightToMeasured(r.term);   // <-- term hugs its OWN measured height
  hugHeightToMeasured(r.explain);// <-- explanation hugs its OWN measured height
  blocks.push(r.term, r.explain);
});
```

Confirming each claim:
- **max-only-for-spacing:** `rowHeight` is consumed at exactly one place — `measure: () => r.rowHeight` inside `items`. Because `anchor:'start'` makes `tops[i+1] = tops[i] + rowHeight_i + ROW_GAP`, the max only determines where the *next* row starts. It is never assigned to `term.h` or `explain.h`.
- **hug-each-cell:** after placement, `hugHeightToMeasured(r.term)` and `hugHeightToMeasured(r.explain)` set each block's `h` to *its own* `measuredHeightPct + 0.2` (the engine's hug epsilon). The shorter cell does **not** get stretched to `rowHeight`. (`hugHeightToMeasured` is in `src/layouts/shared.ts`: `block.h = block.measuredHeightPct + HUG_EPSILON_PCT`.)
- **no `emitBandCell`:** there is no `emitBandCell` import or call; `valign` is left unset (top). The rewritten test asserts `terms[0].valign === 'top' || undefined` precisely to lock this.

The same place-then-hug idiom is used in `comparison` (heading + points) and `concept_definition` (definition + bullets) — see §3.

---

## 3. The actual diffs (three layout files)

> `git diff HEAD -- src/layouts/comparison.ts src/layouts/concept-definition.ts src/layouts/typographic-keywords.ts`
> (The `git` warning "LF will be replaced by CRLF" on the rewritten typographic file is a Windows autocrlf note — the commit normalizes to LF; non-gating.)

```diff
diff --git a/packages/presentation-worker/src/layouts/comparison.ts b/packages/presentation-worker/src/layouts/comparison.ts
@@ docstring @@
- * Both columns share a top edge that floors below the title's measured bottom,
- * and within each column the bullet points stack below the heading's real
- * bottom and below each other (stackBelow + hugHeightToMeasured) rather than
- * dropping into fixed equal-height slots — so a long heading or a point that
- * wraps to two lines pushes the next point down instead of clipping.
+ * Both columns share a top edge hugged below the title's measured bottom, and
+ * within each column the heading + points are placed by the shared fit engine
+ * (fitMeasuredStack, anchor:'start') — each block hugs its own measured height,
+ * so a long heading or a point that wraps to two lines pushes the next one down
+ * instead of dropping into a fixed equal-height slot.
@@ imports @@
   stripListPrefix,
 } from './shared.js';
+import { fitMeasuredStack } from './fit.js';
@@ layoutComparison: column top @@
-  // Both columns start at the same top edge: their designed y, floored below a
-  // tall title's measured bottom so the title can't overlap the columns.
-  const columnTop = Math.max(regions.body!.y, stackBelow(titleBlock, COLUMN_GAP));
+  // Both columns start at the same top edge, hugged below the title's REAL
+  // measured bottom (no fixed floor): dropping the old Math.max(regions.body.y, …)
+  // removes the dead gap that stranded the columns at the designed body.y (15)
+  // even under a short title.
+  const columnTop = stackBelow(titleBlock, COLUMN_GAP);
@@ layoutComparisonColumn (full rewrite) @@
-  const columnBottom = region.y + region.h;
-
-  const headingBlock = hugHeightToMeasured(
-    buildTextBlock({
-      text: column.heading,
-      region: { x: region.x, y: region.y, w: region.w, h: region.h },
-      fontFamily: design.heading_font,
-      fontWeight: 'bold',
-      color: column.is_preferred ? design.palette.accent : design.palette.text,
-      align: 'left',
-      tier: FONT_SIZES.subheading,
-      lineHeight: LINE_HEIGHTS.heading,
-    }),
-  );
-  blocks.push(headingBlock);
-
-  const points = column.points ?? [];
-  if (points.length === 0) return;
-
-  let cursorY = stackBelow(headingBlock, HEADING_GAP);
-  points.forEach((point) => {
-    const pointBlock = hugHeightToMeasured(
-      buildTextBlock({
-        text: `• ${stripListPrefix(point)}`,
-        region: {
-          x: region.x,
-          y: cursorY,
-          w: region.w,
-          h: Math.max(0, columnBottom - cursorY),
-        },
-        fontFamily: design.body_font,
-        fontWeight: 'normal',
-        color: design.palette.text,
-        align: 'left',
-        tier: FONT_SIZES.body,
-        lineHeight: LINE_HEIGHTS.body,
-      }),
-    );
-    blocks.push(pointBlock);
-    cursorY = stackBelow(pointBlock, POINT_GAP);
-  });
+  // Build tall against the full column (so a long heading/point shrinks-to-fit
+  // there), then let the shared fit engine place the stack. The heading-color
+  // branch below is the column-emphasis contract — keep it byte-identical.
+  const headingBlock = buildTextBlock({
+    text: column.heading,
+    region,
+    fontFamily: design.heading_font,
+    fontWeight: 'bold',
+    color: column.is_preferred ? design.palette.accent : design.palette.text,
+    align: 'left',
+    tier: FONT_SIZES.subheading,
+    lineHeight: LINE_HEIGHTS.heading,
+  });
+
+  const pointBlocks = (column.points ?? []).map((point) =>
+    buildTextBlock({
+      text: `• ${stripListPrefix(point)}`,
+      region,
+      fontFamily: design.body_font,
+      fontWeight: 'normal',
+      color: design.palette.text,
+      align: 'left',
+      tier: FONT_SIZES.body,
+      lineHeight: LINE_HEIGHTS.body,
+    }),
+  );
+
+  // anchor:'start' ⇒ tops[0] === region.y (= columnTop); each block then hugs its
+  // own measured height (valign stays 'top' — do NOT emitBandCell). overflow:
+  // 'truncate' makes per-block shrink+truncate the only reliability floor.
+  const stack = [headingBlock, ...pointBlocks];
+  const fit = fitMeasuredStack({
+    region,
+    items: [
+      { measure: () => headingBlock.measuredHeightPct, gapAfter: HEADING_GAP },
+      ...pointBlocks.map((p) => ({ measure: () => p.measuredHeightPct, gapAfter: POINT_GAP })),
+    ],
+    overflow: 'truncate',
+    anchor: 'start',
+  });
+
+  stack.forEach((block, i) => {
+    block.y = fit.tops[i]!;
+    hugHeightToMeasured(block);
+    blocks.push(block);
+  });


diff --git a/packages/presentation-worker/src/layouts/concept-definition.ts b/packages/presentation-worker/src/layouts/concept-definition.ts
@@ imports @@
   stripListPrefix,
 } from './shared.js';
+import { fitMeasuredStack } from './fit.js';
@@ body stacking (definition + bullets) — title untouched above @@
-  let cursorY = stackBelow(titleBlock, TITLE_GAP);
+  // The definition + bullets stack below the title's measured bottom. Each block
+  // is built tall against the column (measure-tall), then placed by the shared
+  // fit engine (anchor:'start' ⇒ tops follow the old stackBelow chain exactly);
+  // each then hugs its own measured height so a wrapped block pushes the next one
+  // down instead of clipping. The TITLE stays outside the engine — it is the
+  // region anchor, and keeping it standalone leaves its geometry byte-identical.
+  const stackTop = stackBelow(titleBlock, TITLE_GAP);
+  const stackRegion = { x: LEFT_X, y: stackTop, w: COLUMN_W, h: availableHeightBelow(stackTop) };
+
+  const entries: Array<{ block: TextBlock; gapAfter: number }> = [];

   const definition = pickDefinition(slide.content.subtitle, slide.content.body_text);
   if (definition) {
-    const definitionBlock = hugHeightToMeasured(
-      buildTextBlock({
+    entries.push({
+      block: buildTextBlock({
         text: definition,
-        region: { x: LEFT_X, y: cursorY, w: COLUMN_W, h: availableHeightBelow(cursorY) },
+        region: stackRegion,
         fontFamily: design.body_font,
         fontWeight: 'normal',
         fontStyle: 'italic',
         /* color: design.palette.text, tier: subheading, lineHeight: body */
       }),
-    );
-    blocks.push(definitionBlock);
-    cursorY = stackBelow(definitionBlock, DEFINITION_GAP);
+      gapAfter: DEFINITION_GAP,
+    });
   }

   const bullets = (slide.content.bullets ?? []).slice(0, MAX_BULLETS);
-  bullets.forEach((bullet) => {
-    const bulletBlock = hugHeightToMeasured(
-      buildTextBlock({
+  for (const bullet of bullets) {
+    entries.push({
+      block: buildTextBlock({
         text: `• ${stripListPrefix(bullet)}`,
-        region: { x: LEFT_X, y: cursorY, w: COLUMN_W, h: availableHeightBelow(cursorY) },
+        region: stackRegion,
         /* body font, normal, text, caption tier, body lineHeight */
       }),
-    );
-    blocks.push(bulletBlock);
-    cursorY = stackBelow(bulletBlock, BULLET_GAP);
+      gapAfter: BULLET_GAP,
+    });
+  }
+
+  const fit = fitMeasuredStack({
+    region: stackRegion,
+    items: entries.map((e) => ({ measure: () => e.block.measuredHeightPct, gapAfter: e.gapAfter })),
+    overflow: 'truncate',
+    anchor: 'start',
+  });
+  entries.forEach((e, i) => {
+    e.block.y = fit.tops[i]!;
+    hugHeightToMeasured(e.block);
+    blocks.push(e.block);
   });


diff --git a/packages/presentation-worker/src/layouts/typographic-keywords.ts b/packages/presentation-worker/src/layouts/typographic-keywords.ts
@@ imports @@
-import { FONT_SIZES, LINE_HEIGHTS, SLIDE_REGIONS, getKeywordPositions } from '../constants.js';
+import { FONT_SIZES, LINE_HEIGHTS, SLIDE_REGIONS } from '../constants.js';
 import type { DeckSpec, SlideLayout, SlideSpec, TextBlock } from '../types.js';
-import { buildScrim, buildTextBlock, compose, defaultBackground } from './shared.js';
+import {
+  availableHeightBelow,
+  buildScrim,
+  buildTextBlock,
+  compose,
+  defaultBackground,
+  hugHeightToMeasured,
+  stackBelow,
+} from './shared.js';
+import { fitMeasuredStack } from './fit.js';
 import { layoutContentSplit } from './content-split.js';
+
+// Horizontal pairing (slide %): the term sits left, its explanation to the right.
+// These survive from the deleted getKeywordPositions; only the vertical math (the
+// old even-distribution band) is gone — rows now derive from measured content.
+const TERM_X = 5;
+const TERM_W = 35;
+const EXPLAIN_X = 42;
+const EXPLAIN_W = 50;
+const TITLE_ROWS_GAP = 2; // below the title before the first keyword row
+const ROW_GAP = 3; // between keyword rows (distinct, heading-weight items)
+const MAX_KEYWORDS = 6;
@@ keyword count slice @@
-  const keywords = (slide.content.keywords ?? []).slice(0, 6);
+  const keywords = (slide.content.keywords ?? []).slice(0, MAX_KEYWORDS);
@@ title now hugged; rows derived + fit-placed (full rewrite) @@
-  blocks.push(
+  // Hug the title so the keyword rows derive from its REAL measured bottom — this
+  // removes the old fixed startY=18 dead gap. regions.title.h caps the build.
+  const titleBlock = hugHeightToMeasured(
     buildTextBlock({
       text: slide.content.title,
       region: regions.title!,
       /* heading font, bold, text, center, heading tier */
     }),
   );
+  blocks.push(titleBlock);

-  const positions = getKeywordPositions(keywords.length);
-  keywords.forEach((kw, idx) => {
-    const pos = positions[idx];
-    if (!pos) return;
-    blocks.push(buildTextBlock({ text: kw.term, region: pos.term, /* accent, bold, heading */ }));
-    blocks.push(buildTextBlock({ text: kw.explanation, region: pos.explain, /* text_secondary, body */ }));
-  });
+  const contentTop = stackBelow(titleBlock, TITLE_ROWS_GAP);
+  const contentH = availableHeightBelow(contentTop);
+
+  // Build each row's term + explanation tall against the band. rowHeight = the
+  // taller of the two, used ONLY to space the next row; the cells themselves hug
+  // their own height (top-aligned — do NOT emitBandCell). The accent colour + bold
+  // on the term and text_secondary on the explanation are the emphasis contract:
+  // keep them byte-identical.
+  const rows = keywords.map((kw) => {
+    const term = buildTextBlock({
+      text: kw.term,
+      region: { x: TERM_X, y: contentTop, w: TERM_W, h: contentH },
+      fontFamily: design.heading_font,
+      fontWeight: 'bold',
+      color: design.palette.accent,
+      align: 'left',
+      tier: FONT_SIZES.heading,
+      lineHeight: LINE_HEIGHTS.heading,
+    });
+    const explain = buildTextBlock({
+      text: kw.explanation,
+      region: { x: EXPLAIN_X, y: contentTop, w: EXPLAIN_W, h: contentH },
+      fontFamily: design.body_font,
+      fontWeight: 'normal',
+      color: design.palette.text_secondary,
+      align: 'left',
+      tier: FONT_SIZES.body,
+      lineHeight: LINE_HEIGHTS.body,
+    });
+    return {
+      term,
+      explain,
+      rowHeight: Math.max(term.measuredHeightPct, explain.measuredHeightPct),
+    };
+  });
+
+  const fit = fitMeasuredStack({
+    region: { x: TERM_X, y: contentTop, w: 90, h: contentH },
+    items: rows.map((r) => ({ measure: () => r.rowHeight, gapAfter: ROW_GAP })),
+    overflow: 'truncate',
+    anchor: 'start',
+  });
+
+  rows.forEach((r, i) => {
+    r.term.y = fit.tops[i]!;
+    r.explain.y = fit.tops[i]!;
+    hugHeightToMeasured(r.term);
+    hugHeightToMeasured(r.explain);
+    blocks.push(r.term, r.explain);
+  });
```

`src/constants.ts`: deleted the dead `getKeywordPositions` (single caller, now gone) and demoted `comparison.body/image` y/h to documented max-bound comments (values kept; `Region` type still requires the fields). `typographic_keywords.title` annotated as a build-cap max-bound.

---

## 4. Tests

- **`__tests__/layout-typographic-keywords.test.ts`** — kept the two pre-existing tests (per-keyword term+explanation emitted, terms accent; terms bold+accent). **Replaced** "spaces keywords tighter when there are more of them" (the deleted `gap6 < gap3` even-distribution assertion) with: (a) rows hug the title — `terms[0].y ≈ title.y + title.measuredHeightPct + TITLE_ROWS_GAP` AND `terms[0].y < 18` (old fixed floor gone); (b) uniform pitch within a deck; (c) `pitch(6) ≈ pitch(3)` — the deliberate inverse of the old behavior; (d) paired row tops `explanations[i].y ≈ terms[i].y`; (e) `valign` top/undefined (locks no-`emitBandCell`); (f) everything on slide for both 3- and 6-keyword decks.
- **`__tests__/layout-comparison.test.ts`** (new) — (1) short title → left heading hugs title + `COLUMN_GAP`, and `< 15` (old floor gone); (2) points stack by measured height, uniform pitch, no overlap; (3) both columns share top edge; (4) x routing preserved (left=5, right=52); (5) heading hugged; (6) divider spans full column from `columnTop` to bottom margin; (7) `is_preferred → accent`, other → text; (8) zero-points column emits heading only, no throw.
- Tripwires unchanged and green: `layout-concept-definition.test.ts` (9), `layout-pass.test.ts` comparison `is_preferred` + concept figure (24).

---

## 5. Codex independent review (read-only, xhigh) — verbatim

**Run:** Codex CLI `0.140.0`, model `gpt-5.5`, `-s read-only`, `model_reasoning_effort=xhigh`, `approval: never`.

**Operational caveat (honest):** Codex's sandboxed command runner could not spawn `git` on this Windows machine (it failed with `exit 0xC0000142` / `STATUS_DLL_INIT_FAILED`), and an earlier attempt hung on an open stdin. So Codex did **not** read the repo live — it reviewed the **complete `git diff HEAD` fed inline** via a stdin file, with an explicit instruction not to run commands. The diff is the exact artifact under review, so the analysis is genuinely independent (a different model, GPT-5.5, reading the real change); it just didn't fetch the bytes itself. (Codex's cited line numbers are counted off the diff hunks, so they're ±1–2 vs the working-tree files — e.g. it says `comparison.ts:104` where the working tree has `:103`.)

**Verdict — verbatim:**

> (1) **PASS.** The rewritten test has a genuine discriminator for no fixed startY: `OLD_FIXED_START_Y = 18` is defined in `layout-typographic-keywords.test.ts:15`, and `expect(terms3[0]!.y).toBeLessThan(OLD_FIXED_START_Y);` is at `layout-typographic-keywords.test.ts:98`. Old code fixed the first keyword row at `startY = 18` in `constants.ts:297`, so this would fail against OLD.
>
> It also genuinely asserts cross-count uniform pitch: `pitch3a` is computed from 3-keyword rows at `layout-typographic-keywords.test.ts:102`, `pitch6` from 6-keyword rows at `layout-typographic-keywords.test.ts:110`, and `expect(pitch6).toBeCloseTo(pitch3a, 5);` is at `layout-typographic-keywords.test.ts:111`. OLD computed `stepY = 70 / count` at `constants.ts:298-299`, so 6 rows had about half the pitch of 3 rows; this assertion would fail. The tolerance `5` is tight, not over-wide. The first test block is unchanged in the diff, so the pre-existing term accent/bold assertions remain present by differential evidence at `layout-typographic-keywords.test.ts:18-56`.
>
> (2) **PASS.** The three emphasis branches are unchanged:
> - Comparison heading color remains `column.is_preferred ? design.palette.accent : design.palette.text` on both old and new sides in `layouts/comparison.ts:104`.
> - Typographic keyword term emphasis remains `fontWeight: 'bold'` and `color: design.palette.accent` on both old and new sides in `layouts/typographic-keywords.ts:83-84`.
> - Typographic keyword explanation color remains `color: design.palette.text_secondary` on both old and new sides in `layouts/typographic-keywords.ts:95`.
>
> VERDICT: (1) PASS ; (2) PASS

**Tokens used:** 22,913.
