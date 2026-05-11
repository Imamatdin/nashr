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
 */

import { FONT_SIZES, LINE_HEIGHTS, type Region } from '../constants.js';
import type {
  DeckSpec,
  ImageBlock,
  ScrimBlock,
  SlideBackground,
  SlideLayout,
  SlideSpec,
  TextBlock,
} from '../types.js';
import { buildScrim, buildTextBlock, compose, defaultBackground } from './shared.js';

const TITLE: Region = { x: 5, y: 3, w: 90, h: 7 };
const SUBTITLE: Region = { x: 5, y: 10, w: 90, h: 3 };
const PROMPT: Region = { x: 5, y: 16, w: 90, h: 12 };
const POSITIONS_BAND_Y = 34;
const POSITION_BLOCK_H = 20;
const MAX_POSITIONS = 3;

export function layoutInteractiveDebate(slide: SlideSpec, deck: DeckSpec): SlideLayout {
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
  positions.forEach((option, pIdx) => {
    const groupId = `d${pIdx}`;
    const posY = POSITIONS_BAND_Y + pIdx * POSITION_BLOCK_H;

    blocks.push(
      buildTextBlock({
        text: `${pIdx + 1}. «${option.position}»`,
        region: { x: 8, y: posY, w: 84, h: 7 },
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
    );

    blocks.push(
      buildTextBlock({
        text: option.framework_label,
        region: { x: 10, y: posY + 8, w: 80, h: 5 },
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
    );
  });

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
