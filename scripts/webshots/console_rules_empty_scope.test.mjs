// node --test console_rules_empty_scope.test.mjs   (CONSOLE_RULES=<module> picks another classifier)
//
// The first-sight step's empty-project allowance is exactly its own not-ready
// reads (B1-FIX4, Codex review of 3723d30): the API's /jobs?project_id=<it> and
// its /deck and /decisions, during the not-ready phase only. CI also runs this
// file with CONSOLE_RULES=./prefix/console_rules_3723d30.mjs, where the scope
// cases fail.
import assert from "node:assert/strict";
import { test } from "node:test";

const { expectedConsoleError } = await import(process.env.CONSOLE_RULES ?? "./console_rules.mjs");

const P = "e11ac1a4-809a-4cf1-8c0d-989db1e256dc";
const OTHER = "0be7a710-1111-4222-8333-944455556666";
const API = "http://127.0.0.1:8090";
const notFound = "Failed to load resource: the server responded with a status of 404 (Not Found)";
const accepted = (url, emptyProject = P) => expectedConsoleError({ text: notFound, url, emptyProject });

test("the empty project's own not-ready reads are accepted while it is not ready", () => {
  for (const url of [`${API}/jobs?project_id=${P}`, `${API}/projects/${P}/deck`, `${API}/projects/${P}/decisions`]) {
    assert.equal(accepted(url), true, url);
  }
});

test("another project's /jobs 404 is a defect in the empty project's context", () => {
  assert.equal(accepted(`${API}/jobs?project_id=${OTHER}`), false, "another project's /jobs 404 was accepted");
});

test("a /jobs 404 with any other query is a defect", () => {
  for (const url of [`${API}/jobs`, `${API}/jobs?project_id=${P}&status=queued`, `${API}/jobs?id=${P}`]) {
    assert.equal(accepted(url), false, `a /jobs 404 with another query was accepted: ${url}`);
  }
});

test("a not-ready 404 from anywhere but the API is a defect", () => {
  for (const url of [
    `http://127.0.0.1:3100/jobs?project_id=${P}`,
    `http://127.0.0.1:3100/projects/${P}/deck`,
    `http://example.test:8090/projects/${P}/decisions`,
  ]) {
    assert.equal(accepted(url), false, `a 404 from outside the API was accepted: ${url}`);
  }
});

test("once the not-ready phase is over the same 404s are defects", () => {
  for (const url of [`${API}/jobs?project_id=${P}`, `${API}/projects/${P}/deck`]) {
    assert.equal(accepted(url, null), false, url);
  }
});
