import { mkdir } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { VIEWPORTS, launchBrowser, mockApi, mockSupabase, seedSession, settle } from "./lib.mjs";

const BASE = (process.env.BASE_URL ?? "http://localhost:3000").replace(/\/$/, "");
const OUT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..", "review", "redesign_shots");

async function shoot(browser, { name, url, theme, width, session = true, supabase = {}, api = {}, drive, waitFor }) {
  const ctx = await browser.newContext({ viewport: { width, height: width > 600 ? 900 : 844 }, deviceScaleFactor: 2 });
  const page = await ctx.newPage();
  await page.addInitScript((t) => localStorage.setItem("nashr.theme", t), theme);
  if (session) await seedSession(page);
  await mockSupabase(page, supabase);
  await mockApi(page, api);
  let status = "OK";
  try {
    await page.goto(`${BASE}${url}`, { waitUntil: "domcontentloaded", timeout: 30000 });
    await settle(page);
    if (drive) { await drive(page).catch((e) => { status = `WARN drive: ${String(e).split("\n")[0]}`; }); }
    if (waitFor) { await page.waitForSelector(waitFor, { timeout: 15000 }).catch((e) => { status = `WARN waitFor ${waitFor}: ${String(e).split("\n")[0]}`; }); }
    await settle(page);
    await page.screenshot({ path: path.join(OUT, `${name}.png`), fullPage: true });
  } catch (e) { status = `FAIL ${String(e).split("\n")[0]}`; }
  console.log(`${name}.png  ${status}`);
  await ctx.close();
}

// Drive /new to the attached + confirm states.
async function driveAttach(page) {
  await page.waitForSelector("[data-promptbar] textarea", { timeout: 15000 });
  await page.fill("[data-promptbar] textarea", "Yoritish davri va uning merosi");
  await page.setInputFiles("[data-promptbar] input[type=file]", {
    name: "yoritish-davri-tarixi.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF-1.4 stub"),
  });
  await page.waitForSelector(".new-uploads", { timeout: 15000 });
  await page.waitForTimeout(800);
}
async function driveMenu(page) {
  await page.waitForSelector("[data-promptbar] textarea", { timeout: 15000 });
  await page.fill("[data-promptbar] textarea", "@");
  await page.waitForTimeout(500);
}
async function driveConfirm(page) {
  await driveAttach(page);
  await page.click("[data-promptbar] button[aria-label='Yuborish']");
  await page.waitForSelector(".new-confirm", { timeout: 15000 });
  await page.waitForTimeout(500);
}
async function driveRefusal(page) {
  await page.waitForSelector("[data-promptbar] textarea", { timeout: 15000 });
  await page.fill("[data-promptbar] textarea", "Yoritish davri va uning merosi");
  await page.click("[data-promptbar] button[aria-label='Yuborish']");
  await page.waitForSelector(".new-confirm", { timeout: 15000 });
  await page.click(".new-confirm button[aria-label='Send answers'], .new-confirm .approval-send, .new-confirm button:has-text('Boshlash')").catch(() => {});
  // fire the single radio option to submit
  await page.click(".new-confirm [role='radio'], .new-confirm button:has-text('Ha, boshlash')").catch(() => {});
  await page.waitForSelector(".state-note", { timeout: 15000 }).catch(() => {});
  await page.waitForTimeout(500);
}

const browser = await launchBrowser();
await mkdir(OUT, { recursive: true });
const W = VIEWPORTS.desktop.width, P = VIEWPORTS.phone.width;

// /new
for (const theme of ["light", "dark"]) {
  await shoot(browser, { name: `new-${theme}-1440`, url: "/new", theme, width: W });
  await shoot(browser, { name: `new-${theme}-390`, url: "/new", theme, width: P });
  await shoot(browser, { name: `new-attached-${theme}-1440`, url: "/new", theme, width: W, drive: driveAttach });
  await shoot(browser, { name: `new-confirm-${theme}-1440`, url: "/new", theme, width: W, drive: driveConfirm });
}
await shoot(browser, { name: "new-menu-light-1440", url: "/new", theme: "light", width: W, drive: driveMenu });
await shoot(browser, { name: "new-402-light-1440", url: "/new", theme: "light", width: W, api: { enqueue: "credit" }, drive: driveRefusal });
await shoot(browser, { name: "new-429-light-1440", url: "/new", theme: "light", width: W, api: { enqueue: "limit" }, drive: driveRefusal });

// workspace
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
