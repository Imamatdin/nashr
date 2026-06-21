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
 *
 * Vertical layout (L2 fit migration): the title and conditional subtitle stay
 * frozen chrome at the top; the items band is SCALE-STACKED via fitCompositeStack.
 * Each item is a composite of three sub-blocks (statement, verdict, explanation);
 * a statement that wraps pushes its own verdict, its explanation, and the
 * following item DOWN, and if the whole stack is too tall it is scaled-to-fit
 * (fonts shrink, content rebuilt) so it can never run past the band — which
 * reserves room at the bottom for the reveal trigger. Horizontal `x`/`w` stay
 * caller-side; only the vertical axis is engine-driven.
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

const FALSE_VERDICT_COLOR = '#C0392B';
const TITLE: Region = { x: 5, y: 3, w: 90, h: 7 };
const SUBTITLE: Region = { x: 5, y: 10, w: 90, h: 3 };
const ITEMS_BAND_Y = 16;
const INNER_GAP = 1; // between an item's sub-blocks (statement → verdict → explanation)
const ITEM_GAP = 3.5; // between consecutive items
const TRIGGER_GAP = 2; // last explanation → reveal trigger
const TRIGGER_FLOOR_Y = 92; // bottom-margin clamp for the reveal trigger
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

  // The items band reserves room at the bottom for the reveal trigger, so a full,
  // scaled-to-fit stack never collides with it. Each item is a composite of a
  // statement + verdict + explanation; fitCompositeStack scales the items down
  // (and rebuilds them so the fonts shrink/truncate) when their natural height
  // overflows the band — content can never run past `bandRegion`'s bottom.
  const bandRegion: Region = {
    x: 8,
    y: ITEMS_BAND_Y,
    w: 84,
    h: TRIGGER_FLOOR_Y - TRIGGER_GAP - ITEMS_BAND_Y,
  };

  const composites: CompositeItem[] = items.map((item, i) => {
    const groupId = `tf${i}`;
    const verdictText = item.is_true
      ? `✓ ${labels.interactive.trueLabel}`
      : `✗ ${labels.interactive.falseLabel}`;
    const verdictColor = item.is_true ? design.palette.accent : FALSE_VERDICT_COLOR;
    return {
      gapAfter: ITEM_GAP,
      subs: [
        {
          innerGapAfter: INNER_GAP,
          build: (y, h) =>
            buildTextBlock({
              text: `${i + 1}. ${item.statement}`,
              region: { x: 8, y, w: 84, h },
              fontFamily: design.body_font,
              fontWeight: 'normal',
              color: design.palette.text,
              align: 'left',
              tier: FONT_SIZES.body,
              lineHeight: LINE_HEIGHTS.body,
              role: 'tf_statement',
              groupId,
              dataIndex: i,
            }),
        },
        {
          innerGapAfter: INNER_GAP,
          build: (y, h) =>
            buildTextBlock({
              text: verdictText,
              region: { x: 10, y, w: 40, h },
              fontFamily: design.body_font,
              fontWeight: 'bold',
              color: verdictColor,
              align: 'left',
              tier: FONT_SIZES.caption,
              lineHeight: LINE_HEIGHTS.caption,
              role: 'tf_verdict',
              groupId,
              dataIndex: i,
            }),
        },
        {
          build: (y, h) =>
            buildTextBlock({
              text: item.explanation,
              region: { x: 10, y, w: 80, h },
              fontFamily: design.body_font,
              fontWeight: 'normal',
              fontStyle: 'italic',
              color: design.palette.text_secondary,
              align: 'left',
              tier: FONT_SIZES.small,
              lineHeight: LINE_HEIGHTS.caption,
              role: 'tf_explanation',
              groupId,
              dataIndex: i,
            }),
        },
      ],
    };
  });

  const fitted = fitCompositeStack(bandRegion, composites);
  blocks.push(...fitted.blocks);

  // Reveal trigger sits below the last fitted item's measured bottom (clamped to
  // the bottom margin). The band reserved space above the floor for it, so it
  // never overlaps content. The HTML renderer keeps every `tf_verdict` and
  // `tf_explanation` block hidden until clicked.
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
