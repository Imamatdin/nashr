/**
 * Debug renderer for the data_emphasis + flow_process fixtures used to
 * eyeball the feat/layout-fill geometry. Writes HTML + per-slide PNGs
 * at 1920x1080 into ../debug/out/ (the debug/ tree is gitignored;
 * this script is committed under scripts/ so it persists across branches).
 *
 * Usage: `node scripts/render-fixture.mjs <suffix>` from the worker
 * package root. Suffix is appended to each output filename, e.g.
 * "before" / "after". Defaults to "current".
 */

import { chromium } from 'playwright';
import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { LayoutPass } from '../dist/layout-pass.js';
import { HtmlRenderer } from '../dist/renderers/html-renderer.js';

const __dirname = dirname(fileURLToPath(import.meta.url));
const outDir = resolve(__dirname, '..', 'debug', 'out');
mkdirSync(outDir, { recursive: true });

const suffix = process.argv[2] ?? 'current';

const design = {
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
};

const deck = {
  project_id: 'fix-test',
  title: 'Layout fill probe',
  language: 'en',
  created_at: '2026-05-26T00:00:00Z',
  design,
  interview: {},
  export_formats: ['html'],
  slides: [
    {
      slide_index: 0,
      slide_type: 'data_emphasis',
      source_claim_ids: [],
      content: {
        title: 'Cooling economics',
        stats: [
          {
            value: '1.58',
            unit: 'PUE',
            label: 'Power Usage Effectiveness',
            highlight: true,
            comparison: 'vs 2.0 industry average',
          },
          {
            value: '94.4',
            unit: '%',
            label: 'Water savings',
            comparison: 'vs evaporative tower',
          },
          {
            value: '12',
            unit: 'MW',
            label: 'Rack-scale capacity',
            comparison: '1.4 kW/L coolant flux',
          },
        ],
      },
    },
    {
      slide_index: 1,
      slide_type: 'data_emphasis',
      source_claim_ids: [],
      content: {
        title: 'Stack economics — four levers',
        stats: [
          { value: '1.58', unit: 'PUE', label: 'Power Usage Effectiveness', highlight: true },
          { value: '94.4', unit: '%', label: 'Water savings' },
          { value: '12', unit: 'MW', label: 'Rack-scale capacity' },
          { value: '3.2', unit: 'yr', label: 'Payback period' },
        ],
      },
    },
    {
      slide_index: 2,
      slide_type: 'flow_process',
      source_claim_ids: [],
      content: {
        title: 'Single-phase sCO2 cooling loop',
        steps: [
          {
            label: 'Heat capture',
            description: 'Two-phase microchannels lift heat off the silicon die.',
          },
          {
            label: 'Vapour transport',
            description: 'Saturated sCO2 carries the load to the rejection stage.',
          },
          {
            label: 'Condensation',
            description: 'Dry coolers reject heat to ambient without water evaporation.',
          },
          {
            label: 'Pump return',
            description: 'A diaphragm pump cycles the working fluid back to the racks.',
          },
          {
            label: 'Control loop',
            description: 'PID controllers maintain stable saturation across the array.',
          },
        ],
      },
    },
  ],
};

const layout = new LayoutPass().layout(deck);
const html = new HtmlRenderer().render(deck, layout);
const htmlPath = join(outDir, `fixture_${suffix}.html`);
writeFileSync(htmlPath, html, 'utf8');
console.log(`wrote ${htmlPath}`);

const browser = await chromium.launch();
const context = await browser.newContext({ viewport: { width: 1920, height: 1080 } });
const page = await context.newPage();
await page.goto(`file://${htmlPath.replaceAll('\\', '/')}`);

for (let i = 0; i < deck.slides.length; i++) {
  await page.evaluate((idx) => {
    document.querySelectorAll('.slide').forEach((el, j) => {
      el.classList.toggle('active', j === idx);
    });
  }, i);
  await page.waitForTimeout(150);
  const out = join(outDir, `slide_${i + 1}_${deck.slides[i].slide_type}_${suffix}.png`);
  await page.screenshot({ path: out, fullPage: false });
  console.log(`wrote ${out}`);
}

await browser.close();
