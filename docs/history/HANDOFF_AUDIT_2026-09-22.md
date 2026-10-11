> Superseded by docs/adr/0001-canonical-document-state.md (2026-10-11); kept for history, not current guidance.

# Audit task handoff — 2026-09-22

## Ownership and user decision

User approved consolidating `Audit and continue Nashr build`
(`01a0c870-6b8f-7d52-8e8d-415de94abf8d`) into `Open and finish Nashr project`
(`01a096f1-d2e0-7203-b775-2c76fee6a2a3`). The latter is the sole implementation
writer. A detailed handoff was sent through the task messaging tool. The audit
task stopped product edits after discovering simultaneous writes to this checkout.
Task histories were not literally merged.

## Inspected

Checkout `C:\Users\imama\Projects\nashr`, branch `wire/coherence`, baseline HEAD
`a1ab4dc`. Read root Claude instructions and applicable database/core/source/article/
test rules. Inspected requested BUILD_STATE (including Plan of Record and later
status sections), BUILD_2_PLAN, RECON_5B, INVARIANTS, AUTORUN close-out, SPEC, current
September plan and September 21 handoff. Long files were inspected in targeted
sections; not every historical narrative was independently verified.

Traced source registration, validation/parsing/chunking, article orchestrator and
worker interfaces, brain loop/driver/prompt slots, image pass/planner/orchestrator,
research/Lex.uz, document routes/model/export, editor/graph, queue/worker dispatch,
storage/database and migrations 001, 005, 011–013. See
`ARCHAEOLOGY_2026-09-22.md` for the capability classification and decisions.

## Changes from the audit task

- Added `docs/ARCHAEOLOGY_2026-09-22.md`.
- Added `tests/unit/test_source_evidence.py`: real text/PDF extraction, empty input,
  distinct passage versus claim citation targets.
- Changed `packages/core/models/document.py`: optional claim/passage ID with
  exactly-one target constraint, preserving legacy claim references.
- Wrote `packages/workers/source/evidence.py` with `ExtractedPassages` and
  `extract_passages`. **This overwrote a same-path file concurrently created by the
  other task.** Its `ingest.py` expects `EvidenceExtractor`; reconcile from that
  task's own patch history. Do not assume this mixed state works.
- Added `supabase/migrations/014_persistent_evidence.sql`: fenced extraction commit
  and article-revision citation validation trigger. **Competes with the other
  task's `014_source_evidence.sql`; consolidate into one before applying.**
- Added this handoff. No product edits after collision detection.

A subsequent multi-file patch failed preflight at the worker executor and applied
nothing. Its proposed `platform/evidence.py`, `source/ingestion.py`, replacement
evidence routes and citation-error HTTP mapping were not written. Current API app
registration, evidence routes, database/storage methods and worker dispatch were
created by the other active task; preserve them.

## Validation actually performed

`python -m pytest tests/unit/test_source_evidence.py -q` exited 1 during collection:
`ImportError: cannot import name 'extract_passages'` while concurrent writes were
occurring. No passing tests, lint/typecheck, production test, commit, push,
migration application or deployment is claimed by this audit task.

## Required continuation

1. Reconcile the extractor API and duplicate migration; preserve useful tests and
   DB-level source/project/citation checks. Verify retries keep evidence IDs stable
   and stale workers cannot commit after cancellation/reaping.
2. Complete the vertical upload → passages → block citations → saved export path;
   expose extraction failures and retry. Passages are not verified claims.
3. Incorporate audit classifications into existing BUILD_PLAN without losing its
   retained historical scope. Continue paid article proposals and safe discovery
   ingestion, brain retrieval/memory, design/editing and resilience/localization
   in dependency order. Run targeted checks each batch and broader checks as needed.
4. Deployment remains separate. SSH, migrations and live provider/output quality
   are unverified; these do not block local product implementation.

The source model change adds nullable citation keys to serialization; audit exact
shape tests and TypeScript assumptions. Existing web DOCX formatting also differs
from the earlier publication specification. Neither issue is silently waived.
