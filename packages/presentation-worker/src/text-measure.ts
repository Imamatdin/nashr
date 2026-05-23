/**
 * Text measurement.
 *
 * Width comes from true glyph advances via fontkit (see font-metrics.ts):
 * each word and the space glyph are measured against the actual font
 * outlines, so greedy word-wrapping reflects what the renderer will draw.
 * The Layout Pass runs in pure Node with no browser, which is why the
 * measurement backend must work without a DOM or canvas.
 *
 * When a family resolves to no real font file (neither vendored nor
 * installed), font-metrics falls back to a character-width ratio. That
 * fallback is only an approximation good enough to catch gross overflow;
 * the previous interim WIDTH_SAFETY inflation hack is gone now that the
 * primary path measures real widths.
 *
 * The public interface (TextMeasurement / MeasureOptions) is unchanged so
 * callers and the quality audit are unaffected.
 */

import { measureLineWidthPx } from './font-metrics.js';

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
 * Measures per-word and per-space glyph widths, simulates greedy word
 * wrapping, and reports whether the resulting block fits the box.
 */
export function measureText(options: MeasureOptions): TextMeasurement {
  const {
    text,
    fontSize,
    fontFamily,
    fontWeight,
    maxWidth: nominalMaxWidth,
    maxHeight,
    lineHeight,
  } = options;
  // Render-engine safety margin. We measure widths with fontkit but the deck
  // is rendered by PowerPoint/LibreOffice (PPTX/PDF) and the browser (HTML),
  // which wrap text at a narrower effective width (text-box insets + metric
  // drift). Empirically a 906px title wraps to 2 lines inside a 960px region
  // (94% full), so fontkit's raw "fits on one line" overcounts. Cap usable
  // width at 85% of nominal so a line only counts as fitting when the real
  // renderers also fit it. DO NOT remove — fontkit is not the renderer.
  const RENDER_WIDTH_SAFETY = 0.78;
  const maxWidth = nominalMaxWidth * RENDER_WIDTH_SAFETY;

  const words = text.split(/\s+/).filter((w) => w.length > 0);
  if (words.length === 0) {
    return { width: 0, height: 0, lineCount: 0, overflow: false, fitsInBox: true };
  }

  const spaceWidth = measureLineWidthPx(' ', fontFamily, fontWeight, fontSize);

  let lineCount = 1;
  let currentLineWidth = 0;
  let maxLineWidth = 0;

  for (const word of words) {
    const wordWidth = measureLineWidthPx(word, fontFamily, fontWeight, fontSize);
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
  // Render-engine height safety. PowerPoint/LibreOffice render lines taller
  // than the nominal fontSize*lineHeight (their own line spacing + paragraph
  // metrics), so a block occupies more vertical space than fontkit computes.
  // Inflate measured height so stacked blocks reserve enough room and do not
  // overlap. Calibrated against observed PPTX line spacing. DO NOT remove —
  // fontkit is not the renderer.
  const HEIGHT_SAFETY = 1.3;
  const totalHeight = lineCount * lineHeightPx * HEIGHT_SAFETY;

  return {
    width: maxLineWidth,
    height: totalHeight,
    lineCount,
    overflow: totalHeight > maxHeight,
    fitsInBox: totalHeight <= maxHeight && maxLineWidth <= maxWidth,
  };
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
