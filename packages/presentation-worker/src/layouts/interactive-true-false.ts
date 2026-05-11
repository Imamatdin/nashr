/**
 * INTERACTIVE_TRUE_FALSE layout.
 *
 * Numbered statements followed by a verdict ("✓ True" / "✗ False") and
 * a one-line explanation. Verdict + explanation are revealable: the
 * HTML renderer keeps both hidden until the user picks a side; the
 * PPTX renderer shows them as a study aid.
 *
 * The verdict colour encodes the answer at the layout level: the deck
 * accent for `true`, a muted clay red for `false`. This is one of two
 * places in the entire codebase (the other is feedback_wrong on
 * interactive_quiz_mcq) where a colour outside the deck palette
 * appears intentionally.
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

const FALSE_VERDICT_COLOR = '#C0392B';
const TITLE: Region = { x: 5, y: 3, w: 90, h: 7 };
const SUBTITLE: Region = { x: 5, y: 10, w: 90, h: 3 };
const ITEMS_BAND_Y = 16;
const ITEM_BLOCK_H = 16;
const MAX_ITEMS = 5;

export function layoutInteractiveTrueFalse(slide: SlideSpec, deck: DeckSpec): SlideLayout {
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

  if (slide.content.subtitle) {
    blocks.push(
      buildTextBlock({
        text: slide.content.subtitle,
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
  }

  const items = (slide.content.true_false_items ?? []).slice(0, MAX_ITEMS);
  let lastItemY = ITEMS_BAND_Y;
  items.forEach((item, tIdx) => {
    const groupId = `tf${tIdx}`;
    const itemY = ITEMS_BAND_Y + tIdx * ITEM_BLOCK_H;

    blocks.push(
      buildTextBlock({
        text: `${tIdx + 1}. ${item.statement}`,
        region: { x: 8, y: itemY, w: 84, h: 5 },
        fontFamily: design.body_font,
        fontWeight: 'normal',
        color: design.palette.text,
        align: 'left',
        tier: FONT_SIZES.body,
        lineHeight: LINE_HEIGHTS.body,
        role: 'tf_statement',
        groupId,
        dataIndex: tIdx,
      }),
    );

    const verdictText = item.is_true
      ? `✓ ${labels.interactive.trueLabel}`
      : `✗ ${labels.interactive.falseLabel}`;
    const verdictColor = item.is_true ? design.palette.accent : FALSE_VERDICT_COLOR;
    blocks.push(
      buildTextBlock({
        text: verdictText,
        region: { x: 10, y: itemY + 6, w: 40, h: 4 },
        fontFamily: design.body_font,
        fontWeight: 'bold',
        color: verdictColor,
        align: 'left',
        tier: FONT_SIZES.caption,
        lineHeight: LINE_HEIGHTS.caption,
        role: 'tf_verdict',
        groupId,
        dataIndex: tIdx,
      }),
    );

    blocks.push(
      buildTextBlock({
        text: item.explanation,
        region: { x: 10, y: itemY + 10, w: 80, h: 4 },
        fontFamily: design.body_font,
        fontWeight: 'normal',
        fontStyle: 'italic',
        color: design.palette.text_secondary,
        align: 'left',
        tier: FONT_SIZES.small,
        lineHeight: LINE_HEIGHTS.caption,
        role: 'tf_explanation',
        groupId,
        dataIndex: tIdx,
      }),
    );
    lastItemY = itemY;
  });

  // Reveal trigger sits below the last item. The HTML renderer keeps
  // every `tf_verdict` and `tf_explanation` block hidden until clicked.
  const triggerY = items.length > 0 ? Math.min(lastItemY + 14, 92) : 92;
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
