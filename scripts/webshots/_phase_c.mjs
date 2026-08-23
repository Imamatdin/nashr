import { mkdir } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { VIEWPORTS, launchBrowser, mockApi, mockSupabase, seedSession, settle, stubTelegramInert } from "./lib.mjs";
const BASE = (process.env.BASE_URL ?? "http://localhost:3000").replace(/\/$/, "");
const OUT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..", "review", "redesign_shots");

async function shoot(browser, { name, url, width, theme, colorScheme, telegram, share, waitFor }) {
  const ctx = await browser.newContext({ viewport: { width, height: width > 600 ? 900 : 844 }, deviceScaleFactor: 2, ...(colorScheme ? { colorScheme } : {}) });
  const page = await ctx.newPage();
  if (theme) await page.addInitScript((t) => localStorage.setItem("nashr.theme", t), theme);
  if (telegram === "inert") await stubTelegramInert(page);
  if (share !== undefined) { await mockApi(page, { shareState: share }); }
  let status = "OK";
  try {
    await page.goto(`${BASE}${url}`, { waitUntil: "domcontentloaded", timeout: 40000 });
    await settle(page);
    if (waitFor) await page.waitForSelector(waitFor, { timeout: 15000 }).catch((e) => { status = `WARN ${waitFor}: ${String(e).split("\n")[0]}`; });
    await settle(page);
    await page.screenshot({ path: path.join(OUT, `${name}.png`), fullPage: true });
  } catch (e) { status = `FAIL ${String(e).split("\n")[0]}`; }
  console.log(`${name}.png  ${status}`);
  await ctx.close();
}

const browser = await launchBrowser();
await mkdir(OUT, { recursive: true });
const W = VIEWPORTS.desktop.width, P = VIEWPORTS.phone.width;

// login + callback + 404 — light, prove they resist a dark preference/system
await shoot(browser, { name: "login-1440", url: "/login", width: W, telegram: "inert" });
await shoot(browser, { name: "login-390", url: "/login", width: P, telegram: "inert" });
await shoot(browser, { name: "login-forced-dark-1440", url: "/login", width: W, theme: "dark", colorScheme: "dark", telegram: "inert" });
await shoot(browser, { name: "callback-1440", url: "/auth/callback", width: W });
await shoot(browser, { name: "notfound-1440", url: "/definitely-missing", width: W });
await shoot(browser, { name: "notfound-390", url: "/definitely-missing", width: P });
await shoot(browser, { name: "notfound-forced-dark-1440", url: "/definitely-missing", width: W, theme: "dark", colorScheme: "dark" });

// share — always dark, one theme
const T = "/p/share-stub-token";
await shoot(browser, { name: "share-deck-1440", url: T, width: W, share: "deck", waitFor: ".share-frame iframe" });
await shoot(browser, { name: "share-deck-390", url: T, width: P, share: "deck", waitFor: ".share-frame iframe" });
await shoot(browser, { name: "share-loading-1440", url: T, width: W, share: "loading" });
await shoot(browser, { name: "share-error-1440", url: T, width: W, share: "error", waitFor: ".share-error" });

await browser.close();
console.log("done");
