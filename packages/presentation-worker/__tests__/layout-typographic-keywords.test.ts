import { describe, expect, it } from 'vitest';
import { LayoutPass } from '../src/layout-pass.js';
import { buildTestDeck, makeSlide } from './helpers.js';
import type { KeywordItem } from '../src/types.js';

function keywords(count: number): KeywordItem[] {
  return Array.from({ length: count }, (_, i) => ({
    term: `Term${i + 1}`,
    explanation: `Explanation number ${i + 1}.`,
  }));
}

describe('layout — TYPOGRAPHIC_KEYWORDS', () => {
  it('emits a term block and an explanation block per keyword, with terms stacked vertically', () => {
    const deck = buildTestDeck([
      makeSlide('typographic_keywords', {
        title: 'Key terms',
        keywords: keywords(5),
      }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);

    const terms = layout.textBlocks.filter((b) => /^Term\d+$/.test(b.text));
    expect(terms).toHaveLength(5);
    const explanations = layout.textBlocks.filter((b) =>
      b.text.startsWith('Explanation number'),
    );
    expect(explanations).toHaveLength(5);

    for (const t of terms) {
      expect(t.color).toBe(deck.design.palette.accent);
    }
    const ys = terms.map((t) => t.y);
    const sorted = [...ys].sort((a, b) => a - b);
    expect(ys).toEqual(sorted);
    expect(sorted[sorted.length - 1]).toBeGreaterThan(sorted[0]!);
  });

  it('marks keyword terms as bold in the accent colour', () => {
    const deck = buildTestDeck([
      makeSlide('typographic_keywords', {
        title: 'Glossary',
        keywords: keywords(3),
      }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    const terms = layout.textBlocks.filter((b) => /^Term\d+$/.test(b.text));
    for (const t of terms) {
      expect(t.fontWeight).toBe('bold');
      expect(t.color).toBe(deck.design.palette.accent);
    }
  });

  it('spaces keywords tighter when there are more of them', () => {
    const deck3 = buildTestDeck([
      makeSlide('typographic_keywords', { title: 'A', keywords: keywords(3) }),
    ]);
    const deck6 = buildTestDeck([
      makeSlide('typographic_keywords', { title: 'B', keywords: keywords(6) }),
    ]);
    const layout3 = new LayoutPass().layoutSlide(deck3.slides[0]!, deck3);
    const layout6 = new LayoutPass().layoutSlide(deck6.slides[0]!, deck6);
    const terms3 = layout3.textBlocks.filter((b) => /^Term\d+$/.test(b.text));
    const terms6 = layout6.textBlocks.filter((b) => /^Term\d+$/.test(b.text));
    const gap3 = terms3[1]!.y - terms3[0]!.y;
    const gap6 = terms6[1]!.y - terms6[0]!.y;
    expect(gap6).toBeLessThan(gap3);
    // Both fit on the slide.
    for (const t of [...terms3, ...terms6]) {
      expect(t.y + t.h).toBeLessThanOrEqual(100);
    }
  });
});
