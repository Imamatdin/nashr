/**
 * GALLERY_PEOPLE layout.
 *
 * 3-5 portrait cutouts spread horizontally, each with name +
 * optional dates/role + optional description stacked below. The
 * portraits sit directly on the deck background (R24) — no frames,
 * no cards.
 */

import { FONT_SIZES, LINE_HEIGHTS, SLIDE_REGIONS, getPortraitPositions, type Region } from '../constants.js';
import type {
  DeckSpec,
  ImageBlock,
  SlideLayout,
  SlideSpec,
  TextBlock,
} from '../types.js';
import { buildTextBlock, compose, defaultBackground } from './shared.js';

export function layoutGalleryPeople(slide: SlideSpec, deck: DeckSpec): SlideLayout {
  const regions = SLIDE_REGIONS.gallery_people!;
  const { design } = deck;
  const blocks: TextBlock[] = [];
  const images: ImageBlock[] = [];

  blocks.push(
    buildTextBlock({
      text: slide.content.title,
      region: regions.title!,
      fontFamily: design.heading_font,
      fontWeight: 'bold',
      color: design.palette.text,
      align: 'center',
      tier: FONT_SIZES.heading,
      lineHeight: LINE_HEIGHTS.heading,
    }),
  );

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

    const baseY = position.y + position.h + 1;
    const captionWidth = position.w;
    const nameRegion: Region = { x: position.x, y: baseY, w: captionWidth, h: 4 };
    blocks.push(
      buildTextBlock({
        text: person.name,
        region: nameRegion,
        fontFamily: design.body_font,
        fontWeight: 'bold',
        color: design.palette.text,
        align: 'center',
        tier: FONT_SIZES.caption,
        lineHeight: LINE_HEIGHTS.caption,
      }),
    );

    if (person.years || person.role) {
      const datesRegion: Region = { x: position.x, y: baseY + 5, w: captionWidth, h: 3 };
      const datesText = [person.years, person.role].filter(Boolean).join(' · ');
      blocks.push(
        buildTextBlock({
          text: datesText,
          region: datesRegion,
          fontFamily: design.body_font,
          fontWeight: 'normal',
          color: design.palette.text_secondary,
          align: 'center',
          tier: FONT_SIZES.small,
          lineHeight: LINE_HEIGHTS.caption,
        }),
      );
    }

    if (person.description) {
      const descRegion: Region = { x: position.x, y: baseY + 9, w: captionWidth, h: 3 };
      blocks.push(
        buildTextBlock({
          text: person.description,
          region: descRegion,
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

  if (slide.content.caption) {
    blocks.push(
      buildTextBlock({
        text: slide.content.caption,
        region: regions.caption!,
        fontFamily: design.body_font,
        fontWeight: 'normal',
        fontStyle: 'italic',
        color: design.palette.text_secondary,
        align: 'center',
        tier: FONT_SIZES.caption,
        lineHeight: LINE_HEIGHTS.caption,
      }),
    );
  }

  const background = defaultBackground(design);
  return compose(slide, blocks, images, [], background);
}
