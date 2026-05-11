/**
 * INTERACTIVE_CATEGORIZE layout.
 *
 * Category labels span the top of the slide as column headers; items
 * are stacked under their correct category below. In the v1 renderer
 * the items are shown pre-sorted (study aid) rather than as a real
 * drag-and-drop puzzle. The role + groupId tagging is what lets a
 * future HTML renderer shuffle the items at start-up and reveal the
 * correct grouping on demand.
 *
 * Supports 2-5 categories. With 2-4 the layout uses the canonical GRID
 * tracks (R19); 5 columns are computed inline since no preset exists
 * for that count.
 */

import { FONT_SIZES, GRID, LINE_HEIGHTS, type Region } from '../constants.js';
import type {
  DeckSpec,
  ScrimBlock,
  SlideBackground,
  SlideLayout,
  SlideSpec,
  TextBlock,
} from '../types.js';
import { buildScrim, buildTextBlock, compose, defaultBackground } from './shared.js';

const TITLE: Region = { x: 5, y: 3, w: 90, h: 7 };
const SUBTITLE: Region = { x: 5, y: 10, w: 90, h: 3 };
const LABEL_Y = 15;
const LABEL_H = 5;
const ITEMS_START_Y = 22;
const ITEM_H = 4;
const ITEM_STEP = 5;

interface ColumnSpec {
  x: number;
  w: number;
}

export function layoutInteractiveCategorize(slide: SlideSpec, deck: DeckSpec): SlideLayout {
  const { design } = deck;
  const blocks: TextBlock[] = [];

  blocks.push(
    buildTextBlock({
      text: slide.content.title,
      region: TITLE,
      fontFamily: design.heading_font,
      fontWeight: 'bold',
      color: design.palette.text,
      align: 'center',
      tier: FONT_SIZES.heading,
      lineHeight: LINE_HEIGHTS.heading,
      role: 'static',
    }),
  );

  if (slide.content.subtitle) {
    blocks.push(
      buildTextBlock({
        text: slide.content.subtitle,
        region: SUBTITLE,
        fontFamily: design.body_font,
        fontWeight: 'normal',
        fontStyle: 'italic',
        color: design.palette.accent,
        align: 'center',
        tier: FONT_SIZES.caption,
        lineHeight: LINE_HEIGHTS.caption,
        role: 'static',
      }),
    );
  }

  const labelsList = slide.content.category_labels ?? [];
  const items = slide.content.category_items ?? [];
  const columns = getCategoryColumns(labelsList.length);

  labelsList.forEach((label, catIdx) => {
    const col = columns[catIdx];
    if (!col) return;
    blocks.push(
      buildTextBlock({
        text: label,
        region: { x: col.x, y: LABEL_Y, w: col.w, h: LABEL_H },
        fontFamily: design.body_font,
        fontWeight: 'bold',
        color: design.palette.accent,
        align: 'center',
        tier: FONT_SIZES.caption,
        lineHeight: LINE_HEIGHTS.caption,
        role: 'category_label',
        dataIndex: catIdx,
      }),
    );

    const groupId = `cat${catIdx}`;
    const itemsInCat = items.filter((it) => it.category === label);
    itemsInCat.forEach((item, itemIdx) => {
      blocks.push(
        buildTextBlock({
          text: item.term,
          region: {
            x: col.x + 1,
            y: ITEMS_START_Y + itemIdx * ITEM_STEP,
            w: col.w - 2,
            h: ITEM_H,
          },
          fontFamily: design.body_font,
          fontWeight: 'normal',
          color: design.palette.text,
          align: 'left',
          tier: FONT_SIZES.small,
          lineHeight: LINE_HEIGHTS.body,
          role: 'category_item',
          groupId,
          dataIndex: itemIdx,
        }),
      );
    });
  });

  const background = buildBackground(deck);
  return compose(slide, blocks, [], [], background);
}

function getCategoryColumns(count: number): ColumnSpec[] {
  if (count <= 0) return [];
  if (count === 2 || count === 3 || count === 4) {
    const grid = GRID[count];
    const totalGutter = grid.gutter * (count - 1);
    const totalCols = grid.columns.reduce<number>((a, b) => a + b, 0);
    const totalWidth = totalCols + totalGutter;
    let x = (100 - totalWidth) / 2;
    return grid.columns.map((w) => {
      const col = { x, w };
      x += w + grid.gutter;
      return col;
    });
  }
  const gutter = 2;
  const w = (90 - gutter * (count - 1)) / count;
  return Array.from({ length: count }, (_, i) => ({
    x: 5 + i * (w + gutter),
    w,
  }));
}

function buildBackground(deck: DeckSpec): SlideBackground {
  const { design } = deck;
  const bg: SlideBackground = defaultBackground(design);
  const scrim: ScrimBlock = buildScrim(design, {
    direction: 'top-to-bottom',
    opacity: 0.6,
    x: 0,
    y: 0,
    w: 100,
    h: 100,
  });
  bg.scrim = scrim;
  return bg;
}
