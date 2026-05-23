/**
 * CONTENT_SPLIT layout.
 *
 * Body text alongside an image or visual. Text on the left half,
 * image filling the right half to the slide edge. Italic caption
 * sits at the bottom of the text side when present.
 *
 * Also acts as the temporary fallback for the 6 interactive slide
 * types until Task 21 replaces them with their proper renderers.
 */

import { FONT_SIZES, LINE_HEIGHTS, SLIDE_REGIONS, type Region } from '../constants.js';
import type {
  DeckSpec,
  ImageBlock,
  SlideLayout,
  SlideSpec,
  TextBlock,
} from '../types.js';
import {
  availableHeightBelow,
  buildTextBlock,
  compose,
  composeBodyText,
  defaultBackground,
  hugHeightToMeasured,
  stackBelow,
} from './shared.js';

// Gap below the title before the body. Includes a one-line buffer because
// fontkit and PowerPoint/LibreOffice wrap headings to DIFFERENT line counts
// (different break points), and the renderer can produce one more line than
// measured. Reserving an extra heading line guarantees the body never
// overlaps a title that wrapped longer in the actual renderer.
const BODY_GAP = 2;
const MIN_BODY_H = 10; // never give the body less than this even if the title is tall

export function layoutContentSplit(slide: SlideSpec, deck: DeckSpec): SlideLayout {
  const regions = SLIDE_REGIONS.content_split!;
  const { design } = deck;
  const blocks: TextBlock[] = [];

  // Title hugs its measured height so a two-line title doesn't clip in a fixed
  // 8% box; the body then stacks below the title's real bottom.
  const titleBlock = hugHeightToMeasured(
    buildTextBlock({
      text: slide.content.title,
      // Cap the title's fit-height at ~2 heading lines so a long title SHRINKS
      // to two lines instead of sprawling to three. buildTextBlock steps the
      // font down until the text fits this height; 12% ~= two lines at the
      // heading tier (incl. render height-safety).
      region: { ...regions.title!, h: Math.min(12, availableHeightBelow(regions.title!.y)) },
      fontFamily: design.heading_font,
      fontWeight: 'bold',
      color: design.palette.text,
      align: 'left',
      tier: FONT_SIZES.heading,
      lineHeight: LINE_HEIGHTS.heading,
    }),
  );
  blocks.push(titleBlock);

  const bodyText = composeBodyText(slide.content);
  if (bodyText) {
    // Never-stack-upward floor: rest at the designed body y, drop lower only if
    // the title's measured bottom reaches past it. The body fills the column
    // down to the caption strip (or the bottom margin), so it owns its area and
    // shrinks-to-fit there rather than clipping under a fixed slot.
    const bodyY = Math.max(regions.body!.y, stackBelow(titleBlock, BODY_GAP));
    // Bottom edge of the body: just above the caption strip, or the slide's
    // bottom content margin (availableHeightBelow(y) + y) when there's no caption.
    const bodyBottom = regions.caption ? regions.caption.y - 1 : bodyY + availableHeightBelow(bodyY);
    const bodyRegion: Region = {
      x: regions.body!.x,
      y: bodyY,
      w: regions.body!.w,
      h: Math.max(MIN_BODY_H, bodyBottom - bodyY),
    };
    blocks.push(
      buildTextBlock({
        text: bodyText,
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

  if (slide.content.caption) {
    blocks.push(
      buildTextBlock({
        text: slide.content.caption,
        region: regions.caption!,
        fontFamily: design.body_font,
        fontWeight: 'normal',
        fontStyle: 'italic',
        color: design.palette.text_secondary,
        align: 'left',
        tier: FONT_SIZES.caption,
        lineHeight: LINE_HEIGHTS.caption,
      }),
    );
  }

  const images: ImageBlock[] = [];
  if (slide.content.background_url) {
    images.push({
      src: slide.content.background_url,
      x: regions.image!.x,
      y: regions.image!.y,
      w: regions.image!.w,
      h: regions.image!.h,
      objectFit: 'cover',
      opacity: 1,
      isBackground: false,
    });
  }

  const background = defaultBackground(design);
  return compose(slide, blocks, images, [], background);
}
