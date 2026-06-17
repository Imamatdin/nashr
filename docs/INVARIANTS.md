# Nashr — Invariants (load-bearing, outrank test status)

These are non-negotiable contracts of the production system. A violation is a bug
regardless of whether tests pass: tests are the floor of correctness, the invariants
are the ceiling. This file is referenced from the top of [BUILD_STATE.md](BUILD_STATE.md)
and is the second file read every session.

---

## I1 — No hardcoded constant stands in for tier logic on a paid or visible path

Every behavior the SPEC distinguishes between paid tiers MUST derive from the user's
`GenerationPackage`, not a module-level default. Two corollaries:

- **Every tier difference must be observable in output.** If a premium user pays for
  more and gets the same output as standard, the tier they paid for is fictional and
  the difference is a bug, not an interim. The wire is what proves it.
- **The budget arrives at code as a function of the package, not as a literal.**
  `PRESENTATION_TIER_IMAGE_LIMITS` is keyed by `GenerationPackage` so pyright traps
  drift when a new tier is added; access goes through
  `image_budget_for_package(package)` (`packages/core/constants.py`). Per-call
  budgets land on `ImagePass.resolve_deck(max_generated_images=…)` from the
  orchestrator's `run_full_pipeline(package=…)`.

The test that proves the wire:
`tests/unit/test_presentation_orchestrator.py::test_full_pipeline_threads_package_to_image_budget`.
It captures the budget the orchestrator hands to `ImagePass` for each tier and asserts
`PREMIUM > STANDARD > BASIC`. It MUST fail on any code that lets the tier default —
the failure IS the invariant.

## I2 — Every slide carries content weight

A slide that only names a section, or only echoes an adjacent stat, is NOT emitted.

- A non-content slide (SECTION_BREAK, the auto SUMMARY_TAKEAWAY breather) is emitted
  only if it carries a real one-line thesis. For a SECTION_BREAK the thesis lives in
  `subtitle` (or `body_text`); a bare-label divider is dropped by
  `_drop_hollow_dividers` in `editorial.py`. The prompt
  (`SLIDE_TYPE_DESCRIPTIONS[SECTION_BREAK]` + `EDITORIAL_SYSTEM` rule 8) instructs
  the model to put the section name in `section_name` and the thesis in `subtitle`,
  or to omit the divider entirely.
- The breather device (`_insert_breathing_after_data`) is retained but defaults OFF.
  It must earn its place by carrying real model-authored content (BUILD_STATE plan
  item 2) before it is re-enabled. The stat-echo seed it ships with today would not
  pass this invariant if emitted.
- **R01** (no consecutive same-types) and **R03** (section every 4-5) are now model-
  prompt concerns only — the post-process no longer enforces them by injecting
  hollow dividers, because that injection violates this invariant. Layout variety
  is the layout pass's responsibility. Section cadence relies on the model emitting
  thesis-bearing breaks (or no break, which is fine).
- A consequence to be aware of: `_merge_slides` uses SECTION_BREAK slides as
  insertion anchors for interactive content. With fewer thesis-bearing breaks,
  interactive slides fall back to end-append — a normal "quiz finale" pattern, not
  a regression — but `EDITORIAL_SYSTEM` rule 7 still asks the model to vary slide
  types so the cadence stays readable.

## I3 — Text always wins over background

No image behind body text without a scrim that passes the contrast check. The most
important image in a deck — the title-hero background — is guaranteed AHEAD of
lower-priority images **within the deck's image budget**; a tier whose budget is zero
(basic) generates nothing, hero included.

- The "guaranteed first claim" half is `_BACKGROUND_PRIORITY < _FIGURE_PRIORITY` in
  `image_pass.py`. Lower priority sorts first, then the per-deck budget caps the
  list; with a non-zero budget, the title-hero scene is always in.
- The "within the budget" half is what keeps I1 honest. Basic-tier (budget 0) decks
  still render — they fall back to a CSS gradient / palette background as the SPEC
  free tier intends — but no AI image is generated, including the hero.
- The "scrim over body text" half is implemented in
  `packages/presentation-worker/src/layouts/shared.ts::heroBackground` (and in every
  layout that places body text over an image: concept_definition, content_split,
  typographic_keywords, the interactive layouts). The contrast check that proves it
  passes is `packages/presentation-worker/src/audit/quality-audit.ts`, which blends
  the scrim color into the background before measuring text contrast.

## I4 — No load-bearing TODO/stub/interim on a paid or visible path

A `TODO` / `FIXME` / "follow-up" / "interim" / "stub" / "for now" / "hardcode" /
"placeholder" marker on a path that touches tier, budget, image count, slide
emission, or contrast is a BUG, not a deferral — unless Iko has signed off on the
deferral, by name, IN THIS FILE.

### Authorized deferrals (Iko sign-off required to add or remove)

- **`bundle_article_presentation` image budget.** The bundle package is defined in
  `PRICING_UZS` (135,000 UZS) but is NOT reachable from any keyboard today —
  presentation and article flows only emit `presentation_*` / `article_*` tiers. When
  the bundle is wired through a keyboard, its image budget must be added explicitly
  to `PRESENTATION_TIER_IMAGE_LIMITS` (likely matching premium = 5). Until then,
  `image_budget_for_package` maps the bundle (and any other non-presentation tier) to
  the SPEC standard tier (2) with a logged warning, so the bundle's first wire-up
  doesn't ship a zero-image deck. **Sign-off requested.**
- **`GenerationJob.image_count` telemetry.** The field exists on the model and is
  initialized to 0, but the orchestrator does not record the actual count of images
  resolved after a deck completes. SPEC §8 cost controls treat `image_count` as a
  tracked telemetry; today it stays at 0. The fix is a small surface change to
  `resolve_images` — return the count so the caller can persist it. Out of scope
  here; flagged so it is not silently forgotten. **Sign-off requested.**

## I5 — A quality gate may vary, degrade, or warn, but MUST NOT block export over a cosmetic issue

A user who paid for a deck gets the deck. The audit's job is to keep correctness
failures off the user's screen (text that doesn't render, contrast that can't be
read, an interactive without a correct answer) — not to gatekeep on style, and
not to refuse the whole deck over a single slide that can be DEGRADED into a
legible, exportable state. A stylistic concern means: a real human designer might
argue with the choice but the deck is still legible, accurate, and complete.

- **Correctness failures (severity: `fail`, blocks export):** Q2 WCAG contrast,
  Q5 empty slide, Q7 unrenderable font, Q9 interactive without a correct answer,
  Q10 quiz without feedback, Q13 deck in the wrong language.
- **Degrade-and-ship (severity: `warn`, never blocks — the content still
  RENDERS):** Q1 text overflow-at-floor, truncated to fit (see below).
- **Stylistic / cosmetic concerns (severity: `warn`, never blocks):** Q4 adjacent
  same-layout, Q3 word count over, Q6 unresolved background image, Q8 mixed
  script, Q11 visible cards, Q12 generic title, Q14 consecutive data slides,
  Q15 unvaried stats.

Adding a new check defaults to `warn` unless it traps a correctness failure
defined above. If a check upgrades from `warn` to `fail`, the upgrade must name
the specific user-visible breakage it prevents and be defended here. The
`is_exportable` flag is computed from `failed === 0`, so the line lives in the
severity field — keep it honest.

Q1 specifically (text overflow → degrade-and-ship). Text that does not fit IS a
real correctness problem — this is **not** a statement that fit no longer matters.
It is a statement about the RESPONSE. The right response to "does not fit even at
the floor font" is to TRUNCATE-and-ellipsize the text so the slide still renders
and the deck still EXPORTS, then WARN — not to block the whole deck and dead-end
the user with "an error occurred" (the live failure on the Enlightenment deck
before this). Truncation (`buildTextBlock`, the `truncated` flag) is L1's
RELIABILITY FLOOR, **not the cure**. The cure — reconciling editorial's word
budget with the renderer's pixel budget so the full text genuinely fits — is L2's
shared fit contract. The Q1 warning is therefore kept LOUD and logged, carrying
the slide index and the truncated text, precisely so L2 can locate every
truncated slide and fix the fit for real. A fit/overflow condition can NEVER again
set `is_exportable=false` — including the pathological case where even an ellipsis
will not fit a degenerate box, which also resolves to a warning. Q1 is now a
`warn` (see `quality-audit.ts` and the tests `degrades a residual overflow to a
WARNING` / `does NOT block export on a Q1 overflow`).

Q4 specifically: adjacent same-layout was a `fail` historically and blocked the
sCO2 deck from exporting. It is now `warn` (see `quality-audit.ts` and the test
`warns on consecutive same type but does NOT block export`). The variety problem
is addressed upstream by `EDITORIAL_SYSTEM` rule 7; the audit reports the
violation so it remains observable.
