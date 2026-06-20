import { describe, expect, it } from 'vitest';
import { LayoutPass } from '../src/layout-pass.js';
import { buildTestDeck, makeSlide } from './helpers.js';
import type { QuizQuestion } from '../src/types.js';

function makeQuestion(idx: number, optionCount = 3): QuizQuestion {
  const options = Array.from({ length: optionCount }, (_, i) => ({
    text: `Option ${idx}-${i}`,
    is_correct: i === 0,
  }));
  return {
    question: `Question ${idx}?`,
    options,
    explanation_correct: `Correct because ${idx}.`,
    explanation_wrong: `Wrong because ${idx}.`,
  };
}

describe('layout — INTERACTIVE_QUIZ_MCQ', () => {
  it('has the right number of question and option blocks', () => {
    const deck = buildTestDeck([
      makeSlide('interactive_quiz_mcq', {
        title: 'Quiz time',
        quiz_questions: [makeQuestion(0, 3), makeQuestion(1, 3)],
      }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);

    const questions = layout.textBlocks.filter((b) => b.role === 'question');
    expect(questions).toHaveLength(2);

    const options = layout.textBlocks.filter(
      (b) => b.role === 'option_correct' || b.role === 'option_wrong',
    );
    expect(options.length).toBe(6);
    expect(options.filter((b) => b.role === 'option_correct')).toHaveLength(2);
  });

  it('labels options with A) B) C) D) prefixes', () => {
    const deck = buildTestDeck([
      makeSlide('interactive_quiz_mcq', {
        title: 'Quiz',
        quiz_questions: [makeQuestion(0, 4)],
      }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    const opts = layout.textBlocks
      .filter((b) => b.role === 'option_correct' || b.role === 'option_wrong')
      .sort((a, b) => (a.dataIndex ?? 0) - (b.dataIndex ?? 0));
    expect(opts).toHaveLength(4);
    expect(opts[0]!.text.startsWith('A) ')).toBe(true);
    expect(opts[1]!.text.startsWith('B) ')).toBe(true);
    expect(opts[2]!.text.startsWith('C) ')).toBe(true);
    expect(opts[3]!.text.startsWith('D) ')).toBe(true);
  });

  it('has one feedback_correct and one feedback_wrong per question', () => {
    const deck = buildTestDeck([
      makeSlide('interactive_quiz_mcq', {
        title: 'Quiz',
        quiz_questions: [makeQuestion(0), makeQuestion(1), makeQuestion(2)],
      }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    expect(layout.textBlocks.filter((b) => b.role === 'feedback_correct')).toHaveLength(3);
    expect(layout.textBlocks.filter((b) => b.role === 'feedback_wrong')).toHaveLength(3);
  });

  it('co-locates feedback_correct and feedback_wrong at the same y per question', () => {
    // The two feedback blocks are mutually-exclusive overlays (the renderer
    // reveals exactly one per answer), so they MUST share a y. This is the
    // frozen-by-design invariant a naive fitMeasuredStack migration would break.
    const deck = buildTestDeck([
      makeSlide('interactive_quiz_mcq', {
        title: 'Quiz',
        quiz_questions: [makeQuestion(0), makeQuestion(1), makeQuestion(2)],
      }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    const correct = layout.textBlocks.filter((b) => b.role === 'feedback_correct');
    const wrong = layout.textBlocks.filter((b) => b.role === 'feedback_wrong');
    expect(correct).toHaveLength(3);
    expect(wrong).toHaveLength(3);
    for (const c of correct) {
      const w = wrong.find((b) => b.groupId === c.groupId);
      expect(w).toBeDefined();
      expect(w!.y).toBe(c.y);
    }
  });

  it('uses localized feedback labels (ru / kaa)', () => {
    const ruDeck = buildTestDeck(
      [
        makeSlide('interactive_quiz_mcq', {
          title: 'Quiz',
          quiz_questions: [makeQuestion(0)],
        }),
      ],
      'ru',
    );
    const ruLayout = new LayoutPass().layoutSlide(ruDeck.slides[0]!, ruDeck);
    const ruCorrect = ruLayout.textBlocks.find((b) => b.role === 'feedback_correct');
    expect(ruCorrect!.text.startsWith('Правильно')).toBe(true);

    const kaaDeck = buildTestDeck(
      [
        makeSlide('interactive_quiz_mcq', {
          title: 'Quiz',
          quiz_questions: [makeQuestion(0)],
        }),
      ],
      'kaa',
    );
    const kaaLayout = new LayoutPass().layoutSlide(kaaDeck.slides[0]!, kaaDeck);
    const kaaCorrect = kaaLayout.textBlocks.find((b) => b.role === 'feedback_correct');
    expect(kaaCorrect!.text.startsWith('Dúrıs')).toBe(true);
  });

  it('groups question, options, and feedback under one groupId per question', () => {
    const deck = buildTestDeck([
      makeSlide('interactive_quiz_mcq', {
        title: 'Quiz',
        quiz_questions: [makeQuestion(0, 4), makeQuestion(1, 4)],
      }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    const g0 = layout.textBlocks.filter((b) => b.groupId === 'q0');
    const g1 = layout.textBlocks.filter((b) => b.groupId === 'q1');
    expect(g0.filter((b) => b.role === 'question')).toHaveLength(1);
    expect(g0.filter((b) => b.role === 'feedback_correct')).toHaveLength(1);
    expect(g0.filter((b) => b.role === 'feedback_wrong')).toHaveLength(1);
    expect(g0.filter((b) => b.role === 'option_correct' || b.role === 'option_wrong'))
      .toHaveLength(4);
    expect(g1.filter((b) => b.role === 'question')).toHaveLength(1);
  });

  it('caps at 3 questions per slide', () => {
    const deck = buildTestDeck([
      makeSlide('interactive_quiz_mcq', {
        title: 'Quiz',
        quiz_questions: [0, 1, 2, 3, 4].map((i) => makeQuestion(i)),
      }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    expect(layout.textBlocks.filter((b) => b.role === 'question')).toHaveLength(3);
  });

  it('uses localized nav labels (uz / kaa)', () => {
    const uzDeck = buildTestDeck(
      [
        makeSlide('interactive_quiz_mcq', {
          title: 'Quiz',
          quiz_questions: [makeQuestion(0)],
        }),
      ],
      'uz',
    );
    const uzLayout = new LayoutPass().layoutSlide(uzDeck.slides[0]!, uzDeck);
    const uzNav = uzLayout.textBlocks.filter((b) => b.role === 'nav_label').map((b) => b.text);
    expect(uzNav).toContain('Keyingi');
    expect(uzNav).toContain('Orqaga');

    const kaaDeck = buildTestDeck(
      [
        makeSlide('interactive_quiz_mcq', {
          title: 'Quiz',
          quiz_questions: [makeQuestion(0)],
        }),
      ],
      'kaa',
    );
    const kaaLayout = new LayoutPass().layoutSlide(kaaDeck.slides[0]!, kaaDeck);
    const kaaNav = kaaLayout.textBlocks.filter((b) => b.role === 'nav_label').map((b) => b.text);
    expect(kaaNav).toContain('Kelesi');
    expect(kaaNav).toContain('Artqa');
  });

  it('does not crash when quiz_questions is empty', () => {
    const deck = buildTestDeck([
      makeSlide('interactive_quiz_mcq', {
        title: 'Empty quiz',
        quiz_questions: [],
      }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    expect(layout.textBlocks.filter((b) => b.role === 'question')).toHaveLength(0);
    expect(layout.textBlocks.find((b) => b.text === 'Empty quiz')).toBeDefined();
  });
});
