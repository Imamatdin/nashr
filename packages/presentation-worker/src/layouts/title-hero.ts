/**
 * TITLE_HERO layout.
 *
 * Opening slide. Sets the mood (R02): largest type in the deck, the
 * displayJumbo tier, optional italic subtitle, optional caption. If
 * the slide carries a background image it goes full-bleed with a
 * left-anchored gradient scrim so the text reads against any imagery
 * the Design Direction Pass picked.
 */

import { FONT_SIZES, LINE_HEIGHTS, SLIDE_REGIONS } from '../constants.js';
import type { DeckSpec, SlideLayout, SlideSpec, TextBlock } from '../types.js';
import { buildTextBlock, compose, heroBackground } from './shared.js';

export function layoutTitleHero(slide: SlideSpec, deck: DeckSpec): SlideLayout {
  const regions = SLIDE_REGIONS.title_hero!;
  const { design } = deck;
  const blocks: TextBlock[] = [];

  blocks.push(
    buildTextBlock({
      text: slide.content.title,
      region: regions.title!,
      fontFamily: design.heading_font,
      fontWeight: 'bold',
      color: design.palette.text,
      align: 'left',
      tier: FONT_SIZES.displayJumbo,
      lineHeight: LINE_HEIGHTS.heading,
    }),
  );

  if (slide.content.subtitle) {
    blocks.push(
      buildTextBlock({
        text: slide.content.subtitle,
        region: regions.subtitle!,
        fontFamily: design.body_font,
        fontWeight: 'normal',
        fontStyle: 'italic',
        color: design.palette.text_secondary,
        align: 'left',
        tier: FONT_SIZES.subheading,
        lineHeight: LINE_HEIGHTS.body,
      }),
    );
  }

  if (slide.content.caption) {
    blocks.push(
      buildTextBlock({
        text: slide.content.caption,
        region: regions.caption!,
        fontFamily: design.body_font,
        fontWeight: 'normal',
        color: design.palette.text_secondary,
        align: 'left',
        tier: FONT_SIZES.caption,
        lineHeight: LINE_HEIGHTS.caption,
      }),
    );
  }

  const background = heroBackground(design, slide.content);
  return compose(slide, blocks, [], [], background);
}
