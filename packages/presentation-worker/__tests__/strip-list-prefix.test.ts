/**
 * stripListPrefix (FIX C2) — strip a single baked-in enumerator from bullets
 * so the renderer's own "• " prefix does not produce doubled numbering
 * ("• 1. …"), while leaving decimals that merely open a bullet untouched.
 */

import { describe, expect, it } from 'vitest';
import { LayoutPass } from '../src/layout-pass.js';
import { stripListPrefix } from '../src/layouts/shared.js';
import type { DeckSpec, SlideContent, SlideSpec, SlideType } from '../src/types.js';

describe('stripListPrefix', () => {
  it('strips a "1. " enumerator', () => {
    expect(stripListPrefix('1. PUE of 1.08')).toBe('PUE of 1.08');
  });

  it('leaves a leading decimal untouched (no space after the dot)', () => {
    expect(stripListPrefix('1.08 PUE improvement')).toBe('1.08 PUE improvement');
  });

  it('handles ")" enumerators and multi-digit indices', () => {
    expect(stripListPrefix('10) Second reason')).toBe('Second reason');
  });

  it('consumes leading whitespace before the enumerator', () => {
    expect(stripListPrefix('  3. Indented reason')).toBe('Indented reason');
  });

  it('strips only the first enumerator', () => {
    expect(stripListPrefix('1. 2. nested')).toBe('2. nested');
  });

  it('leaves plain bullets and "1." with no trailing space alone', () => {
    expect(stripListPrefix('Plain takeaway')).toBe('Plain takeaway');
    expect(stripListPrefix('1.Item')).toBe('1.Item');
  });
});

function buildDeck(slides: SlideSpec[]): DeckSpec {
  return {
    project_id: 'p-test',
    title: 'Test deck',
    language: 'en',
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

function makeSlide(index: number, type: SlideType, content: SlideContent): SlideSpec {
  return { slide_index: index, slide_type: type, content, source_claim_ids: [] };
}

const NUMBERED_BULLET = /^•?\s*\d+[.)]\s/;

describe('SUMMARY_TAKEAWAY — no doubled numbering', () => {
  it('renders model-numbered bullets without a second enumerator', () => {
    const deck = buildDeck([
      makeSlide(0, 'summary_takeaway', {
        title: 'Five Reasons',
        bullets: [
          '1. PUE of 1.08 cuts cooling overhead',
          '2. 35% less water than air cooling',
          '3. 12 MW capacity per module',
        ],
      }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    const offenders = layout.textBlocks.filter((b) => NUMBERED_BULLET.test(b.text)).map((b) => b.text);
    expect(offenders).toEqual([]);
    // The decimal "1.08" survives inside the first bullet's body.
    expect(layout.textBlocks.some((b) => b.text.includes('PUE of 1.08'))).toBe(true);
  });
});
