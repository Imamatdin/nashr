/**
 * PdfRenderer tests.
 *
 * Skipped by default because they require:
 *   - Playwright installed (`npx playwright install chromium`)
 *   - A few seconds of cold-start Chromium per test
 *
 * Enable them locally with:
 *   RUN_PDF_TESTS=1 npm run test -- pdf-renderer
 *
 * The describe.skipIf guard means CI / standard `npm run test` stays
 * fast and does not depend on browser binaries.
 */

import { readFileSync } from 'fs';
import { join } from 'path';
import { describe, expect, it, vi } from 'vitest';
import { LayoutPass } from '../src/layout-pass.js';
import { PdfRenderer } from '../src/renderers/pdf-renderer.js';
import { HtmlRenderer } from '../src/renderers/html-renderer.js';
import { buildTestDeck, makeSlide } from './helpers.js';
import type { DeckSpec } from '../src/types.js';

const RUN_PDF_TESTS = process.env.RUN_PDF_TESTS === '1';

function loadFixture(): DeckSpec {
  const path = join(__dirname, 'fixtures', 'enlightenment.json');
  return JSON.parse(readFileSync(path, 'utf-8')) as DeckSpec;
}

describe.skipIf(!RUN_PDF_TESTS)('PdfRenderer', () => {
  it('returns a non-empty Buffer beginning with the PDF magic header', async () => {
    const deck = buildTestDeck([
      makeSlide('title_hero', { title: 'A' }, 0),
      makeSlide('content_split', { title: 'B' }, 1),
      makeSlide('section_break', { title: 'C' }, 2),
    ]);
    const layout = new LayoutPass().layout(deck);
    const pdf = await new PdfRenderer().render(deck, layout);
    expect(Buffer.isBuffer(pdf)).toBe(true);
    expect(pdf.length).toBeGreaterThan(1000);
    // PDFs start with the 5-byte signature "%PDF-".
    expect(pdf.slice(0, 5).toString('utf-8')).toBe('%PDF-');
  }, 60_000);

  it('delegates to HtmlRenderer for the source HTML', async () => {
    const deck = buildTestDeck([makeSlide('title_hero', { title: 'X' })]);
    const layout = new LayoutPass().layout(deck);
    const spy = vi.spyOn(HtmlRenderer.prototype, 'render');
    try {
      await new PdfRenderer().render(deck, layout);
      expect(spy).toHaveBeenCalledOnce();
    } finally {
      spy.mockRestore();
    }
  }, 60_000);

  it('renders the enlightenment fixture to a valid PDF', async () => {
    const deck = loadFixture();
    const layout = new LayoutPass().layout(deck);
    const pdf = await new PdfRenderer().render(deck, layout);
    expect(pdf.slice(0, 5).toString('utf-8')).toBe('%PDF-');
    expect(pdf.length).toBeGreaterThan(5000);
  }, 120_000);
});
