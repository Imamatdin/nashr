import { describe, expect, it } from 'vitest';
import { readFileSync } from 'fs';
import { fileURLToPath } from 'url';
import { dirname, resolve } from 'path';
import { validateDeckSpec } from '../src/validators.js';

const here = dirname(fileURLToPath(import.meta.url));
const fixtureDir = resolve(here, 'fixtures');

function loadFixture(name: string): unknown {
  return JSON.parse(readFileSync(resolve(fixtureDir, name), 'utf-8'));
}

function minimalValidDeck(): Record<string, unknown> {
  return {
    project_id: 'p-1',
    title: 'Untitled Deck',
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
    slides: [
      {
        slide_index: 0,
        slide_type: 'title_hero',
        content: { title: 'Hello' },
        source_claim_ids: [],
      },
    ],
    export_formats: ['html'],
  };
}

describe('validateDeckSpec', () => {
  it('accepts the Python-generated enlightenment fixture', () => {
    const fixture = loadFixture('enlightenment.json');
    const result = validateDeckSpec(fixture);
    expect(result.errors).toEqual([]);
    expect(result.valid).toBe(true);
  });

  it('accepts a hand-crafted minimal deck', () => {
    const result = validateDeckSpec(minimalValidDeck());
    expect(result.valid).toBe(true);
  });

  it('rejects an empty slides array', () => {
    const deck = minimalValidDeck();
    deck.slides = [];
    const result = validateDeckSpec(deck);
    expect(result.valid).toBe(false);
    expect(result.errors.some((e) => e.path === 'slides')).toBe(true);
  });

  it('rejects a missing design field', () => {
    const deck = minimalValidDeck();
    delete deck.design;
    const result = validateDeckSpec(deck);
    expect(result.valid).toBe(false);
    expect(result.errors.some((e) => e.path === 'design')).toBe(true);
  });

  it('rejects an unknown slide_type', () => {
    const deck = minimalValidDeck();
    (deck.slides as Array<Record<string, unknown>>)[0]!.slide_type = 'nonexistent_type';
    const result = validateDeckSpec(deck);
    expect(result.valid).toBe(false);
    expect(result.errors.some((e) => e.path.endsWith('slide_type'))).toBe(true);
  });

  it('rejects a slide with no title', () => {
    const deck = minimalValidDeck();
    const slides = deck.slides as Array<Record<string, unknown>>;
    slides[0]!.content = {};
    const result = validateDeckSpec(deck);
    expect(result.valid).toBe(false);
    expect(result.errors.some((e) => e.path.endsWith('content.title'))).toBe(true);
  });

  it('rejects an invalid hex palette colour', () => {
    const deck = minimalValidDeck();
    const design = deck.design as Record<string, unknown>;
    const palette = design.palette as Record<string, unknown>;
    palette.background = 'not-a-color';
    const result = validateDeckSpec(deck);
    expect(result.valid).toBe(false);
    expect(result.errors.some((e) => e.path === 'design.palette.background')).toBe(true);
  });

  it('rejects an invalid accent_override on a slide', () => {
    const deck = minimalValidDeck();
    const slides = deck.slides as Array<Record<string, unknown>>;
    slides[0]!.accent_override = 'not-a-color';
    const result = validateDeckSpec(deck);
    expect(result.valid).toBe(false);
    expect(result.errors.some((e) => e.path.endsWith('accent_override'))).toBe(true);
  });

  it('rejects a non-object payload', () => {
    expect(validateDeckSpec(null).valid).toBe(false);
    expect(validateDeckSpec('string').valid).toBe(false);
    expect(validateDeckSpec([]).valid).toBe(false);
  });
});
