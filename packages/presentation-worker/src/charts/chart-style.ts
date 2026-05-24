/**
 * Chart styling primitives: the per-deck colour ramp, value formatting,
 * and the small geometry helpers the chart drawers share.
 *
 * Colours are derived from the deck's *actual* palette rather than a
 * hardcoded per-mood table. The Design Direction Pass emits a bespoke
 * palette per deck (the six-mood table is only its fallback), so a fixed
 * ramp keyed by mood would clash with a generated palette. Anchoring on
 * `palette.accent` and deriving the supporting colours from the palette
 * keeps every chart inside its own deck's world.
 */

import { SLIDE_HEIGHT, SLIDE_WIDTH } from '../constants.js';
import type { ColorPalette, ShapeBlock } from '../types.js';

// ---------------------------------------------------------------------------
// Colour math (sRGB; good enough for ramp derivation + contrast guarding)
// ---------------------------------------------------------------------------

interface Rgb {
  r: number;
  g: number;
  b: number;
}

function hexToRgb(hex: string): Rgb {
  const clean = hex.startsWith('#') ? hex.slice(1) : hex;
  return {
    r: parseInt(clean.slice(0, 2), 16),
    g: parseInt(clean.slice(2, 4), 16),
    b: parseInt(clean.slice(4, 6), 16),
  };
}

function rgbToHex({ r, g, b }: Rgb): string {
  const h = (n: number) =>
    Math.max(0, Math.min(255, Math.round(n))).toString(16).padStart(2, '0');
  return `#${h(r)}${h(g)}${h(b)}`.toUpperCase();
}

/** Channel-wise mix: t=0 returns `a`, t=1 returns `b`. */
function mixHex(a: string, b: string, t: number): string {
  const ca = hexToRgb(a);
  const cb = hexToRgb(b);
  return rgbToHex({
    r: ca.r + (cb.r - ca.r) * t,
    g: ca.g + (cb.g - ca.g) * t,
    b: ca.b + (cb.b - ca.b) * t,
  });
}

function relativeLuminance(hex: string): number {
  const { r, g, b } = hexToRgb(hex);
  const channel = (c: number) => {
    const s = c / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
}

export function contrastRatio(a: string, b: string): number {
  const la = relativeLuminance(a);
  const lb = relativeLuminance(b);
  const lighter = Math.max(la, lb);
  const darker = Math.min(la, lb);
  return (lighter + 0.05) / (darker + 0.05);
}

/**
 * Nudge `color` toward `toward` (the deck text colour, which the design
 * pass guarantees contrasts the background) until it clears `min` contrast
 * against `bg`. Used so a derived supporting colour can never come out
 * illegible on the slide background. Terminates because `toward` itself
 * clears the threshold.
 */
function ensureContrast(color: string, bg: string, toward: string, min = 3): string {
  let out = color;
  for (let i = 0; i < 10 && contrastRatio(out, bg) < min; i++) {
    out = mixHex(out, toward, 0.2);
  }
  return out;
}

/**
 * A `count`-colour ramp derived from the deck palette (default 4).
 *
 * Hero (first) series = the brand accent, untouched. Supporting series are
 * the accent stepped toward the text colour (a cohesive, single-family
 * gradient that reads as designed), with the palette's secondary text colour
 * as a neutral last entry when there are 3+ series — each contrast-guarded
 * against the background. A 2-series chart gets accent + a lighter accent
 * (monochromatic, studio); more series add evenly spaced steps. The ramp
 * always produces `count` distinct colours so a grouped/stacked legend never
 * reuses one (chart_group_labels caps at 6).
 */
export function resolveChartRamp(palette: ColorPalette, count = 4): string[] {
  const { accent, text, text_secondary: secondary, background } = palette;
  if (count <= 1) return [accent];

  const ramp = [accent];
  const useNeutral = count >= 3;
  const tintSlots = useNeutral ? count - 2 : count - 1;
  for (let k = 0; k < tintSlots; k++) {
    const t = 0.4 + 0.4 * (tintSlots === 1 ? 0 : k / (tintSlots - 1));
    ramp.push(ensureContrast(mixHex(accent, text, t), background, text));
  }
  if (useNeutral) ramp.push(ensureContrast(secondary, background, text));
  return ramp;
}

// ---------------------------------------------------------------------------
// Value formatting (the renderer's job per the model docstring)
// ---------------------------------------------------------------------------

function formatNumber(value: number): string {
  const rounded = Math.round(value * 100) / 100;
  let body: string;
  if (Number.isInteger(rounded)) {
    body = Math.abs(rounded).toString();
  } else {
    body = Math.abs(rounded)
      .toFixed(2)
      .replace(/0+$/, '')
      .replace(/\.$/, '');
  }
  const [intPart, decPart] = body.split('.');
  const grouped = intPart!.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  const sign = rounded < 0 ? '-' : '';
  return decPart !== undefined ? `${sign}${grouped}.${decPart}` : `${sign}${grouped}`;
}

/**
 * Format a plotted value with its unit: thousands separators, up to two
 * decimals (trailing zeros trimmed), unit appended. Alphabetic units get a
 * space ("120 kW"); symbol units attach ("94.4%", "35°C") — the same split
 * the editorial breather uses.
 */
export function formatChartValue(value: number, unit?: string | null): string {
  const num = formatNumber(value);
  if (!unit) return num;
  const space = /^[A-Za-z]/.test(unit) ? ' ' : '';
  return `${num}${space}${unit}`;
}

// ---------------------------------------------------------------------------
// Geometry helpers
// ---------------------------------------------------------------------------

/**
 * A circle of pixel diameter `diameterPx` centred at (`cxPct`, `cyPct`).
 *
 * Width and height percentages are computed against each axis so both
 * renderers' `min(w_px, h_px)` lands on the same pixel diameter (the canvas
 * is 16:9 on both axes), yielding a true circle rather than an ellipse.
 */
export function circleShape(
  cxPct: number,
  cyPct: number,
  diameterPx: number,
  fill: string,
  opacity = 1,
): ShapeBlock {
  const wPct = (diameterPx / SLIDE_WIDTH) * 100;
  const hPct = (diameterPx / SLIDE_HEIGHT) * 100;
  return {
    type: 'circle',
    x: cxPct - wPct / 2,
    y: cyPct - hPct / 2,
    w: wPct,
    h: hPct,
    fill,
    opacity,
  };
}

/** A horizontal hairline (baseline / gridline) from (`x`,`y`) spanning `w`. */
export function horizontalRule(
  x: number,
  y: number,
  w: number,
  stroke: string,
  strokeWidth = 2,
  opacity = 1,
): ShapeBlock {
  return { type: 'line', x, y, w, h: 0, stroke, strokeWidth, opacity };
}

/**
 * The drawn extent of a shape as a bounding box, resolving diagonal lines
 * (x2/y2) to their endpoint box. Tests use it to assert chart shapes stay
 * inside the chart region.
 */
export function shapeExtent(shape: ShapeBlock): {
  x: number;
  y: number;
  w: number;
  h: number;
} {
  if (shape.type === 'line' && shape.x2 !== undefined && shape.y2 !== undefined) {
    return {
      x: Math.min(shape.x, shape.x2),
      y: Math.min(shape.y, shape.y2),
      w: Math.abs(shape.x2 - shape.x),
      h: Math.abs(shape.y2 - shape.y),
    };
  }
  return { x: shape.x, y: shape.y, w: shape.w, h: shape.h };
}
