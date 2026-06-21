/**
 * INTERACTIVE_FILL_BLANK layout.
 *
 * Numbered statements with a literal "____" gap, followed by the
 * answer on the next row. The Layout Pass positions the answer block
 * directly under each statement; the HTML renderer hides it until the
 * user clicks "Show answer," while the PPTX renderer leaves it visible
 * as a study aid.
 *
 * Up to 5 items per slide. The clean, exam-paper background uses the
 * palette background colour with no scrim, decorative texture, or image.
 *
 * Vertical layout (L2 fit migration): the title and subtitle stay frozen chrome
 * at the top; the items band is SCALE-STACKED via fitCompositeStack. Each item is
 * a composite of two sub-blocks (statement, then its answer); a statement that
 * wraps pushes its own answer and the following item DOWN, and if the whole stack
 * is too tall it is scaled-to-fit (fonts shrink, content rebuilt) so it can never
 * run past the band — which reserves room at the bottom for the reveal trigger.
 * Horizontal `x`/`w` stay caller-side; only the vertical axis is engine-driven.
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
import {
  buildTextBlock,
  compose,
  defaultBackground,
  fitCompositeStack,
  type CompositeItem,
} from './shared.js';

const TITLE: Region = { x: 5, y: 3, w: 90, h: 7 };
const SUBTITLE: Region = { x: 5, y: 10, w: 90, h: 3 };
const STATEMENT_X = 8;
const STATEMENT_W = 84;
const ANSWER_X = 10;
const ANSWER_W = 80;
const ITEMS_BAND_Y = 16;
const INNER_GAP = 1; // statement → its answer, within one item
const ITEM_GAP = 4; // between consecutive items
const TRIGGER_GAP = 2; // last answer → reveal trigger
const TRIGGER_FLOOR_Y = 92; // bottom-margin clamp for the reveal trigger
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

  // The items band reserves room at the bottom for the reveal trigger, so a full,
  // scaled-to-fit stack never collides with it. Each item is a composite of a
  // statement + its answer; fitCompositeStack scales the items down (and rebuilds
  // them so the fonts shrink/truncate) when their natural height overflows the
  // band — content can never run past `bandRegion`'s bottom.
  const bandRegion: Region = {
    x: STATEMENT_X,
    y: ITEMS_BAND_Y,
    w: STATEMENT_W,
    h: TRIGGER_FLOOR_Y - TRIGGER_GAP - ITEMS_BAND_Y,
  };

  const composites: CompositeItem[] = items.map((item, fIdx) => {
    const groupId = `f${fIdx}`;
    return {
      gapAfter: ITEM_GAP,
      subs: [
        {
          innerGapAfter: INNER_GAP,
          build: (y, h) =>
            buildTextBlock({
              text: `${fIdx + 1}. ${item.statement}`,
              region: { x: STATEMENT_X, y, w: STATEMENT_W, h },
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
        },
        {
          build: (y, h) =>
            buildTextBlock({
              text: `→ ${item.answer}`,
              region: { x: ANSWER_X, y, w: ANSWER_W, h },
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
        },
      ],
    };
  });

  const fitted = fitCompositeStack(bandRegion, composites);
  blocks.push(...fitted.blocks);

  // Reveal trigger sits below the last fitted item's measured bottom (clamped to
  // the bottom margin). The band reserved space above the floor for it, so it
  // never overlaps content. The HTML renderer keeps every `blank_answer` hidden
  // until this trigger is clicked.
  const triggerY =
    items.length > 0 ? Math.min(fitted.lastBottom + TRIGGER_GAP, TRIGGER_FLOOR_Y) : TRIGGER_FLOOR_Y;
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
