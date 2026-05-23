/**
 * SUMMARY_TAKEAWAY layout.
 *
 * Bulleted recap of the preceding section. The title hugs its measured height
 * and each bullet stacks below the previous bullet's real bottom (stackBelow)
 * rather than being dropped into a fixed equal-height slot — so a bullet that
 * wraps to two lines pushes the next one down instead of clipping. If no
 * bullets are present the layout falls back to a single body_text block that
 * fills the area below the title.
 */

import { FONT_SIZES, LINE_HEIGHTS, SLIDE_REGIONS, type Region } from '../constants.js';
import type { DeckSpec, SlideLayout, SlideSpec, TextBlock } from '../types.js';
import {
  availableHeightBelow,
  buildTextBlock,
  compose,
  defaultBackground,
  hugHeightToMeasured,
  stackBelow,
} from './shared.js';

const TITLE_GAP = 2; // below the title before the first bullet/body
const BULLET_GAP = 2; // between consecutive bullets

export function layoutSummaryTakeaway(slide: SlideSpec, deck: DeckSpec): SlideLayout {
  const regions = SLIDE_REGIONS.summary_takeaway!;
  const { design } = deck;
  const blocks: TextBlock[] = [];

  const titleBlock = hugHeightToMeasured(
    buildTextBlock({
      text: slide.content.title,
      region: { ...regions.title!, h: availableHeightBelow(regions.title!.y) },
      fontFamily: design.heading_font,
      fontWeight: 'bold',
      color: design.palette.text,
      align: 'left',
      tier: FONT_SIZES.heading,
      lineHeight: LINE_HEIGHTS.heading,
    }),
  );
  blocks.push(titleBlock);

  // Never-stack-upward floor: keep the body/bullets at their designed top, drop
  // lower only if a tall title reaches past it.
  let cursorY = Math.max(regions.body!.y, stackBelow(titleBlock, TITLE_GAP));

  const bullets = slide.content.bullets ?? [];
  if (bullets.length > 0) {
    bullets.forEach((bullet) => {
      const bulletBlock = hugHeightToMeasured(
        buildTextBlock({
          text: `• ${bullet}`,
          region: {
            x: regions.body!.x,
            y: cursorY,
            w: regions.body!.w,
            h: availableHeightBelow(cursorY),
          },
          fontFamily: design.body_font,
          fontWeight: 'normal',
          color: design.palette.text,
          align: 'left',
          tier: FONT_SIZES.body,
          lineHeight: LINE_HEIGHTS.body,
        }),
      );
      blocks.push(bulletBlock);
      cursorY = stackBelow(bulletBlock, BULLET_GAP);
    });
  } else if (slide.content.body_text) {
    const bodyRegion: Region = {
      x: regions.body!.x,
      y: cursorY,
      w: regions.body!.w,
      h: availableHeightBelow(cursorY),
    };
    blocks.push(
      buildTextBlock({
        text: slide.content.body_text,
        region: bodyRegion,
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
