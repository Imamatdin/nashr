import { mkdir } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  VIEWPORTS,
  launchBrowser,
  mockApi,
  mockSupabase,
  mockTelegram,
  settle,
} from "./lib.mjs";

const BASE_URL = (process.env.BASE_URL ?? "http://localhost:3000").replace(/\/$/, "");
const BASE_ORIGIN = new URL(BASE_URL).origin;
const HERE = path.dirname(fileURLToPath(import.meta.url));
const OUT_DIR = path.resolve(HERE, "..", "..", "review", "p36_shots");

const results = [];

function record(name, ok, detail) {
  results.push({ name, ok });
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail ? `  — ${detail}` : ""}`);
}

async function openDoor(browser) {
  const context = await browser.newContext({ viewport: VIEWPORTS.desktop, deviceScaleFactor: 2 });
  const page = await context.newPage();
  await mockTelegram(page);
  await mockApi(page);
  await mockSupabase(page);
  return { context, page };
}

async function positiveCase(browser) {
  const name = "returnTo=%2Fnew lands on /new";
  const { context, page } = await openDoor(browser);
  try {
    await page.goto(`${BASE_URL}/login?returnTo=%2Fnew`, { waitUntil: "domcontentloaded" });
    await page.waitForURL("**/new**", { timeout: 15000 });
    const final = new URL(page.url());
    await settle(page);
    await page.screenshot({ path: path.join(OUT_DIR, "journey-login-to-new.png"), fullPage: true });
    if (final.pathname !== "/new") throw new Error(`pathname is ${final.pathname}`);
    record(name, true, final.href);
  } catch (error) {
    record(name, false, String(error).split("\n")[0]);
  } finally {
    await context.close();
  }
}

async function rejectedCase(browser, label, encoded, shotName) {
  const name = `returnTo=${label} rejected -> /projects`;
  const { context, page } = await openDoor(browser);
  try {
    await page.goto(`${BASE_URL}/login?returnTo=${encoded}`, { waitUntil: "domcontentloaded" });
    await page.waitForURL((url) => url.pathname === "/projects", { timeout: 15000 });
    const final = new URL(page.url());
    await settle(page);
    await page.screenshot({ path: path.join(OUT_DIR, shotName), fullPage: true });
    if (final.origin !== BASE_ORIGIN) throw new Error(`origin is ${final.origin}`);
    if (final.pathname !== "/projects") throw new Error(`pathname is ${final.pathname}`);
    record(name, true, final.href);
  } catch (error) {
    record(name, false, String(error).split("\n")[0]);
  } finally {
    await context.close();
  }
}

async function main() {
  await mkdir(OUT_DIR, { recursive: true });
  const browser = await launchBrowser();
  await positiveCase(browser);
  await rejectedCase(browser, "https://evil.com", "https%3A%2F%2Fevil.com", "journey-absolute-rejected.png");
  await rejectedCase(browser, "//evil.com", "%2F%2Fevil.com", "journey-protocol-relative-rejected.png");
  await browser.close();

  const failed = results.filter((entry) => !entry.ok).length;
  console.log(`\n${results.length - failed}/${results.length} passed (base ${BASE_URL})`);
  if (failed > 0) process.exitCode = 1;
}

await main();
