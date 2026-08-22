import { launchBrowser, mockApi, mockSupabase, seedSession, VIEWPORTS } from "./lib.mjs";

const BASE_URL = (process.env.BASE_URL ?? "http://localhost:3000").replace(/\/$/, "");

async function probe(browser, pathname) {
  const context = await browser.newContext({ viewport: VIEWPORTS.desktop });
  const page = await context.newPage();
  await seedSession(page);
  await page.addInitScript(() => window.localStorage.setItem("nashr.theme", "dark"));
  await page.addInitScript(() => {
    window.__classLog = [];
    new MutationObserver(() => window.__classLog.push(document.documentElement.className)).observe(
      document.documentElement ?? document,
      { attributes: true, attributeFilter: ["class"], subtree: true },
    );
  });
  await mockSupabase(page);
  await mockApi(page);
  await page.goto(`${BASE_URL}${pathname}`, { waitUntil: "commit" });
  // The earliest moment a paint could happen: <body> attached.
  await page.waitForSelector("body", { state: "attached" });
  const first = await page.evaluate(() => ({
    className: document.documentElement.className,
    body: getComputedStyle(document.body).backgroundColor,
    bodyChildren: document.body.childElementCount,
  }));
  await page.waitForLoadState("networkidle");
  const after = await page.evaluate(() => ({
    className: document.documentElement.className,
    body: getComputedStyle(document.body).backgroundColor,
  }));
  console.log(pathname, "at commit:", JSON.stringify(first));
  const log = await page.evaluate(() =>
    (window.__classLog ?? []).map((c) => (c.includes("dark") ? "dark" : "light")),
  );
  console.log(pathname, "settled  :", JSON.stringify(after));
  console.log(pathname, "class mutations:", JSON.stringify(log));
  await context.close();
}

const browser = await launchBrowser();
await probe(browser, "/projects");
await probe(browser, "/");
await browser.close();
