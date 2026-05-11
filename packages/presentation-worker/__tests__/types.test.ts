import { describe, expect, it } from 'vitest';
import { readFileSync } from 'fs';
import { fileURLToPath } from 'url';
import { dirname, resolve } from 'path';
import { ALL_SLIDE_TYPES, ALL_MOODS, type DeckSpec } from '../src/types.js';

const here = dirname(fileURLToPath(import.meta.url));
const fixturePath = resolve(here, 'fixtures', 'enlightenment.json');

describe('TypeScript types ↔ Python wire format', () => {
  it('the Python fixture loads and conforms to DeckSpec at the type level', () => {
    const raw = readFileSync(fixturePath, 'utf-8');
    const deck = JSON.parse(raw) as DeckSpec;
    expect(typeof deck.project_id).toBe('string');
    expect(typeof deck.title).toBe('string');
    expect(['uz', 'ru', 'en']).toContain(deck.language);
    expect(deck.design).toBeDefined();
    expect(deck.design.palette).toBeDefined();
    expect(deck.slides.length).toBeGreaterThan(0);
    for (const slide of deck.slides) {
      expect(ALL_SLIDE_TYPES).toContain(slide.slide_type);
      expect(typeof slide.content.title).toBe('string');
    }
  });

  it('every SlideType in the union is present in ALL_SLIDE_TYPES', () => {
    // 22 types per SPEC.md / design language v2
    expect(ALL_SLIDE_TYPES).toHaveLength(22);
  });

  it('every PresentationMood is present in ALL_MOODS', () => {
    expect(ALL_MOODS).toHaveLength(6);
  });

  it('exposes snake_case keys to match the Python wire format', () => {
    const raw = readFileSync(fixturePath, 'utf-8');
    const deck = JSON.parse(raw) as DeckSpec;
    const firstSlide = deck.slides[0]!;
    expect('slide_index' in firstSlide).toBe(true);
    expect('slide_type' in firstSlide).toBe(true);
    expect('source_claim_ids' in firstSlide).toBe(true);
    expect('background_treatment' in deck.design).toBe(true);
    expect('text_secondary' in deck.design.palette).toBe(true);
  });
});
