import { describe, expect, it } from 'vitest';
import { LayoutPass } from '../src/layout-pass.js';
import type { DeckSpec, SlideContent, SlideSpec } from '../src/types.js';

function buildDeck(slides: SlideSpec[]): DeckSpec {
  return {
    project_id: 'p-test',
    title: 'Test deck',
    language: 'en',
    created_at: '2026-05-11T12:00:00Z',
    design: {
      mood: 'warm_historical',
      palette: {
        background: '#1A120B',
        surface: '#2A1F15',
        text: '#F5F0E8',
        accent: '#C4923A',
        text_secondary: '#A89F91',
      },
      heading_font: 'Playfair Display',
      body_font: 'EB Garamond',
      decorative_font: null,
      image_style_prefix: 'classical',
      background_treatment: 'dark',
    },
    interview: {},
    slides,
    export_formats: ['html'],
  };
}

function makeSlide(content: SlideContent): SlideSpec {
  return {
    slide_index: 0,
    slide_type: 'concept_definition',
    content,
    source_claim_ids: [],
  };
}

describe('layout — CONCEPT_DEFINITION', () => {
  it('renders a title block large enough to read as a heading', () => {
    const deck = buildDeck([
      makeSlide({
        title: "Ag'artıwshılıq ne?",
        subtitle: 'Aqıl-oy hám bilim arqalı erkinlik.',
        bullets: ['Aqıl', 'Erkinlik'],
      }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    const title = layout.textBlocks.find((b) => b.text.includes("Ag'artıwshılıq"));
    expect(title).toBeDefined();
    expect(title!.fontSize).toBeGreaterThanOrEqual(28);
  });

  it('renders the definition in an italic style', () => {
    const deck = buildDeck([
      makeSlide({
        title: "Concept",
        subtitle: 'Reason and knowledge through inquiry.',
      }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    const definition = layout.textBlocks.find((b) =>
      b.text.startsWith('Reason and knowledge'),
    );
    expect(definition).toBeDefined();
    expect(definition!.fontStyle).toBe('italic');
    expect(definition!.fontSize).toBeGreaterThanOrEqual(20);
    expect(definition!.fontSize).toBeLessThanOrEqual(24);
  });

  it('emits one bullet block per bullet, each prefixed with "• "', () => {
    const deck = buildDeck([
      makeSlide({
        title: 'Pillars',
        bullets: ['Reason', 'Liberty', 'Tolerance', 'Progress'],
      }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    const bullets = layout.textBlocks.filter((b) => b.text.startsWith('• '));
    expect(bullets).toHaveLength(4);
  });

  it('places a left-to-right scrim that covers ~55% of slide width', () => {
    const deck = buildDeck([
      makeSlide({ title: 'Concept', subtitle: 'Definition' }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    expect(layout.background.scrim).toBeDefined();
    expect(layout.background.scrim!.direction).toBe('left-to-right');
    expect(layout.background.scrim!.w).toBeCloseTo(55, 0);
  });

  it('produces a valid layout when no bullets are supplied', () => {
    const deck = buildDeck([
      makeSlide({ title: 'Bare concept', subtitle: 'Just a definition.' }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    expect(layout.textBlocks.length).toBeGreaterThanOrEqual(2);
    const bullets = layout.textBlocks.filter((b) => b.text.startsWith('• '));
    expect(bullets).toHaveLength(0);
  });
});
