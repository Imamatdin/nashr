import { describe, expect, it } from 'vitest';
import { LayoutPass } from '../src/layout-pass.js';
import { buildTestDeck, makeSlide } from './helpers.js';
import type { FillBlankItem } from '../src/types.js';

function makeBlanks(count: number): FillBlankItem[] {
  return Array.from({ length: count }, (_, i) => ({
    statement: `Statement ${i} with ____ blank.`,
    answer: `answer${i}`,
  }));
}

describe('layout — INTERACTIVE_FILL_BLANK', () => {
  it('emits one statement and one answer block per item', () => {
    const deck = buildTestDeck([
      makeSlide('interactive_fill_blank', {
        title: 'Fill in',
        fill_blanks: makeBlanks(4),
      }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    expect(layout.textBlocks.filter((b) => b.role === 'blank_statement')).toHaveLength(4);
    expect(layout.textBlocks.filter((b) => b.role === 'blank_answer')).toHaveLength(4);
  });

  it('renders answers in the accent colour', () => {
    const deck = buildTestDeck([
      makeSlide('interactive_fill_blank', {
        title: 'Fill in',
        fill_blanks: makeBlanks(3),
      }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    const accent = deck.design.palette.accent;
    const answers = layout.textBlocks.filter((b) => b.role === 'blank_answer');
    expect(answers).toHaveLength(3);
    for (const b of answers) expect(b.color).toBe(accent);
  });

  it('numbers statements with "1. ", "2. ", ...', () => {
    const deck = buildTestDeck([
      makeSlide('interactive_fill_blank', {
        title: 'Fill in',
        fill_blanks: makeBlanks(3),
      }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    const stmts = layout.textBlocks
      .filter((b) => b.role === 'blank_statement')
      .sort((a, b) => (a.dataIndex ?? 0) - (b.dataIndex ?? 0));
    expect(stmts[0]!.text.startsWith('1. ')).toBe(true);
    expect(stmts[1]!.text.startsWith('2. ')).toBe(true);
    expect(stmts[2]!.text.startsWith('3. ')).toBe(true);
  });

  it('uses localized subtitle (ru)', () => {
    const deck = buildTestDeck(
      [
        makeSlide('interactive_fill_blank', {
          title: 'Заполни',
          fill_blanks: makeBlanks(2),
        }),
      ],
      'ru',
    );
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    const subtitle = layout.textBlocks.find(
      (b) => b.role === 'static' && b.text.includes('Заполните пропуск'),
    );
    expect(subtitle).toBeDefined();
  });
});
