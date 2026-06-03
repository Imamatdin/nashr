/**
 * TABLE_COMPACT layout.
 *
 * Up to 6 rows of structured data. The header row carries a bold
 * weight and a faint accent-coloured bar (8% opacity); odd data
 * rows pick up a 3% palette.surface shade so the eye can track
 * across the table without explicit grid lines (R37).
 *
 * Column alignment is detected per-column. If more than half of a
 * column's data cells match the "numeric" character class
 * (digits, currency/percent symbols, ±, separators), the whole
 * column is right-aligned (R38). Mixed and text-only columns stay
 * left-aligned.
 *
 * A header-less call (no `table_headers` on the content) falls
 * back to CONTENT_SPLIT so the slide still renders something
 * meaningful instead of an empty grid.
 */

import { FONT_SIZES, LINE_HEIGHTS, type Region } from '../constants.js';
import type {
  DeckSpec,
  ShapeBlock,
  SlideLayout,
  SlideSpec,
  TableRow,
  TextAlign,
  TextBlock,
} from '../types.js';
import { buildTextBlock, compose, defaultBackground, hugHeightToMeasured } from './shared.js';
import { layoutContentSplit } from './content-split.js';

const TITLE: Region = { x: 5, y: 4, w: 90, h: 8 };
const TABLE_X = 5;
const TABLE_W = 90;
const TABLE_Y = 15;
const TABLE_H = 75;
const HEADER_H = 5;
const MAX_ROWS = 6;
/**
 * Cap on a single data row's band height (slide %). Without it, few-row tables
 * divided the whole 70% data area evenly — `(TABLE_H-HEADER_H)/rows` — giving a
 * 4-row table ~17.5%-tall rows with text pinned to the top of each and a large
 * empty cell below (row I). Capping the band, vertically centering each cell's
 * text within it, and centering the whole table block in the region keeps rows
 * compact and the table balanced. This is table geometry, NOT content
 * canvas-fill (deferred to L2): it neither grows fonts nor needs a fit budget.
 */
const MAX_ROW_BAND = 12;
/** Min band so a row never collapses thinner than a comfortable line. */
const MIN_ROW_BAND = 6;
const CITATION: Region = { x: 5, y: 92, w: 90, h: 4 };
const NUMERIC_RE = /^[\d$%.,\s+-]+$/;

export function layoutTableCompact(slide: SlideSpec, deck: DeckSpec): SlideLayout {
  const headers = slide.content.table_headers ?? [];
  const rows = (slide.content.table_rows ?? []).slice(0, MAX_ROWS);
  if (headers.length === 0) {
    return layoutContentSplit(slide, deck);
  }

  const { design } = deck;
  const blocks: TextBlock[] = [];
  const shapes: ShapeBlock[] = [];

  blocks.push(
    buildTextBlock({
      text: slide.content.title,
      region: TITLE,
      fontFamily: design.heading_font,
      fontWeight: 'bold',
      color: design.palette.text,
      align: 'left',
      tier: FONT_SIZES.heading,
      lineHeight: LINE_HEIGHTS.heading,
    }),
  );

  const columnCount = headers.length;
  const columnWidth = TABLE_W / columnCount;
  const actualRows = Math.max(1, rows.length);

  // Compact, capped row band instead of dividing the whole data area evenly —
  // the latter inflated few-row tables into oversized cells with text pinned to
  // the top and a large empty cell below (row I). Center the whole table block
  // in the region so a sparse table reads balanced rather than top-anchored.
  const rowBand = Math.min(
    MAX_ROW_BAND,
    Math.max(MIN_ROW_BAND, (TABLE_H - HEADER_H) / actualRows),
  );
  const tableHeight = HEADER_H + actualRows * rowBand;
  const tableTop = TABLE_Y + Math.max(0, (TABLE_H - tableHeight) / 2);

  const columnAlignments = detectColumnAlignments(columnCount, rows);

  shapes.push({
    type: 'rect',
    x: TABLE_X,
    y: tableTop,
    w: TABLE_W,
    h: HEADER_H,
    fill: design.palette.accent,
    opacity: 0.08,
  });

  headers.forEach((header, j) => {
    const region: Region = {
      x: TABLE_X + j * columnWidth,
      y: tableTop,
      w: columnWidth,
      h: HEADER_H,
    };
    blocks.push(
      centerInBand(
        buildTextBlock({
          text: header,
          region,
          fontFamily: design.body_font,
          fontWeight: 'bold',
          color: design.palette.text,
          align: columnAlignments[j] ?? 'left',
          tier: FONT_SIZES.small,
          lineHeight: LINE_HEIGHTS.caption,
        }),
        tableTop,
        HEADER_H,
      ),
    );
  });

  rows.forEach((row, i) => {
    const bandY = tableTop + HEADER_H + i * rowBand;
    if (i % 2 === 1) {
      shapes.push({
        type: 'rect',
        x: TABLE_X,
        y: bandY,
        w: TABLE_W,
        h: rowBand,
        fill: design.palette.surface,
        opacity: 0.03,
      });
    }
    for (let j = 0; j < columnCount; j++) {
      const cell = row.cells[j] ?? '';
      const region: Region = {
        x: TABLE_X + j * columnWidth,
        y: bandY,
        w: columnWidth,
        h: rowBand,
      };
      blocks.push(
        centerInBand(
          buildTextBlock({
            text: cell,
            region,
            fontFamily: design.body_font,
            fontWeight: 'normal',
            color: design.palette.text,
            align: columnAlignments[j] ?? 'left',
            tier: FONT_SIZES.small,
            lineHeight: LINE_HEIGHTS.caption,
          }),
          bandY,
          rowBand,
        ),
      );
    }
  });

  if (slide.content.source_citation) {
    blocks.push(
      buildTextBlock({
        text: slide.content.source_citation,
        region: CITATION,
        fontFamily: design.body_font,
        fontWeight: 'normal',
        color: design.palette.text_secondary,
        align: 'left',
        tier: FONT_SIZES.small,
        lineHeight: LINE_HEIGHTS.caption,
      }),
    );
  }

  const background = defaultBackground(design);
  return compose(slide, blocks, [], shapes, background);
}

/**
 * Hug a header/cell block to its measured height and vertically center it
 * within its row band, so short cell text sits in the middle of the band
 * instead of pinned to the top with an empty gap below (row I). Both the HTML
 * and PPTX renderers top-anchor text inside a box, so the centering is done by
 * positioning the (hugged) block's y — not via a renderer vertical-align.
 */
function centerInBand(block: TextBlock, bandY: number, bandH: number): TextBlock {
  hugHeightToMeasured(block);
  block.y = bandY + Math.max(0, (bandH - block.h) / 2);
  return block;
}

function detectColumnAlignments(
  columnCount: number,
  rows: TableRow[],
): TextAlign[] {
  const result: TextAlign[] = [];
  for (let j = 0; j < columnCount; j++) {
    const values = rows
      .map((r) => (r.cells[j] ?? '').trim())
      .filter((v) => v.length > 0);
    if (values.length === 0) {
      result.push('left');
      continue;
    }
    const numericCount = values.filter((v) => NUMERIC_RE.test(v)).length;
    result.push(numericCount * 2 > values.length ? 'right' : 'left');
  }
  return result;
}
