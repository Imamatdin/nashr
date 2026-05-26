import { describe, expect, it } from 'vitest';
import {
  LINE_MIN_POINTS,
  LOW_SPREAD_THRESHOLD,
  pickSubjectIndex,
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
    expect(decision.subjectIndex).toBeNull();
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

  it('does not touch a 3+ point line chart even if its values are clustered', () => {
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
    expect(LINE_MIN_POINTS).toBe(3);
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

describe('validateChartEncoding — low-spread re-route to multi_stat', () => {
  it('re-routes a clustered PUE comparison to multi_stat, all points preserved', () => {
    const decision = validateChartEncoding(
      content({
        title: 'sCO₂ Achieves PUE 1.08',
        chart_type: 'bar',
        chart_series: [
          { label: 'Air', value: 1.57, unit: 'PUE' },
          { label: 'Liquid', value: 1.25, unit: 'PUE' },
          { label: 'sCO2', value: 1.08, unit: 'PUE' },
        ],
      }),
    );
    // The comparison is preserved — every point reaches the renderer.
    expect(decision.chartType).toBe('multi_stat');
    expect(decision.series).toHaveLength(3);
    expect(decision.series.map((p) => p.value)).toEqual([1.57, 1.25, 1.08]);
    // The subject is sCO2 (matched by the title's subscript-2 form against
    // the ASCII series label via NFKD normalisation). NOT series[0] (Air),
    // the bug this rewrite exists to fix.
    expect(decision.subjectIndex).toBe(2);
    expect(decision.reroutes).toHaveLength(1);
    expect(decision.reroutes[0]).toMatchObject({
      from: 'bar',
      to: 'multi_stat',
      reason: 'low_spread',
    });
    expect(decision.reroutes[0]!.detail).toContain('sCO2');
    expect(decision.reroutes[0]!.detail).toContain('1.08');
  });

  it('lower-is-better metric without a subject token picks the min', () => {
    // No series label appears in the title; the polarity lexicon ("PUE")
    // forces lower-better, so the subject is argmin(series) = sCO2.
    const decision = validateChartEncoding(
      content({
        title: 'Cooling efficiency compared (PUE)',
        chart_type: 'bar',
        chart_series: [
          { label: 'Air', value: 1.57, unit: 'PUE' },
          { label: 'Liquid', value: 1.25, unit: 'PUE' },
          { label: 'sCO2', value: 1.08, unit: 'PUE' },
        ],
      }),
    );
    expect(decision.chartType).toBe('multi_stat');
    expect(decision.subjectIndex).toBe(2);
  });

  it('higher-is-better metric without a subject token picks the max', () => {
    // Efficiency is higher-better; argmax = the 0.91 point at index 2.
    const decision = validateChartEncoding(
      content({
        title: 'Cooling efficiency compared',
        chart_type: 'bar',
        chart_series: [
          { label: 'Air', value: 0.78 },
          { label: 'Liquid', value: 0.85 },
          { label: 'sCO2', value: 0.91 },
        ],
      }),
    );
    expect(decision.chartType).toBe('multi_stat');
    expect(decision.subjectIndex).toBe(2);
  });

  it('falls back to argmax when no title token and no polarity match', () => {
    // No subject token in title, no polarity word — argmax (the biggest
    // number is the natural hero). Multi-character distinct labels so the
    // title-match path is reachable but doesn't fire on a generic title.
    const decision = validateChartEncoding(
      content({
        title: 'Benchmarks',
        chart_type: 'bar',
        chart_series: [
          { label: 'Alpha', value: 13, unit: 'score' },
          { label: 'Bravo', value: 12, unit: 'score' },
          { label: 'Charlie', value: 10, unit: 'score' },
        ],
      }),
    );
    expect(decision.chartType).toBe('multi_stat');
    expect(decision.subjectIndex).toBe(0); // 13 is the largest
  });

  it('re-routes a 2-point clustered ratio (PUE 1.08 vs 1.25) to multi_stat', () => {
    const decision = validateChartEncoding(
      content({
        title: 'Liquid vs sCO2 PUE',
        chart_type: 'bar',
        chart_series: [
          { label: 'Liquid', value: 1.25, unit: 'PUE' },
          { label: 'sCO2', value: 1.08, unit: 'PUE' },
        ],
      }),
    );
    expect(decision.chartType).toBe('multi_stat');
    expect(decision.series).toHaveLength(2);
    // Title says "Liquid vs sCO2" — sCO2 appears AFTER Liquid, so the
    // subject picker prefers it (the "answer" sits after the "vs").
    expect(decision.subjectIndex).toBe(1);
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

  it('does not re-route a non-bar chart even with clustered values', () => {
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

describe('validateChartEncoding — line with too few points', () => {
  it('re-routes a 2-point line to bar (the categories are discrete, no trend)', () => {
    // Payback Liquid 5yr vs sCO2 3.2yr — two discrete categories, ratio
    // 5/3.2 = 1.5625 is above the low-spread threshold, so after the
    // line→bar re-route we land on a clean two-bar chart.
    const decision = validateChartEncoding(
      content({
        title: 'sCO2 cuts payback to 3.2 years',
        chart_type: 'line',
        chart_series: [
          { label: 'Liquid', value: 5, unit: 'yr' },
          { label: 'sCO2', value: 3.2, unit: 'yr' },
        ],
      }),
    );
    expect(decision.chartType).toBe('bar');
    expect(decision.series).toHaveLength(2);
    expect(decision.reroutes).toHaveLength(1);
    expect(decision.reroutes[0]).toMatchObject({
      from: 'line',
      to: 'bar',
      reason: 'line_too_few_points',
    });
  });

  it('cascades line<3 → bar → multi_stat when the two values are low-spread', () => {
    // 1.0 vs 1.2 has ratio 1.2 — line is wrong (2 discrete categories) AND
    // the bar would be flat. Both re-routes fire in order; the final
    // chartType is multi_stat with the subject picked.
    const decision = validateChartEncoding(
      content({
        title: 'Liquid vs sCO2 PUE',
        chart_type: 'line',
        chart_series: [
          { label: 'Liquid', value: 1.2, unit: 'PUE' },
          { label: 'sCO2', value: 1.0, unit: 'PUE' },
        ],
      }),
    );
    expect(decision.chartType).toBe('multi_stat');
    expect(decision.series).toHaveLength(2);
    // Both re-routes logged: line→bar, then bar→multi_stat.
    expect(decision.reroutes.map((r) => r.reason)).toEqual([
      'line_too_few_points',
      'low_spread',
    ]);
    expect(decision.subjectIndex).toBe(1); // sCO2 named in title, last position
  });

  it('leaves a 3-point line alone (genuine sequence)', () => {
    const decision = validateChartEncoding(
      content({
        chart_type: 'line',
        chart_series: [
          { label: '2020', value: 12 },
          { label: '2021', value: 18 },
          { label: '2022', value: 30 },
        ],
      }),
    );
    expect(decision.chartType).toBe('line');
    expect(decision.reroutes).toEqual([]);
  });

  it('cascades a degenerate 1-point line through line→bar→multi_stat', () => {
    // A 1-point line is a degenerate case (no slope, no comparison). The
    // line→bar re-route fires; then the bar's max/min = 1/1 = 1, which is
    // below the 1.5 spread threshold so the low-spread guard fires too,
    // landing on a single-card multi_stat. Both re-routes are logged.
    const decision = validateChartEncoding(
      content({
        chart_type: 'line',
        chart_series: [{ label: '2023', value: 44 }],
      }),
    );
    expect(decision.chartType).toBe('multi_stat');
    expect(decision.series).toHaveLength(1);
    expect(decision.subjectIndex).toBe(0);
    expect(decision.reroutes.map((r) => r.reason)).toEqual([
      'line_too_few_points',
      'low_spread',
    ]);
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

describe('pickSubjectIndex — Unicode + polarity', () => {
  const series = [
    { label: 'Air', value: 1.57, unit: 'PUE' },
    { label: 'Liquid', value: 1.25, unit: 'PUE' },
    { label: 'sCO2', value: 1.08, unit: 'PUE' },
  ];

  it('matches subscript-2 in the title against ASCII series label', () => {
    expect(pickSubjectIndex('sCO₂ Achieves PUE 1.08', series)).toBe(2);
  });

  it('matches the LAST label in "X vs Y" patterns', () => {
    expect(pickSubjectIndex('Air vs sCO2: cooling overhead', series)).toBe(2);
  });

  it('case-insensitive — uppercase title with lowercase label still matches', () => {
    expect(pickSubjectIndex('SCO2 BEATS THE FIELD', series)).toBe(2);
  });

  it('falls back to polarity argmin for lower-better metrics', () => {
    expect(pickSubjectIndex('Cooling PUE compared', series)).toBe(2);
  });

  it('title-token match WINS over polarity (rule priority lock)', () => {
    // Polarity (PUE → lower-better) would pick sCO2 at index 2; the title
    // names "Air" so title-match (a) wins and the subject is Air at index
    // 0. Without this test, reordering the picker's rules so polarity ran
    // first would silently pass every other case — they all agree by
    // coincidence in the PUE-cooling fixture.
    expect(pickSubjectIndex('Air still leads on PUE', series)).toBe(0);
  });

  it('falls back to argmax when no title match and no polarity word', () => {
    // Need a series with NO polarity hint in label/unit — the PUE-tagged
    // shared fixture would force lower-better. Argmax = 13 at index 0.
    const neutral = [
      { label: 'Alpha', value: 13, unit: 'pts' },
      { label: 'Bravo', value: 12, unit: 'pts' },
      { label: 'Charlie', value: 10, unit: 'pts' },
    ];
    expect(pickSubjectIndex('Benchmarks', neutral)).toBe(0);
  });

  it('ignores single-character labels when title-matching', () => {
    // "A" / "B" / "C" labels would otherwise hit countless titles.
    const abc = [
      { label: 'A', value: 10 },
      { label: 'B', value: 12 },
      { label: 'C', value: 13 },
    ];
    // Title contains "a" (in "Cooling efficiency"), but a 1-char label is
    // not allowed as a needle; falls through to higher-is-better polarity
    // (efficiency) → argmax = C at index 2.
    expect(pickSubjectIndex('Cooling efficiency', abc)).toBe(2);
  });

  it('returns 0 for an empty or single-point series', () => {
    expect(pickSubjectIndex('whatever', [])).toBe(0);
    expect(pickSubjectIndex('whatever', [{ label: 'Only', value: 1 }])).toBe(0);
  });
});
