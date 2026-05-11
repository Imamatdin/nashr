/**
 * CONTENT_SPLIT layout.
 *
 * Body text alongside an image or visual. Text on the left half,
 * image filling the right half to the slide edge. Italic caption
 * sits at the bottom of the text side when present.
 *
 * Also acts as the temporary fallback for the 6 interactive slide
 * types until Task 21 replaces them with their proper renderers.
 */

import { FONT_SIZES, LINE_HEIGHTS, SLIDE_REGIONS } from '../constants.js';
import type {
  DeckSpec,
  ImageBlock,
  SlideLayout,
  SlideSpec,
  TextBlock,
} from '../types.js';
import {
  buildTextBlock,
  compose,
  composeBodyText,
  defaultBackground,
} from './shared.js';

export function layoutContentSplit(slide: SlideSpec, deck: DeckSpec): SlideLayout {
  const regions = SLIDE_REGIONS.content_split!;
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
      tier: FONT_SIZES.heading,
      lineHeight: LINE_HEIGHTS.heading,
    }),
  );

  const bodyText = composeBodyText(slide.content);
  if (bodyText) {
    blocks.push(
      buildTextBlock({
        text: bodyText,
        region: regions.body!,
        fontFamily: design.body_font,
        fontWeight: 'normal',
        color: design.palette.text,
        align: 'left',
        tier: FONT_SIZES.body,
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
        fontStyle: 'italic',
        color: design.palette.text_secondary,
        align: 'left',
        tier: FONT_SIZES.caption,
        lineHeight: LINE_HEIGHTS.caption,
      }),
    );
  }

  const images: ImageBlock[] = [];
  if (slide.content.background_url) {
    images.push({
      src: slide.content.background_url,
      x: regions.image!.x,
      y: regions.image!.y,
      w: regions.image!.w,
      h: regions.image!.h,
      objectFit: 'cover',
      opacity: 1,
      isBackground: false,
    });
  }

  const background = defaultBackground(design);
  return compose(slide, blocks, images, [], background);
}
