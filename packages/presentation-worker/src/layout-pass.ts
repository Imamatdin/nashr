/**
 * Layout Pass.
 *
 * Transforms a DeckSpec (positioning-agnostic editorial output) into a
 * DeckLayout (every text block, image, and shape positioned in slide
 * percentages, ready for the renderer).
 *
 * Workflow per slide:
 *   1. Look up the slide-type region map from constants.SLIDE_REGIONS.
 *   2. Apply the design direction (palette, fonts) to every block.
 *   3. Lay out text into each region, picking the appropriate font tier.
 *   4. Run measureText to detect overflow; reduce font size in 2px steps
 *      down to FONT_SIZES.minimum. Flag the block if it still overflows.
 *   5. Tally the slide's word count for R17 audit comparison.
 *   6. Compose the background (solid / image / scrim).
 *
 * The eight core slide types (TITLE_HERO, CONTENT_SPLIT, DATA_EMPHASIS,
 * SECTION_BREAK, SUMMARY_TAKEAWAY, QUOTE_PULLQUOTE, GALLERY_PEOPLE,
 * COMPARISON) have full implementations. The remaining 14 types fall
 * back to a generic title+body layout — they will be completed in
 * Task 20.
 */

import {
  FONT_SIZES,
  LINE_HEIGHTS,
  SLIDE_HEIGHT,
  SLIDE_REGIONS,
  SLIDE_WIDTH,
  STAT_POSITIONS,
  WORD_LIMITS,
  getPortraitPositions,
  type Region,
} from './constants.js';
import { measureText } from './text-measure.js';
import type {
  DeckLayout,
  DeckSpec,
  DesignDirectionSpec,
  FontStyle,
  FontWeight,
  ImageBlock,
  ScrimBlock,
  ShapeBlock,
  SlideBackground,
  SlideContent,
  SlideLayout,
  SlideSpec,
  StatItem,
  TextAlign,
  TextBlock,
} from './types.js';

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

interface FontTier {
  readonly min: number;
  readonly max: number;
}

function pctToPx(pct: number, dimension: number): number {
  return (pct / 100) * dimension;
}

function regionWidthPx(region: Region): number {
  return pctToPx(region.w, SLIDE_WIDTH);
}

function regionHeightPx(region: Region): number {
  return pctToPx(region.h, SLIDE_HEIGHT);
}

function countWords(text: string | null | undefined): number {
  if (!text) return 0;
  return text.trim().split(/\s+/).filter(Boolean).length;
}

function countSlideWords(content: SlideContent): number {
  let total = 0;
  total += countWords(content.title);
  total += countWords(content.subtitle);
  total += countWords(content.body_text);
  total += countWords(content.caption);
  total += countWords(content.quote_text);
  total += countWords(content.quote_attribution);
  total += countWords(content.debate_prompt);
  for (const bullet of content.bullets ?? []) total += countWords(bullet);
  for (const stat of content.stats ?? []) {
    total += countWords(stat.value) + countWords(stat.unit) + countWords(stat.label);
    if (stat.comparison) total += countWords(stat.comparison);
  }
  for (const person of content.people ?? []) {
    total +=
      countWords(person.name) +
      countWords(person.years) +
      countWords(person.role) +
      countWords(person.description);
  }
  for (const kw of content.keywords ?? []) {
    total += countWords(kw.term) + countWords(kw.explanation);
  }
  if (content.left_column) {
    total += countWords(content.left_column.heading);
    for (const p of content.left_column.points) total += countWords(p);
  }
  if (content.right_column) {
    total += countWords(content.right_column.heading);
    for (const p of content.right_column.points) total += countWords(p);
  }
  for (const node of content.timeline_nodes ?? []) {
    total += countWords(node.date) + countWords(node.label);
  }
  for (const step of content.steps ?? []) {
    total += countWords(step.label) + countWords(step.description);
  }
  for (const q of content.quiz_questions ?? []) {
    total += countWords(q.question);
    for (const opt of q.options) total += countWords(opt.text);
  }
  for (const pair of content.matching_pairs ?? []) {
    total += countWords(pair.left) + countWords(pair.right);
  }
  for (const lbl of content.category_labels ?? []) total += countWords(lbl);
  for (const item of content.category_items ?? []) total += countWords(item.term);
  for (const fb of content.fill_blanks ?? []) {
    total += countWords(fb.statement) + countWords(fb.answer);
  }
  for (const tf of content.true_false_items ?? []) {
    total += countWords(tf.statement) + countWords(tf.explanation);
  }
  for (const opt of content.debate_options ?? []) {
    total += countWords(opt.position) + countWords(opt.framework_label);
  }
  for (const res of content.resources ?? []) {
    total += countWords(res.name) + countWords(res.description);
  }
  return total;
}

interface BuildTextBlockOptions {
  text: string;
  region: Region;
  fontFamily: string;
  fontWeight: FontWeight;
  fontStyle?: FontStyle;
  color: string;
  align: TextAlign;
  tier: FontTier;
  lineHeight: number;
}

/**
 * Build a TextBlock and run the overflow-reduction loop.
 *
 * Starts at the tier maximum, drops fontSize by 2px each iteration
 * until the text fits or the floor is hit. If the final size still
 * overflows, the block is returned with overflow=true and the floor
 * font size — the renderer is expected to truncate visually and the
 * audit will surface the violation.
 */
function buildTextBlock(opts: BuildTextBlockOptions): TextBlock {
  const maxWidthPx = regionWidthPx(opts.region);
  const maxHeightPx = regionHeightPx(opts.region);
  const floor = Math.max(FONT_SIZES.minimum, Math.min(opts.tier.min, opts.tier.max));

  let fontSize = opts.tier.max;
  let overflow = true;

  while (fontSize >= floor) {
    const measurement = measureText({
      text: opts.text,
      fontSize,
      fontFamily: opts.fontFamily,
      fontWeight: opts.fontWeight,
      maxWidth: maxWidthPx,
      maxHeight: maxHeightPx,
      lineHeight: opts.lineHeight,
    });
    if (measurement.fitsInBox) {
      overflow = false;
      break;
    }
    if (fontSize === floor) break;
    fontSize = Math.max(floor, fontSize - 2);
  }

  return {
    text: opts.text,
    x: opts.region.x,
    y: opts.region.y,
    w: opts.region.w,
    h: opts.region.h,
    fontSize,
    fontFamily: opts.fontFamily,
    fontWeight: opts.fontWeight,
    fontStyle: opts.fontStyle ?? 'normal',
    color: opts.color,
    align: opts.align,
    lineHeight: opts.lineHeight,
    overflow,
  };
}

function defaultBackground(design: DesignDirectionSpec): SlideBackground {
  // The Design Direction Pass already chose a `background` colour that
  // matches the deck's polarity (dark or light). A per-slide override
  // signals "invert me" — section breaks use the accent and so handle
  // their own background; other slide types currently render the deck
  // background regardless of override, which the renderer can still
  // tune in CSS by inspecting `slide.background_override`.
  return { color: design.palette.background };
}

/**
 * For TITLE_HERO and similar: full-bleed image (if present) with a
 * gradient scrim that anchors the text to the left/bottom of the slide.
 */
function heroBackground(
  design: DesignDirectionSpec,
  content: SlideContent,
): SlideBackground {
  const bg: SlideBackground = defaultBackground(design);
  if (content.background_url) {
    const image: ImageBlock = {
      src: content.background_url,
      x: 0,
      y: 0,
      w: 100,
      h: 100,
      objectFit: 'cover',
      opacity: 1,
      isBackground: true,
    };
    const scrim: ScrimBlock = {
      direction: 'left-to-right',
      color: design.palette.background,
      opacity: 0.6,
      x: 0,
      y: 0,
      w: 70,
      h: 100,
    };
    bg.image = image;
    bg.scrim = scrim;
  }
  return bg;
}

function compose(
  slide: SlideSpec,
  textBlocks: TextBlock[],
  imageBlocks: ImageBlock[],
  shapes: ShapeBlock[],
  background: SlideBackground,
): SlideLayout {
  const hasOverflow = textBlocks.some((b) => b.overflow);
  const wordCount = countSlideWords(slide.content);
  return {
    slideIndex: slide.slide_index,
    slideType: slide.slide_type,
    width: SLIDE_WIDTH,
    height: SLIDE_HEIGHT,
    background,
    textBlocks,
    imageBlocks,
    shapes,
    hasOverflow,
    wordCount,
    wordLimit: WORD_LIMITS[slide.slide_type],
  };
}

// ---------------------------------------------------------------------------
// Layout pass
// ---------------------------------------------------------------------------

export class LayoutPass {
  /** Generate layouts for every slide in the deck. */
  layout(deck: DeckSpec): DeckLayout {
    const slides = deck.slides.map((slide) => this.layoutSlide(slide, deck));
    return {
      slides,
      totalOverflows: slides.filter((s) => s.hasOverflow).length,
      totalWordLimitViolations: slides.filter((s) => s.wordCount > s.wordLimit).length,
    };
  }

  /** Dispatch on slide_type. */
  layoutSlide(slide: SlideSpec, deck: DeckSpec): SlideLayout {
    switch (slide.slide_type) {
      case 'title_hero':
        return this.layoutTitleHero(slide, deck);
      case 'content_split':
        return this.layoutContentSplit(slide, deck);
      case 'data_emphasis':
        return this.layoutDataEmphasis(slide, deck);
      case 'section_break':
        return this.layoutSectionBreak(slide, deck);
      case 'summary_takeaway':
        return this.layoutSummaryTakeaway(slide, deck);
      case 'quote_pullquote':
        return this.layoutQuotePullquote(slide, deck);
      case 'gallery_people':
        return this.layoutGalleryPeople(slide, deck);
      case 'comparison':
        return this.layoutComparison(slide, deck);
      // TODO(task-20): full implementations for the remaining types.
      // For now they share the generic content-split fallback so a
      // deck with mixed types still renders coherently.
      case 'concept_definition':
      case 'typographic_keywords':
      case 'timeline':
      case 'flow_process':
      case 'chart_data':
      case 'table_compact':
      case 'resources_links':
      case 'team_credits':
      case 'interactive_quiz_mcq':
      case 'interactive_matching':
      case 'interactive_categorize':
      case 'interactive_fill_blank':
      case 'interactive_true_false':
      case 'interactive_debate':
        return this.layoutGenericFallback(slide, deck);
    }
  }

  // -------------------------------------------------------------------------
  // Core slide types (8 fully implemented)
  // -------------------------------------------------------------------------

  private layoutTitleHero(slide: SlideSpec, deck: DeckSpec): SlideLayout {
    const regions = SLIDE_REGIONS.title_hero!;
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
        tier: FONT_SIZES.displayJumbo,
        lineHeight: LINE_HEIGHTS.heading,
      }),
    );

    if (slide.content.subtitle) {
      blocks.push(
        buildTextBlock({
          text: slide.content.subtitle,
          region: regions.subtitle!,
          fontFamily: design.body_font,
          fontWeight: 'normal',
          fontStyle: 'italic',
          color: design.palette.text_secondary,
          align: 'left',
          tier: FONT_SIZES.subheading,
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
          color: design.palette.text_secondary,
          align: 'left',
          tier: FONT_SIZES.caption,
          lineHeight: LINE_HEIGHTS.caption,
        }),
      );
    }

    const background = heroBackground(design, slide.content);
    return compose(slide, blocks, [], [], background);
  }

  private layoutContentSplit(slide: SlideSpec, deck: DeckSpec): SlideLayout {
    const regions = SLIDE_REGIONS.content_split!;
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

    const bodyText = this.composeBodyText(slide.content);
    if (bodyText) {
      blocks.push(
        buildTextBlock({
          text: bodyText,
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

  private layoutDataEmphasis(slide: SlideSpec, deck: DeckSpec): SlideLayout {
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
      const accentColor = stat.highlight
        ? design.palette.accent
        : design.palette.text;
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
        // Unit gets a dedicated tier on multi-stat slides; on the hero
        // slide we already concatenated unit into the number block.
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

  private layoutSectionBreak(slide: SlideSpec, deck: DeckSpec): SlideLayout {
    const regions = SLIDE_REGIONS.section_break!;
    const { design } = deck;
    const blocks: TextBlock[] = [];

    // R03: section divider uses the accent colour for its background.
    // Title text uses palette.background as the high-contrast inverse.
    blocks.push(
      buildTextBlock({
        text: slide.content.title,
        region: regions.title!,
        fontFamily: design.heading_font,
        fontWeight: 'bold',
        color: design.palette.background,
        align: 'center',
        tier: FONT_SIZES.displayLarge,
        lineHeight: LINE_HEIGHTS.heading,
      }),
    );

    const background: SlideBackground = { color: design.palette.accent };
    return compose(slide, blocks, [], [], background);
  }

  private layoutSummaryTakeaway(slide: SlideSpec, deck: DeckSpec): SlideLayout {
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

  private layoutQuotePullquote(slide: SlideSpec, deck: DeckSpec): SlideLayout {
    const regions = SLIDE_REGIONS.quote_pullquote!;
    const { design } = deck;
    const blocks: TextBlock[] = [];

    const quoteText = slide.content.quote_text ?? slide.content.title;
    blocks.push(
      buildTextBlock({
        text: `"${quoteText}"`,
        region: regions.title!,
        fontFamily: design.body_font,
        fontWeight: 'normal',
        fontStyle: 'italic',
        color: design.palette.text,
        align: 'left',
        tier: FONT_SIZES.heading,
        lineHeight: LINE_HEIGHTS.heading,
      }),
    );

    if (slide.content.quote_attribution) {
      blocks.push(
        buildTextBlock({
          text: `— ${slide.content.quote_attribution}`,
          region: regions.subtitle!,
          fontFamily: design.body_font,
          fontWeight: 'normal',
          color: design.palette.text_secondary,
          align: 'right',
          tier: FONT_SIZES.caption,
          lineHeight: LINE_HEIGHTS.caption,
        }),
      );
    }

    // Decorative oversized quotation mark (R26 visual breath).
    const shapes: ShapeBlock[] = [
      {
        type: 'circle',
        x: 8,
        y: 18,
        w: 4,
        h: 4,
        fill: design.palette.accent,
        opacity: 0.1,
      },
    ];

    const background = defaultBackground(design);
    return compose(slide, blocks, [], shapes, background);
  }

  private layoutGalleryPeople(slide: SlideSpec, deck: DeckSpec): SlideLayout {
    const regions = SLIDE_REGIONS.gallery_people!;
    const { design } = deck;
    const blocks: TextBlock[] = [];
    const images: ImageBlock[] = [];

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

    const people = (slide.content.people ?? []).slice(0, 5);
    const positions = getPortraitPositions(people.length);

    people.forEach((person, idx) => {
      const position = positions[idx];
      if (!position) return;

      if (person.portrait_url) {
        images.push({
          src: person.portrait_url,
          x: position.x,
          y: position.y,
          w: position.w,
          h: position.h,
          objectFit: 'cover',
          opacity: 1,
          isBackground: false,
        });
      }

      const baseY = position.y + position.h + 1;
      const captionWidth = position.w;
      const nameRegion: Region = { x: position.x, y: baseY, w: captionWidth, h: 4 };
      blocks.push(
        buildTextBlock({
          text: person.name,
          region: nameRegion,
          fontFamily: design.body_font,
          fontWeight: 'bold',
          color: design.palette.text,
          align: 'center',
          tier: FONT_SIZES.caption,
          lineHeight: LINE_HEIGHTS.caption,
        }),
      );

      if (person.years || person.role) {
        const datesRegion: Region = {
          x: position.x,
          y: baseY + 5,
          w: captionWidth,
          h: 3,
        };
        const datesText = [person.years, person.role].filter(Boolean).join(' · ');
        blocks.push(
          buildTextBlock({
            text: datesText,
            region: datesRegion,
            fontFamily: design.body_font,
            fontWeight: 'normal',
            color: design.palette.text_secondary,
            align: 'center',
            tier: FONT_SIZES.small,
            lineHeight: LINE_HEIGHTS.caption,
          }),
        );
      }

      if (person.description) {
        const descRegion: Region = {
          x: position.x,
          y: baseY + 9,
          w: captionWidth,
          h: 3,
        };
        blocks.push(
          buildTextBlock({
            text: person.description,
            region: descRegion,
            fontFamily: design.body_font,
            fontWeight: 'normal',
            color: design.palette.text_secondary,
            align: 'center',
            tier: FONT_SIZES.small,
            lineHeight: LINE_HEIGHTS.caption,
          }),
        );
      }
    });

    if (slide.content.caption) {
      blocks.push(
        buildTextBlock({
          text: slide.content.caption,
          region: regions.caption!,
          fontFamily: design.body_font,
          fontWeight: 'normal',
          fontStyle: 'italic',
          color: design.palette.text_secondary,
          align: 'center',
          tier: FONT_SIZES.caption,
          lineHeight: LINE_HEIGHTS.caption,
        }),
      );
    }

    const background = defaultBackground(design);
    return compose(slide, blocks, images, [], background);
  }

  private layoutComparison(slide: SlideSpec, deck: DeckSpec): SlideLayout {
    const regions = SLIDE_REGIONS.comparison!;
    const { design } = deck;
    const blocks: TextBlock[] = [];
    const shapes: ShapeBlock[] = [];

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

    const leftRegion = regions.body!;
    const rightRegion = regions.image!;

    this.layoutComparisonColumn(slide.content.left_column, leftRegion, design, blocks);
    this.layoutComparisonColumn(slide.content.right_column, rightRegion, design, blocks);

    // Subtle vertical divider between columns (R19 grid gutter).
    shapes.push({
      type: 'rect',
      x: 49.9,
      y: leftRegion.y,
      w: 0.1,
      h: leftRegion.h,
      fill: design.palette.accent,
      opacity: 0.3,
    });

    const background = defaultBackground(design);
    return compose(slide, blocks, [], shapes, background);
  }

  private layoutComparisonColumn(
    column: SlideContent['left_column'],
    region: Region,
    design: DesignDirectionSpec,
    blocks: TextBlock[],
  ): void {
    if (!column) return;

    const headingRegion: Region = { x: region.x, y: region.y, w: region.w, h: 8 };
    blocks.push(
      buildTextBlock({
        text: column.heading,
        region: headingRegion,
        fontFamily: design.heading_font,
        fontWeight: 'bold',
        color: column.is_preferred ? design.palette.accent : design.palette.text,
        align: 'left',
        tier: FONT_SIZES.subheading,
        lineHeight: LINE_HEIGHTS.heading,
      }),
    );

    const points = column.points ?? [];
    if (points.length === 0) return;

    const pointsTop = region.y + 10;
    const pointsBottom = region.y + region.h;
    const totalH = pointsBottom - pointsTop;
    const slotH = totalH / Math.max(1, points.length);

    points.forEach((point, idx) => {
      const pointRegion: Region = {
        x: region.x,
        y: pointsTop + idx * slotH,
        w: region.w,
        h: slotH * 0.9,
      };
      blocks.push(
        buildTextBlock({
          text: `• ${point}`,
          region: pointRegion,
          fontFamily: design.body_font,
          fontWeight: 'normal',
          color: design.palette.text,
          align: 'left',
          tier: FONT_SIZES.body,
          lineHeight: LINE_HEIGHTS.body,
        }),
      );
    });
  }

  // -------------------------------------------------------------------------
  // Generic fallback (used by 14 not-yet-implemented types)
  // -------------------------------------------------------------------------

  private layoutGenericFallback(slide: SlideSpec, deck: DeckSpec): SlideLayout {
    const { design } = deck;
    const blocks: TextBlock[] = [];

    const titleRegion: Region = { x: 5, y: 5, w: 90, h: 8 };
    blocks.push(
      buildTextBlock({
        text: slide.content.title,
        region: titleRegion,
        fontFamily: design.heading_font,
        fontWeight: 'bold',
        color: design.palette.text,
        align: 'left',
        tier: FONT_SIZES.heading,
        lineHeight: LINE_HEIGHTS.heading,
      }),
    );

    const bodyText = this.composeBodyText(slide.content);
    if (bodyText) {
      const bodyRegion: Region = { x: 5, y: 18, w: 90, h: 70 };
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

    const background = defaultBackground(design);
    return compose(slide, blocks, [], [], background);
  }

  /**
   * Compose a single body string from `body_text` and `bullets` for
   * fallback layouts that need one text block. Bullets are
   * concatenated with leading dots so the renderer doesn't have to
   * special-case lists at this level.
   */
  private composeBodyText(content: SlideContent): string | null {
    const parts: string[] = [];
    if (content.body_text) parts.push(content.body_text);
    if (content.bullets) {
      for (const bullet of content.bullets) parts.push(`• ${bullet}`);
    }
    if (parts.length === 0) return null;
    return parts.join('\n');
  }
}
