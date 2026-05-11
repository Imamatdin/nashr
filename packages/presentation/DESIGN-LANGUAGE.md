# NASHR PRESENTATION DESIGN LANGUAGE v2.0

> The design brain for Nashr's presentation engine.
> Design data is the paint. Design judgment is knowing where to put it.
>
> Derived from three golden references:
> - Ag'artıwshılıq (educational, warm, historical, interactive)
> - sCO2 Cooling System (technical, bold, data-driven, persuasive)
> - TKS Recommendation Deck Guide (professional, structured, argument-driven)

---

## Baseline assumptions

These are industry-standard rules. They are non-negotiable but not novel.
Listed here once so they don't inflate the rule count.

- Left-align body text. Never justify in presentations.
- Center-align is for: slide titles, single-line captions, section dividers. Nothing else.
- WCAG AA contrast ratio (4.5:1) on every text element.
- Maximum 2 font families per deck. A third (script/display) is allowed on max 2 slides.
- No pure black (#000000). Darkest ink: #2A2A2A (warm) or #1A1A1E (cool).
- `prefers-reduced-motion`: all transitions collapse to instant. Non-negotiable.
- Slide transitions: cut or fade, max 300ms. No bounce, spin, zoom, fly-in, or 3D.
- 16:9 aspect ratio (1920×1080px / 13.33"×7.5").

---

## Operational rules

These are the judgment calls that separate professional output from AI-generated mediocrity. Every rule is specific, testable, and enforceable by the renderer or the quality audit.

### IDENTITY

**R01 — Never repeat a layout type on consecutive slides.**
Acceptable: title → content-split → data-emphasis → gallery → comparison → content-split.
Unacceptable: content-split → content-split. The quality audit rejects consecutive repeats.

**R02 — Slide 1 and slide N carry the most visual weight.**
Slide 1 uses the largest type size in the deck (the `--display-jumbo` tier: 72-96px).
Slide N either restates the key takeaway, provides contact/CTA, or closes with a final statement.
A slide N that says only "Thank You" with no other content is a quality audit failure.

**R03 — Section dividers every 4-5 content slides.**
A section divider uses the accent color or the dark variant of the palette as its background.
Content: section title only (36-48px, centered). Optional: section number in very large text (96px+) at 10% opacity behind the title.
No body text. No images. No data. The divider is a visual breath.

**R04 — The audience should never identify the template.**
Every slide must feel composed for its specific content. This is achieved by varying across slides: text position (left/right/center/bottom), background treatment (light/dark/image/texture), content structure (prose/grid/timeline/stat), and visual weight distribution (image-heavy vs text-heavy).

### TYPOGRAPHY

**R05 — Heading-to-body size ratio is at least 2:1.**
If body is 18px, heading is at least 36px. If body is 24px, heading is at least 48px.
This ratio is measured on the same slide. A slide with 32px heading and 28px body has no hierarchy and fails audit.

**R06 — Numbers are always big, units are always small.**
The number is at least 2x the size of the unit/label. Exact pairings:

| Context | Number | Unit | Label |
|---------|--------|------|-------|
| Hero stat (1 per slide) | 72-96px | 36-48px | 18-24px |
| Standard stat (2-4 per slide) | 48-64px | 24-32px | 14-18px |
| Inline stat (within body text) | same as body, bold | same as body, regular | n/a |

WRONG: "94.4%" all at the same size. CORRECT: "94.4" at 72px, "%" at 36px.

**R07 — Font size floor: 14px for audience-facing text.**
12px is reserved for: slide numbers, navigation labels ("Kelesi"/"Artqa"), source citations, and copyright lines. Nothing else goes below 14px. If text needs to be smaller than 14px to fit, the slide has too much content. Split it.

**R08 — Titles state the takeaway, not the topic.**
WRONG: "Results" / "Problem Analysis" / "Literature Review"
CORRECT: "RL agents outperform rule-based control in all climates" / "Germany's open-door policy created the largest refugee overflow"

Test: a reader who only reads titles should understand the deck's narrative arc. If a title could be swapped between two different decks without anyone noticing, it fails.

**R09 — One weight for headings, one for body. No weight soup.**
Headings: Bold (700) or Semibold (600). Pick one, use it for ALL headings.
Body: Regular (400). Never Light (300) for body, it disappears on projectors.
Emphasis within body: Semibold (600), not italic. Italic is for: direct quotes, foreign terms, and book/journal titles. Nothing else.

**R10 — Line height: tight for headings, generous for body.**
Headings: 1.0-1.2. Multi-line headings feel like one cohesive block.
Body: 1.4-1.6. Scannable.
Never use the default (often 1.15). It's too tight for body, too loose for headings.

**R11 — Maximum 2 competing text blocks per slide.**
"Competing" means similar visual weight. A slide can have: heading + body, heading + stat, heading + image caption. Never three independent text areas of similar size. If three things need equal attention, they become three slides.

### COLOR

**R12 — One palette per deck. 4-5 colors total.**
The Design Direction Pass selects:
- `--slide-bg`: dominant background
- `--slide-surface`: content surface (lighter or darker than bg)
- `--slide-text`: primary text
- `--slide-accent`: highlights, emphasis, key data (used on ≤10% of elements)
- `--slide-text-secondary`: captions, metadata, subordinate text (optional)

Decision tree for palette mood:

| Content domain | Background | Accent | Mood |
|----------------|------------|--------|------|
| History/education | warm off-white (#F5F0E8) | brown/gold (#8B6914) | warm-historical |
| Engineering/technical | dark (#0D0D12) | red-orange (#E8553A) | bold-technical |
| Professional/business | light gray (#F8F8FA) | teal (#0A8A7A) | clean-professional |
| Medical/health | white (#FAFAFA) | blue-green (#2E8B8B) | calm-medical |
| Environmental | cream (#F5F2E8) | forest green (#2D6B4F) | natural |
| Legal/policy | warm white (#FAF8F5) | navy (#1A3A5C) | institutional |

**R13 — The accent color appears on ≤10% of visual elements.**
60% dominant (background/surface), 30% secondary (text, borders, subtle fills), 10% accent.
If accent is on more than ~3 elements per slide, it's overused and nothing is highlighted.

**R14 — Gradient scrims replace boxes on image overlays.**
When text overlays an image, use a semi-transparent gradient:
- Direction: follows reading flow (left-to-right for LTR text, bottom-to-top for bottom-placed text)
- Opacity: 50-70% at the solid end, 0% at the transparent end
- The scrim must look like natural lighting/shadow, not like a rectangular panel placed on top
- Shape: full-width or full-height strip, never a floating rectangle

FORBIDDEN over images: bordered rectangles, rounded cards, drop-shadow containers, any visible box shape.

**R15 — Dark and light slides can coexist in one deck.**
Choose one dominant treatment (light OR dark). The opposite may appear on at most 20% of slides. Section dividers and emphasis slides are the natural candidates for the inverted treatment.

### SPACING AND LAYOUT

**R16 — Content area occupies a bounded rectangle within the slide.**
Maximum content rectangle: 90% of slide width × 88% of slide height.
This leaves minimum margins: 5% left/right (96px at 1920w), 6% top/bottom (65px at 1080h).
Content touching the slide edge is a quality audit failure (risks projector overscan).

**R17 — Maximum 6 lines of body text per slide. Maximum word count by type.**

| Slide type | Max words | Max body lines |
|------------|-----------|----------------|
| TITLE-HERO | 15 | 0 (title + subtitle only) |
| DATA-EMPHASIS | 30 | 0 (numbers + labels only) |
| QUOTE-PULLQUOTE | 35 | 0 (the quote IS the slide) |
| SECTION-BREAK | 6 | 0 |
| CONCEPT-DEFINITION | 50 | 5 |
| CONTENT-SPLIT | 60 | 6 |
| GALLERY-PEOPLE | 60 | 0 (names + captions) |
| COMPARISON | 70 | 5 per column |
| TABLE-COMPACT | n/a | n/a (table data) |
| All interactive types | 50 | 4 |
| All other types | 55 | 6 |

If the content exceeds the limit, the Editorial Pass MUST cut or split into two slides.

**R18 — Three spacing tiers. Used consistently across the deck.**

| Tier | Size (px) | Use |
|------|-----------|-----|
| Tight | 8-12 | Within a logical group (name + role under a portrait, number + unit) |
| Medium | 24-32 | Between separate content blocks on the same slide |
| Wide | 48-64 | Between the slide title and the content area |

Never use a spacing value outside these tiers. No 16px gaps, no 20px gaps. The tiers create rhythm.

**R19 — Multi-element slides align to an invisible grid.**
2 columns: 48% + 48% with 4% gutter. 3 columns: 31% + 31% + 31% with 3.5% gutters. 4 columns: 22.75% + 22.75% + 22.75% + 22.75% with 3% gutters.
The gutter width is the SAME across all multi-column slides in the deck.

**R20 — Full-bleed images extend to all four edges. No half-measures.**
If an image is the background, it fills 100% of the slide. No visible margins on any side.
If an image is a content element (not background), it lives within the content rectangle (R16) and follows grid alignment (R19). There is no in-between.

### IMAGERY

**R21 — Every slide has an intentional background treatment.**
Acceptable: solid color, full-bleed topic-relevant image, subtle texture (paper/grain/fabric at ≤5% opacity), two-color gradient from the palette.
UNACCEPTABLE: plain default white with no design intent. This is the single most common failure in AI-generated presentations.

**R22 — Images match the content domain. Never cross-domain.**
History topic → period-appropriate artwork, engravings, historical scenes.
Engineering → technical diagrams, equipment, systems.
Medical → lab environments, microscopy, anatomical illustration.
Economics → cityscapes, markets, data visualizations.
NEVER: a history presentation with stock photos of modern offices.

**R23 — All images in a deck share the same color temperature and treatment.**
Warm-toned historical painting cannot coexist with cold-toned stock photography.
The Design Direction Pass defines an `image_style_prefix` that is applied to every AI-generated image and used to filter any sourced images. Example: "18th-century oil painting, warm earth tones, museum quality, period-appropriate" or "technical diagram, dark background, red-orange accent lines, clean vector, high contrast."

**R24 — Portraits are cutouts. Never framed, never carded.**
People (scientists, authors, team members) are shown as portrait images without borders, frames, card containers, or drop shadows. The portrait sits directly on the background or on a gradient scrim. Museum exhibition style, not corporate directory.

**R25 — One chart or diagram per slide.**
Decision tree:
- 1 chart → full slide, chart fills 65-75% of slide area
- 2 charts that COMPARE the same metric → side-by-side, each 48% width
- 2 charts of DIFFERENT metrics → 2 separate slides
- 3+ charts → replace with a summary table (TABLE-COMPACT) or a key-stat slide (DATA-EMPHASIS) that highlights the conclusions

### RHYTHM AND SEQUENCE

**R26 — Information density increases through the deck.**
Opening slides (1-3): sparse, high-impact. Title, concept, overview.
Middle slides (4-N-3): moderate density. Content, data, evidence.
Late slides (N-2 to N): can be denser. Tables, detailed comparisons.
Closing slide: clean, conclusive.

**R27 — After every data-heavy slide, place a breathing slide.**
"Data-heavy" = CHART-DATA, TABLE-COMPACT, DATA-EMPHASIS with 3+ stats.
"Breathing" = QUOTE-PULLQUOTE, SUMMARY-TAKEAWAY, SECTION-BREAK, or a single full-bleed image slide.
Two consecutive data-heavy slides is a rhythm violation.

**R28 — Interactive slides cluster at section ends.**
Pattern: Content → Content → Content → Summary → Quiz/Exercise → Section Break → (next section).
NOT: Content → Quiz → Content → Quiz → Content → Quiz (scattered).

**R29 — Alternate text-dominant and visual-dominant slides.**
If slide 3 is mostly text (concept definition), slide 4 should be mostly visual (gallery, chart, full-bleed image). If this alternation is impossible because of content, insert a SECTION-BREAK to reset the visual rhythm.

### EDITORIAL (what goes ON the slide)

**R30 — The title IS the argument.**
Every slide answers exactly ONE question. Before placing content, ask: "What is the ONE thing the audience should take away?" If the answer contains "and" (the problem AND the opportunity), it's two slides.

**R31 — Bullets are claims, not descriptions.**
WRONG: "Overview of the market situation" (describes a topic, could be true of anything).
CORRECT: "Market grew 15% YoY driven by AI adoption" (makes a falsifiable claim).
Every bullet should be a statement that has a truth value.

**R32 — Data slides surface the implication.**
The "so what?" lives on the slide, not in the speaker's head.
WRONG: a chart showing revenue growth with no annotation.
CORRECT: the same chart with a callout: "On track to exceed $10M ARR by Q4."
Decision tree: if the slide has data, does the title or a caption state what the data MEANS? If not, add the implication.

**R33 — Citations are present but visually subordinate.**
Format: 10-12px, `--slide-text-secondary` color, bottom-right corner.
Citations never compete with content. In-text references appear as [1] superscripts, matching the deck's bibliography format. The citation supports credibility silently.

**R34 — Speaker notes carry the depth.**
The slide is the visual anchor. The speaker notes contain: full explanation, data source details, transition phrase to the next slide, and talking points. If the slide content is self-explanatory without notes, the notes contain the "bonus depth" layer.

### DATA VISUALIZATION

**R35 — Chart titles state the insight, not the chart type.**
"Solar adoption tripled since 2020" not "Solar Adoption Chart (2015-2024)."

**R36 — Highlight the key data point. Gray the rest.**
The primary data point uses `--slide-accent`. All other data points use 30-40% opacity gray. The audience sees the conclusion instantly without scanning.
If ALL data points are equally important (no single key finding), use the accent color for the most recent or the highest, and annotate why.

**R37 — Tables: no visible grid lines.**
Structure comes from:
- Bold header row (accent color underline or background at 10% opacity)
- Alternating row shading: 0% and 3-5% opacity of `--slide-surface`
- No vertical lines. Horizontal dividers at most 1px, 10% opacity.
Cell padding: 8-12px. Font size: 12-14px (tables are the ONE exception to the 14px floor).

**R38 — Numbers right-aligned. Text left-aligned. Never center table content.**
Right-aligned numbers make magnitude comparison instant. Left-aligned text is scannable.

**R39 — Chart colors come from the deck palette.**
Excel/Google Sheets default colors (blue, red, green, yellow) are forbidden. Replace with: `--slide-accent` for the primary series, grays for secondary series.

### FORBIDDEN PATTERNS

**R40 — No visible rectangles, cards, panels, or bordered containers.**
Content separation is achieved through: spacing (R18), gradient scrims (R14), size contrast (R05-R06), and color contrast (R12-R13).
Padding within text blocks is invisible positioning, not a visible container. No element should have: a visible border, rounded corners, or a drop shadow that creates a box appearance.
EXCEPTION: tables have inherent grid structure, but their borders follow R37.

**R41 — No clip art, cartoon illustrations, or generic stock icons.**
Icons are acceptable ONLY when: from a consistent set (Lucide/Feather), small (24-32px), monochrome in `--slide-text-secondary`, and supplementing text rather than replacing it. Maximum 6 icons per slide.

**R42 — No watermarks or "Confidential" on every slide.**
If needed, once on the title slide. Not repeated.

**R43 — No default PowerPoint/Google Slides/Canva themes.**
The Design Direction Pass produces a bespoke palette. If the output looks like it came from a theme picker, it fails.

### INTERACTIVE ELEMENTS

**R44 — Interactive UI obeys all visual rules.**
No boxes around answer choices. No colored buttons. Options are plain text with hover/click effects (underline, color change, opacity shift). Feedback appears as gradient overlays at the bottom of the slide, not popup boxes.

**R45 — Navigation labels are in the deck's language.**
Uzbek: "Kelesi" (Next), "Artqa" (Back), "Dúrıs" (Correct), "Qáte" (Wrong), "Qayta urınıp kór" (Try again), "Jauapdı kórset" (Show answer), "Kenes" (Hint).
Russian: "Далее", "Назад", "Правильно", "Неверно", "Попробуйте снова", "Показать ответ", "Подсказка".
Navigation text: 10-12px, bottom corners, text-only. Not buttons.

**R46 — Feedback is specific, not generic.**
WRONG: "Correct!" / "Wrong, try again."
CORRECT: "Dúrıs! Monteske hákimiyatti üshke bóldi: nızam, atqarıwshı, sud." (explains WHY)
Every feedback message teaches. It doesn't just validate.

**R47 — PPTX interactivity uses hyperlink navigation.**
Correct answer → hyperlink to "Correct" feedback slide. Wrong answer → hyperlink to "Wrong" feedback slide. "Try again" → hyperlink back to question slide. Each quiz requires 2 dedicated feedback slides.

**R48 — HTML interactivity uses vanilla JS. No external dependencies.**
Quiz logic, score tracking, navigation: all in a single HTML file. No frameworks, no CDN, no localStorage. State lives in memory.

### LANGUAGE AND TEXT

**R49 — All slide content in ONE language.**
If the deck is in Uzbek, every label, title, caption, navigation element, and interactive prompt is in Uzbek. Source citations may reference titles in other languages (English journal names stay in English).

**R50 — Karakalpak and Uzbek diacritics must render correctly.**
Required glyphs: ń, ǵ, ú, ó, á, ı, ş, ñ, ő, ű. The heading and body fonts must support these. If a glyph doesn't render, it's a quality audit failure.
Font fallback chain must include a font that covers Latin Extended-A and Extended-B.

**R51 — Numbers use locale-appropriate formatting.**
Uzbek/Russian: 1 000 000 (space separator), 3,14 (comma decimal).
English: 1,000,000 (comma separator), 3.14 (period decimal).
The formatting matches the deck's language.

---

## Slide type specifications

Every slide in a Nashr presentation is one of these types. The Layout Pass selects the type based on content analysis. The renderer applies the type-specific composition rules.

All positions are given as percentages of slide dimensions (1920×1080).
`x%` = distance from left edge. `y%` = distance from top edge. `w%` = width. `h%` = height.

---

### TITLE-HERO

**Purpose:** Opening slide. Sets the mood.

**Composition:**
```
Background: full-bleed image (topic-relevant, high-impact) + gradient scrim 60-100% coverage
Title:      x 5%,  y 30%, w 70%, h 15%  |  largest in deck: 72-96px heading font, bold
Subtitle:   x 5%,  y 48%, w 70%, h  8%  |  40-60% of title size, italic or lighter weight
Attribution: x 5%, y 90%, w 40%, h  4%  |  14-16px, optional (author/org name)
```

**Content limit:** title + subtitle + optional attribution. Max 15 words total.
**Forbidden:** bullets, body text, content blocks.

---

### CONCEPT-DEFINITION

**Purpose:** Introduce a key concept with a one-sentence definition + supporting points.

**Composition:**
```
Background: relevant image or texture + gradient scrim on text side
Scrim:      covers 50-60% of slide width (left or right, alternating with other slides)
Title:      x 5%,  y 5%,  w 50%, h  8%  |  32-40px heading font
Definition: x 5%,  y 16%, w 48%, h 12%  |  20-24px body font, italic
Bullets:    x 5%,  y 32%, w 48%, h 50%  |  14-18px body font, 3-5 items, max 8 words each
```

**Content limit:** 1 definition sentence + 5 bullets. Max 50 words.

---

### GALLERY-PEOPLE

**Purpose:** Introduce 3-5 key people.

**Composition (for 5 people):**
```
Background: subtle texture or blurred artwork
Portraits:  5 cutouts, evenly spaced horizontally
  Each:     w 14%, h 30%, y 15%
  Spacing:  x positions at 5%, 22%, 39%, 56%, 73%
Name:       centered under portrait  |  14-16px bold
Dates/Role: centered under name     |  12-14px regular, --slide-text-secondary
Description: centered under dates   |  12px regular (one line)
Caption:    x 5%, y 88%, w 90%, h 4% | 14px italic, centered
```

**For 3 people:** w 20%, h 35%, x positions at 10%, 40%, 70%.
**For 4 people:** w 16%, h 32%, x positions at 6%, 28%, 50%, 72%.

**Content limit:** name + dates + one line per person. Max 60 words for 5 people.
**Forbidden:** card containers around portraits. Portraits sit directly on the background.

---

### TYPOGRAPHIC-KEYWORDS

**Purpose:** Present 3-6 key terms with short explanations.

**Composition:**
```
Background: muted image or texture + full-slide gradient scrim (50-60% opacity)
Title:      x 5%, y 4%, w 90%, h 8%  |  28-36px heading font, centered
Keywords:   stacked vertically, left-aligned
  Each keyword:
    Term:   x 5%,  y (18 + idx*15)%, w 35%, h 6%  |  24-32px bold, --slide-accent
    Explain: x 42%, y (18 + idx*15)%, w 50%, h 6%  |  14-18px regular
  Spacing: 15% of slide height between groups (tight tier within group)
```

**Content limit:** 3-6 keywords with one-line explanations. Max 55 words.
**Forbidden:** icons, bullets. The keyword size IS the visual element.

---

### CONTENT-SPLIT

**Purpose:** Body text alongside an image or visual.

**Composition (text left, image right):**
```
Text side:  x 5%, y 5%, w 48%, h 88%
  Title:    top of text side  |  28-36px heading font
  Body:     below title, wide spacing tier gap  |  16-20px body font, max 6 lines
  Caption:  bottom of text side  |  12-14px italic
Image side: x 52%, y 0%, w 48%, h 100%  |  image extends to right edge (no margin)
```

**Alternate version (text right, image left):** mirror the x positions.
Alternate between text-left and text-right across the deck.

**Content limit:** title + 4-5 lines body. Max 60 words.

---

### DATA-EMPHASIS

**Purpose:** Highlight 1-4 key statistics.

**Composition (1 stat, hero):**
```
Background: solid dark or solid light (clean, not busy)
Number:     centered, y 30%  |  72-96px, --slide-accent
Unit:       immediately right of number  |  36-48px, --slide-text-secondary
Label:      centered, y 55%  |  18-24px, --slide-text
Subtext:    centered, y 65%  |  14px, --slide-text-secondary (optional context line)
```

**Composition (2 stats):**
```
Left stat:  x 10%, centered in left half
Right stat: x 60%, centered in right half
Each uses the standard stat (48-64px number, 24-32px unit, 14-18px label)
```

**Composition (3 stats):**
```
Three columns: x 8%, 38%, 68%  |  w 24% each
VARIATION REQUIRED:
  - Stat 1: accent color highlight (number in --slide-accent)
  - Stat 2: trend indicator (↑ or ↓ arrow next to the number, green or red)
  - Stat 3: comparison text ("vs 67% in 2022" below the label)
  Never three identical number-label stacks.
```

**Composition (4 stats):**
```
2×2 grid: top-left (x 8%, y 18%), top-right (x 55%, y 18%), bottom-left (x 8%, y 55%), bottom-right (x 55%, y 55%)
Each cell: w 37%, h 32%
Variation: at least 2 of the 4 must differ (one highlighted, one with trend, etc.)
```

**Content limit:** numbers + labels only. Max 30 words.

---

### COMPARISON

**Purpose:** Side-by-side comparison of two concepts/approaches.

**Composition:**
```
Left column:  x 5%,  y 15%, w 43%, h 75%
Right column: x 52%, y 15%, w 43%, h 75%
Divider:      x 49%, y 15%, w 0.1%, h 70%  |  1px line, --slide-accent at 30% opacity
  OR: no divider, just the 4% gutter (cleaner)

Each column:
  Heading:  top  |  22-28px bold
  Points:   below heading, 3-5 items  |  14-18px regular
  Optional: the "preferred" column gets --slide-accent for its heading
```

**Content limit:** heading + 5 points per side. Max 70 words total.

Decision tree for comparison content:
- 2 items, qualitative → COMPARISON
- 2 items, quantitative → CHART-DATA with two bars/lines
- 3+ items → TABLE-COMPACT
- Before/after of SAME thing → CONTENT-SPLIT with before-image left, after-image right

---

### TIMELINE

**Purpose:** Show chronological progression.

**Composition (horizontal, 3-5 nodes):**
```
Timeline line: y 45%, x 10% to x 90%  |  2px, --slide-accent
Nodes:  evenly spaced along the line
  Each node:
    Dot:    12px circle on the line, --slide-accent fill
    Year:   above the line, centered on dot  |  16-20px bold
    Label:  below the line, centered on dot  |  12-14px regular, max 10 words
```

**Composition (vertical, 3-5 nodes):**
```
Timeline line: x 12%, y 15% to y 85%  |  2px, --slide-accent
Nodes: evenly spaced vertically
  Each node:
    Dot:    12px circle on the line
    Year:   to the right of dot, x 16%  |  16-20px bold
    Label:  to the right of year, x 16% |  12-14px regular
    Optional portrait: to the left of dot, x 3%, w 8%
```

Decision tree:
- 3-5 events → horizontal (fits better on 16:9)
- 6+ events → vertical, or split into two timeline slides
- Events with long descriptions → FLOW-PROCESS instead

**Content limit:** date + one-line description per node. Max 50 words.

---

### FLOW-PROCESS

**Purpose:** Show a multi-step process.

**Composition (3-5 steps, horizontal):**
```
Steps: evenly distributed, y centered at 40-50%
  Each step:
    Number/Icon: 32-48px, --slide-accent  |  centered in step column
    Label:       below icon  |  14-16px bold
    Description: below label |  12-14px regular, max 15 words
Connectors: horizontal arrows or lines between steps  |  2px, --slide-accent, 30% opacity
```

**Content limit:** label + one-line description per step. Max 50 words.
**Forbidden:** nested sub-steps. A complex step gets its own slide.

---

### QUOTE-PULLQUOTE

**Purpose:** Highlight a key quote or finding.

**Composition:**
```
Background: solid or very muted texture (the quote needs a clean field)
Quote:      x 10%, y 25%, w 80%, h 35%  |  24-36px, italic, centered or left-aligned
Attribution: x 10%, y 65%, w 80%, h 5%  |  14-16px, right-aligned, --slide-text-secondary
Decorative: optional large quotation mark  |  120px, --slide-accent at 10% opacity, top-left of quote
```

**Content limit:** the quote (max 30 words) + attribution. The quote IS the slide.

---

### CHART-DATA

**Purpose:** Present a single chart or data visualization.

**Composition:**
```
Title:   x 5%, y 4%, w 90%, h 8%   |  states the insight, not the chart type (R35)
Chart:   x 5%, y 15%, w 65%, h 72% |  fills ~65-75% of slide area
Annotation: x 72%, y 15%, w 23%, h 30% |  optional callout text explaining the key finding
Source:  x 70%, y 90%, w 25%, h 4% |  10-12px, --slide-text-secondary, right-aligned
```

**Content limit:** title + chart + optional annotation + source. Max 20 words of text.

---

### TABLE-COMPACT

**Purpose:** Present structured data.

**Composition:**
```
Title:   x 5%, y 4%, w 90%, h 8%
Table:   x 5%, y 15%, w 90%, h 75%
  Max: 5 columns × 6 rows
  Header: bold, --slide-accent underline or 10% opacity accent background
  Rows:   alternating 0% and 3-5% opacity shading
  Cells:  8-12px padding, 12-14px font
  Numbers: right-aligned. Text: left-aligned.
Source:  x 5%, y 92%, w 90%, h 4%  |  10-12px, --slide-text-secondary
```

**Content limit:** what fits in 5×6 at 12px. Larger tables get split or go to handouts.

---

### SECTION-BREAK

**Purpose:** Signal transition between major sections.

**Composition:**
```
Background: solid --slide-accent (or dark variant of palette)
Section number: centered, y 35%  |  96px, 10% opacity, behind the title (optional)
Section title:  centered, y 40%  |  36-48px, white or cream text
```

**Content limit:** section name only. Max 6 words.
**Forbidden:** body text, images, data.

---

### SUMMARY-TAKEAWAY

**Purpose:** Summarize key points from the preceding section.

**Composition:**
```
Title:      x 5%, y 5%, w 90%, h 8%  |  "Key Takeaways" or equivalent
Takeaways:  numbered or bulleted, x 8%, y 18%, w 84%
  Each:     bold keyword + regular explanation, one sentence
  3-5 items, tight spacing tier within, medium spacing between
```

**Content limit:** 3-5 single-sentence takeaways. Max 60 words.
**Placement:** appears after every 4-6 content slides.

---

### Interactive types

All interactive types share:
- Background: topic-relevant image + gradient scrim, or clean solid background
- Navigation: "Kelesi"/"Artqa" at 10-12px in bottom corners
- No visible boxes around options (R40, R44)

**INTERACTIVE-QUIZ-MCQ:** question at 20-24px bold (y 10-20%), 3-4 text options stacked (18px, labeled A/B/C/D), hyperlink navigation to feedback slides.

**INTERACTIVE-MATCHING:** left column names (bold), right column ideas, dotted baseline connectors (1px dash, --slide-accent at 40%), "Jauapdı kórset" text link reveals connections.

**INTERACTIVE-CATEGORIZE:** 3-5 category labels across top (y 15%), mixed items below, correct grouping revealed on click.

**INTERACTIVE-FILL-BLANK:** 3-5 statements with "\_\_\_\_\_" blanks, answers revealed below each in --slide-accent italic.

**INTERACTIVE-TRUE-FALSE:** 3-5 statements with "Dúrıs"/"Qáte" indicators, explanation below each.

**INTERACTIVE-DEBATE:** scenario prompt (2-3 lines, y 15-25%), 2-3 numbered argument positions below, each with a one-line explanation of which framework/theory it represents.

---

### RESOURCES-LINKS

**Composition:** title + 3-6 resources, each with name (bold) + one-line description + URL. Clean layout.

### TEAM-CREDITS

**Composition:** portrait cutouts horizontal, name + role under each, optional social links. Can integrate a closing statement.

---

## Decision trees

When the content-to-layout mapping is ambiguous, these trees resolve it.

**How many items are being compared?**
```
2 items, qualitative → COMPARISON
2 items, quantitative → CHART-DATA (two series)
3-4 items, brief → TABLE-COMPACT
5+ items → TABLE-COMPACT or multiple slides
Before/after → CONTENT-SPLIT
```

**Content has both text and data:**
```
Data is the main point → CHART-DATA or DATA-EMPHASIS (text in annotation area)
Text is the main point → CONTENT-SPLIT (chart as the image half)
Both equally important → two slides: one CONTENT-SPLIT for the narrative, one CHART-DATA for the evidence
```

**How many people to show?**
```
1 person with detailed bio → CONTENT-SPLIT (portrait as image half)
2 people → CONTENT-SPLIT with side-by-side portraits in image half
3-5 people with brief info → GALLERY-PEOPLE
6+ people → two GALLERY-PEOPLE slides, or a TABLE-COMPACT with names/roles
```

**Content is a list:**
```
3-5 key terms with definitions → TYPOGRAPHIC-KEYWORDS
3-5 process steps → FLOW-PROCESS
3-5 chronological events → TIMELINE
3-5 claims/arguments → CONTENT-SPLIT (as body text, each claim one line)
6+ items of any kind → split into 2 slides
```

**Content is a single powerful statement or finding:**
```
A direct quote from a source → QUOTE-PULLQUOTE
A single statistic → DATA-EMPHASIS (1 stat, hero)
A surprising claim → TITLE-HERO style (large text, full-bleed background)
A key recommendation → CONTENT-SPLIT with the statement as the text and supporting evidence as the image/chart
```

---

## Design Direction Pass output

The Design Direction Pass (LLM-powered) analyzes the source content and produces:

```
DesignDirectionSpec:
  mood: str                    # "warm-historical" | "bold-technical" | "clean-professional" | "calm-medical" | "natural" | "institutional"
  palette:
    background: str            # CSS hex, maps to --slide-bg
    surface: str               # CSS hex, maps to --slide-surface
    text: str                  # CSS hex, maps to --slide-text
    accent: str                # CSS hex, maps to --slide-accent
    text_secondary: str        # CSS hex, maps to --slide-text-secondary
  heading_font: str            # font family name (must support R50 diacritics)
  body_font: str               # font family name
  decorative_font: str | null  # optional script/display font, max 2 slides
  image_style_prefix: str      # prompt prefix for AI image consistency (R23)
  background_treatment: "dark" | "light"  # dominant treatment (R15)
```

The Design Direction Pass decides aesthetics. The Layout Pass decides composition.

---

## Quality audit checklist

Every check must pass before delivery. Failures block export. Warnings are surfaced but don't block.

| # | Check | Fail/Warn | How verified |
|---|-------|-----------|--------------|
| Q1 | No text overflow | FAIL | Pretext measurement |
| Q2 | WCAG AA contrast (4.5:1) on all text | FAIL | Computed from palette |
| Q3 | Word count within type limit (R17) | FAIL | Word count per slide |
| Q4 | No consecutive layout type repeats (R01) | FAIL | Sequence check |
| Q5 | No blank/empty slides | FAIL | Content presence check |
| Q6 | Images ≥ 1920×1080 for full-bleed | WARN | Resolution check |
| Q7 | Fonts available + fallback declared | FAIL | Font availability check |
| Q8 | Language consistency (R49) | WARN | Language detection |
| Q9 | Interactive completeness (answers defined) | FAIL | Schema validation |
| Q10 | Navigation links valid (no broken hyperlinks) | FAIL | Link validation |
| Q11 | No visible boxes/cards/borders (R40) | WARN | Pattern scan |
| Q12 | Titles state takeaway, not topic (R08) | WARN | Heuristic (flags generic titles like "Results") |
| Q13 | Diacritics render correctly (R50) | FAIL | Glyph availability check |
| Q14 | No consecutive data-heavy slides (R27) | WARN | Sequence check |
| Q15 | Stat slides have variation (R06 DATA-EMPHASIS 3+ stats) | WARN | Variation check |

---

END OF NASHR PRESENTATION DESIGN LANGUAGE v2.0