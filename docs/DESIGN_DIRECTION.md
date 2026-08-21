# NASHR — CREATIVE DIRECTION
## Architect deliverable. Governs all design execution. Commit to docs/. 
## Execution rule: every visual decision either serves this document or gets cut.

---

## 1. THE CONCEPT (one idea, everywhere)

**Nashr is the modern continuation of the region's manuscript tradition.**

"Nashr" means *publication*. This civilization built the Ulugh Beg observatory,
produced al-Khwarizmi and Beruni, and ran a manuscript culture where a claim
without a source was not knowledge. Nashr's product literally enforces that
standard with software: claims ground to manba, a critic refuses fabrication,
provenance is a feature. The brand IS the mechanic.

So the identity is: **a scholarly publishing house with an engine inside.**
Not a SaaS. Not an "AI tool." A press.

Every detail obeys the concept the way Agora's details obey the agora:
- Imagery: dithered/engraving-treated plates of the scholarly heritage
  (Ulugh Beg observatory, astrolabes, manuscript pages, Registan geometry) —
  never stock photos, never generic AI gloss.
- The product's own decks are the hero artifacts, framed like plates in a book.
- Motifs: footnote rules, marginalia, folio numbers, the citation mark.
  Section numbers styled as manuscript folios (I., II., III.).
- Testimonials, when they exist, are "Letters" — like a journal's
  correspondence page.
- Microcopy voice: a serious editor, warm but exact. Stakes, not features.

**Hero copy direction (UZ primary), the knife not the brochure:**
"Ma'ruzangiz savolga dosh beradimi?" (Will your presentation survive the
questions?) / subline: "Nashr har bir fikrni manbaga bog'laydi. Ustoz
so'raganda — javob tayyor." Iterate the words, keep the shape: stakes,
then the mechanism, then proof.

---

## 2. PALETTE (tokens, not vibes)

**Flexoki** (stephango.com/flexoki) is the palette of record. Every colour in
the product comes from its scale — nothing is invented, nothing is mixed by
eye. The four role names stay; they are now names for Flexoki values.

- **Qog'oz** (paper): `paper` #FFFCF0. Marketing ground.
- **Siyoh** (ink): `base-950` #1C1B1A. Text on the marketing side, and the
  APP's ground. (Flexoki `black` #100F0F is reserved for labels sitting on a
  bright accent fill, where base-950 is a step short of 4.5:1.)
- **Zangori** (lapis): `blue-600` #205EA6 light / `blue-400` #4385BE dark.
  Links, primary actions. Blue that carries TEXT on the dark ground lifts one
  more step to `blue-300` #66A0C8 — blue-400 as text is 4.37:1 on base-950.
- **Oltin** (gilding): `yellow-600` #AD8301 light / `yellow-400` #D0A215 dark.
  RARE — one element per view. Gilding was expensive; treat it that way.
  **Gold is never small text**: yellow-600 on paper is 3.39:1. Gold is fills,
  rules, underline-draws and carets; text sitting ON a gold fill is ink.
- Status: **Xato** (error) `red-600` #AF3029 light / `red-300` #E8705F dark;
  **Tayyor** (success) `green-700` #536907 light / `green-400` #879A39 dark.
  Both light/dark tiers are set one step off the plain 600/400 rule where the
  600/400 value failed 4.5:1 — see the ratios in the token file's comments.
- **The accent rule**: 600-series on light ground, 400-series on dark ground.
  Deviations exist only where a measured contrast ratio forced them, and each
  one is annotated at the token.
- **Rules, borders, muted text, surface tints**: the Flexoki base scale, never
  an opacity wash. Light: ground `paper`, surface `base-50`, borders
  `base-100`/`base-200`, muted text `base-700`, secondary text `base-800`.
  Dark: ground `base-950`, surface `base-900`, borders `base-850`/`base-800`,
  text `base-200`, muted `base-400`, secondary `base-300`. `color-mix()` is
  allowed only when both inputs are already Flexoki tokens (the accent washes).
  Note the flip: Flexoki has nothing lighter than paper, so a raised light
  surface sits one step BELOW the ground, not above it.
- **The split**: marketing surfaces = ink on paper (light). The product
  viewer/workspace = paper on ink (dark, matching the deck engine's output).
  Crossing from site into product feels like opening the manuscript.
- Raw hex lives in exactly one place: the `--flexoki-*` block at the top of
  `packages/web/app/globals.css`. Everything else resolves through a role
  token. Baked assets (plates, OG image, icons) carry the same values by hand
  because they render outside the cascade.

Banned: purple, gradients as decoration, glassmorphism, neon, emoji in chrome,
pure #000/#FFF, more than one gold element per viewport. Amended: the Flexoki
base scale is the ONLY permitted neutral family — no slate/zinc/gray/neutral/
stone utilities, no ad-hoc grays, no ink-at-N%-opacity rules.

---

## 3. TYPE

- **Display/headers**: a real serif with soul and full Latin-Extended +
  Cyrillic (Uzbek + Karakalpak diacritics are first-class, test O'/G'/ń/á
  in EVERY weight used). Candidates in order: Literata, Source Serif 4,
  STIX Two Text. Self-hosted via next/font. NEVER Inter/Roboto/Arial/
  Space Grotesk anywhere.
- **Body/UI**: a humanist sans with the same coverage: Source Sans 3 or
  IBM Plex Sans. 
- **Numbers/data/provenance**: tabular figures; a mono accent (IBM Plex Mono)
  for chunk refs and citation marks only.
- Scale: display sizes are BRAVE (hero ≥ clamp(3rem, 8vw, 6.5rem)). The
  serif does the talking; everything else stays quiet.

---

## 4. MOTION DESIGN (the layer that separates peak from template)

Library: **Framer Motion** (React-native, already in ecosystem) + CSS
scroll-driven where cheap. No GSAP unless a specific effect demands it.
Optional: **Lenis** for smooth scroll on marketing pages only, never in app.

The motion vocabulary (use THESE, nothing else, consistency = identity):
1. **Ink-reveal**: text blocks enter as opacity 0→1 + 12px rise, staggered
   80ms per element. The site "gets written" as you scroll.
2. **Dither-in**: images resolve from a coarse dithered state to full
   (two-layer crossfade; the Higgsfield plates are generated WITH a dithered
   variant for this). This is the signature move — Agora has dithering,
   ours ANIMATES like ink drying.
3. **The gilded moment**: the primary CTA gets one subtle 600ms gold
   underline-draw on first viewport entry. Once. Never loops.
4. **Deck plates**: hero deck screenshots tilt ≤2deg on pointer, shadow
   deepens. Restraint: no 3D flips, no parallax storms.
5. **Progress as typesetting**: generation progress in-app shows step names
   typing in serif with a steady caret — the press at work.
6. Counters (if stats exist): count-up once, 900ms, ease-out.

Rules: 60fps or cut it; transform/opacity only; `prefers-reduced-motion`
collapses everything to instant states (non-negotiable); nothing animates
on loop except nothing; total motion JS ≤ 40KB gz.

---

## 5. ASSET PIPELINE (Higgsfield MCP + real artifacts)

Real artifacts (not generated, ever): deck screenshots from the live engine
(sCO2 + whitepaper decks; title slide + one data slide each), UI screenshots.

Generated via Higgsfield (GPT-Image-class models for text/graphic fidelity;
every asset produced in TWO states: full + coarse-dither variant for the
dither-in animation):
1. Hero plate: Ulugh Beg observatory as an old engraving, warm ink on
   paper tone, wide, must survive text overlay left-half.
2. Section plates (3-4): astrolabe, manuscript page with marginalia,
   Registan geometric detail, an armillary sphere. Same engraving language.
3. OG image 1200x630: wordmark + plate fragment.
4. Empty-state spot illustrations (2-3): a blank folio, an inkwell —
   monochrome ink, small.
5. Favicon/wordmark support marks: a citation mark ⌜ ⌝ motif.
Judging rule: if it reads as "AI art" (gloss, symmetry-soup, uncanny detail),
regenerate or cut. Max 2 iterations per asset, then move on.

---

## 6. AUDIO (the honest answer: almost none)

Websites with sound are 95% regret. The concept allows exactly TWO sounds,
both OFF by default, both in-APP only (never on marketing pages):
1. Delivery moment: when a deck completes — a single soft paper-and-stamp
   sound (<1s). The press finishing a run.
2. Optional UI tick on share-link copy. 
Implementation: one <audio> sprite, user-enableable in settings, respects
autoplay policies, zero audio on marketing. If a generated/licensed clip
can't be found tastefully, ship silence — silence is on-brand for a library.

---

## 7. PROCESS (how this gets executed without slop)

1. Fable session receives THIS document + live references: it Playwright-
   screenshots agorawriting.com, folk.com, trynia.ai, zerouniversity.com
   (or Zero's landing) at 1440px, and writes a 10-line "moves I'm stealing /
   moves I'm rejecting" note BEFORE any code.
2. Build order with HUMAN GATES between: (a) tokens+type+one hero section →
   Iko eyeball → (b) full landing → eyeball → (c) app shell restyle (dark
   manuscript) → eyeball → (d) states/motion polish pass → (e) audio last.
3. Every section: build → Playwright screenshot 1440+390 → self-critique
   against THIS doc → fix → then show.
4. Performance gate: Lighthouse ≥90 perf/access on landing; fonts subsetted;
   plates served as AVIF/WebP with dither variants tiny.
5. The Zero standard applies (Navid held launch 6 months for craft): a
   section that is merely "good" is not done. But the counterweight is ours:
   scope is never cut, sequencing is — polish lands section by section, and
   the demo uses whatever sections have passed the gate.