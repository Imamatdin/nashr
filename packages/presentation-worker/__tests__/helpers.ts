/**
 * Shared test fixtures for the layout test suite.
 *
 * One canonical deck builder so every per-type test file uses the
 * same palette/fonts; tests stay focused on the layout under test
 * rather than re-declaring the design direction on every line.
 */

import type {
  DeckSpec,
  Language,
  SlideContent,
  SlideSpec,
  SlideType,
} from '../src/types.js';

export function buildTestDeck(
  slides: SlideSpec[],
  language: Language = 'en',
): DeckSpec {
  return {
    project_id: 'p-test',
    title: 'Test deck',
    language,
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

export function makeSlide(
  type: SlideType,
  content: SlideContent,
  index = 0,
): SlideSpec {
  return {
    slide_index: index,
    slide_type: type,
    content,
    source_claim_ids: [],
  };
}
