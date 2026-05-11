/**
 * INTERACTIVE_FILL_BLANK layout.
 *
 * Numbered statements with a literal "____" gap, followed by the
 * answer on the next row. The Layout Pass positions the answer block
 * directly under each statement; the HTML renderer hides it until the
 * user clicks "Show answer," while the PPTX renderer leaves it visible
 * as a study aid.
 *
 * Up to 5 items per slide (15% slide height per item). The clean,
 * exam-paper background uses the palette background colour with no
 * scrim, decorative texture, or image.
 */

import { FONT_SIZES, LINE_HEIGHTS, type Region } from '../constants.js';
import { getLabels } from '../labels.js';
import type {
  DeckSpec,
  SlideBackground,
  SlideLayout,
  SlideSpec,
  TextBlock,
} from '../types.js';
import { buildTextBlock, compose, defaultBackground } from './shared.js';

const TITLE: Region = { x: 5, y: 3, w: 90, h: 7 };
const SUBTITLE: Region = { x: 5, y: 10, w: 90, h: 3 };
const ITEMS_BAND_Y = 16;
const ITEM_BLOCK_H = 15;
const MAX_ITEMS = 5;

export function layoutInteractiveFillBlank(slide: SlideSpec, deck: DeckSpec): SlideLayout {
  const { design } = deck;
  const labels = getLabels(deck.language);
  const blocks: TextBlock[] = [];

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
      role: 'static',
    }),
  );

  blocks.push(
    buildTextBlock({
      text: labels.interactive.fillBlank,
      region: SUBTITLE,
      fontFamily: design.body_font,
      fontWeight: 'normal',
      fontStyle: 'italic',
      color: design.palette.text_secondary,
      align: 'left',
      tier: FONT_SIZES.caption,
      lineHeight: LINE_HEIGHTS.caption,
      role: 'static',
    }),
  );

  const items = (slide.content.fill_blanks ?? []).slice(0, MAX_ITEMS);
  let lastItemY = ITEMS_BAND_Y;
  items.forEach((item, fIdx) => {
    const groupId = `f${fIdx}`;
    const itemY = ITEMS_BAND_Y + fIdx * ITEM_BLOCK_H;

    blocks.push(
      buildTextBlock({
        text: `${fIdx + 1}. ${item.statement}`,
        region: { x: 8, y: itemY, w: 84, h: 5 },
        fontFamily: design.body_font,
        fontWeight: 'normal',
        color: design.palette.text,
        align: 'left',
        tier: FONT_SIZES.body,
        lineHeight: LINE_HEIGHTS.body,
        role: 'blank_statement',
        groupId,
        dataIndex: fIdx,
      }),
    );

    blocks.push(
      buildTextBlock({
        text: `→ ${item.answer}`,
        region: { x: 10, y: itemY + 6, w: 80, h: 4 },
        fontFamily: design.body_font,
        fontWeight: 'normal',
        fontStyle: 'italic',
        color: design.palette.accent,
        align: 'left',
        tier: FONT_SIZES.caption,
        lineHeight: LINE_HEIGHTS.caption,
        role: 'blank_answer',
        groupId,
        dataIndex: fIdx,
      }),
    );
    lastItemY = itemY;
  });

  // Reveal trigger sits below the last item. The HTML renderer keeps
  // every `blank_answer` block hidden until this trigger is clicked.
  const triggerY = items.length > 0 ? Math.min(lastItemY + 12, 92) : 92;
  blocks.push(
    buildTextBlock({
      text: labels.interactive.showAnswer,
      region: { x: 35, y: triggerY, w: 30, h: 4 },
      fontFamily: design.body_font,
      fontWeight: 'normal',
      fontStyle: 'italic',
      color: design.palette.accent,
      align: 'center',
      tier: FONT_SIZES.caption,
      lineHeight: LINE_HEIGHTS.caption,
      role: 'reveal_trigger',
    }),
  );

  const background: SlideBackground = defaultBackground(design);
  return compose(slide, blocks, [], [], background);
}
