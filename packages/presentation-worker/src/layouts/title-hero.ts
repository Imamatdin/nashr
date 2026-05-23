/**
 * TITLE_HERO layout.
 *
 * Opening slide. Sets the mood (R02): largest type in the deck, the
 * displayJumbo tier, optional italic subtitle, optional caption. If
 * the slide carries a background image it goes full-bleed with a
 * left-anchored gradient scrim so the text reads against any imagery
 * the Design Direction Pass picked.
 *
 * The subtitle and caption obey a never-stack-upward floor: their final y
 * is max(their designed region y, the measured bottom of the block above
 * them). A displayJumbo title that wraps far enough to reach past the
 * subtitle's region pushes the subtitle down instead of overlapping it;
 * an ordinary title leaves the subtitle resting at its designed position.
 * Crucially the subtitle is never pulled *up* into the title — that
 * upward pull (an old min-clamp ceiling) was the title/subtitle collision
 * class. With accurate glyph measurement the title also fits its own
 * region honestly, so the floor rarely has to move anything.
 */

import { FONT_SIZES, LINE_HEIGHTS, SLIDE_REGIONS } from '../constants.js';
import type { DeckSpec, SlideLayout, SlideSpec, TextBlock } from '../types.js';
import { buildTextBlock, compose, heroBackground, stackBelow } from './shared.js';

const SUBTITLE_GAP = 3;
const CAPTION_GAP = 2;

export function layoutTitleHero(slide: SlideSpec, deck: DeckSpec): SlideLayout {
  const regions = SLIDE_REGIONS.title_hero!;
  const { design } = deck;
  const blocks: TextBlock[] = [];

  const titleBlock = buildTextBlock({
    text: slide.content.title,
    region: regions.title!,
    fontFamily: design.heading_font,
    fontWeight: 'bold',
    color: design.palette.text,
    align: 'left',
    tier: FONT_SIZES.displayJumbo,
    lineHeight: LINE_HEIGHTS.heading,
  });
  blocks.push(titleBlock);

  // The element each subsequent block stacks under: title, then subtitle
  // once it exists.
  let anchor = titleBlock;

  if (slide.content.subtitle) {
    // Never-stack-upward floor: rest at the designed subtitle region y, and
    // move DOWN only if the title's measured bottom reaches past it. Using
    // max() (not the old min-clamp) means the subtitle can never be pulled
    // up into the title, which is the collision this fixes. If a pathological
    // title pushes the subtitle off-slide, the quality audit's overflow
    // check surfaces it — better than a silent overlap.
    const subtitleY = Math.max(regions.subtitle!.y, stackBelow(titleBlock, SUBTITLE_GAP));
    const subtitleBlock = buildTextBlock({
      text: slide.content.subtitle,
      region: { ...regions.subtitle!, y: subtitleY },
      fontFamily: design.body_font,
      fontWeight: 'normal',
      fontStyle: 'italic',
      color: design.palette.text_secondary,
      align: 'left',
      tier: FONT_SIZES.subheading,
      lineHeight: LINE_HEIGHTS.body,
    });
    blocks.push(subtitleBlock);
    anchor = subtitleBlock;
  }

  if (slide.content.caption) {
    // Keep the caption at its designed footer position, but drop it lower
    // if an unusually tall title/subtitle would otherwise overlap it.
    // Clamp to the slide so it can't run off the bottom edge.
    const maxCaptionY = 100 - regions.caption!.h;
    const captionY = Math.min(
      Math.max(regions.caption!.y, stackBelow(anchor, CAPTION_GAP)),
      maxCaptionY,
    );
    blocks.push(
      buildTextBlock({
        text: slide.content.caption,
        region: { ...regions.caption!, y: captionY },
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
