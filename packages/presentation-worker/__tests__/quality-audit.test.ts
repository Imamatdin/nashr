/**
 * Tests for the QualityAudit (Q1–Q15).
 *
 * Most checks read SlideLayout properties produced by the Layout Pass.
 * To exercise edge cases (overflow, low contrast, empty slides) without
 * fighting the layout's overflow-reduction loop, we build SlideLayout
 * objects directly and feed them into a hand-crafted DeckLayout.
 */

import { describe, expect, it } from 'vitest';
import { readFileSync } from 'fs';
import { fileURLToPath } from 'url';
import { dirname, resolve } from 'path';
import { QualityAudit } from '../src/audit/quality-audit.js';
import { LayoutPass } from '../src/layout-pass.js';
import type {
  DeckLayout,
  DeckSpec,
  DesignDirectionSpec,
  Language,
  ShapeBlock,
  SlideBackground,
  SlideContent,
  SlideLayout,
  SlideSpec,
  SlideType,
  TextBlock,
} from '../src/types.js';

const here = dirname(fileURLToPath(import.meta.url));
const fixtureDir = resolve(here, 'fixtures');

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Design with fonts that ARE in the SAFE_FONTS list so Q7 doesn't fire. */
function safeDesign(overrides: Partial<DesignDirectionSpec> = {}): DesignDirectionSpec {
  return {
    mood: 'clean_professional',
    palette: {
      background: '#F5F0E8',
      surface: '#FAFAFA',
      text: '#2A2A2A',
      accent: '#1A3A5C',
      text_secondary: '#666666',
    },
    heading_font: 'Inter',
    body_font: 'Inter',
    decorative_font: null,
    image_style_prefix: 'clean',
    background_treatment: 'light',
    ...overrides,
  };
}

function buildDeck(
  slides: SlideSpec[],
  language: Language = 'en',
  designOverrides: Partial<DesignDirectionSpec> = {},
): DeckSpec {
  return {
    project_id: 'p-audit',
    title: 'Audit Test Deck',
    language,
    created_at: '2026-05-11T00:00:00Z',
    design: safeDesign(designOverrides),
    interview: {},
    slides,
    export_formats: ['html'],
  };
}

function makeSlide(
  index: number,
  type: SlideType,
  content: SlideContent,
): SlideSpec {
  return {
    slide_index: index,
    slide_type: type,
    content,
    source_claim_ids: [],
  };
}

function textBlock(opts: Partial<TextBlock> = {}): TextBlock {
  return {
    text: 'sample text',
    x: 5,
    y: 5,
    w: 90,
    h: 10,
    fontSize: 24,
    fontFamily: 'Inter',
    fontWeight: 'normal',
    fontStyle: 'normal',
    color: '#2A2A2A',
    align: 'left',
    lineHeight: 1.4,
    overflow: false,
    measuredHeightPct: 0,
    ...opts,
  };
}

function buildSlideLayout(opts: Partial<SlideLayout> & { slideIndex: number; slideType: SlideType }): SlideLayout {
  return {
    slideIndex: opts.slideIndex,
    slideType: opts.slideType,
    width: 1920,
    height: 1080,
    background: opts.background ?? { color: '#F5F0E8' },
    textBlocks: opts.textBlocks ?? [textBlock()],
    imageBlocks: opts.imageBlocks ?? [],
    shapes: opts.shapes ?? [],
    hasOverflow: opts.hasOverflow ?? false,
    wordCount: opts.wordCount ?? 5,
    wordLimit: opts.wordLimit ?? 60,
  };
}

function makeLayout(slides: SlideLayout[]): DeckLayout {
  return {
    slides,
    totalOverflows: slides.filter((s) => s.hasOverflow).length,
    totalWordLimitViolations: slides.filter((s) => s.wordCount > s.wordLimit).length,
  };
}

function resultsFor(audit: ReturnType<QualityAudit['audit']>, id: string) {
  return audit.results.filter((r) => r.check_id === id);
}

// ---------------------------------------------------------------------------
// Q1: Text overflow
// ---------------------------------------------------------------------------

describe('Q1 — Text overflow', () => {
  it('passes when no text block overflows', () => {
    const deck = buildDeck([makeSlide(0, 'content_split', { title: 'Hi' })]);
    const layout = makeLayout([
      buildSlideLayout({
        slideIndex: 0,
        slideType: 'content_split',
        textBlocks: [textBlock({ overflow: false })],
      }),
    ]);
    const report = new QualityAudit().audit(deck, layout);
    expect(resultsFor(report, 'Q1').every((r) => r.passed)).toBe(true);
  });

  it('fails on overflow', () => {
    const deck = buildDeck([makeSlide(0, 'content_split', { title: 'Hi' })]);
    const layout = makeLayout([
      buildSlideLayout({
        slideIndex: 0,
        slideType: 'content_split',
        textBlocks: [textBlock({ overflow: true, text: 'really long text that does not fit at all in its region' })],
      }),
    ]);
    const report = new QualityAudit().audit(deck, layout);
    const q1 = resultsFor(report, 'Q1');
    expect(q1[0].passed).toBe(false);
    expect(q1[0].severity).toBe('fail');
    expect(q1[0].slide_index).toBe(0);
  });
});

// ---------------------------------------------------------------------------
// Q2: WCAG AA contrast
// ---------------------------------------------------------------------------

describe('Q2 — WCAG AA contrast', () => {
  it('passes with high-contrast text on light bg', () => {
    const deck = buildDeck([makeSlide(0, 'content_split', { title: 'Hi' })]);
    const layout = makeLayout([
      buildSlideLayout({
        slideIndex: 0,
        slideType: 'content_split',
        background: { color: '#F5F0E8' },
        textBlocks: [textBlock({ color: '#2A2A2A' })],
      }),
    ]);
    const report = new QualityAudit().audit(deck, layout);
    expect(resultsFor(report, 'Q2').every((r) => r.passed)).toBe(true);
  });

  it('fails with low-contrast gray on white', () => {
    const deck = buildDeck([makeSlide(0, 'content_split', { title: 'Hi' })]);
    const layout = makeLayout([
      buildSlideLayout({
        slideIndex: 0,
        slideType: 'content_split',
        background: { color: '#FFFFFF' },
        textBlocks: [textBlock({ color: '#AAAAAA' })],
      }),
    ]);
    const report = new QualityAudit().audit(deck, layout);
    const q2 = resultsFor(report, 'Q2');
    expect(q2[0].passed).toBe(false);
    expect(q2[0].severity).toBe('fail');
  });

  it('computes contrast ratio correctly (black on white ≈ 21, white on white = 1)', () => {
    const audit = new QualityAudit();
    expect(audit.contrastRatio('#000000', '#FFFFFF')).toBeCloseTo(21, 0);
    expect(audit.contrastRatio('#FFFFFF', '#FFFFFF')).toBeCloseTo(1, 5);
    // Symmetry: order doesn't matter
    expect(audit.contrastRatio('#FFFFFF', '#000000')).toBeCloseTo(21, 0);
  });

  it('blends scrim color so dark scrim on light bg makes text contrast pass', () => {
    const deck = buildDeck([makeSlide(0, 'title_hero', { title: 'Hi' })]);
    // White text on light background: would fail. Adding a dark scrim at 0.7
    // opacity should yield an effective dark background and let it pass.
    const bg: SlideBackground = {
      color: '#FFFFFF',
      scrim: { direction: 'left-to-right', color: '#1A120B', opacity: 0.8, x: 0, y: 0, w: 100, h: 100 },
    };
    const layout = makeLayout([
      buildSlideLayout({
        slideIndex: 0,
        slideType: 'title_hero',
        background: bg,
        textBlocks: [textBlock({ color: '#F5F0E8' })],
      }),
    ]);
    const report = new QualityAudit().audit(deck, layout);
    expect(resultsFor(report, 'Q2')[0].passed).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// Q3: Word count
// ---------------------------------------------------------------------------

describe('Q3 — Word count', () => {
  it('passes TITLE_HERO within 15-word limit', () => {
    const deck = buildDeck([makeSlide(0, 'title_hero', { title: 'Hi' })]);
    const layout = makeLayout([
      buildSlideLayout({ slideIndex: 0, slideType: 'title_hero', wordCount: 10, wordLimit: 15 }),
    ]);
    const report = new QualityAudit().audit(deck, layout);
    expect(resultsFor(report, 'Q3').every((r) => r.passed)).toBe(true);
  });

  it('warns on TITLE_HERO over 15-word limit', () => {
    const deck = buildDeck([makeSlide(0, 'title_hero', { title: 'Hi' })]);
    const layout = makeLayout([
      buildSlideLayout({ slideIndex: 0, slideType: 'title_hero', wordCount: 20, wordLimit: 15 }),
    ]);
    const report = new QualityAudit().audit(deck, layout);
    const q3 = resultsFor(report, 'Q3');
    expect(q3[0].passed).toBe(false);
    expect(q3[0].severity).toBe('warn');
  });

  it('exempts TABLE_COMPACT (limit 999)', () => {
    const deck = buildDeck([makeSlide(0, 'table_compact', { title: 'Hi' })]);
    const layout = makeLayout([
      buildSlideLayout({ slideIndex: 0, slideType: 'table_compact', wordCount: 200, wordLimit: 999 }),
    ]);
    const report = new QualityAudit().audit(deck, layout);
    expect(resultsFor(report, 'Q3').every((r) => r.passed)).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// Q4: Consecutive layout repeats
// ---------------------------------------------------------------------------

describe('Q4 — Consecutive layout repeats', () => {
  it('passes when no two consecutive slides share a type', () => {
    const deck = buildDeck([
      makeSlide(0, 'title_hero', { title: 'A' }),
      makeSlide(1, 'content_split', { title: 'B' }),
      makeSlide(2, 'data_emphasis', { title: 'C' }),
    ]);
    const layout = makeLayout(deck.slides.map((s) => buildSlideLayout({ slideIndex: s.slide_index, slideType: s.slide_type })));
    const report = new QualityAudit().audit(deck, layout);
    expect(resultsFor(report, 'Q4').every((r) => r.passed)).toBe(true);
  });

  it('fails on consecutive same type', () => {
    const deck = buildDeck([
      makeSlide(0, 'content_split', { title: 'A' }),
      makeSlide(1, 'content_split', { title: 'B' }),
    ]);
    const layout = makeLayout(deck.slides.map((s) => buildSlideLayout({ slideIndex: s.slide_index, slideType: s.slide_type })));
    const report = new QualityAudit().audit(deck, layout);
    const q4 = resultsFor(report, 'Q4');
    const fails = q4.filter((r) => !r.passed);
    expect(fails).toHaveLength(1);
    expect(fails[0].slide_index).toBe(1);
  });
});

// ---------------------------------------------------------------------------
// Q5: Empty slides
// ---------------------------------------------------------------------------

describe('Q5 — Empty slides', () => {
  it('passes when every slide has content', () => {
    const deck = buildDeck([makeSlide(0, 'content_split', { title: 'Hi' })]);
    const layout = makeLayout([
      buildSlideLayout({
        slideIndex: 0,
        slideType: 'content_split',
        textBlocks: [textBlock()],
      }),
    ]);
    const report = new QualityAudit().audit(deck, layout);
    expect(resultsFor(report, 'Q5').every((r) => r.passed)).toBe(true);
  });

  it('fails on an empty slide (no text, images, or shapes)', () => {
    const deck = buildDeck([makeSlide(0, 'content_split', { title: '' })]);
    const layout = makeLayout([
      buildSlideLayout({
        slideIndex: 0,
        slideType: 'content_split',
        textBlocks: [],
        imageBlocks: [],
        shapes: [],
      }),
    ]);
    const report = new QualityAudit().audit(deck, layout);
    const fails = resultsFor(report, 'Q5').filter((r) => !r.passed);
    expect(fails).toHaveLength(1);
    expect(fails[0].slide_index).toBe(0);
  });
});

// ---------------------------------------------------------------------------
// Q7: Font availability
// ---------------------------------------------------------------------------

describe('Q7 — Font availability', () => {
  it('passes with safe fonts (Noto Serif + Inter)', () => {
    const deck = buildDeck(
      [makeSlide(0, 'title_hero', { title: 'Hi' })],
      'en',
      { heading_font: 'Noto Serif', body_font: 'Inter' },
    );
    const layout = makeLayout([buildSlideLayout({ slideIndex: 0, slideType: 'title_hero' })]);
    const report = new QualityAudit().audit(deck, layout);
    expect(resultsFor(report, 'Q7').every((r) => r.passed)).toBe(true);
  });

  it('fails on unknown font ("Papyrus")', () => {
    const deck = buildDeck(
      [makeSlide(0, 'title_hero', { title: 'Hi' })],
      'en',
      { heading_font: 'Papyrus', body_font: 'Inter' },
    );
    const layout = makeLayout([buildSlideLayout({ slideIndex: 0, slideType: 'title_hero' })]);
    const report = new QualityAudit().audit(deck, layout);
    const fails = resultsFor(report, 'Q7').filter((r) => !r.passed);
    expect(fails.length).toBeGreaterThan(0);
    expect(fails[0].severity).toBe('fail');
  });

  it('passes Design Language classical pairing (Playfair Display + EB Garamond)', () => {
    const deck = buildDeck(
      [makeSlide(0, 'title_hero', { title: 'Hi' })],
      'en',
      { heading_font: 'Playfair Display', body_font: 'EB Garamond' },
    );
    const layout = makeLayout([buildSlideLayout({ slideIndex: 0, slideType: 'title_hero' })]);
    const report = new QualityAudit().audit(deck, layout);
    expect(resultsFor(report, 'Q7').every((r) => r.passed)).toBe(true);
  });

  it('passes Design Language tech pairing (Space Grotesk + Inter)', () => {
    const deck = buildDeck(
      [makeSlide(0, 'title_hero', { title: 'Hi' })],
      'en',
      { heading_font: 'Space Grotesk', body_font: 'Inter' },
    );
    const layout = makeLayout([buildSlideLayout({ slideIndex: 0, slideType: 'title_hero' })]);
    const report = new QualityAudit().audit(deck, layout);
    expect(resultsFor(report, 'Q7').every((r) => r.passed)).toBe(true);
  });

  it('passes canonical fixtures (no Q7 font failures on enlightenment + minimal-deck)', () => {
    for (const name of ['enlightenment.json', 'minimal-deck.json']) {
      const deck = JSON.parse(readFileSync(resolve(fixtureDir, name), 'utf-8')) as DeckSpec;
      const layout = new LayoutPass().layout(deck);
      const report = new QualityAudit().audit(deck, layout);
      const q7 = resultsFor(report, 'Q7');
      expect(q7.every((r) => r.passed), `Q7 failures in ${name}: ${JSON.stringify(q7.filter((r) => !r.passed))}`).toBe(true);
    }
  });
});

// ---------------------------------------------------------------------------
// Q8: Language consistency
// ---------------------------------------------------------------------------

describe('Q8 — Language consistency', () => {
  it('passes with all-Latin titles', () => {
    const deck = buildDeck([
      makeSlide(0, 'title_hero', { title: 'Hello world' }),
      makeSlide(1, 'content_split', { title: 'Reason replaces revelation' }),
    ]);
    const layout = makeLayout(deck.slides.map((s) => buildSlideLayout({ slideIndex: s.slide_index, slideType: s.slide_type })));
    const report = new QualityAudit().audit(deck, layout);
    expect(resultsFor(report, 'Q8').every((r) => r.passed)).toBe(true);
  });

  it('warns when titles mix Cyrillic and Latin', () => {
    const deck = buildDeck([
      makeSlide(0, 'title_hero', { title: 'Hello world' }),
      makeSlide(1, 'content_split', { title: 'Привет мир' }),
    ]);
    const layout = makeLayout(deck.slides.map((s) => buildSlideLayout({ slideIndex: s.slide_index, slideType: s.slide_type })));
    const report = new QualityAudit().audit(deck, layout);
    const q8 = resultsFor(report, 'Q8');
    expect(q8[0].passed).toBe(false);
    expect(q8[0].severity).toBe('warn');
  });
});

// ---------------------------------------------------------------------------
// Q9: Interactive completeness
// ---------------------------------------------------------------------------

describe('Q9 — Interactive completeness', () => {
  it('passes with a complete quiz', () => {
    const deck = buildDeck([
      makeSlide(0, 'interactive_quiz_mcq', {
        title: 'Quiz',
        quiz_questions: [
          {
            question: 'What is 2+2?',
            options: [
              { text: '3', is_correct: false },
              { text: '4', is_correct: true },
            ],
            explanation_correct: 'Yes',
            explanation_wrong: 'No',
          },
        ],
      }),
    ]);
    const layout = makeLayout([buildSlideLayout({ slideIndex: 0, slideType: 'interactive_quiz_mcq' })]);
    const report = new QualityAudit().audit(deck, layout);
    expect(resultsFor(report, 'Q9').every((r) => r.passed)).toBe(true);
  });

  it('fails when no option is marked correct', () => {
    const deck = buildDeck([
      makeSlide(0, 'interactive_quiz_mcq', {
        title: 'Q',
        quiz_questions: [
          {
            question: 'What?',
            options: [
              { text: 'a', is_correct: false },
              { text: 'b', is_correct: false },
            ],
            explanation_correct: 'x',
            explanation_wrong: 'y',
          },
        ],
      }),
    ]);
    const layout = makeLayout([buildSlideLayout({ slideIndex: 0, slideType: 'interactive_quiz_mcq' })]);
    const report = new QualityAudit().audit(deck, layout);
    const fails = resultsFor(report, 'Q9').filter((r) => !r.passed);
    expect(fails.length).toBeGreaterThan(0);
  });

  it('fails empty matching slide', () => {
    const deck = buildDeck([
      makeSlide(0, 'interactive_matching', { title: 'Match', matching_pairs: [] }),
    ]);
    const layout = makeLayout([buildSlideLayout({ slideIndex: 0, slideType: 'interactive_matching' })]);
    const report = new QualityAudit().audit(deck, layout);
    expect(resultsFor(report, 'Q9').some((r) => !r.passed)).toBe(true);
  });

  it('fails debate with fewer than 2 positions', () => {
    const deck = buildDeck([
      makeSlide(0, 'interactive_debate', {
        title: 'Debate',
        debate_prompt: 'Discuss',
        debate_options: [{ position: 'one', framework_label: 'utilitarian' }],
      }),
    ]);
    const layout = makeLayout([buildSlideLayout({ slideIndex: 0, slideType: 'interactive_debate' })]);
    const report = new QualityAudit().audit(deck, layout);
    expect(resultsFor(report, 'Q9').some((r) => !r.passed)).toBe(true);
  });

  it('fails categorize with no labels or items', () => {
    const deck = buildDeck([
      makeSlide(0, 'interactive_categorize', { title: 'Cat', category_labels: [], category_items: [] }),
    ]);
    const layout = makeLayout([buildSlideLayout({ slideIndex: 0, slideType: 'interactive_categorize' })]);
    const report = new QualityAudit().audit(deck, layout);
    expect(resultsFor(report, 'Q9').some((r) => !r.passed)).toBe(true);
  });

  it('fails fill_blank with missing answer', () => {
    const deck = buildDeck([
      makeSlide(0, 'interactive_fill_blank', {
        title: 'Fill',
        fill_blanks: [{ statement: 'The capital of France is ___', answer: '' }],
      }),
    ]);
    const layout = makeLayout([buildSlideLayout({ slideIndex: 0, slideType: 'interactive_fill_blank' })]);
    const report = new QualityAudit().audit(deck, layout);
    expect(resultsFor(report, 'Q9').some((r) => !r.passed)).toBe(true);
  });

  it('fails true_false missing explanation', () => {
    const deck = buildDeck([
      makeSlide(0, 'interactive_true_false', {
        title: 'TF',
        true_false_items: [{ statement: 'Sky is blue', is_true: true, explanation: '' }],
      }),
    ]);
    const layout = makeLayout([buildSlideLayout({ slideIndex: 0, slideType: 'interactive_true_false' })]);
    const report = new QualityAudit().audit(deck, layout);
    expect(resultsFor(report, 'Q9').some((r) => !r.passed)).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// Q10: Navigation links
// ---------------------------------------------------------------------------

describe('Q10 — Navigation links', () => {
  it('passes when quiz has explanations on every question', () => {
    const deck = buildDeck([
      makeSlide(0, 'interactive_quiz_mcq', {
        title: 'Q',
        quiz_questions: [
          {
            question: 'What?',
            options: [
              { text: 'a', is_correct: true },
              { text: 'b', is_correct: false },
            ],
            explanation_correct: 'Yes',
            explanation_wrong: 'No',
          },
        ],
      }),
    ]);
    const layout = makeLayout([buildSlideLayout({ slideIndex: 0, slideType: 'interactive_quiz_mcq' })]);
    const report = new QualityAudit().audit(deck, layout);
    expect(resultsFor(report, 'Q10').every((r) => r.passed)).toBe(true);
  });

  it('fails when explanation_wrong is missing', () => {
    const deck = buildDeck([
      makeSlide(0, 'interactive_quiz_mcq', {
        title: 'Q',
        quiz_questions: [
          {
            question: 'What?',
            options: [
              { text: 'a', is_correct: true },
              { text: 'b', is_correct: false },
            ],
            explanation_correct: 'Yes',
            explanation_wrong: '',
          },
        ],
      }),
    ]);
    const layout = makeLayout([buildSlideLayout({ slideIndex: 0, slideType: 'interactive_quiz_mcq' })]);
    const report = new QualityAudit().audit(deck, layout);
    const fails = resultsFor(report, 'Q10').filter((r) => !r.passed);
    expect(fails.length).toBeGreaterThan(0);
  });
});

// ---------------------------------------------------------------------------
// Q11: No visible boxes
// ---------------------------------------------------------------------------

describe('Q11 — No visible boxes', () => {
  it('passes when no large opaque rectangles exist', () => {
    const deck = buildDeck([makeSlide(0, 'content_split', { title: 'Hi' })]);
    const layout = makeLayout([buildSlideLayout({ slideIndex: 0, slideType: 'content_split', shapes: [] })]);
    const report = new QualityAudit().audit(deck, layout);
    expect(resultsFor(report, 'Q11').every((r) => r.passed)).toBe(true);
  });

  it('warns on a large filled rectangle', () => {
    const deck = buildDeck([makeSlide(0, 'content_split', { title: 'Hi' })]);
    const cardShape: ShapeBlock = {
      type: 'rect',
      x: 10,
      y: 10,
      w: 60,
      h: 50,
      fill: '#FFFFFF',
      opacity: 0.5,
    };
    const layout = makeLayout([
      buildSlideLayout({ slideIndex: 0, slideType: 'content_split', shapes: [cardShape] }),
    ]);
    const report = new QualityAudit().audit(deck, layout);
    const warns = resultsFor(report, 'Q11').filter((r) => !r.passed);
    expect(warns.length).toBeGreaterThan(0);
    expect(warns[0].severity).toBe('warn');
  });
});

// ---------------------------------------------------------------------------
// Q12: Takeaway titles
// ---------------------------------------------------------------------------

describe('Q12 — Takeaway titles', () => {
  it('passes a descriptive title', () => {
    const deck = buildDeck([
      makeSlide(0, 'content_split', { title: 'GDP grew 5.6% in 2023' }),
    ]);
    const layout = makeLayout([buildSlideLayout({ slideIndex: 0, slideType: 'content_split' })]);
    const report = new QualityAudit().audit(deck, layout);
    expect(resultsFor(report, 'Q12').every((r) => r.passed)).toBe(true);
  });

  it('warns on a generic one-word title ("Results")', () => {
    const deck = buildDeck([
      makeSlide(0, 'content_split', { title: 'Results' }),
    ]);
    const layout = makeLayout([buildSlideLayout({ slideIndex: 0, slideType: 'content_split' })]);
    const report = new QualityAudit().audit(deck, layout);
    const warns = resultsFor(report, 'Q12').filter((r) => !r.passed);
    expect(warns).toHaveLength(1);
    expect(warns[0].severity).toBe('warn');
  });

  it('skips SECTION_BREAK slides', () => {
    const deck = buildDeck([
      makeSlide(0, 'section_break', { title: 'Results' }),
    ]);
    const layout = makeLayout([buildSlideLayout({ slideIndex: 0, slideType: 'section_break' })]);
    const report = new QualityAudit().audit(deck, layout);
    expect(resultsFor(report, 'Q12').every((r) => r.passed)).toBe(true);
  });

  it('skips interactive slides', () => {
    const deck = buildDeck([
      makeSlide(0, 'interactive_quiz_mcq', { title: 'Quiz' }),
    ]);
    const layout = makeLayout([buildSlideLayout({ slideIndex: 0, slideType: 'interactive_quiz_mcq' })]);
    const report = new QualityAudit().audit(deck, layout);
    expect(resultsFor(report, 'Q12').every((r) => r.passed)).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// Q13: Diacritics
// ---------------------------------------------------------------------------

describe('Q13 — Diacritics', () => {
  it('passes Karakalpak deck with diacritics in titles', () => {
    const deck = buildDeck(
      [makeSlide(0, 'title_hero', { title: 'Aǵartıwshılıq' })],
      'kaa',
    );
    const layout = makeLayout([buildSlideLayout({ slideIndex: 0, slideType: 'title_hero' })]);
    const report = new QualityAudit().audit(deck, layout);
    expect(resultsFor(report, 'Q13').every((r) => r.passed)).toBe(true);
  });

  it('fails Karakalpak deck with only plain ASCII titles', () => {
    const deck = buildDeck(
      [makeSlide(0, 'title_hero', { title: 'Hello World' })],
      'kaa',
    );
    const layout = makeLayout([buildSlideLayout({ slideIndex: 0, slideType: 'title_hero' })]);
    const report = new QualityAudit().audit(deck, layout);
    const fails = resultsFor(report, 'Q13').filter((r) => !r.passed);
    expect(fails).toHaveLength(1);
    expect(fails[0].severity).toBe('fail');
  });

  it('skips non-Karakalpak decks (English passes regardless)', () => {
    const deck = buildDeck(
      [makeSlide(0, 'title_hero', { title: 'Hello World' })],
      'en',
    );
    const layout = makeLayout([buildSlideLayout({ slideIndex: 0, slideType: 'title_hero' })]);
    const report = new QualityAudit().audit(deck, layout);
    expect(resultsFor(report, 'Q13').every((r) => r.passed)).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// Q14: Consecutive data slides
// ---------------------------------------------------------------------------

describe('Q14 — Consecutive data slides', () => {
  it('passes when data slides are separated by breathing slides', () => {
    const deck = buildDeck([
      makeSlide(0, 'data_emphasis', { title: 'A' }),
      makeSlide(1, 'content_split', { title: 'B' }),
      makeSlide(2, 'chart_data', { title: 'C' }),
    ]);
    const layout = makeLayout(deck.slides.map((s) => buildSlideLayout({ slideIndex: s.slide_index, slideType: s.slide_type })));
    const report = new QualityAudit().audit(deck, layout);
    expect(resultsFor(report, 'Q14').every((r) => r.passed)).toBe(true);
  });

  it('warns on two data-heavy slides in a row', () => {
    const deck = buildDeck([
      makeSlide(0, 'data_emphasis', { title: 'A' }),
      makeSlide(1, 'chart_data', { title: 'B' }),
    ]);
    const layout = makeLayout(deck.slides.map((s) => buildSlideLayout({ slideIndex: s.slide_index, slideType: s.slide_type })));
    const report = new QualityAudit().audit(deck, layout);
    const warns = resultsFor(report, 'Q14').filter((r) => !r.passed);
    expect(warns).toHaveLength(1);
    expect(warns[0].severity).toBe('warn');
  });
});

// ---------------------------------------------------------------------------
// Q15: Stat variation
// ---------------------------------------------------------------------------

describe('Q15 — Stat variation', () => {
  it('passes when 3 stats include a highlight + trend', () => {
    const deck = buildDeck([
      makeSlide(0, 'data_emphasis', {
        title: 'Stats',
        stats: [
          { value: '94', unit: '%', label: 'savings', highlight: true },
          { value: '12', unit: 'x', label: 'cycles', trend: '↑' },
          { value: '4', unit: 'yrs', label: 'payback' },
        ],
      }),
    ]);
    const layout = makeLayout([buildSlideLayout({ slideIndex: 0, slideType: 'data_emphasis' })]);
    const report = new QualityAudit().audit(deck, layout);
    expect(resultsFor(report, 'Q15').every((r) => r.passed)).toBe(true);
  });

  it('warns on 3 identical stats (no variation)', () => {
    const deck = buildDeck([
      makeSlide(0, 'data_emphasis', {
        title: 'Stats',
        stats: [
          { value: '1', unit: 'a', label: 'one' },
          { value: '2', unit: 'b', label: 'two' },
          { value: '3', unit: 'c', label: 'three' },
        ],
      }),
    ]);
    const layout = makeLayout([buildSlideLayout({ slideIndex: 0, slideType: 'data_emphasis' })]);
    const report = new QualityAudit().audit(deck, layout);
    const warns = resultsFor(report, 'Q15').filter((r) => !r.passed);
    expect(warns).toHaveLength(1);
    expect(warns[0].severity).toBe('warn');
  });

  it('skips slides with fewer than 3 stats', () => {
    const deck = buildDeck([
      makeSlide(0, 'data_emphasis', {
        title: 'Stats',
        stats: [
          { value: '1', unit: 'a', label: 'one' },
          { value: '2', unit: 'b', label: 'two' },
        ],
      }),
    ]);
    const layout = makeLayout([buildSlideLayout({ slideIndex: 0, slideType: 'data_emphasis' })]);
    const report = new QualityAudit().audit(deck, layout);
    expect(resultsFor(report, 'Q15').every((r) => r.passed)).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// Full-audit integration
// ---------------------------------------------------------------------------

describe('Full audit', () => {
  it('reports is_exportable=true on a clean deck', () => {
    const deck = buildDeck([
      makeSlide(0, 'title_hero', { title: 'Opening' }),
      makeSlide(1, 'content_split', { title: 'Reason replaces revelation' }),
    ]);
    const layout = makeLayout(deck.slides.map((s) => buildSlideLayout({ slideIndex: s.slide_index, slideType: s.slide_type })));
    const report = new QualityAudit().audit(deck, layout);
    expect(report.is_exportable).toBe(true);
    expect(report.failed).toBe(0);
  });

  it('blocks export on a Q1 (overflow) failure', () => {
    const deck = buildDeck([makeSlide(0, 'content_split', { title: 'Hi' })]);
    const layout = makeLayout([
      buildSlideLayout({
        slideIndex: 0,
        slideType: 'content_split',
        textBlocks: [textBlock({ overflow: true })],
      }),
    ]);
    const report = new QualityAudit().audit(deck, layout);
    expect(report.is_exportable).toBe(false);
    expect(report.failed).toBeGreaterThan(0);
  });

  it('is exportable when only warnings are present (Q12)', () => {
    const deck = buildDeck([
      makeSlide(0, 'title_hero', { title: 'Opening' }),
      makeSlide(1, 'content_split', { title: 'Results' }),
    ]);
    const layout = makeLayout(deck.slides.map((s) => buildSlideLayout({ slideIndex: s.slide_index, slideType: s.slide_type })));
    const report = new QualityAudit().audit(deck, layout);
    expect(report.is_exportable).toBe(true);
    expect(report.warnings).toBeGreaterThan(0);
  });

  it('runs cleanly against enlightenment.json fixture (no crash)', () => {
    const raw = readFileSync(resolve(fixtureDir, 'enlightenment.json'), 'utf-8');
    const deck = JSON.parse(raw) as DeckSpec;
    const layout = new LayoutPass().layout(deck);
    const report = new QualityAudit().audit(deck, layout);
    expect(report.results.length).toBeGreaterThan(0);
    expect(typeof report.is_exportable).toBe('boolean');
  });
});
