import { describe, expect, it } from 'vitest';
import { LayoutPass } from '../src/layout-pass.js';
import { FONT_SIZES } from '../src/constants.js';
import { buildTestDeck, makeSlide } from './helpers.js';
import type { MatchingPair } from '../src/types.js';

function makePairs(count: number): MatchingPair[] {
  return Array.from({ length: count }, (_, i) => ({
    left: `Term ${i}`,
    right: `Definition ${i}`,
  }));
}

describe('layout — INTERACTIVE_MATCHING', () => {
  it('emits one left and one right block per pair', () => {
    const deck = buildTestDeck([
      makeSlide('interactive_matching', {
        title: 'Match',
        matching_pairs: makePairs(4),
      }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    expect(layout.textBlocks.filter((b) => b.role === 'match_left')).toHaveLength(4);
    expect(layout.textBlocks.filter((b) => b.role === 'match_right')).toHaveLength(4);
  });

  it('emits a dashed connector shape between each pair', () => {
    const deck = buildTestDeck([
      makeSlide('interactive_matching', {
        title: 'Match',
        matching_pairs: makePairs(4),
      }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    const lines = layout.shapes.filter((s) => s.type === 'line');
    expect(lines).toHaveLength(4);
    for (const line of lines) {
      expect(line.dashArray).toBeDefined();
      expect(line.dashArray).toMatch(/\d+\s+\d+/);
    }
  });

  it('uses localized reveal_trigger text (en / kaa)', () => {
    const enDeck = buildTestDeck(
      [makeSlide('interactive_matching', { title: 'Match', matching_pairs: makePairs(2) })],
      'en',
    );
    const enLayout = new LayoutPass().layoutSlide(enDeck.slides[0]!, enDeck);
    const enTrigger = enLayout.textBlocks.find((b) => b.role === 'reveal_trigger');
    expect(enTrigger!.text).toBe('Show answer');

    const kaaDeck = buildTestDeck(
      [makeSlide('interactive_matching', { title: 'Match', matching_pairs: makePairs(2) })],
      'kaa',
    );
    const kaaLayout = new LayoutPass().layoutSlide(kaaDeck.slides[0]!, kaaDeck);
    const kaaTrigger = kaaLayout.textBlocks.find((b) => b.role === 'reveal_trigger');
    expect(kaaTrigger!.text).toBe('Jauapdı kórset');
  });

  it('links left/right under the same pair groupId', () => {
    const deck = buildTestDeck([
      makeSlide('interactive_matching', {
        title: 'Match',
        matching_pairs: makePairs(3),
      }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    for (let i = 0; i < 3; i++) {
      const group = layout.textBlocks.filter((b) => b.groupId === `m${i}`);
      expect(group.filter((b) => b.role === 'match_left')).toHaveLength(1);
      expect(group.filter((b) => b.role === 'match_right')).toHaveLength(1);
    }
  });

  it('caps at 6 pairs', () => {
    const deck = buildTestDeck([
      makeSlide('interactive_matching', {
        title: 'Match',
        matching_pairs: makePairs(8),
      }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    expect(layout.textBlocks.filter((b) => b.role === 'match_left')).toHaveLength(6);
    expect(layout.textBlocks.filter((b) => b.role === 'match_right')).toHaveLength(6);
  });

  it('emits exactly one reveal_trigger block', () => {
    const deck = buildTestDeck([
      makeSlide('interactive_matching', {
        title: 'Match',
        matching_pairs: makePairs(3),
      }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    expect(layout.textBlocks.filter((b) => b.role === 'reveal_trigger')).toHaveLength(1);
  });

  it('renders connectors as dashed lines with the "4 4" pattern', () => {
    const deck = buildTestDeck([
      makeSlide('interactive_matching', {
        title: 'Match',
        matching_pairs: makePairs(2),
      }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    const line = layout.shapes.find((s) => s.type === 'line');
    expect(line!.dashArray).toBe('4 4');
  });

  // --- L2 fit-migration tripwires ---------------------------------------------

  it('row-syncs left, right, and the connector on one bandTop per pair', () => {
    const deck = buildTestDeck([
      makeSlide('interactive_matching', { title: 'Match', matching_pairs: makePairs(4) }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    const lefts = layout.textBlocks
      .filter((b) => b.role === 'match_left')
      .sort((a, b) => (a.dataIndex ?? 0) - (b.dataIndex ?? 0));
    const rights = layout.textBlocks
      .filter((b) => b.role === 'match_right')
      .sort((a, b) => (a.dataIndex ?? 0) - (b.dataIndex ?? 0));
    const connectors = layout.shapes.filter((s) => s.type === 'line').sort((a, b) => a.y - b.y);
    expect(lefts).toHaveLength(4);
    expect(rights).toHaveLength(4);
    expect(connectors).toHaveLength(4);
    for (let i = 0; i < 4; i++) {
      // left_i.y === right_i.y (the shared row top)
      expect(lefts[i]!.y).toBe(rights[i]!.y);
      // connector_i sits at the row mid-y
      const rowH = Math.max(lefts[i]!.measuredHeightPct, rights[i]!.measuredHeightPct);
      expect(connectors[i]!.y).toBeCloseTo(lefts[i]!.y + rowH / 2, 5);
      // rows are ordered and do not overlap
      if (i + 1 < 4) {
        expect(lefts[i + 1]!.y).toBeGreaterThanOrEqual(lefts[i]!.y + rowH - 1e-6);
      }
    }
  });

  it('scales tall pairs to fit on-slide — no row past the 94% bottom margin', () => {
    const LONG =
      'A deliberately long matching term that wraps across multiple lines to ' +
      'exercise the row height and the scale-to-fit guard in the matching engine.';
    const deck = buildTestDeck([
      makeSlide('interactive_matching', {
        title: 'Match',
        matching_pairs: Array.from({ length: 6 }, () => ({ left: LONG, right: LONG })),
      }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    const content = layout.textBlocks.filter(
      (b) => b.role === 'match_left' || b.role === 'match_right',
    );
    const maxBottom = Math.max(...content.map((b) => b.y + b.measuredHeightPct));
    expect(maxBottom).toBeLessThanOrEqual(94);
    const trigger = layout.textBlocks.find((b) => b.role === 'reveal_trigger')!;
    expect(trigger.y).toBeLessThanOrEqual(88);
    // Row-sync must hold in the SCALED regime too (left/right are rebuilt objects here).
    const lefts = layout.textBlocks
      .filter((b) => b.role === 'match_left')
      .sort((a, b) => (a.dataIndex ?? 0) - (b.dataIndex ?? 0));
    const rights = layout.textBlocks
      .filter((b) => b.role === 'match_right')
      .sort((a, b) => (a.dataIndex ?? 0) - (b.dataIndex ?? 0));
    for (let i = 0; i < lefts.length; i++) {
      expect(lefts[i]!.y).toBe(rights[i]!.y);
    }
  });

  it('does not over-shrink the short side of an asymmetric row (shared row budget)', () => {
    // Tall-left / short-right rows forced into the scaled regime. The short side must
    // be sized against the SHARED row budget (max*scale), not its own natural*scale —
    // otherwise it is over-shrunk below the tier max even though the row band has room.
    const LONG_LEFT =
      'A long left-hand matching term that wraps onto several lines so each row is ' +
      'tall and the six-row stack must scale down to fit the available band.';
    const pairs = Array.from({ length: 6 }, () => ({ left: LONG_LEFT, right: 'Yes' }));
    const deck = buildTestDeck([
      makeSlide('interactive_matching', { title: 'Match', matching_pairs: pairs }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    const byIdx = (a: { dataIndex?: number }, b: { dataIndex?: number }) =>
      (a.dataIndex ?? 0) - (b.dataIndex ?? 0);
    const lefts = layout.textBlocks.filter((b) => b.role === 'match_left').sort(byIdx);
    const rights = layout.textBlocks.filter((b) => b.role === 'match_right').sort(byIdx);
    expect(lefts).toHaveLength(6);
    // non-vacuous: the scaled regime is active (the tall side was shrunk below tier max)
    expect(lefts[0]!.fontSize).toBeLessThan(FONT_SIZES.body.max);
    for (let i = 0; i < 6; i++) {
      expect(lefts[i]!.y).toBe(rights[i]!.y); // row-synced
      // short side rendered at full tier size (a per-side budget would shrink it)
      expect(rights[i]!.fontSize).toBe(FONT_SIZES.body.max);
    }
  });

  it('flags hasOverflow when a pair cannot fit even after scaling', () => {
    const HUGE = 'Reason and observation '.repeat(40).trim();
    const deck = buildTestDeck([
      makeSlide('interactive_matching', {
        title: 'Match',
        matching_pairs: Array.from({ length: 6 }, () => ({ left: HUGE, right: HUGE })),
      }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    const content = layout.textBlocks.filter(
      (b) => b.role === 'match_left' || b.role === 'match_right',
    );
    expect(Math.max(...content.map((b) => b.y + b.measuredHeightPct))).toBeLessThanOrEqual(94);
    expect(layout.hasOverflow).toBe(true);
    // at least one column block carries the overflow flag itself (truncated && overflow),
    // proving the rebuilt-truncation promotion, not just the downstream hasOverflow
    expect(content.some((b) => b.truncated === true && b.overflow === true)).toBe(true);
  });
});
