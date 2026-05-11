import { describe, expect, it } from 'vitest';
import { LayoutPass } from '../src/layout-pass.js';
import { buildTestDeck, makeSlide } from './helpers.js';
import type { FlowStep } from '../src/types.js';

function steps(count: number): FlowStep[] {
  return Array.from({ length: count }, (_, i) => ({
    label: `Step ${i + 1}`,
    description: `Description ${i + 1}.`,
  }));
}

describe('layout — FLOW_PROCESS', () => {
  it('emits one label and one description block per step', () => {
    const deck = buildTestDeck([
      makeSlide('flow_process', { title: 'Pipeline', steps: steps(4) }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    const labels = layout.textBlocks.filter((b) => /^Step \d+$/.test(b.text));
    const descs = layout.textBlocks.filter((b) => /^Description \d+\.$/.test(b.text));
    expect(labels).toHaveLength(4);
    expect(descs).toHaveLength(4);
  });

  it('places connector lines at faint opacity between every pair of steps', () => {
    const deck = buildTestDeck([
      makeSlide('flow_process', { title: 'Pipeline', steps: steps(4) }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    const connectors = layout.shapes.filter((s) => s.type === 'line');
    expect(connectors).toHaveLength(3);
    for (const c of connectors) {
      expect(c.opacity).toBeCloseTo(0.3, 2);
    }
  });

  it('distributes step labels evenly across the slide', () => {
    const deck = buildTestDeck([
      makeSlide('flow_process', { title: 'Pipeline', steps: steps(4) }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    const xs = layout.textBlocks
      .filter((b) => /^Step \d+$/.test(b.text))
      .map((b) => b.x)
      .sort((a, b) => a - b);
    expect(xs).toHaveLength(4);
    const gap = (xs[xs.length - 1]! - xs[0]!) / (xs.length - 1);
    for (let i = 1; i < xs.length; i++) {
      expect(xs[i]! - xs[i - 1]!).toBeCloseTo(gap, 1);
    }
  });
});
