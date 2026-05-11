/**
 * TIMELINE layout (horizontal, 1-6 nodes).
 *
 * A 2px accent-coloured horizontal line at y=45%, with evenly-spaced
 * node circles on the line. Each node carries a bold date above the
 * line and a label below. Single-node timelines centre at x=50%.
 *
 * Circle shape positioning follows the SVG `cx,cy` convention: the
 * `x`,`y` fields name the *centre* of the circle, not its top-left
 * corner. The renderer reads them as the node centre.
 */

import { FONT_SIZES, LINE_HEIGHTS, SLIDE_REGIONS, type Region } from '../constants.js';
import type {
  DeckSpec,
  ShapeBlock,
  SlideLayout,
  SlideSpec,
  TextBlock,
} from '../types.js';
import { buildTextBlock, compose, defaultBackground } from './shared.js';

const LINE_Y = 45;
const LINE_LEFT_X = 10;
const LINE_RIGHT_X = 90;
const NODE_DIAMETER = 1;
const DATE_W = 16;
const DATE_H = 8;
const DATE_Y = 33;
const LABEL_W = 20;
const LABEL_H = 12;
const LABEL_Y = 50;

export function layoutTimeline(slide: SlideSpec, deck: DeckSpec): SlideLayout {
  const regions = SLIDE_REGIONS.timeline!;
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

  const nodes = (slide.content.timeline_nodes ?? []).slice(0, 6);
  if (nodes.length === 0) {
    const background = defaultBackground(design);
    return compose(slide, blocks, [], shapes, background);
  }

  shapes.push({
    type: 'line',
    x: LINE_LEFT_X,
    y: LINE_Y,
    w: LINE_RIGHT_X - LINE_LEFT_X,
    h: 0,
    stroke: design.palette.accent,
    strokeWidth: 2,
    opacity: 1,
  });

  nodes.forEach((node, idx) => {
    const nodeX = nodeXFor(idx, nodes.length);

    shapes.push({
      type: 'circle',
      x: nodeX,
      y: LINE_Y,
      w: NODE_DIAMETER,
      h: NODE_DIAMETER,
      fill: design.palette.accent,
      opacity: 1,
    });

    const dateRegion: Region = {
      x: clamp(nodeX - DATE_W / 2, 0, 100 - DATE_W),
      y: DATE_Y,
      w: DATE_W,
      h: DATE_H,
    };
    blocks.push(
      buildTextBlock({
        text: node.date,
        region: dateRegion,
        fontFamily: design.body_font,
        fontWeight: 'bold',
        color: design.palette.text,
        align: 'center',
        tier: FONT_SIZES.subheading,
        lineHeight: LINE_HEIGHTS.heading,
      }),
    );

    const labelRegion: Region = {
      x: clamp(nodeX - LABEL_W / 2, 0, 100 - LABEL_W),
      y: LABEL_Y,
      w: LABEL_W,
      h: LABEL_H,
    };
    blocks.push(
      buildTextBlock({
        text: node.label,
        region: labelRegion,
        fontFamily: design.body_font,
        fontWeight: 'normal',
        color: design.palette.text_secondary,
        align: 'center',
        tier: FONT_SIZES.small,
        lineHeight: LINE_HEIGHTS.caption,
      }),
    );
  });

  const background = defaultBackground(design);
  return compose(slide, blocks, [], shapes, background);
}

function nodeXFor(idx: number, count: number): number {
  if (count <= 1) return 50;
  const span = LINE_RIGHT_X - LINE_LEFT_X;
  return LINE_LEFT_X + (idx * span) / (count - 1);
}

function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value));
}
