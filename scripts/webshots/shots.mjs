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
const OUT_DIR = path.resolve(HERE, "..", "..", "review", "reset_shots");

const SHOTS = [
  { name: "login", url: "/login", session: false, mocks: false, telegram: "inert" },
  { name: "new", url: "/new", session: true, mocks: true },
  { name: "projects", url: "/projects", session: true, mocks: true },
  {
    name: "projects-empty",
    url: "/projects",
    session: true,
    mocks: true,
    supabase: { emptyProjects: true },
  },
  {
    name: "workspace",
    url: "/projects/p-1?job=job-stub",
    session: true,
    mocks: true,
    waitFor: "progress",
  },
  {
    name: "workspace-idle",
    url: "/projects/p-1",
    session: true,
    mocks: true,
  },
  {
    name: "workspace-blank",
    url: "/projects/p-1",
    session: true,
    mocks: true,
    supabase: { emptySources: true },
  },
  {
    name: "workspace-failed",
    url: "/projects/p-1?job=job-stub",
    session: true,
    mocks: true,
    api: { jobStatus: "failed", jobError: "Manba fayli o'qilmadi — PDF shifrlangan." },
    waitFor: "error",
  },
  {
    name: "workspace-deck",
    url: "/projects/p-1",
    session: true,
    mocks: true,
    api: { deckReady: true },
    supabase: { shareToken: "share-stub-token" },
    waitFor: "deck",
  },
  // The /new flow only reveals steps II and III after the API answers, so the
  // later stages are driven rather than routed to.
  { name: "new-stage2", url: "/new", session: true, mocks: true, drive: "sources" },
  { name: "new-stage3", url: "/new", session: true, mocks: true, drive: "confirm" },
  {
    name: "new-402",
    url: "/new",
    session: true,
    mocks: true,
    api: { enqueue: "credit" },
    drive: "enqueue",
    waitFor: "error",
  },
  {
    name: "new-429",
    url: "/new",
    session: true,
    mocks: true,
    api: { enqueue: "limit" },
    drive: "enqueue",
    waitFor: "error",
  },
  { name: "notfound", url: "/definitely-missing-route", session: false, mocks: false },
];

// Walk the flow with the same clicks a user makes: name the project, register
// one source through the presign→PUT→register chain, confirm, and (for the
// refusal shots) press the final button.
async function drive(page, stop) {
  // The controls only enable once the client has hydrated and read the stored
  // session, so type through the real input and wait out the disabled state.
  await page.waitForSelector("#title", { timeout: 20000 });
  await page.fill("#title", "Yoritish davri va uning merosi");
  const start = page.getByRole("button", { name: "Loyihani boshlash" });
  await start.waitFor({ state: "visible", timeout: 20000 });
  await page.waitForFunction(
    () =>
      Array.from(document.querySelectorAll("button")).some(
        (node) => node.textContent?.includes("Loyihani boshlash") && !node.disabled,
      ),
    { timeout: 20000 },
  );
  await start.click();
  await page.waitForSelector("#sources", { timeout: 20000 });
  if (stop === "sources") return;
  await page.setInputFiles("#sources", {
    name: "yoritish-davri-tarixi.pdf",
    mimeType: "application/pdf",
    buffer: Buffer.from("%PDF-1.4 stub"),
  });
  await page.getByRole("button", { name: "Yuklash" }).click();
  await page.getByRole("button", { name: "Davom etish" }).click();
  await page.waitForSelector(".summary", { timeout: 20000 });
  if (stop === "confirm") return;
  await page.getByRole("button", { name: "Taqdimotni boshlash" }).click();
}

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
    await mockSupabase(page, shot.supabase ?? {});
    await mockApi(page, shot.api ?? {});
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
    if (shot.drive) {
      // Nothing is clickable before hydration wires the handlers up.
      await settle(page);
      await drive(page, shot.drive).catch((error) => {
        status = `WARN flow not driven: ${String(error).split("\n")[0]}`;
        process.exitCode = 1;
      });
    }
    if (shot.waitFor === "deck") {
      await page.waitForSelector(".viewer-frame", { timeout: 20000 }).catch((error) => {
        status = `WARN deck not rendered: ${String(error).split("\n")[0]}`;
        process.exitCode = 1;
      });
    }
    if (shot.waitFor === "error") {
      await page.waitForSelector(".state-note", { timeout: 20000 }).catch((error) => {
        status = `WARN error state not rendered: ${String(error).split("\n")[0]}`;
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
