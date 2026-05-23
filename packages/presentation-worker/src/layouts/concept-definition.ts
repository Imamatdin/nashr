/**
 * CONCEPT_DEFINITION layout.
 *
 * Introduce a concept with a one-sentence definition plus 3-5
 * supporting bullets. Text lives on the left ~50% of the slide;
 * topic imagery (when provided) goes full-bleed behind with a
 * left-anchored gradient scrim so the text stays readable.
 *
 * Stacking discipline (the fix for the clipping class):
 *   The three text zones — title, definition, bullets — are NOT pinned to
 *   fixed y/h regions. Each block is built against the real vertical space
 *   remaining on the slide, then its box is hugged to its measured height
 *   (see hugHeightToMeasured), and the next block starts below that measured
 *   bottom (stackBelow). A title that wraps to two lines therefore pushes the
 *   definition DOWN instead of overflowing into it, and the definition gets
 *   exactly the height its wrapped text needs instead of being clipped to a
 *   fixed 12% slot. Blocks only ever flow downward.
 *
 * The definition prefers `slide.content.subtitle`; if that's missing it falls
 * back to the first sentence of `body_text` so the editorial pass can supply
 * either field.
 */

import { FONT_SIZES, LINE_HEIGHTS } from '../constants.js';
import type {
  DeckSpec,
  ImageBlock,
  SlideBackground,
  SlideLayout,
  SlideSpec,
  TextBlock,
} from '../types.js';
import {
  availableHeightBelow,
  buildScrim,
  buildTextBlock,
  compose,
  defaultBackground,
  hugHeightToMeasured,
  stackBelow,
} from './shared.js';

const LEFT_X = 5;
const TITLE_W = 50;
const COLUMN_W = 48; // definition and bullets share the left text column
const TITLE_TOP = 5;
const TITLE_GAP = 2; // below the title before the definition
const DEFINITION_GAP = 3; // below the definition before the bullets
const BULLET_GAP = 1.5; // between consecutive bullets
const MAX_BULLETS = 5;

export function layoutConceptDefinition(slide: SlideSpec, deck: DeckSpec): SlideLayout {
  const { design } = deck;
  const blocks: TextBlock[] = [];

  const titleBlock = hugHeightToMeasured(
    buildTextBlock({
      text: slide.content.title,
      region: { x: LEFT_X, y: TITLE_TOP, w: TITLE_W, h: availableHeightBelow(TITLE_TOP) },
      fontFamily: design.heading_font,
      fontWeight: 'bold',
      color: design.palette.text,
      align: 'left',
      tier: FONT_SIZES.heading,
      lineHeight: LINE_HEIGHTS.heading,
    }),
  );
  blocks.push(titleBlock);

  let cursorY = stackBelow(titleBlock, TITLE_GAP);

  const definition = pickDefinition(slide.content.subtitle, slide.content.body_text);
  if (definition) {
    const definitionBlock = hugHeightToMeasured(
      buildTextBlock({
        text: definition,
        region: { x: LEFT_X, y: cursorY, w: COLUMN_W, h: availableHeightBelow(cursorY) },
        fontFamily: design.body_font,
        fontWeight: 'normal',
        fontStyle: 'italic',
        color: design.palette.text,
        align: 'left',
        tier: FONT_SIZES.subheading,
        lineHeight: LINE_HEIGHTS.body,
      }),
    );
    blocks.push(definitionBlock);
    cursorY = stackBelow(definitionBlock, DEFINITION_GAP);
  }

  const bullets = (slide.content.bullets ?? []).slice(0, MAX_BULLETS);
  bullets.forEach((bullet) => {
    const bulletBlock = hugHeightToMeasured(
      buildTextBlock({
        text: `• ${bullet}`,
        region: { x: LEFT_X, y: cursorY, w: COLUMN_W, h: availableHeightBelow(cursorY) },
        fontFamily: design.body_font,
        fontWeight: 'normal',
        color: design.palette.text,
        align: 'left',
        tier: FONT_SIZES.caption,
        lineHeight: LINE_HEIGHTS.body,
      }),
    );
    blocks.push(bulletBlock);
    cursorY = stackBelow(bulletBlock, BULLET_GAP);
  });

  const background = buildBackground(slide, deck);
  return compose(slide, blocks, [], [], background);
}

function pickDefinition(subtitle?: string | null, body?: string | null): string | null {
  if (subtitle && subtitle.trim()) return subtitle.trim();
  if (body && body.trim()) {
    const match = body.match(/^.*?[.!?](?=\s|$)/); // dont break on decimals like "73.8"
    return (match ? match[0] : body).trim();
  }
  return null;
}

function buildBackground(slide: SlideSpec, deck: DeckSpec): SlideBackground {
  const bg: SlideBackground = defaultBackground(deck.design);
  if (slide.content.background_url) {
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
    bg.image = image;
  }
  // R14: gradient scrim anchored to the left side where the text
  // lives, regardless of whether an image is supplied. Without an
  // image the scrim simply renders against the palette background
  // and is effectively a no-op for the renderer, but emitting it
  // unconditionally keeps the layout shape predictable.
  bg.scrim = buildScrim(deck.design, {
    direction: 'left-to-right',
    opacity: 0.7,
    x: 0,
    y: 0,
    w: 55,
    h: 100,
  });
  return bg;
}
