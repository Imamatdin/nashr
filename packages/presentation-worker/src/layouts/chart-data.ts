/**
 * CHART_DATA layout.
 *
 * Reserves the 65×72 chart rectangle on the left, a 23×30
 * annotation column on the right, and a citation strip at the
 * bottom-right (R33).
 *
 * The chart itself is a placeholder for v1: a centred text block
 * inside a faint palette.surface rectangle. The real chart
 * component (recharts or generated SVG) will drop into this region
 * in a later task without disturbing the rest of the layout.
 *
 * The title takes the R35 phrasing: the *insight*, not the chart
 * type. That decision is the editorial pass's — the layout just
 * renders whatever title it's given.
 */

import { FONT_SIZES, LINE_HEIGHTS, SLIDE_REGIONS, type Region } from '../constants.js';
import type {
  DeckSpec,
  ShapeBlock,
  SlideLayout,
  SlideSpec,
  TextBlock,
} from '../types.js';
import { buildTextBlock, compose, defaultBackground, stackBelow } from './shared.js';

const CHART_PLACEHOLDER_TEXT = '[Chart placeholder]';
const TITLE_GAP = 2;
const MIN_CHART_HEIGHT = 20;

export function layoutChartData(slide: SlideSpec, deck: DeckSpec): SlideLayout {
  const regions = SLIDE_REGIONS.chart_data!;
  const { design } = deck;
  const blocks: TextBlock[] = [];
  const shapes: ShapeBlock[] = [];

  const titleBlock = buildTextBlock({
    text: slide.content.title,
    region: regions.title!,
    fontFamily: design.heading_font,
    fontWeight: 'bold',
    color: design.palette.text,
    align: 'left',
    tier: FONT_SIZES.heading,
    lineHeight: LINE_HEIGHTS.heading,
  });
  blocks.push(titleBlock);

  // Never-stack-upward floor: the chart box (and its annotation column)
  // start at max(the designed body region y, the title's measured bottom).
  // The max() — never a min-clamp — means the content can only ever move
  // DOWN to clear a multi-line title, never up into it, so the title can't
  // overlap the chart. A short title leaves the content at its designed top.
  // Pin the chart bottom and shrink the box from the top so it stays
  // on-slide when pushed down.
  const baseChart = regions.body!;
  const chartBottom = baseChart.y + baseChart.h;
  const contentTop = Math.max(baseChart.y, stackBelow(titleBlock, TITLE_GAP));
  const chartRegion: Region = {
    ...baseChart,
    y: contentTop,
    h: Math.max(MIN_CHART_HEIGHT, chartBottom - contentTop),
  };
  shapes.push({
    type: 'rect',
    x: chartRegion.x,
    y: chartRegion.y,
    w: chartRegion.w,
    h: chartRegion.h,
    fill: design.palette.surface,
    opacity: 0.03,
  });

  blocks.push(
    buildTextBlock({
      text: CHART_PLACEHOLDER_TEXT,
      region: chartRegion,
      fontFamily: design.body_font,
      fontWeight: 'normal',
      color: design.palette.text_secondary,
      align: 'center',
      tier: FONT_SIZES.body,
      lineHeight: LINE_HEIGHTS.body,
    }),
  );

  if (slide.content.body_text) {
    const annotationRegion: Region = { ...regions.caption!, y: contentTop };
    blocks.push(
      buildTextBlock({
        text: slide.content.body_text,
        region: annotationRegion,
        fontFamily: design.body_font,
        fontWeight: 'normal',
        color: design.palette.text,
        align: 'left',
        tier: FONT_SIZES.caption,
        lineHeight: LINE_HEIGHTS.body,
      }),
    );
  }

  if (slide.content.source_citation) {
    blocks.push(
      buildTextBlock({
        text: slide.content.source_citation,
        region: regions.citation!,
        fontFamily: design.body_font,
        fontWeight: 'normal',
        color: design.palette.text_secondary,
        align: 'right',
        tier: FONT_SIZES.small,
        lineHeight: LINE_HEIGHTS.caption,
      }),
    );
  }

  const background = defaultBackground(design);
  return compose(slide, blocks, [], shapes, background);
}
