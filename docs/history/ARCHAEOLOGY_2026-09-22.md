> Superseded by docs/adr/0001-canonical-document-state.md (2026-10-11); kept for history, not current guidance.

# Software archaeology — 2026-09-22

Baseline: `wire/coherence`, HEAD `a1ab4dc`, dirty checkout. The pre-existing
Docker/build/preflight and revision-pinned DOCX work is preserved. This is a
code-path audit, not production certification. The referenced ChatGPT task
returned no turns, so it supplies no additional evidence.

## Classification at the start of this audit

| Capability | Classification | Implementation evidence and reconciliation |
| --- | --- | --- |
| Upload registration | working/connected | `api/routes/sources.py`: ownership, presigned PUT, actual object size, registration. Deep validation happens later, not at registration. |
| Parsing, OCR, page chunks | implemented but disconnected from web articles | `workers/source/validation.py`, `parse_service.py`, `chunker.py`; existing generation orchestrators use them. `scripts/worker_run_job.py::_executor_for` has no source-processing executor. Reuse parsers without running paid claim extraction. |
| Durable article evidence | genuinely missing connection | `source_chunks`/`source_claims` exist in migration 001; database client has no chunk/claim persistence methods. Article editor cannot select evidence. Durable brain-session JSON is not a project evidence library. |
| Article matrix, outline, section draft, hedging, citation verification | implemented but disconnected from web | `bot/orchestrators/article_orchestrator.py` composes the existing workers. Web queue dispatch and admission support presentations only. Adapt persisted IDs and immutable article revisions before exposing generation. |
| Article citation integrity | partial/broken | `core/models/document.py` accepts arbitrary source/claim UUID pairs; `routes/documents.py` saves without resolving them. Current graph only maps session claims to sources, not article blocks. |
| Academic discovery | working/connected for search; disconnected for ingestion | `routes/research.py` searches four academic providers with timeout and availability. UI results are outbound links; no saved research record/full-text acquisition path. |
| Lex.uz | genuinely missing | `suggestions/providers/lex_uz.py` returns `[]`; route reports unavailable and UI offers external search. Provider comment about access agreements is an old assertion, not independent evidence of a legal requirement. Research permitted retrieval before implementing; do not invent an API. |
| Brain transport, caching, deck edits | working/connected at code level | `core/brain_loop.py`, `gemini_tools.py`, `gemini_cache.py`, `bot/sessions/driver.py`, API chat/worker presentation-edit path. Preserve signed model contents and one tool response per call. Live behavior remains unverified in this audit. |
| Source/history retrieval loop | genuinely missing | Brain declares only `edit_slides`; no execute-and-continue retrieval branch. `brain_prompts.py` retrieval/memory slots remain placeholders. Stage 5b recon still identifies the right seams; its no-queue assertion is superseded by migration 006 and worker. |
| Cross-project memory, reflection | genuinely missing | Project sessions exist; no user notes/history store or correction API. Reuse authored prompt documents after adding actual isolated tools, not before. |
| Proactive proposals | partial | Approval machinery exists; persisted caller origin/revision binding and autonomous originating path need completion. Model output cannot grant approval. |
| Planner and intent | partial/connected | `presentation/planner.py` produces deck plan; presentation orchestrator passes web topic into editorial. Full style/format intake advisor and independent slide briefs with neighbor constraints remain absent. User intent must never become source evidence. |
| Image routing/budget/cohesion | partial/connected | `image_pass.py` sorts hero first, caps generated tasks, handles portraits and scoped slide changes. Tier policy comes from constants. Shared cohesion note exists; five full visual families/restyling/font policy are not established. Unlimited-premium historical proposal conflicts with shipped bounded entitlements; retain as explicit unresolved policy, not a silent change. |
| Image telemetry | partial | Edit outcomes count generated images in presentation orchestrator; do not assume old invariant's blanket zero-count claim still applies to every path. Audit initial-generation persisted telemetry separately. |
| Exports | partial/connected | Presentation HTML/native PPTX/PDF render paths exist. Web article DOCX is revision-pinned by pre-existing local work but only prints citation labels and uses 12pt/2.5cm margins. Legacy article bibliography/styles/PDF workers exist and need canonical-document adapters. Old image-only PPTX default is superseded. |
| Revision/recovery | partial | Migrations 011–013, document/design routes, CAS saves/history/restore/render queue exist. Article load/history failures and durable unsaved draft recovery need work. Render versus canonical head races require review. |
| Localization | partial/connected | UZ/RU/EN workspace copy and language payload exist. Literal `Block type` remains in article editor; typography/length budgets and complete real-output journeys remain unverified. |
| Design/editor | partial | `presentation-designer*`: text/theme/order/history controls exist. Element positioning, chart/image editing/crop, undo/redo, reusable presets and proposal previews remain required. |
| One-shot/no iteration product model | obsolete/superseded | SPEC philosophy conflicts with the explicit editable/conversational workspace requirement. Preserve its grounding and export-quality requirements. |
| Old branch/server gates | obsolete as implementation blockers | BUILD_STATE contains successive and sometimes contradictory historical snapshots. AUTORUN close-out supersedes its parked-item tables. Current instruction explicitly separates deployment from product development. Never call historical production gates newly passed. |

## Architecture decision

Keep `BUILD_PLAN_2026-09-22.md` authoritative for dependency order. Keep old plans
as historical rationale, with this classification providing current evidence.
First connect validated uploads → immutable page-located passages → explicit
article attachments → saved revisions/exports. This is a prerequisite for paid
article assistance and a reusable corpus for brain retrieval. Keep raw passages,
extracted claims, attached references, and independent verifier verdicts distinct.

Use the existing Postgres queue and parsers. Atomically commit extraction under
the owning job/worker fence; never regenerate IDs on retry or replace evidence
referenced by old revisions. A source added during a job belongs to the next
explicit processing batch. Report per-source failures and permit retry.

Next: discovery persistence/safe acquisition; revision-bound article proposals;
source/history retrieval and user memory; design controls/visual policy;
resilience/localization; release. All earlier five-family, three-slot, intake,
per-slide brief, judge, loadable taste, AI Fill and locale-budget scope remains.
