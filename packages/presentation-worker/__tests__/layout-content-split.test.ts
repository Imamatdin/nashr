/**
 * CONTENT_SPLIT layout — dead-gap fix + fallback safety.
 *
 * content_split had no dedicated test file. This file locks two things the
 * L2 layout-engine extraction is responsible for:
 *
 *  1. The DEAD-GAP FIX. The body column now derives from the title's REAL
 *     measured bottom (stackBelow(title, BODY_GAP=2)) instead of being pinned
 *     to the frozen region floor (body.y === 18) with a MIN_BODY_H box. A short
 *     title + short body must therefore sit high and hug its content, not strand
 *     a one-line body at y=18 inside a ~69%-tall transparent box.
 *
 *  2. The FALLBACK SAFETY (non-negotiable). content_split is the fallback for
 *     several types (table_compact with no headers, typographic_keywords with no
 *     keywords). With the MIN_BODY_H / full-region box removed, the only thing
 *     standing between a content-light slide and a crash is the `if (bodyText)`
 *     guard around the body block. composeBodyText returning null must yield a
 *     title-only slide, never a throw.
 *
 * Geometry note: measureText uses character-width estimation on this machine
 * (no fontconfig), but the engine choice (truncate, never scale) makes the
 * RELATIONSHIPS asserted here robust — the body hugs measured content, clears
 * the caption, and a degraded body truncates rather than overflowing/blocking.
 */

import { describe, expect, it } from 'vitest';
import { LayoutPass } from '../src/layout-pass.js';
import { buildTestDeck, makeSlide } from './helpers.js';

// Mirrors the constants the layout uses (content-split.ts BODY_GAP / the frozen
// content_split body region y, and the caption strip y from SLIDE_REGIONS).
const BODY_GAP = 2;
const OLD_BODY_FLOOR_Y = 18; // SLIDE_REGIONS.content_split.body.y — the floor that was removed
const FULL_BODY_COLUMN_H = 65; // the old MIN_BODY_H / full-region box height (≈ region.h)
const CAPTION_Y = 88; // SLIDE_REGIONS.content_split.caption.y

function layoutContentSplit(content: Parameters<typeof makeSlide>[1]) {
  const deck = buildTestDeck([makeSlide('content_split', content)]);
  return new LayoutPass().layoutSlide(deck.slides[0]!, deck);
}

describe('layout — CONTENT_SPLIT dead-gap fix', () => {
  it('short title + body: no dead gap (body sits at title bottom + BODY_GAP, not the old floor)', () => {
    const layout = layoutContentSplit({
      title: 'Origins',
      body_text: 'A short remark.',
    });

    const title = layout.textBlocks.find((b) => b.text === 'Origins')!;
    const body = layout.textBlocks.find((b) => b.text.includes('A short remark'))!;
    expect(title).toBeDefined();
    expect(body).toBeDefined();

    // The body's top is the title's MEASURED bottom plus the one-line buffer gap,
    // NOT the frozen region floor. This is the dead-gap fix: a short title pulls
    // the body up with it instead of leaving an 18%-high empty band above it.
    expect(body.y).toBeCloseTo(title.y + title.measuredHeightPct + BODY_GAP, 5);

    // Concretely: the body sits ABOVE the old pinned floor (18). If the floor
    // were still in force the body would be stuck at y≈18 regardless of the
    // short title.
    expect(body.y).toBeLessThan(OLD_BODY_FLOOR_Y);
  });

  it('short body hugs (no dead box): body.h is one-two lines, not the full column', () => {
    const layout = layoutContentSplit({
      title: 'Origins',
      body_text: 'A short remark.',
    });
    const body = layout.textBlocks.find((b) => b.text.includes('A short remark'))!;

    // hugHeightToMeasured shrank the box to the content: a one-line body is a
    // few percent tall, NOT the ~65% full body column the old MIN_BODY_H / full
    // region box produced.
    expect(body.h).toBeLessThan(12);
    expect(body.h).toBeLessThan(FULL_BODY_COLUMN_H);
    // And the box still covers the measured content (no per-block clip).
    expect(body.h).toBeGreaterThanOrEqual(body.measuredHeightPct);
  });

  it('body valign stays top (never middle — content_split reads from the top)', () => {
    const layout = layoutContentSplit({
      title: 'Origins',
      body_text: 'A short remark.',
    });
    const body = layout.textBlocks.find((b) => b.text.includes('A short remark'))!;
    // Guards against an accidental emitBandCell on the body block: content_split
    // must NOT centre its body the way the table centres a cell.
    expect(body.valign === 'top' || body.valign === undefined).toBe(true);
    expect(body.valign).not.toBe('middle');
  });

  it('overflowing body truncates, never blocks (truncate is the floor, not scale)', () => {
    // A body far longer than the column can hold at the minimum font. The fit
    // engine is anchor:'start' + overflow:'truncate' here, so the per-block
    // shrink+truncate is the only reliability floor — it must degrade, not block.
    const longBody = 'Lorem ipsum dolor sit amet consectetur adipiscing elit. '.repeat(60);
    expect(longBody.length).toBeGreaterThan(1200);

    const layout = layoutContentSplit({ title: 'Big topic', body_text: longBody });
    const body = layout.textBlocks.find((b) => b.text.includes('Lorem'))!;

    // The string was shortened-and-ellipsized to fit (the L1 reliability floor).
    expect(body.truncated).toBe(true);
    // overflow:'truncate' never lets the block report a hard overflow, and the
    // deck stays exportable — the slide-level overflow flag is clear.
    expect(body.overflow).toBe(false);
    expect(layout.hasOverflow).toBe(false);
  });

  it('body clears the caption (body bottom sits above the caption strip)', () => {
    const longBody = 'Lorem ipsum dolor sit amet consectetur adipiscing elit. '.repeat(60);
    const layout = layoutContentSplit({
      title: 'Big topic',
      body_text: longBody,
      caption: 'Figure 1 — source.',
    });

    const body = layout.textBlocks.find((b) => b.text.includes('Lorem'))!;
    const caption = layout.textBlocks.find((b) => b.text.includes('Figure 1'))!;
    expect(caption.y).toBeCloseTo(CAPTION_Y, 5);

    // Even a long body bottom-clears the caption strip — the body column is
    // capped at caption.y minus a clearance, so the two boxes never touch.
    expect(body.y + body.h).toBeLessThanOrEqual(caption.y - 0.5);
  });
});

describe('layout — CONTENT_SPLIT fallback safety (non-negotiable)', () => {
  it('(i) header-less table_compact routes to content_split and renders a non-empty body without throwing', () => {
    const deck = buildTestDeck([
      makeSlide('table_compact', {
        title: 'Title only',
        body_text: 'A paragraph of fallback content.',
        table_headers: [],
      }),
    ]);

    let layout!: ReturnType<LayoutPass['layoutSlide']>;
    expect(() => {
      layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    }).not.toThrow();

    // The content_split fallback emits no table shapes (the header background /
    // dividers are gone) and renders the fallback body.
    expect(layout.shapes).toHaveLength(0);
    const body = layout.textBlocks.find((b) => b.text.includes('fallback content'));
    expect(body).toBeDefined();
  });

  it('(ii) keyword-less typographic_keywords routes to content_split and renders safely', () => {
    const deck = buildTestDeck([
      makeSlide('typographic_keywords', {
        title: 'No keywords here',
        body_text: 'Fallback prose stands in for the missing keywords.',
      }),
    ]);

    let layout!: ReturnType<LayoutPass['layoutSlide']>;
    expect(() => {
      layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    }).not.toThrow();

    const title = layout.textBlocks.find((b) => b.text === 'No keywords here');
    const body = layout.textBlocks.find((b) => b.text.includes('Fallback prose'));
    expect(title).toBeDefined();
    expect(body).toBeDefined();
  });

  it('(iii) content_split with no body content at all renders title-only — the if(bodyText) guard holds', () => {
    // composeBodyText returns null (no body_text, no bullets), so the body branch
    // must be skipped entirely: no body block, no throw, title still rendered.
    let layout!: ReturnType<LayoutPass['layoutSlide']>;
    expect(() => {
      layout = layoutContentSplit({ title: 'Only a title' });
    }).not.toThrow();

    const title = layout.textBlocks.find((b) => b.text === 'Only a title');
    expect(title).toBeDefined();

    // No body block exists: the only text block is the title (no caption supplied).
    expect(layout.textBlocks).toHaveLength(1);
    expect(layout.textBlocks[0]!.text).toBe('Only a title');
  });
});
