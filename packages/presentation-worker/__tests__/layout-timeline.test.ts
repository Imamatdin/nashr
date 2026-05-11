import { describe, expect, it } from 'vitest';
import { LayoutPass } from '../src/layout-pass.js';
import { buildTestDeck, makeSlide } from './helpers.js';
import type { TimelineNode } from '../src/types.js';

function nodes(count: number): TimelineNode[] {
  return Array.from({ length: count }, (_, i) => ({
    date: `${1700 + i * 20}`,
    label: `Event ${i + 1}`,
  }));
}

describe('layout — TIMELINE', () => {
  it('renders a horizontal line shape stroked in the accent colour', () => {
    const deck = buildTestDeck([
      makeSlide('timeline', { title: 'Era', timeline_nodes: nodes(4) }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    const lines = layout.shapes.filter((s) => s.type === 'line');
    expect(lines.length).toBeGreaterThanOrEqual(1);
    const baseline = lines[0]!;
    expect(baseline.stroke).toBe(deck.design.palette.accent);
    expect(baseline.h).toBe(0);
    expect(baseline.w).toBeGreaterThan(50);
  });

  it('places one accent-coloured circle per node', () => {
    const deck = buildTestDeck([
      makeSlide('timeline', { title: 'Era', timeline_nodes: nodes(4) }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    const circles = layout.shapes.filter((s) => s.type === 'circle');
    expect(circles).toHaveLength(4);
    for (const c of circles) {
      expect(c.fill).toBe(deck.design.palette.accent);
    }
  });

  it('spaces nodes evenly between 10% and 90% of slide width', () => {
    const deck = buildTestDeck([
      makeSlide('timeline', { title: 'Era', timeline_nodes: nodes(4) }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    const xs = layout.shapes
      .filter((s) => s.type === 'circle')
      .map((s) => s.x)
      .sort((a, b) => a - b);
    expect(xs[0]).toBeCloseTo(10, 1);
    expect(xs[xs.length - 1]).toBeCloseTo(90, 1);
    const gap = (xs[xs.length - 1]! - xs[0]!) / (xs.length - 1);
    for (let i = 1; i < xs.length; i++) {
      expect(xs[i]! - xs[i - 1]!).toBeCloseTo(gap, 1);
    }
  });

  it('puts dates above the line and labels below it', () => {
    const deck = buildTestDeck([
      makeSlide('timeline', { title: 'Era', timeline_nodes: nodes(3) }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    const dates = layout.textBlocks.filter((b) => /^\d{4}$/.test(b.text));
    const labels = layout.textBlocks.filter((b) => b.text.startsWith('Event '));
    expect(dates).toHaveLength(3);
    expect(labels).toHaveLength(3);
    for (const d of dates) expect(d.y).toBeLessThan(45);
    for (const l of labels) expect(l.y).toBeGreaterThan(45);
  });

  it('centres a single node at x=50%', () => {
    const deck = buildTestDeck([
      makeSlide('timeline', { title: 'Era', timeline_nodes: nodes(1) }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    const circles = layout.shapes.filter((s) => s.type === 'circle');
    expect(circles).toHaveLength(1);
    expect(circles[0]!.x).toBeCloseTo(50, 1);
  });
});
