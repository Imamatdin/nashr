/**
 * SECTION_BREAK layout (R03).
 *
 * Signals a section transition. Background flips to the accent
 * colour; the title is rendered in the deck background colour for
 * maximum contrast. No body, no images, no data — the divider IS
 * the visual breath.
 */

import { FONT_SIZES, LINE_HEIGHTS, SLIDE_REGIONS } from '../constants.js';
import type {
  DeckSpec,
  SlideBackground,
  SlideLayout,
  SlideSpec,
  TextBlock,
} from '../types.js';
import { buildTextBlock, compose } from './shared.js';

export function layoutSectionBreak(slide: SlideSpec, deck: DeckSpec): SlideLayout {
  const regions = SLIDE_REGIONS.section_break!;
  const { design } = deck;
  const blocks: TextBlock[] = [];

  blocks.push(
    buildTextBlock({
      text: slide.content.title,
      region: regions.title!,
      fontFamily: design.heading_font,
      fontWeight: 'bold',
      color: design.palette.background,
      align: 'center',
      tier: FONT_SIZES.displayLarge,
      lineHeight: LINE_HEIGHTS.heading,
    }),
  );

  const background: SlideBackground = { color: design.palette.accent };
  return compose(slide, blocks, [], [], background);
}
