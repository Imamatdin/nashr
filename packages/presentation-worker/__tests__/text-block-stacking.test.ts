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

describe('TITLE_HERO — subtitle stacks below the measured title bottom', () => {
  // Known multi-line case: this title wraps in the title_hero title region.
  const LONG_TITLE = 'Supercritical CO2 Is the Future of Data Center Cooling';

  it('places the subtitle at or below where the title actually ends', () => {
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
    // Dynamic: the subtitle is pulled up under the title, not left at the
    // fixed region y it would have had with the old positioning.
    expect(subtitle.y).toBeLessThan(SLIDE_REGIONS.title_hero!.subtitle!.y);
  });

  it('keeps a short title valid — subtitle sits snug below it, not floating low', () => {
    const deck = buildTestDeck([
      makeSlide('title_hero', {
        title: 'Hi',
        subtitle: 'Short subtitle',
      }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);

    const title = layout.textBlocks.find((b) => b.text === 'Hi')!;
    const subtitle = layout.textBlocks.find((b) => b.text === 'Short subtitle')!;

    // Below the title's measured bottom...
    expect(subtitle.y).toBeGreaterThanOrEqual(title.y + title.measuredHeightPct);
    // ...but not floating at the fixed low region y...
    expect(subtitle.y).toBeLessThan(SLIDE_REGIONS.title_hero!.subtitle!.y);
    // ...and close to the title, not absurdly far below it.
    expect(subtitle.y - (title.y + title.measuredHeightPct)).toBeLessThan(10);
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
