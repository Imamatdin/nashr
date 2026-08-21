// OG image 1200x630 for Nashr gate (b).
// usage: node build_og.mjs <hero-full.webp> <out.png>
import { chromium } from 'playwright';
import { readFileSync } from 'node:fs';
import { extname } from 'node:path';

const PLATE = process.argv[2];
const OUT = process.argv[3];

const mime = extname(PLATE).toLowerCase() === '.png' ? 'image/png' : 'image/webp';
const plateUri = `data:${mime};base64,${readFileSync(PLATE).toString('base64')}`;

const html = `<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Literata:wght@700&family=Source+Sans+3:wght@400&display=swap" rel="stylesheet">
<style>
  html,body{margin:0;padding:0}
  /* Flexoki: paper #FFFCF0 ground, base-950 #1C1B1A ink, base-700 #575653
     secondary text, base-200 #CECDC3 rules, base-50 #F2F0E5 plate surface. */
  #og{width:1200px;height:630px;background:#FFFCF0;display:flex;align-items:center;
      font-kerning:normal;-webkit-font-smoothing:antialiased}
  #left{width:600px;padding:0 0 0 84px;box-sizing:border-box}
  #mark{font-family:'Literata',serif;font-weight:700;font-size:130px;line-height:1;
        color:#1C1B1A;letter-spacing:-0.015em;margin:0}
  #rule{width:110px;height:1px;background:#CECDC3;margin:34px 0 30px}
  #sub{font-family:'Source Sans 3',sans-serif;font-weight:400;font-size:30px;
       line-height:1.35;color:#575653;margin:0;max-width:560px;white-space:nowrap}
  #right{width:600px;height:630px;display:flex;align-items:center;justify-content:center;
         box-sizing:border-box;padding-right:84px}
  #frame{border:1px solid #CECDC3;padding:14px;background:#F2F0E5}
  #frame img{display:block;width:404px;height:404px;object-fit:cover;object-position:75% 50%}
</style>
<div id="og">
  <div id="left">
    <p id="mark">Nashr</p>
    <div id="rule"></div>
    <p id="sub">Manbaga asoslangan akademik nashriyot</p>
  </div>
  <div id="right"><div id="frame"><img src="${plateUri}"></div></div>
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
    document.fonts.load('700 130px Literata'),
    document.fonts.load('400 30px "Source Sans 3"'),
  ]),
);
await page.locator('#og').screenshot({ path: OUT });
await browser.close();
console.log('wrote', OUT);
