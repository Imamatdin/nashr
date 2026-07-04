# BUILD 2 — THE BRAIN — BUILD PLAN

> The plan of record for building the brain: the agent (gemini-3.1-pro-preview, multi-turn,
> tool-calling) that owns the deck, runs generation, fixes what's wrong, and talks to the
> user. Branches off `build1-content-critic` (B1 is unmerged; B2 builds on it; the whole
> stack merges once at the end). Part of B2's work is rerouting B1's auto-regen →
> report-to-brain.
>
> **This is staged with hard gates.** Each stage ends with a gate that must pass on a live
> droplet run before the next begins — "tests pass" is necessary, not sufficient; the gate
> is an eyeballed live run against real sources. The order is not arbitrary: Stage 0 is a
> prerequisite that blocks everything, and the stages build on each other. Do not start a
> stage before the prior stage's gate passes.
>
> The brain's character and bar are already specified in seven prompt documents (THE_STANDARD,
> BRAIN_conversational_identity, BRAIN_orchestrator, CRITIC_character, BRAIN_retrieval,
> BRAIN_memory, BRAIN_tool_descriptions). This plan builds the machinery those prompts run on,
> and wires them in at the end. Where a stage needs a prompt, it references the document.

---

## The constitutional invariants (must hold at every stage)

These do not bend during the build. If a stage would violate one, the stage is wrong.

- **No fabrication ever ships or is delivered.** The brain fixes fabrications internally,
  before the user sees the deck. The user never receives a deck with a known fabrication and
  is never asked to approve a fix for one.
- **Code decides, model proposes.** Grounding, severity, approval — the code makes these calls.
  The model proposes; it never self-grants approval, never supplies its own grounding data.
- **slide_id routing, never positional.** Every fix targets a stable slide id, surviving
  reindexing.
- **One cohesive Sonnet call for deck generation.** Cohesion requires one model seeing the whole
  deck. This is not decomposed.
- **Hard gates run; they are not reasoned around.** A gate that trips is fixed, not waived. A
  threshold is never lowered because it tripped.
- **Absence of a verdict is not a verdict of clean.** A missing confirmation never clears a known
  problem.

---

## STAGE 0 — DECK PERSISTENCE (the gating prerequisite)

**Why first:** the recon found the structured `DeckSpec` is never persisted — it's written only
to an ephemeral temp file (deleted after render) and an overwritten debug file. Post-delivery,
the deck the brain would edit *does not exist*. Nothing else in B2 can function until the deck
survives delivery and can be reloaded. This blocks everything.

**What exists:** a `decks` table with a `deck_json jsonb` column already in the schema
(`001_initial_schema.sql`), with a round-trip test (`test_presentation_models.py`). Nothing in
`packages/` ever writes to it. The schema is ready; the wiring is net-new.

**Build:**
- `save_deck` / `get_deck` in the database layer: persist the full `DeckSpec` (with its `plan`)
  to the `decks` table at the point of delivery; reload it by project/deck id.
- Wire `save_deck` into the delivery path (after render/upload, when the deck is delivered to the
  user, persist the structured spec).
- Confirm the round-trip is lossless: a `DeckSpec` saved and reloaded is identical, including the
  `plan` and all slide fields.

**GATE 0:** On the droplet, generate a real deck, confirm it's persisted to the `decks` table,
reload it in a separate call, and confirm the reloaded `DeckSpec` is byte-identical to the
original (round-trips losslessly through jsonb). Verify independently that nothing was already
writing to `decks` (so this is genuinely the first writer). Until a delivered deck can be
reloaded intact, Stage 1 does not start.

---

## STAGE 1 — THE TOOL-CALLING TRANSPORT (the core net-new capability)

**Why here:** the brain is a multi-turn tool-calling agent, and the current `GeminiClient` is
single-shot — no tools, no contents history, no thought-signature handling. This transport is
the spine of the brain. It comes after persistence because the brain operates on a persisted
deck, but before the rewire and the bot surface because those depend on the brain being able to
run a tool loop.

**What exists:** the pinned SDK (`google-genai==2.0.1`) already supports everything —
`Tool`/`FunctionDeclaration`, multi-turn `contents`, `Part.thought_signature` (`Optional[bytes]`),
`function_call`/`function_response`. No SDK upgrade. The transport is net-new *in our wrapper*.

**Build:**
- A new tool-calling method on the Gemini client (alongside `complete`): builds a `contents`
  history, declares tools, calls, reads either text or a `function_call` from the response,
  returns it for the loop to act on. Mirror `complete`'s retry/timeout/cost-logging skeleton.
- **Manual function calling, not automatic.** Disable the SDK's `automatic_function_calling` —
  it auto-executes tools in-process with no human pause, which breaks the approval gate. The loop
  reads `function_calls`, surfaces/gates as needed, executes, appends the `function_response`,
  calls again.
- **Thought-signature preservation within a process:** when a turn returns a `function_call`,
  append the model's `Content` object *verbatim* (parts intact, signature included) to the
  history; never hand-reconstruct the model turn. Preserving the SDK `Content` object end-to-end
  makes signature handling automatic in-process.
- **The sharp edge — serialization across turns:** the conversation must persist across Telegram
  message turns (and bot restarts), which means the `Content`/`Part` history — including the
  `thought_signature` bytes — must survive serialize → store → deserialize. Bytes do not survive a
  naive JSON round-trip. Build the session serialization (pydantic `model_dump_json`, base64 for
  bytes) and **treat "thought_signature survives serialize→DB→deserialize losslessly" as a
  first-class acceptance test**, written like the existing jsonb round-trip test.
- Cross-turn token/cost aggregation (the loop accumulates calls; sum them per session).

**GATE 1:** On the droplet, run a real multi-turn tool-calling exchange against gemini-3.1-pro
with a trivial test tool: the model calls the tool, the loop executes it, appends the result,
the model continues — across at least two tool round-trips, and the exchange completes without a
400 (the thought-signature-dropped error). Then the decisive one: serialize the full conversation
history (with a thought signature) to the store, reload it, continue the conversation from the
reloaded history, and confirm it doesn't 400 — proving the signature survived the round-trip. If
the signature corrupts through serialization, this fails silently in production; the gate must
prove it explicitly.

---

## STAGE 2 — CRITIC FINDINGS → BRAIN (the rewire)

**Why here:** B1's critic currently auto-regenerates flagged slides (blind Sonnet, which
refabricates — the gate proved it) and hard-stops/refunds on residual fabrication. B2 reroutes
this: the critic *detects and reports structured findings to the brain*; the brain decides and
fixes (per BRAIN_orchestrator). This comes after the transport because the brain (which now has a
tool loop) is what receives the findings.

**Build:**
- Change `_enforce_content_critic` so the critic's findings *survive* as structured output rather
  than being consumed by auto-regen or raised as an exception. Carry them on the `DeckSpec` (an
  optional findings field — wire-safe, the Node renderer ignores unknown fields, same as the
  existing `plan` field) or alongside it in the orchestrator return.
- **Remove the blind auto-regen loop.** The critic no longer calls `regenerate_slide_content`
  itself. It reports; the brain acts. (This is the rated-bad loop from the B1 gate, cut here.)
- **Preserve the invariant:** a known fabrication still does not ship. The findings reach the
  brain *before delivery*; the brain fixes hard-stop-class findings (fabrication/unsupported)
  internally and the deck is only delivered once they're resolved. This is the brain owning the
  deck, not "ship-then-discuss" — the user never sees the fabrication.
- **Carry the structured evidence.** The critic's `CriticEvidence` (slide quote, unsupported
  token, the matched claim) is currently flattened to a 500-char prose message before it reaches
  the finding. Define a typed finding subtype that carries the quote, the token, and the matched
  claim id, so the brain can reason about the specific claim (the "slide says 65, source supports
  69" content) rather than parsing prose. Populate it where the evidence is still in scope.
- Apply CRITIC_character as the critic's system prompt (the sharpened adversarial disposition,
  the derivable-vs-fabricated discipline, prove-don't-assert).

**GATE 2:** On the droplet, generate the two real decks (Enlightenment, sCO2). Confirm: the
critic's findings now surface as structured data carrying the evidence detail (not flattened
prose); the blind auto-regen no longer runs; and a deck with a fabrication is *not* delivered with
the fabrication in it. Confirm the derivable-number discipline (a number the source supports by
arithmetic is not flagged as fabrication). This is also the first gate where the planner-roster
and token-cost harness fixes from B1 should be in place (dump the deck on any stop; structured
token logging) so you can finally eyeball the roster and see per-deck cost.

---

## STAGE 3 — THE FIX-AND-DELIVER CHAIN

**Why here:** the brain fixes slides, and a fix has to *reach the user*. The recon found the chain
from "slide regenerated" to "updated deck delivered" is net-new. This comes after the rewire
because the brain now has findings to act on; it needs the machinery to act.

**What exists:** `orchestrator.regenerate_slide` already wraps content regen + splice + *scoped*
image re-resolution (only the regenerated slide's image, others untouched). It does **not** render,
upload, or re-deliver.

**Build:**
- A new orchestrator method — the full "apply edit and redeliver" chain:
  `orchestrator.regenerate_slide` (the existing scoped fix) → render the updated deck → upload
  (overwriting the prior files) → refresh the file references → re-deliver to the user → persist
  the updated `DeckSpec` (Stage 0's `save_deck`, so the edited deck is the new persisted state).
- **Batch, don't thrash:** when the brain makes several slide changes together, apply them all,
  then render/deliver once — not once per slide.
- **The composed-instruction rule (from BRAIN_orchestrator):** the brain calls the fix tool with
  an instruction carrying the *specific correction* (what was wrong, the grounded value, what to do
  if it can't be grounded). Blind "regenerate this slide" reproduces the mistake. The tool
  description (BRAIN_tool_descriptions) states this and the does-NOT-deliver boundary.
- Confirm the share-link cache/overwrite semantics: the public link serves the updated deck after
  re-delivery, not the stale render (the recon flagged this as a thing to verify).

**GATE 3:** On the droplet, take a delivered deck, have the chain regenerate one slide with a
composed instruction, and confirm: the slide is fixed, the deck re-renders, the updated files are
delivered, the persisted `DeckSpec` reflects the edit, and the public link serves the updated
version (not stale). Confirm the regenerated slide's image re-resolved (not null) and other slides'
images are untouched. Confirm a multi-slide batch renders/delivers once, not per-slide.

---

## STAGE 4 — THE BOT SESSION SURFACE (the conversation)

**Why here:** the brain talks to the user across turns, and the bot can't hold that conversation
as-is — FSM is `MemoryStorage` (not even Redis), built for short linear flows, and it can't even
hold the deck's file paths (there's a module-local dict hack for that). This is the largest stage.
It comes after the fix chain because the conversation's purpose is to drive fixes/edits, which now
exist.

**Build:**
- **A DB-backed session** (`presentation_thinker_sessions` or similar): holds the serialized
  conversation history (with the base64 thought signatures from Stage 1), a reference to the
  persisted deck, the critic findings, and the approval state. **FSM holds only the session id.**
  This survives bot restart (the "what if the bot restarts mid-conversation" gap).
- **The chat loop, above the orchestrator (not a pipeline refactor):** a new FSM state
  (`talking_to_brain` / `awaiting_approval`). Each inbound Telegram message is a fresh handler that
  *loads the session → runs one brain turn → persists the session → replies*, calling the
  orchestrator methods (the fix-and-deliver chain) as tools between turns. Do not refactor
  `run_full_pipeline` into a resumable generator — the brain sits *above* the orchestrator in the
  bot layer.
- **The brain inserts at end-of-generation:** after the first deck is generated and delivered (the
  pipeline's existing `reviewing_output` seam), the brain session starts. (Per the architecture:
  the pipeline produces the first draft; the brain owns everything from there — fixing, conversing.
  The brain does *not* replace the planner; intent threading into the planner is a separate, smaller
  piece — see "Adjacent work" below.)
- **The approval gate (code-side, never model-self-granted):** where the brain proposes a
  significant change that re-delivers, the gate is inline callback buttons (a pressed button, or an
  explicit affirmative the *code* recognizes) — an `awaiting_approval` state and a callback route
  that loads the session and fires the tool. The model proposes; code confirms the user authorized;
  then it fires. (Per BRAIN_conversational_identity's "fix-first-report-after" for internal
  fabrication fixes — those are *not* gated, the brain just fixes them — versus user-directed edits,
  which the user is driving and therefore already authorizing.)
- **Per-session budget (code-enforced):** the conversation accumulates LLM tokens, and each fix
  spends image quota. Nothing currently caps cumulative session spend. Add a per-session budget
  (tokens + regen image spend) that refuses further tool calls past the cap (the SDK won't do this).
  Mirrors the existing cost controls; keeps a chatty conversation from becoming unbounded.

**GATE 4:** On the droplet, end-to-end through the bot: generate a deck, enter the brain
conversation, send a message, get a brain reply, direct an edit, confirm the approval button gates
it, confirm the edit applies and re-delivers, send another message and confirm the session
*persisted* (the brain remembers the prior turns — including across a simulated bot restart, proving
the session and the thought signatures survived). Confirm the per-session budget halts runaway tool
calls.

---

## STAGE 5 — WIRE IN THE BRAIN (the prompts) AND THE MEMORY/RETRIEVAL

**Why last:** the machinery now exists (persisted deck, tool loop, findings-to-brain, fix chain,
session). This stage installs the brain's actual *character* on top of it and adds the
cross-session memory.

**Build:**
- **Assemble the brain's system prompt as a cached block** from the prompt documents:
  THE_STANDARD + BRAIN_conversational_identity + BRAIN_orchestrator (the brain's bar + how it talks
  to the user + how it runs generation), with BRAIN_tool_descriptions for its tools. This is the
  static, cacheable prefix; the session-specific content (this deck, this user, the findings, the
  conversation) is the uncached suffix. (Mirror the cache-split discipline; the editorial-caching
  refactor that moves per-deck scalars to the user message is the same pattern and is a relevant
  prerequisite if editorial is in the cached path.)
- **Retrieval (BRAIN_retrieval):** wire the brain's search over the two corpora — the source
  material (for grounding edits and answering "is this in the source") and the conversation history
  (for knowing the user). The source search grounds the fix decisions; the history search is the
  read side of memory.
- **Memory (BRAIN_memory) — the infrastructure half:** the auto-captured searchable history (every
  message, stored automatically — this is the history-retrieval corpus), the curated per-user notes
  (event-driven capture of durable signals, corrections-overwrite-not-accumulate), the reflection
  pass (the periodic sweep catching missed captures), and the selection discipline (pull relevant
  notes, not the whole history). **Compartmentalization is code-enforced** — one user's
  memory/notes never surface to another, an absolute boundary.

**GATE 5 (the real one — the brain is now itself):** On the droplet, the full experience. Generate
a deck; the brain owns it. Confirm against the prompts: it holds the bar (THE_STANDARD — does it
catch and fix below-bar content), it pushes back appropriately (the three bands — does it defer on
preference and hold the line on a buried point), it refuses fabrication (the floor — ask it to
invent a statistic, confirm it declines), it fixes internally and reports rather than exposing the
mess, it remembers the user across sessions (memory), and it stays compartmentalized. **This is the
gate that's your eyes, not the test suite:** the prompts are soft instructions until this run shows
whether the model actually holds the standard under real generation pressure. Expect to find where
it ships slop despite the bar, and sharpen the prompts against what you see. This gate is run, read,
and re-run until the brain is good — the same way the bar itself is your eyes on the output.

---

## ADJACENT WORK (not in the B2 critical path, flagged)

- **Intent threading into the planner.** The recon's real finding on "the planner misses user
  details": intent never *enters* (intake — `interview.py` — is deterministic, no LLM, no free-form
  intent field). The fix is *not* a brain stacked on the planner (that's redundant Pro-on-Pro with a
  silent fabrication hole). It's: capture free-form intent at intake (a free-text field, optionally a
  small LLM intake pass parsing messy input into the structured answers + a `user_intent` field), and
  thread it as a first-class `USER INTENT / FOCUS` block into `PLANNER_USER` (the slot pattern already
  exists beside AUDIENCE/EMPHASIS/CLOSING_ASK). This is small and separable — it can land before,
  during, or after B2, but it is the actual fix for "the deck doesn't reflect what the user said,"
  and the brain's conversation is most useful when the *first* draft already honored intent.
- **The code-level roster-vs-source gate.** The recon found roster grounding is LLM-soft with no code
  backstop — the validators check roster-internal-consistency, not roster-vs-source. This is fine for
  the current planner (it grounds from the source by construction), but if anything ever lets a name
  enter the roster from outside the source (a future feature, or the brain acting on a user request),
  this gate would need to exist first. Flagged so it's not forgotten if the roster ever gets a new
  writer.

---

## MERGE

The whole stack — B1 (with its auto-regen now rerouted) plus B2 (all stages) — merges to main
**once**, at the end, after Gate 5. B2 was built on the `build1-content-critic` branch precisely so
this is one lineage and one merge, not two diverging branches fighting. Until Gate 5 passes, nothing
merges.
