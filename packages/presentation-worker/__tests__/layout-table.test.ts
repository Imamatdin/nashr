import { describe, expect, it } from 'vitest';
import { LayoutPass } from '../src/layout-pass.js';
import { buildTestDeck, makeSlide } from './helpers.js';
import type { TableRow } from '../src/types.js';

function rows(cellRows: string[][]): TableRow[] {
  return cellRows.map((cells) => ({ cells }));
}

describe('layout — TABLE_COMPACT', () => {
  it('renders one bold header block per column', () => {
    const deck = buildTestDeck([
      makeSlide('table_compact', {
        title: 'Comparison',
        table_headers: ['Name', 'Year', 'Score'],
        table_rows: rows([
          ['Alice', '2024', '90'],
          ['Bob', '2025', '85'],
          ['Carol', '2026', '95'],
          ['Dan', '2027', '80'],
        ]),
      }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    const headerBlocks = layout.textBlocks.filter((b) =>
      ['Name', 'Year', 'Score'].includes(b.text),
    );
    expect(headerBlocks).toHaveLength(3);
    for (const h of headerBlocks) expect(h.fontWeight).toBe('bold');
  });

  it('produces one text block per data cell', () => {
    const cellRows = [
      ['Alice', '2024', '90'],
      ['Bob', '2025', '85'],
      ['Carol', '2026', '95'],
      ['Dan', '2027', '80'],
    ];
    const flat = cellRows.flat();
    const deck = buildTestDeck([
      makeSlide('table_compact', {
        title: 'Comparison',
        table_headers: ['Name', 'Year', 'Score'],
        table_rows: rows(cellRows),
      }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    const dataBlocks = layout.textBlocks.filter((b) => flat.includes(b.text));
    expect(dataBlocks.length).toBe(flat.length);
  });

  it('shades odd rows with a faint surface fill', () => {
    const deck = buildTestDeck([
      makeSlide('table_compact', {
        title: 'Comparison',
        table_headers: ['A', 'B'],
        table_rows: rows([
          ['row0', 'r0'],
          ['row1', 'r1'],
          ['row2', 'r2'],
          ['row3', 'r3'],
        ]),
      }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    const shaders = layout.shapes.filter(
      (s) => s.fill === deck.design.palette.surface,
    );
    expect(shaders.length).toBeGreaterThanOrEqual(2);
  });

  it('right-aligns a column dominated by numeric values', () => {
    const deck = buildTestDeck([
      makeSlide('table_compact', {
        title: 'Counts',
        table_headers: ['Name', 'Count'],
        table_rows: rows([
          ['Apple', '100'],
          ['Banana', '200'],
          ['Cherry', '300'],
        ]),
      }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    const numericCells = layout.textBlocks.filter((b) =>
      ['100', '200', '300'].includes(b.text),
    );
    expect(numericCells).toHaveLength(3);
    for (const c of numericCells) expect(c.align).toBe('right');
  });

  it('left-aligns a column of text values', () => {
    const deck = buildTestDeck([
      makeSlide('table_compact', {
        title: 'Fruits',
        table_headers: ['Name', 'Origin'],
        table_rows: rows([
          ['Apple', 'Asia'],
          ['Banana', 'Tropics'],
          ['Cherry', 'Europe'],
        ]),
      }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    const textCells = layout.textBlocks.filter((b) =>
      ['Apple', 'Banana', 'Cherry'].includes(b.text),
    );
    expect(textCells).toHaveLength(3);
    for (const c of textCells) expect(c.align).toBe('left');
  });

  it('falls back to content_split when no table headers are supplied', () => {
    const deck = buildTestDeck([
      makeSlide('table_compact', {
        title: 'Title only',
        body_text: 'A paragraph of fallback content.',
      }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    // The content_split fallback emits no shapes; layoutTableCompact
    // always pushes at least the header background rectangle.
    expect(layout.shapes).toHaveLength(0);
    const body = layout.textBlocks.find((b) =>
      b.text.includes('fallback content'),
    );
    expect(body).toBeDefined();
  });

  it('renders compact, vertically-centered rows — not inflated top-pinned cells (row I)', () => {
    const cellRows = [
      ['Air cooling', '25-30 kW', '1.55-1.80'],
      ['Liquid', '>100 kW', '1.20-1.30'],
      ['Hybrid', '>100 kW', '1.30-1.45'],
      ['sCO2', '300 kW', '1.08'],
    ];
    const flat = cellRows.flat();
    const deck = buildTestDeck([
      makeSlide('table_compact', {
        title: 'Cooling comparison',
        table_headers: ['Type', 'Density', 'PUE'],
        table_rows: rows(cellRows),
      }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);

    // Rows are NO LONGER inflated: the old code gave each cell a ~17.5%-tall box
    // (TABLE_H-HEADER_H / rows) with text pinned to the top. Each cell now hugs
    // its measured height, far below that even-division height.
    const evenDivision = (75 - 5) / cellRows.length; // old per-row height ≈ 17.5
    const dataCells = layout.textBlocks.filter((b) => flat.includes(b.text));
    expect(dataCells.length).toBe(flat.length);
    for (const c of dataCells) {
      expect(c.h).toBeLessThan(evenDivision * 0.6);
    }

    // The table block is centered in its region, not pinned to the top: the
    // header row sits below TABLE_Y (=15), pushed down by the centering.
    const header = layout.textBlocks.find((b) => b.text === 'Type')!;
    expect(header).toBeDefined();
    expect(header.y).toBeGreaterThan(15);

    // Each cell is vertically centered within its band, so the first data row's
    // text begins strictly below the (centered) header — not at the band top.
    const firstRowCell = layout.textBlocks.find((b) => b.text === 'Air cooling')!;
    expect(firstRowCell.y).toBeGreaterThan(header.y);
  });
});
