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

- **Qog'oz** (paper): #F7F3EA — warm manuscript cream. Marketing ground.
- **Siyoh** (ink): #16130E — near-black warm ink. Text, and the APP's ground.
- **Zangori** (lapis): #1D4ED8-family adjusted warm → use #274690. The
  manuscript lapis lazuli accent. Links, primary actions.
- **Oltin** (gilding): #B8860B-family → #A67C2E. RARE. Only for the moments
  that matter (the CTA, one highlight per view). Gilding was expensive; treat
  it that way.
- Rules/borders: ink at 12-18% opacity. No pure grays anywhere.
- **The split**: marketing surfaces = ink on paper (light). The product
  viewer/workspace = paper on ink (dark, matching the deck engine's output).
  Crossing from site into product feels like opening the manuscript.

Banned: purple, gradients as decoration, glassmorphism, neon, emoji in chrome,
pure #000/#FFF, more than one gold element per viewport.

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