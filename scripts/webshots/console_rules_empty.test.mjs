// node --test console_rules_empty.test.mjs
// The first-sight step's empty project: its own "not ready yet" 404s are accepted
// in that context only (B1-FIX3).
import assert from "node:assert/strict";
import { test } from "node:test";
import { expectedConsoleError } from "./console_rules.mjs";

const P = "e11ac1a4-809a-4cf1-8c0d-989db1e256dc";
const notFound = "Failed to load resource: the server responded with a status of 404 (Not Found)";

test("the empty project's own job, deck and decisions 404s are accepted in its context", () => {
  for (const url of [
    "http://127.0.0.1:8090/jobs?project_id=" + P,
    `http://127.0.0.1:8090/projects/${P}/deck`,
    `http://127.0.0.1:8090/projects/${P}/decisions`,
  ]) {
    assert.equal(expectedConsoleError({ text: notFound, url, emptyProject: P }), true, url);
  }
});

test("the same 404s are defects outside that context or for another project", () => {
  const deck = `http://127.0.0.1:8090/projects/${P}/deck`;
  assert.equal(expectedConsoleError({ text: notFound, url: deck }), false);
  assert.equal(expectedConsoleError({ text: notFound, url: deck, emptyProject: "other" }), false);
  const failed = "Failed to load resource: the server responded with a status of 500 (Internal Server Error)";
  assert.equal(expectedConsoleError({ text: failed, url: deck, emptyProject: P }), false);
  assert.equal(
    expectedConsoleError({ text: notFound, url: `http://127.0.0.1:8090/projects/${P}/chat`, emptyProject: P }),
    false,
  );
});
