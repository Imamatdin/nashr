// DOM contrast probe: every visible text node's colour vs its effective background.
// usage: node _probe_contrast.mjs <path> <theme> [width] [--session] [--mocks]
import { chromium } from "playwright";
import { mockApi, mockSupabase, seedSession, settle, stubTelegramInert } from "./lib.mjs";

const [, , path = "/projects", theme = "light", widthArg = "1440", ...flags] = process.argv;
const width = Number(widthArg);
const BASE = (process.env.BASE_URL ?? "http://localhost:3000").replace(/\/$/, "");

const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width, height: width > 600 ? 900 : 844 } });
const page = await ctx.newPage();
await page.addInitScript((t) => localStorage.setItem("nashr.theme", t), theme);
if (flags.includes("--session")) await seedSession(page);
if (flags.includes("--mocks")) {
  await mockSupabase(page, {});
  await mockApi(page, {});
}
if (path.startsWith("/login")) await stubTelegramInert(page);
await page.goto(`${BASE}${path}`, { waitUntil: "domcontentloaded" });
await settle(page);

const result = await page.evaluate(() => {
  const parse = (s) => {
    const m = s.match(/rgba?\(([^)]+)\)/);
    if (!m) return null;
    const p = m[1].split(/[\s,\/]+/).filter(Boolean).map(Number);
    return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 };
  };
  const lum = ({ r, g, b }) => {
    const f = (c) => { c /= 255; return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4; };
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
  };
  const ratio = (a, b) => { const [h, l] = [lum(a), lum(b)].sort((x, y) => y - x); return (h + 0.05) / (l + 0.05); };
  const blend = (fg, bg) => ({ r: fg.r * fg.a + bg.r * (1 - fg.a), g: fg.g * fg.a + bg.g * (1 - fg.a), b: fg.b * fg.a + bg.b * (1 - fg.a), a: 1 });
  const bgOf = (el) => {
    let bg = { r: 255, g: 255, b: 255, a: 1 };
    const chain = [];
    for (let n = el; n; n = n.parentElement) chain.push(n);
    for (const n of chain.reverse()) {
      const c = parse(getComputedStyle(n).backgroundColor);
      if (c && c.a > 0) bg = blend(c, bg);
    }
    return bg;
  };
  const out = [];
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  let node;
  while ((node = walker.nextNode())) {
    const text = node.textContent.trim();
    if (text.length < 2) continue;
    const el = node.parentElement;
    if (!el) continue;
    const cs = getComputedStyle(el);
    if (cs.visibility === "hidden" || cs.display === "none" || Number(cs.opacity) === 0) continue;
    const rect = el.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) continue;
    if (el.closest("[aria-hidden='true']")) continue;
    const fg = parse(cs.color);
    if (!fg) continue;
    const bg = bgOf(el);
    const fgB = blend(fg, bg);
    const size = parseFloat(cs.fontSize);
    const bold = Number(cs.fontWeight) >= 700;
    const large = size >= 24 || (size >= 18.66 && bold);
    const r = ratio(fgB, bg);
    const need = large ? 3 : 4.5;
    out.push({ text: text.slice(0, 40), tag: el.tagName.toLowerCase(), cls: (el.className && typeof el.className === "string" ? el.className : "").slice(0, 50), fg: cs.color, bg: `rgb(${Math.round(bg.r)}, ${Math.round(bg.g)}, ${Math.round(bg.b)})`, size, ratio: Math.round(r * 100) / 100, need, pass: r >= need, disabled: Boolean(el.closest("[disabled], [aria-disabled='true'], .disabled")) });
  }
  return out;
});
await browser.close();
const fails = result.filter((r) => !r.pass && !r.disabled);
const disabledFails = result.filter((r) => !r.pass && r.disabled);
console.log(`${path} ${theme} ${width}: ${result.length} text nodes, ${fails.length} FAIL, ${disabledFails.length} disabled-exempt`);
for (const f of fails) console.log(`  FAIL ${f.ratio} (need ${f.need}) <${f.tag} class="${f.cls}"> "${f.text}" fg=${f.fg} bg=${f.bg} size=${f.size}`);
process.exitCode = fails.length ? 1 : 0;
