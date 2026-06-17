/**
 * Measurement-driven fit engine — the shared geometry primitive.
 *
 * Generalizes the stack-fit loop shipped inline in `table-compact.ts` (the row
 * bands hug measured content + padding, the bands are summed, and the *stack* is
 * what must fit the region — fits → place it; overflows → scale every band by one
 * content-derived factor). This file is PURE ARITHMETIC: it consumes measured
 * heights and returns band tops/heights/scale. It never builds, measures, or
 * mutates a `TextBlock` during the fit — the caller owns the two-pass build
 * (measure tall → place against the result). That purity is exactly why the
 * table re-point stays pixel-identical: the engine IS the block-free slice of the
 * table's loop with renamed symbols.
 *
 * `shared.ts` does everything block-shaped (buildTextBlock / availableHeightBelow
 * / stackBelow / hugHeightToMeasured); this file does only vertical geometry, so
 * it imports nothing from `shared.ts` — only the `Region` / `TextBlock` types.
 */

import type { Region } from '../constants.js';
import type { TextBlock } from '../types.js';

export interface FitItem {
  /**
   * This item's measured CONTENT height (slide %). The CALLER applies any content
   * floor (e.g. the table's `oneLinePct`) INSIDE this closure before returning;
   * the engine never floors content — it only adds band `padding` and applies
   * `scale`. The closure must NOT pre-add padding or pre-apply scale.
   */
  measure: () => number;
  /**
   * Minimum gap (slide %) reserved AFTER this item, before the next. The trailing
   * item's `gapAfter` is dropped (no gap past the last band). Omitted ⇒ 0 — which
   * lets one formula serve the table (no gaps; its breathing lives in band
   * `padding`) and the flow layout (real gaps) without a branch. Under
   * `overflow:'scale'` it scales with the bands; under `anchor:'distribute'` it is
   * the FLOOR — even-spread slack is added on top.
   */
  gapAfter?: number;
}

export type FitOverflow = 'scale' | 'truncate';
export type FitAnchor = 'start' | 'center' | 'distribute';

export interface FitInput {
  /**
   * The authoritative box. `region.h` is the height the stack must fit; a migrated
   * caller DERIVES `region.y`/`region.h` (title bottom + gap → availableHeightBelow,
   * the frozen SLIDE_REGIONS body height demoted to a max bound) and hands the
   * resolved box in. Horizontal `x`/`w` come from the caller unchanged. (The table
   * opts out of derivation and passes its frozen body verbatim — that is what keeps
   * it pixel-identical.)
   */
  region: Region;
  items: FitItem[];
  /**
   * Symmetric band breathing (slide %): each band = `measure() + 2*padding`,
   * matching the table's `content + 2*CELL_PAD_Y`. Per-EDGE (the engine doubles
   * it). Kept as a named param rather than folded into `measure()` so a content
   * floor stays on CONTENT, never on content+padding. Default 0.
   */
  padding?: number;
  /**
   * 'scale'    : on overflow, multiply every band AND gap by `region.h/rawTotal`
   *              (the content-derived factor — never a clamped row height). Use
   *              ONLY when the caller REBUILDS each cell against the scaled band
   *              (`emitBandCell`), so the per-cell `buildTextBlock` shrink/truncate
   *              fires against the real band — the table is the only such caller.
   * 'truncate' : scale stays 1; bands keep their natural padded height. Use when
   *              the caller keeps each block's OWN measured height and only reads
   *              `tops[]` (flow, chart multi-stat, content-split). If 'scale' fired
   *              for these, `tops[]` would compress while the blocks stayed full
   *              height ⇒ OVERLAP. Per-block `buildTextBlock` shrink + `minFontSize`
   *              is the only floor here.
   */
  overflow: FitOverflow;
  /**
   * 'start'      : top-pinned, flowing from `region.y`; leftover slack stays unused
   *                at the bottom (the stack hugs upward).
   * 'center'     : fit, then centre the stack — the table's "balanced, not
   *                top-pinned" policy. Reproduces `region.y + max(0,(region.h −
   *                content)/2)` exactly.
   * 'distribute' : space-between — first band at the region top, last flush to the
   *                bottom, leftover slack split evenly into the n−1 interior gaps ON
   *                TOP of each `gapAfter` floor.
   */
  anchor: FitAnchor;
}

export interface FitResult {
  /** Top y (slide %) of each band, index-aligned to `items`. */
  tops: number[];
  /** Band height (slide %) of each item = `(measure()+2*padding) * scale`. */
  heights: number[];
  /** The single shared scale applied (1 unless `overflow:'scale'` fired). */
  scale: number;
}

/**
 * Fit a measured vertical stack into `region` and return each band's top/height.
 * Mirrors `table-compact.ts`'s inline loop exactly; `scale` is computed ONCE and
 * is anchor-independent, so the centre case is the table's current math line for
 * line and `distribute` falls out as "start + spread the slack".
 */
export function fitMeasuredStack(input: FitInput): FitResult {
  const { region, items, overflow, anchor } = input;
  const padding = input.padding ?? 0;
  const n = items.length;
  if (n === 0) return { tops: [], heights: [], scale: 1 };

  // Bands = content + 2*padding (table L127-128). Gaps are interior only — the
  // trailing item's gapAfter is dropped.
  const bands = items.map((it) => it.measure() + 2 * padding);
  const gaps = items.map((it, i) => (i < n - 1 ? (it.gapAfter ?? 0) : 0));
  const rawTotal = bands.reduce((s, b) => s + b, 0) + gaps.reduce((s, g) => s + g, 0);

  // Strict '>' (table L130): at exact equality the stack does NOT scale.
  const scale = overflow === 'scale' && rawTotal > region.h ? region.h / rawTotal : 1;

  const heights = bands.map((b) => b * scale);
  const scaledGaps = gaps.map((g) => g * scale);
  const content =
    heights.reduce((s, h) => s + h, 0) + scaledGaps.reduce((s, g) => s + g, 0);

  const slack = region.h - content;
  // 'distribute' spreads positive slack evenly into the n−1 interior gaps; for
  // n===1 (or slack<=0) it degenerates to a top-pinned start at the floor gaps.
  const extra = anchor === 'distribute' && n > 1 && slack > 0 ? slack / (n - 1) : 0;
  const top0 = anchor === 'center' ? region.y + Math.max(0, slack / 2) : region.y;

  const tops = new Array<number>(n);
  let cursor = top0;
  for (let i = 0; i < n; i++) {
    tops[i] = cursor;
    cursor += heights[i]! + scaledGaps[i]! + (i < n - 1 ? extra : 0);
  }
  return { tops, heights, scale };
}

/**
 * Stamp a pre-built block into its band: pin `y`/`h`, centre the text vertically.
 * Generalizes the table's `buildCell` tail.
 *
 * CONTRACT (load-bearing for faithfulness): the caller MUST have built `block`
 * via `buildTextBlock` with `region.y === bandTop` and `region.h === bandHeight`
 * (the SCALED `FitResult.heights[i]`), so the shrink/truncate already fired
 * against the real band. Because `buildTextBlock` copies `y`/`h` FROM the region,
 * the re-assignment here is IDEMPOTENT; `valign:'middle'` is the only observable
 * change — byte-identical to today's `block.valign = 'middle'`. This must NOT be
 * the first place `bandHeight` meets the block, or the shrink ran at the wrong
 * height and the scaled (scale<1) case drifts.
 *
 * VERTICAL-ONLY: `x`/`w` and horizontal padding stay caller-side. Both renderers
 * already honour `valign:'middle'` from this one source, so no renderer change is
 * needed. Used only by `table_compact` — the one migrated layout that rebuilds its
 * cells against the scaled band.
 */
export function emitBandCell(block: TextBlock, bandTop: number, bandHeight: number): TextBlock {
  block.y = bandTop;
  block.h = bandHeight;
  block.valign = 'middle';
  return block;
}
