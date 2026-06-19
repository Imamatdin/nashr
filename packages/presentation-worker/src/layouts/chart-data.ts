/**
 * CHART_DATA layout.
 *
 * Reserves the 65×72 chart rectangle on the left, a 23×30
 * annotation column on the right, and a citation strip at the
 * bottom-right (R33).
 *
 * The chart is drawn natively from `slide.content.chart_series` by
 * `drawChart` (src/charts) — rect / line / circle ShapeBlocks plus text,
 * the same primitives every other layout uses, so it renders in HTML, PPTX,
 * and the PPTX→PDF alike. `chart_type` selects bar / line / single_value /
 * grouped_bar / stacked_bar (default bar). When the series is empty or
 * missing, the layout falls back to the centred `[Chart placeholder]` text
 * inside a faint panel rather than drawing an empty axis.
 *
 * The title takes the R35 phrasing: the *insight*, not the chart
 * type. That decision is the editorial pass's — the layout just
 * renders whatever title it's given.
 */

import { FONT_SIZES, LINE_HEIGHTS, SLIDE_REGIONS, type Region } from '../constants.js';
import { drawChart } from '../charts/draw-chart.js';
import type {
  DeckSpec,
  ShapeBlock,
  SlideLayout,
  SlideSpec,
  TextBlock,
} from '../types.js';
import { availableHeightBelow, buildTextBlock, compose, defaultBackground, stackBelow } from './shared.js';

const CHART_PLACEHOLDER_TEXT = '[Chart placeholder]';
const TITLE_GAP = 2;

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

  // Never-stack-upward floor: the chart starts at max(the designed body top, the
  // title's measured bottom + gap), so a multi-line title pushes it DOWN, never up
  // into the title. FILL: the chart then spans down to the bottom content margin
  // (R16) via availableHeightBelow — the frozen body height (72) is demoted to a
  // max bound and gone from the height, and there is no MIN clamp (a pathological
  // title shrinks the box; computePlotArea's plot-floor + per-bar buildTextBlock
  // shrink is the reliability floor). Collision-safe: the chart owns x:5..70; the
  // annotation column (x:72) and citation (x:70..95) are edge-adjacent on the
  // right, horizontally disjoint, so filling down the left side to y≈94 is clear.
  const baseChart = regions.body!;
  const contentTop = Math.max(baseChart.y, stackBelow(titleBlock, TITLE_GAP));
  const chartRegion: Region = {
    ...baseChart,
    y: contentTop,
    h: availableHeightBelow(contentTop),
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

  // Draw the real chart into the reserved box. A missing/empty series falls
  // back to the placeholder text so the slide never renders an empty axis.
  const chart = drawChart(chartRegion, slide.content, design);
  if (chart) {
    shapes.push(...chart.shapes);
    blocks.push(...chart.blocks);
  } else {
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
  }

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
