/**
 * Run-3 coverage fixture — render-verification for the layouts that no other
 * deck fixture exercises (team_credits, resources_links, interactive_categorize,
 * interactive_true_false, interactive_debate). Confirms each dark layout lays
 * out its content and the whole deck renders to a self-contained HTML document
 * without overflowing blocks.
 */

import { readFileSync } from 'fs';
import { join } from 'path';
import { describe, expect, it } from 'vitest';
import { LayoutPass } from '../src/layout-pass.js';
import { HtmlRenderer } from '../src/renderers/html-renderer.js';
import type { DeckSpec, SlideLayout } from '../src/types.js';

function loadFixture(): DeckSpec {
  const path = join(__dirname, 'fixtures', 'run3-coverage.json');
  return JSON.parse(readFileSync(path, 'utf-8')) as DeckSpec;
}

function layoutFor(deck: DeckSpec, type: string): SlideLayout {
  const slide = deck.slides.find((s) => s.slide_type === type)!;
  expect(slide).toBeDefined();
  return new LayoutPass().layoutSlide(slide, deck);
}

function roleCount(layout: SlideLayout, role: string): number {
  return layout.textBlocks.filter((b) => b.role === role).length;
}

describe('run3-coverage fixture', () => {
  const deck = loadFixture();

  it('renders the whole deck to a self-contained HTML document', () => {
    const layout = new LayoutPass().layout(deck);
    const html = new HtmlRenderer().render(deck, layout);
    expect(html.startsWith('<!DOCTYPE html>')).toBe(true);
    expect(html).toContain('</html>');
  });

  it('lays out team_credits without overflow', () => {
    const layout = layoutFor(deck, 'team_credits');
    expect(layout.hasOverflow).toBe(false);
    const names = layout.textBlocks.filter((b) => /Nurlanova|Karimov|Rashidova/.test(b.text));
    expect(names).toHaveLength(3);
  });

  it('lays out resources_links without overflow', () => {
    const layout = layoutFor(deck, 'resources_links');
    expect(layout.hasOverflow).toBe(false);
    const urls = layout.textBlocks.filter((b) => b.color === deck.design.palette.accent);
    expect(urls.length).toBeGreaterThanOrEqual(3);
  });

  it('lays out interactive_categorize without overflow', () => {
    const layout = layoutFor(deck, 'interactive_categorize');
    expect(layout.hasOverflow).toBe(false);
    expect(roleCount(layout, 'category_label')).toBe(2);
    expect(roleCount(layout, 'category_item')).toBe(6);
  });

  it('lays out interactive_true_false without overflow', () => {
    const layout = layoutFor(deck, 'interactive_true_false');
    expect(layout.hasOverflow).toBe(false);
    expect(roleCount(layout, 'tf_statement')).toBe(3);
    expect(roleCount(layout, 'tf_verdict')).toBe(3);
    expect(roleCount(layout, 'tf_explanation')).toBe(3);
    expect(roleCount(layout, 'reveal_trigger')).toBe(1);
  });

  it('lays out interactive_debate without overflow', () => {
    const layout = layoutFor(deck, 'interactive_debate');
    expect(layout.hasOverflow).toBe(false);
    expect(roleCount(layout, 'debate_prompt')).toBe(1);
    expect(roleCount(layout, 'debate_position')).toBe(2);
    expect(roleCount(layout, 'debate_framework')).toBe(2);
    expect(roleCount(layout, 'reveal_trigger')).toBe(1);
  });
});
