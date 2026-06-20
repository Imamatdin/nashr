/**
 * DATA_EMPHASIS layout.
 *
 * Highlights 1-4 key statistics. Each stat is decomposed into a
 * number block (largest), an optional unit block, a label block,
 * and an optional comparison line. The number is the headline content
 * and reads big — sized adaptively against the band's REMAINING height
 * after the unit/label/comparison stack is measured, so on a tall
 * band with short labels the number grows toward the ceiling; on a
 * narrow 4-stat band or with verbose labels the number compresses
 * gracefully. The displayLarge/displayJumbo tiers are floors here, not
 * ceilings: keeping a 64px cap on a 800px-tall band is the under-fill
 * bug this exists to kill.
 *
 * Within each row of stats the number blocks share a COMMON BASELINE
 * (their measured bottoms align) and render at a UNIFORM FONT SIZE
 * (the smallest size at which every value in the row still fits its
 * column). Pure baseline alignment with mismatched font sizes still
 * reads as staggered, so this layout pays one extra build pass per
 * stat to harmonise the row. Do NOT collapse this back to per-column
 * independence — that re-introduces the staggered headline bug.
 *
 * The four blocks of a stat are measured and stacked vertically
 * (number → unit → label → comparison) — a number that wraps to two
 * lines pushes the unit/label/comparison down instead of stranding
 * them in a pre-cut slot. The stack hangs FROM the shared baseline:
 * unit/label/comparison cascade below it, the number rises to align
 * its bottom there. A stack that overflows the band top-aligns
 * (never-stack-upward floor) and the audit surfaces it. The number
 * block carries the value ONLY — the unit has exactly one home, its
 * own block — so a value+unit pair never renders jammed together
 * ("1.58PUE") or doubled.
 */

import {
  FONT_SIZES,
  LINE_HEIGHTS,
  MARGIN,
  SLIDE_HEIGHT,
  SLIDE_WIDTH,
  SLIDE_REGIONS,
  STAT_POSITIONS,
  type Region,
} from '../constants.js';
import { measureText } from '../text-measure.js';
import type {
  DeckSpec,
  DesignDirectionSpec,
  SlideLayout,
  SlideSpec,
  StatItem,
  TextBlock,
} from '../types.js';
import {
  availableHeightBelow,
  buildTextBlock,
  compose,
  defaultBackground,
  hugHeightToMeasured,
  stackBelow,
  type FontTier,
} from './shared.js';
import { fitMeasuredStack } from './fit.js';

/** Vertical gap (slide %) between a stat's number/unit/label/comparison blocks. */
const STAT_BLOCK_GAP = 1;

/** Vertical gap (slide %) below the title's measured bottom before the stat region.
 *  Sibling-consistent with comparison.COLUMN_GAP / typographic.TITLE_ROWS_GAP (=2).
 *  Exported for the layout test, which re-derives the content region from it. */
export const TITLE_GAP = 2;

/** Vertical gap (slide %) between the two rows of the 4-stat 2×2 grid. Matches the
 *  original frozen STAT_POSITIONS[4] gap (row-0 bottom 53 → row-1 top 55 = 2).
 *  Exported for the layout test. */
export const ROW_GAP = 2;

/** Bottom content margin (slide %), mirrored from R16. Exported for layout tests. */
export const REGION_BOTTOM = 100 - MARGIN.bottom;

/** Minimum vertical space (slide %) reserved for the stat grid below the title.
 *  Title-hug caps here so a pathological multi-line headline cannot consume the
 *  stat band (Codex P2). A normal 1-line title derives contentTop ≈ 15–17 via
 *  stackBelow, well above REGION_BOTTOM − MIN (44), so sCO₂ one-line stat slides
 *  are byte-identical. */
export const MIN_STAT_REGION_H = 50;

/** Probe floor for uniform number sizing — never let a pathological long
 *  value drag the row's font size below the displayLarge minimum. The existing
 *  test `keeps multi-stat number blocks in the large display tier` is the
 *  tripwire on this floor: if it fails, this floor is the lever. */
const NUMBER_PROBE_FLOOR_PX = FONT_SIZES.displayLarge.min;

/** Adaptive ceiling for the headline number, in px. Big enough to read
 *  like a Canva stat headline on a full-height band, capped so a single
 *  hero stat doesn't grow absurdly. */
const NUMBER_CEILING_PX = 240;

/** Fraction of the *number-available* height (band minus below-stack) the
 *  number should occupy. 80% leaves a small breather between the wrapped
 *  number's bottom and the unit row above the baseline; lifting this above
 *  ~85% lets the number kiss the unit, below ~70% strands the number high
 *  on a tall band. */
const NUMBER_FILL_FRACTION = 0.8;

/** Render-cost multiplier mirrored from text-measure.HEIGHT_SAFETY (1.3)
 *  × LINE_HEIGHTS.heading (1.1). The Layout Pass knows the renderer
 *  inflates line height, so it sizes against the same factor. */
const RENDER_LINE_FACTOR = LINE_HEIGHTS.heading * 1.3;

interface StatStack {
  number: TextBlock;
  below: TextBlock[];
}

/** Group positions into rows that share a y/h band — 4-stat splits into 2 rows. */
function groupRows(positions: readonly Region[]): readonly (readonly number[])[] {
  const rows = new Map<string, number[]>();
  positions.forEach((p, i) => {
    const key = `${p.y}:${p.h}`;
    const arr = rows.get(key) ?? [];
    arr.push(i);
    rows.set(key, arr);
  });
  return [...rows.values()];
}

interface NumberBuildOptions {
  text: string;
  position: Region;
  tier: FontTier;
  design: DesignDirectionSpec;
  highlight: boolean | undefined;
}

/**
 * Build a number block without hugging — measureRegion stretches to the
 * bottom margin so the shrink loop only contracts on width or on a genuine
 * height overflow, not on the pre-cut nominal band height. Hugging is
 * deferred to the emit pass so we can reposition the block to the shared
 * baseline first.
 */
function buildNumberBlock(opts: NumberBuildOptions): TextBlock {
  const accentColor = opts.highlight ? opts.design.palette.accent : opts.design.palette.text;
  const measureRegion: Region = {
    x: opts.position.x,
    y: opts.position.y,
    w: opts.position.w,
    h: availableHeightBelow(opts.position.y),
  };
  return buildTextBlock({
    text: opts.text,
    region: measureRegion,
    fontFamily: opts.design.heading_font,
    fontWeight: 'bold',
    color: accentColor,
    align: 'center',
    tier: opts.tier,
    lineHeight: LINE_HEIGHTS.heading,
  });
}

/**
 * Adaptive number font ceiling: derive from the height available to the
 * number specifically — band height minus the tallest below-stack and the
 * intra-stat gaps. Numbers grow to fill what's left; verbose labels push
 * the number ceiling down, terse labels let it grow toward NUMBER_CEILING_PX.
 */
function adaptiveNumberMaxPx(numberAvailablePct: number): number {
  const availablePx = (numberAvailablePct / 100) * SLIDE_HEIGHT;
  const targetHeightPx = availablePx * NUMBER_FILL_FRACTION;
  const fontSize = Math.round(targetHeightPx / RENDER_LINE_FACTOR);
  return Math.min(NUMBER_CEILING_PX, Math.max(NUMBER_PROBE_FLOOR_PX, fontSize));
}

/**
 * Largest font size at which `value` fits on a SINGLE line inside the
 * column. The default buildTextBlock loop accepts a value wrapping across
 * "94" / "4" because it caps maxLineWidth at the column width — that's
 * fine for prose, lethal for a headline number where a wrap reads as a
 * typo. We probe explicitly for the one-line fit; if no size in the range
 * does it (a pathological value longer than the column at the floor), we
 * fall back to the floor so the buildTextBlock loop downstream still
 * keeps the row uniform — the value will wrap, but the floor protects the
 * other stats in the row from being dragged with it.
 */
function maxSingleLineFontSize(
  value: string,
  column: Region,
  design: DesignDirectionSpec,
  ceilingPx: number,
  floorPx: number,
): number {
  const columnWidthPx = (column.w / 100) * SLIDE_WIDTH;
  for (let size = ceilingPx; size >= floorPx; size -= 2) {
    const m = measureText({
      text: value,
      fontSize: size,
      fontFamily: design.heading_font,
      fontWeight: 'bold',
      maxWidth: columnWidthPx,
      // Generous height — the predicate we want is just "lineCount === 1",
      // height-overflow would never trigger on a single-line measurement.
      maxHeight: SLIDE_HEIGHT,
      lineHeight: LINE_HEIGHTS.heading,
    });
    if (m.lineCount === 1) return size;
  }
  return floorPx;
}

export function layoutDataEmphasis(slide: SlideSpec, deck: DeckSpec): SlideLayout {
  const regions = SLIDE_REGIONS.data_emphasis!;
  const { design } = deck;
  const blocks: TextBlock[] = [];

  // Hug the title so the stat region derives from its REAL measured bottom (kills the frozen
  // y:14). Cap the title's fit-height so it cannot grow past the stat-reservation floor —
  // otherwise a pathological wrap would hug most of the slide and leave the stats in a
  // hairline band that overflows the bottom margin (Codex P2).
  const statContentTopCap = REGION_BOTTOM - MIN_STAT_REGION_H;
  const titleMaxH = Math.max(
    regions.title!.h,
    statContentTopCap - regions.title!.y - TITLE_GAP,
  );
  const titleBlock = hugHeightToMeasured(
    buildTextBlock({
      text: slide.content.title,
      region: {
        ...regions.title!,
        h: Math.min(availableHeightBelow(regions.title!.y), titleMaxH),
      },
      fontFamily: design.heading_font,
      fontWeight: 'bold',
      color: design.palette.text,
      align: 'left',
      tier: FONT_SIZES.heading,
      lineHeight: LINE_HEIGHTS.heading,
    }),
  );
  blocks.push(titleBlock);

  const stats = (slide.content.stats ?? []).slice(0, 4) as StatItem[];
  const count = Math.max(1, stats.length) as 1 | 2 | 3 | 4;
  const positions = STAT_POSITIONS[count];
  const isHero = count === 1;
  // Below-stack tiers are bumped from the original caption/subheading floor —
  // those sizes were calibrated against the old 50% mid-slide band where tall
  // ancillary text would have crowded the number. With the band expanded to
  // the full content region the unit/label/comparison carry the next tier up
  // and still leave headline-sized room for the number. Hero stats get an
  // additional tier of promotion: the single 50%-wide column carries more
  // ancillary text without crowding the number, and a hero deserves a hero
  // unit.
  const unitTier = isHero ? FONT_SIZES.displayJumbo : FONT_SIZES.heading;
  const labelTier = isHero ? FONT_SIZES.heading : FONT_SIZES.subheading;
  const comparisonTier = isHero ? FONT_SIZES.subheading : FONT_SIZES.body;

  const rows = groupRows(positions);

  // Derive the stat envelope from the title-hugged content region, then partition it into equal
  // row bands via the shared fit engine. Each measure() returns REGION GEOMETRY only (equalBandH
  // from contentH/ROW_GAP) — never the number's measured height — so the adaptive number ceiling
  // (which reads bandHeight) is NOT fed back into the band derivation (that feedback is the
  // circular collapse the frozen-band recipe would have introduced). For numRows===1 this
  // degenerates to a single band == the full content region (the number fills it); for
  // numRows===2 it yields two equal bands separated by ROW_GAP, the lower flush at the margin.
  const contentTop = Math.min(stackBelow(titleBlock, TITLE_GAP), statContentTopCap);
  const contentH = availableHeightBelow(contentTop);
  const numRows = rows.length;
  const equalBandH = Math.max(0, (contentH - (numRows - 1) * ROW_GAP) / numRows);
  const rowFit = fitMeasuredStack({
    region: { x: regions.title!.x, y: contentTop, w: regions.title!.w, h: contentH },
    items: rows.map(() => ({ measure: () => equalBandH, gapAfter: ROW_GAP })),
    overflow: 'truncate',
    anchor: 'start',
  });

  for (const [rowIdx, rowIndices] of rows.entries()) {
    if (rowIndices.length === 0) continue;
    const rowPositions = rowIndices.map((i) => positions[i]!);
    const rowStats = rowIndices.map((i) => stats[i]).filter((s): s is StatItem => Boolean(s));
    if (rowStats.length === 0) continue;

    const bandTop = rowFit.tops[rowIdx]!;
    const bandHeight = rowFit.heights[rowIdx]!;

    // BELOW PASS: build each stat's unit/label/comparison stack at its tier.
    // These probe against the available height down to the bottom margin so
    // the measured heights are real wrap heights, not pre-cut slots.
    const belowStacks: TextBlock[][] = rowStats.map((stat) => {
      const position = rowPositions[rowStats.indexOf(stat)]!;
      const measureRegion = (y: number): Region => ({
        x: position.x,
        y,
        w: position.w,
        h: availableHeightBelow(y),
      });
      const below: TextBlock[] = [];
      if (stat.unit) {
        below.push(
          hugHeightToMeasured(
            buildTextBlock({
              text: stat.unit,
              region: measureRegion(bandTop),
              fontFamily: design.body_font,
              fontWeight: 'normal',
              color: design.palette.text_secondary,
              align: 'center',
              tier: unitTier,
              lineHeight: LINE_HEIGHTS.body,
            }),
          ),
        );
      }
      below.push(
        hugHeightToMeasured(
          buildTextBlock({
            text: stat.label,
            region: measureRegion(bandTop),
            fontFamily: design.body_font,
            fontWeight: 'normal',
            color: design.palette.text,
            align: 'center',
            tier: labelTier,
            lineHeight: LINE_HEIGHTS.body,
          }),
        ),
      );
      if (stat.comparison) {
        below.push(
          hugHeightToMeasured(
            buildTextBlock({
              text: stat.comparison,
              region: measureRegion(bandTop),
              fontFamily: design.body_font,
              fontWeight: 'normal',
              color: design.palette.text_secondary,
              align: 'center',
              tier: comparisonTier,
              lineHeight: LINE_HEIGHTS.caption,
            }),
          ),
        );
      }
      return below;
    });

    // Tallest below-stack drives the number's ceiling: the number gets
    // (band - below - gaps) to render in. Each stat keeps its own below
    // measurement, but the SHARED row layout uses the maximum so all
    // columns reserve the same number-region height.
    const belowHeights = belowStacks.map(
      (stack) => stack.reduce((sum, b) => sum + b.h, 0) + STAT_BLOCK_GAP * stack.length,
    );
    const maxBelowHeight = Math.max(...belowHeights);
    const numberRegionHeight = Math.max(
      NUMBER_PROBE_FLOOR_PX / SLIDE_HEIGHT * 100,
      bandHeight - maxBelowHeight - STAT_BLOCK_GAP,
    );
    const numberCeiling = adaptiveNumberMaxPx(numberRegionHeight);

    // PROBE PASS: find the largest font size at which EACH value fits on
    // ONE line in its column. The uniform size is the MIN across the row,
    // floored at NUMBER_PROBE_FLOOR_PX so a single pathological value can't
    // drag the row below displayLarge.min. Forcing single-line avoids the
    // ugly digit-wrap a generic shrink-on-overflow loop would happily
    // accept (a column wide enough for "9" wraps "94.4" to "94" / "4").
    const perStatSingleLine = rowStats.map((stat, idx) =>
      maxSingleLineFontSize(stat.value, rowPositions[idx]!, design, numberCeiling, NUMBER_PROBE_FLOOR_PX),
    );
    const uniformSize = Math.min(...perStatSingleLine);
    const uniformTier: FontTier = { min: uniformSize, max: uniformSize };

    // EMIT PASS: rebuild every number at the uniform size; hug to measured
    // height here (not in the probe pass) so the renderer's overflow:hidden
    // box hugs the text after the shared-baseline reposition.
    const numberBlocks: TextBlock[] = rowStats.map((stat, idx) => {
      // Column x/w stay frozen (horizontal placement); anchor the number's
      // measurement box at the DERIVED bandTop so its height ceiling
      // (availableHeightBelow inside buildNumberBlock) tracks the real band, not
      // the frozen STAT_POSITIONS y — the last frozen-y removed by this migration.
      const position = { ...rowPositions[idx]!, y: bandTop };
      return hugHeightToMeasured(
        buildNumberBlock({
          text: stat.value,
          position,
          tier: uniformTier,
          design,
          highlight: stat.highlight,
        }),
      );
    });
    const stacks: StatStack[] = numberBlocks.map((number, i) => ({
      number,
      below: belowStacks[i]!,
    }));

    // Shared baseline = deepest number bottom in this row. Centre the
    // (number-row + below-stack) within the band: rowTop pins where the
    // tallest number begins; baselineY is its measured bottom.
    const maxNumberHeight = Math.max(...stacks.map((s) => s.number.measuredHeightPct));
    const rowContentHeight = maxNumberHeight + STAT_BLOCK_GAP + maxBelowHeight;
    const rowTop = bandTop + Math.max(0, (bandHeight - rowContentHeight) / 2);
    const baselineY = rowTop + maxNumberHeight;

    for (const stack of stacks) {
      // Position the number so its measured bottom sits at baselineY. The
      // never-stack-upward floor pins it at bandTop if its stack would
      // overflow the band — top-align instead of climbing into the title.
      stack.number.y = Math.max(bandTop, baselineY - stack.number.measuredHeightPct);
      blocks.push(stack.number);

      let cursorY = baselineY + STAT_BLOCK_GAP;
      for (const block of stack.below) {
        block.y = cursorY;
        cursorY = block.y + block.h + STAT_BLOCK_GAP;
        blocks.push(block);
      }
    }
  }

  const background = defaultBackground(design);
  return compose(slide, blocks, [], [], background);
}
