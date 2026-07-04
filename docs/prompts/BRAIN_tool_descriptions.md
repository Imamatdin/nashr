# THE BRAIN — TOOL DESCRIPTIONS

> The brain acts on the deck through tools. This document is the *template and principles*
> for how those tools are described to the brain, plus concrete drafts for the tools the
> system already has. Some tools described here aren't fully wired yet (the recon flagged
> the deck-edit-and-redeliver chain as net-new) — those drafts are finalized against the
> real implementation when it's built. The principles are stable regardless.

---

## Principles for the brain's tool surface

**Keep the model's tool surface minimal; inject the rest server-side.** The brain calls a
tool with the *decision* it's making — which slide, what correction — and the system supplies
everything else (the deck, the source claims, the package/budget context) from the session.
The brain does not pass grounding data through the tool call. This is the same discipline as
the critic: the model proposes the action, the code supplies the grounded inputs. It keeps the
model from being the place fabrication or wrong context could enter, and it keeps the tool
calls small.

**Every tool description states: what it does, when to use it, and what it does NOT do.** The
"does not do" is as important as the "does" — it's where the brain learns the tool's boundary
and avoids misusing it. A tool that re-resolves images but doesn't re-deliver must *say* it
doesn't re-deliver, or the brain will assume the deck reached the user when it didn't.

**Tools are how the brain acts, not how it decides.** The brain decides (using its judgment, the
Standard, the critic's findings); the tool executes. A tool description never asks the model to
make a judgment the model should have already made — it describes a mechanical capability the
brain invokes once it has decided to.

**Approval-gated tools are gated in code, not by the tool description.** Where a tool requires
the user's "go ahead" before firing (an edit that re-delivers a changed deck), the gate is a
code-side check — the user pressed the button, or gave an affirmative the code recognizes. The
tool description notes that the tool is approval-gated, but the description does not let the model
*self-grant* approval. The model proposes the call; code confirms the user authorized it; then it
fires.

---

## The fix tool: regenerate a slide

> Confirmed to exist: the orchestrator-level slide regeneration (content regen + splice +
> scoped image re-resolution). This is the brain's primary instrument for fixing and editing.

**What it does:** Rewrites a single slide, identified by its stable slide id, according to an
instruction the brain composes. Preserves the slide's identity (its type, its place in the deck,
its section). Re-resolves the image for *that slide only*, so the rest of the deck's images are
untouched. Returns the regenerated slide and whether it passed its own grounding/quality checks.

**When to use it:** To fix a slide the critic flagged (with an instruction carrying the specific
correction), or to apply a change the user asked for on a specific slide. This is the tool for
*targeted, single-slide* changes — the common case for both fixing and editing.

**What it does NOT do:** It does not render the deck, upload the result, or re-deliver it to the
user. A regenerated slide is spliced into the deck in memory; getting the updated deck *to the
user* is a separate step (render → upload → deliver). Do not assume the user has the updated deck
because the slide was regenerated — they don't until it's delivered.

**The instruction is where the brain's judgment goes.** A bare "regenerate this slide" reproduces
the original mistake (the model that fabricated will fabricate again with no reason not to). The
instruction must carry the *specific* correction: what was wrong, what the grounded value or
content is, and what to do if it can't be grounded (drop the claim, state it qualitatively). The
quality of the fix is the quality of the instruction.

**Cost note:** Each call spends regeneration budget, and the image re-resolution spends the deck's
image quota for that slide. This bounds how many times a fix is retried (see the orchestrator's
default: one focused regeneration, then a sharper instruction or removal — not blind repetition).
It does not bound whether a fabrication is fixed.

---

## The deliver-the-updated-deck chain

> Net-new per the recon — the chain that takes an edited deck back to the user. Drafted here;
> finalized against the real implementation.

**What it does (intended):** After one or more slides are regenerated and spliced, this renders
the updated deck (all output formats), uploads the result (overwriting the prior files), refreshes
the file references, and re-delivers the updated deck to the user. This is what makes an edit
*reach* the user.

**When to use it:** After the brain has made the slide changes it intends to make and is ready to
give the user the updated deck. Not after every single slide regen if several are happening
together — batch the changes, then deliver once, to avoid re-rendering repeatedly.

**What it does NOT do:** It does not decide *what* to change (that's the brain's judgment and the
regen tool's job) — it delivers what's already been changed. And it is the step that's
**approval-gated** where the change is significant: the user authorizes the re-delivery via a
code-side gate before it fires.

**Open against wiring:** the exact render/upload/deliver sequence, how the public share link's
cached version is overwritten, and how the updated deck is presented to the user (new files,
updated buttons) are finalized when this chain is built. The recon flagged the share-link cache
overwrite as a specific thing to confirm.

---

## The persistence boundary (why these tools can work at all)

> Context, not a tool: the recon found the deck is not currently persisted past delivery — it
> lives only in an ephemeral temp file that's deleted after render. None of the editing tools
> above can function unless the deck the brain edits actually *exists* to be loaded. So the
> gating prerequisite under all of these is: the deck is persisted at delivery and reloaded
> when the brain's session starts. This isn't a tool the brain calls — it's the foundation that
> makes the brain's tools possible, and it's built first.

---

## Adding tools later

When new tools are wired (whole-deck operations, structural edits beyond single slides, source
re-search as an explicit tool), each gets a description following the principles at the top: state
what it does, when to use it, what it does *not* do; keep the model's surface minimal with grounded
inputs injected server-side; gate approval in code where the action warrants it. The brain's tool
surface grows by adding clearly-bounded capabilities, not by handing the model broad,
underspecified power.
