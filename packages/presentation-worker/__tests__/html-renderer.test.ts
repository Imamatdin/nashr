/**
 * HtmlRenderer tests.
 *
 * Verifies the renderer produces a self-contained HTML document with
 * inline CSS/JS, correct positioning from layout, interactive role
 * wiring, and end-to-end fixture support.
 */

import { readFileSync } from 'fs';
import { join } from 'path';
import { describe, expect, it } from 'vitest';
import { LayoutPass } from '../src/layout-pass.js';
import { HtmlRenderer } from '../src/renderers/html-renderer.js';
import { buildTestDeck, makeSlide } from './helpers.js';
import type { DeckSpec } from '../src/types.js';

function render(deck: DeckSpec): string {
  const layout = new LayoutPass().layout(deck);
  return new HtmlRenderer().render(deck, layout);
}

function loadFixture(): DeckSpec {
  const path = join(__dirname, 'fixtures', 'enlightenment.json');
  return JSON.parse(readFileSync(path, 'utf-8')) as DeckSpec;
}

describe('HtmlRenderer — document structure', () => {
  it('produces valid HTML', () => {
    const deck = buildTestDeck([
      makeSlide('title_hero', { title: 'Slide A' }, 0),
      makeSlide('content_split', { title: 'Slide B' }, 1),
      makeSlide('section_break', { title: 'Slide C' }, 2),
    ]);
    const html = render(deck);
    expect(html.startsWith('<!DOCTYPE html>')).toBe(true);
    expect(html).toContain('<html');
    expect(html).toContain('</html>');
    expect(html).toContain('<title>');
  });

  it('embeds CSS custom properties from the palette', () => {
    const deck = buildTestDeck([
      makeSlide('title_hero', { title: 'Bold' }, 0),
    ]);
    deck.design.palette = {
      background: '#0D0D12',
      surface: '#1A1A22',
      text: '#F5F5F5',
      accent: '#E8553A',
      text_secondary: '#A0A0A0',
    };
    const html = render(deck);
    // Allow with or without space after the colon.
    expect(html).toMatch(/--slide-accent:\s*#E8553A/);
    expect(html).toMatch(/--slide-bg:\s*#0D0D12/);
    expect(html).toMatch(/--slide-text:\s*#F5F5F5/);
  });

  it('sets the correct language attribute on <html>', () => {
    const uz = render(buildTestDeck([makeSlide('title_hero', { title: 'T' })], 'uz'));
    expect(uz).toContain('<html lang="uz"');
    const kaa = render(buildTestDeck([makeSlide('title_hero', { title: 'T' })], 'kaa'));
    expect(kaa).toContain('<html lang="kaa"');
  });

  it('renders one <section class="slide"> per slide', () => {
    const slides = [
      makeSlide('title_hero', { title: 'A' }, 0),
      makeSlide('content_split', { title: 'B' }, 1),
      makeSlide('quote_pullquote', { title: 'Q', quote_text: 'q', quote_attribution: 'a' }, 2),
      makeSlide('section_break', { title: 'D' }, 3),
      makeSlide('summary_takeaway', { title: 'E', bullets: ['x', 'y'] }, 4),
    ];
    const deck = buildTestDeck(slides);
    const html = render(deck);
    const matches = html.match(/<section class="slide/g) ?? [];
    expect(matches.length).toBe(5);
  });

  it('marks only the first slide as active', () => {
    const deck = buildTestDeck([
      makeSlide('title_hero', { title: 'A' }, 0),
      makeSlide('content_split', { title: 'B' }, 1),
    ]);
    const html = render(deck);
    expect(html).toMatch(/<section class="slide active"[^>]*data-index="0"/);
    // Slide 1 should not have the "active" class.
    expect(html).toMatch(/<section class="slide"[^>]*data-index="1"/);
  });

  it('encodes slide_type as data-type attribute', () => {
    const deck = buildTestDeck([
      makeSlide('title_hero', { title: 'A' }, 0),
      makeSlide('content_split', { title: 'B' }, 1),
    ]);
    const html = render(deck);
    expect(html).toContain('data-type="title_hero"');
    expect(html).toContain('data-type="content_split"');
  });
});

describe('HtmlRenderer — text blocks', () => {
  it('positions text blocks in pixels relative to 1920x1080', () => {
    const deck = buildTestDeck([
      makeSlide('title_hero', {
        title: 'Hello World',
        subtitle: 'Subtitle',
      }, 0),
    ]);
    const html = render(deck);
    // title_hero positions title at x 5%, y 26% → 96px, 280.8px.
    expect(html).toMatch(/left:\s*96px/);
    expect(html).toMatch(/top:\s*280\.8px/);
  });

  it('emits font-family / weight / size / color from the layout', () => {
    const deck = buildTestDeck([
      makeSlide('title_hero', { title: 'Hello' }, 0),
    ]);
    const html = render(deck);
    expect(html).toContain('font-family:');
    expect(html).toContain('Playfair Display');
    expect(html).toMatch(/font-weight:\s*700/);
    expect(html).toMatch(/font-size:\s*\d+px/);
  });

  it('renders the title color from the palette', () => {
    const deck = buildTestDeck([
      makeSlide('title_hero', { title: 'Hello' }, 0),
    ]);
    deck.design.palette.text = '#ABCDEF';
    const html = render(deck);
    expect(html).toContain('color:#ABCDEF');
  });

  it('escapes HTML in text content (no XSS)', () => {
    const deck = buildTestDeck([
      makeSlide('title_hero', {
        title: "<script>alert('xss')</script>",
      }, 0),
    ]);
    const html = render(deck);
    // The raw <script>alert form must NOT appear in the body text node.
    expect(html).not.toContain("<script>alert('xss')");
    expect(html).toContain('&lt;script&gt;');
    expect(html).toContain('alert(&#039;xss&#039;)');
  });
});

describe('HtmlRenderer — scrim', () => {
  it('renders a linear-gradient for the scrim', () => {
    const deck = buildTestDeck([
      makeSlide('title_hero', {
        title: 'Hero',
        background_url: 'https://example.com/img.jpg',
      }, 0),
    ]);
    const html = render(deck);
    expect(html).toContain('linear-gradient(to right');
    // Background palette is #1A120B from the test helper; rgba should reflect that.
    expect(html).toMatch(/rgba\(26\s*,\s*18\s*,\s*11\s*,\s*0\.6\)/);
  });
});

describe('HtmlRenderer — shapes', () => {
  it('renders a horizontal line as a thin div', () => {
    // interactive_matching emits horizontal dashed lines between pairs.
    const deck = buildTestDeck([
      makeSlide('interactive_matching', {
        title: 'Match',
        matching_pairs: [{ left: 'A', right: 'a' }],
      }, 0),
    ]);
    const html = render(deck);
    // We must see at least one shape div, with the dashed gradient.
    expect(html).toContain('class="shape"');
    expect(html).toContain('repeating-linear-gradient');
  });

  it('renders a circle with border-radius:50%', () => {
    // Timeline slides emit circular nodes.
    const deck = buildTestDeck([
      makeSlide('timeline', {
        title: 'Time',
        timeline_nodes: [
          { date: '1700', label: 'Start' },
          { date: '1800', label: 'Mid' },
          { date: '1900', label: 'End' },
        ],
      }, 0),
    ]);
    const html = render(deck);
    expect(html).toContain('border-radius:50%');
  });
});

describe('HtmlRenderer — images', () => {
  it('renders an <img> tag when src is a real URL', () => {
    const deck = buildTestDeck([
      makeSlide('title_hero', {
        title: 'Hero',
        background_url: 'https://cdn.example.com/x.jpg',
      }, 0),
    ]);
    const html = render(deck);
    expect(html).toContain('<img src="https://cdn.example.com/x.jpg"');
  });

  it('renders a placeholder for prompt-only images', () => {
    const deck = buildTestDeck([
      makeSlide('content_split', {
        title: 'Reason',
        body_text: 'Body',
        background_url: '[a prompt: a really long generated description that is more than 500 characters long' + 'x'.repeat(500),
      }, 0),
    ]);
    const html = render(deck);
    expect(html).toContain('[Image]');
  });
});

describe('HtmlRenderer — interactive roles', () => {
  it('attaches interactive-option to quiz options', () => {
    const deck = buildTestDeck([
      makeSlide('interactive_quiz_mcq', {
        title: 'Q',
        quiz_questions: [
          {
            question: 'What?',
            options: [
              { text: 'A', is_correct: true },
              { text: 'B', is_correct: false },
            ],
            explanation_correct: 'yes',
            explanation_wrong: 'no',
          },
        ],
      }, 0),
    ]);
    const html = render(deck);
    expect(html).toContain('interactive-option');
    expect(html).toContain('data-role="option_correct"');
    expect(html).toContain('data-role="option_wrong"');
  });

  it('marks feedback blocks as interactive-hidden', () => {
    const deck = buildTestDeck([
      makeSlide('interactive_quiz_mcq', {
        title: 'Q',
        quiz_questions: [
          {
            question: 'q',
            options: [
              { text: 'a', is_correct: true },
              { text: 'b', is_correct: false },
            ],
            explanation_correct: 'yes',
            explanation_wrong: 'no',
          },
        ],
      }, 0),
    ]);
    const html = render(deck);
    expect(html).toContain('interactive-hidden');
    expect(html).toContain('data-role="feedback_correct"');
    expect(html).toContain('data-role="feedback_wrong"');
  });

  it('hides match_right blocks until reveal (interactive-hidden)', () => {
    const deck = buildTestDeck([
      makeSlide('interactive_matching', {
        title: 'Match',
        matching_pairs: [
          { left: 'L0', right: 'R0' },
          { left: 'L1', right: 'R1' },
        ],
      }, 0),
    ]);
    const html = render(deck);
    // Find every match_right block. Each must be in the same DOM div that
    // also carries the interactive-hidden class.
    const re = /<div class="([^"]*)"[^>]*data-role="match_right"/g;
    const matches = Array.from(html.matchAll(re));
    expect(matches.length).toBe(2);
    for (const m of matches) {
      expect(m[1]).toContain('interactive-hidden');
    }
  });

  it('renders fill-blank with hidden answers AND a reveal-trigger', () => {
    const deck = buildTestDeck([
      makeSlide('interactive_fill_blank', {
        title: 'Fill',
        fill_blanks: [
          { statement: 'The sky is _____.', answer: 'blue' },
          { statement: 'Water boils at _____.', answer: '100C' },
        ],
      }, 0),
    ]);
    const html = render(deck);
    // Answers must be interactive-hidden.
    const answerMatches = Array.from(
      html.matchAll(/<div class="([^"]*)"[^>]*data-role="blank_answer"/g),
    );
    expect(answerMatches.length).toBe(2);
    for (const m of answerMatches) {
      expect(m[1]).toContain('interactive-hidden');
    }
    // A reveal-trigger element must exist so the user can un-hide them.
    expect(html).toMatch(/<div class="[^"]*reveal-trigger[^"]*"[^>]*data-role="reveal_trigger"/);
  });

  it('marks reveal_trigger with the reveal-trigger class', () => {
    const deck = buildTestDeck([
      makeSlide('interactive_matching', {
        title: 'Match',
        matching_pairs: [{ left: 'L', right: 'R' }],
      }, 0),
    ]);
    const html = render(deck);
    expect(html).toContain('reveal-trigger');
    expect(html).toContain('data-role="reveal_trigger"');
  });

  it('encodes groupId and dataIndex as data attributes', () => {
    const deck = buildTestDeck([
      makeSlide('interactive_quiz_mcq', {
        title: 'Q',
        quiz_questions: [
          {
            question: 'q',
            options: [
              { text: 'a', is_correct: true },
              { text: 'b', is_correct: false },
              { text: 'c', is_correct: false },
            ],
            explanation_correct: 'yes',
            explanation_wrong: 'no',
          },
        ],
      }, 0),
    ]);
    const html = render(deck);
    expect(html).toContain('data-group="q0"');
    expect(html).toContain('data-index="2"');
  });
});

describe('HtmlRenderer — JavaScript', () => {
  it('includes keyboard navigation logic', () => {
    const html = render(buildTestDeck([makeSlide('title_hero', { title: 'T' })]));
    expect(html).toContain('ArrowRight');
    expect(html).toContain('ArrowLeft');
    expect(html).toContain('nextSlide');
    expect(html).toContain('prevSlide');
  });

  it('includes touch / swipe handlers', () => {
    const html = render(buildTestDeck([makeSlide('title_hero', { title: 'T' })]));
    expect(html).toContain('touchstart');
    expect(html).toContain('touchend');
  });

  it('includes quiz / feedback logic', () => {
    const html = render(buildTestDeck([makeSlide('title_hero', { title: 'T' })]));
    expect(html).toContain('interactive-option');
    expect(html).toContain('feedback_correct');
  });

  it('includes reveal logic', () => {
    const html = render(buildTestDeck([makeSlide('title_hero', { title: 'T' })]));
    expect(html).toContain('reveal-trigger');
    expect(html).toContain('interactive-hidden');
  });

  it('includes viewport scaling logic', () => {
    const html = render(buildTestDeck([makeSlide('title_hero', { title: 'T' })]));
    expect(html).toContain('updateScale');
    expect(html).toContain('1920');
    expect(html).toContain('1080');
  });
});

describe('HtmlRenderer — chrome', () => {
  it('emits a progress bar element', () => {
    const html = render(buildTestDeck([makeSlide('title_hero', { title: 'T' })]));
    expect(html).toContain('progress-bar');
  });

  it('emits a slide counter element', () => {
    const html = render(buildTestDeck([makeSlide('title_hero', { title: 'T' })]));
    expect(html).toContain('slide-counter');
  });
});

describe('HtmlRenderer — end to end', () => {
  it('renders the enlightenment fixture without crashing', () => {
    const deck = loadFixture();
    const layout = new LayoutPass().layout(deck);
    const html = new HtmlRenderer().render(deck, layout);
    expect(html.length).toBeGreaterThan(1000);
    const sections = html.match(/<section class="slide/g) ?? [];
    expect(sections.length).toBe(deck.slides.length);
  });

  it('renders a single-slide deck', () => {
    const html = render(buildTestDeck([makeSlide('title_hero', { title: 'Only' })]));
    const sections = html.match(/<section class="slide/g) ?? [];
    expect(sections.length).toBe(1);
  });

  it('renders an interactive deck (quiz + matching + fill_blank)', () => {
    const deck = buildTestDeck([
      makeSlide('interactive_quiz_mcq', {
        title: 'Quiz',
        quiz_questions: [
          {
            question: 'q?',
            options: [
              { text: 'a', is_correct: true },
              { text: 'b', is_correct: false },
            ],
            explanation_correct: 'right',
            explanation_wrong: 'wrong',
          },
        ],
      }, 0),
      makeSlide('interactive_matching', {
        title: 'Match',
        matching_pairs: [{ left: 'L', right: 'R' }],
      }, 1),
      makeSlide('interactive_fill_blank', {
        title: 'Fill',
        fill_blanks: [{ statement: 'The sky is _____.', answer: 'blue' }],
      }, 2),
    ]);
    const html = render(deck);
    expect(html).toContain('interactive-option');
    expect(html).toContain('interactive-hidden');
    expect(html).toContain('reveal-trigger');
  });
});
