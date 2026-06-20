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

  it('emits a reveal_trigger block so HTML can reveal hidden answers', () => {
    const deck = buildTestDeck([
      makeSlide('interactive_fill_blank', {
        title: 'Fill in',
        fill_blanks: makeBlanks(3),
      }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    const triggers = layout.textBlocks.filter((b) => b.role === 'reveal_trigger');
    expect(triggers).toHaveLength(1);
  });

  it('stacks each answer directly below its own statement, in item order', () => {
    const deck = buildTestDeck([
      makeSlide('interactive_fill_blank', {
        title: 'Fill in',
        fill_blanks: makeBlanks(4),
      }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    const stmts = layout.textBlocks
      .filter((b) => b.role === 'blank_statement')
      .sort((a, b) => (a.dataIndex ?? 0) - (b.dataIndex ?? 0));
    const answers = layout.textBlocks
      .filter((b) => b.role === 'blank_answer')
      .sort((a, b) => (a.dataIndex ?? 0) - (b.dataIndex ?? 0));
    expect(stmts).toHaveLength(4);
    expect(answers).toHaveLength(4);
    for (let i = 0; i < stmts.length; i++) {
      // answer sits below its own statement (same groupId), not overlapping it
      expect(answers[i]!.groupId).toBe(stmts[i]!.groupId);
      expect(answers[i]!.y).toBeGreaterThanOrEqual(stmts[i]!.y + stmts[i]!.measuredHeightPct);
      // items do not overlap: the next statement starts below this answer's bottom
      if (i + 1 < stmts.length) {
        expect(stmts[i + 1]!.y).toBeGreaterThanOrEqual(answers[i]!.y + answers[i]!.measuredHeightPct);
      }
    }
  });

  it('wraps a long statement to its measured height instead of truncating it', () => {
    // The migration payoff: a statement that needs two lines must WRAP (and push
    // its answer + the next item down) rather than be truncated to a fixed slot.
    const longStatement =
      'In the eighteenth century the philosophers of the Enlightenment argued at ' +
      'considerable length that human ____ could be perfected through the patient ' +
      'application of reason, observation, and public debate across many fields.';
    const deck = buildTestDeck([
      makeSlide('interactive_fill_blank', {
        title: 'Fill in',
        fill_blanks: [
          { statement: longStatement, answer: 'reason' },
          { statement: 'A short ____ statement.', answer: 'second' },
        ],
      }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    const stmts = layout.textBlocks
      .filter((b) => b.role === 'blank_statement')
      .sort((a, b) => (a.dataIndex ?? 0) - (b.dataIndex ?? 0));
    const answers = layout.textBlocks
      .filter((b) => b.role === 'blank_answer')
      .sort((a, b) => (a.dataIndex ?? 0) - (b.dataIndex ?? 0));
    expect(stmts[0]!.truncated).toBeFalsy();
    // the long statement occupies more than a single body line, and its answer +
    // the following statement are pushed below its real wrapped bottom
    expect(answers[0]!.y).toBeGreaterThanOrEqual(stmts[0]!.y + stmts[0]!.measuredHeightPct);
    expect(stmts[1]!.y).toBeGreaterThanOrEqual(answers[0]!.y + answers[0]!.measuredHeightPct);
  });

  it('caps at MAX_ITEMS=5 and silently drops the overflow', () => {
    const deck = buildTestDeck([
      makeSlide('interactive_fill_blank', {
        title: 'Fill in',
        fill_blanks: makeBlanks(8),
      }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    expect(layout.textBlocks.filter((b) => b.role === 'blank_statement')).toHaveLength(5);
    expect(layout.textBlocks.filter((b) => b.role === 'blank_answer')).toHaveLength(5);
  });

  it('places the reveal_trigger below the last answer and within the bottom margin', () => {
    const deck = buildTestDeck([
      makeSlide('interactive_fill_blank', {
        title: 'Fill in',
        fill_blanks: makeBlanks(3),
      }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    const answers = layout.textBlocks.filter((b) => b.role === 'blank_answer');
    const lastAnswerBottom = Math.max(...answers.map((b) => b.y + b.measuredHeightPct));
    const trigger = layout.textBlocks.find((b) => b.role === 'reveal_trigger')!;
    expect(trigger.y).toBeGreaterThanOrEqual(lastAnswerBottom);
    expect(trigger.y).toBeLessThanOrEqual(92);
  });

  it('scales tall content to fit on-slide — no block past the 94% bottom margin', () => {
    // Probed pre-fix: 5 long items ran to ~128% (off-slide, silent). The scale+rebuild
    // helper must keep every content block AND the reveal trigger within the slide.
    const LONG =
      'In the eighteenth century the philosophers of the Enlightenment argued at ' +
      'considerable length that human institutions could be perfected through the ' +
      'patient application of reason, observation, and sustained public debate.';
    const deck = buildTestDeck([
      makeSlide('interactive_fill_blank', {
        title: 'Fill in',
        fill_blanks: Array.from({ length: 5 }, () => ({ statement: LONG, answer: LONG })),
      }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    const content = layout.textBlocks.filter(
      (b) => b.role === 'blank_statement' || b.role === 'blank_answer',
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
    const HUGE = ('Reason and observation '.repeat(40) + '____').trim();
    const deck = buildTestDeck([
      makeSlide('interactive_fill_blank', {
        title: 'Fill in',
        fill_blanks: Array.from({ length: 5 }, () => ({ statement: HUGE, answer: HUGE })),
      }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    // still on-slide…
    const content = layout.textBlocks.filter(
      (b) => b.role === 'blank_statement' || b.role === 'blank_answer',
    );
    expect(Math.max(...content.map((b) => b.y + b.measuredHeightPct))).toBeLessThanOrEqual(94);
    // …but the audit can see it could not really fit
    expect(layout.hasOverflow).toBe(true);
  });

  it('localizes the reveal trigger label (ru / kaa)', () => {
    const ruDeck = buildTestDeck(
      [
        makeSlide('interactive_fill_blank', {
          title: 'Заполни',
          fill_blanks: makeBlanks(2),
        }),
      ],
      'ru',
    );
    const ruLayout = new LayoutPass().layoutSlide(ruDeck.slides[0]!, ruDeck);
    const ruTrigger = ruLayout.textBlocks.find((b) => b.role === 'reveal_trigger');
    expect(ruTrigger!.text).toBe('Показать ответ');

    const kaaDeck = buildTestDeck(
      [
        makeSlide('interactive_fill_blank', {
          title: 'Toltır',
          fill_blanks: makeBlanks(2),
        }),
      ],
      'kaa',
    );
    const kaaLayout = new LayoutPass().layoutSlide(kaaDeck.slides[0]!, kaaDeck);
    const kaaTrigger = kaaLayout.textBlocks.find((b) => b.role === 'reveal_trigger');
    expect(kaaTrigger!.text).toBe('Jauapdı kórset');
  });
});
