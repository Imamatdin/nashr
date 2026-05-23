import { describe, expect, it } from 'vitest';
import {
  checkSlideOverflow,
  measureText,
  type MeasureOptions,
} from '../src/text-measure.js';

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

  it('treats a single very long word as a single line that may exceed maxWidth', () => {
    const result = measureText(
      baseOpts({ text: 'Supercalifragilisticexpialidocious', maxWidth: 100, maxHeight: 80 }),
    );
    expect(result.lineCount).toBe(1);
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

  it('measures the sCO2 title as a single line in the real 1632px title region', () => {
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
