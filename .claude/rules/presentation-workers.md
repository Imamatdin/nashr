---
paths:
  - "packages/workers/presentation/**"
---

# Presentation Worker Rules

- The design direction is content-driven, never template-driven. Every deck gets a unique creative brief based on its topic.
- 60-30-10 color rule is non-negotiable: 60% dominant, 30% secondary, 10% accent.
- Exactly 2 fonts per deck: one display, one body. Both must support Cyrillic + Latin Extended-A.
- No two consecutive slides use the same layout_mode.
- Max 50 words per content slide. Max 4 bullets. Min font size 18px body, 36px titles.
- AI-generated images must NEVER contain text. All text is rendered by HTML/CSS or PPTX text primitives.
- All images in one deck share the same style prompt prefix for visual consistency.
- Three primary outputs: interactive HTML, image-based PPTX (Playwright screenshots assembled via pptxgenjs), PDF via Playwright print. Native text-box PPTX is deferred until user demand is proven (per SPEC §2.2 Step 9 Mode 2).
- Interactive elements (quiz, matching, debate) are full in HTML, static with answer pages in PDF/PPTX.
- Student/teacher audience ALWAYS gets quiz + at least 1 interactive exercise.
- Quality audit runs before delivery: overflow detection, contrast ratio, empty slides, language consistency.
- Google Fonts loaded dynamically from design direction. Bundled Inter/Noto as fallback.
