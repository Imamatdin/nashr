/**
 * Unit tests for the measurement-driven fit engine (`src/layouts/fit.ts`).
 *
 * These are PURE-ARITHMETIC tests: each `FitItem.measure()` returns a literal
 * number, so no LayoutPass / measureText is involved and the assertions are
 * machine-portable. They pin the engine's three anchors (start / center /
 * distribute), the two overflow policies (scale / truncate), the strict-'>'
 * scaling boundary, band padding, the empty-stack base case, and `emitBandCell`.
 */

import { describe, expect, it } from 'vitest';
import { emitBandCell, fitMeasuredStack, type FitItem } from '../src/layouts/fit.js';
import type { Region } from '../src/constants.js';
import type { TextBlock } from '../src/types.js';

/** Build a FitItem whose measured content height is a fixed literal. */
function item(measure: number, gapAfter?: number): FitItem {
  return gapAfter === undefined ? { measure: () => measure } : { measure: () => measure, gapAfter };
}

function sum(xs: number[]): number {
  return xs.reduce((s, x) => s + x, 0);
}

describe('fitMeasuredStack — anchor:start', () => {
  it('flows from region.y; tops are running offsets of bands + gaps; heights are bands; scale=1', () => {
    const region: Region = { x: 5, y: 10, w: 40, h: 100 };
    const items = [item(20, 5), item(30, 8), item(15)];

    const { tops, heights, scale } = fitMeasuredStack({
      region,
      items,
      overflow: 'truncate',
      anchor: 'start',
    });

    expect(scale).toBe(1);
    expect(heights).toEqual([20, 30, 15]);
    // start: region.y, then +band0+gap0, then +band1+gap1
    expect(tops[0]).toBe(10);
    expect(tops[1]).toBe(10 + 20 + 5);
    expect(tops[2]).toBe(10 + 20 + 5 + 30 + 8);
  });

  it('leaves leftover slack unused at the bottom (does not reach region bottom)', () => {
    const region: Region = { x: 0, y: 0, w: 50, h: 200 };
    const items = [item(20), item(20)]; // content 40 << 200

    const { tops, heights } = fitMeasuredStack({
      region,
      items,
      overflow: 'truncate',
      anchor: 'start',
    });

    expect(tops[0]).toBe(0);
    const lastBottom = tops[1]! + heights[1]!;
    expect(lastBottom).toBeLessThan(region.y + region.h);
  });
});

describe('fitMeasuredStack — anchor:center', () => {
  it('pushes the stack down by half the slack and is vertically symmetric', () => {
    const region: Region = { x: 0, y: 10, w: 50, h: 100 };
    const items = [item(20, 4), item(16)];
    // content = 20 + 4 + 16 = 40; slack = 60; top slack should be 30
    const { tops, heights } = fitMeasuredStack({
      region,
      items,
      overflow: 'truncate',
      anchor: 'center',
    });

    const content = sum(heights) + 4; // one interior gap of 4
    const topSlack = tops[0]! - region.y;
    const lastBottom = tops[tops.length - 1]! + heights[heights.length - 1]!;
    const bottomSlack = region.y + region.h - lastBottom;

    expect(tops[0]).toBeGreaterThan(region.y);
    expect(topSlack).toBeCloseTo((region.h - content) / 2, 9);
    expect(topSlack).toBeCloseTo(bottomSlack, 9);
  });
});

describe('fitMeasuredStack — anchor:distribute', () => {
  it('n>=2: first band at top, last band flush to bottom, equal interior gaps', () => {
    const region: Region = { x: 0, y: 0, w: 50, h: 120 };
    // three zero-floor bands of 20 each -> content 60, slack 60, n-1=2 interior gaps
    const items = [item(20), item(20), item(20)];

    const { tops, heights } = fitMeasuredStack({
      region,
      items,
      overflow: 'truncate',
      anchor: 'distribute',
    });

    expect(tops[0]).toBe(region.y);
    const lastBottom = tops[2]! + heights[2]!;
    expect(lastBottom).toBeCloseTo(region.y + region.h, 9);

    const gap01 = tops[1]! - (tops[0]! + heights[0]!);
    const gap12 = tops[2]! - (tops[1]! + heights[1]!);
    expect(gap01).toBeCloseTo(gap12, 9);
    // slack 60 split into 2 interior gaps -> 30 each
    expect(gap01).toBeCloseTo(30, 9);
  });

  it('realized interior gap EXCEEDS the gapAfter floor when there is surplus slack', () => {
    const region: Region = { x: 0, y: 0, w: 50, h: 100 };
    // bands 20+20+20=60, floors 5+5 (last dropped) -> rawTotal 70, slack 30
    // extra = 30 / (n-1=2) = 15; realized interior gap = floor 5 + 15 = 20
    const floor = 5;
    const items = [item(20, floor), item(20, floor), item(20, floor)];

    const { tops, heights } = fitMeasuredStack({
      region,
      items,
      overflow: 'truncate',
      anchor: 'distribute',
    });

    const gap01 = tops[1]! - (tops[0]! + heights[0]!);
    const gap12 = tops[2]! - (tops[1]! + heights[1]!);

    expect(gap01).toBeGreaterThan(floor);
    expect(gap01).toBeCloseTo(gap12, 9);
    expect(gap01).toBeCloseTo(floor + 15, 9);
    // last band still flush to the bottom
    expect(tops[2]! + heights[2]!).toBeCloseTo(region.y + region.h, 9);
  });

  it('n===1 degenerates to start (tops[0] === region.y)', () => {
    const region: Region = { x: 0, y: 7, w: 50, h: 100 };
    const items = [item(20)];

    const distributed = fitMeasuredStack({
      region,
      items,
      overflow: 'truncate',
      anchor: 'distribute',
    });
    const started = fitMeasuredStack({
      region,
      items,
      overflow: 'truncate',
      anchor: 'start',
    });

    expect(distributed.tops[0]).toBe(region.y);
    expect(distributed.tops).toEqual(started.tops);
    expect(distributed.heights).toEqual(started.heights);
  });

  it('no surplus (content already fills region): interior gaps stay at the floor', () => {
    const region: Region = { x: 0, y: 0, w: 50, h: 45 };
    // bands 20+20=40, floor 5 -> rawTotal 45 == region.h, slack 0, no extra
    const items = [item(20, 5), item(20, 5)];

    const { tops, heights } = fitMeasuredStack({
      region,
      items,
      overflow: 'truncate',
      anchor: 'distribute',
    });

    const gap01 = tops[1]! - (tops[0]! + heights[0]!);
    expect(gap01).toBeCloseTo(5, 9);
  });
});

describe('fitMeasuredStack — overflow:scale', () => {
  it('fires when rawTotal > region.h: scale<1, Σheights ≈ region.h, band ratios preserved', () => {
    const region: Region = { x: 0, y: 0, w: 50, h: 60 };
    // bands 40 + 80 = 120 > 60 -> scale = 60/120 = 0.5
    const items = [item(40), item(80)];

    const { heights, scale } = fitMeasuredStack({
      region,
      items,
      overflow: 'scale',
      anchor: 'start',
    });

    expect(scale).toBeLessThan(1);
    expect(scale).toBeCloseTo(0.5, 9);
    expect(sum(heights)).toBeCloseTo(region.h, 9);
    // relative ratio of the two bands is preserved (40:80 == 1:2)
    expect(heights[1]! / heights[0]!).toBeCloseTo(2, 9);
  });

  it('scales gaps along with bands so the whole stack fits to the region bottom', () => {
    const region: Region = { x: 0, y: 0, w: 50, h: 50 };
    // bands 40+40=80, gap 20 -> rawTotal 100 > 50, scale = 0.5
    const items = [item(40, 20), item(40)];

    const { tops, heights, scale } = fitMeasuredStack({
      region,
      items,
      overflow: 'scale',
      anchor: 'start',
    });

    expect(scale).toBeCloseTo(0.5, 9);
    // start-anchored scaled stack consumes exactly region.h (no leftover slack)
    const lastBottom = tops[1]! + heights[1]!;
    expect(lastBottom).toBeCloseTo(region.y + region.h, 9);
  });
});

describe('fitMeasuredStack — overflow:truncate', () => {
  it('keeps scale===1 even when content exceeds the region (bands may overflow)', () => {
    const region: Region = { x: 0, y: 0, w: 50, h: 30 };
    const items = [item(40), item(80)]; // 120 >> 30

    const { heights, scale } = fitMeasuredStack({
      region,
      items,
      overflow: 'truncate',
      anchor: 'start',
    });

    expect(scale).toBe(1);
    expect(heights).toEqual([40, 80]);
    expect(sum(heights)).toBeGreaterThan(region.h);
  });
});

describe('fitMeasuredStack — strict ">" boundary', () => {
  it('does NOT scale when rawTotal === region.h exactly', () => {
    const region: Region = { x: 0, y: 0, w: 50, h: 100 };
    // bands 40+60=100, no gaps -> rawTotal === region.h, strict '>' is false
    const items = [item(40), item(60)];

    const { heights, scale } = fitMeasuredStack({
      region,
      items,
      overflow: 'scale',
      anchor: 'start',
    });

    expect(scale).toBe(1);
    expect(heights).toEqual([40, 60]);
  });

  it('scales as soon as rawTotal exceeds region.h by any amount', () => {
    const region: Region = { x: 0, y: 0, w: 50, h: 100 };
    const items = [item(40), item(60.0001)];

    const { scale } = fitMeasuredStack({
      region,
      items,
      overflow: 'scale',
      anchor: 'start',
    });

    expect(scale).toBeLessThan(1);
    expect(scale).toBeGreaterThan(1 - 1e-3);
  });
});

describe('fitMeasuredStack — padding', () => {
  it('each band height === measure() + 2*padding when scale=1', () => {
    const region: Region = { x: 0, y: 0, w: 50, h: 1000 }; // huge -> never scales
    const padding = 3;
    const items = [item(20), item(10)];

    const { heights, scale } = fitMeasuredStack({
      region,
      items,
      padding,
      overflow: 'scale',
      anchor: 'start',
    });

    expect(scale).toBe(1);
    expect(heights[0]).toBe(20 + 2 * padding);
    expect(heights[1]).toBe(10 + 2 * padding);
  });

  it('padding participates in rawTotal so it can trigger overflow scaling', () => {
    const region: Region = { x: 0, y: 0, w: 50, h: 30 };
    const padding: number = 5;
    // bands = (10+10) + (10+10) = 40 > 30 -> scale = 30/40 = 0.75
    const items = [item(10), item(10)];

    const { heights, scale } = fitMeasuredStack({
      region,
      items,
      padding,
      overflow: 'scale',
      anchor: 'start',
    });

    expect(scale).toBeCloseTo(0.75, 9);
    expect(sum(heights)).toBeCloseTo(region.h, 9);
  });
});

describe('fitMeasuredStack — empty stack (n===0)', () => {
  it('returns {tops:[], heights:[], scale:1}', () => {
    const region: Region = { x: 1, y: 2, w: 3, h: 4 };
    const result = fitMeasuredStack({
      region,
      items: [],
      overflow: 'scale',
      anchor: 'distribute',
    });

    expect(result).toEqual({ tops: [], heights: [], scale: 1 });
  });
});

describe('emitBandCell', () => {
  function minimalBlock(): TextBlock {
    return {
      text: 'cell',
      x: 5,
      y: 0,
      w: 40,
      h: 0,
      fontSize: 18,
      fontFamily: 'EB Garamond',
      fontWeight: 'normal',
      fontStyle: 'normal',
      color: '#000000',
      align: 'left',
      lineHeight: 1.2,
      overflow: false,
      measuredHeightPct: 0,
    };
  }

  it('sets y, h, and valign==="middle", and returns the same object', () => {
    const block = minimalBlock();
    const bandTop = 12.5;
    const bandHeight = 7.25;

    const returned = emitBandCell(block, bandTop, bandHeight);

    expect(returned).toBe(block); // mutates and returns the same reference
    expect(block.y).toBe(bandTop);
    expect(block.h).toBe(bandHeight);
    expect(block.valign).toBe('middle');
  });

  it('overwrites any prior y/h/valign with the band values', () => {
    const block = minimalBlock();
    block.y = 99;
    block.h = 99;
    block.valign = 'top';

    emitBandCell(block, 3, 4);

    expect(block.y).toBe(3);
    expect(block.h).toBe(4);
    expect(block.valign).toBe('middle');
  });
});
