/**
 * DATA_EMPHASIS layout.
 *
 * Highlights 1-4 key statistics. Each stat is decomposed into a
 * number block (largest), an optional unit block, a label block,
 * and an optional comparison line. The hero single-stat version
 * promotes the number to displayJumbo; multi-stat versions step
 * down to displayLarge so they fit side-by-side without crowding.
 *
 * The four blocks of a stat are measured and stacked vertically
 * (number → unit → label → comparison) rather than dropped at fixed
 * fractions of the column height: a number that wraps to two lines
 * pushes the unit/label/comparison down instead of stranding them in a
 * pre-cut slot. The measured stack is centred within the column band,
 * clamped so it never starts above the column top (the never-stack-
 * upward floor; a stack taller than the band top-aligns and the audit
 * surfaces the overflow). The number block carries the value ONLY — the
 * unit has exactly one home, its own block — so a value+unit pair never
 * renders jammed together ("1.58PUE") or doubled.
 */

import { FONT_SIZES, LINE_HEIGHTS, SLIDE_REGIONS, STAT_POSITIONS, type Region } from '../constants.js';
import type { DeckSpec, SlideLayout, SlideSpec, StatItem, TextBlock } from '../types.js';
import {
  availableHeightBelow,
  buildTextBlock,
  compose,
  defaultBackground,
  hugHeightToMeasured,
} from './shared.js';

/** Vertical gap (slide %) between a stat's number/unit/label/comparison blocks. */
const STAT_BLOCK_GAP = 1;

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
    const accentColor = stat.highlight ? design.palette.accent : design.palette.text;
    // Measure every block against the space down to the bottom margin so the
    // font tier shrinks only on a genuine width constraint (a long value, a
    // narrow column), never because a pre-cut nominal slot was too short.
    const measureRegion = (y: number): Region => ({
      x: position.x,
      y,
      w: position.w,
      h: availableHeightBelow(y),
    });

    // number → unit → label → comparison, each hugged to its measured height.
    const statBlocks: TextBlock[] = [];
    statBlocks.push(
      hugHeightToMeasured(
        buildTextBlock({
          text: stat.value,
          region: measureRegion(position.y),
          fontFamily: design.heading_font,
          fontWeight: 'bold',
          color: accentColor,
          align: 'center',
          tier: numberTier,
          lineHeight: LINE_HEIGHTS.heading,
        }),
      ),
    );
    if (stat.unit) {
      statBlocks.push(
        hugHeightToMeasured(
          buildTextBlock({
            text: stat.unit,
            region: measureRegion(position.y),
            fontFamily: design.body_font,
            fontWeight: 'normal',
            color: design.palette.text_secondary,
            align: 'center',
            tier: unitTier,
            lineHeight: LINE_HEIGHTS.body,
          }),
        ),
      );
    }
    statBlocks.push(
      hugHeightToMeasured(
        buildTextBlock({
          text: stat.label,
          region: measureRegion(position.y),
          fontFamily: design.body_font,
          fontWeight: 'normal',
          color: design.palette.text,
          align: 'center',
          tier: labelTier,
          lineHeight: LINE_HEIGHTS.body,
        }),
      ),
    );
    if (stat.comparison) {
      statBlocks.push(
        hugHeightToMeasured(
          buildTextBlock({
            text: stat.comparison,
            region: measureRegion(position.y),
            fontFamily: design.body_font,
            fontWeight: 'normal',
            color: design.palette.text_secondary,
            align: 'center',
            tier: FONT_SIZES.caption,
            lineHeight: LINE_HEIGHTS.caption,
          }),
        ),
      );
    }

    // Centre the measured stack within the column band, but never let it begin
    // above the column top: a stack that overflows the band top-aligns instead
    // of climbing into the title above.
    const stackHeight =
      statBlocks.reduce((sum, b) => sum + b.h, 0) + STAT_BLOCK_GAP * (statBlocks.length - 1);
    let cursorY = position.y + Math.max(0, (position.h - stackHeight) / 2);
    for (const block of statBlocks) {
      block.y = cursorY;
      cursorY = block.y + block.h + STAT_BLOCK_GAP;
    }
    blocks.push(...statBlocks);
  });

  const background = defaultBackground(design);
  return compose(slide, blocks, [], [], background);
}
