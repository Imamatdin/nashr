/**
 * Text measurement.
 *
 * v1 implementation: character-width estimation.
 *
 * Why not Pretext? `@chenglou/pretext` is published on npm and is the
 * library we want long-term — its README advertises "Allows rendering
 * to DOM, Canvas, SVG and soon, server-side". Today (0.0.7) its
 * `prepare()` requires either `OffscreenCanvas` or `document.createElement`,
 * neither of which exists in vanilla Node 22. Polyfilling OffscreenCanvas
 * with `@napi-rs/canvas` works but pulls a ~20MB native module just to
 * measure text during the Layout Pass.
 *
 * The spec's accepted v1 path is therefore character-width estimation,
 * good enough to catch gross overflows (>15% over) which is what the
 * Layout Pass needs to know to drop a font tier. Pixel-accurate
 * measurement matters for the renderer (Tasks 20-23) and the quality
 * audit (Q1), and we can swap the backend without changing this module's
 * public interface.
 *
 * Average character widths come from inspecting a few representative
 * Google Fonts metrics: sans-serif ~ 0.48em, serif ~ 0.52em, mono ~ 0.60em,
 * with bold weights inflating ~4-8%.
 */

export interface TextMeasurement {
  /** Width of the longest line after wrapping, in px. */
  width: number;
  /** Total height of the wrapped block, in px. */
  height: number;
  /** Number of wrapped lines. */
  lineCount: number;
  /** True if the wrapped block height exceeds maxHeight. */
  overflow: boolean;
  /** True if the block fits within both maxWidth and maxHeight. */
  fitsInBox: boolean;
}

export interface MeasureOptions {
  text: string;
  fontSize: number;
  fontFamily: string;
  fontWeight: 'normal' | 'bold' | 'semibold';
  maxWidth: number;
  maxHeight: number;
  lineHeight: number;
}

/**
 * Measure text under the given font and box constraints.
 *
 * Approximates per-character widths, simulates greedy word wrapping,
 * and reports whether the resulting block fits the box.
 */
export function measureText(options: MeasureOptions): TextMeasurement {
  const {
    text,
    fontSize,
    fontFamily,
    fontWeight,
    maxWidth,
    maxHeight,
    lineHeight,
  } = options;

  // Safety margin: the char-width model errs optimistic (too few lines),
  // which causes titles to overflow their region. Bias ~12% wider so
  // wrapping is conservative — better a slightly smaller font than a collision.
  const WIDTH_SAFETY = 1.12;
  const charWidthRatio = getCharWidthRatio(fontFamily, fontWeight) * WIDTH_SAFETY;
  const avgCharWidth = fontSize * charWidthRatio;
  const spaceWidth = avgCharWidth * 0.5;

  const words = text.split(/\s+/).filter((w) => w.length > 0);
  if (words.length === 0) {
    return { width: 0, height: 0, lineCount: 0, overflow: false, fitsInBox: true };
  }

  let lineCount = 1;
  let currentLineWidth = 0;
  let maxLineWidth = 0;

  for (const word of words) {
    const wordWidth = word.length * avgCharWidth;
    const isLineStart = currentLineWidth === 0;
    const neededWidth = isLineStart ? wordWidth : currentLineWidth + spaceWidth + wordWidth;

    // A single word longer than maxWidth still occupies a line on its own;
    // we don't simulate character-level breaking here.
    if (!isLineStart && neededWidth > maxWidth) {
      maxLineWidth = Math.max(maxLineWidth, currentLineWidth);
      lineCount += 1;
      currentLineWidth = wordWidth;
    } else {
      currentLineWidth = neededWidth;
    }
  }
  maxLineWidth = Math.max(maxLineWidth, currentLineWidth);

  const lineHeightPx = fontSize * lineHeight;
  const totalHeight = lineCount * lineHeightPx;

  return {
    width: maxLineWidth,
    height: totalHeight,
    lineCount,
    overflow: totalHeight > maxHeight,
    fitsInBox: totalHeight <= maxHeight && maxLineWidth <= maxWidth,
  };
}

/**
 * Average character-width ratio (as a fraction of fontSize) for the
 * supplied font family and weight. The lookup uses substring matching
 * because deck designs commonly request fonts by display name
 * ("EB Garamond", "Playfair Display") rather than a structured spec.
 *
 * Order matters: "Noto Sans Mono" must match mono before sans, and the
 * sans branch must beat the serif branch when both substrings appear
 * (e.g. "Noto Sans Serif", a real Google Fonts name).
 */
function getCharWidthRatio(fontFamily: string, fontWeight: string): number {
  const family = fontFamily.toLowerCase();
  const boldMultiplier =
    fontWeight === 'bold' ? 1.08 : fontWeight === 'semibold' ? 1.04 : 1.0;

  if (
    family.includes('mono') ||
    family.includes('jetbrains') ||
    family.includes('courier')
  ) {
    return 0.6 * boldMultiplier;
  }
  if (family.includes('sans')) {
    return 0.52 * boldMultiplier;
  }
  if (family.includes('serif') || isKnownSerifFamily(family)) {
    return 0.52 * boldMultiplier;
  }
  return 0.48 * boldMultiplier;
}

/**
 * Display-named serif families that don't carry "serif" in the name.
 * Kept small on purpose — extend only when the renderer is told to
 * use one of these by the Design Direction Pass.
 */
function isKnownSerifFamily(family: string): boolean {
  return (
    family.includes('garamond') ||
    family.includes('playfair') ||
    family.includes('baskerville') ||
    family.includes('cormorant') ||
    family.includes('georgia') ||
    family.includes('times')
  );
}

// ---------------------------------------------------------------------------
// Slide-level overflow check
// ---------------------------------------------------------------------------

export interface OverflowIssue {
  field: string;
  text: string;
  lineCount: number;
  maxLines: number;
  suggestion: 'reduce font size' | 'truncate' | 'split slide';
}

export function checkSlideOverflow(
  textBlocks: Array<{ field: string; text: string; options: MeasureOptions }>,
): OverflowIssue[] {
  const issues: OverflowIssue[] = [];

  for (const block of textBlocks) {
    const measurement = measureText(block.options);
    if (!measurement.overflow) continue;

    const lineHeightPx = block.options.fontSize * block.options.lineHeight;
    const maxLines = Math.max(1, Math.floor(block.options.maxHeight / lineHeightPx));
    const ratio = measurement.lineCount / maxLines;
    const suggestion: OverflowIssue['suggestion'] =
      ratio > 1.5 ? 'split slide' : ratio > 1.2 ? 'truncate' : 'reduce font size';

    issues.push({
      field: block.field,
      text: block.text,
      lineCount: measurement.lineCount,
      maxLines,
      suggestion,
    });
  }

  return issues;
}
