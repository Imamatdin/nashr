/**
 * Measured-height stacking: buildTextBlock must preserve the real wrapped
 * height of a block (measuredHeightPct), and the stacking layouts
 * (title_hero, chart_data) must position downstream elements below that
 * measured bottom so a multi-line title can't overlap the element under it.
 */

import { describe, expect, it } from 'vitest';
import { FONT_SIZES, LINE_HEIGHTS, SLIDE_REGIONS } from '../src/constants.js';
import { LayoutPass } from '../src/layout-pass.js';
import { buildTextBlock } from '../src/layouts/shared.js';
import type { FontWeight, TextAlign } from '../src/types.js';
import { buildTestDeck, makeSlide } from './helpers.js';

const FILLER_REGION = { x: 5, y: 5, w: 40, h: 80 } as const;

function block(text: string) {
  return buildTextBlock({
    text,
    region: { ...FILLER_REGION },
    fontFamily: 'Inter',
    fontWeight: 'normal' as FontWeight,
    color: '#000000',
    align: 'left' as TextAlign,
    tier: FONT_SIZES.body,
    lineHeight: LINE_HEIGHTS.body,
  });
}

describe('buildTextBlock — measuredHeightPct capture', () => {
  it('captures a larger measured height for long multi-line text than short text', () => {
    const short = block('Hi');
    const long = block('word '.repeat(80).trim());

    expect(short.measuredHeightPct).toBeGreaterThan(0);
    // The long block wraps to many lines in the same region; its measured
    // height must be well above the single-line short block.
    expect(long.measuredHeightPct).toBeGreaterThan(short.measuredHeightPct * 2);
  });
});

describe('TITLE_HERO — never-stack-upward floor for the subtitle', () => {
  // Known multi-line case: this title wraps in the title_hero title region.
  const LONG_TITLE = 'Supercritical CO2 Is the Future of Data Center Cooling';

  it('places the subtitle at or below the title bottom and never above its region y', () => {
    const deck = buildTestDeck([
      makeSlide('title_hero', {
        title: LONG_TITLE,
        subtitle: 'An italic subtitle line',
      }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);

    const title = layout.textBlocks.find((b) => b.text === LONG_TITLE)!;
    const subtitle = layout.textBlocks.find((b) => b.text.includes('italic subtitle'))!;
    expect(title).toBeDefined();
    expect(subtitle).toBeDefined();
    expect(title.measuredHeightPct).toBeGreaterThan(0);

    // No overlap: the subtitle begins at or after the title's measured bottom.
    expect(subtitle.y).toBeGreaterThanOrEqual(title.y + title.measuredHeightPct);
    // Floor: the subtitle is never pulled UP above its designed region y.
    // (The old behaviour pulled it up snug under the title; that upward pull
    // was the collision class and is deliberately gone.)
    expect(subtitle.y).toBeGreaterThanOrEqual(SLIDE_REGIONS.title_hero!.subtitle!.y);
  });

  it('keeps a short title valid — subtitle rests at its region y, never pulled up', () => {
    const deck = buildTestDeck([
      makeSlide('title_hero', {
        title: 'Hi',
        subtitle: 'Short subtitle',
      }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);

    const title = layout.textBlocks.find((b) => b.text === 'Hi')!;
    const subtitle = layout.textBlocks.find((b) => b.text === 'Short subtitle')!;

    // Below the title's measured bottom (no overlap)...
    expect(subtitle.y).toBeGreaterThanOrEqual(title.y + title.measuredHeightPct);
    // ...and floored at the designed region y, not pulled up under the title.
    expect(subtitle.y).toBe(SLIDE_REGIONS.title_hero!.subtitle!.y);
  });
});

describe('TITLE_HERO — integration with true glyph measurement (IBM Plex Sans)', () => {
  // The sCO2 title rendered with a vendored variable font, so the layout
  // pass measures real glyph advances rather than the char-ratio fallback.
  const SC02_TITLE = 'Supercritical CO2 Is the Future of Data Center Cooling';

  function plexDeck() {
    const deck = buildTestDeck([
      makeSlide('title_hero', {
        title: SC02_TITLE,
        subtitle: 'A grounded italic subtitle line',
      }),
    ]);
    deck.design.heading_font = 'IBM Plex Sans';
    return deck;
  }

  it('keeps the subtitle clear of the measured title and at/below its region y', () => {
    const deck = plexDeck();
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);

    const title = layout.textBlocks.find((b) => b.text === SC02_TITLE)!;
    const subtitle = layout.textBlocks.find((b) => b.text.includes('grounded'))!;
    expect(title.measuredHeightPct).toBeGreaterThan(0);

    // The whole point: subtitle.y >= title.y + title.measuredHeightPct.
    expect(subtitle.y).toBeGreaterThanOrEqual(title.y + title.measuredHeightPct);
    // And the floor holds with real measurement too.
    expect(subtitle.y).toBeGreaterThanOrEqual(SLIDE_REGIONS.title_hero!.subtitle!.y);
  });
});

describe('CHART_DATA — chart box stacks below the measured title bottom', () => {
  const LONG_TITLE =
    'Supercritical CO2 Cooling Slashes Data Center Energy Consumption Across Every Surveyed Climate Zone Worldwide';

  it('never lets the title overlap the chart placeholder region', () => {
    const deck = buildTestDeck([makeSlide('chart_data', { title: LONG_TITLE })]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);

    const title = layout.textBlocks.find((b) => b.text === LONG_TITLE)!;
    const placeholder = layout.textBlocks.find((b) =>
      b.text.includes('[Chart placeholder]'),
    )!;
    expect(title).toBeDefined();
    expect(placeholder).toBeDefined();
    expect(title.measuredHeightPct).toBeGreaterThan(0);

    // The chart box begins at or after the title's measured bottom.
    expect(placeholder.y).toBeGreaterThanOrEqual(title.y + title.measuredHeightPct);
  });
});
