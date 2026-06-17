import { describe, expect, it } from 'vitest';
import {
  checkSlideOverflow,
  measureText,
  type MeasureOptions,
} from '../src/text-measure.js';
import { measureLineWidthPx } from '../src/font-metrics.js';

/**
 * Mirrors RENDER_WIDTH_SAFETY in text-measure.ts. Replicated (not imported) so
 * these tests don't force exporting an internal safety constant, and so the
 * expected line counts are computed the same way the function computes the
 * effective max width: nominal * RENDER_WIDTH_SAFETY.
 */
const RENDER_WIDTH_SAFETY = 0.78;

function baseOpts(overrides: Partial<MeasureOptions> = {}): MeasureOptions {
  return {
    text: 'Hello world',
    fontSize: 24,
    fontFamily: 'Inter',
    fontWeight: 'normal',
    maxWidth: 800,
    maxHeight: 200,
    lineHeight: 1.5,
    ...overrides,
  };
}

describe('measureText', () => {
  it('measures a single short line as one line', () => {
    const result = measureText(baseOpts({ text: 'Hello world' }));
    expect(result.lineCount).toBe(1);
    expect(result.overflow).toBe(false);
    expect(result.fitsInBox).toBe(true);
  });

  it('wraps a long string to multiple lines when maxWidth is small', () => {
    const long = 'The quick brown fox jumps over the lazy dog three times in a row.';
    const wide = measureText(baseOpts({ text: long, maxWidth: 1200 }));
    const narrow = measureText(baseOpts({ text: long, maxWidth: 200 }));
    expect(narrow.lineCount).toBeGreaterThan(wide.lineCount);
  });

  it('detects overflow when wrapped height exceeds maxHeight', () => {
    const long = 'Word '.repeat(200).trim();
    const result = measureText(baseOpts({ text: long, maxWidth: 200, maxHeight: 50 }));
    expect(result.overflow).toBe(true);
    expect(result.fitsInBox).toBe(false);
  });

  it('returns zero metrics for empty text', () => {
    const result = measureText(baseOpts({ text: '' }));
    expect(result.lineCount).toBe(0);
    expect(result.width).toBe(0);
    expect(result.height).toBe(0);
    expect(result.fitsInBox).toBe(true);
  });

  it('measures bold text wider than regular text at the same size', () => {
    const regular = measureText(
      baseOpts({ text: 'Some standard heading text', fontWeight: 'normal' }),
    );
    const bold = measureText(
      baseOpts({ text: 'Some standard heading text', fontWeight: 'bold' }),
    );
    expect(bold.width).toBeGreaterThan(regular.width);
  });

  it('measures a serif font wider than a sans-serif at the same size', () => {
    const sans = measureText(
      baseOpts({ text: 'Some equivalent heading text', fontFamily: 'Inter' }),
    );
    const serif = measureText(
      baseOpts({ text: 'Some equivalent heading text', fontFamily: 'EB Garamond' }),
    );
    expect(serif.width).toBeGreaterThan(sans.width);
  });

  it('flags overflow when lineCount exceeds what maxHeight permits', () => {
    const long = 'Wrap '.repeat(60).trim();
    const result = measureText(baseOpts({ text: long, maxWidth: 200, maxHeight: 100 }));
    expect(result.lineCount).toBeGreaterThan(2);
    expect(result.overflow).toBe(true);
  });

  it('produces more wrapped lines at a larger font size in the same box', () => {
    const text = 'A reasonably long sentence that needs multiple lines to fit comfortably.';
    const small = measureText(baseOpts({ text, fontSize: 14, maxWidth: 300, maxHeight: 1000 }));
    const large = measureText(baseOpts({ text, fontSize: 24, maxWidth: 300, maxHeight: 1000 }));
    expect(large.lineCount).toBeGreaterThanOrEqual(small.lineCount);
  });

  it('treats explicit mono fonts as wider than sans-serif', () => {
    const sans = measureText(baseOpts({ text: 'function compute() {}', fontFamily: 'Inter' }));
    const mono = measureText(
      baseOpts({ text: 'function compute() {}', fontFamily: 'JetBrains Mono' }),
    );
    expect(mono.width).toBeGreaterThan(sans.width);
  });

  it('wraps a single over-long word to ceil(width / effectiveMaxWidth) lines', () => {
    // Corrects the prior contract ("a single very long word stays one line that
    // may exceed maxWidth"): the browser and PPTX/LibreOffice character-break an
    // over-long token, so the measurer must count ceil(tokenWidth / effective
    // maxWidth) lines or anything stacked beneath it is placed too high.
    const text = 'Supercalifragilisticexpialidocious';
    const fontSize = 24;
    const nominalMaxWidth = 100;
    const tokenWidth = measureLineWidthPx(text, 'Inter', 'normal', fontSize);
    const expected = Math.ceil(tokenWidth / (nominalMaxWidth * RENDER_WIDTH_SAFETY));
    expect(expected).toBeGreaterThan(1); // sanity: this token is genuinely over-long
    const result = measureText(
      baseOpts({ text, fontSize, maxWidth: nominalMaxWidth, maxHeight: 10000 }),
    );
    expect(result.lineCount).toBe(expected);
  });
});

describe('measureText — over-long token wrapping (intra-token line count)', () => {
  // The data_emphasis layout stacks a stat's unit/label/comparison beneath the
  // number using the number's MEASURED height. If an over-long value is counted
  // as one line but rendered across two, the unit collides with its lower line.
  // These tests pin the corrected line count at the real font/size/width the
  // layout uses. Widths come from measureLineWidthPx so expectations track the
  // actual vendored-font advances, not a guessed constant.

  const DISPLAY_LARGE = 64; // FONT_SIZES.displayLarge.max — the data_emphasis number tier
  const STAT_COL_3_NOMINAL = (28 / 100) * 1920; // 3-stat column width: 537.6px

  function num(text: string, maxWidth: number, fontSize = DISPLAY_LARGE): MeasureOptions {
    return {
      text,
      fontSize,
      fontFamily: 'IBM Plex Sans',
      fontWeight: 'bold',
      maxWidth,
      maxHeight: 10000,
      lineHeight: 1.1,
    };
  }

  it('counts a single over-long token as ceil(tokenWidth / effectiveMaxWidth) (acceptance 1)', () => {
    const text = 'Supercalifragilisticexpialidocious';
    const nominalMaxWidth = 300;
    const tokenWidth = measureLineWidthPx(text, 'IBM Plex Sans', 'bold', DISPLAY_LARGE);
    const expected = Math.ceil(tokenWidth / (nominalMaxWidth * RENDER_WIDTH_SAFETY));
    expect(expected).toBeGreaterThan(1); // sanity: genuinely over-long at this size/box
    const result = measureText(num(text, nominalMaxWidth));
    expect(result.lineCount).toBe(expected);
  });

  it('wraps a genuinely over-long stat value to >= 2 lines at the number tier (acceptance 2)', () => {
    // A triple-range value, wider than the 3-stat column even at the display
    // tier. (The task originally named "1.56–1.58", but that value measures
    // 307.7px < the 419px effective column — it is NOT over-long and renders on
    // one line; see the regression test below. This is a value that genuinely
    // triggers the wrap.)
    const text = '1.560–1.580–1.600';
    const tokenWidth = measureLineWidthPx(text, 'IBM Plex Sans', 'bold', DISPLAY_LARGE);
    const expected = Math.ceil(tokenWidth / (STAT_COL_3_NOMINAL * RENDER_WIDTH_SAFETY));
    const result = measureText(num(text, STAT_COL_3_NOMINAL));
    expect(result.lineCount).toBeGreaterThanOrEqual(2);
    expect(result.lineCount).toBe(expected);
  });

  it('keeps a short stat value on one line (acceptance 3, no regression)', () => {
    expect(measureText(num('1.08', STAT_COL_3_NOMINAL)).lineCount).toBe(1);
    // "1.56–1.58" from the original report is in fact NOT over-long: it fits the
    // 3-stat column on one line. Pinning this guards against re-introducing a
    // spurious wrap for the value the fix was mistakenly thought to break.
    expect(measureText(num('1.56–1.58', STAT_COL_3_NOMINAL)).lineCount).toBe(1);
  });

  it('caps an over-long token width at the effective maxWidth, not the raw token width (acceptance 4)', () => {
    const text = '1.560–1.580–1.600';
    const nominalMaxWidth = STAT_COL_3_NOMINAL;
    const effectiveMaxWidth = nominalMaxWidth * RENDER_WIDTH_SAFETY;
    const rawTokenWidth = measureLineWidthPx(text, 'IBM Plex Sans', 'bold', DISPLAY_LARGE);
    expect(rawTokenWidth).toBeGreaterThan(effectiveMaxWidth); // precondition: over-long
    const result = measureText(num(text, nominalMaxWidth));
    expect(result.width).toBeLessThanOrEqual(effectiveMaxWidth);
    expect(result.width).toBeLessThan(rawTokenWidth);
  });

  it('counts a token following an over-long token on its own line', () => {
    // Regression guard for the off-by-one that a literal "reset currentLineWidth
    // to 0" would introduce: the word after an over-long token must land on a
    // new, counted line rather than silently reclaiming the token's last line.
    const overLong = 'Supercalifragilisticexpialidocious';
    const overLongLines = measureText(num(overLong, 300)).lineCount;
    const withTrailingWord = measureText(num(`${overLong} tail`, 300)).lineCount;
    expect(withTrailingWord).toBe(overLongLines + 1);
  });
});

describe('measureText — true glyph widths (IBM Plex Sans, vendored variable font)', () => {
  const SC02 = 'Supercritical CO2 Is the Future of Data Center Cooling';
  const TITLE_REGION_PX = 1632; // 85% of the 1920px slide, the title_hero title region

  function plex(text: string, maxWidth: number): MeasureOptions {
    return {
      text,
      fontSize: 64,
      fontFamily: 'IBM Plex Sans',
      fontWeight: 'bold',
      maxWidth,
      maxHeight: 10000,
      lineHeight: 1.1,
    };
  }

  // skipped on Windows: no fontconfig, Plex glyph metrics unavailable; re-enable on
  // Linux/droplet where fonts resolve — see docs/BUILD_STATE.md (plan item 11 / F).
  it.skip('measures the sCO2 title as a single line in the real 1632px title region', () => {
    // True glyph width of this title at bold 64 is ~1617px, which fits the
    // 1632px region on one line. The old char-ratio model (with its 1.12
    // inflation hack) wrongly reported 2 lines here.
    const result = measureText(plex(SC02, TITLE_REGION_PX));
    expect(result.lineCount).toBe(1);
    expect(result.width).toBeGreaterThan(1500);
    expect(result.width).toBeLessThan(TITLE_REGION_PX);
  });

  it('wraps the sCO2 title to three lines in a narrow 800px box', () => {
    const result = measureText(plex(SC02, 800));
    expect(result.lineCount).toBe(3);
  });

  it('measures a short title as a single line', () => {
    const result = measureText(plex('The Crisis', TITLE_REGION_PX));
    expect(result.lineCount).toBe(1);
  });
});

describe('checkSlideOverflow', () => {
  it('returns no issues when every block fits', () => {
    const issues = checkSlideOverflow([
      { field: 'title', text: 'Short title', options: baseOpts({ text: 'Short title' }) },
      { field: 'body', text: 'A short body.', options: baseOpts({ text: 'A short body.' }) },
    ]);
    expect(issues).toHaveLength(0);
  });

  it('flags an overflowing block with a helpful suggestion', () => {
    const long = 'Word '.repeat(400).trim();
    const issues = checkSlideOverflow([
      {
        field: 'body',
        text: long,
        options: baseOpts({ text: long, maxWidth: 200, maxHeight: 60 }),
      },
    ]);
    expect(issues).toHaveLength(1);
    const issue = issues[0]!;
    expect(issue.field).toBe('body');
    expect(['reduce font size', 'truncate', 'split slide']).toContain(issue.suggestion);
  });

  it('reports lineCount and maxLines on each issue', () => {
    const long = 'Word '.repeat(50).trim();
    const issues = checkSlideOverflow([
      {
        field: 'body',
        text: long,
        options: baseOpts({ text: long, maxWidth: 250, maxHeight: 80 }),
      },
    ]);
    expect(issues).toHaveLength(1);
    expect(issues[0]!.lineCount).toBeGreaterThan(issues[0]!.maxLines);
  });
});
