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

  it('emits a reveal_trigger so HTML can reveal framework labels', () => {
    const deck = buildTestDeck([
      makeSlide('interactive_debate', {
        title: 'Debate',
        debate_prompt: 'Pick one.',
        debate_options: makeOptions(),
      }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    const triggers = layout.textBlocks.filter((b) => b.role === 'reveal_trigger');
    expect(triggers).toHaveLength(1);
  });

  it('localizes the reveal trigger label (ru / kaa)', () => {
    const ruDeck = buildTestDeck(
      [
        makeSlide('interactive_debate', {
          title: 'Debate',
          debate_prompt: 'Выберите.',
          debate_options: makeOptions(),
        }),
      ],
      'ru',
    );
    const ruLayout = new LayoutPass().layoutSlide(ruDeck.slides[0]!, ruDeck);
    const ruTrigger = ruLayout.textBlocks.find((b) => b.role === 'reveal_trigger');
    expect(ruTrigger!.text).toBe('Показать ответ');

    const kaaDeck = buildTestDeck(
      [
        makeSlide('interactive_debate', {
          title: 'Debate',
          debate_prompt: 'Birewdi tańlań.',
          debate_options: makeOptions(),
        }),
      ],
      'kaa',
    );
    const kaaLayout = new LayoutPass().layoutSlide(kaaDeck.slides[0]!, kaaDeck);
    const kaaTrigger = kaaLayout.textBlocks.find((b) => b.role === 'reveal_trigger');
    expect(kaaTrigger!.text).toBe('Jauapdı kórset');
  });

  // --- L2 fit-migration tripwires ---------------------------------------------

  it('stacks each framework directly below its own position, in item order', () => {
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
    const frameworks = layout.textBlocks
      .filter((b) => b.role === 'debate_framework')
      .sort((a, b) => (a.dataIndex ?? 0) - (b.dataIndex ?? 0));
    expect(positions).toHaveLength(3);
    expect(frameworks).toHaveLength(3);
    for (let i = 0; i < positions.length; i++) {
      // framework sits below its own position (same groupId), not overlapping it
      expect(frameworks[i]!.groupId).toBe(positions[i]!.groupId);
      expect(frameworks[i]!.y).toBeGreaterThanOrEqual(
        positions[i]!.y + positions[i]!.measuredHeightPct,
      );
      // items do not overlap: the next position starts below this framework's bottom
      if (i + 1 < positions.length) {
        expect(positions[i + 1]!.y).toBeGreaterThanOrEqual(
          frameworks[i]!.y + frameworks[i]!.measuredHeightPct,
        );
      }
    }
  });

  it('caps at MAX_POSITIONS=3 and silently drops the overflow', () => {
    const deck = buildTestDeck([
      makeSlide('interactive_debate', {
        title: 'Debate',
        debate_prompt: 'Pick one.',
        debate_options: [
          ...makeOptions(),
          { position: 'A fourth view that overflows the cap.', framework_label: 'Utilitarianism' },
        ],
      }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    expect(layout.textBlocks.filter((b) => b.role === 'debate_position')).toHaveLength(3);
    expect(layout.textBlocks.filter((b) => b.role === 'debate_framework')).toHaveLength(3);
  });

  it('places the reveal_trigger below the last framework and within the bottom margin', () => {
    const deck = buildTestDeck([
      makeSlide('interactive_debate', {
        title: 'Debate',
        debate_prompt: 'Pick one.',
        debate_options: makeOptions(),
      }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    const frameworks = layout.textBlocks.filter((b) => b.role === 'debate_framework');
    const lastFrameworkBottom = Math.max(...frameworks.map((b) => b.y + b.measuredHeightPct));
    const trigger = layout.textBlocks.find((b) => b.role === 'reveal_trigger')!;
    expect(trigger.y).toBeLessThanOrEqual(94);
    // The trigger clamps to the bottom-margin floor (94); only assert it sits below
    // the last framework when it is NOT clamped (matches the fill_blank/true_false guard).
    if (trigger.y < 94) {
      expect(trigger.y).toBeGreaterThanOrEqual(lastFrameworkBottom);
    }
  });

  it('wraps a long position to its measured height instead of truncating it', () => {
    // The migration payoff: a position that needs several lines must WRAP (and
    // push its framework + the next item down) rather than be truncated to a fixed
    // slot. The string is long enough to wrap to 3+ lines so its measured bottom
    // comfortably exceeds the old fixed +8 framework offset — this is the
    // migration-proving tripwire, not merely migration-consistent.
    const longPosition =
      'In the eighteenth century the philosophers of the European Enlightenment ' +
      'argued at very considerable length, in salons and pamphlets and private ' +
      'correspondence alike, that human institutions of every kind could and ' +
      'indeed should be perfected through the patient and collective application ' +
      'of reason, careful observation, free inquiry, and open public debate.';
    const deck = buildTestDeck([
      makeSlide('interactive_debate', {
        title: 'Debate',
        debate_prompt: 'Pick one.',
        debate_options: [
          { position: longPosition, framework_label: 'Rationalism' },
          { position: 'A short rival view.', framework_label: 'Empiricism' },
        ],
      }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    const positions = layout.textBlocks
      .filter((b) => b.role === 'debate_position')
      .sort((a, b) => (a.dataIndex ?? 0) - (b.dataIndex ?? 0));
    const frameworks = layout.textBlocks
      .filter((b) => b.role === 'debate_framework')
      .sort((a, b) => (a.dataIndex ?? 0) - (b.dataIndex ?? 0));
    expect(positions[0]!.truncated).toBeFalsy();
    // proof it genuinely wrapped: the long position measured TALLER than the short
    // one (so the assertions below are not vacuously true on a single line).
    expect(positions[0]!.measuredHeightPct).toBeGreaterThan(positions[1]!.measuredHeightPct);
    // the long position occupies its full wrapped height, and its framework +
    // the following position are pushed below its real wrapped bottom
    expect(frameworks[0]!.y).toBeGreaterThanOrEqual(
      positions[0]!.y + positions[0]!.measuredHeightPct,
    );
    expect(positions[1]!.y).toBeGreaterThanOrEqual(
      frameworks[0]!.y + frameworks[0]!.measuredHeightPct,
    );
  });

  it('scales tall content to fit on-slide — no block past the 94% bottom margin', () => {
    // Probed pre-fix: 3 long positions ran past the 58%-tall positions band (off-slide,
    // silent). The scale+rebuild helper must keep every content block AND the reveal
    // trigger within the slide.
    const LONG =
      'In the eighteenth century the philosophers of the European Enlightenment ' +
      'argued at very considerable length, in salons and pamphlets and private ' +
      'correspondence alike, that human institutions of every kind could and ' +
      'indeed should be perfected through the patient and collective application ' +
      'of reason, careful observation, free inquiry, and open public debate.';
    const deck = buildTestDeck([
      makeSlide('interactive_debate', {
        title: 'Debate',
        debate_prompt: 'Which view best fits the Enlightenment, and why does it matter today?',
        debate_options: [
          { position: LONG, framework_label: 'Rationalism' },
          { position: LONG, framework_label: 'Empiricism' },
          { position: LONG, framework_label: 'Contractarianism' },
        ],
      }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    const content = layout.textBlocks.filter(
      (b) => b.role === 'debate_position' || b.role === 'debate_framework',
    );
    const maxBottom = Math.max(...content.map((b) => b.y + b.measuredHeightPct));
    expect(maxBottom).toBeLessThanOrEqual(94);
    const trigger = layout.textBlocks.find((b) => b.role === 'reveal_trigger')!;
    expect(trigger.y).toBeLessThanOrEqual(94);
    // trigger sits below the content it reveals (no overlap)
    expect(trigger.y).toBeGreaterThanOrEqual(maxBottom - 1e-6);
  });

  it('flags hasOverflow when content cannot fit even after scaling', () => {
    // Extreme content that must truncate even at the scaled budget → genuine
    // can't-fit must be observable (compose hasOverflow), not silent.
    const HUGE = 'Reason and observation guide every institution '.repeat(40).trim();
    const deck = buildTestDeck([
      makeSlide('interactive_debate', {
        title: 'Debate',
        debate_prompt: 'Pick one.',
        debate_options: [
          { position: HUGE, framework_label: HUGE },
          { position: HUGE, framework_label: HUGE },
          { position: HUGE, framework_label: HUGE },
        ],
      }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    // still on-slide…
    const content = layout.textBlocks.filter(
      (b) => b.role === 'debate_position' || b.role === 'debate_framework',
    );
    expect(Math.max(...content.map((b) => b.y + b.measuredHeightPct))).toBeLessThanOrEqual(94);
    // …but the audit can see it could not really fit
    expect(layout.hasOverflow).toBe(true);
  });
});
