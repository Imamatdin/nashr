// node --test console_rules.test.mjs   (CONSOLE_RULES=<module> picks another classifier)
//
// The journey's console classifier (B1-FIX3, Codex N1): the deliberate Realtime
// refusal is accepted only in a context that blocked Realtime, and only as the
// exact handshake failure the local stack produces. CI also runs this file with
// CONSOLE_RULES=./prefix/console_rules_fdb14bc.mjs, where the negative cases fail.
import assert from "node:assert/strict";
import { test } from "node:test";

const { expectedConsoleError } = await import(process.env.CONSOLE_RULES ?? "./console_rules.mjs");

const SOCKET = "ws://127.0.0.1:54321/realtime/v1/websocket?apikey=anon-key&vsn=2.0.0";
const handshake = (code) =>
  `WebSocket connection to '${SOCKET}' failed: Error during WebSocket handshake: Unexpected response code: ${code}`;
const CHUNK = "http://127.0.0.1:3100/_next/static/chunks/758-1bfae06dc470f829.js";

test("the deliberate refusal is accepted in the context that blocked Realtime", () => {
  assert.equal(expectedConsoleError({ text: handshake(404), url: CHUNK, realtimeBlocked: true }), true);
});

test("a Realtime handshake 500 is a defect even where Realtime is blocked", () => {
  assert.equal(
    expectedConsoleError({ text: handshake(500), url: CHUNK, realtimeBlocked: true }),
    false,
    "a handshake 500 was accepted as the injected refusal",
  );
});

test("a Realtime auth failure is a defect even where Realtime is blocked", () => {
  for (const code of [401, 403]) {
    assert.equal(
      expectedConsoleError({ text: handshake(code), url: CHUNK, realtimeBlocked: true }),
      false,
      `a handshake ${code} was accepted as the injected refusal`,
    );
  }
});

test("the refusal outside a context that blocked Realtime is a defect", () => {
  assert.equal(
    expectedConsoleError({ text: handshake(404), url: CHUNK, realtimeBlocked: false }),
    false,
    "a Realtime failure was accepted in a context that never blocked Realtime",
  );
});

test("any other error located at the Realtime socket is a defect", () => {
  assert.equal(
    expectedConsoleError({
      text: "Failed to load resource: net::ERR_CONNECTION_REFUSED",
      url: SOCKET,
      realtimeBlocked: false,
    }),
    false,
    "an error located at the Realtime URL was accepted by URL alone",
  );
});

test("the article steps' injected failures are still accepted", () => {
  const save = "http://127.0.0.1:8090/projects/p/documents/article";
  assert.equal(
    expectedConsoleError({ text: "Failed to load resource: net::ERR_INTERNET_DISCONNECTED", url: save }),
    true,
  );
  assert.equal(
    expectedConsoleError({
      text: "Failed to load resource: the server responded with a status of 409 (Conflict)",
      url: save,
    }),
    true,
  );
  assert.equal(
    expectedConsoleError({
      text: "Failed to load resource: the server responded with a status of 500 (Internal Server Error)",
      url: save,
    }),
    false,
  );
});
