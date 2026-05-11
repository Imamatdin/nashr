import { describe, expect, it } from 'vitest';
import { LayoutPass } from '../src/layout-pass.js';
import { buildTestDeck, makeSlide } from './helpers.js';
import type {
  CategoryItem,
  DebateOption,
  FillBlankItem,
  MatchingPair,
  QuizQuestion,
  SlideContent,
  SlideType,
  TrueFalseItem,
} from '../src/types.js';

const INTERACTIVE_TYPES: SlideType[] = [
  'interactive_quiz_mcq',
  'interactive_matching',
  'interactive_categorize',
  'interactive_fill_blank',
  'interactive_true_false',
  'interactive_debate',
];

const quizQuestions: QuizQuestion[] = [
  {
    question: 'q0?',
    options: [
      { text: 'a', is_correct: true },
      { text: 'b', is_correct: false },
      { text: 'c', is_correct: false },
    ],
    explanation_correct: 'yes',
    explanation_wrong: 'no',
  },
  {
    question: 'q1?',
    options: [
      { text: 'x', is_correct: false },
      { text: 'y', is_correct: true },
      { text: 'z', is_correct: false },
    ],
    explanation_correct: 'yes',
    explanation_wrong: 'no',
  },
  {
    question: 'q2?',
    options: [
      { text: 'p', is_correct: true },
      { text: 'q', is_correct: false },
      { text: 'r', is_correct: false },
    ],
    explanation_correct: 'yes',
    explanation_wrong: 'no',
  },
];

const matchingPairs: MatchingPair[] = [
  { left: 'L0', right: 'R0' },
  { left: 'L1', right: 'R1' },
];
const categoryLabels = ['Cat A', 'Cat B'];
const categoryItems: CategoryItem[] = [
  { term: 'a', category: 'Cat A' },
  { term: 'b', category: 'Cat B' },
];
const fillBlanks: FillBlankItem[] = [
  { statement: 's0 with ____', answer: 'one' },
  { statement: 's1 with ____', answer: 'two' },
];
const trueFalseItems: TrueFalseItem[] = [
  { statement: 'tf0', is_true: true, explanation: 'because' },
  { statement: 'tf1', is_true: false, explanation: 'no' },
];
const debateOptions: DebateOption[] = [
  { position: 'P0', framework_label: 'F0' },
  { position: 'P1', framework_label: 'F1' },
];

function fixtureFor(type: SlideType): SlideContent {
  switch (type) {
    case 'interactive_quiz_mcq':
      return { title: 'Q', quiz_questions: quizQuestions };
    case 'interactive_matching':
      return { title: 'M', matching_pairs: matchingPairs };
    case 'interactive_categorize':
      return {
        title: 'C',
        category_labels: categoryLabels,
        category_items: categoryItems,
      };
    case 'interactive_fill_blank':
      return { title: 'F', fill_blanks: fillBlanks };
    case 'interactive_true_false':
      return { title: 'T', true_false_items: trueFalseItems };
    case 'interactive_debate':
      return {
        title: 'D',
        debate_prompt: 'Decide',
        debate_options: debateOptions,
      };
    default:
      return { title: 'X' };
  }
}

describe('interactive role tagging', () => {
  it('does not set a role on content slides (title_hero)', () => {
    const deck = buildTestDeck([
      makeSlide('title_hero', { title: 'Hello', subtitle: 'World' }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    for (const block of layout.textBlocks) {
      expect(block.role === undefined || block.role === 'static').toBe(true);
    }
  });

  it('sets a role on every text block of every interactive slide type', () => {
    for (const type of INTERACTIVE_TYPES) {
      const deck = buildTestDeck([makeSlide(type, fixtureFor(type))]);
      const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
      for (const block of layout.textBlocks) {
        expect(block.role, `slide_type=${type} text="${block.text}"`).toBeDefined();
      }
    }
  });

  it('uses distinct groupIds across quiz questions', () => {
    const deck = buildTestDeck([
      makeSlide('interactive_quiz_mcq', {
        title: 'Q',
        quiz_questions: quizQuestions,
      }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    const groupIds = new Set(
      layout.textBlocks
        .filter((b) => b.role === 'question')
        .map((b) => b.groupId),
    );
    expect(groupIds.has('q0')).toBe(true);
    expect(groupIds.has('q1')).toBe(true);
    expect(groupIds.has('q2')).toBe(true);
    expect(groupIds.size).toBe(3);

    for (const gid of ['q0', 'q1', 'q2']) {
      const g = layout.textBlocks.filter((b) => b.groupId === gid);
      expect(g.filter((b) => b.role === 'question')).toHaveLength(1);
      expect(g.filter((b) => b.role === 'feedback_correct')).toHaveLength(1);
      expect(g.filter((b) => b.role === 'feedback_wrong')).toHaveLength(1);
      const opts = g.filter((b) => b.role === 'option_correct' || b.role === 'option_wrong');
      expect(opts.length).toBeGreaterThan(0);
    }
  });

  it('produces sequential dataIndex values across quiz options', () => {
    const deck = buildTestDeck([
      makeSlide('interactive_quiz_mcq', {
        title: 'Q',
        quiz_questions: [
          {
            question: 'one?',
            options: [
              { text: 'a', is_correct: true },
              { text: 'b', is_correct: false },
              { text: 'c', is_correct: false },
              { text: 'd', is_correct: false },
            ],
            explanation_correct: 'y',
            explanation_wrong: 'n',
          },
        ],
      }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    const indices = layout.textBlocks
      .filter(
        (b) =>
          b.groupId === 'q0' && (b.role === 'option_correct' || b.role === 'option_wrong'),
      )
      .map((b) => b.dataIndex)
      .sort((a, b) => (a ?? 0) - (b ?? 0));
    expect(indices).toEqual([0, 1, 2, 3]);
  });
});
