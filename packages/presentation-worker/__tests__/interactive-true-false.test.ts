import { describe, expect, it } from 'vitest';
import { LayoutPass } from '../src/layout-pass.js';
import { buildTestDeck, makeSlide } from './helpers.js';
import type { TrueFalseItem } from '../src/types.js';

function makeItems(): TrueFalseItem[] {
  return [
    { statement: 'Voltaire wrote Candide.', is_true: true, explanation: 'Yes, published 1759.' },
    { statement: 'Newton invented calculus alone.', is_true: false, explanation: 'Leibniz too.' },
    { statement: 'The Bastille fell in 1789.', is_true: true, explanation: 'July 14.' },
  ];
}

describe('layout — INTERACTIVE_TRUE_FALSE', () => {
  it('emits statement, verdict, and explanation per item', () => {
    const deck = buildTestDeck([
      makeSlide('interactive_true_false', {
        title: 'True or false',
        true_false_items: makeItems(),
      }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    expect(layout.textBlocks.filter((b) => b.role === 'tf_statement')).toHaveLength(3);
    expect(layout.textBlocks.filter((b) => b.role === 'tf_verdict')).toHaveLength(3);
    expect(layout.textBlocks.filter((b) => b.role === 'tf_explanation')).toHaveLength(3);
  });

  it('uses localized verdict labels (uz / kaa)', () => {
    const uzDeck = buildTestDeck(
      [
        makeSlide('interactive_true_false', {
          title: "To'g'rimi yo noto'g'rimi",
          true_false_items: makeItems(),
        }),
      ],
      'uz',
    );
    const uzLayout = new LayoutPass().layoutSlide(uzDeck.slides[0]!, uzDeck);
    const uzVerdicts = uzLayout.textBlocks.filter((b) => b.role === 'tf_verdict');
    expect(uzVerdicts.some((b) => b.text.includes("To'g'ri"))).toBe(true);
    expect(uzVerdicts.some((b) => b.text.includes("Noto'g'ri"))).toBe(true);

    const kaaDeck = buildTestDeck(
      [
        makeSlide('interactive_true_false', {
          title: 'Dúrıs yamasa qáte',
          true_false_items: makeItems(),
        }),
      ],
      'kaa',
    );
    const kaaLayout = new LayoutPass().layoutSlide(kaaDeck.slides[0]!, kaaDeck);
    const kaaVerdicts = kaaLayout.textBlocks.filter((b) => b.role === 'tf_verdict');
    expect(kaaVerdicts.some((b) => b.text.includes('Dúrıs'))).toBe(true);
    expect(kaaVerdicts.some((b) => b.text.includes('Qáte'))).toBe(true);
  });

  it('colours true verdicts with accent and false with muted red #C0392B', () => {
    const deck = buildTestDeck([
      makeSlide('interactive_true_false', {
        title: 'Tf',
        true_false_items: makeItems(),
      }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    const accent = deck.design.palette.accent;
    const verdicts = layout.textBlocks
      .filter((b) => b.role === 'tf_verdict')
      .sort((a, b) => (a.dataIndex ?? 0) - (b.dataIndex ?? 0));
    expect(verdicts[0]!.color).toBe(accent);
    expect(verdicts[1]!.color).toBe('#C0392B');
    expect(verdicts[2]!.color).toBe(accent);
  });

  it('shares groupId across statement, verdict, and explanation for the same item', () => {
    const deck = buildTestDeck([
      makeSlide('interactive_true_false', {
        title: 'Tf',
        true_false_items: makeItems(),
      }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    const tf0 = layout.textBlocks.filter((b) => b.groupId === 'tf0');
    expect(tf0.filter((b) => b.role === 'tf_statement')).toHaveLength(1);
    expect(tf0.filter((b) => b.role === 'tf_verdict')).toHaveLength(1);
    expect(tf0.filter((b) => b.role === 'tf_explanation')).toHaveLength(1);
  });

  it('emits a reveal_trigger so HTML can reveal verdicts and explanations', () => {
    const deck = buildTestDeck([
      makeSlide('interactive_true_false', {
        title: 'Tf',
        true_false_items: makeItems(),
      }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    const triggers = layout.textBlocks.filter((b) => b.role === 'reveal_trigger');
    expect(triggers).toHaveLength(1);
  });

  it('localizes the reveal trigger label (ru / kaa)', () => {
    const ruDeck = buildTestDeck(
      [
        makeSlide('interactive_true_false', {
          title: 'Верно или нет',
          true_false_items: makeItems(),
        }),
      ],
      'ru',
    );
    const ruLayout = new LayoutPass().layoutSlide(ruDeck.slides[0]!, ruDeck);
    const ruTrigger = ruLayout.textBlocks.find((b) => b.role === 'reveal_trigger');
    expect(ruTrigger!.text).toBe('Показать ответ');

    const kaaDeck = buildTestDeck(
      [
        makeSlide('interactive_true_false', {
          title: 'Dúrıs yamasa qáte',
          true_false_items: makeItems(),
        }),
      ],
      'kaa',
    );
    const kaaLayout = new LayoutPass().layoutSlide(kaaDeck.slides[0]!, kaaDeck);
    const kaaTrigger = kaaLayout.textBlocks.find((b) => b.role === 'reveal_trigger');
    expect(kaaTrigger!.text).toBe('Jauapdı kórset');
  });
});
