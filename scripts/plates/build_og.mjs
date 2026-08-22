// OG image 1200x630 for Nashr. Paper ground, wordmark and subline left,
// a real deck render inside a rounded ink frame right.
// usage: node build_og.mjs <deck.jpg> <out.jpg>
import { chromium } from 'playwright';
import { readFileSync } from 'node:fs';
import { extname } from 'node:path';

const DECK = process.argv[2];
const OUT = process.argv[3];

const ext = extname(DECK).toLowerCase();
const mime = ext === '.png' ? 'image/png' : ext === '.webp' ? 'image/webp' : 'image/jpeg';
const deckUri = `data:${mime};base64,${readFileSync(DECK).toString('base64')}`;

const html = `<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Literata:wght@700&family=Source+Sans+3:wght@400&display=swap" rel="stylesheet">
<style>
  html,body{margin:0;padding:0}
  /* Flexoki: paper #FFFCF0 ground, base-950 #1C1B1A ink and frame interior,
     base-700 #575653 secondary text, base-150 #DAD8CE hairline. */
  #og{width:1200px;height:630px;background:#FFFCF0;display:flex;align-items:center;
      font-kerning:normal;-webkit-font-smoothing:antialiased}
  #left{width:470px;padding:0 0 0 72px;box-sizing:border-box}
  #mark{font-family:'Literata',serif;font-weight:700;font-size:104px;line-height:1;
        color:#1C1B1A;letter-spacing:-0.025em;margin:0}
  #rule{width:96px;height:1px;background:#DAD8CE;margin:30px 0 26px}
  #sub{font-family:'Source Sans 3',sans-serif;font-weight:400;font-size:27px;
       line-height:1.4;color:#575653;margin:0;max-width:340px}
  #right{width:730px;height:630px;display:flex;align-items:center;justify-content:flex-start;
         box-sizing:border-box}
  #frame{width:660px;border-radius:16px;overflow:hidden;background:#1C1B1A;
         box-shadow:0 0 0 1px #DAD8CE}
  #frame img{display:block;width:100%;height:auto}
</style>
<div id="og">
  <div id="left">
    <p id="mark">Nashr</p>
    <div id="rule"></div>
    <p id="sub">Manbaga asoslangan akademik nashriyot</p>
  </div>
  <div id="right"><div id="frame"><img src="${deckUri}"></div></div>
</div>`;

const browser = await chromium.launch();
const page = await browser.newPage({
  viewport: { width: 1200, height: 630 },
  deviceScaleFactor: 1,
});
await page.setContent(html, { waitUntil: 'networkidle' });
await page.evaluate(() => document.fonts.ready);
await page.evaluate(() =>
  Promise.all([
    document.fonts.load('700 104px Literata'),
    document.fonts.load('400 27px "Source Sans 3"'),
  ]),
);
await page.locator('#og').screenshot({ path: OUT, type: 'jpeg', quality: 88 });
await browser.close();
console.log('wrote', OUT);
