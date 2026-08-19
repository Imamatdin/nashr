import { chromium } from "playwright";

export const VIEWPORTS = {
  desktop: { width: 1440, height: 900 },
  phone: { width: 390, height: 844 },
};

export const SUPABASE_ORIGIN = "https://stub.supabase.co";
export const API_ORIGIN = "https://api.stub.local";
export const TELEGRAM_SCRIPT = "https://telegram.org/js/telegram-web-app.js";

const CORS_HEADERS = {
  "access-control-allow-origin": "*",
  "access-control-allow-credentials": "true",
  "access-control-allow-methods": "GET, POST, PATCH, DELETE, OPTIONS",
  "access-control-allow-headers":
    "authorization, content-type, apikey, accept, accept-profile, content-profile, prefer, range, x-client-info, x-supabase-api-version",
  "access-control-expose-headers": "content-range, content-length",
  "access-control-max-age": "600",
};

function hourAhead() {
  return new Date(Date.now() + 60 * 60 * 1000).toISOString();
}

export function stubSession() {
  return { accessToken: "stub-token", expiresAt: hourAhead(), userId: "u-stub" };
}

export async function launchBrowser() {
  return chromium.launch();
}

function fulfillJson(route, status, body) {
  return route.fulfill({
    status,
    headers: { ...CORS_HEADERS, "content-type": "application/json" },
    body: JSON.stringify(body),
  });
}

function fulfillPreflight(route) {
  return route.fulfill({ status: 204, headers: CORS_HEADERS, body: "" });
}

export async function seedSession(page) {
  const payload = JSON.stringify(stubSession());
  await page.addInitScript((value) => {
    window.localStorage.setItem("nashr.session", value);
  }, payload);
}

const PROJECT_ROWS = [
  {
    id: "p-1",
    title: "Yoritish davri: aql-idrok asrining tug'ilishi",
    type: "presentation",
    project_type: "presentation",
    status: "ready",
    share_token: null,
    created_at: "2026-08-18T09:12:00Z",
  },
  {
    id: "p-2",
    title: "Orol dengizi qurishi: suv balansi va oqibatlar",
    type: "presentation",
    project_type: "presentation",
    status: "generating",
    share_token: null,
    created_at: "2026-08-17T14:05:00Z",
  },
  {
    id: "p-3",
    title: "Alisher Navoiy g'azallarida ramziy obrazlar",
    type: "presentation",
    project_type: "presentation",
    status: "draft",
    share_token: null,
    created_at: "2026-08-15T07:40:00Z",
  },
];

const SOURCE_ROWS = [
  {
    id: "s-1",
    project_id: "p-1",
    filename: "yoritish-davri-tarixi.pdf",
    file_type: "pdf",
    file_size_bytes: 2841233,
    storage_key: "u-stub/p-1/yoritish-davri-tarixi.pdf",
    created_at: "2026-08-18T09:20:00Z",
  },
  {
    id: "s-2",
    project_id: "p-1",
    filename: "volter-va-monteskye-tahlil.docx",
    file_type: "docx",
    file_size_bytes: 418902,
    storage_key: "u-stub/p-1/volter-va-monteskye-tahlil.docx",
    created_at: "2026-08-18T09:24:00Z",
  },
];

const JOB_VIEW = {
  id: "job-stub",
  project_id: "p-1",
  job_type: "presentation_generation",
  status: "processing",
  progress: { step: "Choosing design direction", current: 4, total: 7 },
  error_message: null,
  existing: false,
};

function wantsSingle(request) {
  const accept = request.headers()["accept"] ?? "";
  return accept.includes("vnd.pgrst.object");
}

function eqValue(search, column) {
  const raw = search.get(column);
  if (!raw || !raw.startsWith("eq.")) return null;
  return raw.slice(3);
}

export async function mockSupabase(page) {
  await page.route(`${SUPABASE_ORIGIN}/**`, async (route) => {
    const request = route.request();
    if (request.method() === "OPTIONS") {
      await fulfillPreflight(route);
      return;
    }
    const url = new URL(request.url());
    if (url.pathname === "/rest/v1/projects") {
      const id = eqValue(url.searchParams, "id");
      const rows = id === null ? PROJECT_ROWS : PROJECT_ROWS.filter((row) => row.id === id);
      if (wantsSingle(request)) {
        if (rows.length !== 1) {
          await fulfillJson(route, 406, {
            code: "PGRST116",
            message: "JSON object requested, multiple (or no) rows returned",
          });
          return;
        }
        await fulfillJson(route, 200, rows[0]);
        return;
      }
      await fulfillJson(route, 200, rows);
      return;
    }
    if (url.pathname === "/rest/v1/sources") {
      const projectId = eqValue(url.searchParams, "project_id");
      const rows =
        projectId === null ? SOURCE_ROWS : SOURCE_ROWS.filter((row) => row.project_id === projectId);
      if (wantsSingle(request)) {
        await fulfillJson(route, 200, rows[0] ?? null);
        return;
      }
      await fulfillJson(route, 200, rows);
      return;
    }
    await route.fallback();
  });
}

const API_PATHS = new Set([
  "/jobs/job-stub",
  "/projects/p-1/deck",
  "/projects/p-1/provenance",
]);

export async function mockApi(page) {
  await page.route(`${API_ORIGIN}/**`, async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (!API_PATHS.has(url.pathname)) {
      await route.fallback();
      return;
    }
    if (request.method() === "OPTIONS") {
      await fulfillPreflight(route);
      return;
    }
    if (url.pathname === "/jobs/job-stub") {
      await fulfillJson(route, 200, JOB_VIEW);
      return;
    }
    if (url.pathname === "/projects/p-1/deck") {
      await fulfillJson(route, 404, { detail: "deck_not_ready" });
      return;
    }
    await fulfillJson(route, 200, { rows: [], total_claims: 0 });
  });
}

function telegramScript(initData) {
  return `window.Telegram={WebApp:{initData:'${initData}',ready:function(){}}};`;
}

async function routeTelegramScript(page, initData) {
  await page.route(TELEGRAM_SCRIPT, (route) =>
    route.fulfill({
      status: 200,
      headers: { ...CORS_HEADERS, "content-type": "application/javascript" },
      body: telegramScript(initData),
    }),
  );
}

export async function mockTelegram(page) {
  await routeTelegramScript(page, "stub-init-data");
  await page.route(`${API_ORIGIN}/auth/telegram`, async (route) => {
    const request = route.request();
    if (request.method() === "OPTIONS") {
      await fulfillPreflight(route);
      return;
    }
    if (request.method() !== "POST") {
      await route.fallback();
      return;
    }
    await fulfillJson(route, 200, {
      access_token: "stub-token",
      token_type: "bearer",
      expires_at: hourAhead(),
      user_id: "u-stub",
    });
  });
}

// The inert bridge is what keeps login.png on the login page: a non-empty
// initData would auto-fire the Telegram door and redirect the shot away.
export async function stubTelegramInert(page) {
  await routeTelegramScript(page, "");
}

export async function settle(page, timeout = 6000) {
  await page.waitForLoadState("domcontentloaded");
  await page.waitForLoadState("networkidle", { timeout }).catch(() => {});
  await page.evaluate(() => document.fonts.ready).catch(() => {});
  await page.waitForTimeout(500);
}
