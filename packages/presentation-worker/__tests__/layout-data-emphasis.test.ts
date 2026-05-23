/**
 * DATA_EMPHASIS layout — value/unit separation and measured stacking (FIX A).
 *
 * Locks the two regressions the fixed-fraction layout shipped:
 *   1. the number block jammed value+unit ("1.58PUE") and a second block drew
 *      the unit again, so the unit appeared twice;
 *   2. number/unit/label/comparison sat at fixed fractions of the column
 *      height, so a value that wrapped left the label stranded in a gap.
 */

import { describe, expect, it } from 'vitest';
import { LayoutPass } from '../src/layout-pass.js';
import { FONT_SIZES } from '../src/constants.js';
import type { DeckSpec, SlideContent, SlideSpec, SlideType, StatItem, TextBlock } from '../src/types.js';

function buildDeck(slides: SlideSpec[]): DeckSpec {
  return {
    project_id: 'p-test',
    title: 'Test deck',
    language: 'en',
    created_at: '2026-05-11T12:00:00Z',
    design: {
      mood: 'bold_technical',
      palette: {
        background: '#0D0D12',
        surface: '#1A1A22',
        text: '#F5F0E8',
        accent: '#E8553A',
        text_secondary: '#A89F91',
      },
      heading_font: 'Inter',
      body_font: 'Inter',
      decorative_font: null,
      image_style_prefix: 'technical diagram',
      background_treatment: 'dark',
    },
    interview: {},
    slides,
    export_formats: ['html'],
  };
}

function makeSlide(index: number, type: SlideType, content: SlideContent): SlideSpec {
  return { slide_index: index, slide_type: type, content, source_claim_ids: [] };
}

/** A digit immediately followed by a unit token with no separating space. */
const JAMMED_UNIT = /\d(PUE|MW|%|bar|kW|years|per MW)/;

const findExact = (blocks: TextBlock[], text: string): TextBlock | undefined =>
  blocks.find((b) => b.text === text);

const countContaining = (blocks: TextBlock[], needle: string): number =>
  blocks.filter((b) => b.text.includes(needle)).length;

describe('DATA_EMPHASIS — value/unit separation', () => {
  const stats: StatItem[] = [
    {
      value: '1.56–1.58',
      unit: 'PUE',
      label: 'Power Usage Effectiveness',
      highlight: true,
      comparison: 'vs 2.0 typical',
    },
    { value: '35', unit: '%', label: 'Overhead reduction' },
    { value: '12', unit: 'MW', label: 'Cooling capacity' },
  ];
  const deck = buildDeck([makeSlide(0, 'data_emphasis', { title: 'Cooling economics', stats })]);
  const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);

  it('never jams a digit against its unit in any text block', () => {
    const offenders = layout.textBlocks.filter((b) => JAMMED_UNIT.test(b.text)).map((b) => b.text);
    expect(offenders).toEqual([]);
  });

  it('renders each unit in exactly one block', () => {
    // The number block carries the value only; the unit has a single home.
    expect(findExact(layout.textBlocks, '1.56–1.58')).toBeDefined();
    expect(countContaining(layout.textBlocks, 'PUE')).toBe(1);
    expect(countContaining(layout.textBlocks, 'MW')).toBe(1);
    // "%" only ever appears as the unit block of the 35% stat.
    expect(countContaining(layout.textBlocks, '%')).toBe(1);
    expect(findExact(layout.textBlocks, '%')).toBeDefined();
  });

  it('stacks number → unit → label → comparison tight against measured heights', () => {
    const number = findExact(layout.textBlocks, '1.56–1.58')!;
    const unit = findExact(layout.textBlocks, 'PUE')!;
    const label = findExact(layout.textBlocks, 'Power Usage Effectiveness')!;
    const comparison = findExact(layout.textBlocks, 'vs 2.0 typical')!;
    const ordered = [number, unit, label, comparison];

    // All four belong to the same column.
    for (const b of ordered) expect(b.x).toBe(number.x);

    // Each block sits just below the previous block's MEASURED bottom — a tight
    // gap, not the ~25%+ jump a fixed-fraction layout would leave.
    for (let i = 1; i < ordered.length; i++) {
      const prev = ordered[i - 1]!;
      const cur = ordered[i]!;
      const gap = cur.y - (prev.y + prev.measuredHeightPct);
      expect(gap).toBeGreaterThanOrEqual(0);
      expect(gap).toBeLessThan(3);
    }
  });

  it('keeps multi-stat number blocks in the large display tier', () => {
    const number = findExact(layout.textBlocks, '1.56–1.58')!;
    expect(number.fontSize).toBeGreaterThanOrEqual(FONT_SIZES.displayLarge.min);
  });
});

describe('DATA_EMPHASIS — hero stat shows its unit', () => {
  it('renders the unit block for a single hero stat (no !isHero guard)', () => {
    const stats: StatItem[] = [{ value: '94.4', unit: '%', label: 'Water savings', highlight: true }];
    const deck = buildDeck([makeSlide(0, 'data_emphasis', { title: 'Headline result', stats })]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);

    const number = findExact(layout.textBlocks, '94.4')!;
    expect(number).toBeDefined();
    expect(number.fontSize).toBeGreaterThanOrEqual(FONT_SIZES.displayJumbo.min);
    // The hero unit is now its own block, below the number — not concatenated.
    const unit = findExact(layout.textBlocks, '%');
    expect(unit).toBeDefined();
    expect(unit!.y).toBeGreaterThan(number.y);
    expect(JAMMED_UNIT.test(number.text)).toBe(false);
  });
});
