/**
 * CONTENT_SPLIT layout.
 *
 * Body text alongside an image or visual. Text on the left half,
 * image filling the right half to the slide edge. Italic caption
 * sits at the bottom of the text side when present.
 *
 * Also acts as the fallback for a header-less table_compact slide and a
 * keyword-less typographic_keywords slide (each delegates here when it has no
 * structured content to render). The six interactive slide types now have their
 * own renderers and no longer fall back here.
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
  figureImageBlock,
  hugHeightToMeasured,
  stackBelow,
} from './shared.js';
import { fitMeasuredStack } from './fit.js';

// Gap below the title before the body. Includes a one-line buffer because
// fontkit and PowerPoint/LibreOffice wrap headings to DIFFERENT line counts
// (different break points), and the renderer can produce one more line than
// measured. Reserving an extra heading line guarantees the body never
// overlaps a title that wrapped longer in the actual renderer.
const BODY_GAP = 2;
// Clearance (slide %) between the body's bottom and the caption strip so the two
// boxes never touch (was an inline magic `caption.y - 1`).
const CAPTION_CLEARANCE = 1;

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
    // Body region derives from the title's REAL bottom (no frozen floor): dropping
    // the old Math.max(regions.body.y, …) is what removes the dead gap that
    // stranded a short body at the designed body.y (18) even under a short title.
    // The column spans down to the caption strip (or the bottom content margin);
    // the frozen body height is demoted to a max bound and unused here.
    const bodyY = stackBelow(titleBlock, BODY_GAP);
    const bodyBottom = regions.caption
      ? regions.caption.y - CAPTION_CLEARANCE
      : bodyY + availableHeightBelow(bodyY);
    const bodyRegion: Region = {
      x: regions.body!.x,
      y: bodyY,
      w: regions.body!.w,
      h: Math.max(0, bodyBottom - bodyY),
    };
    // Build against the full column so a LONG body shrinks-to-fit there; route the
    // single block through the shared engine (anchor:'start' ⇒ tops[0] === bodyY)
    // for one geometry path; then hug so a SHORT body owns only its content with no
    // dead box trailing below. valign stays 'top' (do NOT emitBandCell — the body
    // reads from the top). MIN_BODY_H is gone: the height is now a measured/engine
    // output, and buildTextBlock's per-block shrink+truncate is the reliability floor.
    const bodyBlock = buildTextBlock({
      text: bodyText,
      region: bodyRegion,
      fontFamily: design.body_font,
      fontWeight: 'normal',
      color: design.palette.text,
      align: 'left',
      tier: FONT_SIZES.body,
      lineHeight: LINE_HEIGHTS.body,
    });
    const fit = fitMeasuredStack({
      region: bodyRegion,
      items: [{ measure: () => bodyBlock.measuredHeightPct }],
      overflow: 'truncate',
      anchor: 'start',
    });
    bodyBlock.y = fit.tops[0]!;
    hugHeightToMeasured(bodyBlock);
    blocks.push(bodyBlock);
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

  // The right panel carries, in priority order: a contained object-figure
  // (the explicit object slot, shown whole via objectFit:'contain'), else a
  // legacy full-panel cover image from background_url. Neither present → no
  // image block at all, so the slide renders text-only exactly as before.
  const images: ImageBlock[] = [];
  const figure = figureImageBlock(slide.content.figure_url, regions.figure!);
  if (figure) {
    images.push(figure);
  } else if (slide.content.background_url) {
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
