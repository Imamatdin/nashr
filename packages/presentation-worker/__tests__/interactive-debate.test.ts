import { describe, expect, it } from 'vitest';
import { LayoutPass } from '../src/layout-pass.js';
import { buildTestDeck, makeSlide } from './helpers.js';
import type { DebateOption } from '../src/types.js';

function makeOptions(): DebateOption[] {
  return [
    { position: 'Reason should guide policy.', framework_label: 'Rationalism' },
    { position: 'Experience builds knowledge.', framework_label: 'Empiricism' },
    { position: 'Society is a social contract.', framework_label: 'Contractarianism' },
  ];
}

describe('layout — INTERACTIVE_DEBATE', () => {
  it('emits exactly one prompt block and one block per position/framework', () => {
    const deck = buildTestDeck([
      makeSlide('interactive_debate', {
        title: 'Debate',
        debate_prompt: 'Which view best fits the Enlightenment?',
        debate_options: makeOptions(),
      }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    expect(layout.textBlocks.filter((b) => b.role === 'debate_prompt')).toHaveLength(1);
    expect(layout.textBlocks.filter((b) => b.role === 'debate_position')).toHaveLength(3);
    expect(layout.textBlocks.filter((b) => b.role === 'debate_framework')).toHaveLength(3);
  });

  it('numbers position text with "1. «", "2. «", "3. «"', () => {
    const deck = buildTestDeck([
      makeSlide('interactive_debate', {
        title: 'Debate',
        debate_prompt: 'Pick one.',
        debate_options: makeOptions(),
      }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    const positions = layout.textBlocks
      .filter((b) => b.role === 'debate_position')
      .sort((a, b) => (a.dataIndex ?? 0) - (b.dataIndex ?? 0));
    expect(positions[0]!.text.startsWith('1. «')).toBe(true);
    expect(positions[1]!.text.startsWith('2. «')).toBe(true);
    expect(positions[2]!.text.startsWith('3. «')).toBe(true);
  });

  it('renders frameworks in italic and accent colour', () => {
    const deck = buildTestDeck([
      makeSlide('interactive_debate', {
        title: 'Debate',
        debate_prompt: 'Pick one.',
        debate_options: makeOptions(),
      }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    const accent = deck.design.palette.accent;
    const frameworks = layout.textBlocks.filter((b) => b.role === 'debate_framework');
    expect(frameworks).toHaveLength(3);
    for (const f of frameworks) {
      expect(f.fontStyle).toBe('italic');
      expect(f.color).toBe(accent);
    }
  });

  it('shares groupId between position and framework for the same option', () => {
    const deck = buildTestDeck([
      makeSlide('interactive_debate', {
        title: 'Debate',
        debate_prompt: 'Pick one.',
        debate_options: makeOptions(),
      }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    const d0 = layout.textBlocks.filter((b) => b.groupId === 'd0');
    expect(d0.filter((b) => b.role === 'debate_position')).toHaveLength(1);
    expect(d0.filter((b) => b.role === 'debate_framework')).toHaveLength(1);
  });

  it('centers the prompt block', () => {
    const deck = buildTestDeck([
      makeSlide('interactive_debate', {
        title: 'Debate',
        debate_prompt: 'Pick one.',
        debate_options: makeOptions(),
      }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    const prompt = layout.textBlocks.find((b) => b.role === 'debate_prompt');
    expect(prompt).toBeDefined();
    expect(prompt!.align).toBe('center');
  });
});
