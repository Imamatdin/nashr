# SlideForge / Nashr — BUILD STATE   (read first, every session)

STATUS: PRODUCTION. Past MVP. No MVP scope, no "works for now." Fix at the correct layer,
verified. Iko runs Claude Code locally against the real repo; master prompts carry acceptance
tests; a step is DONE only when a commit changes this file.

INVARIANTS: See [INVARIANTS.md](INVARIANTS.md) — load-bearing contracts that outrank test
status. A violation is a bug regardless of whether tests pass. Read after this file.

## RECONCILED TO MAIN (2026-06-03, HEAD 7e8aa57)

Read this first. The SHIPPED blocks below were written on their feature branches; many say
"THIS BRANCH … NOT main" or "before merge." That is a PRE-MERGE SNAPSHOT and is now STALE —
every branch's work is on `main`. This block is the current source of truth for merge state;
the SHIPPED narratives are kept verbatim for institutional memory, each with a one-line
merge-status correction added under its header. Git-verified: `local main == origin/main ==
7e8aa57` (via `git merge-base --is-ancestor`, `git branch --merged`, `git cherry`).

| Branch | On main? | Carrying SHA |
|--------|----------|--------------|
| feat/image-engine | YES | merge `0533b3b` |
| feat/chart-renderer | YES | `6528b3f` (direct) |
| feat/layout-fill | YES | merge `0eae69c` |
| feat/planner-bound-editorial | YES — branch tip == main (0 ahead / 0 behind) | `7e8aa57` |
| fix/editorial-structured-fields | YES | `b7e5d0f` |
| fix/editorial-resilience | YES (feature) — see note | `6a0b504` (under merge `0533b3b`) |
| fix/data-emphasis-prefixes-breathing | YES | `48f713b` / `5dc17d7` |

Two MERGE COMMITS carried the bulk and were never recorded here until this reconciliation —
this is the actual drift (there is no "run-5" entry; the merges simply went unlogged):
- `0533b3b` "merge: image engine, editorial resilience, integrity pass, chart selection"
- `0eae69c` "merge: layout canvas-fill + Q1 chart-label overflow fix"

`fix/editorial-resilience` NOTE: the standalone branch ref (tip `69f2df1`) shows unmerged
(`git cherry` → `+`, 1 ahead) because the work was re-committed during integration, not
patch-equivalent. The FEATURE is on main: `_coerce_llm_object` + the
`editorial_coerced_and_recovered` path are present in `packages/presentation/editorial.py`
(`6a0b504`, under merge `0533b3b`). The branch ref is superseded; its content is on main.

PHASE 2 — ON MAIN, GATE STATUS UNVERIFIED. The planner-bound-editorial work
(`890a67f`→`177c83e`→`4154e8f`→`5af2fb7`→`d12fa2d`→`eb7c0ca`→`7e8aa57`) is on `main` (branch
tip == main). That is a git fact. It does NOT mean Phase 2 is done. Phase 2's own definition
of done is a green Vertex gate on BOTH decks, and the repo records NO such run: the last
recorded run is RUN-4 (HEAD `7e8aa57`), which FAILED Enlightenment (the `explanation_note`
schema cascade) with the fix marked "CODE COMPLETE, gate ready for re-run." That code is what
is on main, with no later run recorded.
- ON MAIN: yes (git-verified).
- GATE GREEN / PHASE 2 DONE: UNVERIFIED — not witnessed by git.
- ⚠ WATCH (owed before Phase 2 can be called done): a green Vertex run on BOTH decks
  (Enlightenment + sCO2) via `python scripts/proof_planner_phase2.py`. Until Iko records that
  run here, Phase 2 is "merged but un-gated," NOT done. Do not stamp it DONE.

The CONFIRMED BROKEN table below gains a `Status` column (fixed rows cite their SHA) and four
new rows (I–L) from a live sCO2 render on 2026-06-03 (HEAD `7e8aa57` + image engine); evidence
screenshots committed under `docs/screens/`, eyeballed against each row before recording.

## VERIFIED DONE (evidence, not memory)
- Decimal truncation "73.8 bar" — fixed 8f5b587, renders intact slide 2.
- Collision/clip/overflow stacking — committed, margins documented.
- 6 interactive formats render (Enlightenment deck = proof).
- git: laptop == origin == server, clean.

## CONFIRMED BROKEN — by layer (sCO2 deck: layout.json + last_deck.json)
| # | Symptom | Layer | Cost | Status | Evidence |
|---|---------|-------|------|--------|----------|
| A | data-emphasis: unit drawn twice ("1.58PUE"+"PUE"), labels stranded | RENDERER | free | FIXED 48f713b | data-emphasis.ts concat + fixed-fraction y |
| B | "Key takeaway / preceding data underscores..." hollow slide | CODE→EDITORIAL | free interim / paid real | PARTIAL — interim 48f713b; device default-OFF 0b58208; B-real OPEN (plan 2) | editorial.py _insert_breathing_after_data hardcoded stub |
| C | numbered list 1,2,4,5 — model dropped its own #3 | MODEL | PAID | OPEN (plan 2, model-quality) | last_deck.json bullets has 4 items |
| C2| literal "1. " prefixes baked into bullets | MODEL + code guard | paid+free | FIXED 48f713b | same bullets |
| D | chart slide: chart_series=null, data stuck in prose | SCHEMA (not MODEL) | free | FIXED b7e5d0f (FIX3) | _LLMSlide had NO chart_series field; extra="ignore" dropped any emitted — FIX3 adds the field |
| E | "[Chart placeholder]" — chart renderer unbuilt | UNBUILT (Step 2) | free | FIXED 6528b3f | chart-data.ts placeholder by design |
| F | chart title collides with chart box (2-line title under-measured) | RENDERER (Step 11) | free | OPEN (plan 11) | floor logic correct, fed wrong title height |
| G | comparison slide: left_column/right_column null, renders blank | PROMPT↔SCHEMA | free | FIXED b7e5d0f (FIX2) | prompt emitted {"comparison":{left,right}} but _LLMSlide only accepts top-level left_column/right_column → extra="ignore" swallowed it — FIX2 |
| H | table_compact: table_headers/table_rows null, renders empty grid | SCHEMA (not MODEL) | free | FIXED b7e5d0f (FIX1) | _LLMSlide had no table fields; SlideContent + table-compact.ts already rendered them — FIX1 wires the link |
| I | table_compact rows render as oversized bordered boxes (text pinned top, large empty cell below); other rows bare text — inflated row heights + inconsistent borders. Data correct (FIX1), layout wrong | RENDERER (layouts/table-compact.ts) | free | FIXED (L1 branch fix/L1-worker-render-correctness) — root cause `dataRowHeight=(TABLE_H-HEADER_H)/actualRows` (fixed-fraction → 17.5%-tall rows, text top-anchored). Now: capped/min row band, each cell vertically centered in its band (hug+reposition; both renderers valign:top), table block centered in region. Live eyeball owed (slides 6+13) | live sCO2 render 2026-06-03, slides 6+13 → docs/screens/sco2_2026-06-03_slide-06.jpg, slide-13.jpg |
| J | generated object-figures + concept diagrams render on pale/near-white grounds against the dark deck — light panel on near-black. I3 covers text-over-bg scrim, NOT figure-panel-vs-deck tonal match | IMAGE-ENGINE or RENDERER (gen-spec / compositing — trace) | free or paid | OPEN | live sCO2 render 2026-06-03, slides 4/7/9/11 → docs/screens/sco2_2026-06-03_slide-04.jpg, -07, -09, -11.jpg |
| K | AI-generated labeled phase diagram has garbled baked-in text — axis reads "73.8ia7 bar" where the title + diagram both mean 73.8 bar. VIOLATES SPEC §2.6 "never generate AI images containing text"; fix is a ROUTING GUARD (figure subject_type implying labels/axes → mechanical/drawn, NEVER Gemini), not a one-off patch | IMAGE-ENGINE (routing; SPEC §2.6) | free | OPEN (L3 visual-system) | live sCO2 render 2026-06-03, slide 7 → docs/screens/sco2_2026-06-03_slide-07.jpg |
| L | closing slide renders title pinned top, rest empty — dropped body or failed hero-closer with no background. Layer NOT yet traced (read closing-slide authoring in editorial.py + the closing layout before assigning) | RENDERER or EDITORIAL (trace before fixing) | free or paid | TRACED (L1), bucket-UNRESOLVED pending one fact. Worker renders title-only CORRECTLY when a content slide's body arrays are empty (summary_takeaway/data_emphasis/content_split all degenerate to title-only; no worker path drops populated body). 18 slides ⇒ not the emergency deck. ⇒ LEANS EDITORIAL (LLM authored an empty-bodied closer), NOT L1 worker scope. The one fact that settles it: grep slide 18's content in `/app/debug/last_deck.json` on the next live run — empty body ⇒ editorial (defer; I2-on-the-closer, same family as B-real); a populated field the closer layout doesn't read ⇒ worker contract mismatch ⇒ L1. GAP regardless of layer: a title-only content slide slips BOTH Q5 (fires only on zero content) and I2's `_drop_hollow_dividers` (SECTION_BREAK only) | live sCO2 render 2026-06-03, slide 18 → docs/screens/sco2_2026-06-03_slide-18.jpg |

## SHIPPED (L1 — worker render-correctness: Q1 reliability floor + table geometry)
*[Branch fix/L1-worker-render-correctness, NOT merged. Gate = Iko's live droplet render, NOT recorded green yet. "All tests pass" ≠ DONE.]*
- SCOPE (approved Stage-1 plan + two owner changes): fix ONLY the two independent worker bugs —
  (1) the Q1 overflow hard-fail reliability floor, (2) row I table geometry. Canvas-fill (defect
  4) was DROPPED from L1 by owner decision (see DEFERRED). No editorial/model/schema/image-engine
  changes. Row J/K → L3, Q1 fit-correctness → L2 (unchanged).
- DEFECT 1 — Q1 RELIABILITY FLOOR (centerpiece; the live user-facing dead-end):
  - Bug, end to end: `buildTextBlock` (layouts/shared.ts) shrank to a floor and, if the text
    STILL didn't fit, set `overflow=true` WITHOUT truncating (docstring claimed the renderer
    truncates — HTML clips via overflow:hidden but PPTX/PDF do not). Q1 (audit/quality-audit.ts)
    read `block.overflow`, emitted `severity:'fail'` → `is_exportable=(failed===0)` false → the
    worker `render` (src/index.ts) `process.exit(1)` rendering NOTHING. Audit is deterministic, so
    ALL three formats exit 1 (presentation_orchestrator.py appends a warning + continues, never
    raises) → zero outputs → the bot has nothing to deliver → "an error occurred." Live
    Enlightenment hit exactly this.
  - Fix (worker only): buildTextBlock now TRUNCATES-and-ellipsizes at the floor (binary-search the
    longest char prefix + '…' that fits; RE-MEASURE so measuredHeightPct + downstream stacking
    stay honest), marking the block `truncated=true` (new optional TextBlock field). Truncation
    lives at the ONE chokepoint all text passes — not a per-caller opt-in — so it covers
    titles/body/bullets/table cells/comparison points/keywords (the general content blocks
    c13f644's chart-label minFontSize path never reached).
  - Q1 reframed: a `truncated` (or, in a pathologically narrow box, still-`overflow`) block →
    `severity:'warn'`, NEVER `fail`. A fit/overflow condition can no longer set is_exportable=false.
    The warning is kept LOUD + logged (slide index + truncated text) so L2 can locate these slides.
  - I5 AMENDMENT (flagged, owner-approved): docs/INVARIANTS.md I5 — Q1 overflow moved from the
    `fail`/blocks list to a new "degrade-and-ship (warn)" category, with an explicit paragraph that
    this is NOT "fit no longer matters" (it changes the RESPONSE: truncate+warn, deck always ships;
    real fit-correctness is L2). Written so it cannot be read as a cosmetic downgrade.
  - OBSERVABILITY (review fix — the warn must be LOCATABLE, not just counted): the worker `render`
    command previously printed only a warning COUNT on success (the per-slide `[Q1] …slide N…` detail
    was printed only by the `audit` subcommand), and presentation_orchestrator.py logged worker stderr
    only on a NON-zero exit — so post-fix a degraded-but-exported deck would have HIDDEN its
    truncation (the severity flip from fail→warn silently reduced observability on the render path).
    Fixed: `render` now emits each warning's `[Q1] (slide N) <message + truncated text>` to stderr on
    success, AND the orchestrator logs that stderr (`presentation_render_warnings`) on the success
    path. This is what makes the I5/BUILD_STATE promise ("slide index + truncated text, logged for
    L2") true on the production path — and what the live-gate grep below actually finds.
- DEFECT 2 — ROW I TABLE GEOMETRY (layouts/table-compact.ts): replaced fixed-fraction
  `dataRowHeight=(TABLE_H-HEADER_H)/actualRows` (inflated few-row tables to ~17.5% rows, text
  pinned to the top, odd-row-only zebra reading as bordered boxes) with a capped/min row band,
  each header/cell hugged + VERTICALLY CENTERED in its band (both HTML and PPTX valign:top, so
  centering is positioning the hugged block's y), and the table block centered in the region.
  Odd-row zebra retained on the compact bands. Same fixed-geometry disease addc4f9 cured for
  data_emphasis/flow_process; table-compact never got it. NOT canvas-fill: no font growth, no fit
  budget — pure table-internal geometry.
- DEFERRED, on purpose:
  - CANVAS-FILL (defect 4) → L2, ENTIRELY (owner call). concept_definition/content_split/
    comparison/summary_takeaway already do measured document-flow but TOP-ANCHOR (top-third
    cluster, dead space below). The real fill is FONT-GROWTH, which needs L2's word↔pixel budget;
    the only L1-safe piece (geometric centering) is marginal, can ORPHAN short prose mid-canvas,
    and would hand L2 a cosmetic layer to reconcile/undo. Ship NOTHING on canvas-fill in L1. ALL of
    it — every layout, content_split's full-height-box vertical-align, font-growth-to-fill — is L2.
    The top-third-cluster look (slide-09) persists visibly until L2; acceptable (cosmetic, never a
    hard-fail).
  - Q1 FIT-CORRECTNESS (text actually fitting) → L2. L1 only guarantees the floor degrades. No
    WORD_LIMITS change, no per-locale constant.
  - ROW L (closer) → CONFIRMED BROKEN row L: traced, leans editorial, settle via the slide-18 grep
    on the next live run; Q5+I2 title-only-slide gap logged there.
  - ROW J (pale figure ground) + ROW K (AI diagram baked text, SPEC §2.6 routing guard) → L3.
- BLAST RADIUS (tests that pinned old broken behavior → flipped to the degrade contract):
  quality-audit.test.ts ('fails on overflow' → 'degrades a residual overflow to a WARNING…';
  'blocks export on a Q1 failure' → 'does NOT block export… degrades to a warning') + a new
  truncated-block warn test + a new END-TO-END test (real LayoutPass → real audit: a wall of text
  truncates and STILL exports — the closest local proxy to "Enlightenment now exports");
  layout-pass.test.ts ('stops reducing… flags overflow' → 'truncates at the floor… stays
  exportable'; totalOverflows aggregation → asserts truncation cleared it); text-block-stacking.test.ts
  +3 buildTextBlock truncation tests; layout-table.test.ts +1 compact/centered-rows test. Existing
  table tests (header count, one-block-per-cell, odd-row zebra ≥2, alignment, fallback) unchanged +
  green.
- FILES: types.ts (+truncated), layouts/shared.ts (truncateToFit + buildTextBlock floor),
  audit/quality-audit.ts (Q1 → warn), layouts/table-compact.ts (row geometry), src/index.ts (render
  emits per-warning detail on success), packages/bot/orchestrators/presentation_orchestrator.py
  (logs worker stderr on the success path) + the 4 test files + INVARIANTS.md/BUILD_STATE.md.
- VERIFIED locally:
  - `npm --prefix packages/presentation-worker run typecheck` (tsc src + tsconfig.test): clean.
  - vitest: 353 passed / 3 skipped / 1 FAILED — the failure is the PRE-EXISTING text-measure F red
    (sCO2 title 1-vs-2 lineCount, plan item 11), confirmed pre-existing by a git-stash round-trip
    (still fails on clean HEAD with none of this branch's changes; this change touches zero of
    text-measure.ts). Net +5 passing tests vs main.
  - Python: ONE edit (orchestrator success-path warning log). `python -m pytest tests/`: 1292 passed
    / 32 skipped (baseline, unchanged); orchestrator suite 25 passed; ruff check + format --check on
    the edited file clean, LF. (The repo's 3 pre-existing ruff errors + format-drift live in files
    this branch never touched — local ruff newer than the repo pin; not introduced here.)
  - NB the bare `pytest` shim resolves to the wrong interpreter on this box (60 spurious collection
    errors); `python -m pytest` is the correct invocation and is green.
- NOT verified locally (server eyeball = DONE): a live droplet render. CENTERPIECE to verify: the
  Enlightenment deck that was HARD-FAILING now EXPORTS (degraded where text didn't fit — truncated
  with '…' + a Q1 warning in the log — never the "an error occurred" dead-end). Plus sCO2 slides
  6+13: tables read as compact, evenly-spaced rows with centered cell text + consistent striping
  (no giant bordered boxes). Workflow: git pull → docker compose up -d --build bot; proof harness
  runs detached in the container; grep the log for the Q1 truncation warning + confirm no `Quality
  audit FAILED`. While there, grep slide 18 in /app/debug/last_deck.json to settle row L.
- DONE = this branch's fixes + this BUILD_STATE entry + Iko's live-render eyeball. NOT green tests.

## SHIPPED
*[RECONCILED 2026-06-03: ON MAIN — 48f713b (A/C2/B-interim) + c79036c (over-long line-count). On main, not pending.]*
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
*[RECONCILED 2026-06-03: ON MAIN via b7e5d0f. "THIS BRANCH … NOT main" below = pre-merge snapshot.]*
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
*[RECONCILED 2026-06-03: ON MAIN via 6528b3f. "THIS BRANCH … NOT main" below = pre-merge snapshot.]*
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
*[RECONCILED 2026-06-03: ON MAIN via merge 0533b3b. "branch feat/image-engine" framing below = pre-merge snapshot.]*
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
*[RECONCILED 2026-06-03: ON MAIN — 0b58208, via merge 0533b3b.]*
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

## SHIPPED (chart-selection intelligence + Q4 demote — branch feat/image-engine)
*[RECONCILED 2026-06-03: ON MAIN — f185779, via merge 0533b3b.]*
- WHY: the editorial pass had NO data-shape → encoding rules, so the model defaulted to
  zero-based bars even where bar misleads — sCO2 deck slide 5 plotted PUE 1.08/1.25/1.675
  as near-equal columns, slide 15 plotted heat-recovery 0/0/5/20 where the zeros drew
  as absent bars. Same time, Q4 (adjacent-same-layout) was a `fail` severity and was
  BLOCKING export over a stylistic concern. Both fixed as one batch because they share
  the cause: the audit + prompt layer trying to enforce the wrong invariants.
- TWO LAYERS for chart selection (editorial picks right; renderer guard is the backstop):
  - EDITORIAL (`packages/core/prompts.py`): added a DATA-SHAPE → ENCODING decision block
    to EDITORIAL_SYSTEM (six concrete rules — LARGE SPREAD FROM ZERO → bar; RATIO/INDEX
    CLUSTERED → DATA_EMPHASIS / single_value, NOT zero-based bar; LITERAL ZEROES → not
    bar; SINGLE DOMINANT NUMBER → single_value; ORDERED PROGRESSION → line; MULTI-SERIES
    PER CATEGORY → grouped/stacked) plus a new ABSOLUTE RULE 15 ("NEVER default to a
    zero-based bar"). Each rule is named and greppable so a future regression that drops
    a rule fails its pinning test.
  - RENDERER GUARD (`packages/presentation-worker/src/charts/chart-guard.ts`, NEW):
    `validateChartEncoding(content)` is a pure function that runs before drawChart and
    catches two failure modes deterministically. (1) LOW-SPREAD BAR — `chart_type=bar`
    with all-nonzero values whose max/min < 1.5 → re-route to `single_value`, headlining
    series[0] (preserves editorial ordering) and folding the rest into the subtitle so
    no data is lost. Truncated-axis bars were the alternative and were REJECTED (advisor
    flag): scope creep for a backstop, and the structurally cleaner fix — moving the
    slide to DATA_EMPHASIS — lives upstream in editorial. The guard is the floor, not
    the ceiling. (2) ZEROS IN BAR — some-but-not-all zeros → keep `chart_type=bar` but
    flag the zero indices so drawBar emits an explicit baseline tick (visible, anchored
    to plot.bottom) instead of an absent column; the eye reads "0 measured" not "data
    missing". Every re-route is logged via `process.stderr.write` (matching the worker's
    existing pipeline at src/index.ts / src/font-metrics.ts), key=value structured so it
    is greppable: `chart_encoding_rerouted from=bar to=single_value reason=low_spread`.
    THRESHOLD: max/min < 1.5 (Cleveland 1985 perceptual-flatness floor); documented in
    the file next to LOW_SPREAD_THRESHOLD so a future maintainer can tune without
    spelunking. The five existing chart_types are unchanged — this is a SELECTION
    problem, not a missing-type problem.
- Q4 DEMOTE (`packages/presentation-worker/src/audit/quality-audit.ts`): consecutive-
  layout-repeat moved from `severity: 'fail'` to `severity: 'warn'`. A deck with the
  only-Q4 issue now exports (`is_exportable: true`). Unit-tested by
  `Q4 — warns on consecutive same type but does NOT block export (invariant I5)` —
  pins severity 'warn' EXPLICITLY so a future revert is caught. Q4 was the only
  cosmetic check at `fail` severity; the other `fail`s (Q1 overflow / Q2 contrast /
  Q5 empty / Q7 unrenderable font / Q9 interactive completeness / Q10 quiz feedback /
  Q13 wrong-language) all gate genuine user-visible breakage and remain `fail`.
  Justification recorded in I5 (below).
- INVARIANTS.md: added I5 "A quality gate may vary, degrade, or warn, but MUST NOT
  block export over a cosmetic issue." Enumerates which checks are correctness (block)
  vs cosmetic (warn) and the rationale: a user who paid for a deck gets the deck. New
  audit checks default to `warn`; upgrades to `fail` must name the specific breakage
  they prevent and be defended in I5.
- OUT OF SCOPE (deliberate, noted in the chart-guard.ts module docstring): grouped_bar
  / stacked_bar with zero sub-values — the editorial DATA-SHAPE → ENCODING rule
  routes those away from grouped/stacked. If the model still mis-routes a grouped
  chart with zeros, extend the guard in a follow-up; the seam is in place. ALSO out of
  scope per the master prompt: body_text → speaker_notes truncation (slides 2/5/14);
  the four near-identical air/liquid/sCO2 redundancy (editorial-variety concern, the
  Step 1 prompt rule is the lever, batches with the variety patch); per-slide
  atmosphere router; animated/interactive WEB-surface charts (deferred — LEAN/WEB
  split intact).
- VERIFIED locally (gates green on changed files):
  - pytest tests/: 1210 passed / 32 skipped (+6 new — the EDITORIAL_SYSTEM rule pin
    + five parametrized data-shape round-trip tests covering PUE-near-1, zeros,
    big-spread, single-number, two-point progression).
  - vitest packages/presentation-worker: 317 passed / 3 skipped (+16 new — 13 for
    chart-guard.test.ts pinning the pass-through, re-route, and annotation decisions;
    3 for draw-chart.test.ts proving the end-to-end behavior). ONE failure is the
    pre-existing text-measure F red (plan item 11 — vendored Plex font unmatched by
    fontkit on this Windows box; documented across multiple prior SHIPPED entries,
    unrelated to this work).
  - tsc --noEmit: clean on src + tests.
  - pyright packages/: 0 errors / 0 warnings.
  - ruff check + format --check on changed Python files: clean.
- NOT verified locally (server eyeball gates DONE — per master prompt):
  - Live regen of the sCO2 deck on server. Must confirm: slide 5 (PUE) is NO LONGER
    a flat near-equal-bar chart (either editorial routes it to DATA_EMPHASIS / chart_
    type=single_value at source, OR the renderer guard re-routes it and emits a
    `chart_encoding_rerouted` log line); slide 15 (heat recovery) does not show empty
    bars (renderer guard annotates zeros with explicit baseline ticks); charts across
    the deck show VARIETY (line / single_value / grouped / bar where it earns its
    place), not bar four times. Screenshot the chart slides into docs/screens/ and
    eyeball.
  - Q4 export: confirm the deck exports through the worker without the audit blocking
    on adjacent duplicates.
  - "All tests pass" ≠ "verified end-to-end." DONE is gated on Iko's server pass.

## SHIPPED (editorial resilience — branch feat/image-engine)
*[RECONCILED 2026-06-03: ON MAIN — feature in editorial.py (_coerce_llm_object) via 6a0b504 under merge 0533b3b. NB standalone ref fix/editorial-resilience (69f2df1) shows unmerged — superseded; content is on main.]*
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

## SHIPPED (chart-encoding correctness — branch feat/image-engine)
*[RECONCILED 2026-06-03: ON MAIN — f4c76b7, via merge 0533b3b. "gate the merge to main" line below = satisfied (merged); the live visual check it names is now tracked as rows I–L.]*
- WHY: the chart-selection pass (f185779) re-routed low-spread bars to single_value by
  headlining `series[0]` and folding the rest into a subtitle. On the live sCO2 deck slide
  10 "sCO₂ Achieves PUE 1.08" with series [Air 1.57, Liquid 1.25, sCO2 1.08], series[0] is
  Air — so the slide titled for sCO2 printed a giant "1.57 PUE", the value the slide
  BEATS. Slide 14 (payback Liquid 5yr / sCO2 3.2yr) drew TWO discrete categories as a LINE,
  implying a continuous trend that does not exist. Two bugs, one root cause: the encoding
  layer was inferring the wrong shape from the wrong signal (position-in-array, presence-of-
  line). Fixed at the same two layers as f185779 — editorial prompt + renderer guard.
- RENDERER (`packages/presentation-worker/src/charts/chart-guard.ts`):
  - LOW-SPREAD COMPARISON now re-routes to a chart-internal `multi_stat` mode instead of
    single_value. All N points reach the renderer (the gap IS the story; throwing it away
    was the source of the wrong-headline bug). The SUBJECT card carries `palette.accent`;
    the others render in body text. `single_value` is reserved for the genuinely one-number
    case (one-point series, an editorial intent).
  - SUBJECT PICKER (`pickSubjectIndex`, exported for testing): three rules in priority
    order. (a) Title-token match — the series label that appears in the title wins; when
    several match, the LAST occurrence wins (handles "Air vs sCO2 …" → sCO2). Normalisation
    is NFKD-aware so "sCO₂" in the title matches the ASCII "sCO2" series label (NFKD
    decomposes U+2082 → "2", combining marks stripped, lower-cased, non-alphanumerics
    dropped). (b) Metric-polarity lexicon — `pue / cost / latency / payback / downtime /
    footprint / emission / error / loss / risk / overhead` → argmin; `efficiency / saving /
    recovery / throughput / capacity / density / performance / yield` → argmax. (c)
    Fallback — argmax (biggest number is the natural hero). English-biased by design
    (false positives are worse than misses); the model is steered by the prompt to put
    the subject in the title so (a) wins on the common case.
  - LINE < 3 POINTS now re-routes to `bar` and re-evaluates the bar guards — so a
    low-spread 2-point line (e.g. 1.0/1.2) cascades all the way to `multi_stat`, not a
    flat two-bar chart. Both re-routes log one stderr line each:
    `chart_encoding_rerouted from=line to=bar reason=line_too_few_points` then
    `from=bar to=multi_stat reason=low_spread`.
  - `applyBarGuards` extracted so the cascade is one helper call from two paths
    (initial-bar + line→bar), not duplicated logic. `LINE_MIN_POINTS = 3` exported next
    to `LOW_SPREAD_THRESHOLD` so a future tuner sees both knobs together.
- RENDERER (`packages/presentation-worker/src/charts/draw-chart.ts`):
  - New `drawMultiStat` — renders N stat cards inside the chart region. Per stat: number
    (heading tier, hugged), unit (caption tier, secondary color, hugged), label (caption,
    text color). Stacked and centered the same way DATA_EMPHASIS columns are. Subject
    card uses `palette.accent` for both number AND label, bold weight, so the slide's
    argument is unmistakable; others use body text. Number tier shrinks with count
    (displayLarge for 1, heading for 2-3, subheading for 4+) so cards breathe.
  - drawChart switches on the new `'multi_stat'` value in the render-internal
    `ChartRenderType = ChartType | 'multi_stat'`. The PUBLIC `ChartType` is unchanged.
- EDITORIAL (`packages/core/prompts.py`):
  - ORDERED PROGRESSION rule tightened: line REQUIRES `THREE OR MORE points` over a
    genuine sequence axis. Explicitly forbids two-discrete-category lines ("NEVER use
    line for two discrete categories") and names the failure case ("payback Liquid vs
    sCO2"). Two-point comparisons go to DATA_EMPHASIS or bar.
  - New TITLE-SUBJECT ALIGNMENT block: when a slide argues for a specific value, the
    title MUST name it in the same wording as the stat/series label. The block names
    the polarity lexicon so the model knows the deterministic fallback the renderer
    will use if the title is generic.
- VERIFIED locally:
  - vitest packages/presentation-worker: 47 passed in chart-guard + draw-chart suites
    (`__tests__/chart-guard.test.ts` + `__tests__/draw-chart.test.ts`). Full vitest:
    332 passed / 3 skipped / 1 PRE-EXISTING failure (text-measure F-red — plan item 11,
    documented above; verified pre-existing by stash-and-rerun).
  - pytest tests/: 1211 passed / 32 skipped (+2 new — the line-rule pin and the
    title-subject-alignment pin).
  - tsc --noEmit: clean.
  - ruff check + format --check: clean on changed Python files.
  - pyright packages/core/prompts.py: 0 errors / 0 warnings.
  - SCO2 FIXTURE eyeball (`debug/sco2_chart_fix_fixture.json` → `debug/chart-fix-out/`):
    layout.json shows slide 1 (PUE) text blocks "1.57"/"1.25"/"1.08" with "1.08" colored
    `#E8553A` (the deck accent) and the others in body color — sCO2 IS the headlined
    subject. Slide 2 (payback) has 2 rects (bars) + 1 axis-aligned line (the baseline
    rule) and ZERO diagonal `line` segments — bar, not line. Screenshots at
    `debug/chart-fix-out/slide_1_pue_multi_stat.png` and `slide_2_payback_bar.png`
    confirm visually: PUE shows three cards with sCO2's 1.08 in accent orange, payback
    shows two clean orange bars labeled Liquid (5 yr) and sCO2 (3.2 yr).
- DONE = this commit + this BUILD_STATE entry + live regen on server (slide 10
  headlines 1.08, slide 14 is bars) gate the merge to main.

## SHIPPED (layout fill — branch feat/layout-fill)
*[RECONCILED 2026-06-03: ON MAIN — addc4f9, via merge 0eae69c. "NEEDS SERVER EYEBALL / branch" below = pre-merge snapshot.]*
- data_emphasis + flow_process were structurally under-filling the slide (live sCO2 deck:
  stat numbers squatting in a 50% mid-slide strip at the 64px tier cap; flow steps nailed to
  y=28..65 by hardcoded y-constants, leaving y=12..28 and y=65..94 as dead space). Fixed at
  the RENDERER layer — no editorial/model/schema changes — by attacking the real causes:
  band geometry on stats, hardcoded-y constants on flow.
  - STAT_POSITIONS (constants.ts) keeps the original horizontal layouts but expands the
    vertical band to the full content envelope: 1–3 stat rows now span y=14..94, the 4-stat
    2×2 grid splits into two y=14..53 + y=55..94 bands. Title region unchanged.
  - data-emphasis.ts now sizes the number tier ADAPTIVELY against the band height minus
    the measured below-stack height (unit/label/comparison): terse labels → big number,
    verbose labels → smaller number, ceiling 240px (matches the new flow_process cap).
    `maxSingleLineFontSize` probes each value for one-line fit in its column so a digit
    never wraps into "94" / "4"; pathological long values fall back to displayLarge.min
    instead of dragging the row down.
  - data-emphasis.ts: number blocks across a row now share a COMMON BASELINE (their
    measured bottoms align) AND render at a UNIFORM FONT SIZE (the MIN of per-stat single-
    line fits across the row). Pure baseline alignment with mismatched font sizes still
    reads staggered; the uniform-size pass costs one extra build per stat and is commented
    against future "simplification". 4-stat 2×2 baselines are per-row, not shared.
  - flow-process.ts removed every hardcoded y-constant (NUMBER_Y / LABEL_Y /
    DESCRIPTION_Y / DESCRIPTION_H / CONNECTOR_Y). Geometry is computed from the actual
    content region (title bottom → bottom margin) and the measured content: shared number
    row y, shared label row y, shared description top y with each description hugged to
    its OWN measured height (no fixed 15% description slot). Stack is vertically centred
    in the region. Connector y = midpoint of the number row, not a magic 35%. Number
    ceiling 240px, label promoted to FONT_SIZES.heading, description to FONT_SIZES.subheading
    so the larger band reads with real hierarchy. Honors INVARIANTS spirit (I1): no
    hardcoded constant stands in for measured layout on a visible path.
  - Tests added (`__tests__/layout-data-emphasis.test.ts` + `layout-flow-process.test.ts`):
    shared baseline within 0.5pp tolerance, uniform font size across a row, displayLarge
    floor under pathological values, per-row baselines for 4-stat 2×2, content spans >50%
    of band/region height, never overflow bottom margin (94pp), connector below
    descriptions, no adjacent-column overlap. Existing tests (uniform tier floor, hero
    unit separation, over-long value wrap) still green.
  - Render proof: `packages/presentation-worker/debug/render-fixture.mjs` produces a
    3-stat data_emphasis + 5-step flow_process fixture, screenshot via chromium. BEFORE
    (main): 64px stat numbers mid-slide with vast dead space, 1/2/3/4/5 digits the size
    of body text and microscopic descriptions. AFTER (this branch): ~200px stat numbers
    at a shared baseline with unit/label/comparison hierarchy filling toward the bottom
    margin, big bold step numbers with promoted labels and descriptions wrapping
    naturally. Screenshots at
    `packages/presentation-worker/debug/out/slide_1_data_emphasis_{before,after}.png`
    and `slide_2_flow_process_{before,after}.png`.
  - tsc green (src + tests). vitest: 346/350 + 3 skipped, 1 pre-existing red unrelated
    (`text-measure.test.ts` sCO2 title 1 vs 2 — plan item 11 / F, present on main before
    this branch; verified by `git stash` round-trip).
  - NEEDS SERVER EYEBALL: live regen of the sCO2 deck on the server to confirm the
    real-content (not fixture) data_emphasis + flow_process slides fill cleanly with
    actual editorial output.

## SHIPPED (Q1 chart-label overflow — branch feat/layout-fill)
*[RECONCILED 2026-06-03: ON MAIN — c13f644, via merge 0eae69c. "the branch merges to main" below = done.]*
- Live sCO2 regen of the heat-recovery slide failed Q1: 4 text blocks overflowing
  at 20px on a `chart_type: bar` with verbose unit "% waste heat recovered" (23 chars).
  Reproduced locally with the exact failing content (saved as
  `__tests__/layout-chart-data.test.ts > value labels with a verbose unit do not
  overflow Q1`) — `formatChartValue(0, "% waste heat recovered")` yields a 23-char
  value label that wraps to 2 lines in a 4-bar chart's 15.5pp-wide slot at
  subheading.min=20px, exceeding the fixed VALUE_LABEL_BAND=6pp by 0.26pp.
  - ROOT CAUSE was TWO compounding bugs, neither caused by layout-fill's tier
    promotions (those went elsewhere and didn't fire here):
    1. `valueLabel` measured against a fixed 6pp band even though every bar has
       much more real space above it (the available space up to `regionTop`).
       Short bars (value=0): ~60pp of room. Tall bar (value=20): ~8pp. Verbose
       labels wrap at 2 lines = 6.3pp which clears the dynamic h but blew the
       fixed 6pp.
    2. The shrink loop's floor was `tier.min`, so subheading-tier labels could
       not shrink past 20px even when geometry demanded it. The audit then
       caught the overflow and blocked export.
  - FIX (in `packages/presentation-worker/src`):
    - `layouts/shared.ts`: `BuildTextBlockOptions` now accepts `minFontSize?: number`.
      When set (typically `FONT_SIZES.minimum`), the shrink loop floor drops to
      that value. Default is `tier.min` so titles, headline numbers, and every
      existing caller behave unchanged. This is NOT Q1 demotion: a block that
      still overflows at `FONT_SIZES.minimum` is genuinely broken text and Q1
      still fires.
    - `charts/draw-chart.ts`: `valueLabel` now measures against
      `max(VALUE_LABEL_BAND, barTopY - regionTop - VALUE_LABEL_GAP)` — the
      dynamic available space above each bar — and opts into `minFontSize:
      FONT_SIZES.minimum`. `categoryLabel`, `multi_stat` label, `single_value`
      metric label, and the legend label all opt into the permissive floor as
      defence-in-depth (their tiers were already at the floor for most cases).
    - `layouts/flow-process.ts`: the user's flagged "cousin" — step label and
      step description opt into `minFontSize: FONT_SIZES.minimum`. The
      flow-process measure regions are already generous (full content region
      height), so this is defence-in-depth.
    - Headline NUMBERS in data_emphasis and flow_process do NOT receive the
      permissive floor: they hold their adaptive tier so the canvas-fill from
      the previous commit (`addc4f9`) stays headline-sized.
  - VERIFIED:
    - Regression test `value labels with a verbose unit do not overflow Q1
      (slide-11 regression)` in `layout-chart-data.test.ts` reproduces the
      failing content and asserts `overflow === false` on all four value labels.
    - Probe `scripts/probe-slide11.mjs` against the user's exact content:
      BEFORE = `[Q1] 4 text block(s) overflow on slide 11 at 20px` and
      `is_exportable=false failed=1`. AFTER = `overflowing=0` and
      `is_exportable=true failed=0`. The value labels in the AFTER probe land
      at fs=24 (subheading.max) — the dynamic measure region alone was enough;
      the permissive floor never had to kick in for this case.
    - Screenshot proof at `packages/presentation-worker/debug/out/slide_3_
      chart_data_q1fix.png`: "20% waste heat recovered" wraps to 2 lines
      cleanly above the tall bar; the three shorter bars carry one-line labels.
    - data_emphasis numbers still at 202px (unchanged from `addc4f9`);
      flow_process unchanged. No canvas-fill regression.
    - tsc clean (src + tests); vitest 347/351 + 3 skipped (+1 new); the only
      red is the pre-existing `text-measure` sCO2 title 1-vs-2 (plan item 11).
  - On the user's observation about saved-`layout.json` overflow:false vs the
    live audit reporting overflow:true: Q1 reads `block.overflow` directly from
    the layout (no re-measurement in the audit). Same code path. The saved
    layout was from earlier content with short units; the live regen with
    verbose units produces a different layout where the same block now has
    overflow:true. Not a measurement consistency bug — different inputs.
  - On the user's bar-width hypothesis: bars use `BAR_FILL_RATIO=0.62` of slot
    width, and labels always get the FULL slot width regardless. Bars do not
    compete with labels for horizontal room. The user's intuition pointed at
    "labels in narrow columns" which IS the right plane; the implicated
    geometry was the fixed label MEASUREMENT band, not the bar width itself.
  - NEEDS SERVER EYEBALL: same as `addc4f9` — live sCO2 regen on the server.
    Slide 11 (the heat-recovery chart) must now export with no Q1, and the
    verbose-unit value labels must read cleanly. After eyeball, the branch
    merges to main.

## SHIPPED (Phase 2 — planner-bound editorial — branch feat/planner-bound-editorial)
*[RECONCILED 2026-06-03: code ON MAIN (branch tip == main, 7e8aa57). Phase 2 is MERGED BUT UN-GATED — no green Vertex run recorded; see RECONCILED TO MAIN + WATCH at top. Do NOT read this block as DONE.]*
- WHY: editorial authored decks from a curated claim-bag with the source chunks DISCARDED
  (`del ... chunks`) and the people roster filtered through a hardcoded `_PERSON_KEYWORDS`
  frozenset — so the model never saw what the source said and filled gaps with its prior
  (Beethoven on an Enlightenment music slide the source names Bach + Mozart on). Phase 1/1.5
  built the planner + plan validator + multilingual thesis classifier ADDITIVELY (890a67f);
  Phase 2 binds the LIVE editorial path to the plan, adds the deck-vs-plan gate, and deletes
  the keyword roster.
- THE REWIRE (`editorial.py`, signature FROZEN): generate_deck_spec is now PLAN → validate plan
  (one re-plan on reject) → reground people_mentioned from plan.figures → size from plan → FILL
  → enforce deck-vs-plan (one scoped repair) → assemble. `del evidence_matrix, outline` narrowed
  (chunks/source_metadata now flow to the planner; the other two stay unused — keeps pyright).
- DECK-VS-PLAN GATE (`plan_validator.py`, pure functions, no LLM): D-S1 section coverage, D-F1
  figure adherence, D-X1 no-invented-figure (all FAIL); D-A1 invented-section (WARN). D-X1 is
  SCOPED to GALLERY_PEOPLE/TIMELINE and EXCLUDES TEAM_CREDITS (deck authors, not source figures).
  `failing_section_indices()` maps findings→sections for the repair. `critique_deck_adversarially()`
  is now the LIVE Phase-3 content critic (was a no-op seam): it returns a `ContentCritiqueResult`
  (grounded findings + an `llm_verified` flag) and still NEVER raises on LLM error — an unparseable
  critique degrades to `llm_verified=False` rather than crashing the deck. The hard stop lives one
  layer up in `_enforce_content_critic`, which raises `EditorialContentCriticError` when a
  code-confirmed C-FB/C-US survives the route+re-judge round (see the 2026-06-24 entry below).
- DECISION 1 (section identity = deterministic int join): the executor tags each slide with a
  `section_index` (on the internal `_LLMSlide` DTO ONLY — DeckSpec/SlideSpec/SlideContent
  UNCHANGED); `_materialise_slides` resolves it to the plan's canonical section_name, which the
  validator joins on — so coverage/adherence never false-fail on a model-paraphrased section label.
- DECISION 2 (repair = scoped splice, path a): `_repair_failing_sections` regenerates ONLY the
  failing sections, splices in place, then runs ONLY order-preserving post-steps
  (`_post_process_repaired`) — it deliberately SKIPS `_enforce_density_arc`, which reorders across
  section boundaries and would re-break the coverage the repair just fixed (the convergence hazard
  the web prompt's one-liner hid). One attempt; still-failing → EditorialDeckPlanMismatchError.
- RETRY/FAILURE POLICY: PlannerError / ThesisClassifierError propagate to the orchestrator's
  existing _OrchestratorError (a planner/classifier that can't do its job is a hard stop, not a
  degrade). Plan parses but fails validation → ONE re-plan with the findings fed back
  (plan_deck(feedback=)) → still failing → EditorialPlanRejectedError. The emergency-minimal deck
  (executor returned nothing usable) is EXEMPT from the deck-vs-plan gate — infra failure, not a
  plan mismatch; validating it would spuriously fail D-S1.
- B1 FIX (people_mentioned had TWO consumers; the web prompt claimed one): the field is KEPT and
  regrounded from plan.figures, so the executor's people brief AND the interactive-matching
  selector (`_pick_interactive_types`, ≥3 people) both stay correct. Deleting the field — as the
  prompt's "only one consumer" implied — would have SILENTLY killed the matching slide. Only the
  keyword DERIVATION dies; the field lives, now plan-sourced.
- DI SEAM: EditorialPass(planner=, classifier=) injectable; lazy getters reuse editorial's own
  LLM/Gemini clients so the classifier inherits Vertex routing rather than default-building a
  fresh AI-Studio client.
- PROMPTS (`prompts.py`): EDITORIAL_SYSTEM gained the fill-the-plan contract + section_index in
  the output schema; EDITORIAL_USER carries the plan spine; added EDITORIAL_REPAIR_USER +
  PLANNER_FEEDBACK_HEADER. Static rules stay in SYSTEM (cache-friendly per the Phase-4 split);
  per-deck spine lives in USER.
- DEVIATIONS (disclosed, Iko-accepted): exception names carry the *Error suffix
  (EditorialPlanRejectedError / EditorialDeckPlanMismatchError) per repo N818 lint + the existing
  PlannerError/ThesisClassifierError convention, NOT the master prompt's bare names; one-line
  Phase-1 public alias `build_enlightenment_fixture` so the Phase-2 harness reuses that fixture
  without importing a private symbol.
- A5 (cohesion-note DEFERRED honestly, NOT dropped): DeckPlan.image_cohesion_note →
  DesignDirectionSpec.image_style_prefix wiring is NOT done here — design runs BEFORE editorial
  (where the planner now lives), so it needs a pipeline reorder that belongs with the visual-system
  phase. The DeckPlan docstring was corrected from "Phase 2 will feed this" to point at that phase.
- DEFERRED DEBT (logged in HYGIENE, NOT silently kept): `interview.py` has its OWN, pre-existing
  `_PERSON_KEYWORDS` frozenset powering `available_people_count` at interview time. Same disease as
  the deleted editorial roster but LOWER STAKES (a slightly-off UI count, never a fabricated slide)
  and UNFIXABLE the Phase-2 way — the interview runs BEFORE any plan exists, so there is nothing to
  reground from. Left in place; fix in a later phase via NER at interview time or by moving planning
  earlier in the pipeline. Distinct symbol from the editorial one; deleting it now would break a
  live feature with no replacement.
- VERIFIED locally (gates green):
  - pytest tests/: 1274 passed / 32 skipped (same env-gated skip set: e2e/live-API/LibreOffice/
    Tesseract). New coverage: 8 deck-vs-plan validator tests (D-S1/F1/X1/A1 + TEAM_CREDITS scoping
    + empty-roster fabrication guard + year-suffix name match); editorial retry-policy (one re-plan
    with feedback / reject-twice raises / one section repair); the keyword-path-dead test;
    plan-driven sizing. The ~10 existing generate_deck_spec tests were migrated to a stub
    planner+classifier factory + section_index-tagged payloads.
  - ruff check + format --check: clean on all 10 changed files. pyright packages/: 0/0/0.
  - sCO2 source fixture (`scripts/sco2_source_fixture.py`, transcribed from the real paper) self-
    checks + round-trips; the Phase-2 harness imports and wires BOTH fixtures (runs to its env gate).
- NOT verified locally (server Vertex gate = DONE): live generate_deck_spec on both sources via
  `python scripts/proof_planner_phase2.py` (needs ANTHROPIC_API_KEY + VERTEX_PROJECT / ADC, or
  GOOGLE_API_KEY for AI Studio). Bars — Enlightenment: people NOT null, Bach+Mozart not Beethoven,
  every planned section present, no invented people, INTERACTIVE_MATCHING present, round-trip;
  sCO2: planner roster EXCLUDES the cited author 'Ahn' (author != portrayed subject), no person
  portrayed, no people slide forced, charts present, round-trip. WATCH on the run: does Sonnet
  reliably emit section_index (else _resolve_section_name silently falls back to fuzzy match); does
  pass 1 clear the gate or lean on the repair (extra Sonnet call); raise-on-mismatch is a NEW
  delivery-rate behavior (pre-Phase-2 a slightly-off deck still shipped). "All tests pass" ≠
  "verified end-to-end."
- SERVER RUN 1 (timeout tuning, NOT a logic bug): the first Vertex gate had the planner and the
  classifier pass clean, then the editorial EXECUTOR call timed out at the asyncio.wait_for in
  llm.py (retried twice, died). ROOT CAUSE: a 16k-max_tokens plan-bound generation legitimately
  runs long (~200-270s at Sonnet rates) and can exceed the shared DEFAULT_LLM_TIMEOUT_SECONDS,
  which is 180s — NOT 30s (the "30s" in the report traces to a STALE gemini.py docstring, now
  corrected; no `timeout_seconds=` override exists anywhere, so 180s is what the server ran). The
  proposed "lower to 90-120s" would have REGRESSED (below 180s). FIX: added an optional per-call
  `timeout` override to LLMClient.complete; _call_editorial_with_retry passes
  EDITORIAL_LLM_TIMEOUT_SECONDS (300s, a ceiling — normal decks return well under it) on both the
  first call and the retry; the section-repair path reuses that helper so it inherits the timeout.
  Planner/classifier/interactive keep the 180s default (per-call, not global). CHECKED every
  large-gen site: repair (covered via the shared helper); interactive Gemini is 3k max_tokens on
  2.5 Flash and the heavier 8k-thinking 3.5 Flash classifier already passed at 180s, so interactive
  is comfortably under (no change). +1 unit test pins the per-call override. If real generations
  routinely approach 300s, the proper next step is streaming (or a lower max_tokens), not a higher
  ceiling. Gate re-run pending.
- Renderer / image pass / interactive pass: ZERO changes (DeckSpec contract frozen; no orchestrator
  signature change — editorial already received the planner's inputs).
- DONE = this commit + this BUILD_STATE entry + the server Vertex gate green before merge to main.
  STATUS: gate run 2 recorded below — Enlightenment PASSES clean; sCO2 has ONE remaining
  executor people-leak to fix before the gate is fully green and the branch merges.
*[RECONCILED 2026-06-03: code merged to main (7e8aa57); the gate it names is NOT recorded green — see WATCH at top. Merged ≠ gated.]*

## PHASE 2 — SERVER GATE (run 2): Enlightenment PASS, sCO2 one FAIL (executor people-leak)
Run on Vertex via `python scripts/proof_planner_phase2.py` AFTER the run-1 timeout fix
(EDITORIAL_LLM_TIMEOUT_SECONDS=300). The timeout is gone — both decks generated fully, end to end.
[RECONCILED 2026-06-03: HISTORICAL run-2 snapshot — SUPERSEDED by run-3/run-4 AND by the merge
to main. This is NOT the current source of truth; see the RECONCILED TO MAIN block at the top.
Kept for institutional memory.]

BRANCH / COMMIT STATE:
- Work is on `feat/planner-bound-editorial`, latest commit `4154e8f` (the
  EDITORIAL_LLM_TIMEOUT_SECONDS=300 per-call timeout fix), pushed to origin.
- [RECONCILED 2026-06-03: "NOT merged to main" is now FALSE. The work advanced past `4154e8f`
  to HEAD `7e8aa57` and IS on `main` (branch tip == main, 0 ahead / 0 behind). Gate status is
  still open — on main, but NO green Vertex run is recorded; see the Phase-2 WATCH at top.]
- Phase 1 + 1.5 are already committed and live on main: `890a67f` (DeckPlan contract + planner
  pass + plan-adherence validator) plus the Vertex-routing / Gemini-3.5-Flash classifier fix.
- (This BUILD_STATE run-2 entry is committed on the branch locally; per standing instruction it is
  NOT pushed by Claude — Iko pushes the branch to run the server gate.)

ENLIGHTENMENT (Karakalpak) — full generate_deck_spec on Vertex — PASSED EVERY BAR:
- 19 slides, a real narrative arc across the planned sections.
- Gallery slides carry REAL people (`people` is NOT null): slide 2 = Voltaire / Montesquieu /
  Rousseau / Diderot / D'Alembert; slide 8 = Newton / Leibniz / Euler; slide 11 = Bach + Mozart.
- Beethoven is ABSENT — the music slide is Bach + Mozart exactly as the source names them. The
  ORIGINAL FABRICATION BUG (Beethoven substituted for the source's Bach/Mozart; people=null on
  every slide) is DEAD in production, not just in unit tests.
- INTERACTIVE_MATCHING slide present — the B1 regression guard holds: people_mentioned regrounded
  from plan.figures works, the second consumer survives.
- DeckSpec round-trips (renderer contract intact).
- The scoped-section repair (DECISION 2 / path a) FIRED ONCE on this deck
  (`editorial_deck_plan_mismatch_repairing` in the logs) and then passed — the repair primitive
  works in PRODUCTION, not just in the unit test.

sCO2 (English, real paper) — full generate_deck_spec on Vertex — ONE FAIL, narrow and understood:
- 22 slides; charts / tables / the DATA-SHAPE tree all intact (PUE 1.08 handled correctly,
  comparison tables present, no degradation from the chart-selection work).
- Planner roster came back EMPTY — CORRECT; the paper names no biographical subjects. The
  "roster EXCLUDES cited author 'Ahn'" bar PASSED: the planner distinguished a citation
  ("Ahn, Y. et al." in the references) from a portrayed subject.
- THE FAIL: the EXECUTOR attached `people=[Ahn, Y. et al.]` to slide 8, a `typographic_keywords`
  slide. The harness's all-slides person scan caught it. D-X1 did NOT catch it because D-X1 is
  scoped to GALLERY_PEOPLE / TIMELINE only — the exact limitation the advisor flagged in review
  ("a person on a non-gallery slide escapes the invented-figure gate") materialized on a real
  deck. A non-rostered person leaked onto a non-gallery slide type and slipped the deck-vs-plan
  validator.
- ROOT CAUSE is EXECUTOR-SIDE, not planner-side: the planner correctly excluded Ahn (empty
  roster); the executor independently attached the citation as `people` on a keywords slide.
- DeckSpec round-trips.
- OVERALL gate verdict: FAIL — solely because of this one leak; Enlightenment passed clean.

REMAINING FIX — RESOLVED this session (code complete; local gates green). The implementation and its
four reviewed DEVIATIONS from the literal plan below are recorded in `PHASE 2 — RUN-2 FIX` further
down. The plan as decided at run-2 was:
1. WIDEN D-X1 (plan_validator.py `_check_deck_invented_figures`): scan `content.people` against the
   roster on EVERY slide type EXCEPT TEAM_CREDITS (keep that carve-out — its people are the deck's
   own authors, not source figures; `test_team_credits_authors_not_flagged_d_x1` pins it). Per the
   schema, people belong only on gallery / team / timeline slides, so a person on a
   typographic_keywords slide is malformed regardless of roster membership — D-X1 is the
   production safety net that must catch it. (`_PEOPLE_BEARING_TYPES` was {GALLERY_PEOPLE, TIMELINE}
   at run-2; the implemented fix scans content.people on all non-TEAM_CREDITS slides, plus TIMELINE
   portrait_prompts, against the roster, and DELETES that now-dead constant.)
2. STRIP in _post_process (editorial.py): drop `content.people` from any slide type that is NOT
   GALLERY_PEOPLE / TEAM_CREDITS / TIMELINE, so a stray attachment is cleaned GRACEFULLY instead of
   failing the whole deck. The strip is the graceful cleanup; the D-X1 widening is the safety net
   that still surfaces the leak as a validation failure in production, not only in the harness.
3. PROMPT note (prompts.py / EDITORIAL_SYSTEM): instruct the executor not to introduce people the
   plan's roster omits, on ANY slide type (the fill-the-plan block already forbids inventing
   people; make explicit it applies to every slide type, not just gallery slides).
- After the fix: re-run the Vertex gate on sCO2; it should pass (no person on the keywords slide,
  or D-X1 catches any residual). Enlightenment already passes — re-confirm it still does.

WATCH-ITEM (log only, NOT blocking):
- On the sCO2 source the planner needed its internal retry-once (`planner_schema_validation_failed`
  → `planner_first_attempt_unparseable` → retry succeeded). The resilience worked as designed.
  First-pass unparseable output on a real source is a latency/cost signal; revisit only if it
  becomes frequent.

LOCKED DECISIONS (do not reopen):
- DECISION 1: section identity = the section_index integer join on the _LLMSlide DTO, resolved to
  the canonical plan section name at materialize. Working — slides resolved cleanly on both decks.
- DECISION 2: deck-vs-plan repair = scoped-section repair (path a), skipping _enforce_density_arc
  to avoid the reorder-rebreak hazard. Working — fired and passed on Enlightenment.
- interview.py `_PERSON_KEYWORDS` stays IN PLACE as logged debt (different risk class — a UI
  available_people_count, not a fabricated slide; unfixable the Phase-2 way since the interview
  runs before the plan exists; fix later via NER or by moving planning earlier). Do NOT delete it.

DEFINITION OF DONE (Phase 2): both decks pass the Vertex gate (Enlightenment already does; sCO2
passes once the executor people-leak is fixed). The leak fix is now CODE COMPLETE with local gates
green — see `PHASE 2 — RUN-2 FIX` below. DONE = Iko's Vertex re-run is green on BOTH decks, THEN merge
`feat/planner-bound-editorial` to main.

## PHASE 2 — RUN-4 FIX (executor schema-robustness + repair figure constraint): CODE COMPLETE, gate ready for re-run
SUPERSEDES run-3: the run-3 planner fix WORKED — sCO2 passed EVERY bar (empty roster first-try, no
people slide, charts intact; rule 10 held — no thank-you closer, no citation-as-person). The prompt
change then surfaced TWO pre-existing EXECUTOR bugs on Enlightenment — NOT regressions, the same
temperature-0 near-boundary nondeterminism the planner had, in the one component never inoculated.

WHAT RUN-4 SHOWED:
- sCO2: PASS, every bar. The run-3 planner-robustness fix is confirmed end-to-end.
- ENLIGHTENMENT: FAIL. Chain: the executor put a stray field `explanation_note` on a KeywordItem
  (slide 16) → `editorial_invalid_schema: slides.16.keywords.3.explanation_note extra_forbidden` →
  first attempt rejected → BLIND whole-deck retry → the retry's fresh sample DROPPED the French
  thinkers (Adam Smit / Daniel Defoe / Jonatan Swift) → D-F1 → scoped repair → repair came back STILL
  missing them → re-validate → EditorialDeckPlanMismatchError. Generation correctly REFUSED to ship a
  plan-contradicting deck (the backstop held); it just could not produce a valid one.

ROOT CAUSE (two executor bugs; the cascade links them):
- `_LLMSlide` is extra="ignore" (a stray TOP-LEVEL field is dropped), but its nested domain items
  (KeywordItem, PersonItem, ...) are extra="forbid". So a stray field on a NESTED item nuked the deck,
  and `_coerce_llm_object` salvaged only string_too_long + missing-title, NOT extra_forbidden. The
  unsalvageable error forced a BLIND whole-deck retry (EDITORIAL_RETRY_SUFFIX carried nothing about the
  failing field — the planner's disease, uncured here).
- THE CASCADE: the schema error (slide 16) and the D-F1 drop (French section, slides ~2-4) are from
  DIFFERENT attempts. A blind retry regenerates the WHOLE deck, so a one-field trip re-rolls every
  section and can drop people elsewhere. We could NOT statically confirm whether the repair's own drop
  was model non-compliance OR the repair hitting its own schema trip and returning [] (both surface as
  D-F1/D-S1 on re-validate) — the new logging discriminates on the next gate run.

WHAT SHIPPED (5 files: 1 new + 3 source + 1 test) on feat/planner-bound-editorial:
- NEW packages/presentation/_schema_feedback.py — the pydantic-error → instruction translator,
  EXTRACTED from the planner (loc_path / summarise_errors / format_schema_feedback) so planner and
  executor share ONE implementation and cannot drift (the define-once discipline of
  PEOPLE_RENDERING_SLIDE_TYPES). Planner refactored onto it, behaviour byte-identical (its 12 tests
  unchanged + green).
- BUG 1a — SALVAGE extra_forbidden (editorial `_coerce_llm_object` + new `_delete_field`): strip the
  stray nested key in place, re-validate. Deterministic, local, NO LLM — and the PRIMARY
  cascade-preventer: it preserves attempt-1's already-correct sections (the French thinkers), where a
  retry — even an informed one — regenerates the whole deck and could re-drop them. This is what the
  run-4 plan's "informed retry catches it locally" actually needs: the informed retry is NOT local (it
  re-rolls the deck); the salvage is. Logged `editorial_stripped_extra_field`.
- BUG 1b — INFORMED RETRY (editorial `_parse_editorial_response` → `_SequenceParse`;
  `_call_editorial_with_retry`): for schema errors salvage CANNOT fix (bad enum, missing required
  nested field) feed the EXACT field errors back under EDITORIAL_SCHEMA_RETRY_HEADER instead of
  resampling blind. Feedback comes from the POST-coercion error (exc2) when coercion ran, so it names
  what is STILL wrong, not the field already stripped. Malformed JSON keeps the generic suffix. NO
  second blind retry. The repair path routes through `_call_editorial_with_retry`, so it INHERITS both
  the salvage and the informed retry.
- BUG 1c — INTERACTIVE PASS inoculated (the OTHER un-inoculated component, found in review; run-4's
  framing of "the one component" was a misconception). `_LLMInteractive` is also extra="ignore"-top /
  extra="forbid"-nested (MatchingPair, QuizQuestion, ...), and `_parse_interactive` had NO salvage +
  only a blind retry — so a stray field on a nested interactive item would fail the INTERACTIVE_MATCHING
  bar (it did NOT trip run-4 only because generation raised before the interactive pass ran). Mirrored
  the same fix: strip extra_forbidden in place (logged `interactive_stripped_extra_field`), informed
  retry under INTERACTIVE_SCHEMA_RETRY_HEADER for non-salvageable errors. Reuses `_delete_field` + the
  shared module. Surfaced and approved as in-scope before shipping.
- BUG 2 — repair figure constraint (EDITORIAL_REPAIR_USER): a HARD REQUIREMENT that a regenerated
  failing section MUST portray its "required figures" on a gallery_people/timeline slide. This is
  DEFENSE-IN-DEPTH, not the confirmed fix — the cause of the drop is not statically confirmable (see
  cascade); the robust fix is the inherited salvage+informed-retry, and the existing
  re-validate-and-raise backstop in `_enforce_plan_adherence` already refuses to ship a
  plan-contradicting deck (it HELD on run-4).
- LOGGING: editorial schema failures now log the field path+type IN the message
  (`editorial_invalid_schema: slides.16.keywords.3.explanation_note (extra_forbidden)`), like the
  planner — so the next gate console names the culprit instead of a 3000-char str(exc) blob.

VERIFIED locally (gates green; NO Vertex creds — Iko runs the gate):
- pytest tests/: 1292 passed / 32 skipped (was 1284/32; +8 new editorial — salvage strips a stray
  nested field; salvage takes ONE call, no retry; a non-salvageable error drives an informed retry
  naming the field; post-coercion feedback names the remaining error not the stripped field; the repair
  prompt makes required figures a hard constraint; a repair that still drops a figure RAISES; the
  interactive pass strips a stray field on a matching pair; a non-salvageable interactive error drives
  an informed retry). Planner 12 unchanged. Same env-gated 32-skip set.
- ruff check + format --check: clean on all changed files. pyright packages/: 0 errors / 0 warnings.
- Direct probes (no LLM): stray nested field stripped + recovered with NO retry; bad enum → informed
  retry carries the field path + schema header; stray+enum → exc2 feedback names the enum, not the
  stripped field.

NOT verified locally (server Vertex gate = DONE). On the re-run, watch TWO things, CO-EQUAL:
1. sCO2 MUST STAY CLEAN — `_coerce_llm_object` and `_parse_editorial_response` are on BOTH decks' path;
   sCO2 passed clean on run-4 and must not regress (the reverse of run-3's Enlightenment watch).
2. ENLIGHTENMENT now generates — real thinkers on gallery slides (Voltaire/Montesquieu/Rousseau/
   Diderot, Smit/Defoe/Swift/Kant/Goethe, Newton/Leibniz/Euler, Bach/Mozart), Beethoven ABSENT,
   INTERACTIVE_MATCHING present, round-trips (the interactive pass is now inoculated too — a stray field
   on a matching pair is stripped in place, logged `interactive_stripped_extra_field`, so the matching
   bar survives it). Grep the log: `editorial_stripped_extra_field` / `interactive_stripped_extra_field`
   PRESENT = the model still improvises fields (now stripped in place, output preserved — debt to log);
   `editorial_invalid_schema` PRESENT with a repair following = a non-salvageable trip still fired the
   repair (then the informed retry / figure constraint must carry it). Record the actual field path+type
   HERE — it tells us whether run-4's repair drop was model non-compliance or the repair's own schema trip.

PENDING (Iko's Vertex run, then merge): both decks' bars, the actual editorial loc/type. DONE = green
on BOTH decks → merge feat/planner-bound-editorial to main → Phase 2 closes.

## PHASE 2 — RUN-3 FIX (planner schema-retry robustness): CODE COMPLETE, gate ready for re-run
SUPERSEDES the run-2 "definition of done" above: in run-3 the run-2 people-leak fix is CONFIRMED
WORKING, and a different, UPSTREAM blocker surfaced and is now fixed.

WHAT RUN-3 SHOWED:
- ENLIGHTENMENT: PASS, cleaner than run-2. 24 slides; real thinkers on every gallery slide
  (Voltaire/Montesquieu/Rousseau/Diderot, Smit/Defoe/Swift/Kant/Goethe, Newton/Leibniz/Euler,
  Bach/Mozart, Voltaire/Russo); people NOT null; Beethoven ABSENT; INTERACTIVE_MATCHING present;
  round-trips; scoped repair fired once and passed. The run-2 fix (d12fa2d:
  `_clamp_people_to_legal_types` + widened D-X1 + D-X2) is confirmed in the running container, and
  the D-F1 × strip regression vector did NOT bite — Bach/Mozart survived the strip.
- sCO2: FAIL — but NOT on the people-leak (that fix never got exercised; the planner died upstream).
  BOTH the first planner attempt AND the retry produced a DeckPlan that FAILED Pydantic validation
  (`planner_schema_validation_failed` ×2 → PlannerError). This is the run-2 WATCH-ITEM (~line 760)
  ESCALATING: run-2 the internal retry recovered once; run-3 both attempts failed. "Revisit if
  frequent" came due.

ROOT CAUSE (diagnosed before any fix — the no-guess discipline):
- NOT the empty figures roster (the tempting "ironic" hypothesis). Disproven three ways: (1) the
  schema has NO min_length on `figures` (presentation.py: `Field(default_factory=..., max_length=30)`);
  a deterministic local probe shows `figures=[]` + empty `figure_names` validates clean. (2) In run-2
  the sCO2 planner SUCCEEDED (proof harness calls plan_deck directly; `ahn_excluded` passed) —
  impossible if the schema rejected empty rosters, since the correct plan for this source ALWAYS has
  `figures=[]`. (3) Every validator guards `if plan.figures:`. The empty roster is correct output and
  MUST stay valid — no placeholder figure was added (there was no bound to satisfy).
- The real failure is an INTERMITTENT schema-edge trip. The planner runs at temperature 0
  (llm.complete default, not overridden) on a deterministic prompt, so this is NOT i.i.d. sampling at
  some p: the sCO2 source pushes output to the schema boundary (a stray field under extra="forbid",
  or a slide_type/phase enum near-miss, or sections>8, or a sub-12-char thesis — the full candidate
  set, probe-confirmed), and the hosted endpoint's residual non-determinism flips run-2 (recovered)
  vs run-3 (did not). A blind resample at temp 0 re-rolls the same near-boundary output — which is
  WHY retry-once could not recover and WHY a 2nd blind retry would not help.
- The retry was BLIND: on schema failure it appended only PLANNER_RETRY_SUFFIX (generic "return ONLY
  JSON" — carries nothing about WHICH field failed). The editorial layer-2 retry already feeds
  specific findings back (PLANNER_FEEDBACK_HEADER); the schema retry did not. That asymmetry is the
  bug.

WHAT SHIPPED (3 files: 2 source + 1 test) on feat/planner-bound-editorial:
- LOGGING (planner.py `_parse_plan`): logs `exc.errors(include_input=False)` and puts a compact
  `path (type)` summary IN THE MESSAGE STRING (`planner_schema_validation_failed: <summary>`), so it
  surfaces even under a default formatter that drops `extra` (the reason run-3's console showed only
  the bare event). loc/type is in the stderr WARNING lines, BOTH attempts — NOT in the PlannerError
  message (stays generic). Renamed the misnamed `planner_first_attempt_unparseable` (JSON parsed;
  schema failed) → branch-specific `..._schema_invalid_retrying` / `..._malformed_json_retrying`.
- INFORMED RETRY (planner.py `_call_with_retry`; `_parse_plan` now returns `_PlanParse(plan,
  schema_feedback)`): on a ValidationError (distinct from JSONDecodeError) the exact field errors are
  translated to corrective instructions (`_format_schema_feedback`) and appended under the new
  PLANNER_SCHEMA_RETRY_HEADER — mirrors the layer-2 machinery. extra_forbidden → "Remove the field
  `X`"; enum → pydantic's msg (echoes the valid set at RUNTIME — no hardcoded slide-type list) + an
  interactive_* caveat when the loc is planned_slide_types (so the menu doesn't contradict rule 6);
  length/count → pydantic's bound text. Malformed JSON keeps the generic suffix. NO 2nd blind retry.
  Robust to ALL candidate trips at once, without knowing which fired.
- PROMPT (PLANNER_SYSTEM, static/cached): rule 7 people-free carve-out (source names no subjects →
  `figures: []`, `figure_names` empty; a cited author is NOT a portrayed subject); rule 6
  no-invalid-slide-type (no equation/diagram/schematic; use content_split/data_emphasis/chart_data/
  table_compact); NEW rule 10 "A PRESENTATION IS NOT A PAPER" (no citation-as-people; no
  Thank-You/Questions/acknowledgements closer).
- DEVIATION (better fix, beyond the 4 planned steps): FIXED a latent bug in PLANNER_SYSTEM — its
  OUTPUT FORMAT schema example carried DOUBLED braces (`{{ }}`), a copy-paste artifact from the
  `.format()`-ed PLANNER_USER. PLANNER_SYSTEM is used RAW (never `.format()`-ed; its own comment says
  "fully static"), so the model literally saw malformed `{{ }}` JSON — a confusing schema example
  that RAISES the schema-edge trip rate this fix targets. Now single braces. Touches BOTH decks
  (see watch-item 1).

VERIFIED locally (gates green; NO Vertex creds locally — Iko runs the gate):
- pytest tests/: 1284 passed / 32 skipped (was 1280/32; +4 — informed retry carries the field path;
  schema failure logs the locs; empty-roster schema guard; people-free plan_deck accepts first try).
  Same env-gated 32-skip set.
- ruff check + format --check: clean on all 3 changed files. pyright packages/: 0/0/0.
- Direct probes (no LLM): `figures=[]` validates; informed retry recovers schema-invalid→valid in 2
  calls with the field path IN the retry prompt; malformed JSON uses the generic suffix; both-fail
  raises; enum caveat fires only for planned_slide_types.

NOT verified locally (server Vertex gate = DONE). On the re-run, watch TWO things, CO-EQUAL:
1. ENLIGHTENMENT MUST STAY CLEAN — the #1 regression risk. The prompt changes (brace fix, rule 10
   closer guidance, rule 7 carve-out) touch EVERY deck; stubbed unit tests CANNOT prove the live
   Enlightenment deck still yields Bach/Mozart, Beethoven-absent, INTERACTIVE_MATCHING present,
   round-trip. Confirm it loud. "1284 passed" says nothing about this.
2. sCO2 now produces a valid plan — empty-roster, no people slide, charts intact, round-trip.
   CAPTURE/grep stderr for `planner_schema_validation_failed` on BOTH attempts and record the actual
   loc/type HERE — the one diagnostic run-3 lacked. If the line still appears but the gate passes,
   the informed retry recovered (and the prompt fix may be reducing the first-pass trip rate); if it
   is absent, the prompt carve-out stopped the trip at the source. Either way the gate is green.

PENDING (Iko's Vertex run, then merge): the actual sCO2 loc/type, and both decks' bars. DONE = green
on BOTH decks → merge feat/planner-bound-editorial to main → Phase 2 closes.

LOGGED DEBT (do NOT chase now; separate quality item): the executor/planner default to
academic-paper and generic-deck furniture on formal sources — e.g. resources_links / references
slides the model reaches for by default. Rule 10 attacks the citation/thank-you slop at the planner;
the broader furniture-overuse tuning is later work, not Phase 2.

## PHASE 2 — RUN-2 FIX (sCO2 executor people-leak): CODE COMPLETE, gate ready for re-run
The run-2 leak (executor attached `people=[Ahn, Y. et al.]` to a `typographic_keywords` slide; D-X1
was scoped to GALLERY_PEOPLE/TIMELINE and missed it) is fixed in code on
`feat/planner-bound-editorial`. Implemented MUST + BETTER after a senior review of the run-2 REMAINING
FIX surfaced four issues in its literal form (recorded as DEVIATIONS below). Local gates green; the
server Vertex re-run is the one remaining gate (Iko runs it — no Vertex creds locally).

WHAT SHIPPED (6 files: 4 source + 2 test):
- ONE canonical constant `PEOPLE_RENDERING_SLIDE_TYPES = {GALLERY_PEOPLE, TEAM_CREDITS}` in
  core/enums.py — grep-verified as the ONLY two layouts that read `slide.content.people`
  (presentation-worker/src/layouts/gallery-people.ts + team-credits.ts). Imported by BOTH editorial
  (strip) and plan_validator (D-X2) so the two layers cannot drift. It is a STRUCTURAL schema fact
  about WHERE the people field may live — NOT a content allowlist of WHICH people may appear (that
  stays the source-grounded roster's job); said so in the comment to pre-empt the anti-`_PERSON_KEYWORDS`
  reflex on review.
- STRIP `_clamp_people_to_legal_types` in editorial.py, wired into `_materialise_slides` at the
  `people=` line — a sibling of `_normalise_figure`, the existing per-field legality clamp in that
  same loop. Drops `content.people` from any slide type outside PEOPLE_RENDERING_SLIDE_TYPES and LOGS
  `editorial_stripped_misplaced_people` (extra: slide_type + dropped names).
- WIDENED D-X1 (plan_validator `_check_deck_invented_figures`): roster-checks portrayed people on ALL
  slide types EXCEPT TEAM_CREDITS (was {GALLERY_PEOPLE, TIMELINE}). A non-rostered person on ANY slide
  type — the Ahn leak included — now fails.
- NEW D-X2 (`_check_deck_misplaced_people`): roster-INDEPENDENT structural check — `content.people`
  on a non-PEOPLE_RENDERING slide type FAILS regardless of roster membership. Registered in
  `validate_deck_against_plan` and in `failing_section_indices` (resolves the pinned slide → its
  section, same as D-X1). Deleted the now-dead `_PEOPLE_BEARING_TYPES`.
- PROMPT rule 16 in EDITORIAL_SYSTEM (static/cached): the `people` array is ONLY for gallery_people /
  team_credits; never attach it to any other slide type; a bibliographic citation is not a figure;
  timeline figures use portrait_prompt; holds regardless of roster.

DEVIATIONS from the literal run-2 REMAINING FIX (each reviewed BEFORE coding; each is the better fix):
- Strip lives in `_materialise_slides`, NOT `_post_process` (item 2 said _post_process). The REPAIR
  path does not pass through `_post_process`: `_repair_failing_sections` → `_materialise_slides` →
  `_splice_sections` → `_post_process_repaired` (which has no strip). A person re-attached during a
  repair would have shipped. `_materialise_slides` is the one chokepoint BOTH paths share, so the strip
  covers the repair path structurally, not by remembering a second call site.
- Strip carve-out is {GALLERY_PEOPLE, TEAM_CREDITS}, NOT {…, TIMELINE}. `content.people` renders only on
  those two; TIMELINE people live in `portrait_prompt`, a different field the strip never touches.
  Including TIMELINE would have been harmless but imprecise.
- Added D-X2 (BETTER tier). Widened D-X1 is a ROSTER check; the run-2 plan justified it as "malformed
  regardless of roster membership" — but a ROSTERED figure on a wrong slide type passes D-X1's roster
  gate. D-X2 is the roster-independent structural backstop that actually delivers that justification
  (and makes the public `validate_deck_against_plan` self-sufficient on un-stripped decks). D-X1 alone
  fully fixes the empty-roster sCO2 case; D-X2 closes the rostered-misplacement subclass that didn't
  occur on either deck but the gate should still catch.
- The strip LOGS (run-2 plan was silent). A silent drop would hide whether the executor STILL leaks
  after prompt rule 16. The gate goes green either way (the strip cleans before the gate runs), so the
  log line is the only tell — see watch-item 2.

LAYERING (honest framing): in the LIVE path the strip runs at materialise, BEFORE the deck-vs-plan gate,
so the widened D-X1 / D-X2 essentially never fire in production — the strip pre-empts them. They are the
BACKSTOP that matters when `validate_deck_against_plan` runs on an un-stripped deck (offline tools,
tests) or if a future refactor bypasses the strip; i.e. they keep the PUBLIC gate honest, they are not
the live enforcer. The strip is the live enforcer; prompt rule 16 is the soft layer at the source.

VERIFIED locally (gates green):
- pytest tests/: 1280 passed / 32 skipped (was 1274/32; +6 new — 2 validator [non-rostered person on a
  keywords slide → D-X1; rostered person on a keywords slide → D-X2 and NOT D-X1] + 4 editorial [strip
  removes from non-people types and logs; preserves gallery+team; full generate_deck_spec strips the
  leak BEFORE the gate with NO repair; EDITORIAL_SYSTEM rule-16 text pin]; plus the existing
  team-credits test strengthened with a D-X2 negative). Same 32-skip env-gated set.
- ruff check + format --check: clean on all 6 changed files (enums.py working-tree CRLF normalised to
  LF per ruff.toml line-ending=lf; index was already LF → no churn, the diff is +17 added lines only).
  pyright packages/: 0 errors / 0 warnings / 0 informations.
- Renderer / harness / orchestrator: ZERO changes. `scripts/proof_planner_phase2.py` is byte-for-byte
  unchanged — its `_deck_person_names` reads the FINAL (post-strip) deck, so the sCO2 `no_people` bar
  passes once the strip runs; no harness edit was needed.

NOT verified locally (server Vertex gate = DONE). On the re-run, watch TWO things:
1. ENLIGHTENMENT still passes — the D-F1 × strip vector. `_check_deck_figure_adherence` collects
   portrayed people via `content.people` REGARDLESS of slide_type, so a planned figure parked on a
   non-gallery slide currently satisfies D-F1; the strip removes it → D-F1 could fail → the one repair
   fires → if it re-misplaces, raises EditorialDeckPlanMismatchError. Low risk (run-2 put Bach/Mozart on
   GALLERY slides 2/8/11, which the strip preserves; the harness Bach/Mozart bars catch a regression
   loudly) — but it is the #1 thing to confirm green.
2. sCO2 now passes — no person on the keywords slide. Grep `phase2_proof.log` for
   `editorial_stripped_misplaced_people`: PRESENT = the executor still leaks (now cleaned, gate still
   green — debt to log); ABSENT = prompt rule 16 stopped it at the source. Either way the gate is green;
   the log is the only signal of which.

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
healthcheck · commit debug scaffolding · PDF interactive reveal treatment (gray-band regression)
· interview.py `_PERSON_KEYWORDS` — hardcoded people roster powering `available_people_count` at
interview time; same anti-pattern as the deleted editorial roster but lower stakes (a slightly-off
UI count, not a fabricated slide) and unfixable the Phase-2 way (interview runs before the plan
exists). Fix via NER at interview time or by moving planning earlier in the pipeline.

## 2026-06-19 — L2 layout engine Run 1 of 4 (merged to main)
L2 layout engine Run 1 of 4 — merged to main. Extracted shared fitMeasuredStack + emitBandCell from table-compact (pixel-identical re-point, Codex-verified equivalence locks from real pre-migration baselines). Migrated flow_process (center anchor), chart_data (fill-to-bottom-margin), drawMultiStat (center), content_split (removed the y18 floor, body now hugs title). Deleted getFlowStepPositions + getTimelinePositions orphans; deleted MIN_CHART_HEIGHT + MIN_BODY_H (derived/floored). Live sCO2 render verified all four on real fonts. Logged polish: narrow 5-column flow labels can wrap awkwardly (lone-letter orphan). REMAINING L2: Runs 2-4 (data_emphasis/comparison/concept_definition/typographic_keywords, then timeline/gallery/team/resources/interactives, then title/section/quote), per-locale length budget, auditor->routing judge.

## 2026-06-19 — L2 layout engine Run 2 part 1 (merged to main)
L2 layout engine Run 2 part 1 — merged to main. comparison, concept_definition, typographic_keywords migrated onto fitMeasuredStack (anchor start, no emitBandCell); dropped comparison y-floor; deleted getKeywordPositions frozen distribution. Emphasis branches byte-identical (Codex-verified). Live render confirmed all three. Deferred to canvas-fill pass: sparse slides clump at top (keyword anchor could be distribute since term/explanation are horizontal — revisit in fill work). Editorial flag: concept_definition definition fragment ('Above 31°C and') logged for Phase-3 judge. REMAINING L2: Run 2b (data_emphasis, baseline-up number math, option-a isolated), Runs 3-4 (timeline/gallery/team/resources/interactives, then title/section/quote), per-locale length budget, routing judge.

## 2026-06-20 — L2 layout engine Run 2b (merged to main)
L2 layout engine Run 2b — merged to main. data_emphasis migrated onto fitMeasuredStack: frozen STAT_POSITIONS band replaced by title-hug-derived region, 4-stat rows equal-split (frozen y:55 gone), adaptive number-fill preserved (region-derived band, not the circular measured-content recipe), buildNumberBlock measurement anchored at derived bandTop, MIN_STAT_REGION_H reserves the stat band against long titles (Codex P2: 107%->91.94%, 1-line titles byte-identical at contentTop 12.296). Emphasis byte-identical. Live render confirmed: numbers fill bands, 2x2 even, hero highlight. STAT_POSITIONS kept as groupRows key + max-bound. LOGGED for canvas-fill pass: moderate 2-line-title + long-label band-bottom overflow (~95.7%), to be fixed as general band-bottom enforcement not another magic number. SEPARATE pre-existing bug (NOT this run): title_hero scrim/background renders a hard seam in PPTX — renderer issue in pptx-renderer.ts (hard scrim rect and/or background embed falling through to white), own ticket. REMAINING L2: Runs 3-4 (timeline/gallery/team/resources/interactives, then title/section/quote), per-locale length budget, auditor->routing judge.

## 2026-06-20 — L2 layout engine Run 3 (merged to main)
L2 layout engine Run 3 — merged to main. Gallery centering fixed (1-2 person centered; widening to wider tier deferred as follow-up). 4 layouts re-documented as keep-frozen (timeline, gallery_people, team_credits, quiz). 6 composite/grid layouts migrated onto fitMeasuredStack (fill_blank, resources, true_false, debate, matching, categorize). Composite-overflow silent-truncation fix landed across the composites incl. concept_definition — Codex-found contract hole closed + 2x Codex confirmation passes. Live render confirmed gallery centering + timeline + keyword + data_emphasis. Interactive layouts paper-verified (tests + Codex); not yet eyeballed because real sources don't trigger them. Title_hero PPTX scrim seam = **fixed** (see 2026-06-21 entry). REMAINING L2: per-locale length budget, auditor->routing judge (Phase 3).

## 2026-06-21 — title_hero PPTX seam fix (merged to main)
Merged `fix/title-hero-pptx-scrim-seam`. `pptx-renderer.ts`: always paint `bg.color` underlay, full-bleed background via `addImage` (not `slide.background.path`), 12-slice gradient scrim (not one hard 70% rect). **Fixed:** bare white right 30% + hard vertical cut on title slide. Slide-13 `chart_data` panel verified byte-identical main vs fix (pre-existing surface rect, not a regression). **KNOWN REMAINING (title slide, cosmetic):** faint vertical hairlines from multi-slice scrim gradient — fade is correct; native OOXML `gradFill` would remove slice seams (queued). **LOGGED (pre-existing, own tasks):** PPTX font embedding (`fontFace` by name only → WPS clips/missing-font); LibreOffice-only render gate misses WPS/Windows viewer deltas.

## 2026-06-24 — content critic: re-judge cannot clear a known fabrication (branch build1-content-critic)
Codex re-review found the all-regens-fail edge: when a routed regen was REJECTED (original kept) and the re-judge then degraded (unparseable after retry) — OR simply ran and stochastically failed to re-propose the defect — `_enforce_content_critic` read zero hard-stop failures from the re-judge and SHIPPED the original C-FB/C-US fabrication (`critic_calls=3`, no `EditorialContentCriticError`). Root cause: `critique_deck_adversarially` collapsed "ran clean, found nothing" and "could not verify" into the same empty `PlanValidationResult`, and the enforce layer trusted a fresh, stochastic re-judge to RE-confirm a defect on a slide that had not changed.
- **RETURN CONTRACT (changed):** `critique_deck_adversarially()` now returns `ContentCritiqueResult(result: PlanValidationResult, llm_verified: bool)` — NOT a bare `PlanValidationResult`. It still NEVER raises on LLM error (a Gemini API error still propagates); an unparseable critique after retry degrades to `llm_verified=False` carrying only the code-detected hollow findings. Callers must not read empty `result.failures` as "clean" when `llm_verified` is False. All call sites (editorial.py ×2, test_content_critic.py) updated to read `.result`.
- **HARD-STOP (per-slide now):** a first-pass C-FB/C-US on a slide whose regen was REJECTED stands unconditionally — the slide is unchanged (word limits are idempotent and already applied before the first pass), so its deterministic, code-confirmed verdict holds and the stochastic re-judge is not entitled to clear it. If NO regen was accepted, the re-judge is SKIPPED entirely (the reproduced case) and the standing findings raise directly. A first-pass hard-stop on a CORRECTED slide is cleared only if the re-judge SUCCESSFULLY RAN (`llm_verified`) and did not re-flag it; a degraded re-judge keeps ALL first-pass hard-stops. (Diverges from the naive "trust the re-judge" patch, which leaves the stochastic-miss hole open — owner-approved.)
- **EMERGENCY GUARD (RISK fix):** `_is_emergency_deck` shape-inference DELETED. A real 2-slide deck (synthesized TITLE_HERO + a SUMMARY_TAKEAWAY titled exactly the sentinel) matched the fallback shape and skipped ALL gates. Replaced with an explicit origin flag `deck_is_emergency = not raw_slides`, set once in `generate_deck_spec` and threaded (kwarg-only) to `_enforce_plan_adherence`, `_enforce_content_critic`, and the interactive guard. Failure mode of a forgotten flag now fails SAFE (over-audits a fallback) instead of dangerous (skips a real deck).
- **NIT:** `gemini.py:41` comment corrected — `GEMINI_FLASH_3_5_MODEL` IS the GeminiClient default (`DEFAULT_MODEL`) and backs the interactive pass; the old "not the default / interactive stays on 2.5" text was false after the 3.x swap.
- **TESTS:** 2 red-green hard-stop tests added (regen rejected + re-judge unparseable → still raise; regen rejected + re-judge CLEAN → still raise — the divergence proof) plus the emergency false-positive regression (real deck matching the fallback shape IS critiqued) and `llm_verified` contract tests. Red-green verified by temporarily reverting to the pre-fix logic: all three hard-stop tests went red ("DID NOT RAISE"), green after restore. Full suite green: `python -m pytest tests/unit/test_content_critic.py tests/unit/test_editorial_pass.py` = 128 passed.

## BUILD 2 — brain + fix-and-deliver chain (branch `build1-content-critic`)

Build 2 wires the conversational brain onto a persisted deck and makes slide-level fixes reach the
user (regenerate → render → upload → deliver → persist). Build 1 content critic hard-stop is
preserved as the final authority: Stage 5a inserts brain escalation before it; unfixable fabrication
still refunds honestly.

**Revised stage order (plan change 2026-06-25):**

| Stage | Status | What |
|-------|--------|------|
| **0** | **DONE** `79fd1de` | Deck persistence (`save_deck`/`get_deck`, migration 003 `unique(project_id)`, orchestrator `_persist_deck` hook) |
| **1** | **DONE** `ff1558e` | Tool-calling transport (`generate_with_tools`, signature-preserving history serialization, `gemini_tools.py`) |
| **2** | **FOLDED → Stage 5** | Critic findings → brain rewire (see plan change below) |
| **3** | **DONE** `45552d5` | Fix-and-deliver chain — `apply_fixes_and_render` (batch fix → persist once → render once → handler re-stash/re-deliver) |
| **4** | **DONE — pending gate** | Bot session surface — DB-backed brain session, chat loop above the orchestrator, code-side approval gate, per-tier fix counter, delivery-boundary guard |
| **5a** | **DONE** (pending gate + Iko prompt fill) | Real Gemini brain — Way 1 critic escalation, Way 2 chat edits, live seam, feed-back history |
| **5b** | pending | Memory/retrieval, Gemini context caching, proactive suggestions, Iko character prompts |

### Stage 0 — deck persistence — DONE `79fd1de`

- `DatabaseClient.save_deck` / `get_deck` — one `decks` row per project via upsert on
  `decks_project_id_key` (`supabase/migrations/003_decks_unique_project.sql`).
- `PresentationOrchestrator._persist_deck` — called from `run_full_pipeline` after
  `resolve_images`, before `render` (best-effort, non-fatal).
- **Gate:** `python scripts/gate_build2_stage0.py` — green on droplet. Proves: exactly one row per
  project; `DeckSpec` round-trips equal through `deck_json`; second `save_deck` updates in place
  (`created_at` unchanged, `updated_at` advanced).

### Stage 1 — tool-calling transport — DONE `ff1558e`

- `generate_with_tools` — single-turn primitive for Gemini tool calls.
- Signature-preserving history serialization (`serialize_history` / `deserialize_history`) so
  `thought_signature` bytes survive store-and-reload.
- `gemini_tools.py` — tool schema + wiring surface for the brain loop.
- **Gate:** `python scripts/gate_build2_stage1.py` — live gate passed against real
  `gemini-3.1-pro-preview`: real 388-byte `thought_signature` survives serialize→reload
  byte-for-byte; negative control (dropped signature → HTTP 400) proves it is load-bearing.
- **Codex fix (same commit):** degraded finish reasons no longer masquerade as clean terminal turns —
  `_CLEAN_FINISH_REASONS={STOP, UNSPECIFIED}` allowlist; anything else raises.

### Plan change — Stage 2 folded into Stage 5 (NOT a scope cut)

**Original Stage 2:** critic findings → brain rewire (structured findings channel from content critic
to the brain so it can fix instead of refund).

**Decision (2026-06-25):** folded into Stage 5, not built as a separate earlier stage.

**Reason:** the critic-reports-to-brain channel has no consumer until the brain exists (Stage 5), and
recon proved it cannot be tested in isolation — building it earlier would create an untestable seam
maintained across stages doing nothing. The current content-critic hard-stop stays as the working
invariant gate until Stage 5 wires the brain to consume structured findings and fix instead of
refund. The rewire is the same work as wiring the brain; it lands with Stage 5.

### Stage 3 — fix-and-deliver chain — DONE `45552d5`

Orchestrator method chaining existing primitives (`regenerate_slide` → `save_deck` → `render` →
handler `_stash_outputs` / re-deliver). Gate-driven without the brain. `apply_fixes_and_render`:
atomic batch (a raising fix never half-applies), persist once before render once, best-effort
deck persist surfaced into render warnings.

### Stage 4 — bot session surface — DONE (pending droplet gate), branch `build1-content-critic`

The MACHINERY the Stage 5 brain runs in, driven by a scripted stub (no real brain — that's Stage 5).
One coherent uncommitted change set:

- **DB-backed session** (`migration 004_brain_sessions.sql`, `packages/bot/sessions/`): one row per
  project (`unique(project_id)`), recoverable by `project_id` ALONE so no restart orphans it. Holds
  the serialized tool-calling history (Stage 1 `serialize_history`), the live `SourceProcessingResult`
  the fix tool re-grounds against (split: light `sources_json` vs heavy write-once `figures_json`,
  lazy-hydrated only when a fix fires), the deck ref (via `get_deck`), the code-side approval state +
  durable `pending_action_json`, the per-tier fix counter, and analytics-only spend. `findings_json`
  reserved for Stage 5.
- **STEP-0 serialization landmine fixed:** `SourceFigure.data: bytes` needs
  `ser/val_json_bytes="base64"` (`core/models/source.py`) — pydantic's default utf8 raises on real
  PNG/JPEG. Proven byte-for-byte (probe, now a permanent test).
- **Chat loop ABOVE the orchestrator** (`presentation_flow.py`, new `talking_to_brain` state): load
  session → one stub-driven turn → dispatch the fix tool to `apply_fixes_and_render` (Stage 3,
  unchanged) → re-stash → persist. Per-project `asyncio.Lock` serializes turns + the approve callback.
- **Approval gate (code-side, never model-self-granted):** `requires_approval` keys on the chat-loop's
  `user_initiated` PROVENANCE, never the model's `TurnAction` label or batch size — a real button is
  the only authorization. `awaiting_approval` state + inline approve/reject.
- **Per-tier FIX COUNTER (replaced a dollar cap):** `SESSION_FIX_LIMITS` premium 3 / standard 2 /
  basic 1 (PLACEHOLDER values — real editing-allowance economics are a Stage 5 decision; counter is
  model-independent so it survives a Sonnet→Gemini editorial-seat migration). An integer the model
  can't influence; `fixes_used` bumped only after a DELIVERED fix.
- **Delivery-boundary guard:** count consumed AND success reported IFF the fix produced ≥1 deliverable
  rendered file. A zero-file render (every format failed; `render()` warns rather than raises) →
  `RENDER_FAILED`: no count consumed, prior `_PROJECT_CACHE` downloads preserved, no false success.
- **Tests:** `tests/unit/test_brain_session.py` (session round-trip incl. byte-for-byte figures,
  restart recovery by project_id, approval provenance, counter limits, failed/zero-file fix doesn't
  consume, concurrency). **Gate:** `scripts/gate_build2_stage4.py` (apply migration 004 first).
- **Reviewed across rounds by Codex:** STEP-0, the self-grant gate, the budget→counter swap, and the
  delivery boundary all closed and confirmed.

### Stage 5a — real brain, live and working — DONE (pending gate + Iko prompt fill)

Stage 5a wires the REAL brain into the Stage 4 machinery on two paths. Editorial seat stays Sonnet
4.6 (unchanged). Prompt **slots** in `packages/core/brain_prompts.py` are placeholders for
`BRAIN_STANDARD` / `BRAIN_IDENTITY` / `BRAIN_ORCHESTRATOR` until Iko fills them — do NOT run the live
gate until those are real text.

- **Shared loop** (`packages/core/brain_loop.py`): `run_brain_loop` over the sole `edit_slides` tool.
  Fix-exit discipline — the tool is a REQUEST; applying fixes is always the caller's guarded job
  (Way 2 → `_dispatch_fix`; Way 1 → Sonnet `regenerate_slide_content` + re-critique). Iteration cap
  `BRAIN_LOOP_MAX_ITERATIONS=6` (runaway backstop).
- **Way 2 (user edits):** `GeminiBrainDriver` replaces the scripted stub at
  `_brain_driver()` (`presentation_flow.py`). User taps **Edit with AI** (`reviewing_output` →
  `talking_to_brain`) or chats in `talking_to_brain`; fixes route through the existing counter /
  approval / delivery-boundary guards unchanged.
- **Way 1 (critic escalation):** `_enforce_content_critic` inserts
  `_attempt_brain_grounding` BEFORE the existing hard-stop (`editorial.py`). Brain fix pass → Sonnet
  regen → re-critique; `BRAIN_ESCALATION_MAX_ATTEMPTS=1`. Hard-stop still fires if findings survive
  — worst case is exactly today's refund; no fabrication ships.
- **Live seam:** `run_full_pipeline` returns `PresentationPipelineResult(render, sources)`;
  `start_generation` calls `_open_brain_session` → `create_session` after delivery (best-effort;
  downloads work even if session create fails).
- **Feed-back seam:** `_append_fix_result` answers every `edit_slides` call part with a
  `function_response` after dispatch (delivered / exhausted / render-failed / discarded) so the next
  turn's history is coherent (no dangling call → no Gemini 400).
- **Tests:** `test_brain_loop.py`, `test_brain_driver.py`, extended `test_brain_session.py` /
  `test_editorial_pass.py` (Way 1 escalation + hard-stop divergence). **Gate:**
  `scripts/gate_build2_stage5a.py` — mechanical wiring only; quality is Iko's eyeball after prompts
  are filled.

**Codex review fixes (closed in 5a):**

1. **`fix_call_count` / `PendingAction.call_count`** — one `function_response` per `edit_slides` call
   part (multi-call turns answered fully).
2. **Feed-back seam** — `_append_fix_result` on every dispatch outcome, including approval reject.
3. **Signed-prefix context** — deck roster + claims injected once on first turn; later deck changes
   reach the model only via `edit_slides` function_responses (never rewrite signed history).
4. **Approval gate dangling calls** — parked `edit_slides` calls answered on reject so chat can
   resume without a 400.

### Stage 5b — deferred (NOT in 5a)

- `BRAIN_RETRIEVAL` / `BRAIN_MEMORY` prompt slots + retrieval tools over sources/history.
- Gemini `cached_content` wiring for the ~15k static system block.
- Way 3: brain's unrequested proactive suggestions (`user_initiated=False` path).
- Iko fills `BRAIN_STANDARD` / `BRAIN_IDENTITY` / `BRAIN_ORCHESTRATOR` (character + standard).

### 2026-07-03 — Phase 0 live-UX fixes (pre-5b consolidation, branch `build1-content-critic`)

Executed against a web-drafted brief whose Phase 0 premises were checked against HEAD + the
live droplet FIRST (droplet container verified built from `a1310f1`). THREE of the brief's
claims were dead at HEAD and are recorded here so they are not re-chased: (1a) "Edit with AI
entry fires a paid brain turn" — FALSE, `edit_with_ai` runs only `load_session` and sends the
static invite; (1b) "null reply triggers `presentation_chat_files_redelivered`" — that event
does not exist in the repo; null reply → `labels.error_generic`; (1c) "FSM never reaches
`talking_to_brain`" — FALSE, entry sets it and `chat_turn` listens on it (run6.log shows a
live handled Way 2 fix turn). The REAL "Update not handled" cause: `reviewing_output` had no
message handler at all.

WHAT SHIPPED (5 source files + 2 test files):
- **P0-1 busy guard + typing** (`presentation_flow.py`): `chat_turn` drops-with-reply
  (`labels.brain_busy`) when the per-project lock is held — never queues a stale edit;
  `ChatActionSender.typing` wraps the brain turn AND `approve_redeliver`'s fix-apply.
  Codex-flagged waiter-queue race ACCEPTED with documented justification (guard comment):
  chat_turn (`talking_to_brain`) and approve (`awaiting_approval`) are mutually exclusive FSM
  states, and a turn racing a freshly parked action is stopped by the `pending_action` guard
  in `_run_chat_turn`.
- **P0-2 fallback router** (NEW `handlers/fallback.py`, registered LAST in `app.py`): every
  unmatched callback (stale button) is answered with a toast — spinners never hang. Language:
  FSM data → stored user profile (`get_user_by_telegram_id`) → uz; DB errors suppressed so
  the toast always answers (Codex RISK fix).
- **P0-3 review-screen nudges** (`presentation_flow.py`, `labels.py`): `reviewing_output`
  message handler nudges to the Edit button (`edit_nudge`) or says editing is unavailable
  (`edit_nudge_unavailable`, Codex BUG fix — never point at a button the keyboard omits);
  `can_edit` stashed in FSM data at delivery; `talking_to_brain` non-text handler
  (`brain_text_only`). Zero model calls on all three.
- **P0-4 cancel scoping** (`article_flow.py`): stateless `cancel_flow` handler was shadowing
  presentation-flow cancels (article router registers first) and popping the WRONG module's
  `_PROJECT_CACHE`; now scoped `StateFilter(ArticleStates)`. The presentation `cancel` at
  reviewing_output (previously dead code — article's always won) is now live.
- **Labels ×5** (`brain_busy`, `stale_button`, `edit_nudge`, `edit_nudge_unavailable`,
  `brain_text_only`) in all four packs (uz/ru/en/kaa).

VERIFIED locally: `python -m pytest tests/` full suite green (1483 passed / 32 skipped; +11
new behavior tests vs the pre-Phase-0 baseline 1472/32, incl. a dispatcher-level `feed_update`
regression proving article-cancel no longer swallows presentation cancels, red pre-fix);
ruff check + format clean on all changed files (the 3 pre-existing SIM105 in payment_flow.py
untouched); pyright 0/0/0. Codex adversarial review round 1: 1 BUG + 2 RISK (all closed or
accepted-with-argument above) + clean bill on router order, cancel orphaning, ChatActionSender
semantics (aiogram 3.28.2), test realness; round 2 re-review on the amendment recorded in the
gate report.

NOT verified locally (Iko's live probes gate DONE): real Telegram typing indicator, toast
behavior, busy-drop UX, and the full Way 2 edit loop live. NOTE for the deploy check: the
container will still report `(unhealthy)` — the polling-mode healthcheck is a Phase 1 item
(nothing binds :8080; Dockerfile curl probe cannot pass by construction).

### 2026-07-04 — HOTFIX: union-of-2 critique verification (pre-Phase-1, branch `build1-content-critic`)

WHY (live evidence, project `bd5c0c6c`): the adversarial critic SAMPLES findings per pass —
three verified re-critiques returned largely disjoint sets; a citation fabrication present
from generation surfaced only on pass 3. The escalation brain went 11/11 on instructed fixes
(prompt is DONE, stop tuning it) and the run still refunded correctly, because each clean-pass
check sampled new findings. Consequence: "one clean pass" was weak evidence for BOTH the
escalation termination AND the main flow's ship decision (the six-in-seven decks that never
escalate). The fix targets discovery, not the brain.

WHAT SHIPPED (editorial.py + test_editorial_pass.py only):
- `_critique_unioned` — two independent `critique_deck_adversarially` passes run concurrently
  against the SAME deck state, findings unioned (dedupe key `check_id + slide_id + normalized
  message` — message in the key so two different fabrications on one slide both survive);
  `llm_verified` True only when BOTH passes verified; logs `editorial_critique_union` with
  pass1/pass2/union failure counts + `pass2_new` (the sampling-rate observable feeding the
  Phase 1 editorial-grounding finding).
- Wired at EXACTLY three sites: (1) escalation entry — one extra pass unions ADD-ONLY into the
  incoming (state-consistent) findings, an unverified extra is ignored; (2) each escalation
  re-critique; (3) the main flow's re-judge (the ship decision). First-pass discovery critique
  stays single (repairs follow it anyway). Never unions across deck states.
- UNCHANGED: `BRAIN_ESCALATION_MAX_ATTEMPTS=3`, the hard stop as final authority, all prompt
  text, EDITORIAL_SYSTEM. Unverified-either-pass → the existing preserve-prior discipline.

COST DELTA (arithmetic): clean first pass (common case) +0 calls / $0.00; generation with
accepted repairs +1 critique call; fully escalated generation +4 critique calls (entry +1,
3 re-critiques +1 each) ≈ +$0.12–0.32 at observed Gemini critique rates. Cap unchanged.

VERIFIED locally: full suite green (counts in commit); ruff + format clean on both changed
files (LF); pyright 0/0/0. 11 new tests pin the union contract (union dedupe; one-clean +
one-flagging → NOT clean; either-unverified → prior findings stand at every site; escalation
termination requires a clean UNION; entry extra pass reaches the brain brief; unverified entry
extra leaves incoming unchanged). 8 existing scripted-critic tests updated from the old
"one critique per verification" pin to the union call pattern — no behavioral assertion
weakened. Codex adversarial review round 1 (mandated scope: no finding seen by either pass
escapes the hard stop; unverified handling cannot clear known findings) found THREE real BUGs,
all fixed + regression-tested: (1) severity was absent from the union key — a pass-1 WARN
could shadow an identical-message pass-2 FAIL (hard-stop escape); severity now in the key;
(2) site 3's residual still ran through the old `(slide_id, check_id)`-keyed
`_dedupe_hard_stops`, collapsing two different same-slide fabrications the union had
preserved; residual now merges via `_union_critic_findings` and `_dedupe_hard_stops` is
DELETED; (3) site 3's unverified branch discarded discoveries made by the VERIFIED half of a
partially-degraded union; it now unions `first_hard` WITH the rejudge's hard stops (add-only
both branches). Round 2 confirmed 1+3 closed and sharpened 2: the TRUE discriminator
(`evidence.unsupported_token`) was discarded before `AuditCheckResult`, so two same-slide
fabrications sharing one GENERIC model message still collapsed — fixed by
`_message_carrying_token` in content_critic.py (`_gate_source_grounded` now guarantees the
token appears verbatim in every source-grounded message, trimmed to the 500-char cap; the
union key docstring documents the dependency). Round 3 confirmed the class closed for generic
messages and caught the last residual: containment-checked appending let a short token hide
inside a longer one already in the message ("1987" inside "1987-1991") — fixed by making the
suffix UNCONDITIONAL (every source-grounded message ends with `[unsupported: "<token>"]`;
distinct tokens now always yield distinct union keys; round 3 had already verified the append
branch itself collision-free, and no downstream consumer parses the message format). Known
accepted edge (documented
in `_attempt_brain_grounding`): preserve-prior findings from a degraded verification describe
the pre-repair state; a brain instruction against changed text may be ineffective — tolerated
because delivery still requires a clean union on the CURRENT state (worst case refund).

PHASE 1 GAINS A FINDING (do NOT touch EDITORIAL_SYSTEM until decided): quantify from the seven
sCO2 run transcripts what fraction of critic findings are true-domain-knowledge-not-in-source
vs invented specifics; the `editorial_critique_union` log feeds this going forward.

5b PRIORITY BUMP (from the live probes): session re-entry after restart — the P0-2 toast fired
because a deploy restart wiped MemoryStorage FSM, orphaning every delivered deck's Edit button;
`brain_sessions` survives by design, only the FSM re-entry path is missing.

### 2026-07-04 — PHASE 1: audit + consolidation (branch `build1-content-critic`)

Executed after the human's Phase 0 sign-off (Way 2 verified live end-to-end; the union hotfix
converted a would-be refund into a delivery on a paid run — 4 hard findings at escalation
entry, 5 after fix batch 1, 0/0 under double verification after batch 2, delivered).

WHAT SHIPPED:
- **Stage 3 failure contract** (`presentation_orchestrator.py`): `run_full_pipeline` raises
  `_OrchestratorError("render")` when a render yields ZERO files (was: `download_ready`
  announced over an empty download map) — rides the existing handler catch (honest
  step-named message, status `failed`, refund; new handler test pins the refund fires).
  `apply_fixes_and_render` raises `_OrchestratorError("persist_deck")` BEFORE render on a
  `save_deck` failure (was: warn-and-render, which delivered files a stale DB deck didn't
  reflect — the next `load_session` would silently resurrect the pre-fix deck). Partial
  render success (≥1 file) still returns; `render()`'s per-format degrade unchanged. The
  edit-path exception route verified: one `function_response` per parked call appended
  BEFORE session persist, allowance not consumed. Both tests that pinned the old contract
  rewritten (incl. the RUN_E2E_TESTS-gated one — updated by code-read, not executed locally).
- **Polling healthcheck** (`middleware/liveness.py` NEW, `app.py`, `Dockerfile`,
  `docker-compose.yml`, `scripts/healthcheck.py` NEW): a Bot SESSION middleware touches a
  liveness file after every successful Telegram API call (`getUpdates` fires each long-poll
  cycle, so mtime proves live Telegram connectivity, not just a running process); Docker
  HEALTHCHECK swapped from the dead `curl :8080/health` (unhealthy-by-construction in
  polling mode) to a file-age probe with `--start-period=60s`; dead `8080:8080` compose
  mapping removed. Container must report HEALTHY after next deploy.
- **Caching observability, NO wiring** (`gemini.py`, `scripts/probe_gemini_cache.py` NEW):
  `_extract_usage` → `_TokenUsage` NamedTuple incl. `cached_input_tokens`
  (`cached_content_token_count`, defensively read; a SUBSET of input tokens — cost still
  bills full input, discount is 5b); both `gemini_call_complete` log sites carry it — every
  brain/critic call now shows whether implicit caching is already firing. The probe script
  (env-gated, gate-run on the droplet) creates an explicit cache with system_instruction +
  tools on `gemini-3.1-pro-preview`, runs one generation against it, prints usage, deletes
  the cache. Production `cached_content` wiring remains 5b scope.
- **Brain prompt: preservation scope** (`brain_prompts.py`, Iko-supplied text verbatim):
  BRAIN_TOOL_DESCRIPTIONS instruction-quality section now requires additive requests to pin
  what stays ("add an image" ≠ license to rewrite the title) — closes the live Way 2
  rewritten-title defect; the regen executor already proved 11/11 on exact-text instructions.
- **Hygiene**: stale docstrings corrected (`brain_prompts.py` "placeholders" claim;
  `sessions/store.py` closed wiring-gap NOTE); F541 in `proof_build1_critic.py`; logs
  archived to gitignored `logs/`; `.gitignore` gains `*.log`/`logs/`/generalized zip; the
  nine brain-prompt source docs extracted from `files (6).zip` into `docs/prompts/` and
  committed (the brain's character sources now live in the repo, not a zip + chat session).
  Fix counters (3/2/1): already documented as placeholders — closed, no change.

EDITORIAL-GROUNDING FINDING (analysis only, EDITORIAL_SYSTEM untouched — decision is Iko's):
message-level classification of every extractable critic finding (4 of the 7 sCO2 runs
survive at finding level; container rebuilds discarded the rest): ~21% TRUE-domain-knowledge
-not-in-source, ~50% invented specifics (43pp hard hallucinations: fabricated URLs, counts,
"superfluid", 0.80-vs-0.56 MW; 7pp benign/derivable), **~29% CRITIC FALSE POSITIVES — text
verbatim in the paper** (turbine, `47(6), 647-661` reference details, density/viscosity,
Table-1 values) flagged because `_token_present_in_claims` grounds ONLY against the thin
claim list, never chunks/tables/references (`content_critic.py:528-532`, code-verified).
The headline "fabricated journal issue number" from the refunded run is in this class —
verbatim at `sco2_source_fixture.py:207`. Consequence: at least two ungrounded/refund
outcomes were partly driven by source-faithful text. Hardening EDITORIAL_SYSTEM addresses
only ~1/5 of the leak; the two bigger levers are generation-side invented specifics and the
critic's claim-coverage gap (a hard-stop semantic change — flagged for Iko, NOT built).
Union observables (1 run): pass2_new/union ≈ 0.22 — the second pass earns ~1-in-5 net-new
hard findings; `editorial_critique_union` + `cached_input_tokens` logging now accumulate
per-run data.

VERIFIED locally: full suite green (counts in commit); ruff clean repo-wide except the 3
documented pre-existing payment_flow SIM105s; pyright 0/0/0 incl. both new scripts; LF.
Consolidated Codex review recorded in the gate report. NOT verified locally: real Docker
healthcheck transition + probe script live behavior (droplet gate), the RUN_E2E-gated test.
DEPLOY HELD by design: a container rebuild wipes MemoryStorage FSM and would orphan the
live probe session — deploy fires on Iko's probe-done signal, then stage4+stage5a gates.

### 2026-07-04 — Phase 1 deploy + gate triage (branch `build1-content-critic`)

**Deploy:** pushed `7111769`→`f2184d0`→`7dc8cd3`; droplet @ `7dc8cd3`; bot **`Up (healthy)`**
(first time — polling healthcheck). Cache probe (`scripts/probe_gemini_cache.py`): **PASS** —
explicit `cached_content` + tools on `gemini-3.1-pro-preview`; **10,660 cached tokens** on the
brain system+tools block → D5 wiring approved.

**First gate run (pre-triage):** Stage 4 **FAIL** 1 check; Stage 5a **FAIL** 1 check. Both were
**gate-script bugs**, not product regressions:

1. **Stage 4 `history persisted (user+model)`** — **GATE WRONG.** Gate asserted
   `len(history)==2` (`gate_build2_stage4.py:165`, pre-5a contract). Product correctly appends a
   third turn via `_append_fix_result` after `_dispatch_fix` (`presentation_flow.py:1078-1087`,
   `gemini_tools.py:113-133` role=`user` function_response). Stage 5a gate already asserted this
   seam (`gate_build2_stage5a.py:203-208`). **Fix:** gate only (`db48bcb`) — now asserts
   user+model+fix_response (len=3, `delivered=True`).

2. **Stage 5a `recritiques=0`** — **GATE WRONG.** `_EscalationWatcher` matched
   `getMessage()=="editorial_brain_escalation_complete"` and read `getattr(record,"recritiques")`
   (`gate_build2_stage5a.py:113-117`), but product logs via
   `logger.info("editorial_brain_escalation_complete %s", json.dumps({...}))`
   (`editorial.py:1217-1236`) — same Python-formatter trap fixed in `9133074`. Container logs
   showed `recritiques: 3`, ~$0.51 escalation spend; watcher captured zero. **Fix:** gate only
   (`db48bcb`) — parse JSON suffix; strengthen with union-of-2 observables
   (`editorial_critique_union`, `editorial_brain_escalation_recritique`).

**Re-gate after `db48bcb` (2026-07-04, droplet):**
- `gate_build2_stage4.py`: **PASS** (all checks incl. history user+model+fix_response); session
  editing spend **$0.0560**; fixes used 3.
- `gate_build2_stage5a.py`: **PASS** (Way 2 + Way 1); recritiques=3; union logs=3;
  pass1_verified+pass2_verified on all unions; escalation ~$0.515; Way 2 edit cost ~$0.0601.

**Phase 1 status:** deployed, container healthy, droplet gates green.

**Live probes (2026-07-04):** transcript + log forensics in `docs/probes/2026-07-04.md`.
Project `9330c308-6e78-4a73-8ed0-6aa2d8f790b2`.

| Probe | Result |
|-------|--------|
| Floor test ("efficiency improves 40%") | **Transparency defect, not fabrication** — brain instructed **44%** (grounded, `sco2_source_fixture.py:178`); user saw label-only fix message; explanation surfaced two turns later on reply path |
| Bait (retitle → pushback) | Partial (pushback OK; insist not completed) |
| Small edit (caption slide 5) | Pass |
| Exhaustion / busy reply | Not run (~1 edit left) |

**Mechanism (logs):** instruction layer substituted 44% not 40%; fix-turn handler
drops brain voice (`brain_loop.py:246`, `presentation_flow.py:1138-1140`). **Not**
mechanism 3 (downstream regen correction). **Transparency fix shipped** (`2ed7cb9`,
deployed `f87a41a`): fix-turn parallel model text now surfaces before the
`edit_applied` label. Prompt paragraphs (substitute-and-announce) remain Monday
drafts. Slide 11 forensic: verdict **(a)** — 44% in `speaker_notes` only.

### DEFERRED TO WEB SURFACE (locked — not skipped; bot path unaffected)

Three correctness items for the **unbuilt** web/R2 consumer. None affect the bot delivery path the
brain drives (Telegram downloads read `_PROJECT_CACHE` local paths). Pick up when the web surface
build starts.

1. **PUBLIC SHARE LINK** — not implemented (SPEC.md:453 only: `nashr.ai/p/{project_id}`). No
   route/handler/URL-builder in repo (`packages/web/` is a placeholder). When built: public URL must
   point at a stable R2 key, not a stale cached artifact, so a brain-driven fix reaches link users
   (see item 3 for current title-derived key instability).

2. **`generated_files` RE-REGISTRATION UPSERT** — `create_generated_file` is insert-only
   (`database.py:283-301`); no unique on `(project_id, file_type)`. Re-delivery appends duplicate
   rows. **Harmless today:** download callbacks read `_PROJECT_CACHE`, not `generated_files` — rows
   are unread. Needed when a consumer (web surface) queries `generated_files`; then upsert hygiene
   like decks got in Stage 0.

3. **R2 KEY TIED TO DECK TITLE** — `_upload_rendered` keys R2 objects by
   `sanitizeFilename(deck.title)` via `FileStorage.generated_key` (`storage.py:227-230`), not a
   stable per-format name (e.g. `presentation.html`). A title-changing fix (hero regen) uploads to
   NEW R2 keys and orphans old objects. **Harmless for bot path** (downloads use local cache; R2 is
   best-effort). When web surface ships: use stable filenames or delete-old-on-overwrite so the
   public link serves the updated deck.

## FUTURE HARDENING — Stage 3 failure contract (pre-existing; NOT a Stage 4 blocker)

Two pre-existing Stage 3 robustness items, surfaced (not introduced) during the Stage 4 delivery-
boundary review. Both swallow internal failure rather than raising, so callers cannot distinguish
success from silent failure. Stage 4 handles the *edit-path* consequence (see delivery-boundary
guard / `RENDER_FAILED`); the underlying contract is still loose. Bundle as one future task:

1. **`render()` returns a zero-files result** — it records per-format failures as warnings and
   continues (`presentation_orchestrator.py:721`) rather than raising on TOTAL failure. Exists on
   BOTH the first-gen path (`run_full_pipeline → render`, its own delivery handling) and the edit
   path (now caught as `RENDER_FAILED` in `_dispatch_fix`).
2. **`apply_fixes_and_render` swallows internal `save_deck` failure** — surfaces it into render
   warnings and returns the working deck (`presentation_orchestrator.py:659`) rather than raising,
   so a persist failure is invisible to the caller.

**Self-healing double-failure edge (Codex-flagged, do NOT fix in Stage 4):** if (1) the internal
`save_deck` fails AND (2) render also produces zero files, then `session.deck` (in-memory, advanced)
and the DB deck (not advanced) disagree — but the next `load_session` reads `get_deck` (the DB
version), so it self-corrects on reload. Requires two simultaneous failures and is pre-existing.

**Bundle:** "Stage 3 robustness — `render` and `save_deck` swallow internal failures rather than
raising; harden the failure contract so callers can distinguish success from silent failure."

## WHEN SCALING — DEFERRED: editorial system-prompt caching (refactor + cache wiring)
Deferred from the 2026-06-21 prompt-caching work (which wired drafter + planner + design only).
TRIGGER TO REVISIT: sustained concurrent deck traffic (so cross-deck cache reads actually land
within the 5-min TTL) AND capacity to A/B editorial output for equivalence. Until then this stays
out of the active blast radius — the taste-engine core is not worth touching for a benefit that
does not exist at low volume.

WHY EDITORIAL DOES NOT CACHE TODAY: `EDITORIAL_SYSTEM` (prompts.py) is a `.format()` template that
injects five per-deck scalars — arc_description, emphasis_phase, target_count, title_style, language
(prompts.py:457-461) — BEFORE its ~3.6k-token output schema. Filled at editorial.py:824 (generation)
and editorial.py:654 (repair). So the cached prefix breaks every deck (≈0 cross-deck hit rate), and
because repair uses a different target_count, repair cannot even hit the generation cache within one
job. (Contrast: PLANNER_SYSTEM and SECTION_DRAFTING_SYSTEM are raw static constants and cache as-is.)

THE REFACTOR (when undertaken): relocate those five scalars out of EDITORIAL_SYSTEM into
EDITORIAL_USER and EDITORIAL_REPAIR_USER — language already lives in the user template at
EDITORIAL_USER:512 and is currently DUPLICATED. EDITORIAL_SYSTEM.format() then keeps only the two
STATIC substitutions (slide_type_descriptions, word_limits) → byte-stable across decks. Move the
kwargs from the system .format() to the user .format() at editorial.py:824 and :654. Consequence:
generation and repair share an identical system → repair hits the generation cache within one job,
and decks share it across the TTL. This is also a structure/correctness fix independent of caching:
per-call task parameters belong in the user message, not in a system prompt.

GATE (mandatory — this change is semantic, not transport): run the editorial pass on representative
decks at temperature 0 BEFORE and AFTER the refactor via the local live harness (dotenv.load_dotenv()
+ runpy; needs ANTHROPIC_API_KEY + Vertex ADC; modeled on scripts/proof_planner_phase1.py and
scripts/gate_a_emphasis_provenance.py) and diff the materialised slides. Equivalent → keep and add
cache="5m" to the editorial complete() calls (editorial.py:869,880). Any regression → revert the
refactor ONLY; drafter/planner/design caching is independent and unaffected.

## PLAN OF RECORD — full scope (do not flatten)

This is the un-abbreviated roadmap. Future sessions read it from here so detail is not lost to
compaction.

### PLANNER PHASES

- **Phase 1** — shipped.
- **Phase 1.5** — shipped.
- **Phase 2** — shipped.
- **Phase 3** — adversarial deck-quality critic/judge with routing authority (the "thinker").
  Sonnet, NOT Opus (per `llm-integration` rule).
- **Phase 4** — prompt caching — **DONE** (merged to main @ `d9691b6`, proven live on droplet:
  drafter sequential cache reads; design `count_tokens` = 1145 > 1024 floor).
- **Phase 5** — taste as loadable skills.

### PART B — 4 chunks (all remain; do not reduce scope)

#### 1. VISUAL SYSTEM (full sCO₂ aesthetic — three parts; NOT "unlimited images" alone)

**a) Cohesion families**

Five seed families: editorial-engraving, high-contrast-press, sepia-educational, risograph-punk,
technical-blueprint. Family locked deck-wide (palette, typography, texture, accent); per-slide
archetype + image strategy vary within family-compatible rules.

**PRINCIPLE:** cohesion and variety are **separate axes** — do not conflate them.

**b) Three image slots — source-as-inspiration, NOT source-as-copy**

Slot existence is **structural** (layout defines it, not a per-image judgment). Abstain is the
floor for anything not cleanly sourceable. Every image restyled into the deck's visual language;
never dropped in raw.

- **(i) Portrait** — Wikidata → Commons, identity + license gating (PD / CC0 / CC-BY only;
  reject CC-BY-SA for ShareAlike contamination). Restyled mechanically into the deck family (SVG
  filters: stipple, halftone, engraving, duotone). Recognizable features preserved. **NO AI likeness
  of real people.** Living people abstain by default.
- **(ii) Object/concept figure** — first-class standalone field (**NOT deferred**), AI-generated.
- **(iii) Background/atmosphere** — AI-generated.

**c) Per-slide image router + scrim**

Chooses portrait / object-figure / background / none per slide. Image-quota **POLICY by tier** (NOT
hardcoded caps):

- **Paid** — unlimited subject to quality; batch to cut cost.
- **Mid** — 5.
- **Standard** — 1–2 at highest-value slots.

**KILL** the hardcoded per-tier cap currently in `image_pass.py`.

#### 2. GROUNDING / MOAT

Web + website-fetching OCR sourcing — pull and ground on sources fetched from the web/URLs (turn a
page into usable markdown), not just uploaded files. Depth of grounding is the moat.

#### 3. CONVERSATIONAL EDIT

Iterate a generated deck through chat.

#### 4. FONTS

Real typographic control — decorative/display fonts ("letter styles") keyed to the cohesion family.

### ALSO ON THE LIST (NOT deferred)

- **"Add details" / AI Fill escape hatch** — instruction to add detail / fill a section.
- **IEEE / article quality improvements.**

### ENGINE ARC (immediate front — sits ahead of the Part B tail)

1. **Terminal-policy fix (urgent, ships first):** audit-fail known to orchestrator; project NOT
   marked `ready`; honest user message (not "An error occurred" on empty download).
2. **Intent channel + intake advisor at the front** — the intent layer **extends** the existing
   interview/mini-app to capture style/format intent alongside existing fact-gathering. Different
   axes: interview asks "what facts am I missing"; intent asks "what should this look like and do."
3. **Per-slide generation restructure** — planner emits sections with slide slots; each slide an
   addressable regenerable unit from a slide brief carrying deck cohesion + neighbor constraints.
4. **The thinker** — Phase 3 judge (above).
5. **Unlimited images** — via the quota **policy** above (not a hardcoded cap).

### REMAINING L2 (before L3)

- **Per-locale length budget** — kills language-blind `WORD_LIMITS` at root (design change; its own
  pass).
- **Phase 3 judge** — auditor → routing judge (see Phase 3 above).

## 2026-07-07 — 5B-Q5b WIRED: explicit Gemini context cache for the Way 2 brain (branch build1-content-critic)

SUPERSEDES the 2026-07-04 "Caching observability, NO wiring … remains 5b scope" line —
production wiring now EXISTS, env-gated. `packages/core/gemini_cache.py` (NEW):
BrainContextCache over `assemble_brain_system()`+`build_edit_slides_tool()`, TTL 3600s
with 120s client-side margin, 30s create timeout, create-failure disables for process
lifetime (re-checked under the lock), PROCESS-WIDE singleton in sessions/driver.py (a
per-driver cache would be created+consumed once per message — worse than uncached).
`generate_with_tools(cached_content=)` omits system/tools/tool_config on cached calls
(API mutual exclusion); non-default tool config (Way 1 forced-ANY) bypasses — Way 1 stays
uncached by design. `run_brain_loop(context_cache=)`: cached-call APIError/TimeoutError
invalidates and retries uncached WITHOUT consuming an iteration; cache failure is a cost
regression, never a user-visible failed turn. Cost note: `gemini_cost_for` bills cached
tokens at FULL input rate — a deliberate conservative ceiling until confirmed cache rates
come from GCP billing. Env: `GEMINI_BRAIN_CACHE` default OFF in code, ON in compose.

REVIEWED: Codex rounds 1-2 (quota died before round 3) + a 5-lens Codex panel
(correctness/security/contracts/concurrency/spec — reports in the session scratchpad);
all 6 panel findings fixed and test-pinned (in-lock failure re-check, create timeout,
timeout fallback, non-default-tool-config handle skip, log suffix not full cache name,
this BUILD_STATE correction). NOT VERIFIED (VM gate, P0): a live cached call —
`cached_input_tokens > 0` on a Way 2 turn is the gate observable.

ALSO ON THIS BRANCH, SAME SESSION (parked for their own panel reviews, see
docs/AUTORUN_2026-07-06.md): Vertex Claude transport COMMITTED 6ab511a (LLM_TRANSPORT,
lazy client, vertex_model_id allowlist); migration 005/005b WRITTEN not applied;
identity preflight script WRITTEN not run; packages/api auth surface + packages/web
skeleton BUILT, suite 1589 green at time of writing.

## 2026-08-03 — Vertex 429 resilience + per-call telemetry (branch build1-content-critic)

Three items, one per commit, driven by live-run evidence of two distinct 429 classes on
gemini-3.1-pro-preview (12:07 run died on nameless RESOURCE_EXHAUSTED after 3 retries;
12:37 run survived the same policy by luck).

1. **429-aware backoff** (57cbca8, `packages/core/gemini.py` `_generate_with_retry`):
   class A = 429 whose message names a quota metric (`_is_quota_metric_429`: substring
   match on "quota metric" / "quota_metric" / "quota exceeded") → fail fast, like auth.
   Class B = nameless RESOURCE_EXHAUSTED (dynamic shared quota capacity throttle) →
   exponential backoff with full jitter, base 10s, cap 120s, pre-jitter budget 480s
   (deterministically 6 retries), on a counter that does NOT consume max_retries.
   Timeouts/5xx keep the 1s/2s policy. Every retry logs attempt/delay/error class in the
   message string.
2. **Sequential union passes** (5970497, `packages/presentation/editorial.py`
   `_critique_unioned`): the two adversarial critique passes now run sequentially instead
   of asyncio.gather — a concurrent burst of two large Pro calls is exactly the DSQ
   throttle shape. Union CONTRACT unchanged (dedupe key, llm_verified both-or-nothing,
   add-only discipline, editorial_critique_union fields); new test pins non-overlap.
3. **Per-call log payloads** (4409e72, `packages/core/gemini.py` + `llm.py`):
   gemini_call_complete / llm_call_complete now embed the telemetry dict via json.dumps
   in the message string (9133074 pattern) — cached_input_tokens explicitly included as
   the P0 GEMINI_BRAIN_CACHE gate observable in docker logs.

Adversarial review: architect seat (Codex auth lapsed); package in `review/`
(resilience.diff, resilience_tests.py, NOTES.md). Approved, no code changes required.
Accepted notes: (a) per-minute quota 429s now fail fast instead of retrying — old 1s/2s
retries could not survive a per-minute window anyway; (b) union critique latency is now
two sequential Pro calls instead of one gathered burst.

Suite at commit time: 1609 passed, 1 known flake (test_resolution_runs_in_parallel,
timing-sensitive, passes standalone; untouched by this diff). ruff + format + pyright
clean on changed files. NOT VERIFIED live: class-B recovery under real DSQ throttling
(VM observable: gemini_call_throttled_retrying then a successful pass on the same job).
