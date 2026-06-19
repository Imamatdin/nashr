/**
 * TYPOGRAPHIC_KEYWORDS layout.
 *
 * 3-6 key terms with brief one-line explanations. The keyword
 * itself IS the visual element (R31): the term sits in the accent
 * colour at heading weight; the explanation sits to its right at
 * body size.
 *
 * Each keyword is one ROW (term + explanation sharing a top). Rows hug the
 * title's measured bottom and stack by measured height via the shared fit engine
 * (fitMeasuredStack, anchor:'start') — no fixed band, no even-distribution. The
 * term and explanation each hug their own height (top-aligned), so a wrapped
 * explanation doesn't clip and the next row clears the taller cell.
 *
 * Falls back to CONTENT_SPLIT when the slide carries no keywords,
 * which can happen if the editorial pass tagged a slide as
 * typographic_keywords but the LLM didn't actually emit any.
 */

import { FONT_SIZES, LINE_HEIGHTS, SLIDE_REGIONS } from '../constants.js';
import type { DeckSpec, SlideLayout, SlideSpec, TextBlock } from '../types.js';
import {
  availableHeightBelow,
  buildScrim,
  buildTextBlock,
  compose,
  defaultBackground,
  hugHeightToMeasured,
  stackBelow,
} from './shared.js';
import { fitMeasuredStack } from './fit.js';
import { layoutContentSplit } from './content-split.js';

// Horizontal pairing (slide %): the term sits left, its explanation to the right.
// These survive from the deleted getKeywordPositions; only the vertical math (the
// old even-distribution band) is gone — rows now derive from measured content.
const TERM_X = 5;
const TERM_W = 35;
const EXPLAIN_X = 42;
const EXPLAIN_W = 50;
const TITLE_ROWS_GAP = 2; // below the title before the first keyword row
const ROW_GAP = 3; // between keyword rows (distinct, heading-weight items)
const MAX_KEYWORDS = 6;

export function layoutTypographicKeywords(slide: SlideSpec, deck: DeckSpec): SlideLayout {
  const keywords = (slide.content.keywords ?? []).slice(0, MAX_KEYWORDS);
  if (keywords.length === 0) {
    return layoutContentSplit(slide, deck);
  }

  const regions = SLIDE_REGIONS.typographic_keywords!;
  const { design } = deck;
  const blocks: TextBlock[] = [];

  // Hug the title so the keyword rows derive from its REAL measured bottom — this
  // removes the old fixed startY=18 dead gap. regions.title.h caps the build.
  const titleBlock = hugHeightToMeasured(
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
  blocks.push(titleBlock);

  const contentTop = stackBelow(titleBlock, TITLE_ROWS_GAP);
  const contentH = availableHeightBelow(contentTop);

  // Build each row's term + explanation tall against the band. rowHeight = the
  // taller of the two, used ONLY to space the next row; the cells themselves hug
  // their own height (top-aligned — do NOT emitBandCell). The accent colour + bold
  // on the term and text_secondary on the explanation are the emphasis contract:
  // keep them byte-identical.
  const rows = keywords.map((kw) => {
    const term = buildTextBlock({
      text: kw.term,
      region: { x: TERM_X, y: contentTop, w: TERM_W, h: contentH },
      fontFamily: design.heading_font,
      fontWeight: 'bold',
      color: design.palette.accent,
      align: 'left',
      tier: FONT_SIZES.heading,
      lineHeight: LINE_HEIGHTS.heading,
    });
    const explain = buildTextBlock({
      text: kw.explanation,
      region: { x: EXPLAIN_X, y: contentTop, w: EXPLAIN_W, h: contentH },
      fontFamily: design.body_font,
      fontWeight: 'normal',
      color: design.palette.text_secondary,
      align: 'left',
      tier: FONT_SIZES.body,
      lineHeight: LINE_HEIGHTS.body,
    });
    return {
      term,
      explain,
      rowHeight: Math.max(term.measuredHeightPct, explain.measuredHeightPct),
    };
  });

  const fit = fitMeasuredStack({
    region: { x: TERM_X, y: contentTop, w: 90, h: contentH },
    items: rows.map((r) => ({ measure: () => r.rowHeight, gapAfter: ROW_GAP })),
    overflow: 'truncate',
    anchor: 'start',
  });

  rows.forEach((r, i) => {
    r.term.y = fit.tops[i]!;
    r.explain.y = fit.tops[i]!;
    hugHeightToMeasured(r.term);
    hugHeightToMeasured(r.explain);
    blocks.push(r.term, r.explain);
  });

  const background = defaultBackground(design);
  background.scrim = buildScrim(design, {
    direction: 'top-to-bottom',
    opacity: 0.55,
    x: 0,
    y: 0,
    w: 100,
    h: 100,
  });

  return compose(slide, blocks, [], [], background);
}
