// Which export set the designer may show, and how to label it (ADR 0001).
// Exports are keyed by revision: only `current` is this version's own export.
// A fallback (same version, earlier renderer; or an earlier version) may be
// shown, but never without saying which kind of older it is.
import type { DeckAccessView, ExportLinks } from "./api";

export type ExportNotice = "renderNeeded" | "olderRevision" | "olderRenderer";

export interface ShownExports {
  exports: ExportLinks | null;
  notice: ExportNotice | null;
}

export function shownExports(deck: DeckAccessView): ShownExports {
  if (deck.current !== null) return { exports: deck.current, notice: null };
  if (deck.fallback === null) return { exports: null, notice: "renderNeeded" };
  return {
    exports: deck.fallback,
    notice: deck.fallback.reason === "older_revision" ? "olderRevision" : "olderRenderer",
  };
}
