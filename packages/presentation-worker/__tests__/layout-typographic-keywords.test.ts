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

// Mirrors the layout's vertical-flow constants (typographic-keywords.ts).
const TITLE_ROWS_GAP = 2; // below the title before the first keyword row
const OLD_FIXED_START_Y = 18; // the deleted even-distribution band floor

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

  it('stacks measured rows hugging the title, uniform pitch, no fixed startY', () => {
    // Identical short content in every row, so each row's measured height is the
    // same: pitch = rowHeight + ROW_GAP is therefore constant within a deck AND
    // across keyword counts. A short title ('A' / 'B') keeps contentTop high so
    // the rows provably clear the deleted fixed floor.
    const deck3 = buildTestDeck([
      makeSlide('typographic_keywords', { title: 'A', keywords: keywords(3) }),
    ]);
    const deck6 = buildTestDeck([
      makeSlide('typographic_keywords', { title: 'B', keywords: keywords(6) }),
    ]);
    const layout3 = new LayoutPass().layoutSlide(deck3.slides[0]!, deck3);
    const layout6 = new LayoutPass().layoutSlide(deck6.slides[0]!, deck6);

    const title3 = layout3.textBlocks.find((b) => b.text === 'A')!;
    expect(title3).toBeDefined();

    const sortByY = (a: { y: number }, b: { y: number }) => a.y - b.y;
    const terms3 = layout3.textBlocks
      .filter((b) => /^Term\d+$/.test(b.text))
      .sort(sortByY);
    const explanations3 = layout3.textBlocks
      .filter((b) => b.text.startsWith('Explanation number'))
      .sort(sortByY);
    const terms6 = layout6.textBlocks
      .filter((b) => /^Term\d+$/.test(b.text))
      .sort(sortByY);

    expect(terms3).toHaveLength(3);
    expect(explanations3).toHaveLength(3);
    expect(terms6).toHaveLength(6);

    // (a) Rows HUG the title: the first row top is the title's MEASURED bottom
    // plus the title→rows gap — exact arithmetic, both sides read the same
    // measuredHeightPct, so the tolerance is tight. And it sits ABOVE the old
    // fixed floor: the even-distribution band (startY=18) is gone.
    expect(terms3[0]!.y).toBeCloseTo(
      title3.y + title3.measuredHeightPct + TITLE_ROWS_GAP,
      5,
    );
    expect(terms3[0]!.y).toBeLessThan(OLD_FIXED_START_Y);

    // (b) Uniform pitch WITHIN a deck: consecutive row pitches are equal because
    // every row hugs the same measured rowHeight and the gap is constant.
    const pitch3a = terms3[1]!.y - terms3[0]!.y;
    const pitch3b = terms3[2]!.y - terms3[1]!.y;
    expect(pitch3b).toBeCloseTo(pitch3a, 5);

    // (c) Uniform pitch ACROSS counts: 6 keywords pitch == 3 keywords pitch.
    // This is the deliberate INVERSE of the deleted gap6 < gap3 behaviour —
    // identical short content means identical rowHeight, so packing more rows
    // does NOT tighten them; spare whitespace pools at the bottom instead.
    const pitch6 = terms6[1]!.y - terms6[0]!.y;
    expect(pitch6).toBeCloseTo(pitch3a, 5);

    // (d) Paired row tops: each explanation shares its term's row top exactly
    // (both are assigned the same fit.tops[i]). Difference is exactly zero.
    for (let i = 0; i < terms3.length; i++) {
      expect(explanations3[i]!.y).toBeCloseTo(terms3[i]!.y, 5);
    }

    // (e) valign locked to top (no accidental emitBandCell, which would centre
    // the cell): buildTextBlock leaves valign unset for top-aligned content.
    expect(terms3[0]!.valign === 'top' || terms3[0]!.valign === undefined).toBe(true);
    expect(
      explanations3[0]!.valign === 'top' || explanations3[0]!.valign === undefined,
    ).toBe(true);

    // (f) Everything stays on the slide — checked on BOTH decks, since the
    // 6-row deck (overflow:'truncate', no scale-to-fit) is where rows could run
    // off the bottom.
    for (const t of [
      ...terms3,
      ...explanations3,
      ...terms6,
      ...layout6.textBlocks.filter((b) => b.text.startsWith('Explanation number')),
    ]) {
      expect(t.y + t.h).toBeLessThanOrEqual(100);
    }
  });
});
