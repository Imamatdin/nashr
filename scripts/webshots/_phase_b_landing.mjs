// Phase B-landing shots. The landing is light permanently, so every shot is
// light; the "forced" one seeds a dark preference and a dark colorScheme to
// prove the page refuses it.
import { mkdir } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { VIEWPORTS, launchBrowser, settle } from "./lib.mjs";

const BASE_URL = (process.env.BASE_URL ?? "http://localhost:3000").replace(/\/$/, "");
const HERE = path.dirname(fileURLToPath(import.meta.url));
const OUT_DIR = path.resolve(HERE, "..", "..", "review", "redesign_shots");

const SHOTS = [
  { name: "landing-light-1440", vp: "desktop", full: true },
  { name: "landing-light-390", vp: "phone", full: true },
  { name: "landing-hero-light-1440", vp: "desktop" },
  { name: "landing-hero-light-390", vp: "phone" },
  { name: "landing-fold2-light-1440", vp: "desktop", scroll: 900 },
  { name: "landing-fold3-light-1440", vp: "desktop", scroll: 1800 },
  { name: "landing-forced-light-1440", vp: "desktop", forceDark: true },
];

async function shoot(browser, shot) {
  const viewport = VIEWPORTS[shot.vp];
  const context = await browser.newContext({
    viewport,
    deviceScaleFactor: 2,
    ...(shot.forceDark ? { colorScheme: "dark" } : {}),
  });
  const page = await context.newPage();
  await page.addInitScript((value) => {
    window.localStorage.setItem("nashr.theme", value);
  }, shot.forceDark ? "dark" : "light");
  await page.goto(`${BASE_URL}/`, { waitUntil: "networkidle" });
  await settle(page);
  await page.addStyleTag({ content: "nextjs-portal { display: none !important }" });
  if (shot.scroll) {
    await page.evaluate((y) => window.scrollTo(0, y), shot.scroll);
    await page.waitForTimeout(400);
  }
  const file = path.join(OUT_DIR, `${shot.name}.png`);
  await page.screenshot({ path: file, fullPage: Boolean(shot.full) });
  console.log(file);
  await context.close();
}

async function main() {
  await mkdir(OUT_DIR, { recursive: true });
  const browser = await launchBrowser();
  for (const shot of SHOTS) {
    await shoot(browser, shot);
  }
  await browser.close();
}

await main();
