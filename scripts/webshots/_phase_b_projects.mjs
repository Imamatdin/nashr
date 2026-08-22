// Phase B-projects shots: the /projects surface in both themes and widths,
// plus the grid, chip-filtered, search-open, sorted and empty states.
import { mkdir } from "node:fs/promises";
import path from "node:path";
import { launchBrowser, mockApi, mockSupabase, seedSession, settle, VIEWPORTS } from "./lib.mjs";

const BASE = (process.env.BASE_URL ?? "http://localhost:3000").replace(/\/$/, "");
const OUT = path.resolve("../../review/redesign_shots");
await mkdir(OUT, { recursive: true });

const browser = await launchBrowser();

async function open({ theme, width, empty = false, view = "list" }) {
  const viewport = width === 390 ? VIEWPORTS.phone : VIEWPORTS.desktop;
  const ctx = await browser.newContext({ viewport, deviceScaleFactor: 2 });
  const page = await ctx.newPage();
  await page.addInitScript(
    ([t, v]) => {
      localStorage.setItem("nashr.theme", t);
      localStorage.setItem("nashr.projects.view", v);
    },
    [theme, view],
  );
  await seedSession(page);
  await mockSupabase(page, empty ? { emptyProjects: true } : { manyProjects: true });
  await mockApi(page, {});
  await page.goto(`${BASE}/projects`, { waitUntil: "domcontentloaded" });
  await settle(page);
  // The dev-server badge is not part of the design.
  await page.addStyleTag({ content: "nextjs-portal{display:none!important}" });
  return { ctx, page };
}

async function shot(page, name) {
  await page.screenshot({ path: path.join(OUT, `${name}.png`), fullPage: true });
  console.log("shot", name);
}

for (const theme of ["light", "dark"]) {
  for (const width of [1440, 390]) {
    const { ctx, page } = await open({ theme, width });
    await shot(page, `projects-${theme}-${width}`);
    await ctx.close();
  }

  {
    const { ctx, page } = await open({ theme, width: 1440, view: "grid" });
    await shot(page, `projects-grid-${theme}-1440`);
    await ctx.close();
  }

  {
    const { ctx, page } = await open({ theme, width: 1440 });
    await page.getByRole("button", { name: /^Tayyor/ }).click();
    await page.waitForTimeout(600);
    await shot(page, `projects-filter-ready-${theme}-1440`);
    await ctx.close();
  }

  {
    const { ctx, page } = await open({ theme, width: 1440 });
    await page.getByLabel("Loyiha qidirish").fill("de");
    await page.waitForTimeout(500);
    await shot(page, `projects-search-${theme}-1440`);
    await ctx.close();
  }

  for (const width of [1440, 390]) {
    const { ctx, page } = await open({ theme, width, empty: true });
    await shot(page, `projects-empty-${theme}-${width}`);
    await ctx.close();
  }
}

{
  const { ctx, page } = await open({ theme: "light", width: 1440 });
  await page.getByRole("button", { name: /Nomi/ }).click();
  await page.waitForTimeout(500);
  await shot(page, "projects-sorted-name-light-1440");
  await ctx.close();
}

await browser.close();
