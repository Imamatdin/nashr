/**
 * PdfRenderer — produces a print-quality PDF by rendering the HTML
 * artifact in headless Chromium and printing each slide as one page.
 *
 * The PDF version is non-interactive by design:
 *   - Hidden content (quiz answers, true/false verdicts, fill-blank
 *     answers, debate frameworks, matching right column) is forced
 *     visible at half opacity so the PDF works as a printable study
 *     aid.
 *   - "Reveal" triggers and the on-screen progress bar/counter are
 *     hidden — they have no meaning on paper.
 *   - Each .slide becomes a 1920×1080 page with page-break-after.
 *
 * Playwright is loaded at runtime because the chromium binary is heavy
 * and isn't needed for the HTML or PPTX paths. Tests that don't set
 * RUN_PDF_TESTS=1 skip the suite and never touch the browser.
 */

import { chromium } from 'playwright';
import { HtmlRenderer } from './html-renderer.js';
import type { DeckLayout, DeckSpec } from '../types.js';

/** CSS injected before page.pdf() to make the HTML printable. */
const PRINT_CSS = `
@page {
  size: 1920px 1080px;
  margin: 0;
}
html, body {
  background: #fff !important;
  overflow: visible !important;
  height: auto !important;
}
.deck {
  position: static !important;
  width: auto !important;
  height: auto !important;
}
.slide {
  display: block !important;
  position: relative !important;
  width: 1920px !important;
  height: 1080px !important;
  page-break-after: always;
  break-after: page;
  overflow: hidden !important;
}
.slide:last-child { page-break-after: auto; break-after: auto; }
.slide-inner {
  transform: none !important;
  margin: 0 !important;
  position: relative !important;
  width: 1920px !important;
  height: 1080px !important;
}
.progress-bar, .slide-counter { display: none !important; }
.reveal-trigger { display: none !important; }
.interactive-hidden {
  display: block !important;
  opacity: 0.5 !important;
}
.interactive-option {
  pointer-events: none;
  cursor: default;
  text-decoration: none !important;
}
`;

export class PdfRenderer {
  /**
   * Render a deck to a PDF buffer. Spawns a headless Chromium for the
   * duration of the call and tears it down on exit, including in the
   * error path.
   */
  async render(deck: DeckSpec, layout: DeckLayout): Promise<Buffer> {
    const html = new HtmlRenderer().render(deck, layout);

    const browser = await chromium.launch({ headless: true });
    try {
      const context = await browser.newContext({
        viewport: { width: 1920, height: 1080 },
        deviceScaleFactor: 2,
      });
      const page = await context.newPage();

      await page.setContent(html, { waitUntil: 'networkidle' });
      await page.addStyleTag({ content: PRINT_CSS });
      await page.emulateMedia({ media: 'print' });

      const pdf = await page.pdf({
        width: '1920px',
        height: '1080px',
        printBackground: true,
        preferCSSPageSize: true,
      });

      return Buffer.from(pdf);
    } finally {
      await browser.close();
    }
  }
}
