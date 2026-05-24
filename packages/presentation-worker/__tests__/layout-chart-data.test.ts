import { describe, expect, it } from 'vitest';
import { LayoutPass } from '../src/layout-pass.js';
import type { ChartSeriesPoint } from '../src/types.js';
import { buildTestDeck, makeSlide } from './helpers.js';

describe('layout — CHART_DATA', () => {
  it('reserves the chart region with a centred placeholder block', () => {
    const deck = buildTestDeck([
      makeSlide('chart_data', {
        title: 'Solar adoption tripled since 2020',
      }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    const placeholder = layout.textBlocks.find((b) =>
      b.text.includes('[Chart placeholder]'),
    );
    expect(placeholder).toBeDefined();
    expect(placeholder!.x).toBe(5);
    expect(placeholder!.y).toBe(15);
    expect(placeholder!.w).toBe(65);
    expect(placeholder!.h).toBe(72);
    expect(placeholder!.align).toBe('center');
  });

  it('renders the body_text as an annotation in the right-side column', () => {
    const deck = buildTestDeck([
      makeSlide('chart_data', {
        title: 'On track to exceed $10M ARR by Q4',
        body_text: 'Driven by AI-adoption tailwinds in Q3.',
      }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    const annotation = layout.textBlocks.find((b) =>
      b.text.startsWith('Driven by AI-adoption'),
    );
    expect(annotation).toBeDefined();
    expect(annotation!.x).toBeGreaterThanOrEqual(70);
    expect(annotation!.y).toBeLessThanOrEqual(20);
  });

  it('draws real bars (not the placeholder) when chart_series is present', () => {
    // Step 2: chart_series now drives a native bar chart. The placeholder is
    // reserved for the empty-series fallback only.
    const series: ChartSeriesPoint[] = [
      { label: 'Air', value: 8, unit: 'kW/rack' },
      { label: 'Liquid', value: 40, unit: 'kW/rack' },
      { label: 'sCO2', value: 120, unit: 'kW/rack' },
    ];
    const deck = buildTestDeck([
      makeSlide('chart_data', {
        title: 'Rack density climbs 15x from air to sCO2',
        chart_series: series,
      }),
    ]);
    const slide = deck.slides[0]!;
    expect(slide.content.chart_series).toEqual(series);
    const layout = new LayoutPass().layoutSlide(slide, deck);

    const placeholder = layout.textBlocks.find((b) =>
      b.text.includes('[Chart placeholder]'),
    );
    expect(placeholder).toBeUndefined();

    // One bar rect per point, in the accent colour, plus value + category labels.
    const accent = deck.design.palette.accent;
    const bars = layout.shapes.filter((s) => s.type === 'rect' && s.fill === accent);
    expect(bars).toHaveLength(3);
    expect(layout.textBlocks.some((b) => b.text === '120 kW/rack')).toBe(true);
    expect(layout.textBlocks.some((b) => b.text === 'sCO2')).toBe(true);
  });

  it('places the source citation small and bottom-right', () => {
    const deck = buildTestDeck([
      makeSlide('chart_data', {
        title: 'Headline',
        source_citation: 'IEA Renewables Report 2025',
      }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    const cite = layout.textBlocks.find((b) =>
      b.text.includes('IEA Renewables'),
    );
    expect(cite).toBeDefined();
    expect(cite!.y).toBeGreaterThanOrEqual(85);
    expect(cite!.align).toBe('right');
    expect(cite!.fontSize).toBeLessThanOrEqual(14);
  });
});
