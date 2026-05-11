import { describe, expect, it } from 'vitest';
import { LayoutPass } from '../src/layout-pass.js';
import { buildTestDeck, makeSlide } from './helpers.js';
import type { CategoryItem } from '../src/types.js';

describe('layout — INTERACTIVE_CATEGORIZE', () => {
  it('emits one block per category label', () => {
    const labels = ['Politics', 'Science', 'Religion', 'Economy'];
    const items: CategoryItem[] = labels.flatMap((l, i) => [
      { term: `${l} item ${i}A`, category: l },
      { term: `${l} item ${i}B`, category: l },
    ]);
    const deck = buildTestDeck([
      makeSlide('interactive_categorize', {
        title: 'Sort it',
        category_labels: labels,
        category_items: items,
      }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    expect(layout.textBlocks.filter((b) => b.role === 'category_label')).toHaveLength(4);
  });

  it('places items for category 0 in the first column (x < 50)', () => {
    const labels = ['Politics', 'Science', 'Religion', 'Economy'];
    const items: CategoryItem[] = [
      { term: 'Voltaire', category: 'Politics' },
      { term: 'Rousseau', category: 'Politics' },
      { term: 'Newton', category: 'Science' },
      { term: 'Locke', category: 'Politics' },
      { term: 'Galileo', category: 'Science' },
      { term: 'Aquinas', category: 'Religion' },
      { term: 'Smith', category: 'Economy' },
      { term: 'Hume', category: 'Politics' },
    ];
    const deck = buildTestDeck([
      makeSlide('interactive_categorize', {
        title: 'Sort it',
        category_labels: labels,
        category_items: items,
      }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    const cat0Items = layout.textBlocks.filter(
      (b) => b.role === 'category_item' && b.groupId === 'cat0',
    );
    expect(cat0Items.length).toBeGreaterThan(0);
    for (const item of cat0Items) {
      expect(item.x).toBeLessThan(50);
    }
  });

  it('renders category labels in the accent colour', () => {
    const labels = ['A', 'B', 'C'];
    const deck = buildTestDeck([
      makeSlide('interactive_categorize', {
        title: 'Sort',
        category_labels: labels,
        category_items: [
          { term: 'x', category: 'A' },
          { term: 'y', category: 'B' },
          { term: 'z', category: 'C' },
        ],
      }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    const accent = deck.design.palette.accent;
    const labelBlocks = layout.textBlocks.filter((b) => b.role === 'category_label');
    expect(labelBlocks).toHaveLength(3);
    for (const b of labelBlocks) {
      expect(b.color).toBe(accent);
    }
  });

  it('handles uneven distribution without crashing', () => {
    const labels = ['A', 'B', 'C'];
    const items: CategoryItem[] = [
      { term: 'a1', category: 'A' },
      { term: 'a2', category: 'A' },
      { term: 'a3', category: 'A' },
      { term: 'b1', category: 'B' },
      { term: 'c1', category: 'C' },
      { term: 'c2', category: 'C' },
      { term: 'c3', category: 'C' },
      { term: 'c4', category: 'C' },
    ];
    const deck = buildTestDeck([
      makeSlide('interactive_categorize', {
        title: 'Sort',
        category_labels: labels,
        category_items: items,
      }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    const itemBlocks = layout.textBlocks.filter((b) => b.role === 'category_item');
    expect(itemBlocks).toHaveLength(8);
    expect(itemBlocks.filter((b) => b.groupId === 'cat0')).toHaveLength(3);
    expect(itemBlocks.filter((b) => b.groupId === 'cat1')).toHaveLength(1);
    expect(itemBlocks.filter((b) => b.groupId === 'cat2')).toHaveLength(4);
  });
});
