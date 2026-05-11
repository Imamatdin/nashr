/**
 * QUOTE_PULLQUOTE layout.
 *
 * The quote IS the slide. Italic body font at heading tier, optional
 * right-aligned attribution, and a decorative accent circle providing
 * the visual breath called for by R26.
 */

import { FONT_SIZES, LINE_HEIGHTS, SLIDE_REGIONS } from '../constants.js';
import type { DeckSpec, ShapeBlock, SlideLayout, SlideSpec, TextBlock } from '../types.js';
import { buildTextBlock, compose, defaultBackground } from './shared.js';

export function layoutQuotePullquote(slide: SlideSpec, deck: DeckSpec): SlideLayout {
  const regions = SLIDE_REGIONS.quote_pullquote!;
  const { design } = deck;
  const blocks: TextBlock[] = [];

  const quoteText = slide.content.quote_text ?? slide.content.title;
  blocks.push(
    buildTextBlock({
      text: `"${quoteText}"`,
      region: regions.title!,
      fontFamily: design.body_font,
      fontWeight: 'normal',
      fontStyle: 'italic',
      color: design.palette.text,
      align: 'left',
      tier: FONT_SIZES.heading,
      lineHeight: LINE_HEIGHTS.heading,
    }),
  );

  if (slide.content.quote_attribution) {
    blocks.push(
      buildTextBlock({
        text: `— ${slide.content.quote_attribution}`,
        region: regions.subtitle!,
        fontFamily: design.body_font,
        fontWeight: 'normal',
        color: design.palette.text_secondary,
        align: 'right',
        tier: FONT_SIZES.caption,
        lineHeight: LINE_HEIGHTS.caption,
      }),
    );
  }

  const shapes: ShapeBlock[] = [
    {
      type: 'circle',
      x: 8,
      y: 18,
      w: 4,
      h: 4,
      fill: design.palette.accent,
      opacity: 0.1,
    },
  ];

  const background = defaultBackground(design);
  return compose(slide, blocks, [], shapes, background);
}
