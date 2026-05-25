/**
 * Shared helpers used by every layout module.
 *
 * Extracted from the monolithic layout-pass.ts so that each per-type
 * layout file stays focused on the composition specific to its slide
 * type. Anything that more than one layout reaches for lives here:
 * region math, text-block construction with overflow reduction, word
 * counting, background composition, the SlideLayout composer.
 */

import { FONT_SIZES, MARGIN, SLIDE_HEIGHT, SLIDE_WIDTH, WORD_LIMITS, type Region } from '../constants.js';
import { measureText } from '../text-measure.js';
import type {
  DesignDirectionSpec,
  FontStyle,
  FontWeight,
  ImageBlock,
  InteractiveRole,
  ScrimBlock,
  ShapeBlock,
  SlideBackground,
  SlideContent,
  SlideLayout,
  SlideSpec,
  TextAlign,
  TextBlock,
} from '../types.js';

// ---------------------------------------------------------------------------
// Geometry / unit helpers
// ---------------------------------------------------------------------------

export interface FontTier {
  readonly min: number;
  readonly max: number;
}

export function pctToPx(pct: number, dimension: number): number {
  return (pct / 100) * dimension;
}

export function regionWidthPx(region: Region): number {
  return pctToPx(region.w, SLIDE_WIDTH);
}

export function regionHeightPx(region: Region): number {
  return pctToPx(region.h, SLIDE_HEIGHT);
}

// ---------------------------------------------------------------------------
// Word counting (R17 audit input)
// ---------------------------------------------------------------------------

export function countWords(text: string | null | undefined): number {
  if (!text) return 0;
  return text.trim().split(/\s+/).filter(Boolean).length;
}

export function countSlideWords(content: SlideContent): number {
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

// ---------------------------------------------------------------------------
// Text-block construction with overflow reduction
// ---------------------------------------------------------------------------

export interface BuildTextBlockOptions {
  text: string;
  region: Region;
  fontFamily: string;
  fontWeight: FontWeight;
  fontStyle?: FontStyle;
  color: string;
  align: TextAlign;
  tier: FontTier;
  lineHeight: number;
  role?: InteractiveRole;
  groupId?: string;
  dataIndex?: number;
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
export function buildTextBlock(opts: BuildTextBlockOptions): TextBlock {
  const maxWidthPx = regionWidthPx(opts.region);
  const maxHeightPx = regionHeightPx(opts.region);
  const floor = Math.max(FONT_SIZES.minimum, Math.min(opts.tier.min, opts.tier.max));

  const measure = (size: number) =>
    measureText({
      text: opts.text,
      fontSize: size,
      fontFamily: opts.fontFamily,
      fontWeight: opts.fontWeight,
      maxWidth: maxWidthPx,
      maxHeight: maxHeightPx,
      lineHeight: opts.lineHeight,
    });

  // Shrink from the tier max by 2px until the text fits or we hit the
  // floor. Keep the measurement from the iteration we stop on (the one
  // that fit, or the floor measurement if nothing fit) — its wrapped px
  // height is what callers stack downstream elements against.
  let fontSize = opts.tier.max;
  let measurement = measure(fontSize);
  while (!measurement.fitsInBox && fontSize > floor) {
    fontSize = Math.max(floor, fontSize - 2);
    measurement = measure(fontSize);
  }
  const overflow = !measurement.fitsInBox;

  const block: TextBlock = {
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
    measuredHeightPct: (measurement.height / SLIDE_HEIGHT) * 100,
  };
  if (opts.role !== undefined) block.role = opts.role;
  if (opts.groupId !== undefined) block.groupId = opts.groupId;
  if (opts.dataIndex !== undefined) block.dataIndex = opts.dataIndex;
  return block;
}

/**
 * Y-coordinate (slide percentage) at which the next stacked element
 * should begin: the measured bottom of `block` plus `gapPct`. Stacking
 * layouts (a subtitle/caption under a title, an annotation beside a
 * chart) use this instead of a fixed region y, so a wrapped multi-line
 * block pushes whatever follows it down rather than overlapping it.
 */
export function stackBelow(block: TextBlock, gapPct: number): number {
  return block.y + block.measuredHeightPct + gapPct;
}

/** Hairline added when hugging a box to its content, so sub-pixel rounding in
 *  the browser/PPTX render can't shave the last line. Smaller than any stacking
 *  gap, so it never makes two stacked boxes overlap. */
const HUG_EPSILON_PCT = 0.2;

/**
 * Vertical space (in slide percent) available to a stacked block whose top is
 * at `y`, measured down to the bottom content margin (R16).
 *
 * Document-flow layouts pass this as a block's region height so buildTextBlock
 * measures against the *real* space left on the slide and only shrinks when the
 * content genuinely can't fit — rather than shrinking (or clipping) against a
 * too-short fixed nominal region, which is the text-clipping bug this replaces.
 */
export function availableHeightBelow(y: number): number {
  return Math.max(0, 100 - MARGIN.bottom - y);
}

/**
 * Shrink a block's rendered box to its measured content height and return it.
 *
 * The HTML renderer sizes every text box to `block.h` with `overflow:hidden`,
 * so for top-down document flow each block's `h` must cover its measured
 * content or the tail clips. Setting `h` to `measuredHeightPct` makes the box
 * hug the text exactly: nothing clips, and the next element placed at
 * `stackBelow(block, gap)` sits flush with no transparent dead box overlapping
 * it.
 *
 * This deliberately diverges from TITLE_HERO / CHART_DATA, which keep their
 * nominal region height — their slots are pre-tuned, and chart_data pins the
 * box bottom instead. Do NOT "simplify" this back to the region height: that
 * reintroduces the clipping anti-pattern this exists to kill.
 */
export function hugHeightToMeasured(block: TextBlock): TextBlock {
  block.h = block.measuredHeightPct + HUG_EPSILON_PCT;
  return block;
}

// ---------------------------------------------------------------------------
// Background helpers
// ---------------------------------------------------------------------------

export function defaultBackground(design: DesignDirectionSpec): SlideBackground {
  // The Design Direction Pass already chose a `background` colour that
  // matches the deck's polarity (dark or light). A per-slide override
  // signals "invert me" — section breaks use the accent and so handle
  // their own background; other slide types currently render the deck
  // background regardless of override, which the renderer can still
  // tune in CSS by inspecting `slide.background_override`.
  return { color: design.palette.background };
}

/**
 * Full-bleed image with a left-anchored gradient scrim — used by
 * TITLE_HERO and any other layout that wants topic imagery behind a
 * left-aligned text block.
 */
export function heroBackground(
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

/**
 * Build a scrim covering a specific rectangle. Layouts that anchor
 * text against an image (concept_definition, typographic_keywords)
 * compose their own scrim shape rather than relying on the hero
 * default.
 */
export function buildScrim(
  design: DesignDirectionSpec,
  options: {
    direction: ScrimBlock['direction'];
    opacity: number;
    x: number;
    y: number;
    w: number;
    h: number;
  },
): ScrimBlock {
  return {
    direction: options.direction,
    color: design.palette.background,
    opacity: options.opacity,
    x: options.x,
    y: options.y,
    w: options.w,
    h: options.h,
  };
}

// ---------------------------------------------------------------------------
// Contained object-figure (image engine PART 2)
// ---------------------------------------------------------------------------

/**
 * Build a contained-figure ImageBlock, or null when there is no figure.
 *
 * The figure is the deck's "workhorse" object slot: a rack, a turbine, a cold
 * plate. It renders with objectFit:'contain' (the whole object stays visible,
 * never cropped) and isBackground:false (it is foreground content, not a
 * full-bleed scene), inside a region that lives clear of the slide's text
 * column. A null `figureUrl` yields null — the caller adds nothing, so a slide
 * with no resolved figure renders exactly as it did before the image engine
 * (no empty box, no placeholder rect).
 */
export function figureImageBlock(
  figureUrl: string | null | undefined,
  region: Region,
): ImageBlock | null {
  if (!figureUrl) return null;
  return {
    src: figureUrl,
    x: region.x,
    y: region.y,
    w: region.w,
    h: region.h,
    objectFit: 'contain',
    opacity: 1,
    isBackground: false,
  };
}

// ---------------------------------------------------------------------------
// Final SlideLayout composer
// ---------------------------------------------------------------------------

export function compose(
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
// Bullet text normalisation
// ---------------------------------------------------------------------------

/**
 * Strip a single leading list enumerator ("1. ", "2) ") from bullet text.
 *
 * The editorial model sometimes bakes its own numbering into bullets; every
 * bullet-rendering layout then prepends "• ", producing "• 1. …" — doubled
 * numbering. Removing the enumerator at the point of render keeps the stored
 * deck untouched and is idempotent.
 *
 * The trailing `\s+` is REQUIRED: it makes the match a real enumerator
 * followed by whitespace ("1. ", "10) "), so a decimal that opens a bullet —
 * "1.08 PUE improvement" — is left intact (no space after the dot to consume).
 */
export function stripListPrefix(text: string): string {
  return text.replace(/^\s*\d+[.)]\s+/, '');
}

// ---------------------------------------------------------------------------
// Body-text composition for fallback layouts that need a single block
// ---------------------------------------------------------------------------

/**
 * Compose a single body string from `body_text` and `bullets`. Used by
 * content_split and any other layout that wants a single text region
 * carrying both running prose and bullets.
 */
export function composeBodyText(content: SlideContent): string | null {
  const parts: string[] = [];
  if (content.body_text) parts.push(content.body_text);
  if (content.bullets) {
    for (const bullet of content.bullets) parts.push(`• ${stripListPrefix(bullet)}`);
  }
  if (parts.length === 0) return null;
  return parts.join('\n');
}
