/**
 * COMPARISON layout.
 *
 * Side-by-side comparison of two columns. The left and right columns
 * are 43% wide with a thin accent-colour divider at the gutter
 * midline. The column flagged `is_preferred` gets the accent colour
 * on its heading; the other gets the standard text colour.
 *
 * Both columns share a top edge hugged below the title's measured bottom, and
 * within each column the heading + points are placed by the shared fit engine
 * (fitMeasuredStack, anchor:'start') — each block hugs its own measured height,
 * so a long heading or a point that wraps to two lines pushes the next one down
 * instead of dropping into a fixed equal-height slot.
 */

import { FONT_SIZES, LINE_HEIGHTS, SLIDE_REGIONS, type Region } from '../constants.js';
import type {
  DeckSpec,
  DesignDirectionSpec,
  ShapeBlock,
  SlideContent,
  SlideLayout,
  SlideSpec,
  TextBlock,
} from '../types.js';
import {
  availableHeightBelow,
  buildTextBlock,
  compose,
  defaultBackground,
  hugHeightToMeasured,
  stackBelow,
  stripListPrefix,
} from './shared.js';
import { fitMeasuredStack } from './fit.js';

const COLUMN_GAP = 2; // below the title before the columns
const HEADING_GAP = 2; // below a column heading before its first point
const POINT_GAP = 1.5; // between consecutive points in a column

export function layoutComparison(slide: SlideSpec, deck: DeckSpec): SlideLayout {
  const regions = SLIDE_REGIONS.comparison!;
  const { design } = deck;
  const blocks: TextBlock[] = [];
  const shapes: ShapeBlock[] = [];

  const titleBlock = hugHeightToMeasured(
    buildTextBlock({
      text: slide.content.title,
      region: { ...regions.title!, h: availableHeightBelow(regions.title!.y) },
      fontFamily: design.heading_font,
      fontWeight: 'bold',
      color: design.palette.text,
      align: 'left',
      tier: FONT_SIZES.heading,
      lineHeight: LINE_HEIGHTS.heading,
    }),
  );
  blocks.push(titleBlock);

  // Both columns start at the same top edge, hugged below the title's REAL
  // measured bottom (no fixed floor): dropping the old Math.max(regions.body.y, …)
  // removes the dead gap that stranded the columns at the designed body.y (15)
  // even under a short title.
  const columnTop = stackBelow(titleBlock, COLUMN_GAP);
  const columnHeight = availableHeightBelow(columnTop);
  const leftRegion: Region = { ...regions.body!, y: columnTop, h: columnHeight };
  const rightRegion: Region = { ...regions.image!, y: columnTop, h: columnHeight };

  layoutComparisonColumn(slide.content.left_column, leftRegion, design, blocks);
  layoutComparisonColumn(slide.content.right_column, rightRegion, design, blocks);

  shapes.push({
    type: 'rect',
    x: 49.9,
    y: columnTop,
    w: 0.1,
    h: columnHeight,
    fill: design.palette.accent,
    opacity: 0.3,
  });

  const background = defaultBackground(design);
  return compose(slide, blocks, [], shapes, background);
}

function layoutComparisonColumn(
  column: SlideContent['left_column'],
  region: Region,
  design: DesignDirectionSpec,
  blocks: TextBlock[],
): void {
  if (!column) return;

  // Build tall against the full column (so a long heading/point shrinks-to-fit
  // there), then let the shared fit engine place the stack. The heading-color
  // branch below is the column-emphasis contract — keep it byte-identical.
  const headingBlock = buildTextBlock({
    text: column.heading,
    region,
    fontFamily: design.heading_font,
    fontWeight: 'bold',
    color: column.is_preferred ? design.palette.accent : design.palette.text,
    align: 'left',
    tier: FONT_SIZES.subheading,
    lineHeight: LINE_HEIGHTS.heading,
  });

  const pointBlocks = (column.points ?? []).map((point) =>
    buildTextBlock({
      text: `• ${stripListPrefix(point)}`,
      region,
      fontFamily: design.body_font,
      fontWeight: 'normal',
      color: design.palette.text,
      align: 'left',
      tier: FONT_SIZES.body,
      lineHeight: LINE_HEIGHTS.body,
    }),
  );

  // anchor:'start' ⇒ tops[0] === region.y (= columnTop); each block then hugs its
  // own measured height (valign stays 'top' — do NOT emitBandCell). overflow:
  // 'truncate' makes per-block shrink+truncate the only reliability floor.
  const stack = [headingBlock, ...pointBlocks];
  const fit = fitMeasuredStack({
    region,
    items: [
      { measure: () => headingBlock.measuredHeightPct, gapAfter: HEADING_GAP },
      ...pointBlocks.map((p) => ({ measure: () => p.measuredHeightPct, gapAfter: POINT_GAP })),
    ],
    overflow: 'truncate',
    anchor: 'start',
  });

  stack.forEach((block, i) => {
    block.y = fit.tops[i]!;
    hugHeightToMeasured(block);
    blocks.push(block);
  });
}
