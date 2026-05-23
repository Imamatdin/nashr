/**
 * COMPARISON layout.
 *
 * Side-by-side comparison of two columns. The left and right columns
 * are 43% wide with a thin accent-colour divider at the gutter
 * midline. The column flagged `is_preferred` gets the accent colour
 * on its heading; the other gets the standard text colour.
 *
 * Both columns share a top edge that floors below the title's measured bottom,
 * and within each column the bullet points stack below the heading's real
 * bottom and below each other (stackBelow + hugHeightToMeasured) rather than
 * dropping into fixed equal-height slots — so a long heading or a point that
 * wraps to two lines pushes the next point down instead of clipping.
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
} from './shared.js';

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

  // Both columns start at the same top edge: their designed y, floored below a
  // tall title's measured bottom so the title can't overlap the columns.
  const columnTop = Math.max(regions.body!.y, stackBelow(titleBlock, COLUMN_GAP));
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

  const columnBottom = region.y + region.h;

  const headingBlock = hugHeightToMeasured(
    buildTextBlock({
      text: column.heading,
      region: { x: region.x, y: region.y, w: region.w, h: region.h },
      fontFamily: design.heading_font,
      fontWeight: 'bold',
      color: column.is_preferred ? design.palette.accent : design.palette.text,
      align: 'left',
      tier: FONT_SIZES.subheading,
      lineHeight: LINE_HEIGHTS.heading,
    }),
  );
  blocks.push(headingBlock);

  const points = column.points ?? [];
  if (points.length === 0) return;

  let cursorY = stackBelow(headingBlock, HEADING_GAP);
  points.forEach((point) => {
    const pointBlock = hugHeightToMeasured(
      buildTextBlock({
        text: `• ${point}`,
        region: {
          x: region.x,
          y: cursorY,
          w: region.w,
          h: Math.max(0, columnBottom - cursorY),
        },
        fontFamily: design.body_font,
        fontWeight: 'normal',
        color: design.palette.text,
        align: 'left',
        tier: FONT_SIZES.body,
        lineHeight: LINE_HEIGHTS.body,
      }),
    );
    blocks.push(pointBlock);
    cursorY = stackBelow(pointBlock, POINT_GAP);
  });
}
