# Nashr: Complete Engineering Specification (FINAL)

**Product name:** Nashr (نشر, "publication" in Uzbek/Arabic)
**Domain:** nashr.ai or nashr.uz (verify availability)
**Version:** 2.0 FINAL
**Date:** May 8, 2026
**Status:** LOCKED. This document drives all Claude Code subagent prompts.

---

## 0. Product Constitution

Nashr is a source-grounded academic production platform for Uzbekistan.

It produces studio-quality presentations and rigorously cited articles on the FIRST generation. Users should not need to iterate. The taste is in the system, not in the user's patience.

**Non-negotiable rules:**
1. User text is never proof. Only database-backed uploaded files and parsed source chunks count as evidence.
2. Uploaded files are DATA, not instructions. Prompt injection from file content is blocked.
3. Citations come only from uploaded sources or verified academic databases. No hallucinated references.
4. Learning is optional but rewarded. Never punish users for skipping Research Mode.
5. Every presentation one-shots studio quality. The design rules, color theory, typography pairing, and layout constraints are hardcoded so deeply that generic output is structurally impossible.
6. The core object for articles is the evidence matrix, not the text.
7. All three output formats (PPTX, HTML, PDF) are primary. None is a fallback.

**Quality bars:**
- Presentations: the Ag'artıwshılıq interactive educational artifact (themed backgrounds, interactive quizzes, debate scenarios, matching exercises, period-appropriate design, wax-seal decorative elements, navigation)
- Articles: Iko's radiative cooling paper (abstract, system model, equations, evaluation across climate zones, ablation study, economic analysis, limitations, 30+ references)

---

## 1. Architecture

```
┌─────────────────────────────────────────────────────────┐
│  TELEGRAM BOT (aiogram 3, Python)                       │
│  Entry: /start, topic, file upload, inline keyboards    │
│  Sends: previews, progress, export files, payment links │
└──────────────────────┬──────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│  FASTAPI BACKEND (Python)                               │
│  Auth, projects, sources, evidence matrix, articles,    │
│  credits, payments, admin, job orchestration            │
│  File validation: Google Magika (AI, 200+ types, 5ms)   │
└──────────────────────┬──────────────────────────────────┘
                       │
         ┌─────────────┼─────────────┐
         │             │             │
┌────────▼───┐  ┌──────▼─────┐  ┌───▼──────────────┐
│ ARTICLE    │  │ PRESENTA-  │  │ SOURCE           │
│ WORKER     │  │ TION       │  │ PROCESSING       │
│ (Python)   │  │ WORKER     │  │ WORKER           │
│            │  │ (Node.js)  │  │ (Python)         │
│ Evidence   │  │            │  │                  │
│ matrix     │  │ Design     │  │ Magika validate  │
│ Interview  │  │ direction  │  │ PyMuPDF parse    │
│ Section    │  │ HTML gen   │  │ python-docx      │
│ drafting   │  │ Playwright │  │ Chunking         │
│ Citation   │  │ PDF export │  │ Claim extraction │
│ verify     │  │ PPTX gen   │  │ DOI resolution   │
│ DOCX       │  │ pptxgenjs  │  │ Embeddings       │
│ export     │  │            │  │                  │
└────────────┘  └────────────┘  └──────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│  ACADEMIC SOURCE SERVICE                                │
│  Semantic Scholar API (214M papers, free, no auth)      │
│  arXiv API (preprints, free, 3 req/sec)                 │
│  OpenAlex API (200M works, free, no auth)               │
│  CrossRef API (DOI resolution, free)                    │
└─────────────────────────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│  INFRASTRUCTURE                                         │
│  Supabase (Postgres + Auth + Realtime + pgvector)       │
│  Redis (job queue via arq)                              │
│  Cloudflare R2 (assets, exports, user uploads)          │
│  Hetzner VPS (Docker Compose, bundled fonts, Chromium)  │
└─────────────────────────────────────────────────────────┘
```

---

## 2. Presentation Generation Pipeline

### 2.1 Philosophy: One-Shot Studio Quality

The system must produce presentation output that looks designed by a human studio on the first attempt. This is achieved by encoding professional design knowledge so deeply into the pipeline that generic output is structurally impossible.

The pipeline has 6 LLM passes, not 3. Each pass handles a distinct concern:

```
User Input
  → Research Pass (extract facts from sources)
  → Editorial Pass (narrative arc, argument structure)
  → Design Direction Pass (creative brief: colors, fonts, textures, mood)
  → Layout Pass (per-slide structure, interactivity decisions)
  → Visual Asset Pass (image generation prompts, consistency enforcement)
  → Rendering (HTML + PPTX + PDF generation)
  → Quality Audit (overflow detection, contrast check, completeness)
```

### 2.2 Step-by-Step Process

**STEP 1: Input Collection**

User sends via Telegram:
- Text topic, OR
- File upload (PDF, DOCX, PPTX, images), OR
- Both

Bot asks via inline keyboards:
- Slide count: 5-7 / 8-12 / 12-15
- Audience: Talaba (student) / O'qituvchi (teacher) / Akademik / Biznes
- Language: auto-detected from input, user can override

**STEP 2: File Validation (Magika)**

Every uploaded file passes through Google Magika before any processing:

```python
from magika import Magika
magika = Magika()

result = magika.identify_bytes(file_bytes)
# Returns: label, mime_type, group, confidence score
# Blocks: scripts, executables, archives with low confidence
# Allows: pdf, docx, pptx, png, jpeg, webp, txt, csv, markdown
# Warns: extension mismatch (invoice.pdf that's actually a DOCX)
```

Rejected files: clear error message in user's language.
Extension mismatch: warning but allow if content type is safe.

**STEP 3: Source Processing**

For each validated file:
a) PDF: PyMuPDF extracts text, page count, images, DOI from metadata
b) DOCX: python-docx extracts text, headings, tables
c) PPTX: python-pptx extracts slide text, speaker notes
d) Images: stored for potential inclusion in slides

Text is split into chunks (max 1000 tokens each) and stored as source_chunks.

If DOI is found in PDF metadata:
- Resolve via CrossRef API to get full citation metadata
- Auto-populate source record with title, authors, year, journal

**STEP 4: Research Pass**

Model: Gemini 3 Flash (fast, cheap)
Input: user topic + source chunk text (truncated to 8K tokens)
Output: structured research brief as JSON

```json
{
  "key_facts": ["...", "..."],
  "statistics": [{"value": "94.4%", "context": "water savings in Seattle"}],
  "arguments": [{"position": "...", "evidence": "..."}],
  "key_terms": [{"term": "...", "definition": "..."}],
  "people": [{"name": "...", "dates": "...", "contribution": "..."}],
  "timeline_events": [{"year": 1776, "event": "..."}]
}
```

This pass extracts raw material. It does not decide structure or design.

**STEP 5: Editorial Pass**

Model: Sonnet 4.6
Input: research brief + audience + language + slide count target
Output: narrative arc and section plan

The editorial pass commits to an argument BEFORE any design decisions.
It answers: "What is this presentation trying to say, and in what order?"

```json
{
  "title": "...",
  "subtitle": "...",
  "thesis": "...",
  "narrative_arc": "We open with X, build through Y, culminate at Z",
  "sections": [
    {"title": "...", "key_point": "...", "supporting_facts": ["..."], "slide_count": 2},
    ...
  ],
  "conclusion": "...",
  "interactive_elements": {
    "include_quiz": true,
    "quiz_questions": 3,
    "include_matching": true,
    "include_debate": false,
    "include_categorization": true
  }
}
```

Interactive elements are decided here based on audience:
- Student/Teacher audience: ALWAYS include quiz + at least 1 exercise
- Academic audience: include 1-2 discussion/review slides
- Business audience: skip quizzes, 1 interactive summary

**STEP 6: Design Direction Pass (the taste engine)**

Model: Sonnet 4.6
Input: editorial plan + topic + audience

This is where one-shot quality comes from. The LLM acts as a senior creative director who has internalized professional design rules.

System prompt encodes these rules:

**60-30-10 Color Rule:**
60% dominant color (backgrounds, large areas), 30% secondary color (content containers, cards, supporting elements), 10% accent color (highlights, key numbers, buttons, CTAs). These proportions are non-negotiable.

**Color must be thematic:**
The color palette comes from the content, not from a preset.
- History of Enlightenment? Sepia, parchment, gold, dark brown.
- Renewable energy? Forest green, sky blue, white, solar yellow.
- Fintech startup pitch? Deep navy, white, electric cyan.
- Uzbek literature? Rich burgundy, cream, calligraphy gold.
- Molecular biology? Clean white, clinical blue, specimen green.

**Typography pairing (exactly 2 fonts):**
One display font (titles, large text, can be expressive) and one body font (readable text, must be highly legible). They must contrast visually.

Examples baked into the system prompt:
- Classical/historical: Playfair Display + EB Garamond
- Modern/tech: Space Grotesk + Inter
- Academic formal: Libre Baskerville + Source Sans Pro
- Youth/energetic: Sora + DM Sans
- Uzbek calligraphic: Cormorant Garamond + Noto Sans

ALL fonts must support Cyrillic + Latin Extended-A (for Uzbek o', g').
Google Fonts loaded dynamically. Bundled Inter/Noto as fallback.

**Visual theme must match content:**
- Background treatment: texture, gradient, pattern, or full-bleed image
- Decorative elements: 2-3 repeating motifs that reinforce the topic
  (wax seals for Enlightenment, circuit traces for tech, molecules for chemistry)
- Image generation style consistency: all images in one deck share the same aesthetic
  (oil painting style, vector illustration, photography, diagram, engraving)
- Mood: 3 adjectives that guide every visual decision
  (e.g., "scholarly, warm, authoritative" or "clean, futuristic, data-driven")

**Layout variety:**
No two consecutive slides use the same layout structure. The system must alternate between: full-bleed image with text overlay, split layout (text + visual), centered text on textured background, card grid for multiple items, large stat/number hero, quote with attribution, interactive element.

**Information density rules:**
- Max 50 words per content slide
- Max 4 bullets per slide
- Minimum font size: 18px body, 36px titles
- Negative space: minimum 30% of slide area must be empty
- One main idea per slide, no exceptions

**Never generate AI images containing text.** AI text rendering is unreliable across all models. All text is rendered by HTML/CSS or PPTX text primitives.

Output: complete design direction JSON

```json
{
  "design_direction": {
    "topic_analysis": "The European Enlightenment: intellectual movement emphasizing reason",
    "mood": ["scholarly", "warm", "authoritative"],
    "color_palette": {
      "dominant_60": {"hex": "#1A120B", "name": "dark walnut", "usage": "slide backgrounds"},
      "secondary_30": {"hex": "#D4C5A9", "name": "parchment", "usage": "content panels, cards"},
      "accent_10": {"hex": "#C4923A", "name": "antique gold", "usage": "titles, key terms, icons"},
      "text_primary": "#F5F0E8",
      "text_secondary": "#A89F91"
    },
    "typography": {
      "display_font": "Playfair Display",
      "display_weight": "800",
      "body_font": "EB Garamond",
      "body_weight": "400"
    },
    "visual_theme": {
      "background_treatment": "aged parchment texture with subtle dark vignette edges",
      "decorative_elements": ["wax_seal", "manuscript_border", "quill_icon"],
      "image_style": "copper engraving, oil portrait, period-appropriate illustration",
      "image_prompt_prefix": "18th century European style, sepia toned, oil painting aesthetic, classical composition, no text in image, "
    }
  }
}
```

**STEP 7: Layout Pass**

Model: Sonnet 4.6
Input: editorial plan + design direction
Output: per-slide specification

Each slide specifies:
```json
{
  "id": "slide_03",
  "type": "content",
  "layout_mode": "split_right",
  "title": "Ag'artıwshılıq oyshılları",
  "body": [
    {"name": "Volter", "dates": "1694-1778"},
    {"name": "Sharl Monteske", "dates": "1689-1755"}
  ],
  "visual": {
    "zone": "right_40pct",
    "description": "Row of 5 portrait paintings of Enlightenment philosophers in period dress",
    "style": "oil portrait gallery format"
  },
  "background": {
    "type": "texture",
    "description": "aged manuscript with wax seal accents"
  },
  "subtitle": "Aqıl-oy, erkinlik, jamiyetlik kelisim",
  "speaker_notes": "Introduce the 5 key Enlightenment thinkers...",
  "navigation": {"prev": "slide_02", "next": "slide_04"}
}
```

Interactive slides use specialized types:
```json
{
  "id": "slide_13",
  "type": "quiz_mcq",
  "layout_mode": "quiz",
  "question": "Ag'artıwshılıq qay ásirde payda boldı?",
  "options": [
    {"id": "a", "text": "XV-XVI ásir", "correct": false},
    {"id": "b", "text": "XVII-XVIII ásir", "correct": true},
    {"id": "c", "text": "XIX-XX ásir", "correct": false}
  ],
  "feedback_correct": {"slide_id": "slide_14", "message": "Dúrıs! Jaqsı bilesiz!"},
  "feedback_wrong": {"slide_id": "slide_15", "message": "Qáte. Qayta oylanıń."},
  "background": {"type": "image", "description": "same chandelier salon scene as title slide"}
}
```

**STEP 8: Visual Asset Generation**

For every slide that needs a generated image:

Image prompt = `{design_direction.image_prompt_prefix}{slide.visual.description}. Aspect ratio 16:9. High resolution. No text, no watermarks, no logos.`

Model: Gemini 2.5 Flash Image (Nano Banana, ~$0.039/image)

**Consistency rule:** All images in one deck use the SAME prompt prefix. This forces visual coherence. A deck about the Enlightenment where one slide has an oil painting and another has a cartoon would look amateur. The prefix prevents this.

Tier limits:
- 5k UZS: 0 AI images. CSS gradients, geometric patterns, solid colors with decorative elements only.
- 10k UZS: max 2 AI images (cover + 1 key visual)
- 15k UZS: max 5 AI images

For the free tier (no images), the renderer uses:
- CSS gradients matching the design direction's color palette
- SVG geometric patterns (grid, dots, lines) as subtle textures
- CSS-rendered decorative elements (borders, dividers, shapes)
- User-uploaded images if provided

**STEP 9: Rendering (all three formats)**

The presentation worker (Node.js) generates all three primary outputs:

**A) HTML (interactive artifact):**

Single self-contained .html file:
- All CSS inlined in `<style>` tags
- All JS inlined in `<script>` tags
- Images as base64 data URIs (for offline portability) or R2 CDN URLs
- Google Fonts loaded via CDN with bundled font fallbacks
- Slide navigation: keyboard arrows, click, swipe, Artqa/Kelesi buttons
- Quiz logic: click answer, show correct/wrong slide, track score
- Matching exercise: click-to-pair interface
- Categorization: drag or click to sort
- Fill-in-the-blank: text input with check button
- Debate: click choice, reveal explanation
- Score summary at the end
- Responsive: works on desktop (projected), tablet, and phone (Telegram webview)
- @media print stylesheet for clean PDF printing

**B) PPTX (editable PowerPoint):**

Two modes:

Mode 1 (default): Image-based PPTX
- Playwright screenshots each slide from the HTML at 1920x1080
- pptxgenjs assembles each screenshot as a full-bleed slide image
- Looks identical to the HTML version
- Not text-editable in PowerPoint, but visually perfect
- Interactive elements become static (quiz shows all options listed)

Mode 2 (future, if demand): Native PPTX
- pptxgenjs constructs text boxes, shapes, images programmatically
- Text is editable in PowerPoint
- Visual quality is lower (PowerPoint rendering differs from browser)
- Build only if users actually demand editable slides

**C) PDF:**

Playwright opens the HTML file with print media query activated:
- Removes navigation buttons
- Removes interactive JS
- Shows all quiz options as static list
- Shows answers on a separate page
- `page.pdf({format: 'A4', landscape: true, printBackground: true})`
- Vector text (selectable, searchable), rasterized images

All three formats uploaded to R2 with signed URLs (7-day expiry).

**STEP 10: Quality Audit (automated)**

Before delivery, the system runs these checks:

```
CHECK 1: Text overflow
  Playwright renders each slide, checks if any text element
  exceeds its container bounds. If yes: truncate and log warning.

CHECK 2: Contrast ratio  
  For every text element: compute contrast ratio against its background.
  Minimum 4.5:1 (WCAG AA). If fail: adjust text color or add overlay.

CHECK 3: Empty slides
  No slide should have zero content. Flag and regenerate.

CHECK 4: Duplicate titles
  No two slides should have identical titles. Flag.

CHECK 5: Language consistency
  All user-facing text must be in the requested language.
  Mixed uz/ru/en only if explicitly in the source material.

CHECK 6: Image completeness
  Every slide that requested an image must have one loaded.
  If image generation failed: fall back to CSS gradient.

CHECK 7: Interactive element functionality
  For quiz slides: verify correct answer is marked.
  For matching: verify all pairs are defined.
  For navigation: verify every slide is reachable.

CHECK 8: File size
  HTML < 15MB, PDF < 20MB, PPTX < 30MB.
  If exceeded: compress images.
```

**STEP 11: Delivery**

Bot sends:
- First 3 slides as photo album (PNG previews)
- Three download buttons:
  [🌐 HTML (interaktiv)] [📄 PDF] [📊 PPTX]
- Edit prompt: "Tahrirlash: /edit_{project_id}"
- Share link: hosted HTML on nashr.ai/p/{project_id} (public, read-only)

---

## 3. Article Generation Pipeline

(Carried forward from MASTER_SPEC.md Sections 2.3.1, 2.3.2, 2.3.3 with these updates:)

### Updates to article pipeline:

1. **File validation uses Magika** (not MIME checking)
2. **Source quality classification** uses the full academic source service (Semantic Scholar, arXiv, OpenAlex, CrossRef) to verify and enrich uploaded source metadata
3. **DOI auto-resolution**: if a PDF contains a DOI, automatically resolve via CrossRef to get full citation metadata (title, authors, journal, year, volume, pages)
4. **Citation format auto-selection**: if language is uz or ru, default GOST R 7.0.5-2008. If en, default APA 7th. User can override.
5. **DOCX formatting** follows Uzbek university standards: Times New Roman 14pt, 1.5 line spacing, margins (top 2cm, bottom 2cm, left 3cm, right 1.5cm), numbered headings
6. **The reward system** is woven into the article experience, not bolted on:
   - The article visibly improves when the user answers research questions
   - Free credits are a side effect, not the main incentive
   - System says: "Javobingiz tufayli muhokama bo'limi kuchaydi" (Your answer strengthened the discussion section), not "You earned 1 credit"
   - Credits are mentioned second: "...va 1 ta bepul kredit qo'shildi"

### Article Structures (Uzbek academic formats):

**Referat (Report):**
Kirish → Asosiy qism (2-4 named sections) → Xulosa → Adabiyotlar ro'yxati

**Kurs ishi (Coursework):**
Mundarija → Kirish (dolzarblik, maqsad, vazifalar, predmet, ob'ekt) → 1-bob: Nazariy asos → 2-bob: Amaliy qism → Xulosa → Adabiyotlar → Ilovalar

**Ilmiy maqola (Research article):**
Abstract → Introduction → Literature Review → Methodology → Results → Discussion → Conclusion → References

**Hisobot (Report):**
Introduction → Background → Analysis → Findings → Recommendations → Conclusion → References

### Citation Formats:

**GOST R 7.0.5-2008** (default for uz/ru):
- Numeric in-text: [1], [2, с. 45]
- Bibliography by order of appearance
- Book: Фамилия И.О. Название. — Город: Издательство, Год. — 000 с.
- Article: Фамилия И.О. Название // Журнал. — Год. — Т. 0, № 0. — С. 00-00.
- Web: Название [Электронный ресурс]. — URL: ... (дата обращения: 00.00.0000).

**APA 7th** (default for en):
- (Author, Year) in-text, alphabetical bibliography

**IEEE** (optional):
- [1] numbered, order of citation

---

## 4. Academic Source Search Service

Four APIs, searched concurrently, deduplicated by DOI:

1. **Semantic Scholar**: 214M+ papers, free, no auth, 100 req/5 min
2. **arXiv**: preprints, free, no auth, 3 req/sec, Atom XML
3. **OpenAlex**: 200M+ works, free, no auth (alternative to Google Scholar which has NO official API)
4. **CrossRef**: DOI resolution to full citation metadata, free, no auth

User flow:
- User says "Manba kerak" or system detects thin evidence
- System searches all four APIs with topic keywords
- Presents top 8 results with title, authors, year, citation count, PDF availability
- User selects which to add
- If open access PDF exists: auto-download, process through source pipeline
- If no PDF: store metadata only, usable for citations but not claim extraction

---

## 5. File Validation with Google Magika

```python
from magika import Magika
magika = Magika()

# Allowed: pdf, docx, pptx, xlsx, png, jpeg, webp, gif, txt, markdown, csv
# Blocked: javascript, python, shell, batch, html, xml, executable, elf, pe
# Low confidence (<0.7): rejected with "File type unclear" message
# Extension mismatch: warning but allow if content type is safe
```

Magika uses a 1MB deep learning model, runs in 5ms per file on CPU, detects 200+ file types by analyzing actual content bytes. This replaces fragile MIME-type checking.

---

## 6. Payment Architecture

Payments happen OUTSIDE Telegram (to avoid Telegram Stars' 32% fee and TON withdrawal complexity).

```
Bot -> "To'lov" button -> opens web URL: https://nashr.ai/pay/{jwt_token}
Web checkout page -> user selects package + payment method (Payme/Click)
Backend creates order -> generates payment link via paytechuz library
User redirected to Payme/Click -> completes payment
Provider webhook -> backend verifies -> credits added to ledger
Bot notification: "✅ To'lov qabul qilindi!"
```

Library: `paytechuz` (Python, unified interface for Payme + Click + Atmos)

Phase 1: Payme + Click
Phase 2: add Paynet, Uzum Bank

### Pricing:

Presentations:
- Basic (no AI images): 5,000 UZS
- Standard (1-2 AI images): 10,000 UZS
- Premium (3-5 AI images): 15,000 UZS

Articles:
- Short (3-5 pages, Fast Mode): 60,000 UZS
- Standard (5-8 pages, Guided Mode): 90,000-100,000 UZS
- Research Package (8-12 pages, Research Mode + presentation): 150,000 UZS

Bundles:
- Article + Presentation: 120,000-150,000 UZS

### Credit Ledger:

Every transaction is a ledger entry, not a balance mutation:
```sql
credit_ledger (
  id, user_id, amount, reason, order_id, generation_job_id, status, created_at
)
-- Balance = SUM(amount) WHERE user_id = ? AND status = 'confirmed'
```

### Free Credits (learning rewards):

Earned by research actions, not polished answers:
- +1: uploaded 3+ valid sources
- +1: answered source-specific question with high specificity
- +1: improved weak answer after feedback
- +1: identified limitation in a source
- +2: explained contradiction between sources
- +3: completed full Research Mode

Caps: 3/day, 10/week, 5/project. Expire after 90 days. No transfer, no withdrawal.

---

## 7. Data Models

### Presentation (DeckJSON):

```python
class DesignDirection(BaseModel):
    topic_analysis: str
    mood: list[str]  # exactly 3
    color_palette: ColorPalette
    typography: TypographySpec
    visual_theme: VisualTheme

class ColorPalette(BaseModel):
    dominant_60: ColorEntry  # {hex, name, usage}
    secondary_30: ColorEntry
    accent_10: ColorEntry
    text_primary: str  # hex
    text_secondary: str  # hex

class Slide(BaseModel):
    id: str
    type: str  # content | quiz_mcq | quiz_matching | quiz_categorize | 
               # quiz_fill_blank | quiz_true_false | debate_scenario |
               # title | section_divider | closing | bibliography | timeline
    layout_mode: str  # full_bleed | split_left | split_right | centered | 
                      # grid_cards | stat_hero | quote | quiz | matching
    title: str = Field(max_length=70)
    subtitle: Optional[str] = Field(None, max_length=130)
    body: Optional[list[str]] = None  # each max 120 chars, max 4 items
    visual: Optional[VisualSpec] = None
    background: BackgroundSpec
    interactive: Optional[InteractiveSpec] = None  # for quiz/matching/debate
    speaker_notes: Optional[str] = None
    navigation: NavigationSpec

class Deck(BaseModel):
    title: str
    language: str  # auto-detected
    audience: str
    design_direction: DesignDirection
    slides: list[Slide]  # 3-20 slides
```

### Article & Evidence Matrix:

(Same as MASTER_SPEC.md Section 4.2 and 4.3, fully carried forward)

### Database Tables:

(Same as MASTER_SPEC.md Section 4.3, with addition of `design_directions` table):

```sql
design_directions (
  id uuid PRIMARY KEY,
  deck_id uuid REFERENCES decks(id),
  direction_json jsonb NOT NULL,
  created_at timestamptz DEFAULT now()
)
```

---

## 8. Cost Controls

| Job Type | Max LLM Calls | Max Images | Max Cost (USD) |
|----------|--------------|------------|----------------|
| Presentation Basic | 5 | 0 | $0.20 |
| Presentation Standard | 6 | 2 | $0.40 |
| Presentation Premium | 7 | 5 | $0.90 |
| Article Short | 8 | 0 | $0.80 |
| Article Standard | 12 | 0 | $1.50 |
| Research Package | 20 | 5 | $4.00 |

Model routing:
- Gemini 3 Flash ($0.50/$3.00 per M tokens): source parsing, claim extraction, citation verification, answer scoring, question generation
- Sonnet 4.6 ($3/$15 per M tokens): editorial, design direction, layout, article sections

Every job records: estimated_cost, actual_cost, model_calls_count, image_count, tokens_in, tokens_out.

---

## 9. Security

1. **Magika file validation** on every upload (replaces MIME checking)
2. **Prompt injection prevention**: uploaded file content is wrapped in data-only framing in every LLM call
3. **Supabase RLS** on all user-owned tables
4. **R2 buckets** private, signed URLs for downloads (7-day expiry)
5. **Rate limits**: max 10 generation jobs per user per day
6. **Job cost limits**: if any job exceeds its budget cap, stop and use partial results
7. **Payment webhook verification**: cryptographic signature check on every Payme/Click callback
8. **Admin access**: allowlisted Telegram IDs only

---

## 10. Evaluation Harness

50+ test prompts before launch:

- 10 Uzbek Latin presentations (various topics: history, science, literature, economics)
- 5 Uzbek Latin articles (referat, kurs ishi, ilmiy maqola)
- 10 Russian presentations
- 5 Russian articles
- 5 English presentations
- 5 English articles
- 5 mixed Uzbek/Russian projects
- 5 adversarial (fake sources, prompt injection in PDFs, empty files, huge files)

Per test, verify:
- [ ] Design direction is thematic and appropriate
- [ ] 60-30-10 color rule respected
- [ ] Typography is paired correctly (2 fonts max)
- [ ] No text overflow in any slide
- [ ] All three exports work (HTML interactive, PDF static, PPTX)
- [ ] Quiz interactivity works in HTML
- [ ] Uzbek special characters render (o', g', sh, ch)
- [ ] Russian Cyrillic renders
- [ ] Citations reference only real uploaded sources
- [ ] No hallucinated references
- [ ] DOCX opens in Word and LibreOffice
- [ ] Article structure matches requested format
- [ ] Bibliography format matches requested style
- [ ] Credit deduction only on success
- [ ] Failed jobs do not charge

---

## 11. Deployment

Hetzner Cloud CCX13 (4 vCPU AMD, 16GB RAM, ~14 EUR/month, Helsinki datacenter)

Docker Compose: bot, api, article-worker, presentation-worker, postgres, redis, caddy

Font bundle in presentation-worker container:
Inter, Noto Sans, Noto Serif, EB Garamond, Playfair Display, Space Grotesk, Sora, Libre Baskerville, Source Sans Pro, JetBrains Mono, Cormorant Garamond, DM Sans
(All with full Cyrillic + Latin Extended-A support)

Additional Google Fonts loaded dynamically based on design direction. Fallback to bundled fonts if CDN fails.

---

## 12. Questions for Client

1. **Academic structure**: "Siz aytgan 'ABC tuzilishi' nima aniq? Assertion-Background-Commentary? Yoki boshqa format?"
2. **Payme/Click merchant accounts**: registered or need to create?
3. **Domain preference**: nashr.ai / nashr.uz / boshqa?
4. **First users**: which professors, which university, which subjects?

---

## 13. Build Order (for Claude Code subagents)

```
WEEK 1: Foundation + Source Pipeline
  1. Database schema (Supabase migration)
  2. Magika file validation service
  3. Source upload + parsing (PyMuPDF, python-docx)
  4. Source chunking + claim extraction
  5. Academic search service (Semantic Scholar + arXiv + OpenAlex + CrossRef)
  6. DOI auto-resolution

WEEK 2: Article Engine
  7. Evidence matrix data model + builder
  8. Research interview engine (question generation, adaptive scoring)
  9. Article outline generator (all 4 Uzbek formats)
  10. Section-by-section drafter with citation grounding
  11. Citation verifier
  12. Bibliography formatter (GOST, APA, IEEE)
  13. DOCX export (python-docx, Uzbek university formatting)
  14. PDF export (LibreOffice headless conversion)

WEEK 3: Presentation Engine  
  15. Design Direction Pass (system prompt with all design rules)
  16. Layout Pass (slide-by-slide specification)
  17. Interactive slide types (quiz, matching, categorize, debate)
  18. HTML renderer (single-file artifact with all interactivity)
  19. PPTX renderer (Playwright screenshot + pptxgenjs)
  20. PDF renderer (Playwright print)
  21. Visual asset generation (Gemini API integration)
  22. Quality audit system

WEEK 4: Integration + Payments + Polish
  23. Telegram bot (aiogram 3, webhooks, conversation flow)
  24. Credit ledger + free credit reward system
  25. Payment checkout page (Payme/Click via paytechuz)
  26. Admin dashboard
  27. Evaluation harness (50+ test prompts)
  28. End-to-end testing
  29. Deployment (Docker Compose on Hetzner)
  30. Monitoring + error alerting
```
