/**
 * Design language constants.
 *
 * Encodes the per-slide-type region specifications, font size tiers,
 * spacing tiers, and word-count limits defined in
 * packages/presentation/DESIGN-LANGUAGE.md sections 5-6.
 *
 * Every value is a percentage of slide dimensions unless the comment
 * says otherwise. The Layout Pass multiplies by SLIDE_WIDTH / SLIDE_HEIGHT
 * to derive pixel coordinates when needed.
 */

import type { SlideType } from './types.js';

// ---------------------------------------------------------------------------
// Slide dimensions
// ---------------------------------------------------------------------------

export const SLIDE_WIDTH = 1920 as const;
export const SLIDE_HEIGHT = 1080 as const;

// ---------------------------------------------------------------------------
// Margins and content area (R16)
// ---------------------------------------------------------------------------

export const MARGIN = {
  left: 5,
  right: 5,
  top: 6,
  bottom: 6,
} as const;

export const CONTENT_AREA = {
  maxWidth: 90,
  maxHeight: 88,
} as const;

// ---------------------------------------------------------------------------
// Spacing tiers (R18). Pixel values.
// ---------------------------------------------------------------------------

export const SPACING = {
  tight: { min: 8, max: 12 },
  medium: { min: 24, max: 32 },
  wide: { min: 48, max: 64 },
} as const;

// ---------------------------------------------------------------------------
// Font sizes (R05, R06, R07). Pixel values.
// ---------------------------------------------------------------------------

export const FONT_SIZES = {
  displayJumbo: { min: 40, max: 64 },
  displayLarge: { min: 48, max: 64 },
  heading: { min: 28, max: 40 },
  subheading: { min: 20, max: 24 },
  body: { min: 16, max: 20 },
  caption: { min: 14, max: 16 },
  small: { min: 12, max: 14 },
  minimum: 12,
} as const;

// ---------------------------------------------------------------------------
// Line heights (R10)
// ---------------------------------------------------------------------------

export const LINE_HEIGHTS = {
  heading: 1.1,
  body: 1.5,
  caption: 1.3,
} as const;

// ---------------------------------------------------------------------------
// Word count limits per slide type (R17)
// ---------------------------------------------------------------------------

export const WORD_LIMITS: Record<SlideType, number> = {
  title_hero: 15,
  concept_definition: 50,
  gallery_people: 60,
  typographic_keywords: 55,
  content_split: 60,
  data_emphasis: 30,
  comparison: 70,
  timeline: 50,
  flow_process: 50,
  quote_pullquote: 35,
  chart_data: 20,
  table_compact: 999,
  section_break: 6,
  summary_takeaway: 60,
  resources_links: 60,
  team_credits: 40,
  interactive_quiz_mcq: 50,
  interactive_matching: 50,
  interactive_categorize: 50,
  interactive_fill_blank: 50,
  interactive_true_false: 50,
  interactive_debate: 70,
};

// ---------------------------------------------------------------------------
// Image source classification
// ---------------------------------------------------------------------------

/**
 * Whether an image `src` is an unresolved placeholder rather than a loadable
 * reference. A real reference — an http(s)/file/data URL or an absolute path —
 * is loadable at ANY length (signed object-store URLs routinely exceed 500
 * chars), so it is never a placeholder. Only a `[`-prefixed prompt marker or a
 * long bare string (leftover prompt text the image engine never resolved) is.
 */
export function isPlaceholderImageSrc(src: string | null | undefined): boolean {
  if (!src) return true;
  if (/^(https?:|file:|data:|\/|[a-zA-Z]:[\\/])/.test(src)) return false;
  return src.startsWith('[') || src.length > 500;
}

// ---------------------------------------------------------------------------
// Region specs per slide type. Percentages of slide dimensions.
// ---------------------------------------------------------------------------

export interface Region {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface SlideRegions {
  title?: Region;
  subtitle?: Region;
  body?: Region;
  image?: Region;
  /** Bounding box for a contained object-figure (objectFit:'contain'). Lives
   *  in the right column, clear of the left-hand text, so a figure never
   *  overlaps title/body. Only the layouts that can carry a figure define it. */
  figure?: Region;
  caption?: Region;
  citation?: Region;
}

export const SLIDE_REGIONS: Partial<Record<SlideType, SlideRegions>> = {
  title_hero: {
    title: { x: 5, y: 26, w: 85, h: 34 },
    subtitle: { x: 5, y: 64, w: 80, h: 8 },
    caption: { x: 5, y: 90, w: 40, h: 4 },
  },
  concept_definition: {
    title: { x: 5, y: 5, w: 50, h: 8 },
    subtitle: { x: 5, y: 16, w: 48, h: 12 },
    body: { x: 5, y: 32, w: 48, h: 50 },
    // Right column, clear of the left text (which ends at x=53).
    figure: { x: 55, y: 18, w: 40, h: 64 },
  },
  content_split: {
    title: { x: 5, y: 5, w: 48, h: 8 },
    // h is a MAX bound only — layoutContentSplit derives the body column's height
    // from the title's measured bottom down to the caption strip.
    body: { x: 5, y: 18, w: 48, h: 65 },
    image: { x: 52, y: 0, w: 48, h: 100 },
    // A contained figure sits inset from the full-bleed `image` panel so the
    // object reads as a clean specimen rather than a cropped edge-to-edge photo.
    figure: { x: 55, y: 12, w: 41, h: 76 },
    caption: { x: 5, y: 88, w: 48, h: 5 },
  },
  data_emphasis: {
    title: { x: 5, y: 5, w: 90, h: 8 },
  },
  comparison: {
    title: { x: 5, y: 5, w: 90, h: 8 },
    body: { x: 5, y: 15, w: 43, h: 75 },
    image: { x: 52, y: 15, w: 43, h: 75 },
  },
  quote_pullquote: {
    title: { x: 10, y: 25, w: 80, h: 35 },
    subtitle: { x: 10, y: 65, w: 80, h: 5 },
  },
  section_break: {
    title: { x: 10, y: 35, w: 80, h: 20 },
  },
  summary_takeaway: {
    title: { x: 5, y: 5, w: 90, h: 8 },
    body: { x: 8, y: 18, w: 84, h: 70 },
  },
  gallery_people: {
    title: { x: 5, y: 3, w: 90, h: 7 },
    caption: { x: 5, y: 88, w: 90, h: 4 },
  },
  typographic_keywords: {
    title: { x: 5, y: 4, w: 90, h: 8 },
  },
  timeline: {
    title: { x: 5, y: 3, w: 90, h: 7 },
  },
  flow_process: {
    title: { x: 5, y: 3, w: 90, h: 7 },
  },
  chart_data: {
    title: { x: 5, y: 4, w: 90, h: 8 },
    // h is a MAX bound only — layoutChartData derives the chart region's height
    // from the title's measured bottom down to the bottom content margin.
    body: { x: 5, y: 15, w: 65, h: 72 },
    caption: { x: 72, y: 15, w: 23, h: 30 },
    citation: { x: 70, y: 90, w: 25, h: 4 },
  },
  table_compact: {
    title: { x: 5, y: 4, w: 90, h: 8 },
    body: { x: 5, y: 15, w: 90, h: 75 },
    citation: { x: 5, y: 92, w: 90, h: 4 },
  },
};

// ---------------------------------------------------------------------------
// Multi-column grid specs (R19)
// ---------------------------------------------------------------------------

export const GRID = {
  2: { columns: [48, 48] as const, gutter: 4 },
  3: { columns: [31, 31, 31] as const, gutter: 3.5 },
  4: { columns: [22.75, 22.75, 22.75, 22.75] as const, gutter: 3 },
} as const;

// ---------------------------------------------------------------------------
// Stat positions for DATA_EMPHASIS by count
// ---------------------------------------------------------------------------

/**
 * Column bands for the stat row(s). Horizontal positions match the
 * original 1/2/3/4 layouts; vertical bands span the full content envelope
 * — title bottom (y≈14 after a 1pp breather) to the bottom margin
 * (y=94) — so the number can read big like a Canva headline instead of
 * being trapped in a 50% mid-slide strip. For 4 stats the band splits
 * into two equal rows so the 2×2 grid still reads as two distinct rows.
 *
 * The data_emphasis layout consumes y/h as the band envelope; an
 * adaptive font tier (computed from band height) decides how big the
 * number actually renders. Do NOT shrink these back to 50% — the under-
 * fill bug this fixes lives in band geometry.
 */
export const STAT_POSITIONS: Record<1 | 2 | 3 | 4, readonly Region[]> = {
  1: [{ x: 25, y: 14, w: 50, h: 80 }],
  2: [
    { x: 10, y: 14, w: 35, h: 80 },
    { x: 55, y: 14, w: 35, h: 80 },
  ],
  3: [
    { x: 5, y: 14, w: 28, h: 80 },
    { x: 36, y: 14, w: 28, h: 80 },
    { x: 67, y: 14, w: 28, h: 80 },
  ],
  4: [
    { x: 8, y: 14, w: 37, h: 39 },
    { x: 55, y: 14, w: 37, h: 39 },
    { x: 8, y: 55, w: 37, h: 39 },
    { x: 55, y: 55, w: 37, h: 39 },
  ],
};

/**
 * Portrait positions for GALLERY_PEOPLE based on count.
 * Returns an empty array when count is out of supported range (1-2 or 6+).
 */
export function getPortraitPositions(count: number): Region[] {
  if (count <= 0) return [];
  if (count === 3) {
    return [
      { x: 10, y: 15, w: 20, h: 35 },
      { x: 40, y: 15, w: 20, h: 35 },
      { x: 70, y: 15, w: 20, h: 35 },
    ];
  }
  if (count === 4) {
    return [
      { x: 6, y: 15, w: 16, h: 32 },
      { x: 28, y: 15, w: 16, h: 32 },
      { x: 50, y: 15, w: 16, h: 32 },
      { x: 72, y: 15, w: 16, h: 32 },
    ];
  }
  // 5 (and the default for any unusual count) — five evenly spaced cutouts
  return [
    { x: 5, y: 15, w: 14, h: 30 },
    { x: 22, y: 15, w: 14, h: 30 },
    { x: 39, y: 15, w: 14, h: 30 },
    { x: 56, y: 15, w: 14, h: 30 },
    { x: 73, y: 15, w: 14, h: 30 },
  ];
}

/**
 * Per-keyword (term + explanation) positions for TYPOGRAPHIC_KEYWORDS.
 * Distributes count rows evenly between y=18 and y=88 (70% vertical band).
 */
export function getKeywordPositions(count: number): Array<{ term: Region; explain: Region }> {
  if (count <= 0) return [];
  const startY = 18;
  const bandHeight = 70;
  const stepY = bandHeight / count;
  const rowHeight = Math.min(stepY * 0.7, 10);
  return Array.from({ length: count }, (_, i) => ({
    term: { x: 5, y: startY + i * stepY, w: 35, h: rowHeight },
    explain: { x: 42, y: startY + i * stepY, w: 50, h: rowHeight },
  }));
}
