import { describe, expect, it } from 'vitest';
import type { Region } from '../src/constants.js';
import { drawChart } from '../src/charts/draw-chart.js';
import {
  contrastRatio,
  formatChartValue,
  resolveChartRamp,
  shapeExtent,
} from '../src/charts/chart-style.js';
import type { DesignDirectionSpec, ShapeBlock, SlideContent, TextBlock } from '../src/types.js';
import { buildTestDeck } from './helpers.js';

const DESIGN: DesignDirectionSpec = buildTestDeck([]).design;
// The default chart box from SLIDE_REGIONS.chart_data (short title → no push-down).
const REGION: Region = { x: 5, y: 15, w: 65, h: 72 };
const EPS = 0.01;

function content(overrides: Partial<SlideContent>): SlideContent {
  return { title: 'Chart', ...overrides };
}

function expectWithinRegion(shapes: ShapeBlock[], blocks: TextBlock[], region: Region): void {
  for (const shape of shapes) {
    const e = shapeExtent(shape);
    expect(e.x).toBeGreaterThanOrEqual(region.x - EPS);
    expect(e.y).toBeGreaterThanOrEqual(region.y - EPS);
    expect(e.x + e.w).toBeLessThanOrEqual(region.x + region.w + EPS);
    expect(e.y + e.h).toBeLessThanOrEqual(region.y + region.h + EPS);
  }
  for (const b of blocks) {
    expect(b.x).toBeGreaterThanOrEqual(region.x - EPS);
    expect(b.y).toBeGreaterThanOrEqual(region.y - EPS);
    expect(b.x + b.w).toBeLessThanOrEqual(region.x + region.w + EPS);
    expect(b.y + b.h).toBeLessThanOrEqual(region.y + region.h + EPS);
  }
}

describe('drawChart — bar', () => {
  const series = [
    { label: 'Air', value: 8, unit: 'kW/rack' },
    { label: 'Liquid', value: 40, unit: 'kW/rack' },
    { label: 'sCO2', value: 120, unit: 'kW/rack' },
  ];

  it('draws one accent bar per point with a baseline, all within the region', () => {
    const result = drawChart(REGION, content({ chart_type: 'bar', chart_series: series }), DESIGN)!;
    expect(result).not.toBeNull();
    const bars = result.shapes.filter((s) => s.type === 'rect');
    expect(bars).toHaveLength(3);
    for (const bar of bars) expect(bar.fill).toBe(DESIGN.palette.accent);
    expect(result.shapes.some((s) => s.type === 'line')).toBe(true); // baseline
    expectWithinRegion(result.shapes, result.blocks, REGION);
  });

  it('scales bar height to the max value (zero-based)', () => {
    const result = drawChart(REGION, content({ chart_type: 'bar', chart_series: series }), DESIGN)!;
    const bars = result.shapes.filter((s) => s.type === 'rect');
    // 8 : 40 : 120 → heights in the same ratio.
    const heights = bars.map((b) => b.h);
    expect(heights[2] / heights[0]).toBeCloseTo(15, 1);
    expect(heights[1] / heights[0]).toBeCloseTo(5, 1);
  });

  it('renders value and category labels', () => {
    const result = drawChart(REGION, content({ chart_type: 'bar', chart_series: series }), DESIGN)!;
    expect(result.blocks.some((b) => b.text === '120 kW/rack')).toBe(true);
    expect(result.blocks.some((b) => b.text === 'Air')).toBe(true);
  });

  it('defaults to bar when chart_type is omitted', () => {
    const result = drawChart(REGION, content({ chart_series: series }), DESIGN)!;
    expect(result.shapes.filter((s) => s.type === 'rect')).toHaveLength(3);
  });
});

describe('drawChart — line', () => {
  const series = [
    { label: '2020', value: 12 },
    { label: '2021', value: 18 },
    { label: '2022', value: 30 },
    { label: '2023', value: 44 },
  ];

  it('draws N-1 diagonal segments and N point markers within the region', () => {
    const result = drawChart(REGION, content({ chart_type: 'line', chart_series: series }), DESIGN)!;
    const segments = result.shapes.filter(
      (s) => s.type === 'line' && s.x2 !== undefined && s.y2 !== undefined,
    );
    const points = result.shapes.filter((s) => s.type === 'circle');
    expect(segments).toHaveLength(3);
    expect(points).toHaveLength(4);
    expectWithinRegion(result.shapes, result.blocks, REGION);
  });

  it('places higher values higher on the slide (smaller y)', () => {
    const result = drawChart(REGION, content({ chart_type: 'line', chart_series: series }), DESIGN)!;
    const points = result.shapes.filter((s) => s.type === 'circle');
    // 2023 (value 44) sits above 2020 (value 12).
    expect(points[3]!.y).toBeLessThan(points[0]!.y);
  });
});

describe('drawChart — single_value', () => {
  it('renders a progress bar for a percent value out of 100', () => {
    const result = drawChart(
      REGION,
      content({ chart_type: 'single_value', chart_series: [{ label: 'Water saved', value: 94.4, unit: '%' }] }),
      DESIGN,
    )!;
    expect(result.blocks.some((b) => b.text === '94.4%')).toBe(true);
    const rects = result.shapes.filter((s) => s.type === 'rect');
    expect(rects.length).toBe(2); // track + fill
    expect(rects[1]!.w).toBeLessThan(rects[0]!.w); // fill is 94.4% of the track
    expectWithinRegion(result.shapes, result.blocks, REGION);
  });

  it('uses a second point as the target/denominator', () => {
    const result = drawChart(
      REGION,
      content({
        chart_type: 'single_value',
        chart_series: [
          { label: 'ARR', value: 1.04, unit: '$M' },
          { label: 'target', value: 5, unit: '$M' },
        ],
      }),
      DESIGN,
    )!;
    const rects = result.shapes.filter((s) => s.type === 'rect');
    expect(rects).toHaveLength(2);
    // fill ≈ 1.04/5 of the track.
    expect(rects[1]!.w / rects[0]!.w).toBeCloseTo(1.04 / 5, 2);
    expect(result.blocks.some((b) => b.text.includes('target'))).toBe(true);
  });

  it('shows just the hero number when there is no denominator', () => {
    const result = drawChart(
      REGION,
      content({ chart_type: 'single_value', chart_series: [{ label: 'Papers', value: 214, unit: 'M' }] }),
      DESIGN,
    )!;
    expect(result.shapes.filter((s) => s.type === 'rect')).toHaveLength(0);
    expect(result.blocks.some((b) => b.text === '214 M')).toBe(true);
  });
});

describe('drawChart — grouped / stacked bar', () => {
  const series = [
    { label: 'Air', value: 0, values: [6, 1.5, 0.5] },
    { label: 'Liquid', value: 0, values: [30, 8, 2] },
    { label: 'sCO2', value: 0, values: [90, 25, 5] },
  ];
  const groups = ['IT load', 'Cooling', 'Other'];

  it('grouped: draws one rect per (category × group) plus a legend, within bounds', () => {
    const result = drawChart(
      REGION,
      content({ chart_type: 'grouped_bar', chart_series: series, chart_group_labels: groups }),
      DESIGN,
    )!;
    const ramp = resolveChartRamp(DESIGN.palette, 3);
    const rects = result.shapes.filter((s) => s.type === 'rect');
    // 3 categories × 3 groups = 9 bars + 3 legend swatches.
    expect(rects).toHaveLength(12);
    // Each group colour from the ramp is used, and the three are distinct.
    expect(new Set(ramp).size).toBe(3);
    for (let g = 0; g < 3; g++) {
      expect(rects.some((r) => r.fill === ramp[g])).toBe(true);
    }
    expect(result.blocks.some((b) => b.text === 'IT load')).toBe(true);
    expectWithinRegion(result.shapes, result.blocks, REGION);
  });

  it('stacked: one column per category, segments stacked, within bounds', () => {
    const result = drawChart(
      REGION,
      content({ chart_type: 'stacked_bar', chart_series: series, chart_group_labels: groups }),
      DESIGN,
    )!;
    const rects = result.shapes.filter((s) => s.type === 'rect');
    // 9 segments + 3 legend swatches.
    expect(rects).toHaveLength(12);
    expectWithinRegion(result.shapes, result.blocks, REGION);
  });

  it('falls back to the scalar value when a point omits values', () => {
    const flat = [
      { label: 'A', value: 10 },
      { label: 'B', value: 20 },
    ];
    const result = drawChart(
      REGION,
      content({ chart_type: 'grouped_bar', chart_series: flat, chart_group_labels: ['only'] }),
      DESIGN,
    )!;
    const rects = result.shapes.filter((s) => s.type === 'rect');
    // 2 categories × 1 group = 2 bars + 1 legend swatch.
    expect(rects).toHaveLength(3);
  });
});

describe('drawChart — empty series', () => {
  it('returns null so the caller draws the placeholder', () => {
    expect(drawChart(REGION, content({ chart_type: 'bar' }), DESIGN)).toBeNull();
    expect(drawChart(REGION, content({ chart_type: 'bar', chart_series: [] }), DESIGN)).toBeNull();
  });
});

describe('drawChart — encoding guard', () => {
  it('renders a low-spread bar through the single_value path (one number, no bars)', () => {
    const pue = [
      { label: 'Air', value: 1.58, unit: 'PUE' },
      { label: 'Liquid', value: 1.25, unit: 'PUE' },
      { label: 'sCO2', value: 1.08, unit: 'PUE' },
    ];
    const result = drawChart(
      REGION,
      content({ chart_type: 'bar', chart_series: pue }),
      DESIGN,
    )!;
    // single_value with a single point and no progress-bar denominator
    // renders the headline number + label only (no rect shapes).
    expect(result.shapes.filter((s) => s.type === 'rect')).toHaveLength(0);
    expect(result.blocks.some((b) => b.text === '1.58 PUE')).toBe(true);
    // The other values still appear in the composite label so no data is lost.
    expect(result.blocks.some((b) => b.text.includes('Liquid') && b.text.includes('1.25'))).toBe(true);
  });

  it('renders a big-spread bar untouched (3 accent bars, baseline, value + category labels)', () => {
    const result = drawChart(
      REGION,
      content({
        chart_type: 'bar',
        chart_series: [
          { label: 'Air', value: 8, unit: 'kW/rack' },
          { label: 'Liquid', value: 40, unit: 'kW/rack' },
          { label: 'sCO2', value: 120, unit: 'kW/rack' },
        ],
      }),
      DESIGN,
    )!;
    const bars = result.shapes.filter((s) => s.type === 'rect');
    expect(bars).toHaveLength(3);
    expect(bars.every((b) => b.h > 0.5)).toBe(true); // no zero-ticks here
  });

  it('renders explicit zero-ticks for zero entries in a partial-zero bar', () => {
    const result = drawChart(
      REGION,
      content({
        chart_type: 'bar',
        chart_series: [
          { label: 'Air', value: 0, unit: '%' },
          { label: 'Liquid (low)', value: 0, unit: '%' },
          { label: 'Liquid (high)', value: 5, unit: '%' },
          { label: 'sCO2', value: 20, unit: '%' },
        ],
      }),
      DESIGN,
    )!;
    const bars = result.shapes.filter((s) => s.type === 'rect');
    // 4 columns total: 2 zero-ticks + 2 real bars.
    expect(bars).toHaveLength(4);
    const tinyBars = bars.filter((b) => b.h < 1);
    const realBars = bars.filter((b) => b.h >= 1);
    expect(tinyBars).toHaveLength(2);
    expect(realBars).toHaveLength(2);
    // Zero-ticks sit at the baseline (their bottoms align with the others' bottoms).
    const bottoms = bars.map((b) => b.y + b.h);
    const refBottom = bottoms[0]!;
    for (const b of bottoms) expect(b).toBeCloseTo(refBottom, 1);
    // Zero values still get their "0%" labels.
    expect(result.blocks.filter((b) => b.text === '0%')).toHaveLength(2);
  });
});

describe('chart-style helpers', () => {
  it('formatChartValue: separators, decimals, unit spacing', () => {
    expect(formatChartValue(120, 'kW/rack')).toBe('120 kW/rack');
    expect(formatChartValue(94.4, '%')).toBe('94.4%');
    expect(formatChartValue(1200, 'kW')).toBe('1,200 kW');
    expect(formatChartValue(1.1, 'PUE')).toBe('1.1 PUE');
    expect(formatChartValue(1000000)).toBe('1,000,000');
    expect(formatChartValue(35, '°C')).toBe('35°C');
    expect(formatChartValue(1.08)).toBe('1.08');
  });

  it('resolveChartRamp: accent first, requested count of legible colours', () => {
    const ramp = resolveChartRamp(DESIGN.palette);
    expect(ramp).toHaveLength(4);
    expect(ramp[0]).toBe(DESIGN.palette.accent);
    for (const c of ramp) expect(c).toMatch(/^#[0-9A-F]{6}$/);
    // Supporting colours clear the 3:1 graphical-object contrast guard.
    for (let i = 1; i < ramp.length; i++) {
      expect(contrastRatio(ramp[i]!, DESIGN.palette.background)).toBeGreaterThanOrEqual(3);
    }
    // Count-aware: never reuses a colour up to the schema cap of 6 groups.
    const six = resolveChartRamp(DESIGN.palette, 6);
    expect(six).toHaveLength(6);
    expect(new Set(six).size).toBe(6);
  });

  it('shapeExtent: resolves a diagonal line to its bounding box', () => {
    const line: ShapeBlock = { type: 'line', x: 10, y: 80, x2: 20, y2: 40, w: 10, h: 40 };
    expect(shapeExtent(line)).toEqual({ x: 10, y: 40, w: 10, h: 40 });
  });
});
