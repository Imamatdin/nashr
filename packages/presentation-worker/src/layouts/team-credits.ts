/**
 * TEAM_CREDITS layout.
 *
 * Portrait cutouts of contributors with name + role caption below
 * each. Often the closing slide ("Thank You" or equivalent); when
 * a hero image is attached the layout drops the deck background to
 * a faint backdrop so the people stay foregrounded.
 *
 * Portrait positions share the GALLERY_PEOPLE allocator so a deck
 * with both a gallery slide and a credits slide gets visually
 * consistent cutout spacing.
 */

import { FONT_SIZES, LINE_HEIGHTS, getPortraitPositions, type Region } from '../constants.js';
import type {
  DeckSpec,
  ImageBlock,
  SlideBackground,
  SlideLayout,
  SlideSpec,
  TextBlock,
} from '../types.js';
import { buildTextBlock, compose, defaultBackground } from './shared.js';

const TITLE: Region = { x: 5, y: 4, w: 90, h: 8 };
const NAME_OFFSET = 2;
const NAME_H = 4;
const ROLE_OFFSET = 3;
const ROLE_H = 3;

export function layoutTeamCredits(slide: SlideSpec, deck: DeckSpec): SlideLayout {
  const { design } = deck;
  const blocks: TextBlock[] = [];
  const images: ImageBlock[] = [];

  if (slide.content.title) {
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
      }),
    );
  }

  const people = (slide.content.people ?? []).slice(0, 5);
  const positions = getPortraitPositions(people.length);

  people.forEach((person, idx) => {
    const position = positions[idx];
    if (!position) return;

    if (person.portrait_url) {
      images.push({
        src: person.portrait_url,
        x: position.x,
        y: position.y,
        w: position.w,
        h: position.h,
        objectFit: 'cover',
        opacity: 1,
        isBackground: false,
      });
    }

    const nameY = position.y + position.h + NAME_OFFSET;
    blocks.push(
      buildTextBlock({
        text: person.name,
        region: { x: position.x, y: nameY, w: position.w, h: NAME_H },
        fontFamily: design.body_font,
        fontWeight: 'bold',
        color: design.palette.text,
        align: 'center',
        tier: FONT_SIZES.caption,
        lineHeight: LINE_HEIGHTS.caption,
      }),
    );

    if (person.role) {
      blocks.push(
        buildTextBlock({
          text: person.role,
          region: {
            x: position.x,
            y: nameY + ROLE_OFFSET,
            w: position.w,
            h: ROLE_H,
          },
          fontFamily: design.body_font,
          fontWeight: 'normal',
          color: design.palette.text_secondary,
          align: 'center',
          tier: FONT_SIZES.small,
          lineHeight: LINE_HEIGHTS.caption,
        }),
      );
    }
  });

  const background = buildBackground(slide, deck);
  return compose(slide, blocks, images, [], background);
}

function buildBackground(slide: SlideSpec, deck: DeckSpec): SlideBackground {
  const bg: SlideBackground = defaultBackground(deck.design);
  if (slide.content.background_url) {
    bg.image = {
      src: slide.content.background_url,
      x: 0,
      y: 0,
      w: 100,
      h: 100,
      objectFit: 'cover',
      opacity: 0.15,
      isBackground: true,
    };
  }
  return bg;
}
