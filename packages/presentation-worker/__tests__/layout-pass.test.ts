import { describe, expect, it } from 'vitest';
import { readFileSync } from 'fs';
import { fileURLToPath } from 'url';
import { dirname, resolve } from 'path';
import { LayoutPass } from '../src/layout-pass.js';
import { FONT_SIZES, SLIDE_HEIGHT, SLIDE_WIDTH, WORD_LIMITS } from '../src/constants.js';
import type {
  ComparisonColumn,
  DeckSpec,
  PersonItem,
  SlideContent,
  SlideSpec,
  SlideType,
  StatItem,
  TextBlock,
} from '../src/types.js';

const here = dirname(fileURLToPath(import.meta.url));
const fixtureDir = resolve(here, 'fixtures');

function loadDeckFixture(): DeckSpec {
  const raw = readFileSync(resolve(fixtureDir, 'enlightenment.json'), 'utf-8');
  return JSON.parse(raw) as DeckSpec;
}

function buildDeck(slides: SlideSpec[], language: 'en' | 'uz' | 'ru' = 'en'): DeckSpec {
  return {
    project_id: 'p-test',
    title: 'Test deck',
    language,
    created_at: '2026-05-11T12:00:00Z',
    design: {
      mood: 'bold_technical',
      palette: {
        background: '#0D0D12',
        surface: '#1A1A22',
        text: '#F5F0E8',
        accent: '#E8553A',
        text_secondary: '#A89F91',
      },
      heading_font: 'Inter',
      body_font: 'Inter',
      decorative_font: null,
      image_style_prefix: 'technical diagram',
      background_treatment: 'dark',
    },
    interview: {},
    slides,
    export_formats: ['html'],
  };
}

function makeSlide(
  index: number,
  type: SlideType,
  content: SlideContent,
  extras: Partial<SlideSpec> = {},
): SlideSpec {
  return {
    slide_index: index,
    slide_type: type,
    content,
    source_claim_ids: [],
    ...extras,
  };
}

function findBlock(blocks: TextBlock[], substring: string): TextBlock | undefined {
  return blocks.find((b) => b.text.includes(substring));
}

describe('LayoutPass.layoutSlide — TITLE_HERO', () => {
  it('places title in displayJumbo tier and includes subtitle when present', () => {
    const deck = buildDeck([
      makeSlide(0, 'title_hero', {
        title: 'Hello world',
        subtitle: 'A subtitle',
        caption: 'caption text',
      }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    expect(layout.slideType).toBe('title_hero');

    const title = findBlock(layout.textBlocks, 'Hello world');
    expect(title).toBeDefined();
    // displayJumbo tier max is 96; expect a starting size at the top of the
    // tier when the text is short enough to fit there.
    expect(title!.fontSize).toBeGreaterThanOrEqual(FONT_SIZES.displayJumbo.min);
    expect(title!.fontSize).toBeLessThanOrEqual(FONT_SIZES.displayJumbo.max);

    const subtitle = findBlock(layout.textBlocks, 'A subtitle');
    expect(subtitle).toBeDefined();
    expect(subtitle!.fontStyle).toBe('italic');

    expect(layout.background.color).toBeDefined();
  });

  it('adds a full-bleed image and scrim when background_url is provided', () => {
    const deck = buildDeck([
      makeSlide(0, 'title_hero', {
        title: 'Hero',
        background_url: 'https://example.com/bg.jpg',
      }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    expect(layout.background.image).toBeDefined();
    expect(layout.background.image!.isBackground).toBe(true);
    expect(layout.background.scrim).toBeDefined();
  });
});

describe('LayoutPass.layoutSlide — CONTENT_SPLIT', () => {
  it('places title and body in the left half and image in the right half', () => {
    const deck = buildDeck([
      makeSlide(0, 'content_split', {
        title: 'A concept title',
        body_text: 'A short body that fits on one line.',
        bullets: ['First claim', 'Second claim'],
        background_url: 'https://example.com/side.jpg',
      }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);

    const title = findBlock(layout.textBlocks, 'A concept title');
    expect(title).toBeDefined();
    expect(title!.x).toBeLessThan(50);
    expect(title!.w).toBeLessThanOrEqual(50);

    expect(layout.imageBlocks).toHaveLength(1);
    expect(layout.imageBlocks[0]!.x).toBeGreaterThanOrEqual(50);
  });
});

describe('LayoutPass.layoutSlide — DATA_EMPHASIS', () => {
  it('centers a single hero stat with displayJumbo number size', () => {
    const stats: StatItem[] = [
      { value: '94.4', unit: '%', label: 'water savings', highlight: true },
    ];
    const deck = buildDeck([
      makeSlide(0, 'data_emphasis', { title: 'Headline result', stats }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);

    const numberBlock = findBlock(layout.textBlocks, '94.4');
    expect(numberBlock).toBeDefined();
    expect(numberBlock!.fontSize).toBeGreaterThanOrEqual(FONT_SIZES.displayJumbo.min);
    expect(numberBlock!.x).toBe(25);
    expect(numberBlock!.w).toBe(50);
  });

  it('spreads three stats across three columns', () => {
    const stats: StatItem[] = [
      { value: '28', unit: 'vols', label: 'Encyclopedie' },
      { value: '150K', unit: '', label: 'subscribers' },
      { value: '75', unit: 'yrs', label: 'span' },
    ];
    const deck = buildDeck([
      makeSlide(0, 'data_emphasis', { title: 'In numbers', stats }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    const labelXs = layout.textBlocks
      .filter((b) => b.text === 'Encyclopedie' || b.text === 'subscribers' || b.text === 'span')
      .map((b) => b.x)
      .sort((a, b) => a - b);
    expect(labelXs).toHaveLength(3);
    expect(labelXs[2]! - labelXs[0]!).toBeGreaterThan(30);
  });
});

describe('LayoutPass.layoutSlide — SECTION_BREAK', () => {
  it('centers the section title and produces no body blocks', () => {
    const deck = buildDeck([
      makeSlide(0, 'section_break', { title: 'Part II: Legacy' }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    const title = findBlock(layout.textBlocks, 'Part II: Legacy');
    expect(title).toBeDefined();
    expect(title!.align).toBe('center');
    expect(layout.textBlocks).toHaveLength(1);
  });

  it('uses the accent colour for the background and the deck background for the text (R03 inversion)', () => {
    const deck = buildDeck([
      makeSlide(0, 'section_break', { title: 'Part II: Legacy' }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    expect(layout.background.color).toBe(deck.design.palette.accent);
    const title = findBlock(layout.textBlocks, 'Part II: Legacy')!;
    expect(title.color).toBe(deck.design.palette.background);
  });
});

describe('LayoutPass.layoutSlide — GALLERY_PEOPLE', () => {
  it('produces one image plus a name caption for each person', () => {
    const people: PersonItem[] = [
      {
        name: 'Voltaire',
        years: '1694-1778',
        portrait_url: 'https://example.com/v.jpg',
      },
      {
        name: 'Kant',
        years: '1724-1804',
        portrait_url: 'https://example.com/k.jpg',
      },
      {
        name: 'Rousseau',
        years: '1712-1778',
        portrait_url: 'https://example.com/r.jpg',
      },
    ];
    const deck = buildDeck([
      makeSlide(0, 'gallery_people', { title: 'Five thinkers', people }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);

    expect(layout.imageBlocks).toHaveLength(3);
    expect(findBlock(layout.textBlocks, 'Voltaire')).toBeDefined();
    expect(findBlock(layout.textBlocks, 'Kant')).toBeDefined();
    expect(findBlock(layout.textBlocks, 'Rousseau')).toBeDefined();
  });
});

describe('LayoutPass.layoutSlide — COMPARISON', () => {
  it('routes left column to x<50% and right column to x>=50%', () => {
    const left: ComparisonColumn = {
      heading: 'Radical',
      points: ['Materialist', 'Democratic'],
    };
    const right: ComparisonColumn = {
      heading: 'Moderate',
      points: ['Deist', 'Constitutional'],
      is_preferred: true,
    };
    const deck = buildDeck([
      makeSlide(0, 'comparison', {
        title: 'Two strands',
        left_column: left,
        right_column: right,
      }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);

    const radical = findBlock(layout.textBlocks, 'Radical');
    const moderate = findBlock(layout.textBlocks, 'Moderate');
    expect(radical).toBeDefined();
    expect(moderate).toBeDefined();
    expect(radical!.x).toBeLessThan(50);
    expect(moderate!.x).toBeGreaterThanOrEqual(50);
    expect(moderate!.color).toBe(deck.design.palette.accent);
  });
});

describe('LayoutPass.layoutSlide — QUOTE_PULLQUOTE', () => {
  it('renders the quote in italic body font with an attribution', () => {
    const deck = buildDeck([
      makeSlide(0, 'quote_pullquote', {
        title: 'placeholder',
        quote_text: 'Dare to know.',
        quote_attribution: 'Kant',
      }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    const quote = findBlock(layout.textBlocks, 'Dare to know.');
    expect(quote).toBeDefined();
    expect(quote!.fontStyle).toBe('italic');
    expect(findBlock(layout.textBlocks, 'Kant')).toBeDefined();
  });
});

describe('LayoutPass.layoutSlide — SUMMARY_TAKEAWAY', () => {
  it('emits one block per bullet', () => {
    const deck = buildDeck([
      makeSlide(0, 'summary_takeaway', {
        title: 'Takeaways',
        bullets: ['First point', 'Second point', 'Third point'],
      }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    const bulletBlocks = layout.textBlocks.filter((b) => b.text.startsWith('• '));
    expect(bulletBlocks).toHaveLength(3);
  });
});

describe('LayoutPass overflow handling', () => {
  it('reduces font size for a title that does not fit at the tier maximum', () => {
    const massiveTitle =
      'This is an unusually long slide title that contains far too many words to fit in the title region without wrapping repeatedly';
    const deck = buildDeck([
      makeSlide(0, 'content_split', { title: massiveTitle }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    const title = findBlock(layout.textBlocks, 'This is an unusually long');
    expect(title).toBeDefined();
    expect(title!.fontSize).toBeLessThanOrEqual(FONT_SIZES.heading.max);
  });

  it('stops reducing at the floor and flags overflow if the text still does not fit', () => {
    const wallOfText = 'word '.repeat(2000).trim();
    const deck = buildDeck([
      makeSlide(0, 'summary_takeaway', { title: 'X', body_text: wallOfText }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    const body = findBlock(layout.textBlocks, 'word');
    expect(body).toBeDefined();
    expect(body!.fontSize).toBeGreaterThanOrEqual(FONT_SIZES.minimum);
    expect(body!.overflow).toBe(true);
    expect(layout.hasOverflow).toBe(true);
  });
});

describe('LayoutPass deck-level outputs', () => {
  it('counts words across all content fields on a slide', () => {
    const deck = buildDeck([
      makeSlide(0, 'summary_takeaway', {
        title: 'Two words',
        bullets: ['three more here', 'four more on this'],
      }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    // "Two words" = 2, "three more here" = 3, "four more on this" = 4 → 9
    expect(layout.wordCount).toBe(9);
    expect(layout.wordLimit).toBe(WORD_LIMITS.summary_takeaway);
  });

  it('lays out an entire deck with mixed slide types without crashing', () => {
    const deck = loadDeckFixture();
    const layout = new LayoutPass().layout(deck);
    expect(layout.slides).toHaveLength(deck.slides.length);
    for (const slide of layout.slides) {
      expect(slide.width).toBe(SLIDE_WIDTH);
      expect(slide.height).toBe(SLIDE_HEIGHT);
      expect(slide.textBlocks.length).toBeGreaterThan(0);
    }
  });

  it('applies design palette colors to text blocks', () => {
    const deck = loadDeckFixture();
    const layout = new LayoutPass().layout(deck);
    const palette = deck.design.palette;
    const allowed = new Set([
      palette.text,
      palette.text_secondary,
      palette.accent,
      palette.background,
      palette.surface,
    ]);
    for (const slide of layout.slides) {
      for (const block of slide.textBlocks) {
        expect(allowed).toContain(block.color);
      }
    }
  });

  it('reports totalOverflows and totalWordLimitViolations across the deck', () => {
    const deck = buildDeck([
      makeSlide(0, 'title_hero', { title: 'Short' }),
      makeSlide(1, 'summary_takeaway', {
        title: 'X',
        body_text: 'word '.repeat(2000).trim(),
      }),
    ]);
    const layout = new LayoutPass().layout(deck);
    expect(layout.totalOverflows).toBeGreaterThanOrEqual(1);
    expect(typeof layout.totalWordLimitViolations).toBe('number');
  });
});
