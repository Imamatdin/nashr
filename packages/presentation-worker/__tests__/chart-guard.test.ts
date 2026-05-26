import { describe, expect, it } from 'vitest';
import {
  LOW_SPREAD_THRESHOLD,
  validateChartEncoding,
} from '../src/charts/chart-guard.js';
import type { SlideContent } from '../src/types.js';

function content(overrides: Partial<SlideContent>): SlideContent {
  return { title: 'Chart', ...overrides };
}

describe('validateChartEncoding — pass-through cases', () => {
  it('does not touch a big-spread bar (max/min >= 1.5)', () => {
    const decision = validateChartEncoding(
      content({
        chart_type: 'bar',
        chart_series: [
          { label: 'Air', value: 8, unit: 'kW/rack' },
          { label: 'Liquid', value: 40, unit: 'kW/rack' },
          { label: 'sCO2', value: 120, unit: 'kW/rack' },
        ],
      }),
    );
    expect(decision.chartType).toBe('bar');
    expect(decision.reroutes).toEqual([]);
    expect(decision.zeroAnnotations).toEqual([]);
    expect(decision.series).toHaveLength(3);
  });

  it('does not touch a single-value chart', () => {
    const decision = validateChartEncoding(
      content({
        chart_type: 'single_value',
        chart_series: [{ label: 'Water saved', value: 94.4, unit: '%' }],
      }),
    );
    expect(decision.chartType).toBe('single_value');
    expect(decision.reroutes).toEqual([]);
  });

  it('does not touch a line chart even if its values are clustered', () => {
    const decision = validateChartEncoding(
      content({
        chart_type: 'line',
        chart_series: [
          { label: '2020', value: 1.08 },
          { label: '2021', value: 1.12 },
          { label: '2022', value: 1.15 },
        ],
      }),
    );
    expect(decision.chartType).toBe('line');
    expect(decision.reroutes).toEqual([]);
  });

  it('returns the original chart_type when chart_series is empty', () => {
    const decision = validateChartEncoding(content({ chart_type: 'bar', chart_series: [] }));
    expect(decision.chartType).toBe('bar');
    expect(decision.reroutes).toEqual([]);
  });

  it('does not touch a grouped bar (out-of-scope, deferred to v2)', () => {
    const decision = validateChartEncoding(
      content({
        chart_type: 'grouped_bar',
        chart_series: [
          { label: 'Air', value: 0, values: [0, 1.5, 0.5] },
          { label: 'Liquid', value: 0, values: [30, 8, 2] },
        ],
        chart_group_labels: ['IT load', 'Cooling', 'Other'],
      }),
    );
    expect(decision.chartType).toBe('grouped_bar');
    expect(decision.reroutes).toEqual([]);
  });
});

describe('validateChartEncoding — low-spread re-route', () => {
  it('re-routes a 3-point clustered ratio (PUE 1.08/1.25/1.58) to single_value', () => {
    const decision = validateChartEncoding(
      content({
        chart_type: 'bar',
        chart_series: [
          { label: 'Air', value: 1.58, unit: 'PUE' },
          { label: 'Liquid', value: 1.25, unit: 'PUE' },
          { label: 'sCO2', value: 1.08, unit: 'PUE' },
        ],
      }),
    );
    expect(decision.chartType).toBe('single_value');
    expect(decision.series).toHaveLength(1);
    // The first point becomes the headline (preserves editorial ordering).
    expect(decision.series[0]!.value).toBe(1.58);
    expect(decision.series[0]!.unit).toBe('PUE');
    expect(decision.series[0]!.label).toContain('Air');
    expect(decision.series[0]!.label).toContain('Liquid');
    expect(decision.series[0]!.label).toContain('sCO2');
    expect(decision.reroutes).toHaveLength(1);
    expect(decision.reroutes[0]).toMatchObject({
      from: 'bar',
      to: 'single_value',
      reason: 'low_spread',
    });
    // detail string includes the formatted ratio (1.58 / 1.08 = 1.46…).
    expect(decision.reroutes[0]!.detail).toContain('1.46');
  });

  it('re-routes a 2-point clustered ratio (PUE 1.08 vs 1.58) to single_value', () => {
    const decision = validateChartEncoding(
      content({
        chart_type: 'bar',
        chart_series: [
          { label: 'Air', value: 1.58, unit: 'PUE' },
          { label: 'sCO2', value: 1.08, unit: 'PUE' },
        ],
      }),
    );
    expect(decision.chartType).toBe('single_value');
    expect(decision.series).toHaveLength(1);
    expect(decision.series[0]!.value).toBe(1.58);
    expect(decision.reroutes[0]!.reason).toBe('low_spread');
  });

  it('does NOT re-route when max/min sits right at the threshold', () => {
    // Threshold is strict (< 1.5), so a ratio of exactly 1.5 is allowed.
    const decision = validateChartEncoding(
      content({
        chart_type: 'bar',
        chart_series: [
          { label: 'A', value: 10 },
          { label: 'B', value: 15 },
        ],
      }),
    );
    expect(LOW_SPREAD_THRESHOLD).toBe(1.5);
    expect(decision.chartType).toBe('bar');
    expect(decision.reroutes).toEqual([]);
  });

  it('does not re-route when the spread is healthy (8/40/120 = 15x)', () => {
    const decision = validateChartEncoding(
      content({
        chart_type: 'bar',
        chart_series: [
          { label: 'Air', value: 8 },
          { label: 'Liquid', value: 40 },
          { label: 'sCO2', value: 120 },
        ],
      }),
    );
    expect(decision.chartType).toBe('bar');
    expect(decision.reroutes).toEqual([]);
  });

  it('does not re-route when chart_type was already not "bar"', () => {
    // Even if values are clustered, only the bar default is guarded.
    const decision = validateChartEncoding(
      content({
        chart_type: 'single_value',
        chart_series: [
          { label: 'Air', value: 1.58, unit: 'PUE' },
          { label: 'sCO2', value: 1.08, unit: 'PUE' },
        ],
      }),
    );
    expect(decision.chartType).toBe('single_value');
    expect(decision.reroutes).toEqual([]);
  });
});

describe('validateChartEncoding — zero annotation', () => {
  it('annotates partial zeros in a bar without re-routing', () => {
    // Heat recovery 0 / 0 / 5 / 20% — the sCO2 deck slide 15 case.
    const decision = validateChartEncoding(
      content({
        chart_type: 'bar',
        chart_series: [
          { label: 'Air', value: 0, unit: '%' },
          { label: 'Liquid (low-grade)', value: 0, unit: '%' },
          { label: 'Liquid (high-grade)', value: 5, unit: '%' },
          { label: 'sCO2', value: 20, unit: '%' },
        ],
      }),
    );
    expect(decision.chartType).toBe('bar');
    expect(decision.zeroAnnotations).toEqual([0, 1]);
    expect(decision.reroutes).toHaveLength(1);
    expect(decision.reroutes[0]).toMatchObject({
      from: 'bar',
      to: 'bar_with_zero_annotation',
      reason: 'zero_in_bar',
    });
    expect(decision.reroutes[0]!.detail).toContain('2/4');
  });

  it('does not act when EVERY value is zero (empty-series fallback handles it)', () => {
    const decision = validateChartEncoding(
      content({
        chart_type: 'bar',
        chart_series: [
          { label: 'A', value: 0 },
          { label: 'B', value: 0 },
        ],
      }),
    );
    expect(decision.chartType).toBe('bar');
    expect(decision.zeroAnnotations).toEqual([]);
    expect(decision.reroutes).toEqual([]);
  });

  it('does not annotate when there are no zeros at all', () => {
    const decision = validateChartEncoding(
      content({
        chart_type: 'bar',
        chart_series: [
          { label: 'A', value: 8 },
          { label: 'B', value: 40 },
        ],
      }),
    );
    expect(decision.zeroAnnotations).toEqual([]);
    expect(decision.reroutes).toEqual([]);
  });
});
