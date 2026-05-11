/**
 * INTERACTIVE_MATCHING layout.
 *
 * Two-column matching exercise. The left column holds names/terms; the
 * right column holds definitions/concepts. Both columns are always
 * visible — what is hidden is the *connection* between them. The
 * renderer reveals the correct pairing when the user activates the
 * reveal trigger; the Layout Pass only positions the visible content
 * and the dotted connector lines that imply pair groupings.
 *
 * Up to 6 pairs are laid out (12% slide height per pair). Pairs beyond
 * the cap are silently dropped — the editorial pass is expected to
 * split larger sets across multiple slides.
 */

import { FONT_SIZES, LINE_HEIGHTS, type Region } from '../constants.js';
import { getLabels } from '../labels.js';
import type {
  DeckSpec,
  ImageBlock,
  ScrimBlock,
  ShapeBlock,
  SlideBackground,
  SlideLayout,
  SlideSpec,
  TextBlock,
} from '../types.js';
import { buildScrim, buildTextBlock, compose, defaultBackground } from './shared.js';

const TITLE: Region = { x: 5, y: 3, w: 90, h: 7 };
const SUBTITLE: Region = { x: 5, y: 10, w: 90, h: 3 };
const PAIRS_BAND_Y = 16;
const PAIR_BLOCK_H = 12;
const MAX_PAIRS = 6;

export function layoutInteractiveMatching(slide: SlideSpec, deck: DeckSpec): SlideLayout {
  const { design } = deck;
  const labels = getLabels(deck.language);
  const blocks: TextBlock[] = [];
  const shapes: ShapeBlock[] = [];

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
      role: 'static',
    }),
  );

  blocks.push(
    buildTextBlock({
      text: labels.interactive.checkPairs,
      region: SUBTITLE,
      fontFamily: design.body_font,
      fontWeight: 'normal',
      fontStyle: 'italic',
      color: design.palette.accent,
      align: 'center',
      tier: FONT_SIZES.caption,
      lineHeight: LINE_HEIGHTS.caption,
      role: 'static',
    }),
  );

  const pairs = (slide.content.matching_pairs ?? []).slice(0, MAX_PAIRS);
  pairs.forEach((pair, pIdx) => {
    const groupId = `m${pIdx}`;
    const pairY = PAIRS_BAND_Y + pIdx * PAIR_BLOCK_H;

    blocks.push(
      buildTextBlock({
        text: pair.left,
        region: { x: 5, y: pairY, w: 28, h: 4 },
        fontFamily: design.body_font,
        fontWeight: 'bold',
        color: design.palette.text,
        align: 'left',
        tier: FONT_SIZES.body,
        lineHeight: LINE_HEIGHTS.body,
        role: 'match_left',
        groupId,
        dataIndex: pIdx,
      }),
    );

    shapes.push({
      type: 'line',
      x: 34,
      y: pairY + 2,
      w: 28,
      h: 0,
      stroke: design.palette.accent,
      strokeWidth: 1,
      opacity: 0.4,
      dashArray: '4 4',
    });

    blocks.push(
      buildTextBlock({
        text: pair.right,
        region: { x: 64, y: pairY, w: 31, h: 4 },
        fontFamily: design.body_font,
        fontWeight: 'normal',
        color: design.palette.text_secondary,
        align: 'left',
        tier: FONT_SIZES.body,
        lineHeight: LINE_HEIGHTS.body,
        role: 'match_right',
        groupId,
        dataIndex: pIdx,
      }),
    );
  });

  blocks.push(
    buildTextBlock({
      text: labels.interactive.showAnswer,
      region: { x: 35, y: 88, w: 30, h: 4 },
      fontFamily: design.body_font,
      fontWeight: 'normal',
      fontStyle: 'italic',
      color: design.palette.accent,
      align: 'center',
      tier: FONT_SIZES.caption,
      lineHeight: LINE_HEIGHTS.caption,
      role: 'reveal_trigger',
    }),
  );

  const background = buildBackground(slide, deck);
  return compose(slide, blocks, [], shapes, background);
}

function buildBackground(slide: SlideSpec, deck: DeckSpec): SlideBackground {
  const { design } = deck;
  if (slide.content.background_url) {
    const bg: SlideBackground = defaultBackground(design);
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
    const scrim: ScrimBlock = buildScrim(design, {
      direction: 'top-to-bottom',
      opacity: 0.55,
      x: 0,
      y: 0,
      w: 100,
      h: 100,
    });
    bg.image = image;
    bg.scrim = scrim;
    return bg;
  }
  return { color: design.palette.surface };
}
