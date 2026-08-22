import { mkdir } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { VIEWPORTS, launchBrowser, mockApi, mockSupabase, seedSession, settle } from "./lib.mjs";

const BASE_URL = (process.env.BASE_URL ?? "http://localhost:3000").replace(/\/$/, "");
const HERE = path.dirname(fileURLToPath(import.meta.url));
const OUT_DIR = path.resolve(HERE, "..", "..", "review", "redesign_shots");

const SHOTS = [
  { name: "chrome-expanded", theme: "light", vp: "desktop" },
  { name: "chrome-expanded", theme: "dark", vp: "desktop" },
  { name: "chrome-collapsed", theme: "light", vp: "desktop", act: "collapse" },
  { name: "chrome-collapsed", theme: "dark", vp: "desktop", act: "collapse" },
  { name: "chrome", theme: "light", vp: "phone" },
  { name: "chrome", theme: "dark", vp: "phone" },
  { name: "chrome-workspace-menu", theme: "dark", vp: "desktop", act: "workspace" },
  { name: "chrome-recents-search", theme: "light", vp: "desktop", act: "search" },
];

async function act(page, kind) {
  if (kind === "collapse") {
    await page.click('button[aria-label="Panelni yig‘ish"]');
  } else if (kind === "workspace") {
    await page.click("[data-workspace-trigger]");
  } else if (kind === "search") {
    await page.click('button[aria-label="Loyihalarni qidirish"]');
    await page.fill('input[aria-label="Loyihalar tarixidan qidirish"]', "Orol");
  }
  if (kind) await page.waitForTimeout(600);
}

async function main() {
  await mkdir(OUT_DIR, { recursive: true });
  const browser = await launchBrowser();
  for (const shot of SHOTS) {
    const viewport = VIEWPORTS[shot.vp];
    const context = await browser.newContext({ viewport, deviceScaleFactor: 2 });
    const page = await context.newPage();
    await seedSession(page);
    await page.addInitScript((value) => {
      window.localStorage.setItem("nashr.theme", value);
    }, shot.theme);
    await mockSupabase(page);
    await mockApi(page);
    await page.goto(`${BASE_URL}/projects`, { waitUntil: "networkidle" });
    await settle(page);
    // The Next dev-mode indicator is a fixed bottom-left badge that would sit
    // on top of the sidebar footer in every shot.
    await page.addStyleTag({ content: "nextjs-portal { display: none !important }" });
    await act(page, shot.act);
    const file = path.join(OUT_DIR, `${shot.name}-${shot.theme}-${viewport.width}.png`);
    await page.screenshot({ path: file, fullPage: true });
    console.log(file);
    await context.close();
  }
  await browser.close();
}

await main();
