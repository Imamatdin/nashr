/**
 * SUMMARY_TAKEAWAY layout.
 *
 * Bulleted recap of the preceding section. Each bullet gets its own
 * vertical slot inside the body region; if no bullets are present
 * the layout falls back to a single body_text block.
 */

import { FONT_SIZES, LINE_HEIGHTS, SLIDE_REGIONS, type Region } from '../constants.js';
import type { DeckSpec, SlideLayout, SlideSpec, TextBlock } from '../types.js';
import { buildTextBlock, compose, defaultBackground } from './shared.js';

export function layoutSummaryTakeaway(slide: SlideSpec, deck: DeckSpec): SlideLayout {
  const regions = SLIDE_REGIONS.summary_takeaway!;
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

  const bullets = slide.content.bullets ?? [];
  if (bullets.length > 0) {
    const startY = regions.body!.y;
    const totalH = regions.body!.h;
    const slotH = totalH / Math.max(1, bullets.length);
    bullets.forEach((bullet, idx) => {
      const region: Region = {
        x: regions.body!.x,
        y: startY + idx * slotH,
        w: regions.body!.w,
        h: slotH * 0.9,
      };
      blocks.push(
        buildTextBlock({
          text: `• ${bullet}`,
          region,
          fontFamily: design.body_font,
          fontWeight: 'normal',
          color: design.palette.text,
          align: 'left',
          tier: FONT_SIZES.body,
          lineHeight: LINE_HEIGHTS.body,
        }),
      );
    });
  } else if (slide.content.body_text) {
    blocks.push(
      buildTextBlock({
        text: slide.content.body_text,
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

  const background = defaultBackground(design);
  return compose(slide, blocks, [], [], background);
}
