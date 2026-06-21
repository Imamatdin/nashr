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

describe('layout — CONCEPT_DEFINITION measured stacking (banked-deck clipping bug)', () => {
  // Reproduces the exact slide from the banked deck (debug/last_deck.json, which
  // is gitignored and not in the tree) that surfaced the clipping bug: a title
  // that wraps to two lines and a definition longer than the old fixed 12% box,
  // which the renderer clipped to "Above 31°C and 73." via overflow:hidden.
  const BUG_TITLE = 'Supercritical CO₂ Behaves Like No Other Coolant';
  const BUG_DEFINITION =
    'Above 31°C and 73.8 bar, CO₂ enters a supercritical state — neither liquid nor gas.';
  const BUG_BULLETS = [
    'Density approaches that of a liquid while viscosity stays gas-like',
    'Tiny temperature changes near the critical point swing density sharply',
    'This tunability is what makes sCO₂ an exceptional heat-transfer fluid',
  ];

  function bugLayout() {
    const deck = buildDeck([
      makeSlide({
        title: BUG_TITLE,
        subtitle: BUG_DEFINITION,
        bullets: BUG_BULLETS,
      }),
    ]);
    return new LayoutPass().layoutSlide(deck.slides[0]!, deck);
  }

  it('gives the definition block enough height for the full "73.8 bar" sentence (no clip)', () => {
    const layout = bugLayout();
    const definition = layout.textBlocks.find((b) => b.text.startsWith('Above 31'))!;
    expect(definition).toBeDefined();

    // The full sentence is preserved verbatim — never truncated to fit.
    expect(definition.text).toBe(BUG_DEFINITION);
    expect(definition.text).toContain('73.8 bar');

    // The renderer clips text to block.h (overflow:hidden), so the allocated
    // box height must cover the measured wrapped height. This is the assertion
    // that failed on the old fixed 12% region.
    expect(definition.measuredHeightPct).toBeGreaterThan(0);
    expect(definition.measuredHeightPct).toBeLessThanOrEqual(definition.h);
    expect(definition.overflow).toBe(false);
  });

  it('starts the definition below the title’s real (measured) bottom', () => {
    const layout = bugLayout();
    const title = layout.textBlocks.find((b) => b.text === BUG_TITLE)!;
    const definition = layout.textBlocks.find((b) => b.text.startsWith('Above 31'))!;
    expect(definition.y).toBeGreaterThanOrEqual(title.y + title.measuredHeightPct);
  });

  it('never overlaps any two stacked blocks (next.y >= prev.y + prev.measuredHeightPct)', () => {
    const layout = bugLayout();
    // Every block lives in the same left text column, so y-order is stack order.
    const stacked = [...layout.textBlocks].sort((a, b) => a.y - b.y);
    for (let i = 1; i < stacked.length; i++) {
      const prev = stacked[i - 1]!;
      const curr = stacked[i]!;
      expect(curr.y).toBeGreaterThanOrEqual(prev.y + prev.measuredHeightPct);
      // And each block's own box fits its measured content (no per-block clip).
      expect(curr.measuredHeightPct).toBeLessThanOrEqual(curr.h);
    }
  });

  it('keeps the left column width and emits the left-anchored scrim', () => {
    const layout = bugLayout();
    for (const block of layout.textBlocks) {
      expect(block.x).toBeLessThan(50);
      expect(block.w).toBeLessThanOrEqual(50);
    }
    expect(layout.background.scrim!.direction).toBe('left-to-right');
  });
});

describe('layout — CONCEPT_DEFINITION overflow containment (scale-to-fit)', () => {
  const LONG =
    'In the eighteenth century the philosophers of the Enlightenment argued at ' +
    'considerable length that human institutions could be perfected through the ' +
    'patient application of reason, observation, and sustained public debate.';

  it('scales a long definition + many bullets to fit the column (no block past 94%)', () => {
    const deck = buildDeck([
      makeSlide({
        title: 'A reasonably long concept title that wraps to two lines on the slide',
        subtitle: LONG,
        bullets: [LONG, LONG, LONG, LONG, LONG],
      }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    const maxBottom = Math.max(...layout.textBlocks.map((b) => b.y + b.measuredHeightPct));
    expect(maxBottom).toBeLessThanOrEqual(94);
  });

  it('flags hasOverflow when the column content cannot fit even after scaling', () => {
    const HUGE = 'Reason and observation '.repeat(80).trim();
    const deck = buildDeck([
      makeSlide({
        title: 'Concept',
        subtitle: HUGE,
        bullets: [HUGE, HUGE, HUGE, HUGE, HUGE],
      }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    expect(Math.max(...layout.textBlocks.map((b) => b.y + b.measuredHeightPct))).toBeLessThanOrEqual(94);
    expect(layout.hasOverflow).toBe(true);
  });

  it('flags hasOverflow when a single item is truncated at the natural/full pass (scale===1)', () => {
    // The case the original containment proof missed: one composite item so tall it
    // truncates even against the FULL band, so the stack does NOT scale (scale===1)
    // and the natural block is reused verbatim — its truncation must STILL surface as
    // hasOverflow. (No bullets ⇒ a single definition item.)
    const HUGE = 'word '.repeat(600).trim();
    const deck = buildDeck([makeSlide({ title: 'Concept', subtitle: HUGE })]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    const def = layout.textBlocks.find((b) => b.text.startsWith('word'))!;
    expect(def).toBeDefined();
    expect(def.truncated).toBe(true);
    // the truncated block itself carries the overflow flag (not just the downstream
    // hasOverflow) — proves the natural/full-band (scale===1) path sets it
    expect(def.overflow).toBe(true);
    expect(def.y + def.measuredHeightPct).toBeLessThanOrEqual(94);
    expect(layout.hasOverflow).toBe(true);
  });
});
