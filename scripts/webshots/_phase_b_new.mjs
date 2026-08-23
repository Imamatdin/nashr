// Phase B-new shots: the /new creation surface in both themes and widths,
// plus the attached, confirm, @-menu, credit-refusal and daily-limit states.
import { mkdir } from "node:fs/promises";
import path from "node:path";
import { launchBrowser, mockApi, mockSupabase, seedSession, settle, VIEWPORTS } from "./lib.mjs";

const BASE = (process.env.BASE_URL ?? "http://localhost:3000").replace(/\/$/, "");
const OUT = path.resolve("../../review/redesign_shots");
await mkdir(OUT, { recursive: true });

const TOPIC = "Yoritish davri va uning merosi";
const FILE = {
  name: "yoritish-davri-tarixi.pdf",
  mimeType: "application/pdf",
  buffer: Buffer.from("%PDF-1.4 stub"),
};

const browser = await launchBrowser();

async function open({ theme, width, enqueue }) {
  const viewport = width === 390 ? VIEWPORTS.phone : VIEWPORTS.desktop;
  const ctx = await browser.newContext({ viewport, deviceScaleFactor: 2 });
  const page = await ctx.newPage();
  await page.addInitScript((t) => localStorage.setItem("nashr.theme", t), theme);
  await seedSession(page);
  await mockSupabase(page, {});
  await mockApi(page, enqueue ? { enqueue } : {});
  await page.goto(`${BASE}/new`, { waitUntil: "domcontentloaded" });
  await settle(page);
  await page.addStyleTag({ content: "nextjs-portal{display:none!important}" });
  return { ctx, page };
}

async function shot(page, name) {
  await page.screenshot({ path: path.join(OUT, `${name}.png`), fullPage: true });
  console.log("shot", name);
}

const composer = (page) => page.getByLabel("Buyruq");
const attachInput = (page) => page.locator("[data-promptbar] input[type=file]");

async function attach(page) {
  await composer(page).fill(TOPIC);
  await attachInput(page).setInputFiles(FILE);
  await page.getByText("ro‘yxatdan o‘tdi").waitFor({ timeout: 8000 });
  await page.waitForTimeout(500);
}

async function toConfirm(page) {
  await composer(page).fill(TOPIC);
  await page.getByRole("button", { name: "Yuborish" }).click();
  await page.getByText("Generatsiyani boshlaymizmi?").waitFor({ timeout: 8000 });
  await page.waitForTimeout(600);
}

for (const theme of ["light", "dark"]) {
  for (const width of [1440, 390]) {
    const { ctx, page } = await open({ theme, width });
    await shot(page, `new-${theme}-${width}`);
    await ctx.close();
  }

  {
    const { ctx, page } = await open({ theme, width: 1440 });
    await attach(page);
    await shot(page, `new-attached-${theme}-1440`);
    await ctx.close();
  }

  {
    const { ctx, page } = await open({ theme, width: 1440 });
    await toConfirm(page);
    await shot(page, `new-confirm-${theme}-1440`);
    await ctx.close();
  }
}

{
  const { ctx, page } = await open({ theme: "light", width: 1440 });
  await composer(page).click();
  await composer(page).type("@");
  await page.waitForTimeout(600);
  await shot(page, "new-menu-light-1440");
  await ctx.close();
}

for (const [enqueue, name, marker] of [
  ["credit", "new-402-light-1440", "Kredit yetarli emas"],
  ["limit", "new-429-light-1440", "Kunlik limit"],
]) {
  const { ctx, page } = await open({ theme: "light", width: 1440, enqueue });
  await toConfirm(page);
  await page.getByRole("button", { name: /Ha, boshlash/ }).click();
  await page.getByRole("heading", { name: marker }).waitFor({ timeout: 8000 });
  await page.waitForTimeout(600);
  await shot(page, name);
  await ctx.close();
}

await browser.close();
