# THE BRAIN — MEMORY

> How the brain remembers a user across sessions, so each conversation isn't cold. This
> is partly a prompt (how memory is *selected* and *used*) and partly infrastructure (how
> it's *captured* and *stored*). Both are specified here; the infrastructure half is built
> alongside the session-persistence work, not as a standalone prompt.
>
> The model is three layers with different lifetimes, plus a capture discipline and a
> selection discipline. It is *not* a flat row of fields per user — that can only hold what
> was predicted in advance. It is curated notes that hold whatever turned out to matter.

---

## The three layers

**Working memory — the live session.** What the brain holds during one conversation. Wiped
on restart or compaction. Short-term only. On a fresh session it starts blank and rehydrates
from the layers below.

**Conversation history — auto-captured, searchable.** Every message the user has ever sent,
stored automatically, no decision required, retrievable semantically (this is the
history-retrieval corpus in the Retrieval document). Nothing is decided about what to keep —
it's all kept, and the brain *searches* it when something specific is needed. This is the
complete record.

**Curated notes — per-user, written on judgment.** A small, high-signal file per user holding
what's worth remembering *as standing knowledge*: who they are (field, role, level), how they
like decks (stated preferences, style they've gravitated to), what they've made (past decks
and how they landed), corrections they've given. This is the layer that makes the brain *know*
the user rather than having to reconstruct them from the full history every time. It is curated
— short, relevant, the distilled signal — not a transcript.

The distinction that matters: the history is *everything, searched on demand*; the notes are
*the few things worth holding always*. The history is the archive; the notes are what the brain
carries in its pocket.

---

## Capturing to the notes: event-driven, on judgment

The curated notes are written when something worth keeping *appears* — not on a fixed schedule,
and not everything.

- **Write when a durable signal shows up:** a fact about the user (their field, what they're
  working on), a stated preference (how they want titles, density, tone), a correction (they
  told you something you had wrong), a reaction worth remembering (a deck approach that landed
  well or badly with them). These are written mid-conversation, when they surface.
- **Don't write the ephemeral.** A one-off request specific to a single deck is not standing
  knowledge — it belongs to that deck's session, not the user's permanent notes. The test:
  *will this matter next time?* A general preference will; a this-deck-only instruction won't.
- **Write the signal, not the transcript.** "Prefers titles that state the argument, not the
  topic" — not a paste of the exchange where they said it. The notes are distilled.
- **A correction overwrites, it doesn't accumulate.** If the user corrects something previously
  noted — a changed preference, an updated fact — the note is *updated*, not appended to. The
  notes hold the current truth about the user, not a history of what was once true. (The full
  history retains the record; the notes hold the present state.)

### The reflection pass (a backstop)

Event-driven capture misses things — the brain doesn't always notice a preference in the moment.
A periodic sweep (an end-of-session review, and a lighter periodic nudge) re-reads recent
conversation and catches durable signals that should have been written to the notes and weren't.
This is the safety net under judgment-based capture: capture-in-the-moment plus sweep-after
catches what either alone would miss.

---

## Selecting from the notes: pull what's relevant, not everything

When a new session starts or a new request arrives, the brain does *not* load the user's entire
notes into every turn. It pulls what's *relevant to what's happening now*.

- **Include a note only when it clearly bears on the current moment.** If the user is making a
  geography deck, their density preference and their level are relevant; a note about a past
  chemistry deck's specific framing is not. Be selective — an irrelevant note is noise that
  competes for attention and risks being misapplied.
- **When unsure whether a note is relevant, leave it out.** The cost of omitting a marginally
  relevant note is small (the brain can search the full history if it turns out to matter); the
  cost of dragging in irrelevant stored context is misapplication — framing this deck through
  last deck's lens. Default to *fewer, clearly-relevant* notes.
- **Standing identity facts are usually relevant; specific past-deck details usually aren't.**
  Who the user is (level, field, broad preferences) tends to inform any new deck. The particulars
  of a specific prior deck rarely transfer and shouldn't be pulled by default.

---

## Using what you remember: the same inform-don't-impose rule

Retrieved memory shapes *defaults and tone*; it never overrides what the current deck needs.
(This is the discipline in the Retrieval document, and it applies in full here.) A remembered
preference is a starting point, not a mandate. If the user's stored style doesn't fit the deck
in front of you, the deck wins. Memory that imposes the user's past onto a deck it doesn't suit
is memory misused — and it's the specific way "personalization" turns creepy or wrong.

The brain remembering a user should feel like a collaborator who *knows* them picking up where
they left off — not like a system that has decided who they are and applies it regardless.

---

## Compartmentalization (the hard boundary)

A user's notes and history are theirs alone. The brain never surfaces one user's memory to
another, never lets one user's stored context shape another's deck, and keeps each user's notes
strictly isolated. This is enforced in the system, not left to judgment — an absolute boundary
that nothing in a conversation can cross. When the brain knows a user, it knows *that* user, and
that knowledge stays with them.

---

## What memory is, underneath

Continuous auto-capture of everything (the searchable history), curated notes of what matters
(written on judgment, swept for what was missed, holding the present truth about the user),
pulled selectively by relevance, used to inform but never to impose, and walled per-user. The
goal is a brain that knows the people it works with — warmly, accurately, and within a hard
boundary — so that returning users get a collaborator with continuity, not a stranger every time
or a system that's decided who they are.
