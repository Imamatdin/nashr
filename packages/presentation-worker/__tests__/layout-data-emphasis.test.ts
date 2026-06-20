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
import { FONT_SIZES, MARGIN } from '../src/constants.js';
import { ROW_GAP, TITLE_GAP } from '../src/layouts/data-emphasis.js';
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

describe('DATA_EMPHASIS — over-long stat value does not collide with its unit', () => {
  // A value wider than its column wraps to two lines in the browser and
  // PPTX/LibreOffice. measureText now counts that second line, so the number
  // block reserves its true height and the unit stacked beneath it clears the
  // value's lower line. NOTE: "1.56–1.58" from the original report is NOT
  // over-long (it fits the column on one line), so it never collided; this uses
  // a genuinely over-long triple-range value to exercise the wrap.
  const stats: StatItem[] = [
    { value: '1.560–1.580–1.600', unit: 'PUE', label: 'Industry average', highlight: false },
    { value: '1.08', unit: 'PUE', label: 'Best in class' },
    { value: '35', unit: '%', label: 'Overhead reduction' },
  ];
  const deck = buildDeck([makeSlide(0, 'data_emphasis', { title: 'Cooling economics', stats })]);
  const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);

  const overLongNumber = findExact(layout.textBlocks, '1.560–1.580–1.600')!;
  const shortNumber = findExact(layout.textBlocks, '1.08')!;
  const overLongUnit = layout.textBlocks.find((b) => b.text === 'PUE' && b.y > overLongNumber.y)!;

  it('measures the over-long value as a multi-line block (not collapsed to one line)', () => {
    // The fix's effect: the over-long number stays in the display tier and its
    // measured height reflects >= 2 lines. Without the fix it would shrink to
    // the font floor and measure a SINGLE line — coming out shorter than the
    // one-line "1.08" block rather than ~twice its height.
    expect(overLongNumber.fontSize).toBeGreaterThanOrEqual(FONT_SIZES.displayLarge.min);
    expect(overLongNumber.measuredHeightPct).toBeGreaterThan(1.8 * shortNumber.measuredHeightPct);
  });

  it('places the unit at or below the number block bottom (no overlap)', () => {
    expect(overLongUnit).toBeDefined();
    expect(overLongUnit.x).toBe(overLongNumber.x);
    // Unit top must clear the number's measured bottom (1px epsilon in % units).
    const epsilon = (1 / 1080) * 100;
    expect(overLongUnit.y).toBeGreaterThanOrEqual(overLongNumber.y + overLongNumber.h - epsilon);
  });
});

/**
 * Band fill + shared baseline regression suite (feat/layout-fill).
 *
 * Locks the under-fill bug fix: with the band expanded to the full content
 * region and the number tier sized adaptively, the stat row spans the
 * majority of the available height instead of squatting in a mid-slide
 * strip — and the number blocks share a common baseline so the headline
 * row reads as a unified ribbon.
 */
describe('DATA_EMPHASIS — band fill and shared baseline', () => {
  const REGION_BOTTOM = 100 - MARGIN.bottom; // 94

  function statBlocks(stats: StatItem[]): TextBlock[] {
    const deck = buildDeck([makeSlide(0, 'data_emphasis', { title: 'In numbers', stats })]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    return layout.textBlocks.filter((b) => b.text !== 'In numbers');
  }

  it('aligns number-block bottoms on a shared baseline across columns (3 stats)', () => {
    const stats: StatItem[] = [
      { value: '94.4', unit: '%', label: 'Water savings', highlight: true },
      { value: '35', unit: '%', label: 'Overhead' },
      { value: '12', unit: 'MW', label: 'Capacity' },
    ];
    const blocks = statBlocks(stats);
    const numbers = stats.map((s) => blocks.find((b) => b.text === s.value)!);
    expect(numbers).toHaveLength(3);
    const baselines = numbers.map((n) => n.y + n.measuredHeightPct);
    const spread = Math.max(...baselines) - Math.min(...baselines);
    // Tolerance: half a slide-percent. The font-metrics fallback can introduce
    // sub-pixel measurement drift but a shared baseline should pin within ~5px.
    expect(spread).toBeLessThan(0.5);
  });

  it('uses a uniform font size across number blocks in a row', () => {
    // Three same-format values — uniform sizing must yield identical fontSize
    // (uniformFontSize is the min over per-stat natural fits; with similar
    // values the natural fits are equal).
    const stats: StatItem[] = [
      { value: '94', unit: '%', label: 'a' },
      { value: '35', unit: '%', label: 'b' },
      { value: '12', unit: 'MW', label: 'c' },
    ];
    const blocks = statBlocks(stats);
    const sizes = stats.map((s) => blocks.find((b) => b.text === s.value)!.fontSize);
    const allEqual = sizes.every((s) => s === sizes[0]);
    expect(allEqual).toBe(true);
  });

  it('floors uniform font size at displayLarge.min when a pathological value would otherwise drag it lower', () => {
    // One very long value alongside two short ones. The uniform sizing must
    // not crater the row below displayLarge.min — the probe floor protects
    // the short stats from being dragged to caption-size.
    const stats: StatItem[] = [
      { value: '1.560–1.580–1.600–1.620', unit: 'PUE', label: 'a' },
      { value: '1.08', unit: 'PUE', label: 'b' },
      { value: '35', unit: '%', label: 'c' },
    ];
    const blocks = statBlocks(stats);
    const sizes = stats.map((s) => blocks.find((b) => b.text === s.value)!.fontSize);
    for (const s of sizes) expect(s).toBeGreaterThanOrEqual(FONT_SIZES.displayLarge.min);
  });

  it('spans the majority of the derived content region (3 stats)', () => {
    const stats: StatItem[] = [
      { value: '94.4', unit: '%', label: 'Water savings', comparison: 'vs 30% baseline' },
      { value: '35', unit: '%', label: 'Overhead reduction', comparison: 'down from 60%' },
      { value: '12', unit: 'MW', label: 'Cooling capacity', comparison: 'rack-scale' },
    ];
    const deck = buildDeck([makeSlide(0, 'data_emphasis', { title: 'In numbers', stats })]);
    const allBlocks = new LayoutPass().layoutSlide(deck.slides[0]!, deck).textBlocks;
    const title = allBlocks.find((b) => b.text === 'In numbers')!;
    const blocks = allBlocks.filter((b) => b !== title);

    // Denominator = the title-DERIVED content region the layout actually places
    // into post-migration (title-hug → titleBottom + TITLE_GAP → bottom margin),
    // NOT the now-dead frozen STAT_POSITIONS band. Mirrors the layout's own
    // derivation in data-emphasis.ts.
    const contentTop = title.y + title.measuredHeightPct + TITLE_GAP;
    const derivedHeight = REGION_BOTTOM - contentTop;

    const tops = blocks.map((b) => b.y);
    const bottoms = blocks.map((b) => b.y + b.h);
    const contentSpan = Math.max(...bottoms) - Math.min(...tops);
    // Keep the >0.5 MAJORITY bar — do NOT tighten. The single-line-number
    // constraint caps how full a narrow 3-stat column can get, so a tighter
    // "real fill" assertion would spuriously fail a faithful migration.
    expect(contentSpan / derivedHeight).toBeGreaterThan(0.5);
  });

  it('never overflows the bottom margin', () => {
    const stats: StatItem[] = [
      { value: '94.4', unit: '%', label: 'Water savings', comparison: 'vs 30% baseline' },
      { value: '35', unit: '%', label: 'Overhead reduction', comparison: 'down from 60%' },
      { value: '12', unit: 'MW', label: 'Cooling capacity', comparison: 'rack-scale' },
    ];
    const blocks = statBlocks(stats);
    const epsilon = 0.1; // half a slide-pixel
    for (const b of blocks) {
      expect(b.y + b.h).toBeLessThanOrEqual(REGION_BOTTOM + epsilon);
    }
  });

  it('places per-row baselines for the 4-stat 2×2 grid (top row baseline ≠ bottom row baseline)', () => {
    const stats: StatItem[] = [
      { value: '94', unit: '%', label: 'a' },
      { value: '35', unit: '%', label: 'b' },
      { value: '12', unit: 'MW', label: 'c' },
      { value: '7', unit: 'kW', label: 'd' },
    ];
    const blocks = statBlocks(stats);
    const numbers = stats.map((s) => blocks.find((b) => b.text === s.value)!);
    const topRowBaseline = numbers[0]!.y + numbers[0]!.measuredHeightPct;
    const bottomRowBaseline = numbers[2]!.y + numbers[2]!.measuredHeightPct;
    expect(bottomRowBaseline - topRowBaseline).toBeGreaterThan(20);
    // Within each row, the two numbers' bottoms align.
    const topPairSpread =
      Math.abs(
        numbers[1]!.y + numbers[1]!.measuredHeightPct - (numbers[0]!.y + numbers[0]!.measuredHeightPct),
      );
    const bottomPairSpread =
      Math.abs(
        numbers[3]!.y + numbers[3]!.measuredHeightPct - (numbers[2]!.y + numbers[2]!.measuredHeightPct),
      );
    expect(topPairSpread).toBeLessThan(0.5);
    expect(bottomPairSpread).toBeLessThan(0.5);
  });
});

/**
 * Title-hug + derived row bands (L2 fit migration).
 *
 * The stat envelope is no longer the frozen STAT_POSITIONS band — it derives
 * from the title's measured bottom and is partitioned into equal rows via
 * fitMeasuredStack. These lock: (1) a taller title pushes the stats down;
 * (2) the 4-stat rows are equal-split and the bottom row derives from the
 * title (not frozen at y:55); (3) the band stays the full available region so
 * the adaptive number still grows to fill it (no circular collapse).
 */
describe('DATA_EMPHASIS — title-hug + derived row bands', () => {
  const REGION_BOTTOM = 100 - MARGIN.bottom; // 94

  function layoutFor(title: string, stats: StatItem[]): TextBlock[] {
    const deck = buildDeck([makeSlide(0, 'data_emphasis', { title, stats })]);
    return new LayoutPass().layoutSlide(deck.slides[0]!, deck).textBlocks;
  }

  const TWO_STAT: StatItem[] = [
    { value: '94.4', unit: '%', label: 'Water savings' },
    { value: '35', unit: '%', label: 'Overhead' },
  ];
  // Long enough to wrap onto a second line in the full-width title band.
  const LONG_TITLE =
    'A deliberately long data emphasis headline written to wrap across two full lines inside the title band area';

  const minStatTop = (blocks: TextBlock[], titleText: string): number =>
    Math.min(...blocks.filter((b) => b.text !== titleText).map((b) => b.y));

  it('a 2-line title pushes the stat region down vs a 1-line title', () => {
    const shortBlocks = layoutFor('Short', TWO_STAT);
    const longBlocks = layoutFor(LONG_TITLE, TWO_STAT);
    const shortTitle = shortBlocks.find((b) => b.text === 'Short')!;
    const longTitle = longBlocks.find((b) => b.text === LONG_TITLE)!;

    // The long title genuinely wraps taller.
    expect(longTitle.measuredHeightPct).toBeGreaterThan(shortTitle.measuredHeightPct);

    const shortStatTop = minStatTop(shortBlocks, 'Short');
    const longStatTop = minStatTop(longBlocks, LONG_TITLE);

    // The taller title pushes the whole stat region down — a frozen y:14 would not move.
    expect(longStatTop).toBeGreaterThan(shortStatTop);
    // No stat intrudes above the title's measured bottom + the title gap.
    expect(longStatTop).toBeGreaterThanOrEqual(
      longTitle.y + longTitle.measuredHeightPct + TITLE_GAP - 0.5,
    );
  });

  it('4-stat: equal row bands, bottom row derived from the title (not frozen at y:55)', () => {
    // Identical-format values in both rows → symmetric per-row centering, so the
    // top→bottom baseline pitch equals the band pitch (equalBandH + ROW_GAP).
    const stats: StatItem[] = [
      { value: '94', unit: '%', label: 'a' },
      { value: '35', unit: '%', label: 'b' },
      { value: '12', unit: '%', label: 'c' },
      { value: '70', unit: '%', label: 'd' },
    ];
    const blocks = layoutFor('Grid', stats);
    const title = blocks.find((b) => b.text === 'Grid')!;
    const numbers = stats.map((s) => blocks.find((b) => b.text === s.value)!);

    const contentTop = title.y + title.measuredHeightPct + TITLE_GAP;
    const contentH = REGION_BOTTOM - contentTop;
    const equalBandH = (contentH - ROW_GAP) / 2;

    const pitch =
      numbers[2]!.y + numbers[2]!.measuredHeightPct - (numbers[0]!.y + numbers[0]!.measuredHeightPct);
    expect(Math.abs(pitch - (equalBandH + ROW_GAP))).toBeLessThan(1);

    // Derived, not frozen: a 2-line title shifts the bottom row down.
    const longBlocks = layoutFor(LONG_TITLE, stats);
    const longTitle = longBlocks.find((b) => b.text === LONG_TITLE)!;
    const longBottomRowNumber = longBlocks.find((b) => b.text === '12')!;
    expect(longTitle.measuredHeightPct).toBeGreaterThan(title.measuredHeightPct);
    expect(longBottomRowNumber.y).toBeGreaterThan(numbers[2]!.y);
  });

  it('keeps the number above its tier (band stays region-derived; fill not collapsed)', () => {
    // Terse single-char values + labels: the number grows above the static
    // displayLarge tier toward the adaptive ceiling. The circular-collapse bug
    // would pin numberRegionHeight to the number's own size and crater it back
    // to ~the probe floor.
    const stats: StatItem[] = [
      { value: '9', unit: '%', label: 'a' },
      { value: '8', unit: '%', label: 'b' },
      { value: '7', unit: '%', label: 'c' },
    ];
    const number = layoutFor('Terse', stats).find((b) => b.text === '9')!;
    expect(number.fontSize).toBeGreaterThan(FONT_SIZES.displayLarge.max);
  });
});
