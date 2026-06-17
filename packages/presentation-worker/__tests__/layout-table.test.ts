import { describe, expect, it } from 'vitest';
import { LayoutPass } from '../src/layout-pass.js';
import { HtmlRenderer } from '../src/renderers/html-renderer.js';
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

  it('separates rows with uniform dividers, not per-odd-row zebra', () => {
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
    // One faint divider between each adjacent data-row pair — uniform, not the
    // old alternating per-odd-row surface zebra.
    const dividers = layout.shapes.filter(
      (s) => s.fill === deck.design.palette.text_secondary,
    );
    expect(dividers).toHaveLength(3);
    // With no hero row marked, there is no surface band at all (the zebra is gone).
    const surfaceFills = layout.shapes.filter(
      (s) => s.fill === deck.design.palette.surface,
    );
    expect(surfaceFills).toHaveLength(0);
  });

  it('gives the preferred column an accent header and an accent column fill', () => {
    const deck = buildTestDeck([
      makeSlide('table_compact', {
        title: 'sCO2 wins',
        table_headers: ['Metric', 'Air', 'sCO2'],
        table_rows: rows([
          ['PUE', '1.55', '1.08'],
          ['Density', '30', '300'],
        ]),
        table_preferred_column: 2,
      }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);

    const winning = layout.textBlocks.find((b) => b.text === 'sCO2')!;
    expect(winning.color).toBe(deck.design.palette.accent);
    expect(winning.fontWeight).toBe('bold');
    const other = layout.textBlocks.find((b) => b.text === 'Air')!;
    expect(other.color).toBe(deck.design.palette.text);

    // An accent column tint spans the table height (the thin accent header rule
    // is short; the column tint is tall) and sits over the winning column (index
    // 2 of 3: region x=5, columnWidth=90/3=30 → x=65, w=30).
    const accentFills = layout.shapes.filter((s) => s.fill === deck.design.palette.accent);
    const columnTint = accentFills.find((s) => s.h > 10);
    expect(columnTint).toBeDefined();
    expect(columnTint!.x).toBeCloseTo(5 + 2 * (90 / 3), 1); // ≈ 65, column 2 not 0/1
    expect(columnTint!.w).toBeCloseTo(90 / 3, 1); // ≈ 30, exactly one column wide
  });

  it('fills the hero row with a surface band and bolds its cells', () => {
    const deck = buildTestDeck([
      makeSlide('table_compact', {
        title: 'Results',
        table_headers: ['Outcome', 'Air', 'sCO2'],
        table_rows: rows([
          ['Density', '30', '300'],
          ['Payback', 'N/A', '3.2 yr'],
          ['Water', 'High', 'Zero'],
        ]),
        table_hero_row: 1,
      }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);

    const heroBands = layout.shapes.filter((s) => s.fill === deck.design.palette.surface);
    expect(heroBands).toHaveLength(1);
    expect(heroBands[0]!.w).toBeCloseTo(90, 1); // full table width

    const heroCell = layout.textBlocks.find((b) => b.text === 'Payback')!;
    expect(heroCell.fontWeight).toBe('semibold');
    const normalCell = layout.textBlocks.find((b) => b.text === 'Density')!;
    expect(normalCell.fontWeight).toBe('normal');
  });

  it('vertically centers every cell via valign, honored by the HTML renderer', () => {
    const deck = buildTestDeck([
      makeSlide('table_compact', {
        title: 'Comparison',
        table_headers: ['Name', 'Score'],
        table_rows: rows([
          ['Alice', '90'],
          ['Bob', '85'],
        ]),
      }),
    ]);
    const slideLayout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);
    const cells = slideLayout.textBlocks.filter((b) =>
      ['Name', 'Score', 'Alice', '90', 'Bob', '85'].includes(b.text),
    );
    expect(cells).toHaveLength(6);
    for (const c of cells) expect(c.valign).toBe('middle');

    // Renderer parity: the HTML output flex-centers the valign:'middle' boxes.
    const deckLayout = new LayoutPass().layout(deck);
    const html = new HtmlRenderer().render(deck, deckLayout);
    expect(html).toContain('justify-content:center');
  });

  it('scales bands proportionally when content overflows — not to a single floor', () => {
    // Enough text that the measured bands far exceed the 75% region on any font:
    // 7 rows of long multi-line cells forces the proportional-scaling branch.
    const long = 'A genuinely long descriptive cell that wraps across several lines '.repeat(12);
    const cellRows = [
      [long, long, long],
      ['x', 'y', 'z'],
      [long, long, long],
      ['x', 'y', 'z'],
      [long, long, long],
      ['x', 'y', 'z'],
      [long, long, long],
    ];
    const deck = buildTestDeck([
      makeSlide('table_compact', {
        title: 'Overstuffed',
        table_headers: ['Col A', 'Col B', 'Col C'],
        table_rows: rows(cellRows),
      }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);

    const tallCell = layout.textBlocks.find((b) => b.text.startsWith('A genuinely'))!;
    const shortCell = layout.textBlocks.find((b) => b.text === 'x')!;
    // Proportional scaling preserves the relative heights — the multi-line row
    // stays taller than the one-line row; it is NOT cramped to a uniform floor.
    expect(tallCell.h).toBeGreaterThan(shortCell.h);
    // Overflow fired: the scaled table fills the region exactly (bottom ≈ y=90,
    // the region's lower edge) rather than sitting centered with slack.
    const bottoms = layout.textBlocks
      .filter((b) => b.text === 'x' || b.text.startsWith('A genuinely'))
      .map((b) => b.y + b.h);
    const maxBottom = Math.max(...bottoms);
    expect(maxBottom).toBeGreaterThan(89); // proves the scaling branch executed
    expect(maxBottom).toBeLessThanOrEqual(90.5); // and never exceeds the region
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

    // Rows are NOT inflated: the old code divided the 70% data area evenly
    // (~17.5%/row) and pinned text to the top. Each band now hugs measured
    // content + padding, far below the even-division height.
    const evenDivision = (75 - 5) / cellRows.length; // old per-row height ≈ 17.5
    const dataCells = layout.textBlocks.filter((b) => flat.includes(b.text));
    expect(dataCells.length).toBe(flat.length);
    for (const c of dataCells) {
      expect(c.h).toBeLessThan(evenDivision * 0.6);
    }

    // Centering is driven by valign (one source), not y-math: every data cell
    // carries valign:'middle'.
    for (const c of dataCells) expect(c.valign).toBe('middle');

    // The whole table is centered in its region, not pinned to the top: the
    // header row sits below the region top (y=15), pushed down by the centering.
    const header = layout.textBlocks.find((b) => b.text === 'Type')!;
    expect(header).toBeDefined();
    expect(header.y).toBeGreaterThan(15);

    // Data rows sit below the header band.
    const firstRowCell = layout.textBlocks.find((b) => b.text === 'Air cooling')!;
    expect(firstRowCell.y).toBeGreaterThan(header.y);
  });
});

describe('pixel-identical equivalence lock (real pre-migration baselines)', () => {
  // These two fixtures were captured by running the UNMODIFIED (pre-migration)
  // table-compact.ts on the exact inputs below. They are the contract the
  // shared-engine re-point must reproduce byte-for-byte. toBeCloseTo(.,6)
  // absorbs <=1 ULP of float-reassociation drift while still failing on any
  // real geometric regression (a band shift, an off-by-one row map, a scale
  // that fires when it should not).

  it('fixture (a) non-overflow: all 15 cells match the captured baseline', () => {
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

    // x is column-driven (region.x=5, columnWidth=90/3=30, CELL_PAD_X=1):
    // col0=6, col1=36, col2=66. w=cellWidth=28. h is the scaled band height.
    const X = { Name: 6, Year: 36, Score: 66 };
    const W = 28;
    const H = 4.790741;

    // Each row's three cells share one y (the band top). Header band is band 0,
    // each data row k is band k+1 — captured baselines below.
    const expected: Array<{ text: string; x: number; y: number }> = [
      { text: 'Name', x: X.Name, y: 40.523148 },
      { text: 'Year', x: X.Year, y: 40.523148 },
      { text: 'Score', x: X.Score, y: 40.523148 },
      { text: 'Alice', x: X.Name, y: 45.313889 },
      { text: '2024', x: X.Year, y: 45.313889 },
      { text: '90', x: X.Score, y: 45.313889 },
      { text: 'Bob', x: X.Name, y: 50.104630 },
      { text: '2025', x: X.Year, y: 50.104630 },
      { text: '85', x: X.Score, y: 50.104630 },
      { text: 'Carol', x: X.Name, y: 54.895370 },
      { text: '2026', x: X.Year, y: 54.895370 },
      { text: '95', x: X.Score, y: 54.895370 },
      { text: 'Dan', x: X.Name, y: 59.686111 },
      { text: '2027', x: X.Year, y: 59.686111 },
      { text: '80', x: X.Score, y: 59.686111 },
    ];
    // 3 headers + 4 rows * 3 cols = 15 distinct cells; assert every one.
    expect(expected).toHaveLength(15);

    for (const e of expected) {
      const cell = layout.textBlocks.find((b) => b.text === e.text)!;
      expect(cell, `cell ${e.text} must exist`).toBeDefined();
      expect(cell.x, `${e.text}.x`).toBeCloseTo(e.x, 6);
      expect(cell.y, `${e.text}.y`).toBeCloseTo(e.y, 6);
      expect(cell.w, `${e.text}.w`).toBeCloseTo(W, 6);
      expect(cell.h, `${e.text}.h`).toBeCloseTo(H, 6);
    }

    // Explicit off-by-one guard for rowTop(k) -> fit.tops[k+1]: the first data
    // row ('Alice') must sit at the row0 band top, NOT the header band
    // (40.523148) and NOT row1's band (50.104630). A header-vs-row0 or
    // row0-vs-row1 shift makes exactly this assertion fail.
    const alice = layout.textBlocks.find((b) => b.text === 'Alice')!;
    expect(alice.y).toBeCloseTo(45.313889, 6);
    expect(alice.y).not.toBeCloseTo(40.523148, 4);
    expect(alice.y).not.toBeCloseTo(50.104630, 4);

    // Strict monotonic top-to-bottom: header < row0 < row1 < row2 < row3.
    const yOf = (t: string): number => layout.textBlocks.find((b) => b.text === t)!.y;
    expect(yOf('Name')).toBeLessThan(yOf('Alice'));
    expect(yOf('Alice')).toBeLessThan(yOf('Bob'));
    expect(yOf('Bob')).toBeLessThan(yOf('Carol'));
    expect(yOf('Carol')).toBeLessThan(yOf('Dan'));
  });

  it('fixture (c) scale===1 minimal: bands are bit-exact', () => {
    const deck = buildTestDeck([
      makeSlide('table_compact', {
        title: 'Minimal',
        table_headers: ['A', 'B'],
        table_rows: rows([['x', 'y']]),
      }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);

    // x: region.x=5, columnWidth=90/2=45, CELL_PAD_X=1 → col0=6, col1=51.
    // w=cellWidth=43. With scale===1 the band height is exact, so assert h with
    // toBe (bit-identical) and y with toBeCloseTo(.,6).
    const expected: Array<{ text: string; x: number; y: number }> = [
      { text: 'A', x: 6, y: 47.709259 },
      { text: 'B', x: 51, y: 47.709259 },
      { text: 'x', x: 6, y: 52.5 },
      { text: 'y', x: 51, y: 52.5 },
    ];
    const W = 43;
    // Bit-exact band height when scale===1. The spec's "4.790741" is this value
    // rounded to 6 dp; toBe() locks the full-precision constant so any change to
    // the one-line band math (CELL_PAD_Y, tier, line-height) trips the lock.
    const H = 4.790740740740741;

    for (const e of expected) {
      const cell = layout.textBlocks.find((b) => b.text === e.text)!;
      expect(cell, `cell ${e.text} must exist`).toBeDefined();
      expect(cell.x, `${e.text}.x`).toBeCloseTo(e.x, 6);
      expect(cell.y, `${e.text}.y`).toBeCloseTo(e.y, 6);
      expect(cell.w, `${e.text}.w`).toBeCloseTo(W, 6);
      // scale===1 ⇒ band height is the exact constant, bit-for-bit.
      expect(cell.h, `${e.text}.h`).toBe(H);
    }
  });

  it('fixture (b) overflow: scaled bands, fonts, and truncation match the captured baseline', () => {
    // The scale<1 path. buildCell builds each cell against the SCALED band height
    // BEFORE emitBandCell re-stamps it, so the engine's scale must feed the cell
    // build — not just the box geometry. Captured from the UNMODIFIED layout. y/h
    // are the character-width-estimation values this suite runs under (asserted
    // with toBeCloseTo); fontSize / truncated / overflow are the build-against-the
    // -scaled-band discriminators (asserted exactly): a regression that measured a
    // cell at the wrong height then re-stamped h would keep y/h but flip fontSize
    // (12 -> larger) or truncated (true -> false).
    const long = 'A genuinely long descriptive cell that wraps across several lines '.repeat(12);
    const deck = buildTestDeck([
      makeSlide('table_compact', {
        title: 'Overstuffed',
        table_headers: ['Col A', 'Col B', 'Col C'],
        table_rows: rows([
          [long, long, long],
          ['x', 'y', 'z'],
          [long, long, long],
          ['x', 'y', 'z'],
          [long, long, long],
          ['x', 'y', 'z'],
          [long, long, long],
        ]),
      }),
    ]);
    const layout = new LayoutPass().layoutSlide(deck.slides[0]!, deck);

    // Header band (scaled): one line at the full tier, never truncated.
    const header = layout.textBlocks.find((b) => b.text === 'Col A')!;
    expect(header.y).toBeCloseTo(15, 6);
    expect(header.h).toBeCloseTo(2.231609, 6);
    expect(header.fontSize).toBe(14);
    expect(header.truncated ?? false).toBe(false);
    expect(header.overflow).toBe(false);

    // Long cells: built against the SCALED band (16.518391% tall), shrunk to the
    // tier floor (12px) and truncated — the load-bearing "build at the scaled
    // band" signal. Every long cell is identical; assert all 12 (4 rows * 3 cols).
    const longCells = layout.textBlocks.filter((b) => b.text.startsWith('A genuinely'));
    expect(longCells).toHaveLength(12);
    for (const c of longCells) {
      expect(c.h, 'long cell band height').toBeCloseTo(16.518391, 6);
      expect(c.fontSize, 'long cell shrunk to tier floor').toBe(12);
      expect(c.truncated, 'long cell truncated at the scaled band').toBe(true);
      expect(c.overflow, 'reliability floor held').toBe(false);
    }
    const firstLong = longCells.reduce((a, b) => (b.y < a.y ? b : a));
    expect(firstLong.y, 'first long row sits directly under the header band').toBeCloseTo(17.231609, 6);

    // Short cells: one line, full tier, not truncated (9 = 3 rows * 3 cols).
    const shortCells = layout.textBlocks.filter((b) => ['x', 'y', 'z'].includes(b.text));
    expect(shortCells).toHaveLength(9);
    for (const c of shortCells) {
      expect(c.h).toBeCloseTo(2.231609, 6);
      expect(c.fontSize).toBe(14);
      expect(c.truncated ?? false).toBe(false);
      expect(c.overflow).toBe(false);
    }

    // Scale fired and the table fills exactly to the region bottom (y=90), never
    // past it: the last long row bottom is the captured 90.0.
    const maxBottom = Math.max(
      ...layout.textBlocks.filter((b) => b.text !== 'Overstuffed').map((b) => b.y + b.h),
    );
    expect(maxBottom).toBeCloseTo(90, 6);
  });
});
