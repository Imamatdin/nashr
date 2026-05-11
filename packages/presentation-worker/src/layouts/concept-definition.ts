/**
 * CONCEPT_DEFINITION layout.
 *
 * Introduce a concept with a one-sentence definition plus 3-5
 * supporting bullets. Text lives on the left 53% of the slide;
 * topic imagery (when provided) goes full-bleed behind with a
 * left-anchored gradient scrim so the text stays readable.
 *
 * Region breakdown (from DESIGN-LANGUAGE.md):
 *   Title       x:5%  y:5%  w:50% h:8%   heading tier
 *   Definition  x:5%  y:16% w:48% h:12%  italic subheading
 *   Bullets     x:5%  y:32% w:48% h:50%  caption tier, 3-5 items
 *
 * The definition prefers `slide.content.subtitle`; if that's
 * missing it falls back to the first sentence of `body_text` so
 * the editorial pass can supply either field.
 */

import { FONT_SIZES, LINE_HEIGHTS, type Region } from '../constants.js';
import type {
  DeckSpec,
  ImageBlock,
  SlideBackground,
  SlideLayout,
  SlideSpec,
  TextBlock,
} from '../types.js';
import { buildScrim, buildTextBlock, compose, defaultBackground } from './shared.js';

const TITLE: Region = { x: 5, y: 5, w: 50, h: 8 };
const DEFINITION: Region = { x: 5, y: 16, w: 48, h: 12 };
const BULLETS_TOP = 32;
const BULLETS_HEIGHT = 50;
const BULLETS_X = 5;
const BULLETS_W = 48;
const BULLET_SPACING_FACTOR = 0.9;

export function layoutConceptDefinition(slide: SlideSpec, deck: DeckSpec): SlideLayout {
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

  const definition = pickDefinition(slide.content.subtitle, slide.content.body_text);
  if (definition) {
    blocks.push(
      buildTextBlock({
        text: definition,
        region: DEFINITION,
        fontFamily: design.body_font,
        fontWeight: 'normal',
        fontStyle: 'italic',
        color: design.palette.text,
        align: 'left',
        tier: FONT_SIZES.subheading,
        lineHeight: LINE_HEIGHTS.body,
      }),
    );
  }

  const bullets = (slide.content.bullets ?? []).slice(0, 5);
  if (bullets.length > 0) {
    const slotH = BULLETS_HEIGHT / bullets.length;
    bullets.forEach((bullet, idx) => {
      const region: Region = {
        x: BULLETS_X,
        y: BULLETS_TOP + idx * slotH,
        w: BULLETS_W,
        h: slotH * BULLET_SPACING_FACTOR,
      };
      blocks.push(
        buildTextBlock({
          text: `• ${bullet}`,
          region,
          fontFamily: design.body_font,
          fontWeight: 'normal',
          color: design.palette.text,
          align: 'left',
          tier: FONT_SIZES.caption,
          lineHeight: LINE_HEIGHTS.body,
        }),
      );
    });
  }

  const background = buildBackground(slide, deck);
  return compose(slide, blocks, [], [], background);
}

function pickDefinition(subtitle?: string | null, body?: string | null): string | null {
  if (subtitle && subtitle.trim()) return subtitle.trim();
  if (body && body.trim()) {
    const match = body.match(/^[^.!?]+[.!?]/);
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
