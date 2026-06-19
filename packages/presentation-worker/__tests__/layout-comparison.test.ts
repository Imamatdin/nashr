/**
 * COMPARISON layout — shared fit-engine migration.
 *
 * comparison had no dedicated test file (the only prior coverage was the
 * is_preferred / x-routing case in layout-pass.test.ts, which stays green
 * independently). This file locks the NEW fill behaviour after the L2
 * fit-engine migration:
 *
 *  1. The DEAD-GAP FIX. Both columns now start at the title's REAL measured
 *     bottom — columnTop = title.y + title.measuredHeightPct + COLUMN_GAP —
 *     instead of being floored at the frozen body region y (15) via the old
 *     Math.max(regions.body.y, …). A short title therefore pulls the columns
 *     up above 15 and they hug their content.
 *
 *  2. The PER-COLUMN STACK. Inside each column the heading is placed at
 *     columnTop, then points stack by MEASURED height through the shared fit
 *     engine (anchor:'start'): HEADING_GAP after the heading, POINT_GAP between
 *     points, each block hugging its own measured height (so a wrapped point
 *     pushes the next down rather than dropping into a fixed slot).
 *
 *  3. The INVARIANTS that survive the migration: x routing (left=5, right=52,
 *     the engine ignores region.x/w so x is the column tag), the accent-colour
 *     divider spanning the full column, and the is_preferred heading emphasis.
 *
 * Geometry note (see layout-content-split.test.ts header): measureText uses
 * character-width estimation on this machine (no fontconfig), so ABSOLUTE pixel
 * values are not reliable. Every assertion here is a RELATIONSHIP off measured
 * values (hugs title bottom, uniform pitch, no overlap, shared top edge, x
 * routing, hug height, divider span, colour) via toBeCloseTo — never a hardcoded
 * y. The one exception, case (1)'s `heading.y < 15`, is the floor-removed proof:
 * it rides on the short title measuring under the old 15 floor, which a one-word
 * title does comfortably.
 */

import { describe, expect, it } from 'vitest';
import { LayoutPass } from '../src/layout-pass.js';
import { buildTestDeck, makeSlide } from './helpers.js';
import type { SlideContent } from '../src/types.js';

// Mirrors the constants comparison.ts uses.
const COLUMN_GAP = 2; // below the title before the columns
const HEADING_GAP = 2; // below a column heading before its first point
const POINT_GAP = 1.5; // between consecutive points in a column
const OLD_BODY_FLOOR_Y = 15; // SLIDE_REGIONS.comparison.body.y — the removed floor
const BOTTOM_MARGIN = 6; // MARGIN.bottom: availableHeightBelow(y) === 100 - 6 - y
const LEFT_X = 5; // SLIDE_REGIONS.comparison.body.x
const RIGHT_X = 52; // SLIDE_REGIONS.comparison.image.x

function runComparison(content: SlideContent) {
  const deck = buildTestDeck([makeSlide('comparison', content)]);
  const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
  return { deck, layout };
}

// Distinct left/right strings so .find()/.includes() never grabs the wrong
// column (both columns build their blocks from the same per-column region, so x
// is the only routing tag). Points get a "• " prefix in the layout, hence
// .includes() rather than exact match.
function shortContent(rightPreferred = false): SlideContent {
  return {
    title: 'Strands',
    left_column: { heading: 'Radical', points: ['Materialist', 'Democratic'] },
    right_column: {
      heading: 'Moderate',
      points: ['Deist', 'Constitutional'],
      is_preferred: rightPreferred,
    },
  } as SlideContent;
}

describe('layout — COMPARISON fill (shared fit engine)', () => {
  it('(1) short title: left heading hugs the title bottom + COLUMN_GAP, above the removed floor', () => {
    const { layout } = runComparison(shortContent());
    const title = layout.textBlocks.find((b) => b.text === 'Strands')!;
    const heading = layout.textBlocks.find((b) => b.text === 'Radical')!;
    expect(title).toBeDefined();
    expect(heading).toBeDefined();

    // columnTop = title.y + title.measuredHeightPct + COLUMN_GAP. The heading
    // sits at columnTop (anchor:'start' ⇒ tops[0] === region.y === columnTop).
    expect(heading.y).toBeCloseTo(title.y + title.measuredHeightPct + COLUMN_GAP, 5);

    // The floor-removed proof: with the old Math.max(regions.body.y=15, …) gone,
    // a short title pulls the columns ABOVE 15 instead of stranding them there.
    expect(heading.y).toBeLessThan(OLD_BODY_FLOOR_Y);
  });

  it('(2) points stack by measured height: uniform pitch, no overlap', () => {
    const { layout } = runComparison(shortContent());
    const heading = layout.textBlocks.find((b) => b.text === 'Radical')!;
    const point0 = layout.textBlocks.find((b) => b.text.includes('Materialist'))!;
    const point1 = layout.textBlocks.find((b) => b.text.includes('Democratic'))!;
    expect(point0).toBeDefined();
    expect(point1).toBeDefined();

    // point0 sits HEADING_GAP below the heading's measured bottom.
    expect(point0.y).toBeCloseTo(heading.y + heading.measuredHeightPct + HEADING_GAP, 5);
    // point1 sits POINT_GAP below point0's measured bottom.
    expect(point1.y).toBeCloseTo(point0.y + point0.measuredHeightPct + POINT_GAP, 5);

    // No overlap: each next top clears the previous block's measured bottom.
    expect(point0.y).toBeGreaterThanOrEqual(heading.y + heading.measuredHeightPct);
    expect(point1.y).toBeGreaterThanOrEqual(point0.y + point0.measuredHeightPct);
  });

  it('(3) both columns share the top edge', () => {
    const { layout } = runComparison(shortContent());
    const left = layout.textBlocks.find((b) => b.text === 'Radical')!;
    const right = layout.textBlocks.find((b) => b.text === 'Moderate')!;
    expect(left).toBeDefined();
    expect(right).toBeDefined();
    // Both columns derive their top from the same columnTop, so the two headings
    // start at the same y regardless of column.
    expect(left.y).toBeCloseTo(right.y, 5);
  });

  it('(4) x routing preserved: left blocks at x=5, right blocks at x=52', () => {
    const { layout } = runComparison(shortContent());
    const leftHeading = layout.textBlocks.find((b) => b.text === 'Radical')!;
    const leftPoint = layout.textBlocks.find((b) => b.text.includes('Materialist'))!;
    const rightHeading = layout.textBlocks.find((b) => b.text === 'Moderate')!;
    const rightPoint = layout.textBlocks.find((b) => b.text.includes('Deist'))!;

    // The fit engine uses only region.y/h for vertical math; region.x/w are
    // ignored, so the per-column x from buildTextBlock survives untouched.
    expect(leftHeading.x).toBe(LEFT_X);
    expect(leftPoint.x).toBe(LEFT_X);
    expect(rightHeading.x).toBe(RIGHT_X);
    expect(rightPoint.x).toBe(RIGHT_X);
  });

  it('(5) heading is hugged: h covers measured content and is small, not the full column', () => {
    const { layout } = runComparison(shortContent());
    const heading = layout.textBlocks.find((b) => b.text === 'Radical')!;

    // hugHeightToMeasured shrank the box to its content (+HUG_EPSILON_PCT 0.2):
    // the box covers the measured content but stays a few percent tall, NOT the
    // ~79%-tall full column it was built against.
    expect(heading.h).toBeGreaterThanOrEqual(heading.measuredHeightPct);
    expect(heading.h).toBeCloseTo(heading.measuredHeightPct + 0.2, 5);
    expect(heading.h).toBeLessThan(12);
  });

  it('(6) divider spans the full column from columnTop down to the bottom margin', () => {
    const { layout } = runComparison(shortContent());
    const heading = layout.textBlocks.find((b) => b.text === 'Radical')!;

    // columnTop === a heading's y (anchor:'start'); columnHeight ===
    // availableHeightBelow(columnTop) === 100 - MARGIN.bottom - columnTop.
    const columnTop = heading.y;
    const expectedHeight = 100 - BOTTOM_MARGIN - columnTop;

    const divider = layout.shapes.find((s) => s.type === 'rect')!;
    expect(divider).toBeDefined();
    expect(layout.shapes).toHaveLength(1);

    expect(divider.x).toBeCloseTo(49.9, 5);
    expect(divider.w).toBeCloseTo(0.1, 5);
    expect(divider.y).toBeCloseTo(columnTop, 5);
    expect(divider.h).toBeCloseTo(expectedHeight, 5);
  });

  it('(7) emphasis at the fill level: is_preferred column heading is accent, the other is text', () => {
    const { deck, layout } = runComparison(shortContent(/* rightPreferred */ true));
    const leftHeading = layout.textBlocks.find((b) => b.text === 'Radical')!;
    const rightHeading = layout.textBlocks.find((b) => b.text === 'Moderate')!;

    expect(rightHeading.color).toBe(deck.design.palette.accent);
    expect(leftHeading.color).toBe(deck.design.palette.text);
  });

  it('(8) zero-points column emits its heading only (no throw, no point blocks)', () => {
    let layout!: ReturnType<LayoutPass['layoutSlide']>;
    expect(() => {
      ({ layout } = runComparison({
        title: 'Strands',
        left_column: { heading: 'Empty', points: [] },
        right_column: { heading: 'Filled', points: ['Sole point'] },
      } as SlideContent));
    }).not.toThrow();

    // The empty (left) column contributes exactly one block — its heading. x is
    // the routing tag the engine leaves intact, so left-column blocks are those
    // at x=5; the title also lives at x=5 (its region is x:5) so exclude it by
    // text. The point being: NO point blocks were emitted for the empty column.
    const leftColumnBlocks = layout.textBlocks.filter(
      (b) => b.x === LEFT_X && b.text !== 'Strands',
    );
    expect(leftColumnBlocks).toHaveLength(1);
    expect(leftColumnBlocks[0]!.text).toBe('Empty');

    // The right column with one point still renders its heading + that point.
    const rightHeading = layout.textBlocks.find((b) => b.text === 'Filled');
    const rightPoint = layout.textBlocks.find((b) => b.text.includes('Sole point'));
    expect(rightHeading).toBeDefined();
    expect(rightPoint).toBeDefined();
  });
});
