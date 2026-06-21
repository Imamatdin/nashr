/**
 * INTERACTIVE_DEBATE layout.
 *
 * A scenario prompt followed by 2-3 argument positions. Each position
 * is paired with a framework label naming the theoretical lens it
 * represents (e.g., "Rationalist," "Empiricist"). The framework label
 * is the revealable part — the renderer hides it until the user has
 * committed to a position.
 *
 * Positions are wrapped in « » quotation marks because the layout is
 * specified for cyrillic-friendly Karakalpak/Uzbek decks; the marks
 * render identically across all four target languages and keep the
 * statement visually distinct from its framework annotation.
 *
 * Vertical layout (L2 fit migration): the title, subtitle, and debate prompt stay
 * frozen chrome at their fixed regions; the positions band is SCALE-STACKED via
 * fitCompositeStack. Each position is a composite of two sub-blocks (the statement,
 * then its framework label); a position that wraps pushes its own framework and the
 * following position DOWN, and if the whole stack is too tall it is scaled-to-fit
 * (fonts shrink, content rebuilt) so it can never run past the band — which reserves
 * room at the bottom for the reveal trigger. Horizontal `x`/`w` stay caller-side;
 * only the vertical axis is engine-driven.
 */

import { FONT_SIZES, LINE_HEIGHTS, type Region } from '../constants.js';
import { getLabels } from '../labels.js';
import type {
  DeckSpec,
  ImageBlock,
  ScrimBlock,
  SlideBackground,
  SlideLayout,
  SlideSpec,
  TextBlock,
} from '../types.js';
import {
  buildScrim,
  buildTextBlock,
  compose,
  defaultBackground,
  fitCompositeStack,
  type CompositeItem,
} from './shared.js';

const TITLE: Region = { x: 5, y: 3, w: 90, h: 7 };
const SUBTITLE: Region = { x: 5, y: 10, w: 90, h: 3 };
const PROMPT: Region = { x: 5, y: 16, w: 90, h: 12 };
const POSITION_X = 8;
const POSITION_W = 84;
const FRAMEWORK_X = 10;
const FRAMEWORK_W = 80;
const POSITIONS_BAND_Y = 34;
const INNER_GAP = 1.5; // position → its framework label, within one item
const ITEM_GAP = 3; // between consecutive positions
const TRIGGER_GAP = 2; // last framework → reveal trigger
const TRIGGER_FLOOR_Y = 94; // bottom-margin clamp for the reveal trigger
const MAX_POSITIONS = 3;

export function layoutInteractiveDebate(slide: SlideSpec, deck: DeckSpec): SlideLayout {
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

  if (slide.content.debate_prompt) {
    blocks.push(
      buildTextBlock({
        text: slide.content.debate_prompt,
        region: PROMPT,
        fontFamily: design.body_font,
        fontWeight: 'normal',
        color: design.palette.text,
        align: 'center',
        tier: FONT_SIZES.body,
        lineHeight: LINE_HEIGHTS.body,
        role: 'debate_prompt',
      }),
    );
  }

  const positions = (slide.content.debate_options ?? []).slice(0, MAX_POSITIONS);

  // The positions band reserves room at the bottom for the reveal trigger, so a
  // full, scaled-to-fit stack never collides with it. Each position is a composite
  // of a statement + its framework label; fitCompositeStack scales the items down
  // (and rebuilds them so the fonts shrink/truncate) when their natural height
  // overflows the band — content can never run past `bandRegion`'s bottom.
  const bandRegion: Region = {
    x: POSITION_X,
    y: POSITIONS_BAND_Y,
    w: POSITION_W,
    h: TRIGGER_FLOOR_Y - TRIGGER_GAP - POSITIONS_BAND_Y,
  };

  const composites: CompositeItem[] = positions.map((option, pIdx) => {
    const groupId = `d${pIdx}`;
    return {
      gapAfter: ITEM_GAP,
      subs: [
        {
          innerGapAfter: INNER_GAP,
          build: (y, h) =>
            buildTextBlock({
              text: `${pIdx + 1}. «${option.position}»`,
              region: { x: POSITION_X, y, w: POSITION_W, h },
              fontFamily: design.body_font,
              fontWeight: 'bold',
              color: design.palette.text,
              align: 'left',
              tier: FONT_SIZES.body,
              lineHeight: LINE_HEIGHTS.body,
              role: 'debate_position',
              groupId,
              dataIndex: pIdx,
            }),
        },
        {
          build: (y, h) =>
            buildTextBlock({
              text: option.framework_label,
              region: { x: FRAMEWORK_X, y, w: FRAMEWORK_W, h },
              fontFamily: design.body_font,
              fontWeight: 'normal',
              fontStyle: 'italic',
              color: design.palette.accent,
              align: 'left',
              tier: FONT_SIZES.small,
              lineHeight: LINE_HEIGHTS.caption,
              role: 'debate_framework',
              groupId,
              dataIndex: pIdx,
            }),
        },
      ],
    };
  });

  const fitted = fitCompositeStack(bandRegion, composites);
  blocks.push(...fitted.blocks);

  // Reveal trigger sits below the last fitted position's measured bottom (clamped
  // to the bottom margin). The band reserved space above the floor for it, so it
  // never overlaps content. The HTML renderer keeps every `debate_framework` block
  // hidden until this trigger is clicked.
  const triggerY =
    positions.length > 0
      ? Math.min(fitted.lastBottom + TRIGGER_GAP, TRIGGER_FLOOR_Y)
      : TRIGGER_FLOOR_Y;
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

  const background = buildBackground(slide, deck);
  return compose(slide, blocks, [], [], background);
}

function buildBackground(slide: SlideSpec, deck: DeckSpec): SlideBackground {
  const { design } = deck;
  if (slide.content.background_url) {
    const bg: SlideBackground = defaultBackground(design);
    const image: ImageBlock = {
      src: slide.content.background_url,
      x: 0,
      y: 0,
      w: 100,
      h: 100,
      objectFit: 'cover',
      opacity: 1,
      isBackground: true,
    };
    const scrim: ScrimBlock = buildScrim(design, {
      direction: 'top-to-bottom',
      opacity: 0.5,
      x: 0,
      y: 0,
      w: 100,
      h: 100,
    });
    bg.image = image;
    bg.scrim = scrim;
    return bg;
  }
  return defaultBackground(design);
}
