import { describe, expect, it } from 'vitest';
import { LayoutPass } from '../src/layout-pass.js';
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
