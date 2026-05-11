import { describe, expect, it } from 'vitest';
import { LayoutPass } from '../src/layout-pass.js';
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
});
