import { mkdir } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { launchBrowser, settle } from "./lib.mjs";

const BASE_URL = (process.env.BASE_URL ?? "http://localhost:3000").replace(/\/$/, "");
const HERE = path.dirname(fileURLToPath(import.meta.url));
const OUT_DIR = path.resolve(HERE, "..", "..", "review", "redesign_shots");
const URL_PATH = "/dev/components";

async function newPage(browser, theme) {
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    deviceScaleFactor: 2,
  });
  const page = await context.newPage();
  // The stored key is what the app reads; the class is applied here too because
  // Phase A1's no-flash script had not landed when these shots were taken.
  await page.addInitScript((value) => {
    window.localStorage.setItem("nashr.theme", value);
    const apply = () => {
      try {
        document.documentElement.classList.toggle("dark", value === "dark");
      } catch {
        /* documentElement not ready yet */
      }
    };
    apply();
    document.addEventListener("DOMContentLoaded", apply);
  }, theme);
  return { context, page };
}

async function reapplyTheme(page, theme) {
  await page.evaluate((value) => {
    document.documentElement.classList.toggle("dark", value === "dark");
  }, theme);
}

async function clipOf(page, cell, { padTop = 0, padBottom = 0, padX = 8, maxHeight } = {}) {
  const box = await page.locator(`[data-cell="${cell}"]`).boundingBox();
  if (!box) throw new Error(`cell ${cell} not found`);
  const height = Math.min(box.height + padTop + padBottom, maxHeight ?? Number.MAX_SAFE_INTEGER);
  return {
    x: Math.max(0, box.x - padX),
    y: Math.max(0, box.y - padTop),
    width: box.width + padX * 2,
    height,
  };
}

async function shootGallery(browser, theme) {
  const { context, page } = await newPage(browser, theme);
  await page.goto(`${BASE_URL}${URL_PATH}`, { waitUntil: "domcontentloaded" });
  await settle(page);
  await reapplyTheme(page, theme);
  await page.waitForTimeout(4500);
  await page.screenshot({
    path: path.join(OUT_DIR, `gallery-${theme}-1440.png`),
    fullPage: true,
  });
  await context.close();
}

async function shootCloseups(browser) {
  // #08 prompt bar with the @ menu open (light)
  {
    const { context, page } = await newPage(browser, "light");
    await page.goto(`${BASE_URL}${URL_PATH}`, { waitUntil: "domcontentloaded" });
    await settle(page);
    await reapplyTheme(page, "light");
    const bar = page.locator('[data-cell="#08"] textarea');
    await bar.click();
    await page.keyboard.type("@");
    await page.waitForTimeout(500);
    await page.mouse.move(0, 0);
    await page.screenshot({
      fullPage: true,
      path: path.join(OUT_DIR, "gallery-promptbar-at-menu-light-1440.png"),
      clip: await clipOf(page, "#08", { padTop: 340, padBottom: 16, maxHeight: 700 }),
    });
    await context.close();
  }

  // #08 with a picker menu open (dark)
  {
    const { context, page } = await newPage(browser, "dark");
    await page.goto(`${BASE_URL}${URL_PATH}`, { waitUntil: "domcontentloaded" });
    await settle(page);
    await reapplyTheme(page, "dark");
    await page.locator('[data-cell="#08"] button[aria-label="Paket"]').click();
    await page.waitForTimeout(500);
    await page.screenshot({
      fullPage: true,
      path: path.join(OUT_DIR, "gallery-promptbar-picker-dark-1440.png"),
      clip: await clipOf(page, "#08", { padTop: 60, padBottom: 16, maxHeight: 700 }),
    });
    await context.close();
  }

  const simple = [
    { cell: "#06", theme: "light", name: "gallery-taskrows-light-1440.png" },
    { cell: "#02", theme: "dark", name: "gallery-thinking-dark-1440.png" },
    { cell: "#04", theme: "light", name: "gallery-approval-light-1440.png" },
  ];
  for (const shot of simple) {
    const { context, page } = await newPage(browser, shot.theme);
    await page.goto(`${BASE_URL}${URL_PATH}`, { waitUntil: "domcontentloaded" });
    await settle(page);
    await reapplyTheme(page, shot.theme);
    await page.waitForTimeout(900);
    await page.screenshot({
      fullPage: true,
      path: path.join(OUT_DIR, shot.name),
      clip: await clipOf(page, shot.cell, { padTop: 8, padBottom: 8, maxHeight: 900 }),
    });
    await context.close();
  }
}

async function main() {
  await mkdir(OUT_DIR, { recursive: true });
  const browser = await launchBrowser();
  try {
    await shootGallery(browser, "light");
    await shootGallery(browser, "dark");
    await shootCloseups(browser);
  } finally {
    await browser.close();
  }
  console.log(`wrote shots to ${OUT_DIR}`);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
