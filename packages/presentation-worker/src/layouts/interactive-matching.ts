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
 * Up to 6 pairs are laid out. Pairs beyond the cap are silently dropped — the
 * editorial pass is expected to split larger sets across multiple slides.
 *
 * Vertical layout (L2 fit migration): title + subtitle stay frozen chrome; the
 * pairs band is ROW-SYNCED and SCALE-STACKED. Each row's height is the taller of
 * its left/right columns (measured), and ONE bandTop per row is reused for the
 * left block, the right block, AND the dashed connector (at the row mid) so the
 * three always read as one matching row. The two columns' x/w and the connector
 * geometry stay frozen — only the shared vertical position is engine-driven — and
 * the row stack scales-to-fit so long terms can never run past the band.
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
import {
  buildScrim,
  buildTextBlock,
  compose,
  defaultBackground,
  hugHeightToMeasured,
} from './shared.js';
import { fitMeasuredStack } from './fit.js';

const TITLE: Region = { x: 5, y: 3, w: 90, h: 7 };
const SUBTITLE: Region = { x: 5, y: 10, w: 90, h: 3 };
const LEFT_X = 5;
const LEFT_W = 28;
const RIGHT_X = 64;
const RIGHT_W = 31;
const CONNECTOR_X = 34;
const CONNECTOR_W = 28;
const PAIRS_BAND_Y = 16;
const ROW_GAP = 3; // between consecutive pair rows
const TRIGGER_GAP = 2; // last row → reveal trigger
const TRIGGER_FLOOR_Y = 88; // bottom-margin clamp for the reveal trigger
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

  // The pairs band reserves room at the bottom for the reveal trigger. Each row's
  // two columns keep their frozen x/w; only the shared vertical position is fit.
  const bandRegion: Region = {
    x: LEFT_X,
    y: PAIRS_BAND_Y,
    w: 100 - LEFT_X,
    h: TRIGGER_FLOOR_Y - TRIGGER_GAP - PAIRS_BAND_Y,
  };

  // Pass 1 — build each pair's two columns TALL; the row's natural height is the
  // taller column so a wrapped left/right pushes the whole row (and the rest) down.
  const rows = pairs.map((pair, pIdx) => {
    const groupId = `m${pIdx}`;
    const buildLeft = (y: number, h: number): TextBlock =>
      buildTextBlock({
        text: pair.left,
        region: { x: LEFT_X, y, w: LEFT_W, h },
        fontFamily: design.body_font,
        fontWeight: 'bold',
        color: design.palette.text,
        align: 'left',
        tier: FONT_SIZES.body,
        lineHeight: LINE_HEIGHTS.body,
        role: 'match_left',
        groupId,
        dataIndex: pIdx,
      });
    const buildRight = (y: number, h: number): TextBlock =>
      buildTextBlock({
        text: pair.right,
        region: { x: RIGHT_X, y, w: RIGHT_W, h },
        fontFamily: design.body_font,
        fontWeight: 'normal',
        color: design.palette.text_secondary,
        align: 'left',
        tier: FONT_SIZES.body,
        lineHeight: LINE_HEIGHTS.body,
        role: 'match_right',
        groupId,
        dataIndex: pIdx,
      });
    const left = buildLeft(PAIRS_BAND_Y, bandRegion.h);
    const right = buildRight(PAIRS_BAND_Y, bandRegion.h);
    return { buildLeft, buildRight, left, right, natural: Math.max(left.measuredHeightPct, right.measuredHeightPct) };
  });

  // Pass 2 — stack the rows with scale-to-fit; ONE bandTop per row is reused for
  // the left block, the right block, AND the connector (placed at the row mid), so
  // left_i.y === right_i.y and the connector reads as their shared row.
  const fit = fitMeasuredStack({
    region: bandRegion,
    items: rows.map((r) => ({ measure: () => r.natural, gapAfter: ROW_GAP })),
    overflow: 'scale',
    anchor: 'start',
  });
  const scale = fit.scale;

  let lastRowBottom = PAIRS_BAND_Y;
  rows.forEach((r, i) => {
    const bandTop = fit.tops[i]!;
    let left = r.left;
    let right = r.right;
    if (scale < 1) {
      // Rebuild BOTH sides against the SHARED scaled row height (the taller side's
      // natural * scale), not each side's own natural * scale — otherwise the short
      // side of an asymmetric (tall/short) row is over-shrunk even though the row
      // band has room for it.
      const rowBudget = Math.max(0, r.natural * scale);
      left = r.buildLeft(bandTop, rowBudget);
      right = r.buildRight(bandTop, rowBudget);
    }
    left.y = bandTop;
    right.y = bandTop;
    hugHeightToMeasured(left);
    hugHeightToMeasured(right);
    // INVARIANT (parity with fitCompositeStack): final emitted truncation ⟹ overflow,
    // regardless of which pass produced it, so a clipped term is never silent.
    if (left.truncated === true) left.overflow = true;
    if (right.truncated === true) right.overflow = true;
    const rowH = Math.max(left.measuredHeightPct, right.measuredHeightPct);
    blocks.push(left, right);
    shapes.push({
      type: 'line',
      x: CONNECTOR_X,
      y: bandTop + rowH / 2,
      w: CONNECTOR_W,
      h: 0,
      stroke: design.palette.accent,
      strokeWidth: 1,
      opacity: 0.4,
      dashArray: '4 4',
    });
    lastRowBottom = bandTop + rowH;
  });

  const triggerY =
    pairs.length > 0 ? Math.min(lastRowBottom + TRIGGER_GAP, TRIGGER_FLOOR_Y) : TRIGGER_FLOOR_Y;
  blocks.push(
    buildTextBlock({
      text: labels.interactive.showAnswer,
      region: { x: 35, y: triggerY, w: 30, h: 4 },
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
