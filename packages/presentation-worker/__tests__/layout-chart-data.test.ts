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

  it('value labels with a verbose unit do not overflow Q1 (slide-11 regression)', () => {
    // The live sCO2 regen failed [Q1] on a chart whose unit was
    // "% waste heat recovered" — a 23-char unit that yields a value label
    // like "20% waste heat recovered". With the old fixed 6pp VALUE_LABEL_BAND,
    // the wrap at subheading.min=20px overflowed the band. The fix measures
    // against the real space above each bar AND opts the chart labels into
    // FONT_SIZES.minimum as the absolute floor.
    const series: ChartSeriesPoint[] = [
      { label: 'Air cooling (min)', value: 0, unit: '% waste heat recovered' },
      { label: 'Liquid cooling (min)', value: 0, unit: '% waste heat recovered' },
      { label: 'sCO2 (min)', value: 5, unit: '% waste heat recovered' },
      { label: 'sCO2 (max)', value: 20, unit: '% waste heat recovered' },
    ];
    const deck = buildTestDeck([
      makeSlide('chart_data', {
        title: 'Most cooling stacks throw their waste heat away',
        chart_type: 'bar',
        chart_series: series,
      }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    const valueLabels = layout.textBlocks.filter((b) => b.text.includes('% waste heat recovered'));
    expect(valueLabels).toHaveLength(4);
    for (const b of valueLabels) {
      expect(b.overflow).toBe(false);
      // Common case: the dynamic measure region is generous enough that the
      // label stays at subheading.max=24 — no shrink needed.
      expect(b.fontSize).toBeGreaterThanOrEqual(20);
    }
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
