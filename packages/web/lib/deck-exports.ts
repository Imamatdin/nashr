// Which export set the designer may show, and how to label it (ADR 0001).
// Exports are keyed by revision: only `current` is this version's own export.
// A fallback (same version, earlier renderer; or an earlier version) may be
// shown, but never without saying which kind of older it is.
import type { DeckAccessView, ExportLinks } from "./api";

export type ExportNotice = "renderNeeded" | "partial" | "olderRevision" | "olderRenderer";

export interface ShownExports {
  exports: ExportLinks | null;
  notice: ExportNotice | null;
  /** Required formats this version does not have yet (for a partial set). */
  missing: string[];
}

export function shownExports(deck: DeckAccessView): ShownExports {
  const missing = deck.missing_formats;
  if (deck.current !== null)
    return {
      exports: deck.current,
      notice: deck.state === "partial" ? "partial" : null,
      missing: deck.state === "partial" ? missing : [],
    };
  if (deck.fallback === null) return { exports: null, notice: "renderNeeded", missing };
  return {
    exports: deck.fallback,
    notice: deck.fallback.reason === "older_revision" ? "olderRevision" : "olderRenderer",
    missing,
  };
}
