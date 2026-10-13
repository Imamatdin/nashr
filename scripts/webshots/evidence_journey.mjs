// Stage A browser journey against the local stack (scripts/local_stack).
// node scripts/webshots/evidence_journey.mjs <seed.json> <fixtures dir> <out dir>
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const [seedPath, fixturesDir, outDir] = process.argv.slice(2);
// JOURNEY_ONLY=delivery runs only the B1-FIX2 delivery steps (the pre-fix job).
const ONLY = process.env.JOURNEY_ONLY ?? "";
const HERE = dirname(fileURLToPath(import.meta.url));
const WEB = "http://127.0.0.1:3100";
const API = "http://127.0.0.1:8090";
const seed = JSON.parse(await readFile(seedPath, "utf8"));
const token = seed.session.accessToken;
await mkdir(outDir, { recursive: true });
const results = [];
const consoleErrors = [];
const failedRequests = [];
let currentPage = null;
// The only browser errors the journey accepts are the ones it causes on purpose,
// matched by URL and kind. Everything else is a defect and fails the run.
const EXPECTED_ERRORS = [
  // recovery steps abort or reset the article save request
  { url: /\/documents\/article$/, kind: /^net::ERR_(INTERNET_DISCONNECTED|CONNECTION_RESET|FAILED)$/ },
  // conflict steps save elsewhere first, so the browser's stale save gets 409
  { url: /\/documents\/article$/, kind: /^409$/ },
  // the local stack runs no Realtime server; the client falls back to polling
  { url: /\/realtime\/v1\//, kind: /.*/ },
];
const errorKind = (text) => text.match(/net::ERR_[A-Z_]+/)?.[0] ?? text.match(/status of (\d{3})/)?.[1] ?? "other";
const expectedError = (url, kind) =>
  EXPECTED_ERRORS.some((rule) => rule.url.test(url.split("?")[0]) && rule.kind.test(kind));
const redact = (text) =>
  text.replace(/apikey=[^&\s']+/g, "apikey=<redacted>").replace(/X-Amz-[A-Za-z]+=[^&\s]+/g, "X-Amz=<redacted>");

async function step(name, run) {
  try {
    await run();
    results.push({ name, ok: true });
    console.log(`PASS ${name}`);
  } catch (error) {
    const message = String(error?.message ?? error).split("\n")[0].slice(0, 400);
    results.push({ name, ok: false, error: message });
    console.log(`FAIL ${name}: ${message}`);
    if (currentPage) await currentPage.screenshot({ path: join(outDir, `FAIL-${results.length}.png`), fullPage: true }).catch(() => {});
  }
}

// JOURNEY_RECORD=1 (CI) keeps a video and a Playwright trace per browser context.
const record = process.env.JOURNEY_RECORD === "1";
let traceCount = 0;

async function openProject(
  browser,
  locale,
  { viewport = { width: 1440, height: 1000 }, session = seed.session, projectId = null, realtime = true } = {},
) {
  const context = await browser.newContext({
    viewport,
    acceptDownloads: true,
    locale: "en-US",
    ...(record ? { recordVideo: { dir: join(outDir, "video"), size: { width: 1280, height: 800 } } } : {}),
  });
  if (record) {
    await context.tracing.start({ screenshots: true, snapshots: true });
    const close = context.close.bind(context);
    const name = `trace-${locale}-${++traceCount}.zip`;
    context.close = async () => {
      await context.tracing.stop({ path: join(outDir, name) }).catch(() => {});
      return close();
    };
  }
  await context.addInitScript(([stored, chosen]) => {
    if (!window.sessionStorage.getItem("journey-seeded")) {
      window.localStorage.setItem("nashr.session", stored);
      window.localStorage.setItem("nashr.locale", chosen);
      window.sessionStorage.setItem("journey-seeded", "1");
    }
  }, [JSON.stringify(session), locale]);
  const page = await context.newPage();
  page.on("console", (message) => {
    if (message.type() !== "error") return;
    const text = message.text();
    const url = message.location()?.url ?? "";
    const kind = errorKind(text);
    consoleErrors.push({
      text: redact(`${locale}: ${text.slice(0, 300)} @ ${new URL(url || "about:blank").pathname}`),
      expected: expectedError(url, kind),
    });
  });
  page.on("pageerror", (error) =>
    consoleErrors.push({ text: `${locale} pageerror: ${error.message.slice(0, 300)}`, expected: false }),
  );
  page.on("response", (response) => {
    if (response.status() >= 400) failedRequests.push(redact(`${locale} ${response.status()} ${response.request().method()} ${new URL(response.url()).pathname}`));
  });
  currentPage = page;
  if (!realtime) {
    // Delivery must not depend on Realtime: refuse the websocket outright.
    await context.route(/\/realtime\/v1\//, (route) => route.abort());
  }
  await page.goto(`${WEB}/projects/${projectId ?? seed.projects[locale]}`);
  return { context, page };
}

// The stand-in render worker (scripts/local_stack/delivery_fixture.py).
function fixture(...args) {
  const out = execFileSync("python", [join(HERE, "..", "local_stack", "delivery_fixture.py"), ...args], {
    encoding: "utf8",
  });
  return JSON.parse(out.trim().split("\n").pop());
}

async function eventually(check, message, timeout = 60_000) {
  const until = Date.now() + timeout;
  for (;;) {
    if (await check()) return;
    if (Date.now() > until) throw new Error(message);
    await new Promise((resolve) => setTimeout(resolve, 1_000));
  }
}

async function deliverySteps(browser) {
  let generation = null;
  let page = null;
  let context = null;
  const marked = () => page.evaluate(() => window.__journeyNoReload === true).catch(() => false);
  const downloads = () => page.locator(".designer-downloads a[download]").count();

  await step("delivery: a paid deck follows its render to the downloads without reload or Realtime", async () => {
    generation = fixture("paid", seed.session.userId);
    ({ context, page } = await openProject(browser, "uz", { projectId: generation.project, realtime: false }));
    await page.locator(".designer-downloads").waitFor({ timeout: 90_000 });
    const sawDelivering = await page
      .locator('[data-testid="ws-delivering"]')
      .waitFor({ timeout: 20_000 })
      .then(() => true, () => false);
    assert.equal(await downloads(), 0, "downloads were offered before the render published");
    await page.evaluate(() => {
      window.__journeyNoReload = true;
    });
    const published = fixture("publish", generation.render, String(generation.token));
    assert.equal(published.completed, true, "the render did not complete");
    // The web delivers html (the preview), pdf and pptx (the two download links).
    await eventually(async () => (await downloads()) === 2, "downloads did not appear within 60 s without a reload");
    const partial = await page.locator(".designer-render-needed").count();
    assert.equal(partial, 0, "the downloads are still reported as incomplete");
    assert.equal(await marked(), true, "the page reloaded to show the downloads");
    assert.equal(sawDelivering, true, "the page never showed the delivery in progress");
    const job = await api(`/jobs?project_id=${generation.project}`);
    assert.equal(job.body.status, "completed", `the paid job is ${job.body.status} after delivery`);
    assert.equal(job.body.render_status, "completed");
    await shot(page, "10-delivery-done");
  });

  await step("delivery: an edit whose render fails restores the allowance and says so", async () => {
    assert.ok(generation && page, "needs the delivered deck from the previous step");
    const edit = fixture("edit", generation.project, seed.session.userId);
    await page.reload();
    const remaining = page.locator(".ws-fine", { hasText: "Qolgan tahrirlar" });
    await remaining.first().waitFor({ timeout: 60_000 });
    const before = await remaining.first().innerText();
    await page.evaluate(() => {
      window.__journeyNoReload = true;
    });
    const failed = fixture("fail", edit.render, String(edit.token));
    assert.equal(failed.render_status, "failed", "the render did not fail for good");
    await eventually(
      async () => (await page.locator('.chat-msg[data-role="system"]').count()) > 0,
      "the chat never said the edit's files could not be produced",
    );
    const notice = await page.locator('.chat-msg[data-role="system"]').last().innerText();
    assert.match(notice, /saqlandi/, `unexpected notice: ${notice}`);
    await eventually(
      async () => /2\s*\/\s*2/.test(await remaining.first().innerText()),
      `the allowance was not restored (was "${before}", now "${await remaining.first().innerText()}")`,
    );
    assert.equal(await marked(), true, "the page reloaded to show the failure");
    const job = await api(`/jobs/${edit.job}`);
    assert.equal(job.body.status, "delivery_failed", `the edit job is ${job.body.status}`);
    await shot(page, "11-edit-delivery-failed");
    await context.close();
  });
}

const ready = (page) => page.locator(".article-page textarea").first().waitFor({ timeout: 90_000 });
const shot = (page, name) => page.screenshot({ path: join(outDir, `${name}.png`), fullPage: true });
const status = (page, label) => page.locator(".article-save", { hasText: label }).waitFor({ timeout: 30_000 });
const paragraph = (page) => page.locator(".article-block.paragraph").first();

async function upload(page, filename) {
  await page.locator("#article-source-file").setInputFiles(join(fixturesDir, filename));
  await page.locator(".article-source-card > button").click();
  await page.locator(".article-source-card li", { hasText: filename }).waitFor({ timeout: 30_000 });
}

async function processSources(page, readyLabel, filename) {
  await page.locator(".evidence-process").click();
  await page.locator(".evidence-source-status", { hasText: filename }).locator("small", { hasText: readyLabel }).waitFor({ timeout: 120_000 });
}

async function cite(page, citeLabel, passageText, attachLabel) {
  const block = paragraph(page);
  await block.locator("textarea").focus();
  await block.getByRole("button", { name: citeLabel }).click();
  await page.locator(".source-passage", { hasText: passageText }).first().getByRole("button", { name: attachLabel }).click();
}

async function api(path, init = {}) {
  const response = await fetch(`${API}${path}`, {
    ...init,
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json", ...(init.headers ?? {}) },
  });
  return { status: response.status, body: await response.json().catch(() => null) };
}
const article = (project) => api(`/projects/${project}/documents/article`).then((r) => r.body);
async function saveElsewhere(project, text) {
  const head = await article(project);
  const content = { ...head.content, blocks: [...head.content.blocks, { id: crypto.randomUUID(), type: "paragraph", text, level: null, citations: [] }] };
  const saved = await api(`/projects/${project}/documents/article`, {
    method: "PUT",
    body: JSON.stringify({ base_revision_id: head.revision_id, idempotency_key: crypto.randomUUID(), content }),
  });
  assert.equal(saved.status, 200, "external save failed");
  return saved.body;
}
const revisions = (project) => api(`/projects/${project}/documents/article/revisions`).then((r) => r.body.revisions.length);
const draftCount = (page) => page.evaluate(() => Object.keys(window.localStorage).filter((key) => key.startsWith("nashr.articleDraft.")).length);
const blockTexts = (page) => page.locator(".article-page textarea").evaluateAll((nodes) => nodes.map((node) => node.value));
const saveRoute = (url) => url.pathname.endsWith("/documents/article");

const browser = await chromium.launch();
try {
  await deliverySteps(browser);
  if (ONLY !== "delivery") {
  // ------------------------------------------------------------------ UZ core
  const uz = seed.projects.uz;
  const { context, page } = await openProject(browser, "uz");
  await ready(page);

  await step("uz: upload PDF, DOCX and a corrupt PDF", async () => {
    for (const name of ["orol-dengizi-tarixi.pdf", "аральское-море.docx", "buzilgan-manba.pdf"]) await upload(page, name);
  });

  await step("uz: process; good sources ready, corrupt source named as unreadable", async () => {
    await processSources(page, "Tayyor", "orol-dengizi-tarixi.pdf");
    const broken = page.locator(".evidence-source-status", { hasText: "buzilgan-manba.pdf" });
    await broken.locator("small", { hasText: "Faylni o‘qib bo‘lmadi" }).waitFor({ timeout: 30_000 });
    await page.locator(".evidence-library [role=alert]", { hasText: "Ba’zi fayllarni o‘qib bo‘lmadi" }).waitFor();
    assert.match(await page.locator(".evidence-source-status", { hasText: "аральское-море.docx" }).innerText(), /Tayyor · 1/);
    await shot(page, "01-uz-processed");
  });

  await step("uz: DOCX passage shows a passage number, not an invented page", async () => {
    const docx = page.locator(".source-passage", { hasText: "Аральское море начало" }).first();
    assert.match(await docx.innerText(), /Parcha 1/);
    assert.doesNotMatch(await docx.innerText(), /Sahifa/);
  });

  const blockText = "Orol dengizi 1960-yildan beri qurib bormoqda.";
  await step("uz: write, attach a page-2 passage, autosave to server", async () => {
    await paragraph(page).locator("textarea").fill(blockText);
    await cite(page, "Manbaga havola", "2010-yilga kelib", "Tanlangan blokka biriktirish");
    await paragraph(page).locator(".article-citations", { hasText: "orol-dengizi-tarixi.pdf · 2" }).waitFor();
    await status(page, "Saqlandi");
    const cited = (await article(uz)).content.blocks.find((block) => block.text === blockText);
    assert.equal(cited?.citations.length, 1);
    assert.equal(await draftCount(page), 0, "draft kept after a confirmed save");
    await shot(page, "02-uz-attached");
  });

  await step("uz: inspect the cited passage", async () => {
    await page.locator(".article-citations button", { hasText: "orol-dengizi-tarixi.pdf" }).first().click();
    assert.match(await page.locator(".evidence-inspected .source-passage").innerText(), /2010-yilga kelib/);
  });

  await step("uz: reopen keeps text and citation", async () => {
    await page.reload();
    await ready(page);
    assert.ok((await blockTexts(page)).includes(blockText));
    await page.locator(".article-citations", { hasText: "orol-dengizi-tarixi.pdf · 2" }).waitFor();
  });

  await step("uz: remove the citation; persisted after reopen", async () => {
    await page.getByRole("button", { name: /Manba havolasini olib tashlash/ }).first().click();
    await status(page, "Saqlandi");
    await page.reload();
    await ready(page);
    assert.equal(await page.locator(".article-citations").count(), 0);
  });

  await step("uz: keyboard reaches the cite action from the text", async () => {
    await paragraph(page).locator("textarea").focus();
    const labels = [];
    for (let i = 0; i < 6; i += 1) {
      await page.keyboard.press("Shift+Tab");
      labels.push(await page.evaluate(() => document.activeElement?.getAttribute("aria-label") ?? ""));
      if (labels.at(-1) === "Manbaga havola") break;
    }
    assert.equal(labels.at(-1), "Manbaga havola", `focus order: ${labels.join(" | ")}`);
    await page.keyboard.press("Enter");
    await page.locator(".evidence-selection", { hasText: "Blok uchun manba" }).waitFor();
  });

  await step("uz: deleting the selected block clears the citation target", async () => {
    await paragraph(page).locator("textarea").focus();
    await paragraph(page).getByRole("button", { name: "Blok qo‘shish" }).click();
    const added = page.locator(".article-block.paragraph").nth(1);
    await added.locator("textarea").fill("Vaqtincha blok");
    await added.getByRole("button", { name: "Manbaga havola" }).click();
    await page.locator(".evidence-selection", { hasText: "Vaqtincha blok" }).waitFor();
    await added.locator("textarea").focus();
    await added.getByRole("button", { name: "Blokni o‘chirish" }).click();
    await page.locator(".evidence-selection", { hasText: "Avval maqola blokida" }).waitFor();
    await status(page, "Saqlandi");
  });

  await step("uz: re-attach and download DOCX of the saved revision", async () => {
    await cite(page, "Manbaga havola", "Orol dengizi 1960-yildan boshlab", "Tanlangan blokka biriktirish");
    await status(page, "Saqlandi");
    const [download] = await Promise.all([page.waitForEvent("download"), page.getByRole("button", { name: "DOCX yuklash" }).click()]);
    await download.saveAs(join(outDir, "uz-article.docx"));
  });

  // ------------------------------------------------------- recovery scenarios
  await step("recovery: save failure keeps a device draft, survives reload, then saves", async () => {
    await page.route(saveRoute, (route) => route.request().method() === "PUT" ? route.abort("internetdisconnected") : route.fallback());
    await paragraph(page).locator("textarea").fill(`${blockText} Oflayn tahrir.`);
    await page.locator(".article-alert", { hasText: "nusxasi shu qurilmada turibdi" }).waitFor({ timeout: 30_000 });
    assert.equal(await draftCount(page), 1);
    await shot(page, "03-recovery-error");
    await page.reload();
    await ready(page);
    await page.locator(".article-alert", { hasText: "saqlanmagan o‘zgarishlar tiklandi" }).waitFor({ timeout: 30_000 });
    assert.ok((await blockTexts(page)).includes(`${blockText} Oflayn tahrir.`), "draft text not restored");
    await shot(page, "04-recovery-resumed");
    await page.unroute(saveRoute);
    await page.getByRole("button", { name: "Hozir qayta urinish" }).click().catch(() => {});
    await status(page, "Saqlandi");
    assert.ok((await article(uz)).content.blocks.some((block) => block.text.endsWith("Oflayn tahrir.")));
    assert.equal(await draftCount(page), 0);
  });

  await step("recovery: a save whose response is lost replays instead of conflicting", async () => {
    const before = await revisions(uz);
    // Every browser save in this step: the replay must be the SAME operation.
    const puts = [];
    const onRequest = (request) => {
      if (request.method() === "PUT" && saveRoute(new URL(request.url()))) puts.push(JSON.parse(request.postData() ?? "{}"));
    };
    page.on("request", onRequest);
    let dropped = false;
    await page.route(saveRoute, async (route) => {
      if (route.request().method() !== "PUT" || dropped) return route.fallback();
      dropped = true;
      await route.fetch();
      await route.abort("connectionreset");
    });
    await paragraph(page).locator("textarea").fill(`${blockText} Javob yo‘qoldi.`);
    await status(page, "Saqlandi");
    await page.unroute(saveRoute);
    page.off("request", onRequest);
    assert.ok(dropped, "response was never dropped");
    assert.ok(puts.length >= 2, `expected the lost save to be replayed; saw ${puts.length} browser PUT(s)`);
    const [first, replay] = [puts[0], puts[puts.length - 1]];
    assert.equal(replay.idempotency_key, first.idempotency_key, "replay used a new idempotency key");
    assert.equal(replay.base_revision_id, first.base_revision_id, "replay changed its base");
    assert.deepEqual(replay.content, first.content, "replay changed the content");
    assert.equal(await page.locator(".article-alert", { hasText: "boshqa joyda o‘zgardi" }).count(), 0, "false conflict");
    assert.equal(await revisions(uz), before + 1, "replay created an extra revision");
  });

  await step("recovery: a live conflict lets the user keep their version", async () => {
    await saveElsewhere(uz, "Boshqa oynada qo‘shilgan xatboshi.");
    await paragraph(page).locator("textarea").fill(`${blockText} Mening versiyam.`);
    await page.locator(".article-alert", { hasText: "boshqa joyda o‘zgardi" }).waitFor({ timeout: 30_000 });
    await shot(page, "05-conflict");
    await page.getByRole("button", { name: "Mening versiyamni qoldirish" }).click();
    await status(page, "Saqlandi");
    const head = await article(uz);
    assert.ok(head.content.blocks.some((block) => block.text.endsWith("Mening versiyam.")));
    assert.ok(!head.content.blocks.some((block) => block.text.startsWith("Boshqa oynada")), "keep-mine merged the other version");
  });

  await step("recovery: a stale draft found on reopen is offered, not silently applied", async () => {
    await page.route(saveRoute, (route) => route.request().method() === "PUT" ? route.abort("internetdisconnected") : route.fallback());
    await paragraph(page).locator("textarea").fill(`${blockText} Eskirgan qoralama.`);
    await page.locator(".article-alert", { hasText: "nusxasi shu qurilmada turibdi" }).waitFor({ timeout: 30_000 });
    await saveElsewhere(uz, "Serverdagi yangi xatboshi.");
    await page.unroute(saveRoute);
    await page.reload();
    await ready(page);
    await page.locator(".article-alert", { hasText: "boshqa joyda o‘zgardi" }).waitFor({ timeout: 30_000 });
    await page.getByRole("button", { name: "Saqlangan versiyani olish" }).click();
    await status(page, "Saqlandi");
    const texts = await blockTexts(page);
    assert.ok(texts.includes("Serverdagi yangi xatboshi."));
    assert.ok(!texts.some((text) => text.endsWith("Eskirgan qoralama.")));
    assert.equal(await draftCount(page), 0);
  });

  await step("history: restore is blocked while changes are unsaved", async () => {
    await page.route(saveRoute, (route) => route.request().method() === "PUT" ? route.abort("internetdisconnected") : route.fallback());
    await paragraph(page).locator("textarea").fill(`${blockText} Tarix sinovi.`);
    await page.locator(".article-alert", { hasText: "nusxasi shu qurilmada turibdi" }).waitFor({ timeout: 30_000 });
    await page.getByRole("button", { name: "Versiyalar tarixi" }).click();
    await page.locator(".article-history", { hasText: "saqlanishini kuting" }).waitFor();
    assert.ok(await page.locator(".article-history button", { hasText: "Tiklash" }).first().isDisabled());
    await page.locator(".article-history header button").click();
    await page.unroute(saveRoute);
    await page.getByRole("button", { name: "Hozir qayta urinish" }).click();
    await status(page, "Saqlandi");
  });

  await step("uz: phone layout has no horizontal scroll", async () => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.waitForTimeout(500);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    await shot(page, "06-uz-phone");
    assert.ok(overflow <= 1, `horizontal overflow ${overflow}px`);
  });
  await context.close();

  // ---------------------------------------------------------------- isolation
  await step("isolation: another user cannot open the article", async () => {
    const intruder = { accessToken: seed.intruderToken, expiresAt: seed.session.expiresAt, userId: "00000000-0000-4000-8000-000000000000" };
    // The API itself refuses the other user, whatever the page renders.
    const direct = await fetch(`${API}/projects/${uz}/documents/article`, {
      headers: { Authorization: `Bearer ${seed.intruderToken}` },
    });
    assert.ok([403, 404].includes(direct.status), `intruder read the article: HTTP ${direct.status}`);
    const listed = await fetch(`${API}/projects/${uz}/documents/article/revisions`, {
      headers: { Authorization: `Bearer ${seed.intruderToken}` },
    });
    assert.ok([403, 404].includes(listed.status), `intruder listed revisions: HTTP ${listed.status}`);
    const { context: other, page: otherPage } = await openProject(browser, "uz", { session: intruder });
    await otherPage.waitForTimeout(8000);
    const body = await otherPage.locator("body").innerText();
    assert.ok(!body.includes(blockText), "intruder sees article text");
    assert.equal(await otherPage.locator(".article-page textarea").count(), 0);
    await shot(otherPage, "07-intruder");
    await other.close();
  });

  // ------------------------------------------------------------------- RU, EN
  await step("ru: Russian UI, DOCX passage, cite and save", async () => {
    const { context: ru, page: ruPage } = await openProject(browser, "ru");
    await ready(ruPage);
    await upload(ruPage, "аральское-море.docx");
    await processSources(ruPage, "Готов", "аральское-море.docx");
    assert.match(await ruPage.locator(".source-passage").first().innerText(), /Фрагмент 1/);
    await paragraph(ruPage).locator("textarea").fill("Арал пересыхает с 1960-х годов.");
    await cite(ruPage, "Сослаться на источник", "Аральское море начало", "Прикрепить к выбранному блоку");
    await status(ruPage, "Сохранено");
    await ruPage.getByRole("button", { name: "Скачать DOCX" }).waitFor();
    await shot(ruPage, "08-ru");
    await ru.close();
  });

  await step("en: English UI, PDF passage, cite, save and export", async () => {
    const { context: en, page: enPage } = await openProject(browser, "en");
    await ready(enPage);
    await upload(enPage, "orol-dengizi-tarixi.pdf");
    await processSources(enPage, "Ready", "orol-dengizi-tarixi.pdf");
    await paragraph(enPage).locator("textarea").fill("The Aral Sea has been shrinking since 1960.");
    await cite(enPage, "Cite a source", "Orol dengizi 1960-yildan boshlab", "Attach to selected block");
    await status(enPage, "Saved");
    const [download] = await Promise.all([enPage.waitForEvent("download"), enPage.getByRole("button", { name: "Download DOCX" }).click()]);
    await download.saveAs(join(outDir, "en-article.docx"));
    await shot(enPage, "09-en");
    await en.close();
  });
  }
} finally {
  await browser.close();
  const unique = [...new Set(failedRequests)];
  const unexpected = [...new Set(consoleErrors.filter((e) => !e.expected).map((e) => e.text))];
  const expected = consoleErrors.filter((e) => e.expected).length;
  await writeFile(
    join(outDir, "results.json"),
    JSON.stringify({ results, unexpectedConsoleErrors: unexpected, expectedConsoleErrors: expected, consoleErrors, failedRequests: unique }, null, 2),
  );
  console.log(
    `${results.filter((r) => r.ok).length}/${results.length} steps passed; console errors: ${unexpected.length} unexpected, ${expected} injected`,
  );
  for (const line of unexpected.slice(0, 20)) console.log(`  UNEXPECTED ${line}`);
  process.exitCode = results.every((result) => result.ok) && unexpected.length === 0 ? 0 : 1;
}
