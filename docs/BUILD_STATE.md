# SlideForge / Nashr — BUILD STATE   (read first, every session)

STATUS: PRODUCTION. Past MVP. No MVP scope, no "works for now." Fix at the correct layer,
verified. Iko runs Claude Code locally against the real repo; master prompts carry acceptance
tests; a step is DONE only when a commit changes this file.

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

## PLAN
1. [x] Free batch: A · C2 · B-interim — DONE 48f713b
2. [~] Editorial structured fields: H tables + G comparison + D-data chart_series — DONE this branch.
   STILL OPEN (separate model-quality concerns, not this fix): B-real (model writes breathing
   takeaways) · C (model drops its own numbered items).
3. [x] Step 2 chart renderer (free) — native-shape charts from chart_series — DONE this branch (see SHIPPED below).
4-12. [ ] image engine (3/4/5) · intent (6/7) · grounding (8) · convo edit (9) · honest failure (10) · fontkit accuracy (11) · font library (12)

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
