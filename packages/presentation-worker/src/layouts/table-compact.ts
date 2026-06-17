/**
 * TABLE_COMPACT layout.
 *
 * Geometry is COMPUTED FROM CONTENT, not divided from a frozen area. Every cell
 * is measured (buildTextBlock's measuredHeightPct); each row band hugs its
 * tallest cell plus padding; the bands are summed and the whole table is the
 * thing that must fit the region — when it fits it is centred, when it doesn't
 * every band scales by the same content-derived factor (never a clamped min/max
 * row height). Cells centre vertically via `valign:'middle'`, honoured by both
 * renderers from one source instead of the layout faking it through `y`.
 *
 * Emphasis is read from the contract the editorial executor authored:
 * `table_preferred_column` gets an accent column tint + an accent, bold header
 * (the subject the table argues for); `table_hero_row` gets a surface band + a
 * heavier cell weight (the dominant row). A flat table with a clear subject no
 * longer renders every column identically.
 *
 * Column alignment is still detected per-column (numeric → right): alignment is
 * a readability concern, distinct from — and coexisting with — emphasis.
 *
 * A header-less call falls back to CONTENT_SPLIT so the slide still renders
 * something meaningful instead of an empty grid.
 */

import { FONT_SIZES, LINE_HEIGHTS, SLIDE_HEIGHT, SLIDE_REGIONS, type Region } from '../constants.js';
import type {
  DeckSpec,
  FontWeight,
  ShapeBlock,
  SlideLayout,
  SlideSpec,
  TableRow,
  TextAlign,
  TextBlock,
} from '../types.js';
import { buildTextBlock, compose, defaultBackground } from './shared.js';
import { layoutContentSplit } from './content-split.js';

// Model cap: SlideContent.table_rows is max_length 7 — never render more rows
// than the contract can carry.
const MAX_ROWS = 7;

// Vertical breathing above + below a cell's text inside its row band (slide %).
// The one design number that sets how airy the table reads; everything else is
// derived from the measured content.
const CELL_PAD_Y = 1.3;
// Horizontal inset so cell text never touches the column edge or the adjacent
// column's highlight fill (slide %).
const CELL_PAD_X = 1.0;

// Accent tint behind the subject (preferred) column — strong enough to read as
// "this column is the answer", light enough to keep the cell text at full
// contrast over it.
const PREFERRED_COLUMN_OPACITY = 0.14;
// Surface band behind the dominant (hero) row — a readable highlight, not the
// old 0.03 ghost zebra.
const HERO_ROW_OPACITY = 0.5;
// Accent rule under the header row, and the faint dividers between data rows
// that replace per-row zebra with one uniform, intentional treatment.
const HEADER_RULE_OPACITY = 0.6;
const HEADER_RULE_THICKNESS = 0.25; // slide %
const ROW_DIVIDER_OPACITY = 0.12;
const ROW_DIVIDER_THICKNESS = 0.1; // slide %

const NUMERIC_RE = /^[\d$%.,\s+-]+$/;

export function layoutTableCompact(slide: SlideSpec, deck: DeckSpec): SlideLayout {
  const headers = slide.content.table_headers ?? [];
  const rows = (slide.content.table_rows ?? []).slice(0, MAX_ROWS);
  if (headers.length === 0) {
    return layoutContentSplit(slide, deck);
  }

  const { design } = deck;
  const regions = SLIDE_REGIONS.table_compact!;
  const region = regions.body!;
  const blocks: TextBlock[] = [];
  const shapes: ShapeBlock[] = [];

  blocks.push(
    buildTextBlock({
      text: slide.content.title,
      region: regions.title!,
      fontFamily: design.heading_font,
      fontWeight: 'bold',
      color: design.palette.text,
      align: 'left',
      tier: FONT_SIZES.heading,
      lineHeight: LINE_HEIGHTS.heading,
    }),
  );

  const columnCount = headers.length;
  const columnWidth = region.w / columnCount;
  const cellWidth = Math.max(1, columnWidth - 2 * CELL_PAD_X);
  const cellTier = FONT_SIZES.small;
  // A non-empty cell is at least one line tall; derive that floor from the line
  // box so an all-but-empty row never collapses to a hairline (NOT a frozen min).
  const oneLinePct = ((cellTier.max * LINE_HEIGHTS.caption) / SLIDE_HEIGHT) * 100;
  const alignments = detectColumnAlignments(columnCount, rows);

  // --- Measure: each band hugs its tallest cell's wrapped content ---
  const measure = (text: string, weight: FontWeight): number =>
    buildTextBlock({
      text: text || ' ',
      region: { x: 0, y: 0, w: cellWidth, h: region.h },
      fontFamily: design.body_font,
      fontWeight: weight,
      color: design.palette.text,
      align: 'left',
      tier: cellTier,
      lineHeight: LINE_HEIGHTS.caption,
    }).measuredHeightPct;

  const headerContent = Math.max(oneLinePct, ...headers.map((h) => measure(h, 'bold')));
  const rowContent = rows.map((row) =>
    Math.max(
      oneLinePct,
      ...Array.from({ length: columnCount }, (_, j) => measure(row.cells[j] ?? '', 'normal')),
    ),
  );

  // Bands = measured content + padding. Sum them; the table is the thing that
  // must fit the region. It fits → centre it; it overflows → scale every band by
  // the same content/region factor (derived, not a clamped row height) and let
  // buildTextBlock's shrink+truncate be the per-cell reliability floor.
  const rawHeader = headerContent + 2 * CELL_PAD_Y;
  const rawRows = rowContent.map((h) => h + 2 * CELL_PAD_Y);
  const rawTotal = rawHeader + rawRows.reduce((sum, h) => sum + h, 0);
  const scale = rawTotal > region.h ? region.h / rawTotal : 1;

  const headerBand = rawHeader * scale;
  const rowBands = rawRows.map((h) => h * scale);
  const tableHeight = headerBand + rowBands.reduce((sum, h) => sum + h, 0);
  const tableTop = region.y + Math.max(0, (region.h - tableHeight) / 2);

  const preferredColumn = indexInRange(slide.content.table_preferred_column, columnCount);
  const heroRow = indexInRange(slide.content.table_hero_row, rows.length);

  const rowTop = (i: number): number =>
    tableTop + headerBand + rowBands.slice(0, i).reduce((sum, h) => sum + h, 0);

  // --- Emphasis + structure fills (behind the text) ---
  if (heroRow !== null) {
    shapes.push({
      type: 'rect',
      x: region.x,
      y: rowTop(heroRow),
      w: region.w,
      h: rowBands[heroRow]!,
      fill: design.palette.surface,
      opacity: HERO_ROW_OPACITY,
    });
  }
  if (preferredColumn !== null) {
    shapes.push({
      type: 'rect',
      x: region.x + preferredColumn * columnWidth,
      y: tableTop,
      w: columnWidth,
      h: tableHeight,
      fill: design.palette.accent,
      opacity: PREFERRED_COLUMN_OPACITY,
    });
  }
  shapes.push({
    type: 'rect',
    x: region.x,
    y: tableTop + headerBand - HEADER_RULE_THICKNESS,
    w: region.w,
    h: HEADER_RULE_THICKNESS,
    fill: design.palette.accent,
    opacity: HEADER_RULE_OPACITY,
  });
  for (let i = 0; i < rowBands.length - 1; i++) {
    shapes.push({
      type: 'rect',
      x: region.x,
      y: rowTop(i) + rowBands[i]! - ROW_DIVIDER_THICKNESS / 2,
      w: region.w,
      h: ROW_DIVIDER_THICKNESS,
      fill: design.palette.text_secondary,
      opacity: ROW_DIVIDER_OPACITY,
    });
  }

  // --- Header cells (preferred column header reads in accent) ---
  headers.forEach((header, j) => {
    blocks.push(
      buildCell({
        text: header,
        columnIndex: j,
        bandTop: tableTop,
        bandHeight: headerBand,
        weight: 'bold',
        color: j === preferredColumn ? design.palette.accent : design.palette.text,
        align: alignments[j] ?? 'left',
        region,
        columnWidth,
        cellWidth,
        fontFamily: design.body_font,
      }),
    );
  });

  // --- Data cells (hero row reads heavier) ---
  rows.forEach((row, i) => {
    const bandTop = rowTop(i);
    const weight: FontWeight = i === heroRow ? 'semibold' : 'normal';
    for (let j = 0; j < columnCount; j++) {
      blocks.push(
        buildCell({
          text: row.cells[j] ?? '',
          columnIndex: j,
          bandTop,
          bandHeight: rowBands[i]!,
          weight,
          color: design.palette.text,
          align: alignments[j] ?? 'left',
          region,
          columnWidth,
          cellWidth,
          fontFamily: design.body_font,
        }),
      );
    }
  });

  if (slide.content.source_citation) {
    blocks.push(
      buildTextBlock({
        text: slide.content.source_citation,
        region: regions.citation!,
        fontFamily: design.body_font,
        fontWeight: 'normal',
        color: design.palette.text_secondary,
        align: 'left',
        tier: FONT_SIZES.small,
        lineHeight: LINE_HEIGHTS.caption,
      }),
    );
  }

  return compose(slide, blocks, [], shapes, defaultBackground(design));
}

interface CellOptions {
  text: string;
  columnIndex: number;
  bandTop: number;
  bandHeight: number;
  weight: FontWeight;
  color: string;
  align: TextAlign;
  region: Region;
  columnWidth: number;
  cellWidth: number;
  fontFamily: string;
}

/**
 * Build a cell text block sized to its full row band and vertically centred.
 *
 * The box spans the whole band (`bandHeight`); the measured text is shorter
 * (the band already added padding), so `valign:'middle'` leaves equal breathing
 * above and below. When the table was scaled down to fit, the band is tighter
 * than the content and buildTextBlock shrinks/truncates the cell — the per-cell
 * reliability floor — and the centring still holds.
 */
function buildCell(opts: CellOptions): TextBlock {
  const block = buildTextBlock({
    text: opts.text,
    region: {
      x: opts.region.x + opts.columnIndex * opts.columnWidth + CELL_PAD_X,
      y: opts.bandTop,
      w: opts.cellWidth,
      h: opts.bandHeight,
    },
    fontFamily: opts.fontFamily,
    fontWeight: opts.weight,
    color: opts.color,
    align: opts.align,
    tier: FONT_SIZES.small,
    lineHeight: LINE_HEIGHTS.caption,
  });
  block.valign = 'middle';
  return block;
}

/** Clamp an authored emphasis index to a valid slot, or null when absent/out of range. */
function indexInRange(value: number | null | undefined, count: number): number | null {
  if (value === null || value === undefined) return null;
  return value >= 0 && value < count ? value : null;
}

function detectColumnAlignments(columnCount: number, rows: TableRow[]): TextAlign[] {
  const result: TextAlign[] = [];
  for (let j = 0; j < columnCount; j++) {
    const values = rows.map((r) => (r.cells[j] ?? '').trim()).filter((v) => v.length > 0);
    if (values.length === 0) {
      result.push('left');
      continue;
    }
    const numericCount = values.filter((v) => NUMERIC_RE.test(v)).length;
    result.push(numericCount * 2 > values.length ? 'right' : 'left');
  }
  return result;
}
