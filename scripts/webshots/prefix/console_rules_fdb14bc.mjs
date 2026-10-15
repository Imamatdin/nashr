// The journey's console classifier exactly as it was at fdb14bc (Codex N1's
// subject), behind the interface of ../console_rules.mjs. CI's pre-fix job runs
// console_rules.test.mjs against this file: the negative cases must fail here.
// EXPECTED_ERRORS, errorKind, REFUSED_REALTIME and expectedError are copied
// verbatim from fdb14bc:scripts/webshots/evidence_journey.mjs.

const EXPECTED_ERRORS = [
  // recovery steps abort or reset the article save request
  { url: /\/documents\/article$/, kind: /^net::ERR_(INTERNET_DISCONNECTED|CONNECTION_RESET|FAILED)$/ },
  // conflict steps save elsewhere first, so the browser's stale save gets 409
  { url: /\/documents\/article$/, kind: /^409$/ },
  // the local stack runs no Realtime server; the client falls back to polling
  { url: /\/realtime\/v1\//, kind: /.*/ },
];
const errorKind = (text) => text.match(/net::ERR_[A-Z_]+/)?.[0] ?? text.match(/status of (\d{3})/)?.[1] ?? "other";
const REFUSED_REALTIME = /^WebSocket connection to 'ws:\/\/127\.0\.0\.1:54321\/realtime\/v1\/websocket\?/;
const expectedError = (url, kind, text = "") =>
  REFUSED_REALTIME.test(text) ||
  EXPECTED_ERRORS.some((rule) => rule.url.test(url.split("?")[0]) && rule.kind.test(kind));

export { errorKind };

export function expectedConsoleError({ text, url = "" }) {
  return expectedError(url, errorKind(text), text);
}
