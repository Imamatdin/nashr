/**
 * FLOW_PROCESS layout.
 *
 * 3-5 sequential steps in a horizontal row. Each step is a stacked
 * trio of number/icon, bold label, descriptive body text. Faint
 * accent-colour connector lines bridge consecutive steps.
 *
 * Step columns occupy the central 80% of the slide; the number
 * region sits centred above the label so the whole step reads as a
 * single column.
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

const FLOW_LEFT_MARGIN = 10;
const FLOW_TOTAL_WIDTH = 80;
const NUMBER_Y = 28;
const NUMBER_H = 8;
const NUMBER_W = 6;
const LABEL_Y = 42;
const LABEL_H = 6;
const DESCRIPTION_Y = 50;
const DESCRIPTION_H = 15;
const CONNECTOR_Y = 35;

export function layoutFlowProcess(slide: SlideSpec, deck: DeckSpec): SlideLayout {
  const regions = SLIDE_REGIONS.flow_process!;
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

  const steps = (slide.content.steps ?? []).slice(0, 5);
  if (steps.length === 0) {
    const background = defaultBackground(design);
    return compose(slide, blocks, [], shapes, background);
  }

  const columnWidth = FLOW_TOTAL_WIDTH / steps.length;

  steps.forEach((step, idx) => {
    const stepX = FLOW_LEFT_MARGIN + idx * columnWidth;

    const numberRegion: Region = {
      x: stepX + columnWidth / 2 - NUMBER_W / 2,
      y: NUMBER_Y,
      w: NUMBER_W,
      h: NUMBER_H,
    };
    blocks.push(
      buildTextBlock({
        text: step.icon ?? String(idx + 1),
        region: numberRegion,
        fontFamily: design.heading_font,
        fontWeight: 'bold',
        color: design.palette.accent,
        align: 'center',
        tier: FONT_SIZES.displayLarge,
        lineHeight: LINE_HEIGHTS.heading,
      }),
    );

    const labelRegion: Region = {
      x: stepX,
      y: LABEL_Y,
      w: columnWidth,
      h: LABEL_H,
    };
    blocks.push(
      buildTextBlock({
        text: step.label,
        region: labelRegion,
        fontFamily: design.body_font,
        fontWeight: 'bold',
        color: design.palette.text,
        align: 'center',
        tier: FONT_SIZES.caption,
        lineHeight: LINE_HEIGHTS.body,
      }),
    );

    const descRegion: Region = {
      x: stepX,
      y: DESCRIPTION_Y,
      w: columnWidth,
      h: DESCRIPTION_H,
    };
    blocks.push(
      buildTextBlock({
        text: step.description,
        region: descRegion,
        fontFamily: design.body_font,
        fontWeight: 'normal',
        color: design.palette.text_secondary,
        align: 'center',
        tier: FONT_SIZES.small,
        lineHeight: LINE_HEIGHTS.body,
      }),
    );
  });

  for (let i = 0; i < steps.length - 1; i++) {
    const startX = FLOW_LEFT_MARGIN + i * columnWidth + columnWidth * 0.8;
    const endX = FLOW_LEFT_MARGIN + (i + 1) * columnWidth + columnWidth * 0.2;
    shapes.push({
      type: 'line',
      x: startX,
      y: CONNECTOR_Y,
      w: endX - startX,
      h: 0,
      stroke: design.palette.accent,
      strokeWidth: 2,
      opacity: 0.3,
    });
  }

  const background = defaultBackground(design);
  return compose(slide, blocks, [], shapes, background);
}
