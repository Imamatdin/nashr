// Run with: node tests/sql/source-evidence.mjs <directory containing PGlite package.json>
// Uses actual PostgreSQL semantics locally. No network, Supabase keys or production writes.
import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { readFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { resolve } from "node:path";

const require = createRequire(resolve(process.argv[2] ?? ".", "package.json"));
const { PGlite } = require("@electric-sql/pglite");
const db = new PGlite();
const root = new URL("../../", import.meta.url);
const initial = await readFile(new URL("supabase/migrations/001_initial_schema.sql", root), "utf8");
const sourceSchema = initial.slice(initial.indexOf("create table if not exists sources ("), initial.indexOf("-- research_questions"));
const migration = await readFile(new URL("supabase/migrations/014_source_evidence.sql", root), "utf8");
const [user, project, otherProject, source, badSource, job, document] = Array.from({ length: 7 }, randomUUID);
let checks = 0;
async function check(name, run) { await run(); checks += 1; console.log(`PASS ${name}`); }
const rows = async (sql, args = []) => (await db.query(sql, args)).rows;
const chunks = [{ chunk_index: 0, text: "Source passage on page three.", page: 3, is_ocr: false, confidence: null }];
const commit = (id = source, worker = "worker", items = chunks, hash = "a".repeat(64)) =>
  rows("select commit_source_evidence($1,$2,$3,$4,$5,$6) as ok", [job, worker, id, JSON.stringify(items), hash, "[]"]);
const cite = (citation, doc = document) => rows(
  "insert into document_revisions(document_id,content) values($1,$2) returning id",
  [doc, JSON.stringify({ blocks: [{ text: "Article statement", citations: [citation] }] })],
);
try {
  await db.exec(`
    create role anon; create role authenticated; create role service_role bypassrls;
    create schema auth; create function auth.uid() returns uuid language sql as 'select null::uuid';
    create table projects(id uuid primary key, user_id uuid not null);
    ${sourceSchema}
    create table generation_jobs(id uuid primary key,project_id uuid,user_id uuid,worker_id text,job_type text,status text,payload jsonb);
    create table documents(id uuid primary key,project_id uuid,kind text);
    create table document_revisions(id uuid primary key default gen_random_uuid(),document_id uuid references documents(id),content jsonb);
    ${migration}
  `);
  await rows("insert into projects values($1,$2),($3,$2)", [project, user, otherProject]);
  for (const id of [source, badSource]) await rows(
    "insert into sources(id,project_id,filename,file_type,file_size_bytes,storage_key) values($1,$2,'study.txt','txt',100,'key')", [id, project],
  );
  await rows("insert into generation_jobs values($1,$2,$3,'worker','source_processing','processing',$4)", [job, project, user, JSON.stringify({ source_ids: [source, badSource] })]);
  await rows("insert into documents values($1,$2,'article')", [document, project]);

  await check("stale worker cannot publish", async () => assert.equal((await commit(source, "old-worker"))[0].ok, false));
  await check("valid commit retains page and conservative confidence", async () => {
    assert.equal((await commit())[0].ok, true);
    assert.deepEqual((await rows("select page,confidence from source_chunks where source_id=$1", [source]))[0], { page: 3, confidence: 100 });
  });
  const passage = (await rows("select id from source_chunks where source_id=$1", [source]))[0].id;
  await check("retry preserves cited identity and text", async () => {
    await commit(source, "worker", [{ ...chunks[0], text: "Changed content" }]);
    const saved = (await rows("select id,text from source_chunks where source_id=$1", [source]))[0];
    assert.equal(saved.id, passage); assert.equal(saved.text, chunks[0].text);
  });
  await check("invalid later row rolls back every passage", async () => {
    await assert.rejects(commit(badSource, "worker", [chunks[0], { ...chunks[0], chunk_index: 1, text: "" }]));
    assert.equal((await rows("select count(*)::int as n from source_chunks where source_id=$1", [badSource]))[0].n, 0);
    assert.equal((await rows("select evidence_processed_at from sources where id=$1", [badSource]))[0].evidence_processed_at, null);
  });
  await check("null content hash cannot mark a source ready", async () => assert.rejects(commit(badSource, "worker", chunks, null), /invalid_source_hash/));
  await check("source must be in the job snapshot", async () => assert.equal((await commit(randomUUID()))[0].ok, false));
  await check("only service role may execute worker commit", async () => {
    for (const role of ["anon", "authenticated"]) assert.equal((await rows("select has_function_privilege($1,'commit_source_evidence(uuid,text,uuid,jsonb,text,jsonb)','EXECUTE') as ok", [role]))[0].ok, false);
    assert.equal((await rows("select has_function_privilege('service_role','commit_source_evidence(uuid,text,uuid,jsonb,text,jsonb)','EXECUTE') as ok"))[0].ok, true);
  });
  await check("valid article passage citation inserts", async () => assert.equal((await cite({ source_id: source, passage_id: passage, label: "Study" })).length, 1));
  await check("wrong source rejected at revision boundary", async () => assert.rejects(cite({ source_id: badSource, passage_id: passage }), /invalid_citation/));
  await check("missing evidence rejected at revision boundary", async () => assert.rejects(cite({ source_id: source, passage_id: randomUUID() }), /invalid_citation/));
  await check("ambiguous passage and claim rejected", async () => assert.rejects(cite({ source_id: source, passage_id: passage, claim_id: randomUUID() }), /invalid_citation/));
  await check("other project's revision cannot borrow evidence", async () => {
    const otherDoc = randomUUID();
    await rows("insert into documents values($1,$2,'article')", [otherDoc, otherProject]);
    await assert.rejects(cite({ source_id: source, passage_id: passage }, otherDoc), /invalid_citation/);
  });
  await check("legacy claim citations resolve through the correct source passage", async () => {
    const claim = randomUUID();
    await rows("insert into source_claims(id,source_chunk_id,project_id,claim_text,strength) values($1,$2,$3,'Recorded interpretation','moderate')", [claim, passage, project]);
    assert.equal((await cite({ source_id: source, claim_id: claim })).length, 1);
    await assert.rejects(cite({ source_id: badSource, claim_id: claim }), /invalid_citation/);
  });
  console.log(`${checks} PostgreSQL evidence checks passed`);
} finally { await db.close(); }
