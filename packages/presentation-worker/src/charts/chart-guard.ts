/**
 * Chart-encoding guard — the deterministic backstop that keeps a misleading
 * `chart_type` from ever reaching the user.
 *
 * Runs BEFORE drawChart. Independent of the model: even if the editorial
 * pass picks the wrong encoding for the data's shape, this layer re-routes
 * the chart so the result reads honestly. Failure modes caught:
 *
 *   1. LOW-SPREAD COMPARISON — `chart_type: 'bar'` whose values are all
 *      non-zero and clustered (max/min < LOW_SPREAD_THRESHOLD). A zero-based
 *      bar compresses such values into near-equal columns and hides the very
 *      difference the slide exists to show. We RE-ROUTE to a chart-internal
 *      `multi_stat` view: all points are kept (the gap IS the story), but
 *      rendered as stat cards rather than bars, with the SUBJECT point
 *      highlighted in the deck accent. Falling back to a single number
 *      threw away the comparison and — worse — frequently picked the WRONG
 *      number (series[0] was usually the value the slide argued AGAINST).
 *      Single-value is reserved for cases where there is genuinely one
 *      number (one-point series).
 *
 *   2. LINE WITH < 3 POINTS — `chart_type: 'line'` over two (or fewer)
 *      categories implies a continuous trend that does not exist. Two
 *      discrete categories (e.g. payback 5yr vs 3.2yr) get RE-ROUTED to
 *      `bar`, which is then re-evaluated against the bar guards (so a
 *      low-spread two-bar comparison cascades all the way to `multi_stat`).
 *      Both re-routes are logged.
 *
 *   3. ZEROS IN BAR — `chart_type: 'bar'` with some (but not all) values
 *      equal to zero would otherwise draw the zero columns as ABSENT
 *      bars, which reads as missing data, not as the deliberate "0" the
 *      slide intends (e.g. heat-recovery 0 / 0 / 5 / 20%). We keep the
 *      chart but flag those indices so drawBar draws an explicit baseline
 *      tick at each zero position — the zero becomes a visible
 *      observation, not a gap.
 *
 * SUBJECT PICKER. The multi_stat re-route must highlight the value the
 * slide is actually about — the bug that motivated this rewrite was
 * `series[0]` becoming the headline when the slide titled "sCO₂ Achieves
 * PUE 1.08" was about sCO2 but `series[0]` was Air. The picker is, in
 * priority order:
 *   (a) Title-token match — the series point whose normalised label
 *       appears in the normalised title. Normalisation is NFKD-aware so
 *       subscript / superscript / accented forms ("sCO₂" vs "sCO2") match.
 *       When several labels match, the LAST occurrence wins ("Air vs sCO2"
 *       → sCO2, not Air).
 *   (b) Metric polarity — when the title or unit lexicon names a
 *       lower-is-better metric (PUE, cost, latency, payback, downtime,
 *       footprint, emissions, error, loss, risk) pick `min`. When it
 *       names a higher-is-better metric (efficiency, savings, recovery,
 *       throughput, capacity, density, performance, yield) pick `max`.
 *   (c) Fallback — `argmax` (the biggest number is the natural hero).
 * The picker is intentionally English-biased; non-English titles fall
 * through (a) and rely on (b)/(c). Editorial prompt guidance asks the
 * model to put the subject token in the title, which carries (a) on the
 * common case.
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
 */

import { formatChartValue } from './chart-style.js';
import type { ChartSeriesPoint, ChartType, SlideContent } from '../types.js';

/** max/min ratio below which clustered bars read as visually flat. */
export const LOW_SPREAD_THRESHOLD = 1.5;

/** Minimum number of points a `line` chart needs to read as a trend. */
export const LINE_MIN_POINTS = 3;

/**
 * Render-internal chart type. Extends the public `ChartType` with the
 * `multi_stat` mode used by the low-spread re-route. drawChart switches
 * on this; nothing else does.
 */
export type ChartRenderType = ChartType | 'multi_stat';

/** Re-route targets that may appear in a {@link ChartReroute} record. */
export type GuardTarget = ChartRenderType | 'bar_with_zero_annotation';

export type ChartRerouteReason =
  | 'low_spread'
  | 'zero_in_bar'
  | 'line_too_few_points';

export interface ChartReroute {
  from: ChartType;
  to: GuardTarget;
  reason: ChartRerouteReason;
  detail: string;
}

export interface EncodingDecision {
  /** Chart type to actually render (may differ from content.chart_type). */
  chartType: ChartRenderType;
  /** Series to render (may be reshaped from the input by a re-route). */
  series: ChartSeriesPoint[];
  /** Group labels carried through unchanged; the guard never touches them. */
  groupLabels: string[];
  /**
   * Indices into the OUTPUT series whose values are zero and need an
   * explicit baseline marker. Populated only for the zero-in-bar case.
   */
  zeroAnnotations: number[];
  /**
   * Index into the OUTPUT series whose stat card is the subject of the
   * slide. Populated only for the multi_stat re-route so drawMultiStat
   * can highlight it in the deck accent. `null` for every other path.
   */
  subjectIndex: number | null;
  /** One record per decision the guard made; the caller logs these. */
  reroutes: ChartReroute[];
}

// ---------------------------------------------------------------------------
// Subject picker — Unicode-aware title-token match, then polarity, then max.
// ---------------------------------------------------------------------------

/**
 * Canonicalise a label/title fragment so an NFKD-decomposable form (subscript
 * 2, accented vowels) matches its ASCII counterpart. Lower-cases and strips
 * everything that is not an alphanumeric so "sCO₂" → "sco2" and "sCO2" →
 * "sco2" both reduce to the same haystack/needle.
 */
function normaliseForMatch(s: string): string {
  return s
    .normalize('NFKD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]/g, '');
}

/**
 * Metric-polarity lexicon. Plain substrings (matched against the normalised
 * title + each series label/unit). Lower-better keys reward the smallest
 * value; higher-better keys reward the largest. The list is small and
 * English-only by design — false positives are worse than misses, and the
 * (c) fallback (argmax) is a sensible default for unrecognised metrics.
 */
const LOWER_IS_BETTER = [
  'pue',
  'cost',
  'latency',
  'payback',
  'downtime',
  'footprint',
  'emission',
  'error',
  'loss',
  'risk',
  'overhead',
] as const;

const HIGHER_IS_BETTER = [
  'efficiency',
  'saving',
  'recovery',
  'throughput',
  'capacity',
  'density',
  'performance',
  'yield',
] as const;

type Polarity = 'lower-better' | 'higher-better' | null;

function detectPolarity(title: string, series: ChartSeriesPoint[]): Polarity {
  const parts = [title, ...series.flatMap((p) => [p.label, p.unit ?? ''])];
  const hay = parts.map((p) => normaliseForMatch(p)).join(' ');
  for (const tok of LOWER_IS_BETTER) if (hay.includes(tok)) return 'lower-better';
  for (const tok of HIGHER_IS_BETTER) if (hay.includes(tok)) return 'higher-better';
  return null;
}

function argmax(series: ChartSeriesPoint[]): number {
  let best = 0;
  for (let i = 1; i < series.length; i++) {
    if (series[i]!.value > series[best]!.value) best = i;
  }
  return best;
}

function argmin(series: ChartSeriesPoint[]): number {
  let best = 0;
  for (let i = 1; i < series.length; i++) {
    if (series[i]!.value < series[best]!.value) best = i;
  }
  return best;
}

/**
 * Pick the index of the series point the slide is arguing FOR. Public for
 * testing.
 */
export function pickSubjectIndex(title: string, series: ChartSeriesPoint[]): number {
  if (series.length === 0) return 0;
  if (series.length === 1) return 0;

  // (a) Title-token match. A single-character label (e.g. "A") would
  // collide with almost any title; require ≥ 2 normalised characters.
  // When several labels match, the LAST occurrence in the title wins —
  // "Air vs sCO2 PUE" puts sCO2 after Air, and the slide argues for sCO2.
  const normTitle = normaliseForMatch(title);
  if (normTitle.length > 0) {
    let bestIdx = -1;
    let bestPos = -1;
    for (let i = 0; i < series.length; i++) {
      const needle = normaliseForMatch(series[i]!.label);
      if (needle.length < 2) continue;
      const pos = normTitle.lastIndexOf(needle);
      if (pos > bestPos) {
        bestPos = pos;
        bestIdx = i;
      }
    }
    if (bestIdx >= 0) return bestIdx;
  }

  // (b) Metric polarity.
  const polarity = detectPolarity(title, series);
  if (polarity === 'lower-better') return argmin(series);
  if (polarity === 'higher-better') return argmax(series);

  // (c) Fallback: biggest number wins.
  return argmax(series);
}

// ---------------------------------------------------------------------------
// validateChartEncoding
// ---------------------------------------------------------------------------

/**
 * Apply the bar-specific guards (low-spread re-route, zero annotation) to a
 * series. Called from the initial-bar path and from the line→bar cascade so
 * a low-spread 2-point line lands on multi_stat, not a flat two-bar chart.
 */
function applyBarGuards(
  title: string,
  series: ChartSeriesPoint[],
  groupLabels: string[],
  priorReroutes: ChartReroute[],
): EncodingDecision {
  const passthrough: EncodingDecision = {
    chartType: 'bar',
    series,
    groupLabels,
    zeroAnnotations: [],
    subjectIndex: null,
    reroutes: priorReroutes,
  };

  if (series.length === 0) return passthrough;

  const zeroIndices: number[] = [];
  series.forEach((point, i) => {
    if (point.value === 0) zeroIndices.push(i);
  });
  const allZero = zeroIndices.length === series.length;

  // CASE B — zeros mixed with non-zeros: annotate, keep the chart.
  if (zeroIndices.length > 0 && !allZero) {
    return {
      chartType: 'bar',
      series,
      groupLabels,
      zeroAnnotations: zeroIndices,
      subjectIndex: null,
      reroutes: [
        ...priorReroutes,
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

  // CASE A — all non-zero, low spread: re-route to multi_stat preserving
  // every point. Multi_stat draws stat cards, not bars, so the values do
  // not compete with a zero baseline; the subject card carries the deck
  // accent so the slide's argument is still visible at a glance.
  if (zeroIndices.length === 0) {
    const values = series.map((p) => p.value);
    const max = Math.max(...values);
    const min = Math.min(...values);
    if (min > 0 && max / min < LOW_SPREAD_THRESHOLD) {
      const subjectIndex = pickSubjectIndex(title, series);
      const subject = series[subjectIndex]!;
      return {
        chartType: 'multi_stat',
        series,
        groupLabels: [],
        zeroAnnotations: [],
        subjectIndex,
        reroutes: [
          ...priorReroutes,
          {
            from: 'bar',
            to: 'multi_stat',
            reason: 'low_spread',
            detail:
              `max/min ratio ${(max / min).toFixed(2)} below ` +
              `threshold ${LOW_SPREAD_THRESHOLD}; a zero-based bar would ` +
              `compress these into near-equal columns. Rendering ` +
              `${series.length} stat card(s); subject "${subject.label}" ` +
              `= ${formatChartValue(subject.value, subject.unit ?? null)} ` +
              `(index ${subjectIndex}) highlighted in accent.`,
          },
        ],
      };
    }
  }

  return passthrough;
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
  const title = content.title ?? '';

  const passthrough: EncodingDecision = {
    chartType: initialType,
    series,
    groupLabels,
    zeroAnnotations: [],
    subjectIndex: null,
    reroutes: [],
  };

  // Nothing to plot — let the renderer's empty-series fallback handle it.
  if (series.length === 0) return passthrough;

  if (initialType === 'bar') {
    return applyBarGuards(title, series, groupLabels, []);
  }

  if (initialType === 'line' && series.length < LINE_MIN_POINTS) {
    // A line over <3 points implies a trend that does not exist. Re-route
    // to bar and then re-run the bar guards — a low-spread 2-point line
    // (e.g. 1.0 / 1.2) should cascade all the way to multi_stat, not stop
    // at a flat 2-bar chart.
    const lineReroute: ChartReroute = {
      from: 'line',
      to: 'bar',
      reason: 'line_too_few_points',
      detail:
        `line over ${series.length} point(s) implies a continuous ` +
        `progression that does not exist for discrete categories; ` +
        `re-routing to bar and re-evaluating bar guards (a low-spread ` +
        `result will cascade to multi_stat).`,
    };
    return applyBarGuards(title, series, groupLabels, [lineReroute]);
  }

  return passthrough;
}
