// No-flash + landing-forced-light + persistence probe. Records the <html> class
// timeline from the earliest possible moment via an init-script MutationObserver.
import { chromium } from "playwright";
import { seedSession, mockApi, mockSupabase } from "./lib.mjs";
const BASE = (process.env.BASE_URL ?? "http://localhost:3000").replace(/\/$/, "");
const browser = await chromium.launch();
const cases = [
  { path: "/projects", stored: "dark", expect: "dark" },
  { path: "/projects", stored: "light", expect: "light" },
  { path: "/projects", stored: null, dark: true, expect: "dark" },
  { path: "/projects", stored: null, dark: false, expect: "light" },
  { path: "/", stored: "dark", expect: "light" },
  { path: "/", stored: null, dark: true, expect: "light" },
  { path: "/login", stored: "dark", expect: "dark" },
];
let bad = 0;
for (const c of cases) {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, colorScheme: c.dark ? "dark" : "light" });
  const page = await ctx.newPage();
  if (c.stored) await page.addInitScript((t) => localStorage.setItem("nashr.theme", t), c.stored);
  await page.addInitScript(() => {
    const log = [];
    window.__themeLog = log;
    const start = () => {
      const el = document.documentElement;
      if (!el) return false;
      log.push("init:" + el.className);
      new MutationObserver(() => log.push("mut:" + el.className)).observe(el, { attributes: true, attributeFilter: ["class"] });
      return true;
    };
    if (!start()) document.addEventListener("readystatechange", () => start(), { once: true });
  });
  await seedSession(page); await mockSupabase(page, {}); await mockApi(page, {});
  await page.goto(`${BASE}${c.path}`, { waitUntil: "load" });
  await page.waitForTimeout(1500);
  const late = await page.evaluate(() => ({ cls: document.documentElement.className, bg: getComputedStyle(document.body).backgroundColor, scheme: getComputedStyle(document.documentElement).colorScheme, log: window.__themeLog }));
  const lateDark = /\bdark\b/.test(late.cls);
  const states = late.log.map((e) => /\bdark\b/.test(e.slice(e.indexOf(":") + 1)));
  const flipped = states.some((s, i) => i > 0 && s !== states[i - 1]);
  const ok = lateDark === (c.expect === "dark") && !flipped;
  if (!ok) bad++;
  console.log(`${ok ? "OK  " : "FAIL"} ${c.path} stored=${c.stored ?? "-"} system=${c.dark ? "dark" : "light"} expect=${c.expect} final="${late.cls.replace(/__variable_\w+/g, "").trim()}" timeline=${JSON.stringify(late.log.map((e) => e.replace(/__variable_\w+/g, "").trim()))} body-bg=${late.bg} color-scheme=${late.scheme}`);
  await ctx.close();
}
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
const page = await ctx.newPage();
await seedSession(page); await mockSupabase(page, {}); await mockApi(page, {});
await page.goto(`${BASE}/projects`, { waitUntil: "load" });
const group = page.locator("[role='group'][aria-label='Mavzu']").first();
const toggles = await group.locator("button").count();
console.log(`theme toggle buttons found: ${toggles}`);
if (toggles >= 3) {
  await group.locator("button").nth(2).click();
  await page.waitForTimeout(300);
  const stored = await page.evaluate(() => localStorage.getItem("nashr.theme"));
  const live = await page.evaluate(() => document.documentElement.classList.contains("dark"));
  await page.reload({ waitUntil: "load" });
  const after = await page.evaluate(() => document.documentElement.classList.contains("dark"));
  await page.goto(`${BASE}/`, { waitUntil: "load" });
  const landing = await page.evaluate(() => document.documentElement.classList.contains("dark"));
  const ok = stored === "dark" && live && after && !landing;
  if (!ok) bad++;
  console.log(`${ok ? "OK  " : "FAIL"} persistence: stored=${stored} live-dark=${live} after-reload-dark=${after} landing-dark=${landing}`);
} else { bad++; console.log("FAIL no toggle group [aria-label=Mavzu] with >=3 buttons"); }
await browser.close();
process.exitCode = bad ? 1 : 0;
