import { chromium } from 'playwright';
import { readFileSync } from 'node:fs';

const SVG = readFileSync(process.argv[2], 'utf8').trim();
const OUT_180 = process.argv[3];
const OUT_32 = process.argv[4];

const page_html = (size) => `<style>
html,body{margin:0;padding:0;background:transparent}
#m{width:${size}px;height:${size}px;display:block}
#m svg{width:${size}px;height:${size}px;display:block}
</style><div id="m">${SVG}</div>`;

const browser = await chromium.launch();
for (const [size, out] of [[180, OUT_180], [32, OUT_32]]) {
  const page = await browser.newPage({
    viewport: { width: size, height: size },
    deviceScaleFactor: 1,
  });
  await page.setContent(page_html(size), { waitUntil: 'load' });
  await page.locator('#m').screenshot({ path: out, omitBackground: true });
  await page.close();
}
await browser.close();
console.log('done');
