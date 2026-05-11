/**
 * DATA_EMPHASIS layout.
 *
 * Highlights 1-4 key statistics. Each stat is decomposed into a
 * number block (largest), an optional unit block, a label block,
 * and an optional comparison line. The hero single-stat version
 * promotes the number to displayJumbo; multi-stat versions step
 * down to displayLarge so they fit side-by-side without crowding.
 */

import { FONT_SIZES, LINE_HEIGHTS, SLIDE_REGIONS, STAT_POSITIONS, type Region } from '../constants.js';
import type { DeckSpec, SlideLayout, SlideSpec, StatItem, TextBlock } from '../types.js';
import { buildTextBlock, compose, defaultBackground } from './shared.js';

export function layoutDataEmphasis(slide: SlideSpec, deck: DeckSpec): SlideLayout {
  const regions = SLIDE_REGIONS.data_emphasis!;
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

  const stats = (slide.content.stats ?? []).slice(0, 4) as StatItem[];
  const count = Math.max(1, stats.length) as 1 | 2 | 3 | 4;
  const positions = STAT_POSITIONS[count];
  const isHero = count === 1;
  const numberTier = isHero ? FONT_SIZES.displayJumbo : FONT_SIZES.displayLarge;
  const unitTier = isHero ? FONT_SIZES.heading : FONT_SIZES.subheading;
  const labelTier = isHero ? FONT_SIZES.subheading : FONT_SIZES.caption;

  stats.forEach((stat, idx) => {
    const position = positions[idx];
    if (!position) return;
    const numberRegion: Region = {
      x: position.x,
      y: position.y,
      w: position.w,
      h: position.h * 0.55,
    };
    const accentColor = stat.highlight ? design.palette.accent : design.palette.text;
    const numberText = stat.unit ? `${stat.value}${stat.unit}` : stat.value;

    blocks.push(
      buildTextBlock({
        text: numberText,
        region: numberRegion,
        fontFamily: design.heading_font,
        fontWeight: 'bold',
        color: accentColor,
        align: 'center',
        tier: numberTier,
        lineHeight: LINE_HEIGHTS.heading,
      }),
    );

    if (stat.unit && !isHero) {
      const unitRegion: Region = {
        x: position.x,
        y: position.y + position.h * 0.5,
        w: position.w,
        h: position.h * 0.2,
      };
      blocks.push(
        buildTextBlock({
          text: stat.unit,
          region: unitRegion,
          fontFamily: design.body_font,
          fontWeight: 'normal',
          color: design.palette.text_secondary,
          align: 'center',
          tier: unitTier,
          lineHeight: LINE_HEIGHTS.body,
        }),
      );
    }

    const labelRegion: Region = {
      x: position.x,
      y: position.y + position.h * 0.65,
      w: position.w,
      h: position.h * 0.3,
    };
    blocks.push(
      buildTextBlock({
        text: stat.label,
        region: labelRegion,
        fontFamily: design.body_font,
        fontWeight: 'normal',
        color: design.palette.text,
        align: 'center',
        tier: labelTier,
        lineHeight: LINE_HEIGHTS.body,
      }),
    );

    if (stat.comparison) {
      const comparisonRegion: Region = {
        x: position.x,
        y: position.y + position.h * 0.85,
        w: position.w,
        h: position.h * 0.15,
      };
      blocks.push(
        buildTextBlock({
          text: stat.comparison,
          region: comparisonRegion,
          fontFamily: design.body_font,
          fontWeight: 'normal',
          color: design.palette.text_secondary,
          align: 'center',
          tier: FONT_SIZES.caption,
          lineHeight: LINE_HEIGHTS.caption,
        }),
      );
    }
  });

  const background = defaultBackground(design);
  return compose(slide, blocks, [], [], background);
}
