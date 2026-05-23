/**
 * True glyph-width measurement via fontkit.
 *
 * The Layout Pass runs in pure Node with no browser, so a line's width has
 * to come from the actual font outlines rather than a per-character guess.
 * This module loads the TTFs vendored in the repo `fonts/` directory and,
 * for the apt-installed families, resolves a file path through fontconfig
 * (`fc-match`). Every family the Design Direction Pass can emit therefore
 * resolves to a real font file OR cleanly falls back to a character-width
 * ratio (the pre-fontkit model) with a one-time warning naming the family.
 *
 * This module NEVER throws. A missing `fonts/` dir, an unreadable file, a
 * missing `fc-match` binary (e.g. on Windows), or a font that turns out to
 * be a collection all degrade to the ratio fallback.
 *
 * Variable fonts (IBM Plex Sans, Lora, Source Serif 4) are handled by
 * pinning the `wght` axis with `getVariation`; the one static vendored
 * family (IBM Plex Serif) selects a bold or regular file. Resolved fonts
 * are cached by family+weight so each TTF is parsed at most once per weight.
 */

import { execFileSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { openSync, type Font } from 'fontkit';

export type FontWeightInput = 'normal' | 'bold' | 'semibold';

/** Variable-font `wght` axis values, also reused for fontconfig requests. */
const WEIGHT_VALUES: Record<FontWeightInput, number> = {
  normal: 400,
  semibold: 600,
  bold: 700,
};

/** fontconfig symbolic weight constants for the `:weight=` selector. */
const FC_WEIGHT: Record<FontWeightInput, string> = {
  normal: 'regular',
  semibold: 'demibold',
  bold: 'bold',
};

// ---------------------------------------------------------------------------
// Vendored font resolution (repo fonts/ directory)
// ---------------------------------------------------------------------------

interface VendoredEntry {
  /** Filename within fonts/ for the requested weight. Bracket names like
   *  "IBMPlexSans[wdth,wght].ttf" are used literally — never globbed. */
  file: (weight: FontWeightInput) => string;
  /** Variable font: pin the wght axis via getVariation. */
  variable: boolean;
}

const VENDORED: Record<string, VendoredEntry> = {
  'ibm plex sans': {
    file: () => 'IBMPlexSans[wdth,wght].ttf',
    variable: true,
  },
  'ibm plex serif': {
    // Static family: the weight chooses the file, not an axis.
    file: (w) => (w === 'normal' ? 'IBMPlexSerif-Regular.ttf' : 'IBMPlexSerif-Bold.ttf'),
    variable: false,
  },
  lora: {
    file: () => 'Lora[wght].ttf',
    variable: true,
  },
  'source serif 4': {
    file: () => 'SourceSerif4[opsz,wght].ttf',
    variable: true,
  },
};

const MODULE_DIR = dirname(fileURLToPath(import.meta.url));

/**
 * Locate the repo `fonts/` directory. font-metrics ships in
 * packages/presentation-worker/{src,dist}; the vendored fonts live at the
 * repo root, three levels up from either. Falls back to cwd/fonts so the
 * CLI works when invoked from the repo root.
 */
function resolveFontsDir(): string | null {
  const candidates = [
    join(MODULE_DIR, '..', '..', '..', 'fonts'),
    join(MODULE_DIR, '..', '..', 'fonts'),
    join(process.cwd(), 'fonts'),
  ];
  for (const candidate of candidates) {
    if (existsSync(candidate)) return candidate;
  }
  return null;
}

const FONTS_DIR = resolveFontsDir();

// ---------------------------------------------------------------------------
// Cache + fallback warning
// ---------------------------------------------------------------------------

interface ResolvedFont {
  /** Weight already pinned (variable) or selected (static). */
  font: Font;
  unitsPerEm: number;
}

const cache = new Map<string, ResolvedFont | null>();
const warned = new Set<string>();

function warnFallback(family: string, reason: string): void {
  if (warned.has(family)) return;
  warned.add(family);
  // stderr, not stdout: the `layout` CLI writes its JSON to stdout.
  process.stderr.write(
    `[font-metrics] no glyph metrics for "${family}" (${reason}); ` +
      `falling back to character-width estimation\n`,
  );
}

/**
 * Pin the weight (for variable fonts) and confirm the object is a usable
 * single font, not a .ttc collection. Returns null if the result can't be
 * laid out — the caller then falls back rather than crashing later.
 */
function toResolved(font: Font, weight: FontWeightInput, variable: boolean): ResolvedFont | null {
  let resolved = font;
  if (
    variable &&
    resolved.variationAxes &&
    'wght' in resolved.variationAxes &&
    typeof resolved.getVariation === 'function'
  ) {
    resolved = resolved.getVariation({ wght: WEIGHT_VALUES[weight] });
  }
  if (
    typeof resolved.layout !== 'function' ||
    typeof resolved.unitsPerEm !== 'number' ||
    !(resolved.unitsPerEm > 0)
  ) {
    return null;
  }
  return { font: resolved, unitsPerEm: resolved.unitsPerEm };
}

function loadVendored(familyKey: string, weight: FontWeightInput): ResolvedFont | null {
  if (!FONTS_DIR) return null;
  const entry = VENDORED[familyKey]!;
  const path = join(FONTS_DIR, entry.file(weight));
  if (!existsSync(path)) return null;
  return toResolved(openSync(path), weight, entry.variable);
}

/**
 * Resolve an apt-installed family through fontconfig. fontconfig always
 * returns *some* font (it substitutes a fallback when the family is
 * absent), so we only trust the result when the returned family name
 * actually contains the requested one — otherwise we fall back rather than
 * silently measure an unrelated typeface.
 */
function loadViaFontconfig(family: string, weight: FontWeightInput): ResolvedFont | null {
  let out: string;
  try {
    out = execFileSync(
      'fc-match',
      ['-f', '%{family}\t%{file}', `${family}:weight=${FC_WEIGHT[weight]}`],
      { encoding: 'utf-8', stdio: ['ignore', 'pipe', 'ignore'], timeout: 5000 },
    );
  } catch {
    return null; // fc-match absent (Windows) or errored
  }
  const tab = out.indexOf('\t');
  if (tab < 0) return null;
  const matchedFamily = out.slice(0, tab).toLowerCase();
  const file = out.slice(tab + 1).trim();
  if (!file || !existsSync(file)) return null;
  if (!matchedFamily.includes(family.toLowerCase())) return null;
  return toResolved(openSync(file), weight, false);
}

function resolve(family: string, weight: FontWeightInput): ResolvedFont | null {
  const key = `${family.toLowerCase()}|${weight}`;
  const cached = cache.get(key);
  if (cached !== undefined) return cached;

  const familyKey = family.toLowerCase();
  let resolved: ResolvedFont | null = null;
  try {
    resolved =
      familyKey in VENDORED
        ? loadVendored(familyKey, weight)
        : loadViaFontconfig(family, weight);
  } catch {
    resolved = null; // any fontkit/IO failure → fallback, never throw
  }

  if (resolved === null) {
    warnFallback(
      family,
      familyKey in VENDORED ? 'vendored file unreadable' : 'no fontconfig match',
    );
  }
  cache.set(key, resolved);
  return resolved;
}

// ---------------------------------------------------------------------------
// Public measurement
// ---------------------------------------------------------------------------

/**
 * Width in px of `text` laid out on a single line in `family`/`weight` at
 * `fontSizePx`. Uses true glyph advances when the font resolves to a real
 * file:
 *
 *     advanceWidth * (fontSizePx / unitsPerEm)
 *
 * and otherwise falls back to the character-width ratio model. Never throws.
 */
export function measureLineWidthPx(
  text: string,
  family: string,
  weight: FontWeightInput,
  fontSizePx: number,
): number {
  if (text.length === 0) return 0;
  const resolved = resolve(family, weight);
  if (resolved) {
    return resolved.font.layout(text).advanceWidth * (fontSizePx / resolved.unitsPerEm);
  }
  return text.length * fontSizePx * getCharWidthRatio(family, weight);
}

// ---------------------------------------------------------------------------
// Character-width fallback (used only when no real font file resolves)
// ---------------------------------------------------------------------------

/**
 * FALLBACK ONLY. Average character-width ratio (as a fraction of fontSize)
 * for a family/weight, used when the family resolves to no real font file.
 * The primary path measures true glyph advances; this keeps gross-overflow
 * detection working for families that are neither vendored nor installed.
 *
 * Substring matching mirrors how decks request fonts by display name. Order
 * matters: "Noto Sans Mono" must match mono before sans, and the sans branch
 * must beat the serif branch when both substrings appear ("Noto Sans Serif").
 */
export function getCharWidthRatio(fontFamily: string, fontWeight: string): number {
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
 * Kept small on purpose — extend only when the renderer is told to use one
 * of these by the Design Direction Pass.
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
