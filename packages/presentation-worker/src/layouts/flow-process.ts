/**
 * FLOW_PROCESS layout.
 *
 * 3-5 sequential steps in a horizontal row. Each step is a stacked
 * trio of number/icon, bold label, descriptive body text. Faint
 * accent-colour connector lines bridge consecutive steps.
 *
 * Geometry is REGION-RELATIVE, not hardcoded. The step row is centred
 * vertically within the content region (title bottom → bottom margin)
 * and the number tier is sized adaptively against that region. Three
 * shared rows result: every step's number sits at the same y (so the
 * connector line cuts horizontally across them); every step's label
 * sits at the same y; every step's description starts at the same y
 * but its rendered height is measured (long descriptions push into
 * the band, short ones don't strand). Long descriptions get a real
 * body tier — small (12-14px) wastes the band.
 *
 * Do NOT re-introduce NUMBER_Y/LABEL_Y/DESCRIPTION_Y/CONNECTOR_Y
 * constants — that's the hardcoded-geometry violation of
 * docs/INVARIANTS.md this file exists to kill. Positions are computed
 * from the region and the measured content.
 */

import {
  FONT_SIZES,
  LINE_HEIGHTS,
  MARGIN,
  SLIDE_HEIGHT,
  SLIDE_REGIONS,
  type Region,
} from '../constants.js';
import type { DeckSpec, ShapeBlock, SlideLayout, SlideSpec, TextBlock } from '../types.js';
import { buildTextBlock, compose, defaultBackground, hugHeightToMeasured, type FontTier } from './shared.js';
import { fitMeasuredStack } from './fit.js';

/** Horizontal layout: the step grid occupies the central 80% of the slide. */
const FLOW_LEFT_MARGIN = 10;
const FLOW_TOTAL_WIDTH = 80;

/** Vertical breather between the title bottom and the step row. */
const TITLE_GAP = 3;

/** Inter-block gaps within a step column (slide %). */
const NUMBER_TO_LABEL_GAP = 2;
const LABEL_TO_DESCRIPTION_GAP = 1.5;

/** Adaptive number tier ceiling (px) and target fraction of region height.
 *  Mirrors the data_emphasis tuning: aim for ~30% of region height as the
 *  rendered number height, cap at 240px to match the data_emphasis hero
 *  cap so the two layouts read at the same headline scale. */
const NUMBER_CEILING_PX = 240;
const NUMBER_TARGET_REGION_FRACTION = 0.3;
const NUMBER_FLOOR_PX = 64;

/** Render-cost multiplier mirrored from text-measure.HEIGHT_SAFETY (1.3)
 *  × LINE_HEIGHTS.heading (1.1). */
const RENDER_LINE_FACTOR = LINE_HEIGHTS.heading * 1.3;

/** Connector line stroke (raw px in the renderer). */
const CONNECTOR_STROKE_PX = 2;
const CONNECTOR_OPACITY = 0.3;

/**
 * Compute the adaptive number font max (px) for the given region height.
 * Bigger region → bigger numbers, bounded by NUMBER_CEILING_PX and never
 * smaller than NUMBER_FLOOR_PX (the floor is what gives 3-5 step decks
 * with skinny regions a still-readable number).
 */
function adaptiveNumberMaxPx(regionHeightPct: number): number {
  const regionHeightPx = (regionHeightPct / 100) * SLIDE_HEIGHT;
  const targetHeightPx = regionHeightPx * NUMBER_TARGET_REGION_FRACTION;
  const fontSize = Math.round(targetHeightPx / RENDER_LINE_FACTOR);
  return Math.min(NUMBER_CEILING_PX, Math.max(NUMBER_FLOOR_PX, fontSize));
}

interface StepBlocks {
  number: TextBlock;
  label: TextBlock;
  description: TextBlock;
}

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

  const titleBottom = regions.title!.y + regions.title!.h;
  const regionTop = titleBottom + TITLE_GAP;
  const regionBottom = 100 - MARGIN.bottom;
  const regionHeight = regionBottom - regionTop;

  const columnWidth = FLOW_TOTAL_WIDTH / steps.length;
  const numberMaxPx = adaptiveNumberMaxPx(regionHeight);
  const numberTier: FontTier = { min: NUMBER_FLOOR_PX, max: numberMaxPx };
  // Labels and descriptions are bumped up two tiers from the old (caption,
  // small) — that pairing was sized against the old 6%/15% pre-cut slots
  // and looks anaemic next to a 200px+ number. Labels are the step name
  // (heading, bold) so they hold their own under the headline number;
  // descriptions read at subheading so they fill the remaining band.
  const labelTier = FONT_SIZES.heading;
  const descriptionTier = FONT_SIZES.subheading;

  // BUILD PASS: measure each step's three blocks. The label and description
  // probe against the full region height (not a pre-cut slot) so a wrapped
  // multi-line block measures its real height rather than overflowing a
  // fixed 6%/15% box.
  const stepBlocks: StepBlocks[] = steps.map((step, idx) => {
    const stepX = FLOW_LEFT_MARGIN + idx * columnWidth;
    const fullRegion: Region = {
      x: stepX,
      y: regionTop,
      w: columnWidth,
      h: regionHeight,
    };

    const number = hugHeightToMeasured(
      buildTextBlock({
        text: step.icon ?? String(idx + 1),
        region: fullRegion,
        fontFamily: design.heading_font,
        fontWeight: 'bold',
        color: design.palette.accent,
        align: 'center',
        tier: numberTier,
        lineHeight: LINE_HEIGHTS.heading,
      }),
    );

    const label = hugHeightToMeasured(
      buildTextBlock({
        text: step.label,
        region: fullRegion,
        fontFamily: design.body_font,
        fontWeight: 'bold',
        color: design.palette.text,
        align: 'center',
        tier: labelTier,
        lineHeight: LINE_HEIGHTS.body,
        // Step columns get narrow at 5 steps (16% slot ≈ 240px usable).
        // A verbose label at heading.min=28 can still pin-overflow; the
        // permissive floor is the Q1 safety the chart bar label path
        // also uses. Numbers are not given this escape — they hold their
        // adaptive tier so the canvas-fill stays headline-sized.
        minFontSize: FONT_SIZES.minimum,
      }),
    );

    const description = hugHeightToMeasured(
      buildTextBlock({
        text: step.description,
        region: fullRegion,
        fontFamily: design.body_font,
        fontWeight: 'normal',
        color: design.palette.text_secondary,
        align: 'center',
        tier: descriptionTier,
        lineHeight: LINE_HEIGHTS.body,
        minFontSize: FONT_SIZES.minimum,
      }),
    );

    return { number, label, description };
  });

  // PLACE PASS: compute shared row y's. Numbers and labels use the row
  // maxima so the whole grid reads as horizontal strips. Descriptions
  // share a top-y so they hang off the label strip uniformly, but each
  // column keeps its own measured height — a longer description renders
  // taller than its short neighbours rather than clipping.
  // Fit the three SHARED rows (number/label/description) ONCE and reuse the tops
  // for every column, so the grid reads as horizontal strips (the connector cuts
  // the number row) while each column keeps its own measured block height.
  //
  // measure() returns each row's max HUGGED height (block.h, which already carries
  // hugHeightToMeasured's anti-clip epsilon) — NOT measuredHeightPct — so the
  // distributed bottom band reserves that epsilon and the tallest description
  // lands exactly on the region bottom instead of 0.2pp past it.
  //
  // ANCHOR DECISION — distribute: the step rows SPACE OUT across the content
  // region (airy strips) rather than clumping in a centred block;
  // NUMBER_TO_LABEL_GAP / LABEL_TO_DESCRIPTION_GAP are the floor gaps and the
  // surplus is spread evenly between them. overflow:'truncate' keeps scale=1 — the
  // blocks are already built at their own hugged height, so a global scale would
  // compress the tops while the blocks stayed full size and overlap; per-block
  // buildTextBlock shrink (minFontSize) is the reliability floor.
  const maxNumberH = Math.max(...stepBlocks.map((s) => s.number.h));
  const maxLabelH = Math.max(...stepBlocks.map((s) => s.label.h));
  const maxDescriptionH = Math.max(...stepBlocks.map((s) => s.description.h));

  const fit = fitMeasuredStack({
    region: { x: FLOW_LEFT_MARGIN, y: regionTop, w: FLOW_TOTAL_WIDTH, h: regionHeight },
    items: [
      { measure: () => maxNumberH, gapAfter: NUMBER_TO_LABEL_GAP },
      { measure: () => maxLabelH, gapAfter: LABEL_TO_DESCRIPTION_GAP },
      { measure: () => maxDescriptionH },
    ],
    overflow: 'truncate',
    anchor: 'distribute',
  });
  const numberY = fit.tops[0]!;
  const labelY = fit.tops[1]!;
  const descriptionY = fit.tops[2]!;

  for (const sb of stepBlocks) {
    sb.number.y = numberY;
    sb.label.y = labelY;
    sb.description.y = descriptionY;
    blocks.push(sb.number, sb.label, sb.description);
  }

  // Connector: a thin horizontal line at the vertical centre of the number
  // row. Hairlines are positioned by their TOP-y in slide %, with stroke
  // applied as raw px — 2px is 0.18pp on a 1080-px slide, so the visual
  // misalignment of using "centre y" as "top y" is invisible and the test
  // only asserts opacity + count. Bridging the gap between consecutive
  // columns at 80%/20% of the column width leaves the number/label
  // glyphs clear of the line.
  const connectorY = numberY + maxNumberH / 2;
  for (let i = 0; i < steps.length - 1; i++) {
    const startX = FLOW_LEFT_MARGIN + i * columnWidth + columnWidth * 0.8;
    const endX = FLOW_LEFT_MARGIN + (i + 1) * columnWidth + columnWidth * 0.2;
    shapes.push({
      type: 'line',
      x: startX,
      y: connectorY,
      w: endX - startX,
      h: 0,
      stroke: design.palette.accent,
      strokeWidth: CONNECTOR_STROKE_PX,
      opacity: CONNECTOR_OPACITY,
    });
  }

  const background = defaultBackground(design);
  return compose(slide, blocks, [], shapes, background);
}
