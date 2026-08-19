import { mkdir } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  VIEWPORTS,
  launchBrowser,
  mockApi,
  mockSupabase,
  seedSession,
  settle,
  stubTelegramInert,
} from "./lib.mjs";

const BASE_URL = (process.env.BASE_URL ?? "http://localhost:3000").replace(/\/$/, "");
const HERE = path.dirname(fileURLToPath(import.meta.url));
const OUT_DIR = path.resolve(HERE, "..", "..", "review", "p36_shots");

const SHOTS = [
  { name: "login", url: "/login", session: false, mocks: false, telegram: "inert" },
  { name: "new", url: "/new", session: true, mocks: true },
  { name: "projects", url: "/projects", session: true, mocks: true },
  {
    name: "workspace",
    url: "/projects/p-1?job=job-stub",
    session: true,
    mocks: true,
    waitFor: "progress",
  },
  { name: "notfound", url: "/definitely-missing-route", session: false, mocks: false },
];

async function waitForProgress(page) {
  await page.waitForSelector(".progress-track", { timeout: 20000 });
  await page
    .getByText("Dizayn yo'nalishi tanlanmoqda")
    .first()
    .waitFor({ timeout: 20000 });
}

async function capture(browser, shot, viewport) {
  const context = await browser.newContext({ viewport, deviceScaleFactor: 2 });
  const page = await context.newPage();
  if (shot.telegram === "inert") await stubTelegramInert(page);
  if (shot.mocks) {
    await mockSupabase(page);
    await mockApi(page);
  }
  if (shot.session) await seedSession(page);

  const file = path.join(OUT_DIR, `${shot.name}-${viewport.width}.png`);
  let status = "OK";
  try {
    await page.goto(`${BASE_URL}${shot.url}`, { waitUntil: "domcontentloaded", timeout: 30000 });
    if (shot.waitFor === "progress") {
      await waitForProgress(page).catch((error) => {
        status = `WARN progress UI not rendered: ${String(error).split("\n")[0]}`;
        process.exitCode = 1;
      });
    }
    await settle(page);
    await page.screenshot({ path: file, fullPage: true });
  } catch (error) {
    status = `FAIL ${String(error).split("\n")[0]}`;
    process.exitCode = 1;
  }
  console.log(`${shot.name}-${viewport.width}.png  ${status}`);
  await context.close();
}

async function main() {
  await mkdir(OUT_DIR, { recursive: true });
  const browser = await launchBrowser();
  for (const shot of SHOTS) {
    for (const viewport of [VIEWPORTS.desktop, VIEWPORTS.phone]) {
      await capture(browser, shot, viewport);
    }
  }
  await capture(
    browser,
    { name: "landing", url: "/", session: false, mocks: false, telegram: "inert" },
    VIEWPORTS.desktop,
  );
  await browser.close();
  console.log(`\nshots -> ${OUT_DIR} (base ${BASE_URL})`);
}

await main();
