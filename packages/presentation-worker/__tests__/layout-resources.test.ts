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

  // ---- L2 fit-migration tripwires -----------------------------------------
  // The name/desc/url sub-blocks are identified by COLOUR: name = palette.text,
  // desc = palette.text_secondary, url = palette.accent. Geometry below must be
  // engine-driven (measured stack), not fixed-pitch slots.

  it('keeps intra-resource order: desc below name, url below desc', () => {
    const deck = buildTestDeck([
      makeSlide('resources_links', {
        title: 'Further reading',
        resources: resources(4),
      }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    const { text, text_secondary, accent } = deck.design.palette;

    for (let i = 0; i < 4; i++) {
      const name = layout.textBlocks.find(
        (b) => b.text === `Resource ${i + 1}` && b.color === text,
      );
      const desc = layout.textBlocks.find(
        (b) => b.text === `Brief description ${i + 1}.` && b.color === text_secondary,
      );
      const url = layout.textBlocks.find(
        (b) => b.text === `https://example.com/${i + 1}` && b.color === accent,
      );
      expect(name).toBeDefined();
      expect(desc).toBeDefined();
      expect(url).toBeDefined();
      // desc top sits at/below name's measured bottom; url top at/below desc's.
      expect(desc!.y).toBeGreaterThanOrEqual(name!.y + name!.measuredHeightPct - 1e-6);
      expect(url!.y).toBeGreaterThanOrEqual(desc!.y + desc!.measuredHeightPct - 1e-6);
    }
  });

  it('does not overlap resources: next name sits below previous url bottom', () => {
    const deck = buildTestDeck([
      makeSlide('resources_links', {
        title: 'Further reading',
        resources: resources(4),
      }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    const { text, accent } = deck.design.palette;

    const nameY = (i: number) =>
      layout.textBlocks.find((b) => b.text === `Resource ${i}` && b.color === text)!;
    const urlBlock = (i: number) =>
      layout.textBlocks.find(
        (b) => b.text === `https://example.com/${i}` && b.color === accent,
      )!;

    for (let i = 1; i < 4; i++) {
      const prevUrl = urlBlock(i);
      const nextName = nameY(i + 1);
      expect(nextName.y).toBeGreaterThanOrEqual(
        prevUrl.y + prevUrl.measuredHeightPct - 1e-6,
      );
    }
  });

  it('caps at MAX_RESOURCES=6 even when 8 are supplied', () => {
    const deck = buildTestDeck([
      makeSlide('resources_links', {
        title: 'Further reading',
        resources: resources(8),
      }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    const names = layout.textBlocks.filter((b) => /^Resource \d+$/.test(b.text));
    expect(names).toHaveLength(6);
  });

  it('wraps a long description instead of truncating; url sits below its measured bottom', () => {
    const longDescription =
      'This is a deliberately verbose description that is far longer than a single ' +
      'line of body text would ever be, written specifically so the layout engine ' +
      'must wrap it across multiple lines and reserve genuine vertical space for it ' +
      'rather than clamping the resource into a fixed three-percent slot and clipping.';
    const deck = buildTestDeck([
      makeSlide('resources_links', {
        title: 'Further reading',
        resources: [
          {
            name: 'Long resource',
            description: longDescription,
            url: 'https://example.com/long',
          },
        ],
      }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    const { text_secondary, accent } = deck.design.palette;

    const desc = layout.textBlocks.find(
      (b) => b.text === longDescription && b.color === text_secondary,
    );
    const url = layout.textBlocks.find(
      (b) => b.text === 'https://example.com/long' && b.color === accent,
    );
    expect(desc).toBeDefined();
    expect(url).toBeDefined();
    // The long description WRAPS — it is not shortened/ellipsized to a slot.
    expect(desc!.truncated).toBeFalsy();
    // It occupies more than one body line of height (proof it wrapped, not clamped).
    expect(desc!.measuredHeightPct).toBeGreaterThan(4);
    // The url is pushed DOWN past the wrapped description's measured bottom.
    expect(url!.y).toBeGreaterThanOrEqual(
      desc!.y + desc!.measuredHeightPct - 1e-6,
    );
  });

  it('scales tall content to fit on-slide — no block past the 94% bottom margin', () => {
    // Probed pre-fix: 6 resources each with a long ~30-word description ran to
    // ~110% (off-slide, silent). The scale+rebuild helper must keep every content
    // block within the slide. No reveal trigger in this layout, so the only
    // assertion is the max content bottom.
    const LONG_DESC =
      'A thoroughly verbose description spanning roughly thirty words so the layout ' +
      'engine wraps it across several lines and the six stacked resources together ' +
      'exceed the band height and must scale down to fit.';
    const deck = buildTestDeck([
      makeSlide('resources_links', {
        title: 'Further reading',
        resources: Array.from({ length: 6 }, (_, i) => ({
          name: `Resource ${i + 1}`,
          description: LONG_DESC,
          url: `https://example.com/${i + 1}`,
        })),
      }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    const { text, text_secondary, accent } = deck.design.palette;
    const content = layout.textBlocks.filter(
      (b) => b.color === text_secondary || b.color === accent ||
        /^Resource \d+$/.test(b.text) && b.color === text,
    );
    const maxBottom = Math.max(...content.map((b) => b.y + b.measuredHeightPct));
    expect(maxBottom).toBeLessThanOrEqual(94);
  });

  it('flags hasOverflow when content cannot fit even after scaling', () => {
    // Extreme content that must truncate even at the scaled budget → genuine
    // can't-fit must be observable (compose hasOverflow), not silent. The
    // per-sub repetition is tuned so each sub still fits the full band naturally
    // (no pre-existing truncation), but the combined 6×3 stack forces scale<1 and
    // truncation in the rebuild — which the helper surfaces as overflow.
    const HUGE = 'Reason and observation '.repeat(12).trim();
    const deck = buildTestDeck([
      makeSlide('resources_links', {
        title: 'Further reading',
        resources: Array.from({ length: 6 }, (_, i) => ({
          name: `Resource ${i + 1}`,
          description: HUGE,
          url: `https://example.com/${i + 1}`,
        })),
      }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    const { text, text_secondary, accent } = deck.design.palette;
    // still on-slide…
    const content = layout.textBlocks.filter(
      (b) => b.color === text_secondary || b.color === accent ||
        /^Resource \d+$/.test(b.text) && b.color === text,
    );
    expect(Math.max(...content.map((b) => b.y + b.measuredHeightPct))).toBeLessThanOrEqual(94);
    // …but the audit can see it could not really fit
    expect(layout.hasOverflow).toBe(true);
  });
});
