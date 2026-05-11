import { describe, expect, it } from 'vitest';
import { LayoutPass } from '../src/layout-pass.js';
import { getPortraitPositions } from '../src/constants.js';
import { buildTestDeck, makeSlide } from './helpers.js';
import type { PersonItem } from '../src/types.js';

function people(count: number): PersonItem[] {
  return Array.from({ length: count }, (_, i) => ({
    name: `Person ${i + 1}`,
    role: `Role ${i + 1}`,
  }));
}

describe('layout — TEAM_CREDITS', () => {
  it('uses the GALLERY_PEOPLE portrait positions for name placement', () => {
    const deck = buildTestDeck([
      makeSlide('team_credits', { title: 'Thank You', people: people(3) }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    const names = layout.textBlocks
      .filter((b) => /^Person \d+$/.test(b.text))
      .sort((a, b) => a.x - b.x);
    expect(names).toHaveLength(3);
    const expected = getPortraitPositions(3).map((p) => p.x);
    expect(names.map((b) => b.x)).toEqual(expected);
  });

  it('emits role text blocks below each name in the secondary text colour', () => {
    const deck = buildTestDeck([
      makeSlide('team_credits', { title: 'Credits', people: people(3) }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    const names = layout.textBlocks.filter((b) => /^Person \d+$/.test(b.text));
    const roles = layout.textBlocks.filter((b) => /^Role \d+$/.test(b.text));
    expect(roles).toHaveLength(3);
    for (let i = 0; i < names.length; i++) {
      const name = names[i]!;
      const role = roles.find((r) => r.text === `Role ${i + 1}`)!;
      expect(role.y).toBeGreaterThan(name.y);
      expect(role.color).toBe(deck.design.palette.text_secondary);
    }
  });
});
