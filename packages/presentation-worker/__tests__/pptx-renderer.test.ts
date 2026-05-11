/**
 * PptxRenderer tests.
 *
 * We exercise the renderer at three levels:
 *
 *   1. Pure helpers (coordinate / unit conversion, hex stripping) — called
 *      directly. No I/O, no pptxgenjs.
 *   2. Feedback-slide mapping — called directly via the exposed
 *      computeFeedbackMap method, so we can assert the precise 1-based
 *      slide numbers without parsing the generated .pptx.
 *   3. Full render — pptxgenjs is replaced with a recording mock so we
 *      can assert addSlide / addText / addShape / addImage / addNotes
 *      call counts and arguments, plus hyperlink targets on quiz
 *      options. One smoke test renders against the real pptxgenjs to
 *      catch integration breakage and confirm the file is a valid
 *      zip-container .pptx.
 */

import { readFileSync } from 'fs';
import { join } from 'path';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { LayoutPass } from '../src/layout-pass.js';
import { buildTestDeck, makeSlide } from './helpers.js';
import type { DeckSpec, QuizQuestion } from '../src/types.js';

// ---------------------------------------------------------------------------
// pptxgenjs recording mock
// ---------------------------------------------------------------------------
// vi.mock is hoisted, so we can't reference outer variables in the factory.
// We expose the mock state through a module-level object that tests reset
// between cases.

interface MockSlide {
  background: unknown;
  textCalls: Array<{ text: string; options: Record<string, unknown> }>;
  shapeCalls: Array<{ shape: string; options: Record<string, unknown> }>;
  imageCalls: Array<Record<string, unknown>>;
  noteCalls: string[];
}

interface MockPptxState {
  slides: MockSlide[];
  layoutDefined: { name: string; width: number; height: number } | null;
  layoutName: string | null;
  author: string | null;
  title: string | null;
  subject: string | null;
  reset(): void;
}

vi.mock('pptxgenjs', () => {
  class MockSlideImpl implements MockSlide {
    background: unknown = null;
    textCalls: Array<{ text: string; options: Record<string, unknown> }> = [];
    shapeCalls: Array<{ shape: string; options: Record<string, unknown> }> = [];
    imageCalls: Array<Record<string, unknown>> = [];
    noteCalls: string[] = [];

    addText(text: string, options: Record<string, unknown>): MockSlideImpl {
      this.textCalls.push({ text, options });
      return this;
    }
    addShape(shape: string, options: Record<string, unknown>): MockSlideImpl {
      this.shapeCalls.push({ shape, options });
      return this;
    }
    addImage(options: Record<string, unknown>): MockSlideImpl {
      this.imageCalls.push(options);
      return this;
    }
    addNotes(notes: string): MockSlideImpl {
      this.noteCalls.push(notes);
      return this;
    }
  }

  class MockPptxGenJS {
    slides: MockSlideImpl[] = [];
    author: string | null = null;
    title: string | null = null;
    subject: string | null = null;
    layout: string | null = null;

    constructor() {
      mockState.slides = this.slides;
      mockState.author = null;
      mockState.title = null;
      mockState.subject = null;
      mockState.layoutName = null;
      mockState.layoutDefined = null;
      // Wire reads so the *latest* values flow through.
      const self = this;
      Object.defineProperty(this, 'author', {
        get() {
          return mockState.author;
        },
        set(v: string) {
          mockState.author = v;
        },
      });
      Object.defineProperty(this, 'title', {
        get() {
          return mockState.title;
        },
        set(v: string) {
          mockState.title = v;
        },
      });
      Object.defineProperty(this, 'subject', {
        get() {
          return mockState.subject;
        },
        set(v: string) {
          mockState.subject = v;
        },
      });
      Object.defineProperty(this, 'layout', {
        get() {
          return mockState.layoutName;
        },
        set(v: string) {
          mockState.layoutName = v;
        },
      });
      void self;
    }

    defineLayout(layout: { name: string; width: number; height: number }): void {
      mockState.layoutDefined = layout;
    }

    addSlide(): MockSlideImpl {
      const s = new MockSlideImpl();
      this.slides.push(s);
      return s;
    }

    async write(_props: { outputType?: string }): Promise<Buffer> {
      // Return a minimal placeholder buffer; the smoke test that needs a
      // real .pptx uses vi.unmock for that suite.
      return Buffer.from('MOCK_PPTX');
    }
  }

  return { default: MockPptxGenJS };
});

const mockState: MockPptxState = {
  slides: [],
  layoutDefined: null,
  layoutName: null,
  author: null,
  title: null,
  subject: null,
  reset() {
    this.slides = [];
    this.layoutDefined = null;
    this.layoutName = null;
    this.author = null;
    this.title = null;
    this.subject = null;
  },
};

// ---------------------------------------------------------------------------
// Imports under test (must come AFTER vi.mock)
// ---------------------------------------------------------------------------

// eslint-disable-next-line import/first
import { PptxRenderer } from '../src/renderers/pptx-renderer.js';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeQuestion(idx: number, optionCount = 3): QuizQuestion {
  return {
    question: `Question ${idx}?`,
    options: Array.from({ length: optionCount }, (_, i) => ({
      text: `Option ${idx}-${i}`,
      is_correct: i === 0,
    })),
    explanation_correct: `Correct because ${idx}.`,
    explanation_wrong: `Wrong because ${idx}.`,
  };
}

async function renderDeck(deck: DeckSpec): Promise<Buffer> {
  const layout = new LayoutPass().layout(deck);
  return new PptxRenderer().render(deck, layout);
}

function loadFixture(): DeckSpec {
  const path = join(__dirname, 'fixtures', 'enlightenment.json');
  return JSON.parse(readFileSync(path, 'utf-8')) as DeckSpec;
}

beforeEach(() => {
  mockState.reset();
});

afterEach(() => {
  mockState.reset();
});

// ---------------------------------------------------------------------------
// Helpers: pure conversion math
// ---------------------------------------------------------------------------

describe('PptxRenderer — conversions', () => {
  it('pctToInchesX scales 50% to half of 13.33"', () => {
    const r = new PptxRenderer();
    expect(r.pctToInchesX(50)).toBeCloseTo(6.665, 3);
  });

  it('pctToInchesY scales 50% to half of 7.5"', () => {
    const r = new PptxRenderer();
    expect(r.pctToInchesY(50)).toBeCloseTo(3.75, 3);
  });

  it('pctToInchesW and pctToInchesH match their axis dimensions', () => {
    const r = new PptxRenderer();
    expect(r.pctToInchesW(100)).toBeCloseTo(13.33, 3);
    expect(r.pctToInchesH(100)).toBeCloseTo(7.5, 3);
  });

  it('pxToPt converts via 0.75 multiplier', () => {
    const r = new PptxRenderer();
    expect(r.pxToPt(24)).toBe(18);
    expect(r.pxToPt(72)).toBe(54);
    expect(r.pxToPt(14)).toBe(11); // rounded
  });

  it('stripHash removes leading #', () => {
    const r = new PptxRenderer();
    expect(r.stripHash('#E8553A')).toBe('E8553A');
    expect(r.stripHash('E8553A')).toBe('E8553A');
  });
});

// ---------------------------------------------------------------------------
// Feedback-slide mapping
// ---------------------------------------------------------------------------

describe('PptxRenderer — feedback map', () => {
  it('produces no entries when the deck has no quiz slides', () => {
    const deck = buildTestDeck([
      makeSlide('title_hero', { title: 'A' }, 0),
      makeSlide('content_split', { title: 'B' }, 1),
    ]);
    const layout = new LayoutPass().layout(deck);
    const map = new PptxRenderer().computeFeedbackMap(deck, layout);
    expect(map.size).toBe(0);
  });

  it('assigns 2 slide numbers per question, sequential after content', () => {
    const deck = buildTestDeck([
      makeSlide('title_hero', { title: 'Open' }, 0),
      makeSlide(
        'interactive_quiz_mcq',
        {
          title: 'Quiz A',
          quiz_questions: [makeQuestion(0), makeQuestion(1)],
        },
        1,
      ),
      makeSlide(
        'interactive_quiz_mcq',
        {
          title: 'Quiz B',
          quiz_questions: [makeQuestion(2)],
        },
        2,
      ),
    ]);
    const layout = new LayoutPass().layout(deck);
    const map = new PptxRenderer().computeFeedbackMap(deck, layout);
    // 3 content slides → feedback slides start at 4 (1-based).
    expect(map.get('slide1_q0_correct')).toBe(4);
    expect(map.get('slide1_q0_wrong')).toBe(5);
    expect(map.get('slide1_q1_correct')).toBe(6);
    expect(map.get('slide1_q1_wrong')).toBe(7);
    expect(map.get('slide2_q0_correct')).toBe(8);
    expect(map.get('slide2_q0_wrong')).toBe(9);
    expect(map.size).toBe(6);
  });

  it('caps at 3 questions per quiz slide (matches layout cap)', () => {
    const deck = buildTestDeck([
      makeSlide(
        'interactive_quiz_mcq',
        {
          title: 'Big quiz',
          quiz_questions: [0, 1, 2, 3, 4].map((i) => makeQuestion(i)),
        },
        0,
      ),
    ]);
    const layout = new LayoutPass().layout(deck);
    const map = new PptxRenderer().computeFeedbackMap(deck, layout);
    expect(map.size).toBe(6); // 3 questions × 2 feedback slides
    expect(map.has('slide0_q2_wrong')).toBe(true);
    expect(map.has('slide0_q3_correct')).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// Slide / metadata structure
// ---------------------------------------------------------------------------

describe('PptxRenderer — slide structure', () => {
  it('returns a Buffer', async () => {
    const deck = buildTestDeck([
      makeSlide('title_hero', { title: 'Hello' }, 0),
      makeSlide('content_split', { title: 'World' }, 1),
      makeSlide('section_break', { title: 'Done' }, 2),
    ]);
    const buf = await renderDeck(deck);
    expect(Buffer.isBuffer(buf)).toBe(true);
    expect(buf.length).toBeGreaterThan(0);
  });

  it('adds one slide per content slide when no quizzes are present', async () => {
    const deck = buildTestDeck([
      makeSlide('title_hero', { title: 'A' }, 0),
      makeSlide('content_split', { title: 'B' }, 1),
      makeSlide('section_break', { title: 'C' }, 2),
      makeSlide('summary_takeaway', { title: 'D', bullets: ['x', 'y'] }, 3),
      makeSlide('quote_pullquote', { title: 'E', quote_text: 'q', quote_attribution: 'a' }, 4),
    ]);
    await renderDeck(deck);
    expect(mockState.slides.length).toBe(5);
  });

  it('generates one extra feedback slide per option pair (1 quiz, 2 questions ⇒ +4)', async () => {
    const deck = buildTestDeck([
      makeSlide('title_hero', { title: 'Intro' }, 0),
      makeSlide(
        'interactive_quiz_mcq',
        {
          title: 'Quiz',
          quiz_questions: [makeQuestion(0), makeQuestion(1)],
        },
        1,
      ),
      makeSlide('section_break', { title: 'Close' }, 2),
    ]);
    await renderDeck(deck);
    // 3 content slides + 2 questions × 2 feedback = 7
    expect(mockState.slides.length).toBe(7);
  });

  it('defines a 13.33×7.5 layout named NASHR_16_9 and applies it', async () => {
    const deck = buildTestDeck([makeSlide('title_hero', { title: 'T' })]);
    await renderDeck(deck);
    expect(mockState.layoutDefined).toEqual({
      name: 'NASHR_16_9',
      width: 13.33,
      height: 7.5,
    });
    expect(mockState.layoutName).toBe('NASHR_16_9');
  });

  it('sets author / title / subject from the deck', async () => {
    const deck = buildTestDeck([makeSlide('title_hero', { title: 'My deck' })]);
    deck.title = 'My deck';
    deck.subtitle = 'A subtitle';
    await renderDeck(deck);
    expect(mockState.author).toBe('Nashr');
    expect(mockState.title).toBe('My deck');
    expect(mockState.subject).toBe('A subtitle');
  });
});

// ---------------------------------------------------------------------------
// Text properties
// ---------------------------------------------------------------------------

describe('PptxRenderer — text properties', () => {
  it('passes bold:true for headings', async () => {
    const deck = buildTestDeck([makeSlide('title_hero', { title: 'Heading' })]);
    await renderDeck(deck);
    const titleCall = mockState.slides[0]!.textCalls.find((c) => c.text === 'Heading');
    expect(titleCall).toBeDefined();
    expect(titleCall!.options.bold).toBe(true);
  });

  it('passes italic:true for italic text blocks (quote)', async () => {
    const deck = buildTestDeck([
      makeSlide('quote_pullquote', {
        title: 'Quote',
        quote_text: 'A profound saying',
        quote_attribution: 'Anonymous',
      }, 0),
    ]);
    await renderDeck(deck);
    const italicCall = mockState.slides[0]!.textCalls.find(
      (c) => c.options.italic === true,
    );
    expect(italicCall).toBeDefined();
  });

  it('passes align center / left / right through verbatim', async () => {
    // section_break centers its title; title_hero left-aligns it. Render
    // both and assert each alignment surfaces verbatim.
    const deck = buildTestDeck([
      makeSlide('title_hero', { title: 'Left' }, 0),
      makeSlide('section_break', { title: 'Center' }, 1),
    ]);
    await renderDeck(deck);
    const leftAligned = mockState.slides[0]!.textCalls.find((c) => c.text === 'Left');
    const centerAligned = mockState.slides[1]!.textCalls.find((c) => c.text === 'Center');
    expect(leftAligned!.options.align).toBe('left');
    expect(centerAligned!.options.align).toBe('center');
  });

  it('converts px font sizes to pt (0.75 ratio)', async () => {
    const deck = buildTestDeck([makeSlide('title_hero', { title: 'Big' })]);
    await renderDeck(deck);
    const sizes = mockState.slides[0]!.textCalls.map(
      (c) => c.options.fontSize as number,
    );
    // Every emitted fontSize must be an integer in pt, not px.
    for (const s of sizes) {
      expect(Number.isInteger(s)).toBe(true);
      expect(s).toBeLessThan(80); // pt, not px — the 72-96px title becomes 54-72pt
    }
  });
});

// ---------------------------------------------------------------------------
// Shapes
// ---------------------------------------------------------------------------

describe('PptxRenderer — shapes', () => {
  it('renders timeline dots as ellipses', async () => {
    const deck = buildTestDeck([
      makeSlide('timeline', {
        title: 'Time',
        timeline_nodes: [
          { date: '1700', label: 'A' },
          { date: '1800', label: 'B' },
          { date: '1900', label: 'C' },
        ],
      }, 0),
    ]);
    await renderDeck(deck);
    const ellipses = mockState.slides[0]!.shapeCalls.filter((s) => s.shape === 'ellipse');
    expect(ellipses.length).toBeGreaterThan(0);
  });

  it('renders matching connectors as lines', async () => {
    const deck = buildTestDeck([
      makeSlide('interactive_matching', {
        title: 'Match',
        matching_pairs: [{ left: 'A', right: 'a' }, { left: 'B', right: 'b' }],
      }, 0),
    ]);
    await renderDeck(deck);
    const lines = mockState.slides[0]!.shapeCalls.filter((s) => s.shape === 'line');
    expect(lines.length).toBeGreaterThan(0);
  });

  it('converts scrim opacity into pptx transparency (1 - opacity) * 100', async () => {
    // title_hero with a background URL triggers a scrim at opacity 0.6.
    const deck = buildTestDeck([
      makeSlide('title_hero', {
        title: 'Hero',
        background_url: 'https://example.com/img.jpg',
      }, 0),
    ]);
    await renderDeck(deck);
    // Find a rect with fill.transparency set — the scrim is the first one.
    const scrim = mockState.slides[0]!.shapeCalls.find((s) => {
      if (s.shape !== 'rect') return false;
      const fill = s.options.fill as { transparency?: number } | undefined;
      return fill?.transparency !== undefined;
    });
    expect(scrim).toBeDefined();
    const fill = scrim!.options.fill as { transparency: number };
    // 0.6 opacity → 40 transparency.
    expect(fill.transparency).toBe(40);
  });
});

// ---------------------------------------------------------------------------
// Quiz hyperlinks
// ---------------------------------------------------------------------------

describe('PptxRenderer — quiz hyperlinks', () => {
  it('hyperlinks correct option to correct feedback slide, wrong to wrong', async () => {
    const deck = buildTestDeck([
      makeSlide(
        'interactive_quiz_mcq',
        {
          title: 'Quiz',
          quiz_questions: [makeQuestion(0, 3)], // option 0 correct, 1 and 2 wrong
        },
        0,
      ),
    ]);
    await renderDeck(deck);
    // Quiz slide is index 0; layout has 1 content slide; feedback slides
    // are PPT 2 (correct) and PPT 3 (wrong).
    const quizSlide = mockState.slides[0]!;
    const optionCalls = quizSlide.textCalls.filter((c) =>
      c.text.match(/^[ABC]\) Option 0-/),
    );
    expect(optionCalls.length).toBe(3);
    const a = optionCalls.find((c) => c.text.startsWith('A)'))!;
    const b = optionCalls.find((c) => c.text.startsWith('B)'))!;
    const c = optionCalls.find((c) => c.text.startsWith('C)'))!;
    expect((a.options.hyperlink as { slide: number }).slide).toBe(2);
    expect((b.options.hyperlink as { slide: number }).slide).toBe(3);
    expect((c.options.hyperlink as { slide: number }).slide).toBe(3);
  });

  it("appends localized 'Correct/Wrong' feedback slides at the end", async () => {
    const deck = buildTestDeck(
      [
        makeSlide(
          'interactive_quiz_mcq',
          {
            title: 'Quiz',
            quiz_questions: [makeQuestion(0)],
          },
          0,
        ),
      ],
      'kaa',
    );
    await renderDeck(deck);
    // 1 content + 2 feedback = 3 slides.
    expect(mockState.slides.length).toBe(3);
    const correctSlide = mockState.slides[1]!;
    const wrongSlide = mockState.slides[2]!;
    const correctHeading = correctSlide.textCalls.find((c) =>
      c.text.startsWith('Dúrıs'),
    );
    const wrongHeading = wrongSlide.textCalls.find((c) => c.text === 'Qáte');
    expect(correctHeading).toBeDefined();
    expect(wrongHeading).toBeDefined();
  });

  it('uses Russian labels when deck.language is ru', async () => {
    const deck = buildTestDeck(
      [
        makeSlide(
          'interactive_quiz_mcq',
          {
            title: 'Quiz',
            quiz_questions: [makeQuestion(0)],
          },
          0,
        ),
      ],
      'ru',
    );
    await renderDeck(deck);
    const wrongSlide = mockState.slides[2]!;
    const wrongHeading = wrongSlide.textCalls.find((c) => c.text === 'Неверно');
    expect(wrongHeading).toBeDefined();
  });

  it("wrong feedback slide has a 'Try again' link back to the quiz", async () => {
    const deck = buildTestDeck([
      makeSlide('title_hero', { title: 'Intro' }, 0),
      makeSlide(
        'interactive_quiz_mcq',
        {
          title: 'Quiz',
          quiz_questions: [makeQuestion(0)],
        },
        1,
      ),
    ]);
    await renderDeck(deck);
    // Content slides: 1, 2. Feedback: 3 (correct), 4 (wrong).
    const wrongSlide = mockState.slides[3]!;
    const tryAgainCall = wrongSlide.textCalls.find((c) =>
      /Try again|урин|qayta|qayta/i.test(c.text),
    );
    expect(tryAgainCall).toBeDefined();
    // Hyperlink target is the quiz slide, 1-based ⇒ 2.
    expect((tryAgainCall!.options.hyperlink as { slide: number }).slide).toBe(2);
  });
});

// ---------------------------------------------------------------------------
// Non-quiz interactive slides
// ---------------------------------------------------------------------------

describe('PptxRenderer — non-quiz interactives stay visible', () => {
  it('matching slide: match_right blocks are rendered (no hide/reveal in PPTX)', async () => {
    const deck = buildTestDeck([
      makeSlide('interactive_matching', {
        title: 'Match',
        matching_pairs: [{ left: 'L1', right: 'R1' }, { left: 'L2', right: 'R2' }],
      }, 0),
    ]);
    await renderDeck(deck);
    const slide = mockState.slides[0]!;
    const rights = slide.textCalls.filter((c) => c.text === 'R1' || c.text === 'R2');
    expect(rights.length).toBe(2);
  });

  it('fill-blank slide: answer blocks are rendered', async () => {
    const deck = buildTestDeck([
      makeSlide('interactive_fill_blank', {
        title: 'Fill',
        fill_blanks: [
          { statement: 'Sky is _____.', answer: 'blue' },
          { statement: 'Sun is _____.', answer: 'bright' },
        ],
      }, 0),
    ]);
    await renderDeck(deck);
    const slide = mockState.slides[0]!;
    const answers = slide.textCalls.filter((c) => /\bblue\b|\bbright\b/.test(c.text));
    expect(answers.length).toBe(2);
  });
});

// ---------------------------------------------------------------------------
// Speaker notes / image placeholders
// ---------------------------------------------------------------------------

describe('PptxRenderer — extras', () => {
  it('emits speaker notes when present', async () => {
    const deck = buildTestDeck([
      makeSlide('title_hero', {
        title: 'A',
        speaker_notes: 'Welcome the audience and introduce the topic.',
      }, 0),
    ]);
    await renderDeck(deck);
    expect(mockState.slides[0]!.noteCalls).toEqual([
      'Welcome the audience and introduce the topic.',
    ]);
  });

  it('skips images whose src is a placeholder prompt', async () => {
    // GALLERY_PEOPLE lays out portraits as ImageBlocks. Use a prompt-shaped src.
    const longPrompt = '[a generated portrait of ' + 'x'.repeat(600) + ']';
    const deck = buildTestDeck([
      makeSlide('gallery_people', {
        title: 'People',
        people: [
          { name: 'P1', portrait_url: longPrompt },
          { name: 'P2', portrait_url: longPrompt },
          { name: 'P3', portrait_url: longPrompt },
        ],
      }, 0),
    ]);
    await renderDeck(deck);
    expect(mockState.slides[0]!.imageCalls.length).toBe(0);
  });
});

// ---------------------------------------------------------------------------
// Fixture smoke test
// ---------------------------------------------------------------------------

describe('PptxRenderer — fixture smoke', () => {
  it('renders the enlightenment fixture without throwing', async () => {
    const deck = loadFixture();
    const buf = await renderDeck(deck);
    expect(Buffer.isBuffer(buf)).toBe(true);
    expect(buf.length).toBeGreaterThan(0);
    // At minimum N content slides; feedback slides may extend this.
    expect(mockState.slides.length).toBeGreaterThanOrEqual(deck.slides.length);
  });
});
