/**
 * Minimal ambient declaration for fontkit.
 *
 * fontkit 2.x ships no `.d.ts` and there is no `@types/fontkit`, so under
 * `moduleResolution: "bundler"` the bare `import` would raise TS7016. We
 * declare only the surface font-metrics.ts uses; the runtime module has far
 * more. Keep this in sync if the measurement code starts reaching for new
 * fontkit APIs.
 */
declare module 'fontkit' {
  export interface GlyphRun {
    /** Total advance width of the run, in font design units. */
    advanceWidth: number;
  }

  export interface Font {
    /** Design units per em (typically 1000 for the vendored TTFs). */
    unitsPerEm: number;
    /** Present on variable fonts; keys are axis tags ("wght", "wdth", ...). */
    variationAxes?: Record<string, unknown>;
    /** Shape `text` and return its glyph run. */
    layout(text: string): GlyphRun;
    /** Variable fonts only: return a new instance with the axes pinned. */
    getVariation?(settings: Record<string, number>): Font;
  }

  /**
   * Open a font file synchronously. A TrueType/OpenType collection (.ttc)
   * yields a different object without `layout`; callers must guard for that.
   */
  export function openSync(path: string): Font;
}
