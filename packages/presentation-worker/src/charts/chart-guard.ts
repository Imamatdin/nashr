/**
 * Chart-encoding guard — the deterministic backstop that keeps a misleading
 * `chart_type` from ever reaching the user.
 *
 * Runs BEFORE drawChart. Independent of the model: even if the editorial
 * pass picks the wrong encoding for the data's shape, this layer either
 * re-routes the chart type or annotates the draw so the result reads
 * honestly. Two failure modes are caught:
 *
 *   1. LOW-SPREAD BAR — `chart_type: 'bar'` whose values are all non-zero
 *      and clustered (max/min < LOW_SPREAD_THRESHOLD). A zero-based bar
 *      compresses such values into near-equal columns and hides the very
 *      difference the slide exists to show. We RE-ROUTE to `single_value`:
 *      the first series point becomes the headline (preserving editorial
 *      ordering), and the remaining points fold into a subtitle so no
 *      data is lost. The richer fix — moving the slide to `DATA_EMPHASIS`
 *      — is upstream in the editorial prompt's DATA-SHAPE → ENCODING
 *      rules; this guard is the backstop when editorial fails to apply
 *      them.
 *
 *   2. ZEROS IN BAR — `chart_type: 'bar'` with some (but not all) values
 *      equal to zero would otherwise draw the zero columns as ABSENT
 *      bars, which reads as missing data, not as the deliberate "0" the
 *      slide intends (e.g. heat-recovery 0 / 0 / 5 / 20%). We keep the
 *      chart but flag those indices so drawBar draws an explicit baseline
 *      tick at each zero position — the zero becomes a visible
 *      observation, not a gap.
 *
 * The guard is a pure function: it makes decisions, the caller (drawChart)
 * emits the log line and the renderer draws the consequence. That keeps it
 * unit-testable in isolation and lets the worker's existing
 * `process.stderr` pipeline carry the observability.
 *
 * Threshold: max/min < 1.5 is the perceptual-flatness floor. Cleveland's
 * graphical-perception work (1985) shows the eye struggles to read bar
 * differences below ~1.5x; tune here if the threshold proves loose in
 * production but never silently — every re-route is logged.
 *
 * OUT OF SCOPE (deferred, intentional): grouped/stacked bars with zero
 * sub-values. A zero sub-bar reads as missing data the same way a zero
 * primary bar does, but a partial group implies SOMETHING was measured,
 * so the editorial DATA-SHAPE → ENCODING rule carries that load for now.
 * If the model still mis-routes grouped charts with zeros, extend this
 * guard in a follow-up — the seam is here.
 */

import { formatChartValue } from './chart-style.js';
import type { ChartSeriesPoint, ChartType, SlideContent } from '../types.js';

/** max/min ratio below which clustered bars read as visually flat. */
export const LOW_SPREAD_THRESHOLD = 1.5;

/** Re-route target for the zero-annotation path; not a real ChartType. */
export type GuardTarget = ChartType | 'bar_with_zero_annotation';

export interface ChartReroute {
  from: ChartType;
  to: GuardTarget;
  reason: 'low_spread' | 'zero_in_bar';
  detail: string;
}

export interface EncodingDecision {
  /** Chart type to actually render (may differ from content.chart_type). */
  chartType: ChartType;
  /** Series to render (may be reshaped from the input by a re-route). */
  series: ChartSeriesPoint[];
  /** Group labels carried through unchanged; the guard never touches them. */
  groupLabels: string[];
  /**
   * Indices into the OUTPUT series whose values are zero and need an
   * explicit baseline marker. Populated only for the zero-in-bar case.
   */
  zeroAnnotations: number[];
  /** One record per decision the guard made; the caller logs these. */
  reroutes: ChartReroute[];
}

/**
 * Decide what to draw for a CHART_DATA slide.
 *
 * Pure function. Returns the original content's encoding when nothing is
 * suspect, or a re-routed encoding (with one re-route record per decision)
 * when the data's shape would be misrepresented.
 */
export function validateChartEncoding(content: SlideContent): EncodingDecision {
  const initialType: ChartType = content.chart_type ?? 'bar';
  const series = content.chart_series ?? [];
  const groupLabels = content.chart_group_labels ?? [];

  const passthrough: EncodingDecision = {
    chartType: initialType,
    series,
    groupLabels,
    zeroAnnotations: [],
    reroutes: [],
  };

  // Nothing to plot, or a non-bar chart — let the renderer's existing path
  // handle it (placeholder for empty, full draw for line / single_value /
  // grouped / stacked).
  if (series.length === 0) return passthrough;
  if (initialType !== 'bar') return passthrough;

  const zeroIndices: number[] = [];
  series.forEach((point, i) => {
    if (point.value === 0) zeroIndices.push(i);
  });
  const allZero = zeroIndices.length === series.length;

  // CASE B — zeros mixed with non-zeros: annotate, keep the chart.
  // A bar of height zero draws as nothing; the eye reads it as missing
  // data. Marking those positions as zero-annotations lets drawBar render
  // an explicit baseline tick so the zero reads as a measurement.
  if (zeroIndices.length > 0 && !allZero) {
    return {
      chartType: 'bar',
      series,
      groupLabels,
      zeroAnnotations: zeroIndices,
      reroutes: [
        {
          from: 'bar',
          to: 'bar_with_zero_annotation',
          reason: 'zero_in_bar',
          detail:
            `${zeroIndices.length}/${series.length} value(s) are zero ` +
            `(at index ${zeroIndices.join(', ')}); ` +
            `annotating with an explicit baseline tick so each zero reads ` +
            `as an intentional observation, not a missing bar.`,
        },
      ],
    };
  }

  // CASE A — all non-zero, low spread: re-route to single_value.
  // We headline the FIRST series point (preserving the editorial pass's
  // ordering — series[0] is the slide's narrative anchor) and fold the
  // rest into the subtitle so no value is lost on the slide. The
  // structurally cleaner fix (slide_type → DATA_EMPHASIS) lives in
  // editorial; this is the renderer-side backstop.
  if (zeroIndices.length === 0) {
    const values = series.map((p) => p.value);
    const max = Math.max(...values);
    const min = Math.min(...values);
    if (min > 0 && max / min < LOW_SPREAD_THRESHOLD) {
      const head = series[0]!;
      const others = series.slice(1);
      const othersLabel = others
        .map((p) => `${p.label} ${formatChartValue(p.value, p.unit ?? head.unit ?? null)}`)
        .join(' · ');
      const reshapedLabel = othersLabel
        ? `${head.label} (vs. ${othersLabel})`
        : head.label;
      const reshaped: ChartSeriesPoint[] = [
        { label: reshapedLabel, value: head.value, unit: head.unit ?? null },
      ];
      return {
        chartType: 'single_value',
        series: reshaped,
        groupLabels: [],
        zeroAnnotations: [],
        reroutes: [
          {
            from: 'bar',
            to: 'single_value',
            reason: 'low_spread',
            detail:
              `max/min ratio ${(max / min).toFixed(2)} below ` +
              `threshold ${LOW_SPREAD_THRESHOLD}; a zero-based bar would ` +
              `compress these clustered values into near-equal columns. ` +
              `Headlining "${head.label}" = ${formatChartValue(head.value, head.unit ?? null)}` +
              (othersLabel ? `; subtitle carries the rest (${othersLabel}).` : '.'),
          },
        ],
      };
    }
  }

  return passthrough;
}
