/**
 * Native-shape chart drawing for CHART_DATA slides.
 *
 * Composes charts from the same rect / line / circle ShapeBlocks and
 * TextBlocks the rest of the worker draws — no SVG, no charting library, no
 * browser. The same primitives render in HTML, in PPTX (pptxgenjs addShape),
 * and therefore in the PPTX→LibreOffice PDF, so one drawing path serves all
 * three export formats.
 *
 * Scope is the LEAN static export chart: four types (bar, line,
 * single_value, grouped/stacked bar), zero-based axis, value + category
 * labels, a baseline, a per-deck colour ramp. Rich / animated / interactive
 * charts are the WEB-surface phase, deferred, consuming this same
 * chart_series / chart_type spec.
 *
 * Everything is positioned in slide percentages inside `region`; nothing is
 * drawn outside it (the caller hands in a collision-safe chart box).
 */

import { FONT_SIZES, LINE_HEIGHTS, type Region } from '../constants.js';
import { buildTextBlock, type FontTier, hugHeightToMeasured } from '../layouts/shared.js';
import { fitMeasuredStack } from '../layouts/fit.js';
import type {
  ChartSeriesPoint,
  DesignDirectionSpec,
  ShapeBlock,
  SlideContent,
  TextBlock,
} from '../types.js';
import {
  circleShape,
  formatChartValue,
  horizontalRule,
  resolveChartRamp,
} from './chart-style.js';
import { validateChartEncoding } from './chart-guard.js';

export interface ChartDrawing {
  shapes: ShapeBlock[];
  blocks: TextBlock[];
}

// Spacing (slide %) and ratios. Pads are capped to a fraction of the region
// so a squeezed chart box (pushed down by a tall title) still leaves a plot.
const TOP_PAD = 8;
const BOTTOM_PAD = 7;
const SIDE_PAD = 1.5;
const LEGEND_BAND = 6;
const VALUE_LABEL_BAND = 6;
const VALUE_LABEL_GAP = 0.4;
const CAT_LABEL_GAP = 0.6;
const BAR_FILL_RATIO = 0.62;
const GROUP_SLOT_RATIO = 0.74;
const LINE_STROKE = 3;
const BASELINE_STROKE = 2;
const POINT_DIAMETER = 14;
const AXIS_OPACITY = 0.45;
/** Beyond this many sub-bars a grouped chart drops per-bar value labels. */
const GROUPED_LABEL_BUDGET = 8;
/** Height (slide %) of the visible tick that marks an explicit-zero bar. */
const ZERO_TICK_HEIGHT = 0.45;

interface PlotArea {
  x: number;
  y: number;
  w: number;
  h: number;
  bottom: number;
}

function computePlotArea(region: Region, legendBand: number): PlotArea {
  const topPad = Math.min(TOP_PAD, region.h * 0.16);
  const bottomPad = Math.min(BOTTOM_PAD, region.h * 0.16);
  const sidePad = Math.min(SIDE_PAD, region.w * 0.04);
  const y = region.y + topPad + legendBand;
  const h = Math.max(2, region.h - topPad - bottomPad - legendBand);
  return { x: region.x + sidePad, y, w: region.w - 2 * sidePad, h, bottom: y + h };
}

/**
 * Draw the chart for a CHART_DATA slide into `region`. Returns `null` when
 * there is no series to plot, so the caller falls back to its placeholder.
 *
 * The encoding goes through {@link validateChartEncoding} first — a
 * deterministic guard that re-routes a chart whose `chart_type` would
 * misrepresent the data's shape (low-spread bars, zero-laden bars). Every
 * re-route is logged via the worker's existing stderr pipeline so the
 * behavior is observable in production.
 */
export function drawChart(
  region: Region,
  content: SlideContent,
  design: DesignDirectionSpec,
): ChartDrawing | null {
  if ((content.chart_series ?? []).length === 0) return null;

  const decision = validateChartEncoding(content);
  for (const reroute of decision.reroutes) {
    // Match the worker's existing logging pipeline (process.stderr is what
    // src/index.ts and src/font-metrics.ts already use). One line per
    // re-route, structured key=value so logs are greppable in production.
    process.stderr.write(
      `chart_encoding_rerouted from=${reroute.from} to=${reroute.to} ` +
        `reason=${reroute.reason} :: ${reroute.detail}\n`,
    );
  }

  const { chartType, series, groupLabels, zeroAnnotations, subjectIndex } = decision;

  switch (chartType) {
    case 'single_value':
      return drawSingleValue(region, series, design);
    case 'line':
      return drawLine(region, series, design);
    case 'grouped_bar':
      return drawGrouped(region, groupLabels, series, design, false);
    case 'stacked_bar':
      return drawGrouped(region, groupLabels, series, design, true);
    case 'bar':
      return drawBar(region, series, design, zeroAnnotations);
    case 'multi_stat':
      return drawMultiStat(region, series, design, subjectIndex ?? 0);
  }
}

// ---------------------------------------------------------------------------
// Shared label builders
// ---------------------------------------------------------------------------

/** A value label hugged to its text and placed just above `barTopY`.
 *
 * The measure region's height is the REAL space available above the bar
 * (capped at VALUE_LABEL_BAND when there's plenty of room — we don't want
 * a single-line value label to stretch over the whole plot), not a fixed
 * 6pp slot. Verbose units like "% waste heat recovered" wrap to 2 lines
 * at subheading.min; that wrap was the slide-11 Q1 overflow. The dynamic
 * height accommodates the wrap; `minFontSize: FONT_SIZES.minimum` is the
 * belt-and-suspenders safety so a tall-bar + verbose-unit combination
 * shrinks past the tier floor instead of pin-overflowing. */
function valueLabel(
  text: string,
  slotX: number,
  slotW: number,
  barTopY: number,
  regionTop: number,
  design: DesignDirectionSpec,
  tier: FontTier = FONT_SIZES.subheading,
): TextBlock {
  const availableAbovePct = Math.max(VALUE_LABEL_BAND, barTopY - regionTop - VALUE_LABEL_GAP);
  const block = hugHeightToMeasured(
    buildTextBlock({
      text,
      region: { x: slotX, y: regionTop, w: slotW, h: availableAbovePct },
      fontFamily: design.body_font,
      fontWeight: 'bold',
      color: design.palette.text,
      align: 'center',
      tier,
      lineHeight: LINE_HEIGHTS.caption,
      minFontSize: FONT_SIZES.minimum,
    }),
  );
  block.y = Math.max(regionTop, barTopY - block.h - VALUE_LABEL_GAP);
  return block;
}

/** A category label in the bottom band under a slot. The bottom band can
 *  be squeezed (squeezed chart → small bottomPad) and the label can be
 *  verbose; permissive floor (FONT_SIZES.minimum) is the safety net so a
 *  long label doesn't pin-overflow Q1. */
function categoryLabel(
  text: string,
  slotX: number,
  slotW: number,
  plotBottom: number,
  bandHeight: number,
  design: DesignDirectionSpec,
): TextBlock {
  return buildTextBlock({
    text,
    region: {
      x: slotX,
      y: plotBottom + CAT_LABEL_GAP,
      w: slotW,
      h: Math.max(1, bandHeight - CAT_LABEL_GAP),
    },
    fontFamily: design.body_font,
    fontWeight: 'normal',
    color: design.palette.text_secondary,
    align: 'center',
    tier: FONT_SIZES.small,
    lineHeight: LINE_HEIGHTS.caption,
    minFontSize: FONT_SIZES.minimum,
  });
}

// ---------------------------------------------------------------------------
// Bar
// ---------------------------------------------------------------------------

function drawBar(
  region: Region,
  series: ChartSeriesPoint[],
  design: DesignDirectionSpec,
  zeroAnnotations: number[] = [],
): ChartDrawing {
  const ramp = resolveChartRamp(design.palette);
  const plot = computePlotArea(region, 0);
  const shapes: ShapeBlock[] = [];
  const blocks: TextBlock[] = [];
  const zeroSet = new Set(zeroAnnotations);

  const maxValue = Math.max(...series.map((p) => Math.max(0, p.value)), 0) || 1;
  const slotW = plot.w / series.length;
  const barW = slotW * BAR_FILL_RATIO;
  const bottomPad = region.y + region.h - plot.bottom;

  series.forEach((point, i) => {
    const slotX = plot.x + i * slotW;
    const value = Math.max(0, point.value);
    const barH = Math.min(plot.h, (value / maxValue) * plot.h);
    const barX = slotX + (slotW - barW) / 2;
    const barY = plot.bottom - barH;

    if (zeroSet.has(i)) {
      // Explicit zero: draw a visible baseline tick instead of an absent
      // bar so the eye reads "0 measured" rather than "data missing".
      shapes.push({
        type: 'rect',
        x: barX,
        y: plot.bottom - ZERO_TICK_HEIGHT,
        w: barW,
        h: ZERO_TICK_HEIGHT,
        fill: ramp[0],
      });
    } else {
      shapes.push({ type: 'rect', x: barX, y: barY, w: barW, h: barH, fill: ramp[0] });
    }
    blocks.push(
      valueLabel(formatChartValue(point.value, point.unit), slotX, slotW, barY, region.y, design),
    );
    blocks.push(categoryLabel(point.label, slotX, slotW, plot.bottom, bottomPad, design));
  });

  shapes.push(
    horizontalRule(plot.x, plot.bottom, plot.w, design.palette.text_secondary, BASELINE_STROKE, AXIS_OPACITY),
  );
  return { shapes, blocks };
}

// ---------------------------------------------------------------------------
// Line
// ---------------------------------------------------------------------------

function drawLine(
  region: Region,
  series: ChartSeriesPoint[],
  design: DesignDirectionSpec,
): ChartDrawing {
  const ramp = resolveChartRamp(design.palette);
  const plot = computePlotArea(region, 0);
  const shapes: ShapeBlock[] = [];
  const blocks: TextBlock[] = [];

  const maxValue = Math.max(...series.map((p) => Math.max(0, p.value)), 0) || 1;
  const n = series.length;
  // Inset by the point radius so end markers stay inside the region.
  const inset = (POINT_DIAMETER / 2 / 1920) * 100;
  const innerX = plot.x + inset;
  const innerW = Math.max(0, plot.w - 2 * inset);
  const bottomPad = region.y + region.h - plot.bottom;

  const xs = series.map((_, i) => (n === 1 ? innerX + innerW / 2 : innerX + (i / (n - 1)) * innerW));
  const ys = series.map((p) => plot.bottom - (Math.max(0, p.value) / maxValue) * plot.h);

  for (let i = 0; i < n - 1; i++) {
    shapes.push({
      type: 'line',
      x: xs[i]!,
      y: ys[i]!,
      x2: xs[i + 1]!,
      y2: ys[i + 1]!,
      w: Math.abs(xs[i + 1]! - xs[i]!),
      h: Math.abs(ys[i + 1]! - ys[i]!),
      stroke: ramp[0],
      strokeWidth: LINE_STROKE,
    });
  }

  const slotW = plot.w / n;
  series.forEach((point, i) => {
    const labelX = clampX(xs[i]! - slotW / 2, slotW, region);
    shapes.push(circleShape(xs[i]!, ys[i]!, POINT_DIAMETER, ramp[0]!));
    blocks.push(
      valueLabel(formatChartValue(point.value, point.unit), labelX, slotW, ys[i]!, region.y, design, FONT_SIZES.caption),
    );
    blocks.push(categoryLabel(point.label, labelX, slotW, plot.bottom, bottomPad, design));
  });

  shapes.push(
    horizontalRule(plot.x, plot.bottom, plot.w, design.palette.text_secondary, BASELINE_STROKE, AXIS_OPACITY),
  );
  return { shapes, blocks };
}

function clampX(x: number, w: number, region: Region): number {
  return Math.max(region.x, Math.min(x, region.x + region.w - w));
}

// ---------------------------------------------------------------------------
// Multi-stat (low-spread re-route target)
//
// Rendered inside the chart_data slide region when a clustered comparison
// (max/min < 1.5) would otherwise read as a flat zero-based bar. Each
// series point becomes a stat card — number / unit / label, stacked and
// hugged to its measured height the same way DATA_EMPHASIS columns are —
// so the slide reads as a comparison of discrete numbers, not a row of
// near-equal bars. The subject card carries the deck accent so the slide's
// argument stays visible at a glance; the others render in body text.
// ---------------------------------------------------------------------------

const MULTI_STAT_BLOCK_GAP = 1;

function drawMultiStat(
  region: Region,
  series: ChartSeriesPoint[],
  design: DesignDirectionSpec,
  subjectIndex: number,
): ChartDrawing {
  const shapes: ShapeBlock[] = [];
  const blocks: TextBlock[] = [];

  const n = series.length;
  if (n === 0) return { shapes, blocks };

  // Number tier shrinks as the count grows so 4 stats still breathe inside
  // the chart region width (the slide title sits above, not beside).
  const numberTier =
    n === 1 ? FONT_SIZES.displayLarge : n <= 3 ? FONT_SIZES.heading : FONT_SIZES.subheading;
  const labelTier = n <= 3 ? FONT_SIZES.caption : FONT_SIZES.small;
  const subjectColor = design.palette.accent;
  const otherColor = design.palette.text;
  const safeSubject = Math.max(0, Math.min(n - 1, subjectIndex));

  const slotW = region.w / n;
  series.forEach((point, i) => {
    const slotX = region.x + i * slotW;
    const isSubject = i === safeSubject;
    const numberColor = isSubject ? subjectColor : otherColor;
    const numberWeight = isSubject ? 'bold' : 'semibold';

    const stack: TextBlock[] = [];
    stack.push(
      hugHeightToMeasured(
        buildTextBlock({
          text: formatChartValue(point.value, null),
          region: { x: slotX, y: region.y, w: slotW, h: region.h },
          fontFamily: design.heading_font,
          fontWeight: numberWeight,
          color: numberColor,
          align: 'center',
          tier: numberTier,
          lineHeight: LINE_HEIGHTS.heading,
        }),
      ),
    );
    if (point.unit) {
      stack.push(
        hugHeightToMeasured(
          buildTextBlock({
            text: point.unit,
            region: { x: slotX, y: region.y, w: slotW, h: region.h },
            fontFamily: design.body_font,
            fontWeight: 'normal',
            color: design.palette.text_secondary,
            align: 'center',
            tier: FONT_SIZES.caption,
            lineHeight: LINE_HEIGHTS.body,
          }),
        ),
      );
    }
    stack.push(
      hugHeightToMeasured(
        buildTextBlock({
          text: point.label,
          region: { x: slotX, y: region.y, w: slotW, h: region.h },
          fontFamily: design.body_font,
          fontWeight: isSubject ? 'semibold' : 'normal',
          color: isSubject ? subjectColor : design.palette.text,
          align: 'center',
          tier: labelTier,
          lineHeight: LINE_HEIGHTS.body,
          minFontSize: FONT_SIZES.minimum,
        }),
      ),
    );

    // Centre the measured stack vertically within the chart region via the shared
    // engine. anchor:'center' reproduces the previous
    // region.y + max(0,(region.h - stackHeight)/2) placement; overflow:'truncate'
    // keeps scale=1 (the cards keep their own hugged heights — a global scale would
    // compress the tops while the blocks stayed full size and overlap). measure()
    // returns b.h (post-hug, includes the anti-clip epsilon) — NOT measuredHeightPct
    // — so the stack height matches the previous sum exactly. No emitBandCell/valign:
    // the cards read number→unit→label top-down inside the centred stack.
    const fit = fitMeasuredStack({
      region,
      items: stack.map((b) => ({ measure: () => b.h, gapAfter: MULTI_STAT_BLOCK_GAP })),
      overflow: 'truncate',
      anchor: 'center',
    });
    stack.forEach((b, k) => {
      b.y = fit.tops[k]!;
    });
    blocks.push(...stack);
  });

  return { shapes, blocks };
}

// ---------------------------------------------------------------------------
// Single value
// ---------------------------------------------------------------------------

function drawSingleValue(
  region: Region,
  series: ChartSeriesPoint[],
  design: DesignDirectionSpec,
): ChartDrawing {
  const ramp = resolveChartRamp(design.palette);
  const shapes: ShapeBlock[] = [];
  const blocks: TextBlock[] = [];
  const point = series[0]!;

  // Denominator rule: a second point is the target/max; otherwise a percent
  // value is out of 100; otherwise just the hero number, no progress bar.
  let max: number | null = null;
  let caption: string | null = null;
  if (series.length >= 2) {
    max = series[1]!.value;
    caption = `of ${formatChartValue(series[1]!.value, series[1]!.unit ?? point.unit)} · ${series[1]!.label}`;
  } else if (point.unit === '%') {
    max = 100;
  }

  const number = hugHeightToMeasured(
    buildTextBlock({
      text: formatChartValue(point.value, point.unit),
      region: { x: region.x, y: region.y + region.h * 0.14, w: region.w, h: region.h * 0.4 },
      fontFamily: design.heading_font,
      fontWeight: 'bold',
      color: design.palette.accent,
      align: 'center',
      tier: FONT_SIZES.displayLarge,
      lineHeight: LINE_HEIGHTS.heading,
    }),
  );
  blocks.push(number);

  const metric = hugHeightToMeasured(
    buildTextBlock({
      text: point.label,
      region: { x: region.x, y: number.y + number.h + 1, w: region.w, h: region.h * 0.14 },
      fontFamily: design.body_font,
      fontWeight: 'normal',
      color: design.palette.text,
      align: 'center',
      tier: FONT_SIZES.subheading,
      lineHeight: LINE_HEIGHTS.body,
      minFontSize: FONT_SIZES.minimum,
    }),
  );
  blocks.push(metric);

  if (max !== null && max > 0) {
    const ratio = Math.max(0, Math.min(1, point.value / max));
    const trackW = region.w * 0.6;
    const trackX = region.x + (region.w - trackW) / 2;
    const trackY = region.y + region.h * 0.66;
    const trackH = 2.4;
    shapes.push({ type: 'rect', x: trackX, y: trackY, w: trackW, h: trackH, fill: design.palette.surface, opacity: 0.5 });
    shapes.push({ type: 'rect', x: trackX, y: trackY, w: trackW * ratio, h: trackH, fill: ramp[0] });
    if (caption) {
      blocks.push(
        buildTextBlock({
          text: caption,
          region: { x: region.x, y: trackY + trackH + 1, w: region.w, h: region.h * 0.12 },
          fontFamily: design.body_font,
          fontWeight: 'normal',
          color: design.palette.text_secondary,
          align: 'center',
          tier: FONT_SIZES.caption,
          lineHeight: LINE_HEIGHTS.caption,
        }),
      );
    }
  }

  return { shapes, blocks };
}

// ---------------------------------------------------------------------------
// Grouped / stacked bar
// ---------------------------------------------------------------------------

function pointValues(point: ChartSeriesPoint, groupCount: number): number[] {
  const raw = point.values && point.values.length > 0 ? point.values : [point.value];
  return raw.slice(0, groupCount).map((v) => Math.max(0, v));
}

function drawGrouped(
  region: Region,
  groupLabels: string[],
  series: ChartSeriesPoint[],
  design: DesignDirectionSpec,
  stacked: boolean,
): ChartDrawing {
  const groupCount = Math.max(
    1,
    groupLabels.length || Math.max(...series.map((p) => p.values?.length ?? 1)),
  );
  const ramp = resolveChartRamp(design.palette, groupCount);
  const legendBand = groupLabels.length > 0 ? Math.min(LEGEND_BAND, region.h * 0.14) : 0;
  const plot = computePlotArea(region, legendBand);
  const shapes: ShapeBlock[] = [];
  const blocks: TextBlock[] = [];

  const allValues = series.map((p) => pointValues(p, groupCount));
  const maxValue = stacked
    ? Math.max(...allValues.map((vs) => vs.reduce((a, b) => a + b, 0)), 0) || 1
    : Math.max(...allValues.flat(), 0) || 1;

  const slotW = plot.w / series.length;
  const bottomPad = region.y + region.h - plot.bottom;
  const showValues = !stacked && series.length * groupCount <= GROUPED_LABEL_BUDGET;

  series.forEach((point, i) => {
    const slotX = plot.x + i * slotW;
    const vals = allValues[i]!;

    if (stacked) {
      const colW = slotW * BAR_FILL_RATIO;
      const colX = slotX + (slotW - colW) / 2;
      let cursorY = plot.bottom;
      vals.forEach((v, g) => {
        const segH = Math.min(plot.h, (v / maxValue) * plot.h);
        cursorY -= segH;
        shapes.push({ type: 'rect', x: colX, y: cursorY, w: colW, h: segH, fill: ramp[g % ramp.length]! });
      });
      const total = vals.reduce((a, b) => a + b, 0);
      blocks.push(valueLabel(formatChartValue(total, point.unit), slotX, slotW, cursorY, region.y, design, FONT_SIZES.caption));
    } else {
      const groupW = slotW * GROUP_SLOT_RATIO;
      const groupX = slotX + (slotW - groupW) / 2;
      const subW = groupW / groupCount;
      vals.forEach((v, g) => {
        const barH = Math.min(plot.h, (v / maxValue) * plot.h);
        const barX = groupX + g * subW;
        const barY = plot.bottom - barH;
        shapes.push({ type: 'rect', x: barX, y: barY, w: subW * 0.86, h: barH, fill: ramp[g % ramp.length]! });
        if (showValues) {
          blocks.push(valueLabel(formatChartValue(v, point.unit), barX, subW, barY, region.y, design, FONT_SIZES.small));
        }
      });
    }

    blocks.push(categoryLabel(point.label, slotX, slotW, plot.bottom, bottomPad, design));
  });

  if (legendBand > 0) {
    drawLegend(region, groupLabels, ramp, design, legendBand, shapes, blocks);
  }

  shapes.push(
    horizontalRule(plot.x, plot.bottom, plot.w, design.palette.text_secondary, BASELINE_STROKE, AXIS_OPACITY),
  );
  return { shapes, blocks };
}

function drawLegend(
  region: Region,
  groupLabels: string[],
  ramp: string[],
  design: DesignDirectionSpec,
  legendBand: number,
  shapes: ShapeBlock[],
  blocks: TextBlock[],
): void {
  const entryW = region.w / groupLabels.length;
  const swatchW = Math.min(1.2, entryW * 0.12);
  const swatchH = Math.min(2.2, legendBand * 0.5);
  const swatchY = region.y + (legendBand - swatchH) / 2;
  groupLabels.forEach((label, g) => {
    const entryX = region.x + g * entryW;
    shapes.push({
      type: 'rect',
      x: entryX,
      y: swatchY,
      w: swatchW,
      h: swatchH,
      fill: ramp[g % ramp.length]!,
    });
    blocks.push(
      buildTextBlock({
        text: label,
        region: { x: entryX + swatchW + 0.5, y: region.y, w: entryW - swatchW - 0.5, h: legendBand },
        fontFamily: design.body_font,
        fontWeight: 'normal',
        color: design.palette.text,
        align: 'left',
        tier: FONT_SIZES.small,
        lineHeight: LINE_HEIGHTS.caption,
        minFontSize: FONT_SIZES.minimum,
      }),
    );
  });
}
