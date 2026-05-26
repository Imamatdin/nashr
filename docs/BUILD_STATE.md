# SlideForge / Nashr — BUILD STATE   (read first, every session)

STATUS: PRODUCTION. Past MVP. No MVP scope, no "works for now." Fix at the correct layer,
verified. Iko runs Claude Code locally against the real repo; master prompts carry acceptance
tests; a step is DONE only when a commit changes this file.

INVARIANTS: See [INVARIANTS.md](INVARIANTS.md) — load-bearing contracts that outrank test
status. A violation is a bug regardless of whether tests pass. Read after this file.

## VERIFIED DONE (evidence, not memory)
- Decimal truncation "73.8 bar" — fixed 8f5b587, renders intact slide 2.
- Collision/clip/overflow stacking — committed, margins documented.
- 6 interactive formats render (Enlightenment deck = proof).
- git: laptop == origin == server, clean.

## CONFIRMED BROKEN — by layer (sCO2 deck: layout.json + last_deck.json)
| # | Symptom | Layer | Cost | Evidence |
|---|---------|-------|------|----------|
| A | data-emphasis: unit drawn twice ("1.58PUE"+"PUE"), labels stranded | RENDERER | free | data-emphasis.ts concat + fixed-fraction y |
| B | "Key takeaway / preceding data underscores..." hollow slide | CODE→EDITORIAL | free interim / paid real | editorial.py _insert_breathing_after_data hardcoded stub |
| C | numbered list 1,2,4,5 — model dropped its own #3 | MODEL | PAID | last_deck.json bullets has 4 items |
| C2| literal "1. " prefixes baked into bullets | MODEL + code guard | paid+free | same bullets |
| D | chart slide: chart_series=null, data stuck in prose | SCHEMA (not MODEL) | free | _LLMSlide had NO chart_series field; extra="ignore" dropped any emitted — FIX3 adds the field |
| E | "[Chart placeholder]" — chart renderer unbuilt | UNBUILT (Step 2) | free | chart-data.ts placeholder by design |
| F | chart title collides with chart box (2-line title under-measured) | RENDERER (Step 11) | free | floor logic correct, fed wrong title height |
| G | comparison slide: left_column/right_column null, renders blank | PROMPT↔SCHEMA | free | prompt emitted {"comparison":{left,right}} but _LLMSlide only accepts top-level left_column/right_column → extra="ignore" swallowed it — FIX2 |
| H | table_compact: table_headers/table_rows null, renders empty grid | SCHEMA (not MODEL) | free | _LLMSlide had no table fields; SlideContent + table-compact.ts already rendered them — FIX1 wires the link |

## SHIPPED
- A (data-emphasis value/unit split + measured CENTERED stacking) — 48f713b. Verified:
  worker `layout` on crafted sCO2 deck = no jammed units, each unit in one block,
  gaps ~1.2%; chromium screenshot reads number→unit→label→comparison clean.
- C2 (stripListPrefix at all four bullet/point sites, not just summary) — 48f713b.
  "1. " stripped, "1.08" preserved; screenshot shows single "• " markers.
- B-interim (breather seeded from real stat; skip when no stat) — 48f713b. INTERIM:
  real model-authored breathing content is plan item 2. Carries the R27 trade noted above.
- Over-long single-token line undercount — c79036c. measureText kept any token wider
  than the effective maxWidth on ONE line (old "we don't simulate character breaking"
  path); browser/PPTX/LibreOffice character-break it, so blocks stacked beneath a
  wrapped value were under-measured. Now counts ceil(width/maxWidth) lines, width
  capped at maxWidth, off-by-one handled. Part of plan item 11 (fontkit accuracy).
  CORRECTION to the original report: the "1.56–1.58" data-emphasis collision was a
  MISDIAGNOSIS — that value is 307.7px vs a ~419px column, renders one line, and the
  real LayoutPass already stacks it with no overlap (item A). Verified: vitest run of
  a 3-stat fixture with a genuinely over-long value (`1.560–1.580–1.600`) — the number
  measures 2 lines and the unit clears its measured bottom. The remaining text-measure
  red (sCO2 title, 1 vs 2) is a SEPARATE facet of item 11 (multi-token wrap-width
  calibration / F), still open.

## SHIPPED (cont.)
- Editorial structured fields — H (tables, FIX1) · G (comparison, FIX2) · D-data (chart_series, FIX3)
  — THIS BRANCH (fix/editorial-structured-fields, off the data-emphasis branch HEAD, NOT main:
  main lacks BUILD_STATE + the renderer fixes the eyeball step needs). ROOT CAUSE was a missing
  pipeline link, not model laziness: editorial.py _LLMSlide uses extra="ignore", so any field it
  did not declare was SILENTLY DROPPED — table_compact + chart_data could never populate.
  - FIX1 tables (end-to-end): added table_headers/table_rows to _LLMSlide + _materialise_slides +
    EDITORIAL_SYSTEM. SlideContent + table-compact.ts already rendered them; this wires the link.
  - FIX2 comparison (prompt↔schema, deeper than "prose quality"): the prompt's schema example told
    the model to emit {"comparison":{left,right}}, but _LLMSlide only accepts top-level
    left_column/right_column — extra="ignore" swallowed the whole key, which is WHY columns were
    always null. Fixed the schema example to the real keys + added "use content_split/
    summary_takeaway when it is not a genuine two-sided contrast; never emit empty columns."
  - FIX3 chart DATA/renderer SPLIT: added ChartSeriesPoint{label,value:float,unit} + chart_series
    (cap 8) across SlideContent, types.ts, _LLMSlide, _materialise_slides, prompt. The DATA now
    flows; chart-data.ts STILL renders "[Chart placeholder]" by design — the chart VISUAL renderer
    (SVG bars from chart_series) is plan item 3 / Step 2 and will consume this field.
  Verified end-to-end WITHOUT a live LLM: real generate_deck_spec with only the LLM stubbed to a
  sCO2 response using the new shapes → deck json → worker layout + HTML render. Table draws 4
  headers + 12 cells; comparison draws both populated columns (L=3/R=3); chart draws the
  placeholder with chart_series [Air8,Liquid40,sCO2120] behind it in the json (acceptance: data in
  json, not render). pytest 1120 passed / 30 skipped; vitest +1 chart-data test (pre-existing
  text-measure F red unchanged); pyright packages/ + tsc clean; ruff clean.
  NOT done here (be honest): live Sonnet regeneration (no API key in env) and PDF render (no
  soffice locally — same gap as the skipped PDF tests). HTML + layout JSON stand in as proof the
  wire format reaches the render layer intact. debug/last_deck.json absent (gitignored), so the
  check used a fabricated sCO2 deck via the durable loop.

## SHIPPED (Step 2 — chart renderer)
- E (chart renderer) — THIS BRANCH (feat/chart-renderer, off fix/editorial-structured-fields
  HEAD, NOT main: main lacks the FIX3 chart_series data flow this renderer consumes + BUILD_STATE).
  Replaced "[Chart placeholder]" with native-shape charts drawn into the collision-safe chartRegion.
  - FOUR TYPES: bar · line · single_value · grouped_bar (+ stacked_bar variant). chart-data.ts
    delegates to src/charts/draw-chart.ts; empty/missing series still falls back to the placeholder.
  - NATIVE SHAPES ONLY: rect/line/circle ShapeBlocks + text, the same primitives every layout uses.
    No SVG, no chart lib, no browser. One drawing path serves HTML, PPTX, and PPTX→LibreOffice PDF.
  - SCHEMA (Step A): added ChartType enum (enums.py) + chart_type/chart_group_labels on SlideContent
    + values on ChartSeriesPoint (presentation.py), mirrored in types.ts, wired through editorial
    _LLMSlide + _materialise_slides + EDITORIAL_SYSTEM. Flat chart_series unchanged (bar/line/
    single_value); values[] aligned to chart_group_labels drives grouped/stacked. No SQL migration —
    ChartType lives in the deck JSONB, not a column.
  - COLOUR RAMP (Step B) — DEVIATION, deliberate: the palette is BESPOKE per deck (LLM-generated;
    the six-mood table is only the fallback), so a hardcoded per-mood ramp would clash. Instead the
    ramp is DERIVED from the deck's actual palette in the worker (resolveChartRamp): hero = accent,
    supporting = accent stepped toward text + the secondary neutral, each contrast-guarded vs the
    background. Cohesive on any palette, bespoke or fallback (verified by eyeball on BOTH dark and
    light palettes). Count-aware: generates as many distinct steps as a grouped/stacked chart has
    groups (cap 6), so a legend never reuses a colour. Avoids the design_direction.py extra="forbid"
    round-trip trap too.
  - DIAGONAL LINES (renderer fix) — the web prompt assumed line shapes render identically everywhere;
    the HTML renderer only drew AXIS-ALIGNED lines, so a line chart would break in the HTML export.
    Added optional x2/y2 endpoints to ShapeBlock: HTML rotates a hairline rect, PPTX uses pptxgenjs
    flipV. Axis-aligned lines unchanged. (Production PDF = PPTX→soffice, so it was already fine there;
    PdfRenderer/Playwright HTML→PDF is test-only.)
  - VERIFIED: tsc (src+tests) clean; vitest +16 chart tests (draw-chart.test.ts), per-type shape
    counts + within-region bounds + empty→placeholder fallback; pytest 1126 passed / 30 skipped
    (+6 round-trip/parse tests); ruff clean on changed files; pyright clean. EYEBALLED: built a
    chart-types deck (one slide per type, BOLD_TECHNICAL palette), rendered HTML, screenshotted all
    five via chromium — bar shows orange-red bars on near-black with Air/Liquid/sCO2 labelled and
    8/40/120 kW/rack values; line shows connected diagonal slope; single_value shows hero number +
    progress bar; grouped/stacked show ramp-coloured sub-bars + legend + totals. PPTX generates
    without error (the flipV/circle path). NOT done locally (documented gap): live Sonnet regen (no
    API key) and soffice→PDF (not installed) — server eyeball before merge.
  - LEAN/WEB SPLIT: charts are LEAN static for pptx/pdf export. Rich/animated/interactive charts +
    full type set = WEB surface, deferred, consuming the same chart_series/chart_type spec. Web
    surface is the next major phase after the Telegram product ships; the deck spec is the synced
    source of truth across both surfaces. Deferred niceties: currency-prefix unit formatting
    ("$1.04M" vs "1.04$M"); per-sub-bar value labels on dense (>8) grouped charts.

## SHIPPED (image engine — branch feat/image-engine, off main @ 6528b3f)
- THREE image slots built FIRST-CLASS, all three end-to-end (schema → layout → parallel stage →
  sourcing/generation). Object-figure was built NOW, not deferred. Commits: schema e129482 ·
  layout ecb3737 · portraits c108ded · generation 5b67086 · stage d87dc27.
  - PORTRAIT (real people): PersonItem + TimelineNode → Wikidata (wbsearchentities → wbgetentities:
    P31/P569/P570/P18 + description) → Commons imageinfo/extmetadata. GATED + LEGAL: license
    whitelist PD/CC0/CC-BY only (classify_license; reject markers checked before cc-by so cc-by-sa
    is rejected); require instance-of-human; a provided date that contradicts a candidate
    disqualifies it (namesake protection); portrait-rank rejects statues/busts/logos/low-res;
    abstain (null) on any doubt. NO AI likeness of a real person, ever.
  - OBJECT-FIGURE (the workhorse): SlideContent.figure_prompt/figure_url/figure_subject_type +
    ImageSubjectType enum, authored by editorial, rendered contained (objectFit:'contain') in the
    right column of concept_definition / content_split, clear of the text. Null url → slide renders
    exactly as before (no empty box).
  - BACKGROUND (scene): synthesized by the ImagePass for the title-hero from deck title +
    design.image_style_prefix, full-bleed. CURRENT POLICY title-hero only (selective/atmospheric +
    budget); concept_definition-without-figure is the next natural target if wanted.
  - TIMELINE PORTRAITS: wired fully — portrait_url on TimelineNode (Py+TS), rendered above the date
    band in timeline.ts, resolved via Commons from a node portrait_prompt the editorial prompt now
    emits for person-centered nodes.
  - SOURCE-INFORMED GENERATION: PyMuPDF now extracts embedded figures (bytes + "Figure N:" caption
    + page context, skip <150px, capped) into SourceFigure, threaded through SourceProcessingResult.
    The generator topic-matches a slide's subject to a source figure, captions it (Gemini vision,
    falling back to the extracted caption) to STEER the prompt as art direction, then generates —
    output is ALWAYS the generated bytes, source pixels are NEVER copied. No/weak match → generate
    from subject alone. Every generated image carries design.image_style_prefix for deck cohesion.
  - CLIENT: GeminiImageClient (gemini_image.py) extends the GeminiClient pattern (injectable fns,
    retry/timeout/auth-propagation, Vertex→AI-Studio via shared build_default_genai_client) to image
    generation + vision. Image model id via NASHR_IMAGE_MODEL (deployment-configurable).
  - STAGE: ImagePass (after editorial, before render; TOTAL_STEPS 6→7). ALL slots resolve in
    PARALLEL (one asyncio.gather over resolve→re-host→write-back, so uploads overlap too); each
    image re-hosted via FileStorage temp/{project_id}/ with a 7-day signed URL. ABSTAIN FLOOR: any
    failure/low-confidence leaves the url null and never crashes the deck. Generated images obey a
    per-deck budget (default = SPEC standard tier 2; figures before background); Commons portraits
    are free of it. Wiring the budget from GenerationPackage tier is a follow-up.
  - ATTRIBUTION: CC-BY credit folded into the affected slide's speaker_notes — NO credits slide and
    NO new DeckSpec field (per product call: only the teacher sees it; reuse existing content).
    PD/CC0 need no credit.
  - RENDERER DEVIATION (necessary, flagged): the prompt assumed "no renderer changes"; the
    placeholder guard's `length > 500` heuristic would blank real (long) signed URLs. Replaced with
    isPlaceholderImageSrc (constants.ts) — a real http/file/data/path ref is never a placeholder at
    any length; '[' prompt markers still caught. Applied in html-renderer, pptx-renderer, and the Q6
    audit.
  - OUT OF SCOPE (deliberate): animated/interactive images — WEB surface only, deferred.
  - VERIFIED: pyright packages/ clean; ruff clean on all changed files (pre-existing SIM105 in
    payment_flow.py + 6 ruff-version format-drift files are untouched baseline, not from this work);
    pytest 1181 passed / 32 skipped; vitest 301 passed / 3 skipped, the ONE red being the
    pre-existing text-measure F (vendored Plex font unmatched by fontkit on this Windows box →
    char-width fallback; fails identically on the PART-1 commit, unrelated to images).
  - NOT EYEBALLED LOCALLY (server step before merge, per master prompt): the LIVE network paths
    (Wikidata/Commons sourcing, Vertex image generation, Gemini vision) and the actual RENDERED
    portraits/figures/backgrounds. Unit tests mock those boundaries; live behaviour + visual quality
    must be confirmed by regenerating the sCO2 deck on the server. "All tests pass" ≠ "verified
    end-to-end." Live tests are gated behind NASHR_LIVE_NET=1 (Commons) and the server's Vertex creds.

## SHIPPED (integrity + de-slop pass — branch feat/image-engine)
- WHY HERE: three load-bearing "interim" decisions on the image + editorial paths were
  silently nullifying a paid feature (premium == standard == 2 images) and littering
  decks with hollow filler. They share a class (a constant standing in for logic on a
  paid or visible path = bug, not interim), so fixed as a CLASS and wrote the discipline
  into [INVARIANTS.md](INVARIANTS.md) before changing anything. Referenced from this file's top.
- INVARIANTS.md (NEW): I1 (no constant for tier logic on paid path; tier difference must
  be observable in output), I2 (every slide carries content weight — no bare-section
  dividers, no echo breathers), I3 (text wins; title-hero scene guaranteed AHEAD of
  lower-priority images within the deck budget; basic-tier 0-budget generates NOTHING,
  hero included — this resolves the latent #1↔#3 tension where naive "reserve outside
  the budget" would nullify basic tier), I4 (no TODO/stub/interim on a load-bearing path
  without Iko sign-off; two deferrals recorded by name: bundle_article_presentation tier
  + GenerationJob.image_count telemetry).
- BUG #1 — TIER → IMAGE BUDGET (wire, not invention): PRESENTATION_TIER_IMAGE_LIMITS
  already existed in constants.py with the SPEC values (0/2/5). The bug was that nobody
  read it — orchestrator constructed ImagePass() once with the constructor default 2,
  so every tier got 2. The web-Claude prompt said "if numbers aren't defined, STOP and
  ask Iko" — they ARE defined; no ask needed, just wire. Fix:
  - constants.py: re-keyed PRESENTATION_TIER_IMAGE_LIMITS from dict[str,int] to
    dict[GenerationPackage,int] so pyright catches drift when a new tier is added
    (the type system enforces the invariant). Added image_budget_for_package(package)
    helper with a documented standard-tier fallback for not-yet-wired tiers (bundle).
  - image_pass.py: ImagePass.resolve_deck gained a per-call max_generated_images
    override; the budget is a property of the JOB, not the engine instance. Constructor
    default kept as the floor for tests/ad-hoc callers.
  - presentation_orchestrator.py: run_full_pipeline + resolve_images take
    package: GenerationPackage as REQUIRED keyword-only — explicit choice on a paid
    path is the invariant; no silent default at the orchestrator.
  - presentation_flow.py: new _package_for_generation helper at the str→enum boundary
    (handler is the one place that owns the parse; falls back to STANDARD with a logged
    warning on malformed FSM data, never to BASIC, so a flow bug never accidentally
    starves a paying user to zero images).
- BUG #2 — BACKGROUND PRIORITY (invert, but WITHIN budget): swapped
  _BACKGROUND_PRIORITY (0) and _FIGURE_PRIORITY (1) so the title-hero scene takes the
  first claim in the budgeted slice. The SUBTLETY the web-Claude prompt missed: "reserve
  the background outside the figure allocation" must NOT mean "exempt from budget" or
  basic tier (budget 0) would still ship a hero image, nullifying I1 + violating SPEC
  free-tier pricing. So the hero is guaranteed AHEAD OF, not EXEMPT FROM, the budget;
  zero budget generates nothing. The existing test
  test_generated_budget_caps_figures_and_prefers_them_over_background pinned the OLD
  buggy priority — flipped to test_generated_budget_reserves_title_hero_background_first
  asserting the new (correct) order, and added test_zero_budget_generates_nothing_including_hero
  for the basic-tier corner.
- BUG #3 — CUT FILLER (drop the slop, keep the device): the two auto-injectors of
  hollow "•" SECTION_BREAK dividers (_fix_consecutive_repeats for R01,
  _insert_section_breaks for R03) are REMOVED — they only ever produced bare-label
  dividers that violate I2. The breather _insert_breathing_after_data is RETAINED
  (master prompt: "do not delete the device, default it OFF") via an enabled=False
  kwarg; the stat-echo seed it ships with today is an I2 violation if emitted, so
  default off until model-authored breathers replace it (BUILD_STATE plan item 2).
  Added _drop_hollow_dividers filter in _post_process (runs BEFORE _ensure_first_is_title
  so a stray bare SECTION_BREAK at slides[0] never gets promoted to title-hero) that
  drops any SECTION_BREAK whose subtitle AND body_text are both empty — the hard
  backstop for I2 on LLM output. Updated SLIDE_TYPE_DESCRIPTIONS[SECTION_BREAK] and
  EDITORIAL_SYSTEM rule 8 so the model puts the section label in section_name and the
  one-line THESIS in subtitle; a well-behaved model produces no hollow dividers and the
  filter is just the guarantee. R01/R03 are now MODEL-prompt concerns only — documented
  in the editorial module docstring; previously they were enforced by hollow dividers
  in post-process, which is exactly the slop I2 forbids. Side effect on _merge_slides:
  with fewer thesis-bearing breaks, interactive slides fall back to end-append (the
  existing fallback) — a normal "quiz finale" pattern, not a regression.
- ALSO removed dead _ImageTask.is_generated field (set in 4 places, read nowhere) —
  de-slop discipline applied to this file too, per advisor flag.
- PHASE 3 ACCEPTANCE (engine + orchestrator levels, both required):
  - ENGINE: test_premium_budget_yields_strictly_more_generated_images_than_standard
    builds a deck with hero + 6 figure slots, runs ImagePass at budgets 2 and 5,
    asserts the budget caps the generated count and PREMIUM (5) > STANDARD (2).
  - WIRE: test_full_pipeline_threads_package_to_image_budget (parametrized basic/
    standard/premium) and test_full_pipeline_premium_image_budget_strictly_exceeds_standard
    inject a spy ImagePass into the orchestrator and assert the EXACT budget the
    orchestrator passed per tier. This is the regression that proves the wire — it fails
    on any code that lets the budget default at the orchestrator (the bug today).
  - I3: test_drop_hollow_dividers_keeps_thesis_breaks_and_drops_bare_ones, plus the
    rewritten post-process tests that pin the new (correct) behavior: no auto-injected
    hollow dividers, no auto breather by default, the breather device still works when
    enabled (kept for plan item 2).
  - constants.py: coverage assertion test_image_tier_limits_cover_every_presentation_tier
    fails the build if a new presentation_* tier is added without a budget entry.
- VERIFIED locally (gates green on changed files):
  - pytest tests/ -q: 1204 passed / 32 skipped (the same skip set as the prior commit;
    LibreOffice + RUN_E2E_TESTS + RUN_LIVE_API_TESTS unset locally).
  - ruff check + format --check: clean on all 10 changed files.
  - pyright packages/: 0 errors / 0 warnings.
  - vitest: 1 failure / 301 passed / 3 skipped — the failure is the documented
    text-measure.test.ts sCO2 title line-count baseline (plan item 11 / F).
    Identical to pre-edit state; I touched zero TypeScript.
- NOT verified locally (server eyeball gates DONE — per master prompt):
  - Live regen of the sCO2 deck on PREMIUM tier: needs Iko to confirm the log shows
    `gemini_image_generated` > 2 (the wire actually fires more generations) and the
    title-hero background is rendered.
  - Live regen on STANDARD vs PREMIUM same source: confirm the rendered deck count of
    images differs and that PREMIUM > STANDARD in the wild.
  - Slide-count drops on regen (no hollow "•" section breaks, no "Key takeaway"
    echo breather), every remaining slide carries content.
  - Eyeball any atmospheric background behind text — scrim contrast is already enforced
    by heroBackground + quality-audit.ts (no code change needed), but visual confirmation
    is the gate.
  - "All tests pass" ≠ "verified end-to-end." DONE is gated on Iko's server pass.

## SHIPPED (editorial resilience — branch feat/image-engine)
- WHY HERE, not a hardening branch: the editorial pass was collapsing every run to the 2-slide
  "Insufficient source material" fallback, which BLOCKED testing the image engine on this branch
  (no real deck → no slots to resolve). So the fix lands on feat/image-engine to unblock the image
  eyeball, not as a separate initiative.
- ROOT CAUSE = the recurring CLASS, not two fields. The editorial schema is tighter than the
  model's natural output, and the whole LLM response is validated as ONE _LLMSequence — so a SINGLE
  bad field on a SINGLE slide rejected the WHOLE deck. Same family as FIX1/FIX2/FIX3 above
  (table_rows, comparison, chart_series), which were patched one field at a time; this one keeps
  returning on new fields, so the fix is the MECHANISM.
- THREE LAYERS:
  - LOOSEN over-tight caps (the genuine schema bug): StatItem.unit and ChartSeriesPoint.unit
    10 → 32. Real units the model emits — "liters/year", "of facility energy", "of waste heat" —
    were nuking the deck at 10. 32 covers descriptive units without inviting prose. Conservative on
    purpose: only the two units confirmed from live logs were raised. StatItem.trend (4) is the only
    other notably-tight cap but the prompt never tells the model to emit it (absent from the schema
    example), so it is low-risk and the coercion net below would catch a rare overflow anyway.
  - SYNC prompt → schema (preventive): EDITORIAL_SYSTEM now states the limits the model fills —
    "unit max 32 chars, terse, put descriptive words in the label" and "every slide MUST have a
    non-empty title" — so the model stops emitting the violations in the first place.
  - COERCE at the one choke point (_parse_sequence, the real safety net): on ValidationError, before
    falling back, attempt FIELD-LEVEL salvage on exactly two safe-to-fix classes, then re-validate
    ONCE. (1) string_too_long on any field → truncate to the field's declared max_length at a word
    boundary; (2) a slide title that is null/empty/missing → synthesise a terse title from the
    slide's own text (subtitle/body/bullet/stat label/quote), or drop that ONE slide. Anything else
    is left untouched, so genuinely garbage output STILL falls back (coercion never masks real
    failure). Logs editorial_coerced_and_recovered on success; keeps editorial_invalid_schema on the
    genuine-failure path. It is a bounded salvage at one site, NOT a coercion framework.
- VERIFIED (the gates this Python-only change affects): pytest tests/unit/test_editorial_pass.py +
  test_presentation_models.py 102 passed (+11 new — over-long unit truncated not rejected; null /
  empty / missing title repaired; untitled-with-no-text dropped not whole-deck; unknown slide_type
  still falls back; full pipeline with BOTH violations yields a full multi-slide deck not the
  2-slide fallback; uncoercible output → emergency deck; the three real units validate at the new
  cap). pyright packages/ clean; ruff check + format clean on changed files. The Node renderer
  (vitest/tsc) is untouched by this change — pure Python.
- NOT done locally (be honest, per master prompt): the live sCO2 regen on the server (needs running
  services + real Sonnet key) — the proof that the deck now comes back full instead of 2 slides, and
  that editorial_invalid_schema is gone/coerced-and-recovered in the logs — must be run on the
  server BEFORE merging anywhere.

## PLAN
1. [x] Free batch: A · C2 · B-interim — DONE 48f713b
2. [~] Editorial structured fields: H tables + G comparison + D-data chart_series — DONE this branch.
   STILL OPEN (separate model-quality concerns, not this fix): B-real (model writes breathing
   takeaways) · C (model drops its own numbered items).
3. [x] Step 2 chart renderer (free) — native-shape charts from chart_series — DONE this branch (see SHIPPED below).
4. [x] image engine — three slots (portrait/object-figure/background), Commons-gated portraits,
   source-informed generation, abstain floor, parallel resolution, attribution in speaker_notes.
   THIS BRANCH (feat/image-engine). Server eyeball of live + rendered output before merge.
5-12. [ ] intent (6/7) · grounding deepen (8) · convo edit (9) · honest failure (10) ·
   fontkit accuracy (11, incl. the text-measure F red) · font library (12)

## NOTES (load-bearing, don't rediscover the hard way)
- The "free verification loop against debug/last_deck.json" assumes a banked sCO2 deck;
  `debug/` is gitignored and that file is NOT in a fresh checkout. The durable free loop is:
  vitest (`npx vitest run`), the worker `layout` CLI on `__tests__/fixtures/enlightenment.json`,
  and pytest. A crafted data_emphasis fixture lives in `layout-data-emphasis.test.ts`.
- B-interim TRADE (R27 weakened, deliberate): breathers now inject only when the preceding
  data slide carries a usable `stats` entry. CHART_DATA / TABLE_COMPACT hold numbers in
  prose/rows, not `stats`, so a chart→table run gets NO auto breather. Absent beats hollow.
  The model-authored breather in plan item 2 restores coverage for those gaps.
- Still-red, unrelated to the over-long fix: `text-measure.test.ts` sCO2-title-line-count
  (1 vs 2). This is the MULTI-token wrap-width calibration facet of plan item 11 (F) — the
  title fits the renderer's box but exceeds nominal*0.78, so the measurer counts 2 lines.
  The over-long SINGLE-token facet is fixed (c79036c); this title case is a different one
  (RENDER_WIDTH_SAFETY tuning) and remains open. Do not attribute to A/C2/B or to c79036c.

## STATUS IS TRUTH: `git log -- docs/BUILD_STATE.md` shows what shipped. Not chat memory.

## HYGIENE (opportunistic): unify Py/TS font allowlists · rotate PAT + SSH · fix unhealthy
healthcheck · commit debug scaffolding · PDF interactive reveal treatment (gray-band regression).
