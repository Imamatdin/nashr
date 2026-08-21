// Scope (b) button-system see-fix loop. Shoots the real pages that render
// buttons today (/ and /login) plus an injected state matrix, so the light
// theme's .btn dresses are visible at all (the landing CTA is inline-styled).
//
// Run from scripts/webshots:  node buttons.mjs
import { mkdirSync } from "node:fs";
import { launchBrowser, VIEWPORTS, mockApi, mockSupabase, stubTelegramInert, settle } from "./lib.mjs";

const BASE = "http://localhost:3000";
const OUT = new URL("../../review/reset_shots/", import.meta.url).pathname.replace(/^\//, "");

mkdirSync(OUT, { recursive: true });

const MATRIX = `
<section id="btn-matrix" style="padding:2.5rem 2rem 3rem;display:flex;flex-direction:column;gap:2rem">
  <div style="font-family:var(--font-display);font-size:1.4rem">Button state matrix</div>
  ROWS
</section>`;

const VARIANTS = [
  ["primary", "btn-primary", "Havola yuborish"],
  ["ghost", "btn-ghost", "Bekor qilish"],
  ["danger", "btn-danger", "O'chirish"],
  ["gilded", "btn-gilded", "Boshlash"],
];

function rowsHtml() {
  return VARIANTS.map(([name, cls, label]) => {
    const cell = (extra, attr, tag) => `
      <div style="display:flex;flex-direction:column;gap:.45rem;align-items:flex-start">
        <span style="font-family:var(--font-mono);font-size:.7rem;opacity:.6">${tag}</span>
        <button class="btn ${cls} ${extra}" ${attr}>
          <span class="btn-label">${label}</span>
          ${extra.includes("btn-loading") ? '<span class="btn-pulse" aria-hidden><i></i><i></i><i></i></span>' : ""}
        </button>
      </div>`;
    return `
      <div>
        <div style="font-family:var(--font-mono);font-size:.78rem;margin-bottom:.7rem;opacity:.75">${name}</div>
        <div style="display:flex;flex-wrap:wrap;gap:1.6rem;align-items:flex-end">
          ${cell("", "", "rest")}
          ${cell("", 'data-hover="1"', "hover")}
          ${cell("", "disabled", "disabled")}
          ${cell("btn-loading", "disabled aria-busy=true", "loading")}
          ${cell("btn-lg", "", "lg")}
        </div>
      </div>`;
  }).join("");
}

async function injectMatrix(page) {
  await page.evaluate((html) => {
    document.querySelectorAll("#btn-matrix").forEach((n) => n.remove());
    const host = document.createElement("div");
    host.innerHTML = html;
    // The dark theme is scoped to a wrapper (.dark.auth-min), not <body>, so
    // the matrix must land INSIDE it or it renders with the light dresses.
    const root = document.querySelector(".dark") ?? document.body;
    root.prepend(host.firstElementChild);
    window.scrollTo(0, 0);
  }, MATRIX.replace("ROWS", rowsHtml()));
}

// The zero-layout-shift assertion: toggling .btn-loading must not move the
// button box or its label box by a single pixel.
async function measureShift(page) {
  return page.evaluate(() => {
    const btn = document.querySelector("#btn-matrix .btn-primary");
    const label = btn.querySelector(".btn-label");
    const before = { b: btn.getBoundingClientRect(), l: label.getBoundingClientRect() };
    btn.classList.add("btn-loading");
    if (!btn.querySelector(".btn-pulse")) {
      const s = document.createElement("span");
      s.className = "btn-pulse";
      s.innerHTML = "<i></i><i></i><i></i>";
      btn.appendChild(s);
    }
    const after = { b: btn.getBoundingClientRect(), l: label.getBoundingClientRect() };
    btn.classList.remove("btn-loading");
    return {
      buttonDx: +(after.b.x - before.b.x).toFixed(3),
      buttonDw: +(after.b.width - before.b.width).toFixed(3),
      labelDx: +(after.l.x - before.l.x).toFixed(3),
      labelDw: +(after.l.width - before.l.width).toFixed(3),
    };
  });
}

async function shoot(page, name) {
  await page.screenshot({ path: `${OUT}buttons-${name}.png`, fullPage: false });
  console.log("shot", `${OUT}buttons-${name}.png`);
}

async function main() {
  const browser = await launchBrowser();
  const report = {};

  for (const [vpName, vp] of Object.entries(VIEWPORTS)) {
    const size = vpName === "desktop" ? "1440" : "390";
    const context = await browser.newContext({ viewport: vp });
    const page = await context.newPage();
    await mockSupabase(page); await mockApi(page); await stubTelegramInert(page);

    // --- real pages -----------------------------------------------------
    await page.goto(`${BASE}/`, { waitUntil: "networkidle" });
    await settle(page);
    await shoot(page, `landing-${size}`);

    await page.goto(`${BASE}/login`, { waitUntil: "networkidle" });
    await settle(page);
    await shoot(page, `login-${size}`);

    // Hover the real dark ghost door (the primary below it is server-rendered
    // disabled until the email field has a value, and this page is not
    // hydrating in the stub environment — see the report's open issues).
    await page.fill("#email", "talaba@nashr.uz");
    await page.hover(".btn-ghost");
    await page.waitForTimeout(200);
    await shoot(page, `login-hover-${size}`);

    // Keyboard focus ring on a real page control. Six blind Tabs walked past
    // every button in cycle 1; focus the brand link, then ONE Tab lands on the
    // ghost door with :focus-visible genuinely set by the keyboard.
    await page.focus(".auth-min-brand");
    await page.keyboard.press("Tab");
    await page.waitForTimeout(200);
    await shoot(page, `login-focus-${size}`);

    // --- injected matrix, dark ground (/login is .dark.auth-min) --------
    await injectMatrix(page);
    await page.waitForTimeout(500);
    await page.hover('#btn-matrix [data-hover="1"]');
    await page.waitForTimeout(150);
    await shoot(page, `matrix-dark-${size}`);
    report[`shift-dark-${size}`] = await measureShift(page);

    // press (:active) held open with mouse.down, plus the dark focus ring
    await page.hover("#btn-matrix .btn-gilded");
    await page.mouse.down();
    await page.waitForTimeout(180);
    await shoot(page, `matrix-dark-press-${size}`);
    await page.mouse.up();
    await page.focus("#btn-matrix .btn-primary");
    await page.keyboard.press("Tab");
    await page.waitForTimeout(200);
    await shoot(page, `matrix-dark-focus-${size}`);

    // --- injected matrix, light ground (/ is the paper marketing side) --
    await page.goto(`${BASE}/`, { waitUntil: "networkidle" });
    await injectMatrix(page);
    await page.waitForTimeout(500);
    await page.hover('#btn-matrix [data-hover="1"]');
    await page.waitForTimeout(150);
    await shoot(page, `matrix-light-${size}`);
    report[`shift-light-${size}`] = await measureShift(page);

    // Focus ring inside the matrix (light). Focus the first primary, then Tab
    // forward so the ring is keyboard-set rather than script-set.
    await page.focus("#btn-matrix .btn-primary");
    await page.keyboard.press("Tab");
    await page.waitForTimeout(200);
    await shoot(page, `matrix-light-focus-${size}`);

    await context.close();
  }

  // --- reduced motion: the pulse must settle into a static ellipsis -----
  const rm = await browser.newContext({
    viewport: VIEWPORTS.desktop,
    reducedMotion: "reduce",
  });
  const rmPage = await rm.newPage();
  await mockSupabase(rmPage); await mockApi(rmPage); await stubTelegramInert(rmPage);
  await rmPage.goto(`${BASE}/login`, { waitUntil: "networkidle" });
  await injectMatrix(rmPage);
  await rmPage.waitForTimeout(400);
  await shoot(rmPage, "matrix-dark-reduced-1440");
  await rm.close();

  await browser.close();
  console.log(JSON.stringify(report, null, 2));
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
