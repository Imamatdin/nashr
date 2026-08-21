// Scope (d) see-fix loop: landing (light, ink on paper) + the public share
// view (dark, paper on ink). Replaces the orchestrator's _smoke_landing.mjs.
//
//   node landing_shots.mjs            # everything
//   node landing_shots.mjs landing    # landing only
//   node landing_shots.mjs share      # share view only
//
// Output: ../../review/reset_shots/<view>-<state>-<width>.png

import { mkdir, copyFile, readFile } from "node:fs/promises";
import { chromium } from "playwright";
import { VIEWPORTS, settle } from "./lib.mjs";

// Origin-agnostic on purpose: the dev server's NEXT_PUBLIC_API_BASE_URL is
// injected by the orchestrator, so match the path wherever it points.
const SHARE_ROUTE = "**/public/decks/**";

const BASE = process.env.BASE_URL ?? "http://localhost:3000";
const OUT = "../../review/reset_shots";
const only = process.argv[2] ?? "all";

await mkdir(OUT, { recursive: true });
const browser = await chromium.launch();

const shot = (page, name, opts = {}) =>
  page.screenshot({ path: `${OUT}/${name}.png`, ...opts }).then(() => console.log("  ->", name));

// ------------------------------------------------------------------ landing

// The folds are named so a diff between cycles is readable: which section of
// the argument moved, not "the 3rd 900px band".
const FOLDS = [
  ["i-stakes", 0],
  ["ii-mechanism", 1],
  ["iii-artifact", 2],
  ["iv-heritage", 3],
  ["v-workflow", 4],
  ["vi-ask", 5],
];

async function landing(width, height, label) {
  const page = await browser.newPage({ viewport: { width, height } });

  // Entry-moment capture (§4.2 dither-in): the hero plate runs `immediate`,
  // so the coarse two-tone layer is only alone on screen for a few hundred
  // ms after first paint. Shoot before settle(), deliberately.
  await page.goto(`${BASE}/`, { waitUntil: "domcontentloaded", timeout: 90000 });
  await page.waitForTimeout(120);
  await shot(page, `landing-dither-entry-${label}`);

  await settle(page);
  await shot(page, `landing-settled-${label}`);
  await shot(page, `landing-full-${label}`, { fullPage: true });

  // Below-fold dither: scroll section II's manuscript plate in and catch the
  // crossfade mid-flight, then the resolved state.
  await page.evaluate(() => window.scrollTo(0, window.innerHeight * 1.35));
  await page.waitForTimeout(160);
  await shot(page, `landing-dither-plate2-entry-${label}`);
  await page.waitForTimeout(1400);
  await shot(page, `landing-dither-plate2-settled-${label}`);

  // Per-fold sweep of the whole argument — the gold audit needs every
  // viewport-height band, not just the hero.
  for (const [name, index] of FOLDS) {
    await page.evaluate((i) => window.scrollTo(0, window.innerHeight * i), index);
    await page.waitForTimeout(700);
    await shot(page, `landing-fold-${name}-${label}`);
  }

  // Button states: rest was captured above; hover + focus on the hero CTA.
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.waitForTimeout(400);
  const cta = page.locator("a.btn-primary").first();
  await cta.hover();
  await page.waitForTimeout(260);
  await shot(page, `landing-cta-hover-${label}`, { clip: await ctaClip(cta) });
  await page.keyboard.press("Tab");
  await cta.focus();
  await page.waitForTimeout(200);
  await shot(page, `landing-cta-focus-${label}`, { clip: await ctaClip(cta) });

  // Every other interactive thing on the page, not just the primary: the
  // audit is "correct variant everywhere", which a hero-only crop can't show.
  await hoverShot(page, page.getByRole("link", { name: "Kirish", exact: true }), `landing-navlink-hover-${label}`);
  await hoverShot(page, page.locator("a", { hasText: "A’zo bo’lganmisiz?" }).first(), `landing-secondary-hover-${label}`);

  // Scroll the whole page first: the gild only paints after GildOnView fires,
  // so an unscrolled audit would under-count section VI.
  await page.evaluate(async () => {
    for (let y = 0; y < document.body.scrollHeight; y += window.innerHeight / 2) {
      window.scrollTo(0, y);
      await new Promise((r) => setTimeout(r, 90));
    }
  });
  await page.waitForTimeout(900);
  await goldAudit(page, `landing-${label}`);

  await page.close();
}

// Hover a control and crop tightly around it. Returns silently if the control
// isn't on the page at this width — the report says which ones were skipped.
async function hoverShot(page, locator, name) {
  if (!(await locator.count())) return console.log("  -- skipped (absent):", name);
  await locator.first().scrollIntoViewIfNeeded();
  await page.waitForTimeout(200);
  await locator.first().hover();
  await page.waitForTimeout(260);
  const box = await locator.first().boundingBox();
  await shot(page, name, {
    clip: {
      x: Math.max(0, box.x - 20),
      y: Math.max(0, box.y - 16),
      width: Math.min(box.width + 40, page.viewportSize().width - Math.max(0, box.x - 20)),
      height: box.height + 32,
    },
  });
}

// A generous frame around the control so the gold underline draw and the
// focus ring both fall inside the crop.
async function ctaClip(locator) {
  const box = await locator.boundingBox();
  return {
    x: Math.max(0, box.x - 24),
    y: Math.max(0, box.y - 24),
    width: box.width + 200,
    height: box.height + 60,
  };
}

// A wide, short crop: the caption is one centred mono line and needs the
// frame edge above it for the "plate" reading to be judgeable.
async function captionClip(locator) {
  const box = await locator.boundingBox();
  return { x: box.x, y: Math.max(0, box.y - 40), width: box.width, height: box.height + 56 };
}

// --------------------------------------------------------------- share view

// The share route resolves its token against the API, which is not running
// under the stub env. Route it here, and point html_url at a data: URL that
// stands in for the rendered deck so the viewer frame is judged full, not
// as an empty rectangle.
const DECK_STUB = `data:text/html;charset=utf-8,${encodeURIComponent(`
<!doctype html><html><body style="margin:0;height:100vh;display:grid;place-items:center;
background:#1C1B1A;color:#CECDC3;font:600 34px/1.2 Georgia,serif;text-align:center">
<div><div style="font-size:13px;letter-spacing:.2em;color:#878580;font-family:monospace">
SLAYD 01 / 12</div><div style="margin-top:18px">Orol dengizi:<br>suv balansi va oqibatlar</div>
<div style="margin-top:22px;height:2px;width:120px;background:#D0A215;margin-inline:auto"></div>
</div></body></html>`)}`;

async function mockShare(page) {
  await page.route(SHARE_ROUTE, (route) =>
    route.fulfill({
      status: 200,
      headers: { "access-control-allow-origin": "*", "content-type": "application/json" },
      body: JSON.stringify({
        title: "Orol dengizi qurishi: suv balansi va oqibatlar",
        html_url: DECK_STUB,
        expires_in: 604800,
      }),
    }),
  );
}

async function share(width, height, label) {
  // loading skeleton, held by delaying the resolve
  const skel = await browser.newPage({ viewport: { width, height } });
  await skel.route(SHARE_ROUTE, () => {});
  await skel.goto(`${BASE}/p/share-stub-token`, { waitUntil: "domcontentloaded", timeout: 90000 });
  await skel.waitForTimeout(1200);
  await shot(skel, `share-loading-${label}`);
  await skel.close();

  const page = await browser.newPage({ viewport: { width, height } });
  await mockShare(page);
  await page.goto(`${BASE}/p/share-stub-token`, { waitUntil: "domcontentloaded", timeout: 90000 });
  await settle(page);
  await shot(page, `share-ready-${label}`);
  await shot(page, `share-ready-full-${label}`, { fullPage: true });

  const cta = page.locator("a.btn-primary").first();
  if (await cta.count()) {
    await cta.hover();
    await page.waitForTimeout(260);
    await shot(page, `share-cta-hover-${label}`, { clip: await ctaClip(cta) });
  }
  await hoverShot(page, page.locator("a.made-with"), `share-madewith-hover-${label}`);
  await goldAudit(page, `share-ready-${label}`);
  await shot(page, `share-caption-${label}`, {
    clip: await captionClip(page.locator(".plate-caption").first()),
  });
  await page.close();

  // error state
  const err = await browser.newPage({ viewport: { width, height } });
  await err.route(SHARE_ROUTE, (route) =>
    route.fulfill({
      status: 404,
      headers: { "access-control-allow-origin": "*", "content-type": "application/json" },
      body: JSON.stringify({ detail: "not_found" }),
    }),
  );
  await err.goto(`${BASE}/p/share-stub-token`, { waitUntil: "domcontentloaded", timeout: 90000 });
  await settle(err);
  await shot(err, `share-error-${label}`);
  await hoverShot(err, err.getByRole("button", { name: /Qayta urinish/ }), `share-retry-hover-${label}`);
  await err.close();
}

// -------------------------------------------------------------- gold audit

// The "one gold per viewport" rule, measured rather than eyeballed. The gild
// is drawn by a ::after pseudo-element, so an element-only colour sweep would
// report zero — both pseudos are probed alongside the element itself.
const GOLD = ["rgb(173, 131, 1)", "rgb(208, 162, 21)"]; // yellow-600 / yellow-400

async function goldAudit(page, view) {
  const hits = await page.evaluate((gold) => {
    const found = [];
    for (const el of document.querySelectorAll("body *")) {
      for (const pseudo of [null, "::before", "::after"]) {
        const s = getComputedStyle(el, pseudo);
        // A pseudo with no content paints nothing, however its box resolves.
        if (pseudo && (s.content === "none" || s.content === "normal")) continue;
        const props = ["color", "backgroundColor", "borderTopColor", "borderBottomColor"];
        const hit = props.filter((p) => gold.includes(s[p]));
        if (!hit.length) continue;
        const r = el.getBoundingClientRect();
        found.push({
          tag: el.tagName.toLowerCase() + (el.className ? "." + String(el.className).split(" ")[0] : ""),
          pseudo: pseudo ?? "element",
          props: hit,
          top: Math.round(r.top + window.scrollY),
          text: (el.textContent ?? "").trim().slice(0, 32),
        });
      }
    }
    return found;
  }, GOLD);

  const vh = page.viewportSize().height;
  const bands = new Map();
  for (const h of hits) {
    const band = Math.floor(h.top / vh);
    bands.set(band, (bands.get(band) ?? 0) + 1);
  }
  console.log(`  GOLD AUDIT ${view}: ${hits.length} gold element(s)`);
  for (const h of hits) console.log(`    band ${Math.floor(h.top / vh)} @y=${h.top} ${h.tag} ${h.pseudo} [${h.props}] "${h.text}"`);
  const over = [...bands.entries()].filter(([, n]) => n > 1);
  console.log(over.length ? `    !! BANDS OVER LIMIT: ${JSON.stringify(over)}` : "    OK: <=1 gold per viewport band");
}

// ------------------------------------------------------------------- assets

async function assets() {
  for (const [from, to] of [
    ["../../packages/web/public/og.jpg", "og.jpg"],
    ["../../packages/web/app/icon.svg", "icon.svg"],
  ]) {
    await copyFile(from, `${OUT}/${to}`).then(
      () => console.log("  ->", to),
      (error) => console.log("  !! ", to, error.message),
    );
  }

  // The favicon at its real size, on both grounds — an SVG mark judged at
  // 2048px is not the mark anyone sees.
  const svg = await readFile("../../packages/web/app/icon.svg", "utf8");
  const icon = `data:image/svg+xml;utf8,${encodeURIComponent(svg)}`;
  const page = await browser.newPage({ viewport: { width: 420, height: 160 } });
  await page.setContent(`<body style="margin:0;display:flex">
    <div style="flex:1;background:#FFFCF0;display:grid;place-items:center">
      <img src="${icon}" width="32" height="32">
    </div>
    <div style="flex:1;background:#1C1B1A;display:grid;place-items:center">
      <img src="${icon}" width="32" height="32">
    </div>
  </body>`);
  await page.waitForTimeout(600);
  await shot(page, "asset-icon-32-both-grounds");
  await page.close();
}

for (const [label, vp] of [
  ["1440", VIEWPORTS.desktop],
  ["390", VIEWPORTS.phone],
]) {
  if (only === "all" || only === "landing") {
    console.log(`landing @ ${label}`);
    await landing(vp.width, vp.height, label);
  }
  if (only === "all" || only === "share") {
    console.log(`share @ ${label}`);
    await share(vp.width, vp.height, label);
  }
}
if (only === "all" || only === "assets") {
  console.log("assets");
  await assets();
}

await browser.close();
