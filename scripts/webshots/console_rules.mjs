// Which browser console errors the evidence journey accepts (B1-FIX3, Codex N1).
//
// The journey fails on any console error it did not cause on purpose. Two kinds
// are caused on purpose:
//
// * article saves the recovery and conflict steps abort, reset or answer 409;
// * Realtime, refused inside the browser contexts that block it deliberately
//   (openProject({ realtime: false })). The local stack serves no Realtime, so if
//   a socket ever gets past that block the proxy answers its handshake 404 —
//   exactly that failure is accepted, and only in such a context. A handshake
//   that fails any other way (a 500, an auth failure) or any Realtime error in a
//   context that did not block it is a defect;
// * the first-sight step opens a project that has no job and no deck yet, so in
//   that context only, and only until the step creates the job, the API's
//   "not ready yet" 404s for that project are accepted: GET /jobs?project_id=<it>
//   (that exact query), and its own /deck and /decisions. The journey passes
//   emptyProject only during that phase (B1-FIX4, Codex review of 3723d30).

const ARTICLE_SAVE = /\/documents\/article$/;
const ARTICLE_RULES = [
  // recovery steps abort or reset the article save request
  { url: ARTICLE_SAVE, kind: /^net::ERR_(INTERNET_DISCONNECTED|CONNECTION_RESET|FAILED)$/ },
  // conflict steps save elsewhere first, so the browser's stale save gets 409
  { url: ARTICLE_SAVE, kind: /^409$/ },
];

export const REALTIME_URL = /^ws:\/\/127\.0\.0\.1:54321\/realtime\/v1\/websocket(\?|$)/;
const BLOCKED_REALTIME =
  /^WebSocket connection to 'ws:\/\/127\.0\.0\.1:54321\/realtime\/v1\/websocket\?[^']*' failed: Error during WebSocket handshake: Unexpected response code: 404$/;

export const API_ORIGIN = "http://127.0.0.1:8090";

/** True for the API's own "not ready yet" reads of `project`, and nothing else. */
function notReadyRead(url, project) {
  let parsed;
  try {
    parsed = new URL(url);
  } catch {
    return false;
  }
  if (parsed.origin !== API_ORIGIN) return false;
  if (parsed.pathname === "/jobs") {
    const keys = [...parsed.searchParams.keys()];
    return keys.length === 1 && parsed.searchParams.get("project_id") === project;
  }
  return parsed.search === "" && (parsed.pathname === `/projects/${project}/deck` || parsed.pathname === `/projects/${project}/decisions`);
}

/** The failure kind a console line reports: a net::ERR code, an HTTP status, or "other". */
export function errorKind(text) {
  return text.match(/net::ERR_[A-Z_]+/)?.[0] ?? text.match(/status of (\d{3})/)?.[1] ?? "other";
}

/**
 * True when the journey caused this console error on purpose.
 * `url` is the location Chromium reports; `realtimeBlocked` is whether the
 * browser context it came from refuses Realtime deliberately.
 */
export function expectedConsoleError({ text, url = "", realtimeBlocked = false, emptyProject = null }) {
  if (realtimeBlocked && BLOCKED_REALTIME.test(text)) return true;
  const path = url.split("?")[0];
  const kind = errorKind(text);
  // A context opened on a project that deliberately has no job and no deck yet,
  // while it still has none: its own "not ready yet" answers, and nothing else.
  if (emptyProject !== null && kind === "404" && notReadyRead(url, emptyProject)) return true;
  return ARTICLE_RULES.some((rule) => rule.url.test(path) && rule.kind.test(kind));
}
