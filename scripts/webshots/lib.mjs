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

// Timestamps are relative so the elapsed clock and the stall check render
// something real in a shot instead of a frozen zero.
function minutesAgo(n) {
  return new Date(Date.now() - n * 60_000).toISOString();
}

const JOB_VIEW = {
  id: "job-stub",
  project_id: "p-1",
  job_type: "presentation_generation",
  status: "processing",
  progress: { step: "Choosing design direction", current: 4, total: 7 },
  error_message: null,
  existing: false,
  created_at: minutesAgo(3),
  started_at: minutesAgo(2.6),
  heartbeat_at: new Date(Date.now() - 4_000).toISOString(),
  completed_at: null,
  package: "presentation_standard",
  deducted_amount: 10_000,
  refunded: false,
};

const PRICING_VIEW = {
  currency: "UZS",
  packages: [
    { package: "presentation_basic", price: 5_000, ai_images: 0, fix_allowance: 1 },
    { package: "presentation_standard", price: 10_000, ai_images: 2, fix_allowance: 2 },
    { package: "presentation_premium", price: 15_000, ai_images: 5, fix_allowance: 3 },
  ],
  free_credit_value: 5_000,
  free_daily_cap: 3,
  free_weekly_cap: 10,
  free_project_cap: 5,
};

const LEDGER_VIEW = {
  balance: 35_000,
  entries: [
    {
      id: "l-5",
      amount: 10_000,
      action: "refund",
      reason: "refund",
      project_id: "p-5",
      generation_job_id: "job-failed",
      created_at: minutesAgo(60),
    },
    {
      id: "l-4",
      amount: -10_000,
      action: "deduct_presentation",
      reason: "generation:presentation_standard",
      project_id: "p-5",
      generation_job_id: null,
      created_at: minutesAgo(75),
    },
    {
      id: "l-3",
      amount: 5_000,
      action: "grant_free",
      reason: "source_upload",
      project_id: "p-1",
      generation_job_id: null,
      created_at: minutesAgo(2_880),
    },
    {
      id: "l-2",
      amount: -10_000,
      action: "deduct_presentation",
      reason: "generation:presentation_standard",
      project_id: "p-1",
      generation_job_id: null,
      created_at: minutesAgo(2_900),
    },
    {
      id: "l-1",
      amount: 50_000,
      action: "grant_paid",
      reason: "payment",
      project_id: null,
      generation_job_id: null,
      created_at: minutesAgo(4_320),
    },
  ],
};

const CHAT_VIEW = {
  can_edit: true,
  messages: [
    { role: "user", text: "3-slayddagi sanani 2010 ga to'g'rila" },
    {
      role: "assistant",
      text: "3-slaydda sana 2010 ga o'zgartirildi va manbadagi raqam bilan solishtirildi.",
    },
  ],
  pending_action: null,
  fixes_used: 1,
  fix_limit: 2,
  fixes_remaining: 1,
  package: "presentation_standard",
  slide_count: 11,
  applying_job_id: null,
};

const INTERVIEW_VIEW = {
  detected_domain: "history",
  estimated_slide_count: 11,
  available_stats_count: 4,
  available_people_count: 5,
  questions: [
    {
      question_id: "audience",
      question_text: "Kim uchun tayyorlanmoqda?",
      question_type: "single_select",
      options: [
        { value: "school", label: "Maktab o'quvchilari (9-11 sinf)", is_default: false },
        { value: "undergraduate", label: "Bakalavr talabalari", is_default: true },
        { value: "academic_conference", label: "Akademik konferentsiya", is_default: false },
      ],
      min_value: null,
      max_value: null,
      default_value: null,
      placeholder: null,
      help_text: null,
    },
    {
      question_id: "emphasis",
      question_text: "Taqdimot nimaga ko'proq urg'u bersin?",
      question_type: "multi_select",
      options: [
        { value: "problem_framing", label: "Muammoni shakllantirish", is_default: false },
        { value: "results_numbers", label: "Natijalar va raqamlar", is_default: true },
        { value: "roadmap", label: "Keyingi qadamlar", is_default: false },
      ],
      min_value: null,
      max_value: null,
      default_value: null,
      placeholder: null,
      help_text: null,
    },
    {
      question_id: "closing_ask",
      question_text: "Yakuniy slaydda nima so'ralsin?",
      question_type: "text",
      options: null,
      min_value: null,
      max_value: null,
      default_value: null,
      placeholder: "Masalan: siyosat tavsiyasi",
      help_text: null,
    },
  ],
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
    // `unreachable` is a dead backend, not a slow one: the connection is
    // refused rather than answered. The whole point of G12 is that this must
    // NOT render as the loading state.
    if (options.unreachable) {
      await route.abort("connectionrefused");
      return;
    }
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
  "/public/decks/share-stub-token",
  "/sources",
  "/sources/presign",
  "/r2-stub",
  // Session W (P1) seams the workspace, /new and the chrome now depend on.
  "/credits",
  "/credits/ledger",
  "/pricing",
  "/auth/refresh",
  "/projects/p-1/chat",
  "/projects/p-1/chat/approve",
  "/projects/p-1/chat/reject",
  "/projects/p-1/interview",
]);

// The public share view resolves a token to a short-TTL signed URL. Opt in with
// mockApi(page, {shareState: "deck" | "error" | "loading"}); default routes fall
// through untouched so the existing shots are unaffected.
const SHARED_DECK_VIEW = {
  title: "Yoritish davri: aql-idrok asrining tug'ilishi",
  html_url: "about:blank",
  // The real signed-URL TTL, not a link lifetime: a fixture carrying 7 days
  // here is what let the wrong "7 KUNDAN" caption look correct in a shot.
  expires_in: 900,
  downloads: [
    { format: "pptx", url: "about:blank", expires_in: 3600 },
    { format: "pdf", url: "about:blank", expires_in: 3600 },
  ],
};

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
      strength: "strong",
      source_filename: "yoritish-davri-tarixi.pdf",
      chunk_index: 12,
    },
    {
      claim_text: "Monteskyoning hokimiyatlar bo'linishi g'oyasi konstitutsiyalarga kirdi.",
      quote: null,
      strength: "moderate",
      source_filename: "volter-va-monteskye-tahlil.docx",
      chunk_index: 4,
    },
    {
      claim_text: "Volter matbuot erkinligini asosiy shart deb bilgan.",
      quote: "Freedom of the press is the first of freedoms.",
      strength: "strong",
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
    ...(options.jobRefunded ? { refunded: true } : {}),
    ...(options.jobStalled
      ? { heartbeat_at: new Date(Date.now() - 120_000).toISOString() }
      : {}),
    ...(options.jobStatus === "completed"
      ? { completed_at: new Date(Date.now() - 30_000).toISOString() }
      : {}),
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
      // GET /jobs?project_id= is the DISCOVERY route the workspace derives its
      // whole state from; POST /jobs is the enqueue. `noJob` is how a shot asks
      // for "this project has never been generated", which is the only state
      // that may show a priced start button.
      if (request.method() === "GET") {
        if (options.noJob) {
          await fulfillJson(route, 404, { detail: "job_not_found" });
          return;
        }
        await fulfillJson(route, 200, job);
        return;
      }
      // The refusal paths the flow has to dress: no credit (402, structured so
      // the client can state the real shortfall) and the cap (429, carrying the
      // counter state so the copy can say WHEN it resets).
      if (options.enqueue === "credit") {
        await fulfillJson(route, 402, {
          detail: { reason: "insufficient_balance", balance: 4000, required: 10000 },
        });
        return;
      }
      if (options.enqueue === "limit") {
        await fulfillJson(route, 429, {
          detail: {
            reason: "rate_limited",
            scope: "user",
            count: 11,
            limit: 10,
            resets_at: new Date(Date.now() + 20 * 60_000).toISOString(),
          },
        });
        return;
      }
      await fulfillJson(route, 200, { ...job, existing: Boolean(options.enqueueExisting) });
      return;
    }
    if (url.pathname === "/credits") {
      if (options.creditsDown) {
        await fulfillJson(route, 500, { detail: "ledger_unavailable" });
        return;
      }
      await fulfillJson(route, 200, { balance: LEDGER_VIEW.balance, currency: "UZS" });
      return;
    }
    if (url.pathname === "/credits/ledger") {
      if (options.creditsDown) {
        await fulfillJson(route, 500, { detail: "ledger_unavailable" });
        return;
      }
      await fulfillJson(route, 200, options.ledgerEmpty ? { balance: 0, entries: [] } : LEDGER_VIEW);
      return;
    }
    if (url.pathname === "/pricing") {
      await fulfillJson(route, 200, PRICING_VIEW);
      return;
    }
    if (url.pathname === "/auth/refresh") {
      await fulfillJson(route, 200, {
        access_token: "stub-token",
        token_type: "bearer",
        expires_at: new Date(Date.now() + 3_600_000).toISOString(),
        user_id: "u-stub",
      });
      return;
    }
    if (url.pathname === "/projects/p-1/interview") {
      // 409 is the DESIGNED first-run answer, not a failure: sources are only
      // processed during generation.
      if (options.interview === "not_ready") {
        await fulfillJson(route, 409, { detail: { reason: "sources_not_ready" } });
        return;
      }
      await fulfillJson(route, 200, INTERVIEW_VIEW);
      return;
    }
    if (url.pathname === "/projects/p-1/chat") {
      if (request.method() === "GET") {
        if (options.chat === "no_session") {
          await fulfillJson(route, 200, {
            ...CHAT_VIEW,
            can_edit: false,
            messages: [],
            fixes_used: 0,
            slide_count: 0,
          });
          return;
        }
        if (options.chat === "pending") {
          await fulfillJson(route, 200, {
            ...CHAT_VIEW,
            pending_action: {
              reason: "Manbadagi raqam slayd bilan mos kelmadi — ikkalasini moslashtiraman.",
              fixes: [
                { slide_id: "slide_03", instruction: "Sanani 2010 ga to'g'rila" },
                { slide_id: "slide_07", instruction: "Xulosadagi raqamni yangila" },
              ],
            },
          });
          return;
        }
        if (options.chat === "applying") {
          await fulfillJson(route, 200, { ...CHAT_VIEW, applying_job_id: "job-edit" });
          return;
        }
        if (options.chat === "exhausted") {
          await fulfillJson(route, 200, { ...CHAT_VIEW, fixes_used: 2, fixes_remaining: 0 });
          return;
        }
        await fulfillJson(route, 200, CHAT_VIEW);
        return;
      }
      if (options.chatTurn === "exhausted") {
        await fulfillJson(route, 409, {
          detail: { reason: "fixes_exhausted", fix_limit: 2, fixes_used: 2 },
        });
        return;
      }
      if (options.chatTurn === "busy") {
        await fulfillJson(route, 409, {
          detail: { reason: "brain_busy", job_id: "job-edit", job_type: "presentation_edit" },
        });
        return;
      }
      await fulfillJson(route, 200, {
        kind: options.chatTurn === "fix" ? "fix_ready" : "reply",
        reply:
          options.chatTurn === "fix"
            ? "3-slayddagi sanani tuzatdim — taqdimot qayta yig'ilmoqda."
            : "Bu taqdimotda 11 ta slayd bor; 3-slayd Volterga bag'ishlangan.",
        pending_action: null,
        job_id: options.chatTurn === "fix" ? "job-edit" : null,
        fixes_used: 1,
        fix_limit: 2,
        fixes_remaining: 1,
      });
      return;
    }
    if (url.pathname === "/projects/p-1/chat/approve" || url.pathname === "/projects/p-1/chat/reject") {
      await fulfillJson(route, 200, {
        kind: url.pathname.endsWith("approve") ? "fix_ready" : "reply",
        reply: null,
        pending_action: null,
        job_id: url.pathname.endsWith("approve") ? "job-edit" : null,
        fixes_used: 1,
        fix_limit: 2,
        fixes_remaining: 1,
      });
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
    if (url.pathname === "/public/decks/share-stub-token") {
      if (options.shareState === "error") {
        await fulfillJson(route, 404, { detail: "share_not_found" });
        return;
      }
      if (options.shareState === "loading") {
        // Never fulfilled: leaves the page on its skeleton for the shot.
        return;
      }
      await fulfillJson(route, 200, SHARED_DECK_VIEW);
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
