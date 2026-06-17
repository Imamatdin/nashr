import { describe, expect, it } from 'vitest';
import { LayoutPass } from '../src/layout-pass.js';
import { MARGIN, SLIDE_REGIONS } from '../src/constants.js';
import { buildTestDeck, makeSlide } from './helpers.js';
import type { FlowStep, TextBlock } from '../src/types.js';

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

/**
 * Region fill + no-overlap regression suite (feat/layout-fill).
 *
 * Locks the de-hardcode: step rows are sized against the actual content
 * region (title-bottom → bottom-margin) and centered there, descriptions
 * are measured rather than clamped to a fixed 15% slot, and the connector
 * cuts the new number row (not the old hardcoded CONNECTOR_Y=35).
 */
describe('layout — FLOW_PROCESS region fill and no overlap', () => {
  const REGION_BOTTOM = 100 - MARGIN.bottom; // 94
  const titleRegion = SLIDE_REGIONS.flow_process!.title!;
  const TITLE_BOTTOM = titleRegion.y + titleRegion.h; // y=10 for flow_process

  function layoutFor(stepCount: number, descriptions?: string[]): TextBlock[] {
    const flowSteps: FlowStep[] = Array.from({ length: stepCount }, (_, i) => ({
      label: `Step ${i + 1}`,
      description: descriptions?.[i] ?? `Description for step ${i + 1}.`,
    }));
    const deck = buildTestDeck([
      makeSlide('flow_process', { title: 'Pipeline', steps: flowSteps }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    return layout.textBlocks.filter((b) => b.text !== 'Pipeline');
  }

  it('places all step numbers at the same y (shared number row)', () => {
    const blocks = layoutFor(5);
    const numbers = blocks.filter((b) => /^[1-5]$/.test(b.text));
    expect(numbers).toHaveLength(5);
    const ys = numbers.map((n) => n.y);
    const spread = Math.max(...ys) - Math.min(...ys);
    expect(spread).toBeLessThan(0.5);
  });

  it('places all step labels at the same y (shared label row)', () => {
    const blocks = layoutFor(5);
    const labels = blocks.filter((b) => /^Step \d+$/.test(b.text));
    expect(labels).toHaveLength(5);
    const ys = labels.map((b) => b.y);
    const spread = Math.max(...ys) - Math.min(...ys);
    expect(spread).toBeLessThan(0.5);
  });

  it('places all step descriptions at the same top y (shared description row)', () => {
    const blocks = layoutFor(5);
    const descs = blocks.filter((b) => /^Description for step/.test(b.text));
    expect(descs).toHaveLength(5);
    const ys = descs.map((b) => b.y);
    const spread = Math.max(...ys) - Math.min(...ys);
    expect(spread).toBeLessThan(0.5);
  });

  it('content spans the majority of the available content region', () => {
    const blocks = layoutFor(5);
    const tops = blocks.map((b) => b.y);
    const bottoms = blocks.map((b) => b.y + b.h);
    const contentSpan = Math.max(...bottoms) - Math.min(...tops);
    const regionHeight = REGION_BOTTOM - TITLE_BOTTOM;
    // Before the de-hardcode the row was clamped to y=28..65 (37pp) within
    // an 84pp region — 44% fill. After the fix the centered row spans
    // >50% of the region. Threshold is "majority" per the prompt acceptance.
    expect(contentSpan / regionHeight).toBeGreaterThan(0.5);
  });

  it('never overflows the bottom margin even with long descriptions', () => {
    const long = 'A genuinely longer description that runs across multiple lines because the band has room and we want to verify long descriptions do not exit the slide through the bottom margin.';
    const blocks = layoutFor(3, [long, long, long]);
    const epsilon = 0.1;
    for (const b of blocks) {
      expect(b.y + b.h).toBeLessThanOrEqual(REGION_BOTTOM + epsilon);
    }
  });

  it('descriptions sit below the connector line (no overlap with the number row)', () => {
    const deck = buildTestDeck([
      makeSlide('flow_process', { title: 'Pipeline', steps: steps(4) }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    const connector = layout.shapes.find((s) => s.type === 'line');
    expect(connector).toBeDefined();
    const descriptions = layout.textBlocks.filter((b) => /^Description \d+\.$/.test(b.text));
    expect(descriptions).toHaveLength(4);
    for (const d of descriptions) {
      expect(d.y).toBeGreaterThan(connector!.y);
    }
  });

  it('adjacent step columns do not overlap horizontally', () => {
    const blocks = layoutFor(4);
    const labels = blocks
      .filter((b) => /^Step \d+$/.test(b.text))
      .sort((a, b) => a.x - b.x);
    for (let i = 1; i < labels.length; i++) {
      const prev = labels[i - 1]!;
      const cur = labels[i]!;
      // Two adjacent columns may abut but must not overlap.
      expect(cur.x).toBeGreaterThanOrEqual(prev.x + prev.w - 0.01);
    }
  });
});

/**
 * Distribute (space-between) anchor lock — L2 layout-engine extraction (Run 1).
 *
 * flow_process now routes its three shared rows (number / label / description)
 * through fitMeasuredStack with anchor:'distribute', overflow:'truncate'.
 * Distribute pins the first band to the region top, the last band to the region
 * BOTTOM, and spreads leftover slack evenly into the n−1 interior gaps on top of
 * the bare gapAfter floors. These tests discriminate that behaviour from the old
 * centred stack: under 'center' the description bottom would sit at
 * 94 − slack/2 (well above 94) and the interior gaps would equal the bare floors
 * exactly (no spread). They also pin the closure-returns-HUGGED-h decision in the
 * source: measure() returns each row's max block.h (carrying HUG_EPSILON_PCT 0.2),
 * NOT measuredHeightPct, so the tallest description lands exactly on the region
 * bottom rather than 0.2pp past it.
 */
describe('layout — FLOW_PROCESS distribute anchor', () => {
  const REGION_BOTTOM = 100 - MARGIN.bottom; // 94
  // Mirror the floor gaps declared in src/layouts/flow-process.ts. Distribute
  // adds even-spread slack ON TOP of these, so the realised gaps must EXCEED them.
  const NUMBER_TO_LABEL_GAP = 2;
  const LABEL_TO_DESCRIPTION_GAP = 1.5;

  function flowLayout(stepCount: number, descriptions?: string[]): TextBlock[] {
    const flowSteps: FlowStep[] = Array.from({ length: stepCount }, (_, i) => ({
      label: `Step ${i + 1}`,
      description: descriptions?.[i] ?? `Description ${i + 1}.`,
    }));
    const deck = buildTestDeck([
      makeSlide('flow_process', { title: 'Pipeline', steps: flowSteps }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    return layout.textBlocks.filter((b) => b.text !== 'Pipeline');
  }

  it('distribute pins the last row to the region bottom', () => {
    // Short single-line descriptions ⇒ large positive slack. Under distribute
    // the last band (descriptions) bottom-aligns to the region bottom; under a
    // centred stack the bottom would sit far above 94. The tallest description's
    // bottom (max over y+h) lands on 94 within HUG_EPSILON tolerance.
    const blocks = flowLayout(3);
    const descs = blocks.filter((b) => /^Description \d+\.$/.test(b.text));
    expect(descs).toHaveLength(3);
    const maxDescriptionBottom = Math.max(...descs.map((d) => d.y + d.h));
    expect(maxDescriptionBottom).toBeCloseTo(REGION_BOTTOM, 1); // |Δ| < 0.05, well inside ~0.3
  });

  it('interior gaps exceed the bare floors', () => {
    // Distribute spreads surplus slack into BOTH interior gaps, so each realised
    // gap strictly exceeds its gapAfter floor — proving the slack was spread, not
    // clumped at one end (centre) nor stranded at the bottom (start).
    const blocks = flowLayout(3);
    const numbers = blocks.filter((b) => /^[1-9]$/.test(b.text));
    const labels = blocks.filter((b) => /^Step \d+$/.test(b.text));
    const descs = blocks.filter((b) => /^Description \d+\.$/.test(b.text));
    expect(numbers).toHaveLength(3);
    expect(labels).toHaveLength(3);
    expect(descs).toHaveLength(3);

    const numberY = numbers[0]!.y;
    const labelY = labels[0]!.y;
    const descriptionY = descs[0]!.y;
    const maxNumberH = Math.max(...numbers.map((b) => b.h));
    const maxLabelH = Math.max(...labels.map((b) => b.h));

    expect(labelY - (numberY + maxNumberH)).toBeGreaterThan(NUMBER_TO_LABEL_GAP);
    expect(descriptionY - (labelY + maxLabelH)).toBeGreaterThan(LABEL_TO_DESCRIPTION_GAP);
  });

  it('HUG_EPSILON regression guard', () => {
    // Long (~180-char) descriptions wrap to a multi-line band while still leaving
    // positive slack. measure() returns the HUGGED block.h (measuredHeightPct +
    // HUG_EPSILON_PCT 0.2), so distribute lands the tallest description bottom on
    // 94.0 EXACTLY. A refactor that returns measuredHeightPct from measure() while
    // the block keeps its hugged h would short the band by 0.2pp and push the
    // bottom to ~94.2. The threshold sits strictly between 94.0 and 94.2 so that
    // regression fails loudly; the lower bound confirms the band still fills to
    // the bottom (not stranded/overflowed). The spec's nominal 0.25 tolerance is
    // intentionally tightened — at 0.25 the broken 94.2 would slip through.
    const long =
      'A deliberately long step description meant to wrap across several lines so the description band consumes meaningful vertical space within the content region of this flow slide here.';
    const blocks = flowLayout(3, [long, long, long]);
    const maxBottom = Math.max(...blocks.map((b) => b.y + b.h));
    expect(maxBottom).toBeLessThanOrEqual(94.1);
    expect(maxBottom).toBeGreaterThan(93.8);
  });
});
