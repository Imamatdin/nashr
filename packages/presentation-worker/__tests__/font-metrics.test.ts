/**
 * font-metrics: true glyph measurement against the vendored TTFs, plus the
 * documented character-width fallback for families that resolve to no real
 * file. The variable fonts (IBM Plex Sans, Lora, Source Serif 4) must load
 * without crashing — the bracket-named IBMPlexSans[wdth,wght].ttf in
 * particular is the file the layout pass leans on for titles.
 */

import { describe, expect, it } from 'vitest';
import { getCharWidthRatio, measureLineWidthPx } from '../src/font-metrics.js';

describe('measureLineWidthPx — vendored variable fonts load and measure', () => {
  it('loads IBMPlexSans[wdth,wght].ttf and returns a positive glyph width', () => {
    // Explicit coverage of the bracket-named variable font: it must not throw
    // and must produce real (non-fallback-shaped) glyph metrics.
    const width = measureLineWidthPx('Supercritical', 'IBM Plex Sans', 'bold', 64);
    expect(Number.isFinite(width)).toBe(true);
    expect(width).toBeGreaterThan(0);
  });

  it('measures bold wider than normal for IBM Plex Sans (distinct wght instances)', () => {
    const text = 'Supercritical CO2 Cooling';
    const bold = measureLineWidthPx(text, 'IBM Plex Sans', 'bold', 64);
    const normal = measureLineWidthPx(text, 'IBM Plex Sans', 'normal', 64);
    expect(bold).toBeGreaterThan(normal);
  });

  it('loads the other vendored variable/static fonts without crashing', () => {
    for (const family of ['Lora', 'Source Serif 4', 'IBM Plex Serif']) {
      const width = measureLineWidthPx('Climate', family, 'bold', 48);
      expect(width).toBeGreaterThan(0);
    }
  });

  it('scales linearly with font size for a resolved font', () => {
    const at32 = measureLineWidthPx('Energy', 'IBM Plex Sans', 'normal', 32);
    const at64 = measureLineWidthPx('Energy', 'IBM Plex Sans', 'normal', 64);
    expect(at64).toBeCloseTo(at32 * 2, 1);
  });
});

describe('measureLineWidthPx — fallback for unresolved families', () => {
  it('falls back to the char-width ratio without throwing for an unknown family', () => {
    const family = 'Totally Made Up Font 9000';
    const text = 'hello';
    const width = measureLineWidthPx(text, family, 'normal', 40);
    // Fallback shape: length * fontSize * ratio.
    const expected = text.length * 40 * getCharWidthRatio(family, 'normal');
    expect(width).toBeCloseTo(expected, 5);
  });

  it('returns 0 for empty text', () => {
    expect(measureLineWidthPx('', 'IBM Plex Sans', 'bold', 64)).toBe(0);
  });
});

describe('getCharWidthRatio — fallback ratio model', () => {
  it('rates mono wider than sans and serif at least as wide as sans', () => {
    expect(getCharWidthRatio('JetBrains Mono', 'normal')).toBeGreaterThan(
      getCharWidthRatio('Inter', 'normal'),
    );
    expect(getCharWidthRatio('EB Garamond', 'normal')).toBeGreaterThanOrEqual(
      getCharWidthRatio('Inter', 'normal'),
    );
  });

  it('inflates bold over normal', () => {
    expect(getCharWidthRatio('Inter', 'bold')).toBeGreaterThan(
      getCharWidthRatio('Inter', 'normal'),
    );
  });
});
