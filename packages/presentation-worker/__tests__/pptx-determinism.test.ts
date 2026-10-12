/**
 * Two renders of one deck produce the same PPTX bytes (real pptxgenjs, no mock).
 *
 * PptxGenJS writes the wall-clock second into docProps/core.xml and JSZip dates
 * every entry, so without normalization two renders a second apart differ.
 */

import JSZip from 'jszip';
import PptxGenJS from 'pptxgenjs';
import { describe, expect, it } from 'vitest';
import { LayoutPass } from '../src/layout-pass.js';
import { PptxRenderer } from '../src/renderers/pptx-renderer.js';
import { FIXED_PPTX_TIME, normalizePptx } from '../src/renderers/pptx-determinism.js';
import { buildTestDeck, makeSlide } from './helpers.js';

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

// Text-only slides: an image would make pptxgenjs fetch it over the network.
async function render(): Promise<Buffer> {
  const deck = buildTestDeck([
    makeSlide('title_hero', { title: 'Orol dengizi', subtitle: 'Suv balansi' }, 0),
    makeSlide('content_split', { title: 'Sabablar', bullets: ['Sug\u2018orish', 'Iqlim'] }, 1),
    makeSlide('content_split', { title: 'Xulosa' }, 2),
  ]);
  const layout = new LayoutPass().layout(deck);
  return new PptxRenderer().render(deck, layout);
}

async function rawPptx(): Promise<Buffer> {
  const pptx = new PptxGenJS();
  pptx.title = 'raw';
  pptx.addSlide().addText('one', { x: 1, y: 1, w: 4, h: 1 });
  return (await pptx.write({ outputType: 'nodebuffer' })) as Buffer;
}

describe('PPTX determinism', () => {
  it('unnormalized pptxgenjs output changes between renders a second apart', async () => {
    const first = await rawPptx();
    await sleep(1100);
    const second = await rawPptx();
    expect(first.equals(second)).toBe(false);
  });

  it('two renders of one deck a second apart are byte-identical', async () => {
    const first = await render();
    await sleep(1100);
    const second = await render();
    expect(second.equals(first)).toBe(true);
  }, 30_000);

  it('the package carries the fixed timestamps and stays a valid PPTX', async () => {
    const zip = await JSZip.loadAsync(await render());
    const core = await zip.file('docProps/core.xml')!.async('string');
    const stamp = FIXED_PPTX_TIME.toISOString().replace(/\.\d{3}Z$/, 'Z');
    expect(core).toContain(`<dcterms:created xsi:type="dcterms:W3CDTF">${stamp}</dcterms:created>`);
    expect(core).toContain(`<dcterms:modified xsi:type="dcterms:W3CDTF">${stamp}</dcterms:modified>`);
    const names = Object.keys(zip.files);
    expect(names).toEqual([...names].sort());
    expect(names).toContain('[Content_Types].xml');
    expect(names).toContain('ppt/presentation.xml');
    expect(names.filter((name) => zip.files[name]!.dir)).toEqual([]);
  }, 30_000);

  it('normalizing is idempotent', async () => {
    const once = await normalizePptx(await rawPptx());
    expect((await normalizePptx(once)).equals(once)).toBe(true);
  });
});
