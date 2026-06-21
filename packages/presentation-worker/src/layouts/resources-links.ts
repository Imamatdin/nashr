/**
 * RESOURCES_LINKS layout.
 *
 * Up to 6 external resources, each a stacked trio of name (bold),
 * one-line description, and URL. The URL alone uses the accent
 * colour so the link draws the eye without the whole row turning
 * into a button.
 *
 * No imagery: the layout is deliberately a clean list.
 *
 * Vertical layout (L2 fit migration): the title stays frozen chrome at the top;
 * the resources band is SCALE-STACKED via fitCompositeStack. Each resource is a
 * composite of three sub-blocks (name, then description, then url) hugged
 * together; a description that wraps pushes its own url and the following
 * resource DOWN, and if the whole stack is too tall it is scaled-to-fit (fonts
 * shrink, content rebuilt) so it can never run past the band — which spans the
 * full height below the title (no trigger to reserve for). Horizontal `x`/`w`
 * stay caller-side; only the vertical axis is engine-driven.
 */

import { FONT_SIZES, LINE_HEIGHTS, type Region } from '../constants.js';
import type { DeckSpec, SlideLayout, SlideSpec, TextBlock } from '../types.js';
import {
  availableHeightBelow,
  buildTextBlock,
  compose,
  defaultBackground,
  fitCompositeStack,
  type CompositeItem,
} from './shared.js';

const TITLE: Region = { x: 5, y: 5, w: 90, h: 8 };
const FIRST_RESOURCE_Y = 18;
const RESOURCE_X = 8;
const RESOURCE_W = 84;
const INNER_GAP = 0.8; // name → description → url, within one resource
const ITEM_GAP = 3.5; // between consecutive resources
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

  // The resources band spans the full height below the title (there is no reveal
  // trigger to reserve room for). Each resource is a composite of name +
  // description + url; fitCompositeStack scales the items down (and rebuilds them
  // so the fonts shrink/truncate) when their natural height overflows the band —
  // content can never run past `bandRegion`'s bottom.
  const bandRegion: Region = {
    x: RESOURCE_X,
    y: FIRST_RESOURCE_Y,
    w: RESOURCE_W,
    h: availableHeightBelow(FIRST_RESOURCE_Y),
  };

  const composites: CompositeItem[] = resources.map((res) => ({
    gapAfter: ITEM_GAP,
    subs: [
      {
        innerGapAfter: INNER_GAP,
        build: (y, h) =>
          buildTextBlock({
            text: res.name,
            region: { x: RESOURCE_X, y, w: RESOURCE_W, h },
            fontFamily: design.body_font,
            fontWeight: 'bold',
            color: design.palette.text,
            align: 'left',
            tier: FONT_SIZES.caption,
            lineHeight: LINE_HEIGHTS.body,
          }),
      },
      {
        innerGapAfter: INNER_GAP,
        build: (y, h) =>
          buildTextBlock({
            text: res.description,
            region: { x: RESOURCE_X, y, w: RESOURCE_W, h },
            fontFamily: design.body_font,
            fontWeight: 'normal',
            color: design.palette.text_secondary,
            align: 'left',
            tier: FONT_SIZES.caption,
            lineHeight: LINE_HEIGHTS.body,
          }),
      },
      {
        build: (y, h) =>
          buildTextBlock({
            text: res.url,
            region: { x: RESOURCE_X, y, w: RESOURCE_W, h },
            fontFamily: design.body_font,
            fontWeight: 'normal',
            color: design.palette.accent,
            align: 'left',
            tier: FONT_SIZES.small,
            lineHeight: LINE_HEIGHTS.caption,
          }),
      },
    ],
  }));

  const fitted = fitCompositeStack(bandRegion, composites);
  blocks.push(...fitted.blocks);

  const background = defaultBackground(design);
  return compose(slide, blocks, [], [], background);
}
