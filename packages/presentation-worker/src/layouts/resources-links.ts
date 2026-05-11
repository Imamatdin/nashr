/**
 * RESOURCES_LINKS layout.
 *
 * Up to 6 external resources, each a stacked trio of name (bold),
 * one-line description, and URL. The URL alone uses the accent
 * colour so the link draws the eye without the whole row turning
 * into a button.
 *
 * No imagery: the layout is deliberately a clean list.
 */

import { FONT_SIZES, LINE_HEIGHTS, type Region } from '../constants.js';
import type { DeckSpec, SlideLayout, SlideSpec, TextBlock } from '../types.js';
import { buildTextBlock, compose, defaultBackground } from './shared.js';

const TITLE: Region = { x: 5, y: 5, w: 90, h: 8 };
const FIRST_RESOURCE_Y = 18;
const RESOURCE_SPACING = 12;
const RESOURCE_X = 8;
const RESOURCE_W = 84;
const NAME_H = 3;
const DESC_OFFSET = 3.5;
const DESC_H = 3;
const URL_OFFSET = 7;
const URL_H = 3;
const MAX_RESOURCES = 6;

export function layoutResourcesLinks(slide: SlideSpec, deck: DeckSpec): SlideLayout {
  const { design } = deck;
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
    }),
  );

  const resources = (slide.content.resources ?? []).slice(0, MAX_RESOURCES);
  resources.forEach((res, idx) => {
    const baseY = FIRST_RESOURCE_Y + idx * RESOURCE_SPACING;

    blocks.push(
      buildTextBlock({
        text: res.name,
        region: { x: RESOURCE_X, y: baseY, w: RESOURCE_W, h: NAME_H },
        fontFamily: design.body_font,
        fontWeight: 'bold',
        color: design.palette.text,
        align: 'left',
        tier: FONT_SIZES.caption,
        lineHeight: LINE_HEIGHTS.body,
      }),
    );

    blocks.push(
      buildTextBlock({
        text: res.description,
        region: { x: RESOURCE_X, y: baseY + DESC_OFFSET, w: RESOURCE_W, h: DESC_H },
        fontFamily: design.body_font,
        fontWeight: 'normal',
        color: design.palette.text_secondary,
        align: 'left',
        tier: FONT_SIZES.caption,
        lineHeight: LINE_HEIGHTS.body,
      }),
    );

    blocks.push(
      buildTextBlock({
        text: res.url,
        region: { x: RESOURCE_X, y: baseY + URL_OFFSET, w: RESOURCE_W, h: URL_H },
        fontFamily: design.body_font,
        fontWeight: 'normal',
        color: design.palette.accent,
        align: 'left',
        tier: FONT_SIZES.small,
        lineHeight: LINE_HEIGHTS.caption,
      }),
    );
  });

  const background = defaultBackground(design);
  return compose(slide, blocks, [], [], background);
}
