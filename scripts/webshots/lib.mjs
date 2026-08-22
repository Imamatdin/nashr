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

// A wider folio for the /projects search, filter and sort shots: eight rows
// spanning every status the chips group and a date spread wide enough that
// name-sort and date-sort disagree. Opt in with mockSupabase(page, {manyProjects: true}).
const MANY_PROJECT_ROWS = [
  ...PROJECT_ROWS,
  {
    id: "p-4",
    title: "Kremniy quyosh panellari samaradorligi: 2020-2026 tahlili",
    type: "presentation",
    project_type: "presentation",
    status: "ready",
    share_token: null,
    created_at: "2026-08-12T11:30:00Z",
  },
  {
    id: "p-5",
    title: "Buyuk Ipak yo'li shaharlari: savdo tarmog'i geografiyasi",
    type: "presentation",
    project_type: "presentation",
    status: "failed",
    share_token: null,
    created_at: "2026-08-09T16:48:00Z",
  },
  {
    id: "p-6",
    title: "Fermentlar kinetikasi: Mixaelis-Menten modeli",
    type: "article",
    project_type: "article",
    status: "sourcing",
    share_token: null,
    created_at: "2026-07-31T08:15:00Z",
  },
  {
    id: "p-7",
    title: "Zamonaviy o'zbek dramaturgiyasida vaqt qatlamlari",
    type: "article",
    project_type: "article",
    status: "interview",
    share_token: null,
    created_at: "2026-07-24T19:02:00Z",
  },
  {
    id: "p-8",
    title: "Amudaryo delta ekotizimi: qayta tiklash stsenariylari",
    type: "presentation",
    project_type: "presentation",
    status: "archived",
    share_token: null,
    created_at: "2026-07-06T10:00:00Z",
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

// Options let a shot ask for a state the happy path never reaches (an empty
// folio list, a failed job) without forking the mock layer; every default
// reproduces the original behaviour, so journey.mjs is unaffected.
export async function mockSupabase(page, options = {}) {
  const { emptyProjects = false, manyProjects = false } = options;
  await page.route(`${SUPABASE_ORIGIN}/**`, async (route) => {
    const request = route.request();
    if (request.method() === "OPTIONS") {
      await fulfillPreflight(route);
      return;
    }
    const url = new URL(request.url());
    if (url.pathname === "/rest/v1/projects") {
      const id = eqValue(url.searchParams, "id");
      const source = emptyProjects ? [] : manyProjects ? MANY_PROJECT_ROWS : PROJECT_ROWS;
      const all = options.shareToken
        ? source.map((row) => (row.id === "p-1" ? { ...row, share_token: options.shareToken } : row))
        : source;
      const rows = id === null ? all : all.filter((row) => row.id === id);
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
      const all = options.emptySources ? [] : SOURCE_ROWS;
      const rows = projectId === null ? all : all.filter((row) => row.project_id === projectId);
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
  "/jobs",
  "/jobs/job-stub",
  "/projects",
  "/projects/p-1/deck",
  "/projects/p-1/provenance",
  "/projects/p-1/share",
  "/sources",
  "/sources/presign",
  "/r2-stub",
]);

// A delivered deck: the chrome around the viewer is what these shots are for,
// so the iframe points at a blank document rather than a real render.
const DECK_VIEW = {
  html_url: "about:blank",
  html_expires_in: 604800,
  downloads: [
    { format: "html", url: "about:blank", expires_in: 604800 },
    { format: "pdf", url: "about:blank", expires_in: 604800 },
    { format: "pptx", url: "about:blank", expires_in: 604800 },
  ],
};

const PROVENANCE_VIEW = {
  total_claims: 3,
  rows: [
    {
      claim_text: "Yoritish davri XVII–XVIII asrlarda Yevropada shakllangan.",
      quote: "The Enlightenment took shape across the long eighteenth century.",
      source_filename: "yoritish-davri-tarixi.pdf",
      chunk_index: 12,
    },
    {
      claim_text: "Monteskyoning hokimiyatlar bo'linishi g'oyasi konstitutsiyalarga kirdi.",
      quote: null,
      source_filename: "volter-va-monteskye-tahlil.docx",
      chunk_index: 4,
    },
    {
      claim_text: "Volter matbuot erkinligini asosiy shart deb bilgan.",
      quote: "Freedom of the press is the first of freedoms.",
      source_filename: "volter-va-monteskye-tahlil.docx",
      chunk_index: 9,
    },
  ],
};

const PROJECT_CREATED = {
  id: "p-1",
  title: "Yoritish davri: aql-idrok asrining tug'ilishi",
  project_type: "presentation",
  status: "draft",
};

export async function mockApi(page, options = {}) {
  const job = {
    ...JOB_VIEW,
    ...(options.jobStatus ? { status: options.jobStatus } : {}),
    ...(options.jobError !== undefined ? { error_message: options.jobError } : {}),
  };
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
      await fulfillJson(route, 200, job);
      return;
    }
    if (url.pathname === "/projects") {
      await fulfillJson(route, 200, PROJECT_CREATED);
      return;
    }
    if (url.pathname === "/sources/presign") {
      await fulfillJson(route, 200, {
        storage_key: "u-stub/p-1/yoritish-davri-tarixi.pdf",
        upload_url: `${API_ORIGIN}/r2-stub`,
        content_type: "application/pdf",
        expires_in: 900,
      });
      return;
    }
    // The browser PUTs the bytes straight at the presigned URL; the stub just
    // has to answer 200 so the register step runs.
    if (url.pathname === "/r2-stub") {
      await route.fulfill({ status: 200, headers: CORS_HEADERS, body: "" });
      return;
    }
    if (url.pathname === "/sources") {
      await fulfillJson(route, 200, SOURCE_ROWS[0]);
      return;
    }
    if (url.pathname === "/jobs") {
      // The refusal paths the flow has to dress: no credit (402, detail is an
      // object the client parses) and the daily cap (429).
      if (options.enqueue === "credit") {
        await fulfillJson(route, 402, { detail: { balance: 4000, required: 10000 } });
        return;
      }
      if (options.enqueue === "limit") {
        await fulfillJson(route, 429, { detail: "daily_job_limit" });
        return;
      }
      await fulfillJson(route, 200, job);
      return;
    }
    if (url.pathname === "/projects/p-1/share") {
      await fulfillJson(route, 200, { share_token: "share-stub-token" });
      return;
    }
    if (url.pathname === "/projects/p-1/deck") {
      if (options.deckReady) {
        await fulfillJson(route, 200, DECK_VIEW);
        return;
      }
      await fulfillJson(route, 404, { detail: "deck_not_ready" });
      return;
    }
    await fulfillJson(route, 200, options.deckReady ? PROVENANCE_VIEW : { rows: [], total_claims: 0 });
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
