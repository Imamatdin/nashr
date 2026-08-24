// Session W · P2 gate shot matrix.
//
// Covers every state in the workspace state machine (lib/workspace-state.ts)
// across light/dark at 1440/390, plus the surfaces the phase added: the
// clarification turn, the chat thread with a fix round-trip, the approval card,
// money visibility, and the error states the audit's §4 ledger named.
//
//   NODE_OPTIONS=--max-old-space-size=4096 npm run dev   (in packages/web)
//   node scripts/webshots/wire_p2.mjs
//
// The dev server needs the heap flag: /projects/[id] trips a known SWC issue
// without it. That is an environment gotcha, not a code defect.

import { mkdir } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { VIEWPORTS, launchBrowser, mockApi, mockSupabase, seedSession, settle } from "./lib.mjs";

const BASE = (process.env.BASE_URL ?? "http://localhost:3000").replace(/\/$/, "");
const OUT = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
  "..",
  "review",
  "wire_shots",
);

const W = VIEWPORTS.desktop.width;
const P = VIEWPORTS.phone.width;
const P1 = "/projects/p-1";

const results = [];

async function shoot(
  browser,
  { name, url, theme = "light", width = W, supabase = {}, api = {}, waitFor, act, noSession },
) {
  const ctx = await browser.newContext({
    viewport: { width, height: width > 600 ? 900 : 844 },
    deviceScaleFactor: 2,
  });
  const page = await ctx.newPage();
  await page.addInitScript((t) => localStorage.setItem("nashr.theme", t), theme);
  if (!noSession) await seedSession(page);
  await mockSupabase(page, supabase);
  await mockApi(page, api);

  let status = "OK";
  try {
    await page.goto(`${BASE}${url}`, { waitUntil: "domcontentloaded", timeout: 40000 });
    await settle(page);
    if (waitFor) {
      await page.waitForSelector(waitFor, { timeout: 15000 }).catch((error) => {
        status = `WARN missing ${waitFor}: ${String(error).split("\n")[0]}`;
      });
    }
    if (act) await act(page);
    await settle(page);
    await page.screenshot({ path: path.join(OUT, `${name}.png`), fullPage: true });
  } catch (error) {
    status = `FAIL ${String(error).split("\n")[0]}`;
  }
  results.push({ name, status });
  console.log(`${name.padEnd(46)} ${status}`);
  await ctx.close();
}

const browser = await launchBrowser();
await mkdir(OUT, { recursive: true });

// ---------------------------------------------------------- the state machine
//
// Each of these is a state the workspace can be in. The point of the matrix is
// that the priced start button appears in EXACTLY ONE of them.

for (const theme of ["light", "dark"]) {
  for (const width of [W, P]) {
    const tag = `${theme}-${width}`;

    // no_job — the only state that may show the idle priced CTA.
    await shoot(browser, {
      name: `ws-no-job-${tag}`,
      url: P1,
      theme,
      width,
      api: { noJob: true },
      waitFor: ".ws-start",
    });

    // queued / processing — a returning user with NO ?job= param. This is the
    // exact case that used to show the pay button (G3).
    await shoot(browser, {
      name: `ws-queued-${tag}`,
      url: P1,
      theme,
      width,
      api: { jobStatus: "queued" },
      waitFor: ".ws-wait",
    });
    await shoot(browser, {
      name: `ws-processing-${tag}`,
      url: P1,
      theme,
      width,
      waitFor: ".ws-live",
    });

    // failed, WITH the refund stated as a fact off the job-stamped ledger row.
    await shoot(browser, {
      name: `ws-failed-refunded-${tag}`,
      url: P1,
      theme,
      width,
      api: {
        jobStatus: "failed",
        jobError: "editorial: manbalar da'voni tasdiqlamadi",
        jobRefunded: true,
      },
      waitFor: ".ws-failed",
    });

    // completed but no deck yet — a WAIT that keeps listening, not a sentence.
    await shoot(browser, {
      name: `ws-completed-no-deck-${tag}`,
      url: P1,
      theme,
      width,
      api: { jobStatus: "completed" },
      waitFor: ".ws-wait",
    });

    // ready — the delivered deck beside the conversation.
    await shoot(browser, {
      name: `ws-ready-${tag}`,
      url: P1,
      theme,
      width,
      api: { jobStatus: "completed", deckReady: true },
      supabase: { shareToken: "share-stub-token" },
      waitFor: ".ws-deck",
    });
  }
}

// article + archived: states that must never show a presentation price (G13, G37).
for (const theme of ["light", "dark"]) {
  await shoot(browser, {
    name: `ws-article-${theme}-1440`,
    url: "/projects/p-6",
    theme,
    supabase: { manyProjects: true },
    api: { noJob: true },
    waitFor: ".state-blank",
  });
  await shoot(browser, {
    name: `ws-archived-${theme}-1440`,
    url: "/projects/p-8",
    theme,
    supabase: { manyProjects: true },
    api: { noJob: true },
    waitFor: ".state-blank",
  });
}

// ------------------------------------------------------------------ the chat

for (const theme of ["light", "dark"]) {
  await shoot(browser, {
    name: `ws-chat-thread-${theme}-1440`,
    url: P1,
    theme,
    api: { jobStatus: "completed", deckReady: true },
    waitFor: ".chat-scroll",
  });

  // The approval card, inline in the thread: a change the model proposed on its
  // own, which only a button may authorize.
  await shoot(browser, {
    name: `ws-chat-approval-${theme}-1440`,
    url: P1,
    theme,
    api: { jobStatus: "completed", deckReady: true, chat: "pending" },
    waitFor: ".chat-approval",
  });

  // An edit job re-rendering the deck: the deck stays on screen while it runs.
  await shoot(browser, {
    name: `ws-chat-applying-${theme}-1440`,
    url: P1,
    theme,
    api: { jobStatus: "completed", deckReady: true, chat: "applying" },
    waitFor: ".chat-footer",
  });

  // Editing refused honestly because there is no deck to edit yet.
  await shoot(browser, {
    name: `ws-chat-locked-${theme}-1440`,
    url: P1,
    theme,
    api: { chat: "no_session" },
    waitFor: ".chat-disabled",
  });
}

// A fix turn round-trip: type, send, and the reply lands.
await shoot(browser, {
  name: "ws-chat-fix-turn-light-1440",
  url: P1,
  api: { jobStatus: "completed", deckReady: true, chatTurn: "fix" },
  waitFor: ".chat-composer",
  act: async (page) => {
    await page.fill(".chat-input", "3-slayddagi sanani 2010 ga to'g'rila");
    await page.click(".chat-send");
    await page.waitForTimeout(1200);
  },
});

// The tier's edit allowance spent — a refusal that is information, not an error.
await shoot(browser, {
  name: "ws-chat-exhausted-light-1440",
  url: P1,
  api: { jobStatus: "completed", deckReady: true, chat: "exhausted", chatTurn: "exhausted" },
  waitFor: ".chat-composer",
  act: async (page) => {
    await page.fill(".chat-input", "yana bitta tuzatish");
    await page.click(".chat-send");
    await page.waitForTimeout(1200);
  },
});

// The chat mobile tab.
await shoot(browser, {
  name: "ws-chat-light-390",
  url: P1,
  width: P,
  api: { jobStatus: "completed", deckReady: true },
  waitFor: ".ws-tabs",
  act: async (page) => {
    await page.click('.ws-tabs button:has-text("Suhbat")');
    await page.waitForTimeout(400);
  },
});

// ------------------------------------------------------- decisions (G14)
//
// The last of the audit's S1 rows: the pipeline persisted its own design
// direction, binding plan and resolved preferences, and no route returned any
// of it, so the trace could only repeat step labels.

for (const theme of ["light", "dark"]) {
  await shoot(browser, {
    name: `ws-decisions-${theme}-1440`,
    url: P1,
    theme,
    api: { jobStatus: "completed", deckReady: true },
    waitFor: ".ws-drawer",
    act: async (page) => {
      const drawer = page.locator('.ws-drawer:has(> summary:text-is("Nima qaror qilindi"))');
      await drawer.locator("summary").click();
      await page.waitForTimeout(400);
    },
  });
}

// A deck generated before the planner became binding has no argument to show;
// the design and the roster still do.
await shoot(browser, {
  name: "ws-decisions-no-plan-light-1440",
  url: P1,
  api: { jobStatus: "completed", deckReady: true, decisions: "no_plan" },
  waitFor: ".ws-drawer",
  act: async (page) => {
    const drawer = page.locator('.ws-drawer:has(> summary:text-is("Nima qaror qilindi"))');
    await drawer.locator("summary").click();
    await page.waitForTimeout(400);
  },
});

// ------------------------------------------------------------ the money moment

for (const theme of ["light", "dark"]) {
  for (const width of [W, P]) {
    await shoot(browser, {
      name: `hisob-${theme}-${width}`,
      url: "/hisob",
      theme,
      width,
      waitFor: "main",
    });
  }
}
await shoot(browser, { name: "hisob-empty-light-1440", url: "/hisob", api: { ledgerEmpty: true }, waitFor: "main" });
await shoot(browser, { name: "hisob-unreachable-light-1440", url: "/hisob", api: { creditsDown: true }, waitFor: "main" });

// ---------------------------------------------------------------- /new flow

for (const theme of ["light", "dark"]) {
  for (const width of [W, P]) {
    await shoot(browser, { name: `new-empty-${theme}-${width}`, url: "/new", theme, width, waitFor: "[data-promptbar]" });
  }
  // The clarification turn — the questions the engine has always been able to
  // derive and nothing ever asked (G2).
  await shoot(browser, {
    name: `new-interview-${theme}-1440`,
    url: "/new",
    theme,
    api: { interview: "ready" },
    waitFor: "[data-promptbar]",
  });
}

// First run: no processed sources yet, so the honest "decide for me" path.
await shoot(browser, {
  name: "new-decide-for-me-light-1440",
  url: "/new",
  api: { interview: "not_ready" },
  waitFor: "[data-promptbar]",
});

// ------------------------------------------------------------- error states

await shoot(browser, {
  name: "ws-402-insufficient-light-1440",
  url: P1,
  api: { noJob: true, enqueue: "credit" },
  waitFor: ".ws-start",
  act: async (page) => {
    await page.click(".ws-start button");
    await page.waitForTimeout(900);
  },
});

await shoot(browser, {
  name: "ws-429-rate-limited-light-1440",
  url: P1,
  api: { noJob: true, enqueue: "limit" },
  waitFor: ".ws-start",
  act: async (page) => {
    await page.click(".ws-start button");
    await page.waitForTimeout(900);
  },
});

// An unreachable backend must never look like loading (G12).
await shoot(browser, {
  name: "projects-unreachable-light-1440",
  url: "/projects",
  supabase: { unreachable: true },
  waitFor: "main",
});
await shoot(browser, { name: "projects-empty-light-1440", url: "/projects", supabase: { emptyProjects: true }, waitFor: "main" });
await shoot(browser, { name: "projects-many-light-1440", url: "/projects", supabase: { manyProjects: true }, waitFor: "main" });

// Session expiry: no stored session at all, so the guard must route to a door
// carrying returnTo rather than stranding the visitor.
await shoot(browser, {
  name: "ws-session-expired-light-1440",
  url: P1,
  noSession: true,
  // The guard redirects to a door; the shot exists to prove it carries
  // returnTo rather than stranding the visitor on /projects.
  waitFor: "form, .door-shell, input[type=email]",
  act: async (page) => {
    const url = page.url();
    if (!url.includes("returnTo")) console.log(`    !! login URL lost returnTo: ${url}`);
    else console.log(`    returnTo carried: ${decodeURIComponent(url.split("returnTo=")[1] ?? "")}`);
  },
});

// ------------------------------------------------------------- share view

for (const theme of ["light", "dark"]) {
  await shoot(browser, {
    name: `share-deck-${theme}-1440`,
    url: "/p/share-stub-token",
    theme,
    waitFor: ".share-take",
  });
}
await shoot(browser, { name: "share-deck-light-390", url: "/p/share-stub-token", width: P, waitFor: ".share-take" });
await shoot(browser, { name: "share-404-light-1440", url: "/p/share-stub-token", api: { shareState: "error" }, waitFor: ".share-error" });

await browser.close();

const bad = results.filter((r) => r.status !== "OK");
console.log(`\n${results.length} shots · ${results.length - bad.length} OK · ${bad.length} not OK`);
for (const row of bad) console.log(`  ${row.name}: ${row.status}`);
