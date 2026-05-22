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
  displayJumbo: { min: 44, max: 96 },
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
  },
  content_split: {
    title: { x: 5, y: 5, w: 48, h: 8 },
    body: { x: 5, y: 18, w: 48, h: 65 },
    image: { x: 52, y: 0, w: 48, h: 100 },
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

export const STAT_POSITIONS: Record<1 | 2 | 3 | 4, readonly Region[]> = {
  1: [{ x: 25, y: 25, w: 50, h: 50 }],
  2: [
    { x: 10, y: 25, w: 35, h: 50 },
    { x: 55, y: 25, w: 35, h: 50 },
  ],
  3: [
    { x: 5, y: 25, w: 28, h: 50 },
    { x: 36, y: 25, w: 28, h: 50 },
    { x: 67, y: 25, w: 28, h: 50 },
  ],
  4: [
    { x: 8, y: 15, w: 37, h: 32 },
    { x: 55, y: 15, w: 37, h: 32 },
    { x: 8, y: 53, w: 37, h: 32 },
    { x: 55, y: 53, w: 37, h: 32 },
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

/**
 * Timeline node positions for horizontal layout (3-5 nodes).
 * Returns one Region per node, with x spread between 10% and 90%.
 */
export function getTimelinePositions(count: number): Region[] {
  if (count <= 0) return [];
  if (count === 1) return [{ x: 45, y: 35, w: 10, h: 25 }];
  const startX = 10;
  const endX = 90;
  const span = endX - startX;
  const step = span / (count - 1);
  const halfNodeW = 5;
  return Array.from({ length: count }, (_, i) => ({
    x: startX + i * step - halfNodeW,
    y: 35,
    w: halfNodeW * 2,
    h: 25,
  }));
}

/**
 * Flow process step positions: 3-5 steps horizontally distributed.
 */
export function getFlowStepPositions(count: number): Region[] {
  if (count <= 0) return [];
  const totalGutter = 4 * (count - 1);
  const stepWidth = (90 - totalGutter) / count;
  return Array.from({ length: count }, (_, i) => ({
    x: 5 + i * (stepWidth + 4),
    y: 30,
    w: stepWidth,
    h: 40,
  }));
}
