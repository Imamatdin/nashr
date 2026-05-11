import { describe, expect, it } from 'vitest';
import { LayoutPass } from '../src/layout-pass.js';
import { buildTestDeck, makeSlide } from './helpers.js';
import type { ResourceLink } from '../src/types.js';

function resources(count: number): ResourceLink[] {
  return Array.from({ length: count }, (_, i) => ({
    name: `Resource ${i + 1}`,
    description: `Brief description ${i + 1}.`,
    url: `https://example.com/${i + 1}`,
  }));
}

describe('layout — RESOURCES_LINKS', () => {
  it('stacks name, description, and url blocks per resource with increasing y', () => {
    const deck = buildTestDeck([
      makeSlide('resources_links', {
        title: 'Further reading',
        resources: resources(4),
      }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    const names = layout.textBlocks.filter((b) => /^Resource \d+$/.test(b.text));
    const descs = layout.textBlocks.filter((b) =>
      /^Brief description \d+\.$/.test(b.text),
    );
    const urls = layout.textBlocks.filter((b) =>
      /^https:\/\/example\.com\/\d+$/.test(b.text),
    );
    expect(names).toHaveLength(4);
    expect(descs).toHaveLength(4);
    expect(urls).toHaveLength(4);

    const ys = names.map((b) => b.y);
    const sorted = [...ys].sort((a, b) => a - b);
    expect(ys).toEqual(sorted);
    expect(ys[ys.length - 1]).toBeGreaterThan(ys[0]!);
  });

  it('uses the accent colour for url blocks', () => {
    const deck = buildTestDeck([
      makeSlide('resources_links', {
        title: 'Further reading',
        resources: resources(3),
      }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    const urlBlocks = layout.textBlocks.filter((b) =>
      b.text.startsWith('https://example.com'),
    );
    expect(urlBlocks).toHaveLength(3);
    for (const u of urlBlocks) {
      expect(u.color).toBe(deck.design.palette.accent);
    }
  });
});
