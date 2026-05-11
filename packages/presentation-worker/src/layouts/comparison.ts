/**
 * COMPARISON layout.
 *
 * Side-by-side comparison of two columns. The left and right columns
 * are 43% wide with a thin accent-colour divider at the gutter
 * midline. The column flagged `is_preferred` gets the accent colour
 * on its heading; the other gets the standard text colour.
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
import { buildTextBlock, compose, defaultBackground } from './shared.js';

export function layoutComparison(slide: SlideSpec, deck: DeckSpec): SlideLayout {
  const regions = SLIDE_REGIONS.comparison!;
  const { design } = deck;
  const blocks: TextBlock[] = [];
  const shapes: ShapeBlock[] = [];

  blocks.push(
    buildTextBlock({
      text: slide.content.title,
      region: regions.title!,
      fontFamily: design.heading_font,
      fontWeight: 'bold',
      color: design.palette.text,
      align: 'left',
      tier: FONT_SIZES.heading,
      lineHeight: LINE_HEIGHTS.heading,
    }),
  );

  const leftRegion = regions.body!;
  const rightRegion = regions.image!;

  layoutComparisonColumn(slide.content.left_column, leftRegion, design, blocks);
  layoutComparisonColumn(slide.content.right_column, rightRegion, design, blocks);

  shapes.push({
    type: 'rect',
    x: 49.9,
    y: leftRegion.y,
    w: 0.1,
    h: leftRegion.h,
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

  const headingRegion: Region = { x: region.x, y: region.y, w: region.w, h: 8 };
  blocks.push(
    buildTextBlock({
      text: column.heading,
      region: headingRegion,
      fontFamily: design.heading_font,
      fontWeight: 'bold',
      color: column.is_preferred ? design.palette.accent : design.palette.text,
      align: 'left',
      tier: FONT_SIZES.subheading,
      lineHeight: LINE_HEIGHTS.heading,
    }),
  );

  const points = column.points ?? [];
  if (points.length === 0) return;

  const pointsTop = region.y + 10;
  const pointsBottom = region.y + region.h;
  const totalH = pointsBottom - pointsTop;
  const slotH = totalH / Math.max(1, points.length);

  points.forEach((point, idx) => {
    const pointRegion: Region = {
      x: region.x,
      y: pointsTop + idx * slotH,
      w: region.w,
      h: slotH * 0.9,
    };
    blocks.push(
      buildTextBlock({
        text: `• ${point}`,
        region: pointRegion,
        fontFamily: design.body_font,
        fontWeight: 'normal',
        color: design.palette.text,
        align: 'left',
        tier: FONT_SIZES.body,
        lineHeight: LINE_HEIGHTS.body,
      }),
    );
  });
}
