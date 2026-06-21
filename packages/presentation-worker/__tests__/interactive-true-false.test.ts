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

  // --- L2 fit-migration tripwires ---------------------------------------

  it('orders statement < verdict < explanation within an item sharing groupId', () => {
    const deck = buildTestDeck([
      makeSlide('interactive_true_false', {
        title: 'Tf',
        true_false_items: makeItems(),
      }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    const tf0 = layout.textBlocks.filter((b) => b.groupId === 'tf0');
    const statement = tf0.find((b) => b.role === 'tf_statement')!;
    const verdict = tf0.find((b) => b.role === 'tf_verdict')!;
    const explanation = tf0.find((b) => b.role === 'tf_explanation')!;
    expect(statement.y).toBeLessThan(verdict.y);
    expect(verdict.y).toBeLessThan(explanation.y);
    // each sub sits at or below its predecessor's measured bottom (hugged stack)
    expect(verdict.y).toBeGreaterThanOrEqual(statement.y + statement.measuredHeightPct);
    expect(explanation.y).toBeGreaterThanOrEqual(verdict.y + verdict.measuredHeightPct);
  });

  it('stacks consecutive items without vertical overlap', () => {
    const deck = buildTestDeck([
      makeSlide('interactive_true_false', {
        title: 'Tf',
        true_false_items: makeItems(),
      }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    const groups = ['tf0', 'tf1', 'tf2'].map((g) => {
      const subs = layout.textBlocks.filter((b) => b.groupId === g);
      const top = Math.min(...subs.map((b) => b.y));
      const bottom = Math.max(...subs.map((b) => b.y + b.measuredHeightPct));
      return { top, bottom };
    });
    for (let i = 1; i < groups.length; i++) {
      expect(groups[i]!.top).toBeGreaterThanOrEqual(groups[i - 1]!.bottom);
    }
  });

  it('caps at MAX_ITEMS=5 even when given 7 items (silent overflow)', () => {
    const seven: TrueFalseItem[] = Array.from({ length: 7 }, (_, i) => ({
      statement: `Statement number ${i + 1}.`,
      is_true: i % 2 === 0,
      explanation: `Explanation ${i + 1}.`,
    }));
    const deck = buildTestDeck([
      makeSlide('interactive_true_false', {
        title: 'Tf',
        true_false_items: seven,
      }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    expect(layout.textBlocks.filter((b) => b.role === 'tf_statement')).toHaveLength(5);
    expect(layout.textBlocks.filter((b) => b.role === 'tf_verdict')).toHaveLength(5);
    expect(layout.textBlocks.filter((b) => b.role === 'tf_explanation')).toHaveLength(5);
  });

  it('places the reveal trigger below the last explanation and clamped to <=92', () => {
    const deck = buildTestDeck([
      makeSlide('interactive_true_false', {
        title: 'Tf',
        true_false_items: makeItems(),
      }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    const explanations = layout.textBlocks.filter((b) => b.role === 'tf_explanation');
    const lastExplanationBottom = Math.max(
      ...explanations.map((b) => b.y + b.measuredHeightPct),
    );
    const trigger = layout.textBlocks.find((b) => b.role === 'reveal_trigger')!;
    expect(trigger.y).toBeLessThanOrEqual(92);
    // unless clamped, the trigger follows the last item's measured bottom
    if (trigger.y < 92) {
      expect(trigger.y).toBeGreaterThanOrEqual(lastExplanationBottom);
    }
  });

  it('WRAPS a long statement instead of truncating it to a fixed slot', () => {
    const longStatement =
      'Voltaire, born François-Marie Arouet in 1694, wrote the satirical novella ' +
      'Candide, ou l’Optimisme, which lampoons Leibnizian optimism across many ' +
      'continents and remains one of the most widely read works of the French ' +
      'Enlightenment to this very day and beyond and continues onward still.';
    const items: TrueFalseItem[] = [
      { statement: longStatement, is_true: true, explanation: 'Published 1759.' },
      { statement: 'Short follow-up statement.', is_true: false, explanation: 'Nope.' },
    ];
    const deck = buildTestDeck([
      makeSlide('interactive_true_false', {
        title: 'Tf',
        true_false_items: items,
      }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    const tf0Statement = layout.textBlocks.find(
      (b) => b.groupId === 'tf0' && b.role === 'tf_statement',
    )!;
    // The migration proof: the long statement wraps to its natural height and is
    // NOT clipped to a fixed slot.
    expect(tf0Statement.truncated).toBeFalsy();
    // It occupies more than one line (taller than a single-line slot).
    expect(tf0Statement.measuredHeightPct).toBeGreaterThan(5);

    // Its own verdict sits below the wrapped statement's measured bottom.
    const tf0Verdict = layout.textBlocks.find(
      (b) => b.groupId === 'tf0' && b.role === 'tf_verdict',
    )!;
    expect(tf0Verdict.y).toBeGreaterThanOrEqual(
      tf0Statement.y + tf0Statement.measuredHeightPct,
    );

    // And the following item starts below the first item's entire measured stack.
    const tf0Bottom = Math.max(
      ...layout.textBlocks
        .filter((b) => b.groupId === 'tf0')
        .map((b) => b.y + b.measuredHeightPct),
    );
    const tf1Top = Math.min(
      ...layout.textBlocks.filter((b) => b.groupId === 'tf1').map((b) => b.y),
    );
    expect(tf1Top).toBeGreaterThanOrEqual(tf0Bottom);
  });

  it('scales tall content to fit on-slide — no block past the 94% bottom margin', () => {
    // Probed pre-fix: 5 items with a long statement + long explanation each ran to
    // ~128% (off-slide, silent). The scale+rebuild helper must keep every content
    // block AND the reveal trigger within the slide.
    const LONG =
      'In the eighteenth century the philosophers of the Enlightenment argued at ' +
      'considerable length that human institutions could be perfected through the ' +
      'patient application of reason, observation, and sustained public debate.';
    const items: TrueFalseItem[] = Array.from({ length: 5 }, (_, i) => ({
      statement: LONG,
      is_true: i % 2 === 0,
      explanation: LONG,
    }));
    const deck = buildTestDeck([
      makeSlide('interactive_true_false', {
        title: 'Tf',
        true_false_items: items,
      }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    const content = layout.textBlocks.filter(
      (b) =>
        b.role === 'tf_statement' || b.role === 'tf_verdict' || b.role === 'tf_explanation',
    );
    const maxBottom = Math.max(...content.map((b) => b.y + b.measuredHeightPct));
    expect(maxBottom).toBeLessThanOrEqual(94);
    const trigger = layout.textBlocks.find((b) => b.role === 'reveal_trigger')!;
    expect(trigger.y).toBeLessThanOrEqual(92);
    // trigger sits below the content it reveals (no overlap)
    expect(trigger.y).toBeGreaterThanOrEqual(maxBottom - 1e-6);
  });

  it('flags hasOverflow when content cannot fit even after scaling', () => {
    // Extreme content that must truncate even at the scaled budget → genuine
    // can't-fit must be observable (compose hasOverflow), not silent.
    const HUGE = 'Reason and observation '.repeat(40).trim();
    const items: TrueFalseItem[] = Array.from({ length: 5 }, (_, i) => ({
      statement: HUGE,
      is_true: i % 2 === 0,
      explanation: HUGE,
    }));
    const deck = buildTestDeck([
      makeSlide('interactive_true_false', {
        title: 'Tf',
        true_false_items: items,
      }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    // still on-slide…
    const content = layout.textBlocks.filter(
      (b) =>
        b.role === 'tf_statement' || b.role === 'tf_verdict' || b.role === 'tf_explanation',
    );
    expect(Math.max(...content.map((b) => b.y + b.measuredHeightPct))).toBeLessThanOrEqual(94);
    // …but the audit can see it could not really fit
    expect(layout.hasOverflow).toBe(true);
  });
});
