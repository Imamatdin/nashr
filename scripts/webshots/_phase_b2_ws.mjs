import { mkdir } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { VIEWPORTS, launchBrowser, mockApi, mockSupabase, seedSession, settle } from "./lib.mjs";
const BASE = (process.env.BASE_URL ?? "http://localhost:3000").replace(/\/$/, "");
const OUT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..", "review", "redesign_shots");
async function shoot(browser, { name, url, theme, width, supabase = {}, api = {}, waitFor }) {
  const ctx = await browser.newContext({ viewport: { width, height: width > 600 ? 900 : 844 }, deviceScaleFactor: 2 });
  const page = await ctx.newPage();
  await page.addInitScript((t) => localStorage.setItem("nashr.theme", t), theme);
  await seedSession(page);
  await mockSupabase(page, supabase);
  await mockApi(page, api);
  let status = "OK";
  try {
    await page.goto(`${BASE}${url}`, { waitUntil: "domcontentloaded", timeout: 40000 });
    await settle(page);
    if (waitFor) await page.waitForSelector(waitFor, { timeout: 20000 }).catch((e) => { status = `WARN ${waitFor}: ${String(e).split("\n")[0]}`; });
    await settle(page);
    await page.screenshot({ path: path.join(OUT, `${name}.png`), fullPage: true });
  } catch (e) { status = `FAIL ${String(e).split("\n")[0]}`; }
  console.log(`${name}.png  ${status}`);
  await ctx.close();
}
const browser = await launchBrowser();
await mkdir(OUT, { recursive: true });
const W = VIEWPORTS.desktop.width, P = VIEWPORTS.phone.width;
const P1 = "/projects/p-1";
for (const theme of ["light", "dark"]) {
  await shoot(browser, { name: `workspace-running-${theme}-1440`, url: `${P1}?job=job-stub`, theme, width: W, waitFor: ".ws-steps" });
  await shoot(browser, { name: `workspace-failed-${theme}-1440`, url: `${P1}?job=job-stub`, theme, width: W, api: { jobStatus: "failed", jobError: "Manba fayli o‘qilmadi — PDF shifrlangan." }, waitFor: ".ws-failed" });
  await shoot(browser, { name: `workspace-deck-${theme}-1440`, url: P1, theme, width: W, api: { deckReady: true }, supabase: { shareToken: "share-stub-token" }, waitFor: ".ws-deck" });
  await shoot(browser, { name: `workspace-provenance-${theme}-1440`, url: P1, theme, width: W, api: { deckReady: true }, waitFor: ".ws-provenance" });
  await shoot(browser, { name: `workspace-${theme}-390`, url: `${P1}?job=job-stub`, theme, width: P, waitFor: ".ws-steps" });
}
await shoot(browser, { name: "workspace-queued-dark-1440", url: `${P1}?job=job-stub`, theme: "dark", width: W, api: { jobStatus: "queued" }, waitFor: ".ws-wait" });
await shoot(browser, { name: "workspace-idle-light-1440", url: P1, theme: "light", width: W, waitFor: ".ws-start" });
await browser.close();
console.log("done");
