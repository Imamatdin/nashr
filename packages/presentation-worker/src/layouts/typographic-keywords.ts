/**
 * TYPOGRAPHIC_KEYWORDS layout.
 *
 * 3-6 key terms with brief one-line explanations. The keyword
 * itself IS the visual element (R31): the term sits in the accent
 * colour at heading weight; the explanation sits to its right at
 * body size.
 *
 * Falls back to CONTENT_SPLIT when the slide carries no keywords,
 * which can happen if the editorial pass tagged a slide as
 * typographic_keywords but the LLM didn't actually emit any.
 */

import { FONT_SIZES, LINE_HEIGHTS, SLIDE_REGIONS, getKeywordPositions } from '../constants.js';
import type { DeckSpec, SlideLayout, SlideSpec, TextBlock } from '../types.js';
import { buildScrim, buildTextBlock, compose, defaultBackground } from './shared.js';
import { layoutContentSplit } from './content-split.js';

export function layoutTypographicKeywords(slide: SlideSpec, deck: DeckSpec): SlideLayout {
  const keywords = (slide.content.keywords ?? []).slice(0, 6);
  if (keywords.length === 0) {
    return layoutContentSplit(slide, deck);
  }

  const regions = SLIDE_REGIONS.typographic_keywords!;
  const { design } = deck;
  const blocks: TextBlock[] = [];

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

  const positions = getKeywordPositions(keywords.length);
  keywords.forEach((kw, idx) => {
    const pos = positions[idx];
    if (!pos) return;

    blocks.push(
      buildTextBlock({
        text: kw.term,
        region: pos.term,
        fontFamily: design.heading_font,
        fontWeight: 'bold',
        color: design.palette.accent,
        align: 'left',
        tier: FONT_SIZES.heading,
        lineHeight: LINE_HEIGHTS.heading,
      }),
    );

    blocks.push(
      buildTextBlock({
        text: kw.explanation,
        region: pos.explain,
        fontFamily: design.body_font,
        fontWeight: 'normal',
        color: design.palette.text_secondary,
        align: 'left',
        tier: FONT_SIZES.body,
        lineHeight: LINE_HEIGHTS.body,
      }),
    );
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
