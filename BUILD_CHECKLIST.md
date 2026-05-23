# Nashr Presentation Engine — Full Build Checklist

**DONE (this session):**

- Generation unblocked (emergency-deck bug chain cleared)
- Generative palette (topic-derived)
- Slide count content-driven (30 → ~19)
- Real fonts installed (IBM Plex etc., killed fallback rendering)
- PDF engine fixed (PPTX→LibreOffice, no Chromium)
- Collision class fixed (fontkit measurement + never-stack-upward floor)
- Free render-test loop established
- Git divergence under control

---

**REMAINING:**

**Step 1 — Editorial quality fix** (paid, batch into one generation): structured chart data (labels+values+unit), stop truncation ("73." → "73.8 bar"), kill filler bullets, stop dropping list items (#3). Audit after.

**Step 2 — Chart renderer** (free): SVG bars/comparison from step-1 data. Quality-checked, not just functional. Audit after.

**Step 3 — Image engine: portraits** (Wikimedia + mechanical restyle). Audit after.

**Step 4 — Image engine: atmosphere** (AI gen restyled, Nano Banana, tier-gated). Audit after.

**Step 5 — Image engine: per-slide router** (picks portrait/atmosphere/none per slide). Audit after.

**Step 6 — Intent layer: purpose-driven decks** (teach vs persuade vs inform; arc adapts). Audit after.

**Step 7 — Intent layer: "add your own prompt"** (user steering into generation). Audit after.

**Step 8 — Input regimes / grounding** (upload, screenshot+OCR, pasted-URL; ground in user's own material). The product moat. Audit after.

**Step 9 — Conversational edit layer** (talk-to-refine, surgical edits). Audit after.

**Step 10 — Honest failure** (kill the degraded fallback deck; fail cleanly). Audit after.

**Step 11 — fontkit measurement accuracy** (currently undercounts; floor masks it; fix variable-font weight axis so margins aren't thin). Audit after.

**Step 12 — Beautiful font library** (curate Mona Sans / Hubot Sans / numeral font; diacritic-verify ń ǵ ú ó á ı ş ñ; install). Audit after.

---

**HYGIENE (fold in opportunistically, not blocking):**

- Unify the two font allowlists (Python + TS) → one source of truth
- Rotate the GitHub PAT + set up server credential helper/SSH
- Fix the "unhealthy" container healthcheck
- Commit the debug scaffolding (mount + persistence) properly
- PDF interactive-slide reveal treatment (lost in the LibreOffice switch)
